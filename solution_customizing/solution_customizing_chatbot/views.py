import traceback
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework import status
import json


from .models import Conversation, Message, User
from .utils import (
    execute_query,
    process_user_input, analyze_sql_results,
    title_generation_chain,
    AGENT_CHAIN,
    LLM_INSTANCE
)


@api_view(['GET'])
def get_user_details(request, employee_id):
    """
    /chatbot/load_user_details/<str:employee_id>/
    Fetch user details by user_id.
        - employee_id (required in url)
        - Returns user_id, employee_id, first_name, last_name
        - NEW: returns role_name, role_description
    """
    try:
        user = User.objects.select_related('role').get(employee_id=employee_id)
        user_data = {
            'user_id': user.user_id,
            'employee_id': user.employee_id,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role_name': user.role.role_name if user.role else None,
            'role_description': user.role.description if user.role else None,
        }
        return JsonResponse(user_data, status=200)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)
    except Exception as e:
        print(f"Error fetching user details: {e}")
        return JsonResponse({"error": f"Failed to fetch user details: {str(e)}"}, status=500)


@api_view(['GET'])
def conversation_list_by_user(request, employee_id):
    """
    /chatbot/load_conversations/<str:employee_id>/
    Fetch all conversations for a specific employee_id without the archived convos.
        - employee_id (required in url)
        - Returns conversation_id, conversation_title, updated_at, is_archived
        - NEW: removed returning employee_id, started_at from the response
    """
    try:
        conversations = Conversation.objects.filter(
            employee_id=employee_id, 
            is_archived=False
        ).values(
            'conversation_id',
            'conversation_title',
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
    """
    /chatbot/create_conversation/
    Create a new conversation.
        - employee_id (required in request body)
        - Returns conversation_id, conversation_title, employee_id, started_at, updated_at, is_archived
    """
    data = request.data
    employee_id_str = data.get('employee_id')

    if not employee_id_str:
        return JsonResponse({"error": "employee_id is required"}, status=400)

    user_instance = None
    try:
        user_instance = User.objects.get(employee_id=employee_id_str)
    except User.DoesNotExist:
        return JsonResponse({"error": f"User with employee_id '{employee_id_str}' not found"}, status=404)
    except Exception as e:
        print(f"Error fetching user for employee_id {employee_id_str}: {e}")
        return JsonResponse({"error": f"Failed to verify user: {str(e)}"}, status=500)

    try:
        now = timezone.now()

        conversation = Conversation.objects.create(
            conversation_title=None,
            employee_id=user_instance,
            started_at=now,
            updated_at=now
        )

        response_data = {
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            "employee_id": conversation.employee_id.employee_id if conversation.employee_id else None,
            "started_at": conversation.started_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "is_archived": conversation.is_archived,
        }
        return JsonResponse(response_data, status=201)
    except Exception as e:
        print(f"Error creating conversation: {e}")
        return JsonResponse(
            {"error": f"Failed to create conversation: {str(e)}"},
            status=500
        )

@api_view(['PATCH'])
def archive_conversation(request, conversation_id):
    """
    /chatbot/archive_conversation/<str:conversation_id>/
    Archive a specific conversation.
        - conversation_id (required in url)
        - Returns only a success/error status message
    """
    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)
        
        # Check if already archived to avoid unnecessary save
        if conversation.is_archived:
            return JsonResponse(
                {"status": "Conversation already archived", "conversation_id": conversation_id}, status=200
            )
        conversation.is_archived = True
        conversation.save(update_fields=['is_archived'])

        return JsonResponse(
            {"status": "Conversation archived", "conversation_id": conversation_id}, 
            status=200
        )
    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        print(f"Error archiving conversation {conversation_id}: {e}")
        return JsonResponse(
            {"error": f"Failed to archive conversation: {str(e)}"}, 
            status=500
        )
    
