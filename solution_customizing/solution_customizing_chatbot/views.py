from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .utils import (
    connect_to_postgres, execute_query, get_database_schema,
    setup_langchain_agent, process_user_input, analyze_sql_results
)

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
import uuid
import json

# Conversation views
@api_view(['GET'])
def conversation_list_by_user(request, user_id):
    """Fetch all conversations for a specific user_id."""
    try:
        connection = connect_to_postgres()
    except Exception as e:
        return JsonResponse({"error": f"Database connection failed: {str(e)}"}, status=500)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM solution_customizing.conversations WHERE user_id = %s AND is_archived = FALSE;
            """, (user_id,))
            rows = cursor.fetchall()
            conversations = [
                {
                    "conversation_id": row[0],
                    "role_id": row[1],
                    "user_id": row[2],
                    "started_at": row[3],
                    "updated_at": row[4],
                    "is_archived": row[5],
                }
                for row in rows
            ]
        return JsonResponse(conversations, safe=False, status=200)
    except Exception as e:
        return JsonResponse({"error": f"Failed to fetch conversations: {str(e)}"}, status=500)
    finally:
        connection.close()

@api_view(['POST'])
def create_conversation(request):
    """Create a new conversation."""
    try:
        connection = connect_to_postgres()
    except Exception as e:
        return JsonResponse({"error": f"Database connection failed: {str(e)}"}, status=500)

    data = request.data
    conversation_id = data.get('conversation_id', uuid.uuid4().hex)
    role_id = data.get('role_id')
    user_id = data.get('user_id')

    if not user_id:
        return JsonResponse({"error": "user_id is required"}, status=400)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO solution_customizing.conversations (conversation_id, role_id, user_id, started_at, updated_at, is_archived)
                VALUES (%s, %s, %s, NOW(), NULL, FALSE)
                RETURNING *;
            """, (conversation_id, role_id, user_id))
            new_conversation = cursor.fetchone()
            connection.commit()
            response = {
                "conversation_id": new_conversation[0],
                "role_id": new_conversation[1],
                "user_id": new_conversation[2],
                "started_at": new_conversation[3],
                "updated_at": new_conversation[4],
                "is_archived": new_conversation[5],
            }
        return JsonResponse(response, status=201)
    except Exception as e:
        return JsonResponse({"error": f"Failed to create conversation: {str(e)}"}, status=500)
    finally:
        connection.close()

@api_view(['PATCH'])
def archive_conversation(request, conversation_id):
    """Archive a specific conversation by setting is_archived to TRUE."""
    try:
        connection = connect_to_postgres()
    except Exception as e:
        return JsonResponse({"error": f"Database connection failed: {str(e)}"}, status=500)

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE solution_customizing.conversations
                SET is_archived = TRUE, updated_at = NOW()
                WHERE conversation_id = %s
                RETURNING *;
            """, (conversation_id,))
            archived_row = cursor.fetchone()
            if not archived_row:
                return JsonResponse({"error": "Conversation not found"}, status=404)
            connection.commit()
            archived_conversation = {
                "conversation_id": archived_row[0],
                "role_id": archived_row[1],
                "user_id": archived_row[2],
                "started_at": archived_row[3],
                "updated_at": archived_row[4],
                "is_archived": archived_row[5],
            }
        return JsonResponse({"status": "Conversation archived", "conversation": archived_conversation}, status=200)
    except Exception as e:
        return JsonResponse({"error": f"Failed to archive conversation: {str(e)}"}, status=500)
    finally:
        connection.close()

# Message views
@csrf_exempt
def message_list(request, conversation_id=None):
    """Handle GET and POST requests for messages."""
    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    try:
        connection = connect_to_postgres()
    except Exception as e:
        return JsonResponse({"error": f"Database connection failed: {str(e)}"}, status=500)

    if request.method == 'GET':  # Fetch messages for the given conversation_id
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM solution_customizing.messages WHERE conversation_id = %s;
                """, (conversation_id,))
                rows = cursor.fetchall()
                messages = [
                    {
                        "message_id": row[0],
                        "conversation_id": row[1],
                        "sender": row[2],
                        "message": row[3],
                        "created_at": row[4],
                        "intent": row[5],
                        "error": row[6],
                        "sql_query": row[7],
                    }
                    for row in rows
                ]
            return JsonResponse(messages, safe=False, status=200)
        except Exception as e:
            return JsonResponse({"error": f"Failed to fetch messages: {str(e)}"}, status=500)
        finally:
            connection.close()

    elif request.method == 'POST':  # Insert a new message into the messages table
        data = request.POST.copy()
        
        # Required fields validation
        if 'sender' not in data or 'message' not in data:
            return JsonResponse(
                {"error": "sender and message are required fields"}, 
                status=400
            )

        # Sender validation (CHECK constraint in DB)
        if data.get('sender') not in ['user', 'bot']:
            return JsonResponse(
                {"error": "sender must be either 'user' or 'bot'"}, 
                status=400
            )

        # Prepare message data with schema constraints
        message_data = {
            'message_id': data.get('message_id', uuid.uuid4().hex),
            'conversation_id': conversation_id,
            'sender': data.get('sender'),
            'message': data.get('message'),
            'intent': data.get('intent') or None,  # Convert empty string to None
            'error': bool(data.get('error', False)),  # Ensure boolean
            'sql_query': data.get('sql_query') or None  # Convert empty string to None
        }

        try:
            # Check if conversation exists
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT conversation_id FROM solution_customizing.conversations 
                    WHERE conversation_id = %s;
                """, (conversation_id,))
                if not cursor.fetchone():
                    return JsonResponse(
                        {"error": f"Conversation with id {conversation_id} does not exist"},
                        status=400
                    )

            # Insert message with schema-compliant data
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO solution_customizing.messages 
                    (message_id, conversation_id, sender, message, created_at, intent, error, sql_query)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s)
                    RETURNING *;
                """, (
                    message_data['message_id'],
                    message_data['conversation_id'],
                    message_data['sender'],
                    message_data['message'],
                    message_data['intent'],
                    message_data['error'],
                    message_data['sql_query']
                ))
                new_message = cursor.fetchone()
                connection.commit()
                
                response = {
                    "message_id": new_message[0],
                    "conversation_id": new_message[1],
                    "sender": new_message[2],
                    "message": new_message[3],
                    "created_at": new_message[4],
                    "intent": new_message[5],
                    "error": new_message[6],
                    "sql_query": new_message[7]
                }
            return JsonResponse(response, status=201)
        except Exception as e:
            return JsonResponse({"error": f"Failed to create message: {str(e)}"}, status=500)
        finally:
            connection.close()

