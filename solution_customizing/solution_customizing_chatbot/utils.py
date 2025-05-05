import json
import os # Import os module
from datetime import datetime, date
from decimal import Decimal
from django.conf import settings
from django.db import connection

# LangChain imports
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.messages import HumanMessage, AIMessage
from .models import Message

MAX_INPUT_LENGTH = 255
MAX_MEMORY_INTERACTIONS = 3


# --- Hardcoded Schema Subset for Finance/Accounting ---
DB_SCHEMA_ACC_FINANCE = {
    "accounting": {
        "chart_of_accounts": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "account_code",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "account_name",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": "NULL::character varying",
                    "max_length": 50,
                    "name": "account_type",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [],
            "primary_key": "account_code"
        },
        "general_ledger_accounts": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "gl_account_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "account_name",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "account_code",
                    "nullable": False,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [
                {
                    "column": "account_code",
                    "references_column": "account_code",
                    "references_schema": "accounting",
                    "references_table": "chart_of_accounts"
                }
            ],
            "primary_key": "gl_account_id"
        },
        "journal_entries": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "journal_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "journal_date",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": "NULL::character varying",
                    "max_length": 255,
                    "name": "description",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "total_debit",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "total_credit",
                    "nullable": False,
                    "type": "numeric"
                },
                 {
                    "default": "NULL::character varying",
                    "max_length": 255,
                    "name": "invoice_id",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [],
            "primary_key": "journal_id"
        },
        "journal_entry_lines": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "entry_line_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": "NULL::character varying",
                    "max_length": 255,
                    "name": "gl_account_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "journal_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "debit_amount",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "credit_amount",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": "NULL::character varying",
                    "max_length": 255,
                    "name": "description",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [
                {
                    "column": "gl_account_id",
                    "references_column": "gl_account_id",
                    "references_schema": "accounting",
                    "references_table": "general_ledger_accounts"
                },
                {
                    "column": "journal_id",
                    "references_column": "journal_id",
                    "references_schema": "accounting",
                    "references_table": "journal_entries"
                }
            ],
            "primary_key": "entry_line_id"
        },
        "official_receipts": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "or_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "invoice_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "customer_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "or_date",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "settled_amount",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "payment_method",
                    "nullable": False,
                    "type": "USER-DEFINED"
                },
                {
                    "default": None,
                    "max_length": 100,
                    "name": "reference_number",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [], # Assuming FK to sales_invoice is handled elsewhere or not needed for this subset
            "primary_key": "or_id"
        }
    },
    "admin": {
        "assets": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "asset_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "asset_name",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": "now()",
                    "max_length": None,
                    "name": "purchase_date",
                    "nullable": True,
                    "type": "date"
                },
                {
                    "default": "0",
                    "max_length": None,
                    "name": "purchase_price",
                    "nullable": False,
                    "type": "numeric"
                }
            ],
            "foreign_keys": [],
            "primary_key": "asset_id"
        },
        "business_partner_master": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "partner_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "customer_id", # Note: This seems redundant if partner_id is the main key
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "partner_name",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": "'Employee'::partner_category",
                    "max_length": None,
                    "name": "category",
                    "nullable": True,
                    "type": "USER-DEFINED" # Assuming partner_category is an ENUM/TYPE
                }
            ],
            "foreign_keys": [],
            "primary_key": "partner_id"
        },
        "item_master_data": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "item_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "asset_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "item_name",
                    "nullable": False,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [
                {
                    "column": "asset_id",
                    "references_column": "asset_id",
                    "references_schema": "admin",
                    "references_table": "assets"
                }
            ],
            "primary_key": "item_id"
        }
    },
    "finance": {
        "budget_allocation": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_allocation_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_approvals_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "allocated_budget",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "total_spent",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "total_remaining_budget",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "allocated_remaining_budget",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "start_date",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "end_date",
                    "nullable": False,
                    "type": "date"
                }
            ],
            "foreign_keys": [
                {
                    "column": "budget_approvals_id",
                    "references_column": "budget_approvals_id",
                    "references_schema": "finance",
                    "references_table": "budget_approvals"
                }
            ],
            "primary_key": "budget_allocation_id"
        },
        "budget_approvals": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_approvals_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "validation_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "dept_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "amount_requested",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "validated_amount",
                    "nullable": True,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "approval_date",
                    "nullable": True,
                    "type": "date"
                }
            ],
            "foreign_keys": [
                {
                    "column": "validation_id",
                    "references_column": "validation_id",
                    "references_schema": "finance",
                    "references_table": "budget_validations"
                },
                 { # Added FK to departments
                    "column": "dept_id",
                    "references_column": "dept_id",
                    "references_schema": "human_resources",
                    "references_table": "departments"
                }
            ],
            "primary_key": "budget_approvals_id"
        },
        "budget_request_form": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_request_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "dept_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "amount_requested",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "expected_start_usage_period",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "expected_end_usage_period",
                    "nullable": False,
                    "type": "date"
                }
            ],
            "foreign_keys": [
                 { # Added FK to departments
                    "column": "dept_id",
                    "references_column": "dept_id",
                    "references_schema": "human_resources",
                    "references_table": "departments"
                }
            ],
            "primary_key": "budget_request_id"
        },
        "budget_submission": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_submission_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "dept_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "proposed_total_budget",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "start_usage_period",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "end_usage_period",
                    "nullable": False,
                    "type": "date"
                }
            ],
            "foreign_keys": [
                 { # Added FK to departments
                    "column": "dept_id",
                    "references_column": "dept_id",
                    "references_schema": "human_resources",
                    "references_table": "departments"
                }
            ],
            "primary_key": "budget_submission_id"
        },
        "budget_validations": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "validation_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_submission_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "budget_request_id",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [
                {
                    "column": "budget_submission_id",
                    "references_column": "budget_submission_id",
                    "references_schema": "finance",
                    "references_table": "budget_submission"
                },
                {
                    "column": "budget_request_id",
                    "references_column": "budget_request_id",
                    "references_schema": "finance",
                    "references_table": "budget_request_form"
                }
            ],
            "primary_key": "validation_id"
        }
    },
    "human_resources": {
        "departments": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "dept_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 100,
                    "name": "dept_name",
                    "nullable": True,
                    "type": "character varying"
                }
            ],
            "foreign_keys": [],
            "primary_key": "dept_id"
        }
    },
    "inventory": {
        "deprecation_report": { # Renamed from 'deprecation_report' for clarity if needed
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "deprecation_report_id", # Changed from 'deprecation_report_id'
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "inventory_item_id", # Changed from 'inventory_item_id'
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "reported_date", # Changed from 'date'
                    "nullable": True,
                    "type": "timestamp without time zone"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "deprecation_status", # Changed from 'method', assuming status like 'Pending', 'Approved'
                    "nullable": True,
                    "type": "USER-DEFINED" # Assuming an ENUM/TYPE for status
                }
            ],
            "foreign_keys": [
                {
                    "column": "inventory_item_id", # Changed from 'inventory_item_id'
                    "references_column": "item_id",
                    "references_schema": "admin",
                    "references_table": "item_master_data"
                }
            ],
            "primary_key": "deprecation_report_id" # Changed from 'deprecation_report_id'
        }
    },
    "sales": {
        "sales_invoice": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "invoice_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "customer_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "invoice_date",
                    "nullable": False,
                    "type": "date"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "total_amount",
                    "nullable": False,
                    "type": "numeric"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "due_date",
                    "nullable": False,
                    "type": "date"
                }
            ],
            "foreign_keys": [
                 {
                    "column": "customer_id",
                    "references_column": "partner_id", # Assuming customer_id maps to partner_id
                    "references_schema": "admin",
                    "references_table": "business_partner_master"
                }
            ],
            "primary_key": "invoice_id"
        }
    }
}

