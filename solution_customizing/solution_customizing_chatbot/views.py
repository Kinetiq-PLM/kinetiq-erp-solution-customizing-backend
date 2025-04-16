from django.forms import model_to_dict
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError
from rest_framework.decorators import api_view
import json
from datetime import datetime

from .models import Conversation, Message
from .utils import (
    connect_to_postgres, execute_query,
    setup_langchain_agent, process_user_input, analyze_sql_results, get_kinetiq_database_schema
)

# Conversation views
@api_view(['GET'])
def conversation_list_by_user(request, user_id):
    """Fetch all conversations for a specific user_id without the archived convos.
        - user_id (required in url)"""
    try:
        conversations = Conversation.objects.filter(
            user_id=user_id, 
            is_archived=False
        ).values(
            'conversation_id',
            'role_id',
            'user_id',
            'started_at',
            'updated_at',
            'is_archived'
        )
        return JsonResponse(list(conversations), safe=False, status=200)
    except Exception as e:
        return JsonResponse(
            {"error": f"Failed to fetch conversations: {str(e)}"}, 
            status=500
        )

@api_view(['POST'])
def create_conversation(request):
    """Create a new conversation.
        Needs 
        - user_id (required)
        - role_id (optional)
        - is_archived (optional, defaults to False)
    """
    data = request.data
    if not data.get('user_id'):
        return JsonResponse({"error": "user_id is required"}, status=400)

    try:
        # Get the current time
        now = datetime.now()
        
        conversation = Conversation.objects.create(
            # Use uuid.uuid4() directly if conversation_id is a UUIDField
            role_id=data.get('role_id'),
            user_id=data.get('user_id'),
            # Explicitly set started_at and updated_at to the current time
            started_at=now,
            updated_at=now
            # is_archived defaults to False based on the model definition (usually)
        )
        
        # Prepare the response data including the timestamps
        response = {
            "conversation_id": conversation.conversation_id,
            "role_id": conversation.role_id,
            "user_id": conversation.user_id,
            "started_at": conversation.started_at.isoformat(), # Format for JSON
            "updated_at": conversation.updated_at.isoformat(), # Format for JSON
            "is_archived": conversation.is_archived,
        }
        return JsonResponse(response, status=201)
    except Exception as e:
        # Consider logging the error e
        return JsonResponse(
            {"error": f"Failed to create conversation: {str(e)}"}, 
            status=500
        )

@api_view(['PATCH'])
def archive_conversation(request, conversation_id):
    """Archive a specific conversation.
        -conversation_id (required in url)"""
    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)
        conversation.is_archived = True
        conversation.updated_at = datetime.now()
        conversation.save()

        response = {
            "conversation_id": conversation.conversation_id,
            "role_id": conversation.role_id,
            "user_id": conversation.user_id,
            "started_at": conversation.started_at,
            "updated_at": conversation.updated_at,
            "is_archived": conversation.is_archived,
        }
        return JsonResponse(
            {"status": "Conversation archived", "conversation": response}, 
            status=200
        )
    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        return JsonResponse(
            {"error": f"Failed to archive conversation: {str(e)}"}, 
            status=500
        )

# Message views
@csrf_exempt # Keep csrf_exempt if this view might be called from non-browser clients without CSRF tokens
def load_messages(request, conversation_id):
    """Handle GET requests for messages using Django ORM.
        - conversation_id (required in url)"""
    if request.method != 'GET':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    try:
        # Use Django ORM to filter messages by conversation_id
        messages_queryset = Message.objects.filter(conversation_id=conversation_id).order_by('created_at')

        # Check if any messages were found
        if not messages_queryset.exists():
            # Return an empty list if no messages are found for the conversation
            return JsonResponse([], safe=False, status=200)

        # Serialize the queryset to a list of dictionaries
        messages_list = [
            {
                "message_id": msg.message_id,
                "conversation_id": str(msg.conversation_id), # Ensure UUID is serialized correctly if needed
                "sender": msg.sender,
                "message": msg.message,
                "created_at": msg.created_at.isoformat(), # Format datetime for JSON
                "intent": msg.intent,
                "error": msg.error,
                "sql_query": msg.sql_query,
            }
            for msg in messages_queryset
        ]
        return JsonResponse(messages_list, safe=False, status=200)
    except Message.DoesNotExist:
        # This case might not be strictly necessary with filter().exists() check,
        # but good practice for specific object lookups.
        return JsonResponse({"error": "Messages not found for this conversation"}, status=404)
    except Exception as e:
        # Catch other potential errors during ORM query or serialization
        return JsonResponse({"error": f"Failed to fetch messages: {str(e)}"}, status=500)

