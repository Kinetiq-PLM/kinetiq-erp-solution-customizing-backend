from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .utils import (
    connect_to_postgres, execute_query, get_database_schema,
    setup_langchain_agent, process_user_input, analyze_sql_results
)

# Initialize AI client

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