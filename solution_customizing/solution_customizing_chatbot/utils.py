import json
import psycopg2
from datetime import datetime, date
from decimal import Decimal
from django.conf import settings

# LangChain imports
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import ConversationBufferMemory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

MAX_INPUT_LENGTH = 255
MAX_MEMORY_INTERACTIONS = 10

def connect_to_postgres():
    """Establish connection to PostgreSQL database using Django settings"""
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
    """Execute SQL query and return results (with type info)"""
    if not query:
        return {"type": "error", "error": "No SQL query provided"}
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            if cursor.description:
                rows = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                # Check if this is a COUNT query
                is_count_query = (
                    'count' in query.lower() and 
                    len(column_names) == 1 and 
                    column_names[0].lower() == 'count'
                )
                if is_count_query:
                    return {"type": "count", "value": rows[0][0]}
                else:
                    json_rows = []
                    for row in rows:
                        row_dict = {}
                        for i, col in enumerate(column_names):
                            if isinstance(row[i], (datetime, date)):
                                row_dict[col] = row[i].isoformat()
                            elif isinstance(row[i], Decimal):
                                row_dict[col] = float(row[i])
                            else:
                                row_dict[col] = row[i]
                        json_rows.append(row_dict)
                    return {
                        "type": "result_set",
                        "columns": column_names,
                        "rows": json_rows,
                        "row_count": len(rows),
                        "query": query
                    }
            else:
                connection.commit()
                return {"type": "message", "message": "Query executed successfully."}
    except Exception as e:
        print(f"Error executing query: {e}")
        return {"type": "error", "error": str(e)}

def get_database_schema(connection):
    """Get database schema information"""
    schema_query = """
    SELECT 
        table_schema AS schema_name,
        table_name AS table_name,
        column_name,
        data_type
    FROM 
        information_schema.columns
    WHERE 
        table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY 
        table_schema, table_name;
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(schema_query)
            schema_rows = cursor.fetchall()
            schema = {}
            for row in schema_rows:
                schema_name, table_name, column_name, data_type = row
                if schema_name not in schema:
                    schema[schema_name] = {}
                if table_name not in schema[schema_name]:
                    schema[schema_name][table_name] = []
                schema[schema_name][table_name].append({
                    "column_name": column_name,
                    "data_type": data_type
                })
            # Print structure analysis
            num_schemas = len(schema)
            num_tables = sum(len(tables) for tables in schema.values())
            num_columns = sum(len(columns) for tables in schema.values() for columns in tables.values())
            print(f"Database structure: {num_schemas} schemas, {num_tables} tables, {num_columns} columns")
            return schema
    except Exception as e:
        print(f"Error fetching database schema: {e}")
        return {}

def setup_langchain_agent():
    """Set up LangChain agent with conversation memory"""
    ai_config = settings.AI_CONFIG['default']
    llm = ChatGoogleGenerativeAI(
        model=ai_config["model"],
        google_api_key=ai_config["api_key"],
        temperature=0.1
    )
    memory = ConversationBufferMemory(
        return_messages=True,
        memory_key="chat_history",
        k=MAX_MEMORY_INTERACTIONS
    )
    prompt = ChatPromptTemplate.from_template(
        """You are an expert at understanding user input and responding with structured JSON.
        Current time is {current_time}.
        You are not allowed to modify any contents in the Postgres database and is only limited to selecting tables and records. 
        Any attempts to modify the database will be ignored. You are also not allowed to access any external databases or APIs. 
        You can only use the information provided in the user input and the database schema.
        Your task is to:
        1. Identify the intent of the user's input from the following categories:
           - generate_sql: Should generate an SQL query.
           - database_insight: Should answer a database-related question.
           - chitchat: Small talk like "hello there".
           - unrecognized: Input does not fall into your supported domain.
        2. Provide a natural language answer to the input in the "answer" field.
        3. If the intent is "generate_sql", include the generated SQL query in the "sql_query" field.
        4. Return your response as a JSON object.
        Always respond in this JSON format:
        {{
          "intent": "intent_category",
          "answer": "Your natural language response here",
          "sql_query": "SQL query if applicable, otherwise null"
        }}
        Previous conversation:
        {chat_history}
        User query: {input}
        Make sure to handle context from previous interactions when generating SQL queries or answers."""
    )
    chain = (
        RunnablePassthrough.assign(
            chat_history=lambda x: memory.load_memory_variables({})["chat_history"],
            current_time=lambda _: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        | prompt
        | llm
        | StrOutputParser()
    )
    def chain_with_memory(input_text):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response = chain.invoke({"input": input_text})
        memory.save_context(
            {"input": f"[{timestamp}] User: {input_text}"},
            {"output": f"[{timestamp}] Assistant: {response}"}
        )
        return response
    return chain_with_memory

def process_user_input(user_input, chain, db_schema):
    """Process user input and generate a response using LangChain"""
    if len(user_input) > MAX_INPUT_LENGTH:
        return {
            "intent": "error",
            "answer": f"Your input exceeds the maximum length of {MAX_INPUT_LENGTH} characters. Please shorten your message.",
            "sql_query": None
        }
    enhanced_input = f"Database schema: {json.dumps(db_schema)}\n\nUser query: {user_input}"
    try:
        response = chain(enhanced_input)
        clean_text = (response.strip()
                .removeprefix("'''json")
                .removeprefix("```json")
                .removesuffix("'''")
                .removesuffix("```"))
        return json.loads(clean_text)
    except json.JSONDecodeError:
        return {
            "intent": "error",
            "answer": "I'm having trouble generating a proper response. Please try rephrasing.",
            "sql_query": None
        }

def analyze_sql_results(results, user_input, chain_wrapper):
    """Analyze SQL query results using LangChain"""
    formatted_results = json.dumps(results, default=str)
    analysis_prompt = f"""Based on these SQL results: {formatted_results},
    analyze and answer the following question: {user_input}
    Please be concise and focus on the most relevant insights."""
    response = chain_wrapper(analysis_prompt)
    try:
        clean_text = (response.strip()
                     .removeprefix("```json")
                     .removeprefix("'''json")
                     .removesuffix("```")
                     .removesuffix("'''"))
        json_response = json.loads(clean_text)
        return json_response["answer"]
    except json.JSONDecodeError:
        return (response.strip()
                .removeprefix("```")
                .removeprefix("'''")
                .removesuffix("```")
                .removesuffix("'''"))