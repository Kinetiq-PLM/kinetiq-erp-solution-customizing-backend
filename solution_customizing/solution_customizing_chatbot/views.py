from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from google import genai
import google.generativeai as genai
from django.conf import settings
from .utils import (
    connect_to_postgres, execute_query, 
    analyze_response, generate_ai_prompt, 
    process_ai_response
)

# Initialize AI client

@csrf_exempt
def chatbot(request):
    """Django view to handle chatbot requests"""
    if request.method == 'GET':
        user_input = request.GET.get('message', '')
    else:
        return JsonResponse({"error": "Only GET requests are supported"}, status=400)
    
    genai.configure(api_key=settings.AI_CONFIG["api_key"])
    models = genai.GenerativeModel(settings.AI_CONFIG["model"])
    
    
    # Generate AI response
    response = models.generate_content(
        contents=generate_ai_prompt(settings.DATABASE_SCHEMA, user_input)
    )
    
    # Process response
    json_response = process_ai_response(response.text)
    # Handle different intents
    final_response = {"response": json_response["answer"]}
    
    # Execute SQL query if present
    if json_response["sql_query"] != "None":
        connection = connect_to_postgres()              # this runs
        if connection:
            try:
                result = execute_query(connection, json_response["sql_query"])          # sql execute
                # Add analysis if generate_sql intent
                if json_response["intent"] == "generate_sql" and result:
                    analysis = analyze_response(result, user_input, models)
                    final_response["response"] = analysis
                    final_response["data"] = result
                connection.close()
            except Exception as e:
                final_response["error"] = str(e)
    return JsonResponse(final_response, status=200)