@csrf_exempt
def create_message(request, conversation_id):
    """Handle POST requests to create a new message using Django ORM.
        - conversation_id (required in url)
        - sender (required, either 'user' or 'bot') in body of request
        - message (required) in body of request"""
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    # Determine how data is sent (form data or JSON)
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            # Assume form data if not JSON
            data = request.POST.copy()
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON data"}, status=400)

    # Required fields validation
    sender = data.get('sender')
    message_text = data.get('message') # Renamed to avoid conflict with model name

    if not sender or not message_text:
        return JsonResponse(
            {"error": "sender and message are required fields"},
            status=400
        )

    # Sender validation (can also be handled by model choices)
    if sender not in ['user', 'bot']:
        return JsonResponse(
            {"error": "sender must be either 'user' or 'bot'"},
            status=400
        )

    try:
        # Check if conversation exists using ORM
        try:
            conversation = Conversation.objects.get(conversation_id=conversation_id)
        except Conversation.DoesNotExist:
            return JsonResponse(
                {"error": f"Conversation with id {conversation_id} does not exist"},
                status=404 # Use 404 for resource not found
            )

        # Create message object using ORM
        new_message = Message.objects.create(
            # message_id is likely auto-generated by the model (UUIDField(primary_key=True, default=uuid.uuid4))
            # If not, generate it: message_id=data.get('message_id', uuid.uuid4().hex),
            conversation=conversation, # Link to the conversation object
            sender=sender,
            message=message_text,
            intent=data.get('intent') or None,
            error=bool(data.get('error', False)),
            sql_query=data.get('sql_query') or None
            # created_at is likely auto_now_add=True in the model
        )

        # --- Update Conversation Timestamp ---
        # Set the conversation's updated_at to the current time
        conversation.updated_at = datetime.now() # Use timezone.now() for timezone awareness
        conversation.save(update_fields=['updated_at']) # Efficiently save only the updated field
        # --- End Update ---


        # Serialize the new message object for the response
        response_data = model_to_dict(new_message)
        response_data['conversation_id'] = str(new_message.conversation.conversation_id)
        if 'created_at' in response_data and hasattr(response_data['created_at'], 'isoformat'):
            response_data['created_at'] = response_data['created_at'].isoformat()

        return JsonResponse(response_data, status=201)

    except ValidationError as e:
         return JsonResponse({"error": e.message_dict}, status=400)
    except Exception as e:
        # Log the error for debugging
        print(f"Error creating message or updating conversation: {e}") 
        return JsonResponse({"error": f"Failed to create message: {str(e)}"}, status=500)


@csrf_exempt
def chatbot(request):
    """Django view to handle chatbot requests
        - GET request with 'message' query parameter"""
    if request.method == 'GET':
        user_input = request.GET.get('message', '')
        if not user_input:
             return JsonResponse({"error": "message query parameter is required"}, status=400)
    else:
        return JsonResponse({"error": "Only GET requests are supported"}, status=405) # Use 405 Method Not Allowed

    try:
        # Get the comprehensive schema using the utility function
        db_schema = get_kinetiq_database_schema()

        # Set up LangChain agent (could be cached for performance)
        chain = setup_langchain_agent() # Assuming this function doesn't need a connection object
        json_response = process_user_input(user_input, chain, db_schema)
        final_response = {"response": json_response.get("answer", "No answer generated.")} # Use .get for safety

        # Execute SQL query if present
        sql_query = json_response.get("sql_query")
        if sql_query and sql_query.strip() and sql_query.lower() != "none":
            connection = connect_to_postgres() # Connect only if executing SQL
            if not connection:
                 # Log this error internally
                 print("Error: Database connection failed during SQL execution.")
                 # Optionally add error info to response, but might expose details
                 # final_response["error"] = "Database connection failed during SQL execution."
            else:
                try:
                    result = execute_query(connection, sql_query)
                    # Add data only if query execution was successful and returned results
                    if result is not None: # Check if execute_query returned something meaningful
                         final_response["data"] = result
                         # Optionally analyze result if intent matches
                         if json_response.get("intent") == "generate_sql":
                              analysis = analyze_sql_results(result, user_input, chain)
                              final_response["response"] = analysis # Overwrite initial response with analysis

                except Exception as e:
                    print(f"Error executing SQL query: {e}") # Log the specific SQL error
                    final_response["sql_error"] = f"Error executing generated SQL: {str(e)}" # Add specific SQL error info
                finally:
                     if connection:
                          connection.close() # Ensure connection is closed

        return JsonResponse(final_response, status=200)

    except Exception as e:
         # Catch errors from get_kinetiq_database_schema, setup_langchain_agent, process_user_input
         print(f"Error in chatbot view: {e}") # Log the general error
         return JsonResponse({"error": f"An unexpected error occurred: {str(e)}"}, status=500)

@api_view(['GET'])
def get_database_info(request):
    """Endpoint to get complete database schema information."""
    try:
        schema_info = get_kinetiq_database_schema()
        return JsonResponse({
            'status': 'success',
            'schema': schema_info
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)