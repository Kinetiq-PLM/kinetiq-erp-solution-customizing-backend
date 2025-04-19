from django.forms import model_to_dict
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError
from rest_framework.decorators import api_view
import json
from datetime import datetime

from .models import Conversation, Message, User
from .utils import (
    connect_to_postgres, execute_query,
    setup_langchain_agent, process_user_input, analyze_sql_results,
    title_generation_chain,
    get_kinetiq_database_schema
)


@api_view(['GET'])
def get_user_details(request, employee_id):
    """Fetch user details by user_id."""
    try:
        user = User.objects.get(employee_id=employee_id)
        # Return only the necessary fields
        user_data = {
            'user_id': user.user_id,
            'employee_id': user.employee_id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            # Add other fields if needed, e.g., role
            # 'role_id': user.role.role_id if user.role else None
        }
        return JsonResponse(user_data, status=200)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)
    except Exception as e:
        # Log the error e
        print(f"Error fetching user details: {e}")
        return JsonResponse({"error": f"Failed to fetch user details: {str(e)}"}, status=500)


# Conversation views
@api_view(['GET'])
def conversation_list_by_user(request, employee_id):
    """Fetch all conversations for a specific employee_id without the archived convos.
        - employee_id (required in url)"""
    try:
        conversations = Conversation.objects.filter(
            employee_id=employee_id, 
            is_archived=False
        ).values(
            'conversation_id',
            'conversation_title',
            'employee_id',
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
        - employee_id (required)
        - role_id (optional)
        - is_archived (optional, defaults to False)
    """
    data = request.data
    employee_id_str = data.get('employee_id')
    
    if not employee_id_str:
        return JsonResponse({"error": "employee_id is required"}, status=400)

    user_instance = None
    try:
        user_instance = User.objects.get(employee_id=employee_id_str)
    except User.DoesNotExist:
        # Decide how to handle: error out or allow conversation without linked user?
        # Model allows null=True, so we can proceed with user_instance = None
        print(f"Warning: User with employee_id '{employee_id_str}' not found. Creating conversation without user link.")
        # If you want to prevent creation without a valid user, uncomment the next line:
        # return JsonResponse({"error": f"User with employee_id '{employee_id_str}' not found"}, status=404)
    except Exception as e:
        print(f"Error fetching user for employee_id {employee_id_str}: {e}")
        return JsonResponse({"error": f"Failed to verify user: {str(e)}"}, status=500)


    try:
        now = timezone.now()
        
        conversation = Conversation.objects.create(
            # Use uuid.uuid4() directly if conversation_id is a UUIDField
            conversation_title=None,
            employee_id=user_instance,
            # Explicitly set started_at and updated_at to the current time
            started_at=now,
            updated_at=now
            # is_archived defaults to False based on the model definition (usually)
        )
        
        # Prepare the response data including the timestamps
        response = {
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            # --- Extract the employee_id string from the User object ---
            # --- Handle case where employee_id (User instance) might be None ---
            "employee_id": conversation.employee_id.employee_id if conversation.employee_id else None,
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
        conversation.save(update_fields=['is_archived'])

        response_data = {
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            # --- Extract employee_id string, handle None ---
            "employee_id": conversation.employee_id.employee_id if conversation.employee_id else None,
            # --- Format datetimes to ISO strings ---
            "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            "is_archived": conversation.is_archived,
        }
        return JsonResponse(
            {"status": "Conversation archived", "conversation": response_data}, 
            status=200
        )
    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        print(f"Error archiving conversation: {e}")
        return JsonResponse(
            {"error": f"Failed to archive conversation: {str(e)}"}, 
            status=500
        )

# --- Message views ---
# load_messages needs to return role_id
@api_view(['GET']) # Use @api_view for consistency
def load_messages(request, conversation_id):
    """Handle GET requests for messages using Django ORM.
        - conversation_id (required in url)"""
    if request.method != 'GET':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    try:
        # Use Django ORM to filter messages by conversation_id
        messages_queryset = Message.objects.select_related('role_id').filter(conversation_id=conversation_id).order_by('created_at')

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
                "role_id": msg.role_id.role_id if msg.role_id else None,
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

# create_message needs to fetch and add role_id
@api_view(['POST'])
def create_message(request, conversation_id):
    """Handle POST requests to create a new message using Django ORM.
        - conversation_id (required in url)
        - sender (required, either 'user' or 'bot') in body of request
        - message (required) in body of request"""

    # Removed method check as @api_view handles it for POST

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    # Determine how data is sent (form data or JSON)
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            # Fallback or specific handling for form data if needed
            # For simplicity, assuming JSON for now based on frontend likely usage
            data = request.data # Use request.data with DRF @api_view
            # data = request.POST.copy() # If strictly using forms
    except json.JSONDecodeError:
        # request.data handles JSON parsing with DRF, so this might be less needed
        return JsonResponse({"error": "Invalid JSON data"}, status=400)
    except Exception as e:
         # Catch potential errors if request.data fails
         print(f"Error parsing request data: {e}")
         return JsonResponse({"error": "Could not parse request data"}, status=400)


    sender = data.get('sender')
    message_text = data.get('message')

    if not sender or not message_text:
        return JsonResponse({"error": "sender and message are required fields"}, status=400)
    if sender not in ['user', 'bot']:
        return JsonResponse({"error": "sender must be either 'user' or 'bot'"}, status=400)

    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)

        # --- Logic to determine if title should be generated/updated ---
        should_generate_title = False
        first_user_message_text = None

        # Check only when the BOT is sending a message
        if sender == 'bot' and not conversation.conversation_title:
            # Check if this is the FIRST bot message being added
            if not Message.objects.filter(conversation=conversation, sender='bot').exists():
                # Try to get the first user message for context
                first_user_message = Message.objects.filter(
                    conversation=conversation, sender='user'
                ).order_by('created_at').first()

                if first_user_message:
                    should_generate_title = True
                    first_user_message_text = first_user_message.message
        # --- End title generation check ---

        # --- Get User Role INSTANCE ---
        user_role_instance = None # Initialize as None
        if conversation.employee_id: # Check if conversation has an associated user
            try:
                # Fetch user based on employee_id from conversation
                # Ensure the User model has a 'role' ForeignKey to RolePerm
                user = User.objects.select_related('role').get(employee_id=conversation.employee_id.employee_id) # Access employee_id string field
                if hasattr(user, 'role') and user.role: # Check if role relationship exists and is not None
                    user_role_instance = user.role # <-- Get the RolePerm instance
                else:
                     print(f"User {user.employee_id} found but has no associated role.")
            except User.DoesNotExist:
                # User linked to conversation doesn't exist in User table (data integrity issue?)
                print(f"Warning: User with employee_id {conversation.employee_id.employee_id} (from conversation) not found in User table.")
            except AttributeError:
                 # This might happen if the User model doesn't have a 'role' field defined correctly
                 print(f"Warning: User model for {conversation.employee_id.employee_id} might not have a 'role' attribute or it's misconfigured.")
            except Exception as e:
                 # Catch other potential errors during user/role lookup
                 print(f"Error fetching user/role for employee_id {conversation.employee_id.employee_id}: {e}")
        # --- End Get User Role INSTANCE ---


        # Create message object
        new_message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            # --- Assign the RolePerm instance ---
            role_id=user_role_instance, # Assign the fetched RolePerm instance (can be None)
            message=message_text,
            intent=data.get('intent'), # Get intent if provided
            error=data.get('error', False), # Get error flag if provided
            sql_query=data.get('sql_query') # Get sql_query if provided
        )

        # --- Generate Title with LangChain (if needed) & Update Conversation ---
        update_fields = ['updated_at'] # Always update timestamp because a message was added
        generated_title = None

        # --- Use the imported chain ---
        if should_generate_title and title_generation_chain and first_user_message_text:
            try:
                print(f"Attempting to generate title for convo {conversation_id}...")
                # Invoke the chain with context
                generated_title = title_generation_chain.invoke({
                    "user_message": first_user_message_text,
                    "bot_message": message_text # The bot message being saved now
                })
                generated_title = generated_title.strip().strip('"') # Clean up output

                if generated_title: # Check if LLM returned something
                    print(f"Generated title: {generated_title}")
                    conversation.conversation_title = generated_title[:255] # Truncate if needed for model field length
                    update_fields.append('conversation_title')
                else:
                    print("LLM returned empty title, skipping title update.")

            except Exception as llm_error:
                # Log the error but don't stop the message creation process
                print(f"Error generating title with LangChain/Gemini: {llm_error}")
                # Continue without updating the title

        # Save the conversation - auto_now=True handles updated_at automatically
        # Only save fields that were actually changed for efficiency
        conversation.save(update_fields=update_fields)
        # --- End Update ---

        # Serialize the new message object for the response
        response_data = {
            "message_id": new_message.message_id,
            "conversation_id": new_message.conversation.conversation_id, # Access via the instance
            "sender": new_message.sender,
            # --- Get role_id string from the instance for the response ---
            "role_id": new_message.role_id.role_id if new_message.role_id else None,
            "message": new_message.message,
            "created_at": new_message.created_at.isoformat(), # Format datetime
            "intent": new_message.intent,
            "error": new_message.error,
            "sql_query": new_message.sql_query,
            "conversation_title": conversation.conversation_title
            # Optionally include generated title in response if needed by frontend
            # "generated_title": generated_title if 'conversation_title' in update_fields else None
        }
        return JsonResponse(response_data, status=201) # 201 Created status

    except Conversation.DoesNotExist:
         # If the conversation_id provided in the URL doesn't exist
         return JsonResponse({"error": f"Conversation with id {conversation_id} does not exist"}, status=404)
    except Exception as e:
        # Catch-all for other unexpected errors during message creation or conversation update
        print(f"Error creating message or updating conversation {conversation_id}: {e}")
        # Consider more specific logging here
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
        # db_schema = get_kinetiq_database_schema()
        db_schema = {}
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
        # schema_info = get_kinetiq_database_schema()
        schema_info = {}
        return JsonResponse({
            'status': 'success',
            'schema': schema_info
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)