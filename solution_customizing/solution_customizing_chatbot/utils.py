import json
import psycopg2
from datetime import datetime, date
from decimal import Decimal
from django.conf import settings
from django.db import connection

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
    # enhanced_input = f"Database schema: {json.dumps(db_schema)}\n\nUser query: {user_input}"
    enhanced_input = f"User query: {user_input}"
    
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
    
# --- Function to initialize and return the LLM chain ---
def initialize_title_generation_chain():
    """Initializes and returns the LangChain components for title generation."""
    try:
        ai_config = settings.AI_CONFIG['default']
        llm = ChatGoogleGenerativeAI(
            model=ai_config["model"],
            google_api_key=ai_config["api_key"],
            temperature=0.1
        )
        title_prompt_template = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant skilled at creating concise conversation titles."),
            ("human", """Based on the following initial exchange, generate a short, relevant title (max 10 words) for this conversation. Output only the title itself, nothing else.

User: "{user_message}"
Bot: "{bot_message}"

Title:"""),
        ])

        chain = title_prompt_template | llm | StrOutputParser()
        return chain

    except Exception as e:
        print(f"CRITICAL Error initializing LangChain/Gemini Title Chain: {e}")
        # Depending on requirements, you might raise the error or return None
        return None

# --- Initialize at module level by calling the function ---
# This ensures it runs once when the module is first imported.
title_generation_chain = initialize_title_generation_chain()

def get_kinetiq_database_schema():
    """Get complete schema information for Kinetiq database."""
    schema_info = {}
    
    with connection.cursor() as cursor:
        # Get all schemas except system schemas
        cursor.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN 
                ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name;
        """)
        schemas = cursor.fetchall()
        
        for schema in schemas:
            schema_name = schema[0]
            schema_info[schema_name] = {}
            
            # Get all tables for current schema
            cursor.execute("""
                SELECT 
                    table_name,
                    table_type
                FROM information_schema.tables 
                WHERE table_schema = %s
                ORDER BY table_name;
            """, [schema_name])
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                schema_info[schema_name][table_name] = {
                    'columns': [],
                    'foreign_keys': [],
                    'primary_key': None
                }
                
                # Get column information
                cursor.execute("""
                    SELECT 
                        column_name,
                        data_type,
                        character_maximum_length,
                        column_default,
                        is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    AND table_name = %s
                    ORDER BY ordinal_position;
                """, [schema_name, table_name])
                columns = cursor.fetchall()
                
                for column in columns:
                    schema_info[schema_name][table_name]['columns'].append({
                        'name': column[0],
                        'type': column[1],
                        'max_length': column[2],
                        'default': column[3],
                        'nullable': column[4] == 'YES'
                    })
                
                # Get primary key information
                cursor.execute("""
                    SELECT c.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage AS ccu 
                    USING (constraint_schema, constraint_name)
                    JOIN information_schema.columns AS c 
                    ON c.table_schema = tc.constraint_schema
                    AND c.table_name = tc.table_name
                    AND c.column_name = ccu.column_name
                    WHERE constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = %s
                    AND tc.table_name = %s;
                """, [schema_name, table_name])
                pk = cursor.fetchone()
                if pk:
                    schema_info[schema_name][table_name]['primary_key'] = pk[0]
                
                # Get foreign key information
                cursor.execute("""
                    SELECT
                        kcu.column_name,
                        ccu.table_schema AS foreign_table_schema,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = %s
                    AND tc.table_name = %s;
                """, [schema_name, table_name])
                foreign_keys = cursor.fetchall()
                
                for fk in foreign_keys:
                    schema_info[schema_name][table_name]['foreign_keys'].append({
                        'column': fk[0],
                        'references_schema': fk[1],
                        'references_table': fk[2],
                        'references_column': fk[3]
                    })
    
    return schema_info