@api_view(['POST'])
def generate_conversation_title(request, conversation_id):
    """
    /chatbot/generate_title/<str:conversation_id>/
    Explicitly generates or regenerates a title for a given conversation
    based on the first user and bot messages.
    """
    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required in URL"}, status=status.HTTP_400_BAD_REQUEST)

    if not title_generation_chain:
        return JsonResponse({"error": "Title generation feature not initialized."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)

        # Fetch the first user message
        first_user_message = Message.objects.filter(
            conversation=conversation, sender='user'
        ).order_by('created_at').first()

        # Fetch the first bot message
        first_bot_message = Message.objects.filter(
            conversation=conversation, sender='bot'
        ).order_by('created_at').first()

        if not first_user_message or not first_bot_message:
            return JsonResponse(
                {"error": "Cannot generate title: Initial user or bot message missing."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Invoke the title generation chain
        try:
            title_result = title_generation_chain.invoke({
                "user_message": first_user_message.message,
                "bot_message": first_bot_message.message
            })
            # Assuming the chain returns a string directly or an object with a 'content' attribute
            title = title_result.content if hasattr(title_result, 'content') else str(title_result)

        except Exception as llm_err:
            print(f"Error invoking title generation chain for {conversation_id}: {llm_err}")
            return JsonResponse({"error": f"Failed to generate title via LLM: {llm_err}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if title:
            cleaned_title = title.strip().strip('"') # Clean up output
            if cleaned_title:
                conversation.conversation_title = cleaned_title[:255] # Truncate if needed
                conversation.updated_at = timezone.now() # Update timestamp
                conversation.save(update_fields=['conversation_title', 'updated_at'])
                print(f"Generated/Updated title for {conversation_id}: {conversation.conversation_title}")
                return JsonResponse({
                    "status": "Title generated successfully",
                    "conversation_id": conversation_id,
                    # --- Use conversation_title ---
                    "title": conversation.conversation_title
                }, status=status.HTTP_200_OK)
        else:
            return JsonResponse({
                "status": "Title generation returned no result.",
                "conversation_id": conversation_id,
            }, status=status.HTTP_200_OK) # Success, but no title generated

    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(f"Error in generate_conversation_title view for {conversation_id}: {e}\n{traceback.format_exc()}")
        return JsonResponse({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def load_messages(request, conversation_id):
    """
    /chatbot/load_messages/<str:conversation_id>/
    Handle GET requests for messages.
        - conversation_id (required in url)
        - Returns a list of messages for the conversation
        - Each message includes message_id, conversation_id, sender, role_id, message, created_at, intent, error, sql_query
    """
    if request.method != 'GET':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    try:
        # Fetch the conversation object itself to easily get the count later
        conversation = Conversation.objects.get(conversation_id=conversation_id)

        # Fetch the messages related to this conversation
        messages_queryset = Message.objects.select_related('role_id').filter(
            conversation=conversation # Filter by conversation instance
        ).order_by('created_at')

        # Get the total count of messages for this conversation
        message_count = messages_queryset.count() # Efficiently count the filtered messages

        # Serialize the queryset to a list of dictionaries
        messages_list = [
            {
                "message_id": msg.message_id,
                "conversation_id": str(msg.conversation_id), # Use conversation_id from message instance
                "sender": msg.sender,
                "role_id": msg.role_id.role_id if msg.role_id else None,
                "message": msg.message,
                "created_at": msg.created_at.isoformat(),
                "intent": msg.intent,
                "error": msg.error,
                "sql_query": msg.sql_query,
            }
            for msg in messages_queryset
        ]

        # --- Prepare the response payload including the count ---
        response_data = {
            "messages": messages_list,
            "message_count": message_count
        }

        return JsonResponse(response_data, safe=False, status=200) # safe=False because top level is dict

    except Conversation.DoesNotExist:
         # Handle case where the conversation itself doesn't exist
         return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        print(f"Error fetching messages or count for {conversation_id}: {e}") # Added print
        return JsonResponse({"error": f"Failed to fetch messages: {str(e)}"}, status=500)

@api_view(['POST'])
def create_message(request, conversation_id):
    """
    /chatbot/create_message/<str:conversation_id>/
    Handle POST requests to create a new message using Django ORM.
        - conversation_id (required in url)
        - sender (required, either 'user' or 'bot') in body of request
        - message (required) in body of request
    """

    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required"}, status=400)

    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.data
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON data"}, status=400)
    except Exception as e:
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

@api_view(['PATCH'])
def update_conversation_title(request, conversation_id):
    """
    /chatbot/update_title/<str:conversation_id>/
    Update the title of a specific conversation.
        - conversation_id (required in url)
        - title (required in request body/ this is the new updated title)
        - Returns only a success/error status message
    """
    if not conversation_id:
        return JsonResponse({"error": "conversation_id parameter is required in URL"}, status=400)

    data = request.data
    new_title = data.get('title')

    if not new_title:
        return JsonResponse({"error": "JSON body must contain a 'title' field"}, status=400)

    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)

        conversation.conversation_title = new_title[:255] # Truncate if needed
        conversation.updated_at = timezone.now()

        conversation.save(update_fields=['conversation_title', 'updated_at'])

        return JsonResponse(
            {"status": "Conversation title updated", "conversation_id": conversation_id},
            status=200
        )

    except Conversation.DoesNotExist:
        return JsonResponse({"error": "Conversation not found"}, status=404)
    except Exception as e:
        print(f"Error updating title for conversation {conversation_id}: {e}")
        return JsonResponse(
            {"error": f"Failed to update conversation title: {str(e)}"},
            status=500
        )

@csrf_exempt
@api_view(['POST'])
def chatbot(request):
    """
    /chatbot/respond/
    Handles user messages, generates SQL if needed, executes it,
    analyzes results, and returns a response.
    Handles SQL execution errors naturally.
    Saves both user and bot messages.
    """
    data = request.data
    user_input = data.get('message')
    conversation_id = data.get('conversation_id')
    employee_id = data.get('employee_id')

    if not user_input or not conversation_id or not employee_id:
        return JsonResponse({"error": "Missing message, conversation_id, or employee_id"}, status=status.HTTP_400_BAD_REQUEST)

    if not AGENT_CHAIN or not LLM_INSTANCE:
        return JsonResponse({"error": "Chatbot agent not initialized."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    try:
        # --- 1. Fetch User with Role and Conversation ---
        try:
            # --- Use select_related to fetch the role object efficiently ---
            user = User.objects.select_related('role').get(employee_id=employee_id)
            conversation = Conversation.objects.get(conversation_id=conversation_id)

            # --- Check if user has a role assigned ---
            if not user.role:
                print(f"Warning: User {employee_id} does not have a role assigned.")
                user_role_instance = None
            else:
                user_role_instance = user.role # Get the RolePerm instance

        except User.DoesNotExist:
            return JsonResponse({"error": f"User with employee_id {employee_id} not found."}, status=status.HTTP_404_NOT_FOUND)
        except Conversation.DoesNotExist:
            return JsonResponse({"error": f"Conversation with id {conversation_id} not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Error fetching user or conversation: {e}\n{traceback.format_exc()}")
            return JsonResponse({"error": f"Error accessing user/conversation data: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # --- 2. Save User Message ---
        try:
            user_message = Message.objects.create(
                conversation=conversation,
                sender='user',
                message=user_input,
                role_id=user_role_instance
            )
            print(f"User message {user_message.message_id} saved.")
        except Exception as e:
            print(f"Error saving user message: {e}\n{traceback.format_exc()}")
            return JsonResponse({"error": f"Error saving user message: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # --- 3. Process User Input with LLM (Intent, Initial Answer, SQL) ---
        llm_response_data = process_user_input(user_input, conversation_id) # Pass only needed args

        if llm_response_data.get("intent") == "error":
            return JsonResponse({"response": llm_response_data.get("answer", "An error occurred."), "sql_error": llm_response_data.get("answer")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        intent = llm_response_data.get("intent")
        initial_answer = llm_response_data.get("answer", "...") # Default answer
        sql_query = llm_response_data.get("sql_query")

        final_response_text = initial_answer
        sql_results_data = None
        sql_error_message = None
        bot_message_type = 'text' # Default type

        # --- 4. Execute SQL if applicable ---
        if intent == "generate_sql" and sql_query:
            print(f"Executing SQL for conversation {conversation_id}: {sql_query}")
            sql_results = execute_query(sql_query)
            technical_error = sql_results.get("error")

            if technical_error:
                # --- 4a. Handle SQL Execution Error ---
                print(f"SQL Error for conversation {conversation_id}: {technical_error}")
                sql_error_message = technical_error # Store technical error

                try:
                    error_explanation_prompt = f"""The user asked: '{user_input}'.
                    I tried to run the SQL query: '{sql_query}'.
                    However, it failed with the following database error: '{technical_error}'.

                    Please explain this failure to the user in simple, natural language (1-2 sentences).
                    Suggest they might need to rephrase their request or that there might be an issue with the query generation.
                    Do not include the SQL query or the exact technical error details in your explanation itself.
                    Respond only with the natural language explanation."""

                    error_explanation_response = LLM_INSTANCE.invoke(error_explanation_prompt)
                    final_response_text = error_explanation_response.content.strip() if hasattr(error_explanation_response, 'content') else str(error_explanation_response).strip()

                except Exception as llm_err:
                    print(f"Error getting LLM explanation for SQL error: {llm_err}")
                    final_response_text = f"Sorry, I encountered an error trying to run the database query. Please check your request or try again."

            else:
                # --- 4b. Process Successful SQL Results ---
                print(f"SQL executed successfully for conversation {conversation_id}.")
                # Use analyze_sql_results or the initial answer
                # If analyze_sql_results is desired:
                analysis_answer = analyze_sql_results(sql_results, user_input, conversation_id)
                final_response_text = analysis_answer

                # If you just want the initial answer before the table:
                # final_response_text = initial_answer # Already set

                # Prepare data for frontend table display
                if sql_results.get("rows"):
                    sql_results_data = {
                        "headers": sql_results.get("headers", []),
                        "rows": sql_results.get("rows", [])
                    }
                    bot_message_type = 'table' # Mark as table type if rows exist
                else:
                    # If query ran but returned no rows, use the initial answer
                    final_response_text = initial_answer + " (No matching data found)."


        # --- 5. Save Bot Message ---
        try:
            bot_message_content = final_response_text
            db_sql_query_field = sql_query # Store original query by default

            # --- Activate this block ---
            if bot_message_type == 'table' and sql_results_data:
                try:
                    db_sql_query_field = f"[TABLE_DATA]:[{json.dumps(sql_results_data)}]"
                    print(f"Storing table data in sql_query field for message.")
                except Exception as json_err:
                    print(f"Error serializing table data for storage: {json_err}")
                    db_sql_query_field = sql_query

            bot_message = Message.objects.create(
                conversation=conversation,
                sender='bot',
                message=bot_message_content,
                role_id=user_role_instance,
                intent=intent,
                sql_query=db_sql_query_field,
                error=sql_error_message
            )
            print(f"Bot message {bot_message.message_id} saved.")
            bot_message_id = bot_message.message_id
        except Exception as e:
            print(f"Error saving bot message: {e}\n{traceback.format_exc()}")
            bot_message_id = None


        # --- 5. Prepare and Return JsonResponse to Frontend ---
        response_payload = {
            "message_id": bot_message_id, # Include the saved bot message ID
            "response": final_response_text,
            "data": sql_results_data, # Contains headers/rows if successful query with results
            "sql_query": sql_query, # The original SQL query attempted
            "sql_error": sql_error_message, # Technical error message if execution failed
            "intent": intent,
            "type": bot_message_type # Let frontend know if it's text or table
        }

        # --- 6. Generate Title for New Conversations (Optional) ---
        # Check if it's the first exchange (e.g., only 2 messages now)
        if conversation.message_set.count() <= 2 and title_generation_chain:
             try:
                title = title_generation_chain.invoke({
                    "user_message": user_input,
                    "bot_message": final_response_text
                })
                if title:
                    conversation.title = title[:255] # Truncate if needed
                    conversation.save(update_fields=['title'])
                    response_payload['conversation_title'] = conversation.title # Send updated title back
                    print(f"Generated title for {conversation_id}: {title}")
             except Exception as title_err:
                print(f"Error generating title for {conversation_id}: {title_err}")


        return JsonResponse(response_payload, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"Unhandled error in chatbot view: {e}")
        return JsonResponse({"error": f"An unexpected error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)