@api_view(['POST'])
def handle_user_message(request, conversation_id):
    """
    Handle the complete flow of:
    1. Store user message
    2. Get chatbot response
    3. Store bot response
    """
    try:
        # Step 1: Store user message
        user_message_data = {
            'message_id': uuid.uuid4().hex,
            'conversation_id': conversation_id,
            'sender': 'user',
            'message': request.data.get('message'),
            'intent': None,
            'error': False,
            'sql_query': None
        }

        # Create a new request object for the user message
        user_message_request = type('Request', (), {
            'method': 'POST',
            'POST': user_message_data
        })()

        # Store user message
        user_message_response = message_list(user_message_request, conversation_id)
        if user_message_response.status_code != 201:
            return JsonResponse({"error": "Failed to store user message"}, status=500)

        # Step 2: Get chatbot response
        chatbot_request = type('Request', (), {
            'method': 'GET',
            'GET': {'message': request.data.get('message')}
        })()
        
        bot_response = chatbot(chatbot_request)
        if bot_response.status_code != 200:
            return JsonResponse({"error": "Failed to get chatbot response"}, status=500)

        bot_response_data = json.loads(bot_response.content)

        # Step 3: Store bot response
        bot_message_data = {
            'message_id': uuid.uuid4().hex,
            'conversation_id': conversation_id,
            'sender': 'bot',
            'message': bot_response_data.get('response'),
            'intent': None,
            'error': bool(bot_response_data.get('error', False)),
            'sql_query': bot_response_data.get('sql_query')
        }

        # Create a new request object for the bot message
        bot_message_request = type('Request', (), {
            'method': 'POST',
            'POST': bot_message_data
        })()

        # Store bot response
        bot_message_response = message_list(bot_message_request, conversation_id)
        if bot_message_response.status_code != 201:
            return JsonResponse({"error": "Failed to store bot response"}, status=500)

        # Return both messages
        return JsonResponse({
            "user_message": json.loads(user_message_response.content),
            "bot_message": json.loads(bot_message_response.content)
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "error": f"Error in handle_user_message: {str(e)}"
        }, status=500)

@csrf_exempt
def chatbot(request):
    """Django view to handle chatbot requests"""
    if request.method == 'GET':
        user_input = request.GET.get('message', '')
    else:
        return JsonResponse({"error": "Only GET requests are supported"}, status=400)

    # Connect and get schema
    connection = connect_to_postgres()
    if not connection:
        return JsonResponse({"error": "Database connection failed"}, status=500)
    db_schema = get_database_schema(connection)
    connection.close()

    # Set up LangChain agent (could be cached for performance)
    chain = setup_langchain_agent()
    json_response = process_user_input(user_input, chain, db_schema)
    final_response = {"response": json_response["answer"]}

    # Execute SQL query if present
    if json_response.get("sql_query") and json_response["sql_query"] not in [None, "None"]:
        connection = connect_to_postgres()
        if connection:
            try:
                result = execute_query(connection, json_response["sql_query"])
                if json_response["intent"] == "generate_sql" and result:
                    # Optionally analyze result
                    analysis = analyze_sql_results(result, user_input, chain)
                    final_response["response"] = analysis
                    final_response["data"] = result
                connection.close()
            except Exception as e:
                final_response["error"] = str(e)
    return JsonResponse(final_response, status=200)