# --- execute_query to use django.db.connection ---
def execute_query(query):
    """Execute SQL query using Django's connection and return results"""
    if not query:
        return {"headers": [], "rows": [], "error": "No SQL query provided"}

    try:
        with connection.cursor() as cursor:
            cursor.execute(query)

            if cursor.description:
                column_names = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                formatted_rows = []
                for row in rows:
                    formatted_row = []
                    for item in row:
                        if isinstance(item, (datetime, date)):
                            formatted_row.append(item.isoformat())
                        elif isinstance(item, Decimal):
                            formatted_row.append(float(item))
                        else:
                            formatted_row.append(item)
                    formatted_rows.append(formatted_row)

                return {
                    "headers": column_names,
                    "rows": formatted_rows
                }
            else:
                return {"headers": [], "rows": [], "message": "Query executed successfully, no data returned."}

    except Exception as e:
        print(f"Error executing query via Django connection: {e}")
        return {"headers": [], "rows": [], "error": str(e)}

# --- Helper function to load history from DB ---
def _load_chat_history_from_db(conversation_id, limit=MAX_MEMORY_INTERACTIONS):
    if not conversation_id:
        return {"chat_history": []}

    try:
        messages = Message.objects.filter(conversation_id=conversation_id).order_by('-created_at')[:limit * 2]
        messages = reversed(messages)

        history_messages = []
        for msg in messages:
            if msg.sender == 'user':
                history_messages.append(HumanMessage(content=msg.message))
            elif msg.sender == 'bot':
                history_messages.append(AIMessage(content=msg.message))

        return {"chat_history": history_messages}
    except Exception as e:
        print(f"Error loading chat history for conversation {conversation_id}: {e}")
        return {"chat_history": []}


