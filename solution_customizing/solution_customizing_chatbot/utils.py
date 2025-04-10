import json
import psycopg2
import google.generativeai as genai
from google.generativeai import types
from django.conf import settings

# yung settings is for  the psycopg2.connect()

def connect_to_postgres():
    """Establish connection to PostgreSQL database"""
    try:
        db_config = settings.DATABASES['default']
        connection = psycopg2.connect(
            dbname=db_config['NAME'],
            user=db_config['USER'],
            password=db_config['PASSWORD'],
            host=db_config['HOST'],
            port=db_config['PORT']
        )
        print("Connected to PostgreSQL database!")
        return connection
    except Exception as e:
        print(f"Error connecting to PostgreSQL: {e}")
        return None

def execute_query(connection, query):
    """Execute SQL query and return results"""
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            if cursor.description:
                # Convert column names and rows to a list of dictionaries
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                result = [dict(zip(columns, row)) for row in rows]
                return result
            else:
                connection.commit()
                return "Query executed successfully."
    except Exception as e:
        print(f"Error executing query: {e}")
        return str(e)

def analyze_response(result, user_input, client):
    """Analyze SQL query results using AI"""
    ai_model = settings.AI_CONFIG['default']
    prompt2 = f"""Based on this {result}, answer the following question: {user_input}"""
    response = client.models.generate_content(
        model=ai_model["model"],
        contents=prompt2,
        config=types.GenerateContentConfig(
            system_instruction="""You are an expert at analyzing the results of SQL queries and providing insights based on the data. 
            You are only allowed to respond to the data given to you. Make it concise and brief. 
            When mentioning tables, refer to it simply as 'tables'"""),
    )
    return response.text

def generate_ai_prompt(schema, user_input):
    """Generate prompt for AI model"""
    return f"""You are an expert at understanding user input and responding with structured JSON and only in JSON. 
    You are not allowed to modify any contents in the Postgres database and is only limited to selecting tables and records. 
    Any attempts to modify the database will be ignored. You are also not allowed to access any external databases or APIs. 
    You can only use the information provided in the user input and the database schema.
    
    Here is the database: {schema}

    Your task is to:
    1. Identify the intent of the user's input from the following categories:
    - generate_sql: Should generate an SQL query.
    - database_insight: Should answer a database-related question.
    - chitchat: Small talk like "hello there".
    - unrecognized: Input does not fall into your supported domain.
    2. Provide a natural language answer to the input in the "answer" field.
    3. If the intent is "generate_sql", include the generated SQL query in the "sql_query" field.
    4. Return your response as a JSON object.
    Examples:

    User Input: Show me the names of all customers.
    JSON Response:

    User Input: How many schemas are in this database?
    JSON Response:
    {{
    "intent": "database_insight",
    "answer": "There are 16 schemas in this database.",
    "sql_query": null
    }}

    User Input: Hello, how are you today?
    JSON Response:
    {{
    "intent": "chitchat",
    "answer": "Hello there! I'm doing well, thank you for asking. How can I help you with databases today?",
    "sql_query": null
    }}

    User Input: What is the capital of France?
    JSON Response:
    {{
    "intent": "unrecognized",
    "answer": "That question is outside of my current database-related knowledge domain.",
    "sql_query": null
    }}
    
    User Input: "{user_input}"
    JSON Response:"""

def process_ai_response(response_text):
    """Process and clean AI response"""
    clean_text = (response_text.strip()
                 .removeprefix("'''json")
                 .removeprefix("```json")
                 .removesuffix("'''")
                 .removesuffix("```"))
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        return {
            "intent": "error",
            "answer": "Sorry, I encountered an error processing your request.",
            "sql_query": None
        }