def setup_langchain_agent():
    """Sets up and returns the core LangChain agent components using the hardcoded schema subset."""
    try:
        ai_config = settings.AI_CONFIG['default']
        llm = ChatGoogleGenerativeAI(
            model=ai_config["model"],
            google_api_key=ai_config["api_key"],
            temperature=0.1
        )
        
        # --- Prompt uses db_schema_subset which references the hardcoded dict ---
        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt = ChatPromptTemplate.from_template(
            f"""You are an expert assistant for a database chatbot focused *only* on Financial and Accounting reports.
            Current time is {current_time}.""" + """

            You are provided with a subset of the database schema relevant *only* to Financial and Accounting tasks:
            Database Schema (Accounting & Finance Subset):
            {db_schema_subset}

            You are not allowed to modify any contents in the Postgres database and are only limited to selecting tables and records from the provided schema subset.
            Any attempts to modify the database will be ignored. You are also not allowed to access any external databases, APIs, or schema information beyond what is provided above.

            Your primary task is to assist with generating the following Financial & Accounting reports:
            - Financial Statements (Balance Sheet, Income Statement, Cash Flow)
            - General Ledger Report
            - Trial Balance
            - Accounts Receivable Aging
            - Cash Receipts Journal
            - Budget Reports (Budget vs. Actual, Variance, Departmental)
            - Fixed Asset Register
            - Depreciation Report

            Based on the user's input and previous conversation:
            1. Identify the intent:
               - generate_sql: If the user asks for a *set* of data or a report (like the ones listed) that requires retrieving multiple rows/columns from the database using the provided schema subset. This intent usually implies the results will be displayed as a table. A request for a specific calculated value (like a count or sum) that requires a query also falls here, but the primary output should be the value in the 'answer' field.
               - database_insight: If the user asks a question *about* the provided schema, data concepts, or asks for a simple summary/count that can be determined *directly* from the schema description or requires a very simple aggregation query (like COUNT(*)). The answer should be provided textually in the 'answer' field.
               - chitchat: Small talk like "hello there".
               - out_of_scope: If the input asks about reports, data, or schema *outside* the listed Financial & Accounting domain. Politely state you can only handle Financial/Accounting reports listed above.
               - unrecognized: Input does not fall into any other category.
            2. Provide a natural language answer in the "answer" field.
               - If the intent is "out_of_scope", explain the limitation clearly.
               - If the intent is "database_insight", provide the answer or summary directly (e.g., "There are 5 columns in the chart_of_accounts table.", "The total count of accounts is 150.").
               - If the intent is "generate_sql" and the request was for a specific value (like a count), state the value clearly in the answer (e.g., "There are 10 accounts matching that ID."). If the request was for a set of data, provide a brief introductory sentence (e.g., "Here are the accounts you requested.").
               - Do NOT describe which specific tables or columns from the schema you are using in the "answer" field unless it's essential for explaining a limitation.
            3. If the intent is "generate_sql", include the generated SQL query in the "sql_query" field.
               - If the request was for a specific value (like a count) that required a query, include the aggregation query (e.g., SELECT COUNT(*) ...).
               - If the request was for a set of data, include the query to retrieve that data.
               - If the intent is "database_insight" and no query was needed (or only a trivial one implied by the schema description), set "sql_query" to null.
               - Otherwise (for chitchat, out_of_scope, etc.), set "sql_query" to null.
            4. Return your response as a JSON object.

            # --- Added Instruction ---
            IMPORTANT: When explaining limitations (like missing data for a full report), provide the explanation in the "answer". If a partial SQL query is possible and relevant (like fetching account balances), include it in "sql_query". **Never ask the user if they want the SQL generated or ask follow-up clarifying questions about generating SQL. Just provide the explanation and the SQL if applicable.**

            Always respond in this JSON format:
            {{
              "intent": "intent_category",
              "answer": "Your natural language response here",
              "sql_query": "SQL query if applicable, otherwise null"
            }}

            Previous conversation:
            {chat_history}

            User query: {input}

            Remember: Only generate SQL for the specified Financial & Accounting reports using the provided schema subset. Decline requests outside this scope. Be precise and use the correct table and column names from the provided schema.
            """
        )

        # --- Build the core chain, using the hardcoded schema subset ---
        chain = (
            RunnablePassthrough.assign(
                chat_history=lambda x: _load_chat_history_from_db(x.get('conversation_id'))["chat_history"],
                db_schema_subset=lambda x: json.dumps(DB_SCHEMA_ACC_FINANCE, indent=2),
            )
            | prompt
            | llm
            | StrOutputParser()
        )
        return chain, llm
    except Exception as e:
        print(f"CRITICAL Error initializing LangChain Agent Chain: {e}")
        return None


# --- Initialize AGENT_CHAIN at module level ---
AGENT_CHAIN, LLM_INSTANCE = setup_langchain_agent()

# --- process_user_input  ---
def process_user_input(user_input, conversation_id):
    if len(user_input) > MAX_INPUT_LENGTH:
        return {
            "intent": "error",
            "answer": f"Your input exceeds the maximum length of {MAX_INPUT_LENGTH} characters. Please shorten your message.",
            "sql_query": None
        }

    input_dict = {
        "input": user_input,
        "conversation_id": conversation_id
    }

    try:
        if not AGENT_CHAIN:
            raise ValueError("LangChain agent chain is not initialized.")
        response = AGENT_CHAIN.invoke(input_dict)
        clean_text = (response.strip()
                .removeprefix("'''json")
                .removeprefix("```json")
                .removesuffix("'''")
                .removesuffix("```"))
        return json.loads(clean_text)
    except json.JSONDecodeError:
        print(f"JSONDecodeError processing LLM response: {response}")
        return {
            "intent": "error",
            "answer": "I'm having trouble generating a proper response format. Please try rephrasing.",
            "sql_query": None
        }
    except Exception as e:
        print(f"Error during chain invocation or processing: {e}")
        return {
            "intent": "error",
            "answer": f"An internal error occurred while processing your request: {str(e)}",
            "sql_query": None
        }


# --- analyze_sql_results ---
def analyze_sql_results(results, user_input, conversation_id):
    formatted_results = json.dumps(results, default=str)

    analysis_prompt_text = f"""You are an assistant tasked with summarizing database query results into a *single, concise natural language sentence*.
    The user originally asked: "{user_input}"
    The database query returned the following data (this data will be displayed to the user separately as a table):
    {formatted_results}

    Your task is to provide *only* a brief introductory sentence or summary based on the data provided, suitable for preceding the table display. Do *not* list the data items themselves in your response. Focus solely on a high-level interpretation (e.g., "Here is the list of assets you requested," or "The query returned 5 assets."). If the results are empty, state that clearly (e.g., "No assets matching your criteria were found.").

    Generate a JSON response with an "answer" field containing *only* this single summary sentence.
    Example JSON (Good): {{"answer": "Here is the list of assets you requested."}}
    Example JSON (Good): {{"answer": "The query returned 10 assets matching your criteria."}}
    Example JSON (Bad): {{"answer": "Here is the list: * Asset A * Asset B"}}

    Analysis (generate only the summary sentence for the 'answer' field):
    """

    input_dict = {
        "input": analysis_prompt_text,
        "conversation_id": conversation_id
    }

    try:
        if not AGENT_CHAIN:
            raise ValueError("LangChain agent chain is not initialized.")
        response = AGENT_CHAIN.invoke(input_dict)
        clean_text = (response.strip()
                    .removeprefix("```json")
                    .removeprefix("'''json")
                    .removesuffix("```")
                    .removesuffix("'''"))
        json_response = json.loads(clean_text)
        return json_response.get("answer", "Analysis could not be generated.")
    except json.JSONDecodeError:
        print(f"JSONDecodeError processing analysis response: {response}")
        return (response.strip()
                .removeprefix("```")
                .removeprefix("'''")
                .removesuffix("```")
                .removesuffix("'''"))
    except Exception as e:
        print(f"Error during analysis chain invocation or processing: {e}")
        return f"Error analyzing results: {str(e)}"


# --- Title generation chain initialization ---
def initialize_title_generation_chain():
    try:
        if not LLM_INSTANCE: # Check if LLM was initialized
            print("CRITICAL Error initializing Title Chain: LLM_INSTANCE is None.")
            return None

        title_prompt_template = ChatPromptTemplate.from_messages([
            ("system", "You are an assistant skilled at creating concise conversation titles."),
            ("human", """Based on the following initial exchange, generate a short, relevant title (max 10 words) for this conversation. Output only the title itself, nothing else.

User: "{user_message}"
Bot: "{bot_message}"

Title:"""),
        ])

        chain = title_prompt_template | LLM_INSTANCE | StrOutputParser()
        return chain

    except Exception as e:
        print(f"CRITICAL Error initializing LangChain/Gemini Title Chain: {e}")
        return None

title_generation_chain = initialize_title_generation_chain()