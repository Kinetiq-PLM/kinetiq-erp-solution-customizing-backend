import json
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

ENABLE_SCHEMA_CACHING = False # Set to True for production/deployment, False for development

MAX_INPUT_LENGTH = 255
MAX_MEMORY_INTERACTIONS = 10

# --- Global variable for cached schema ---
CACHED_DB_SCHEMA = None
SCHEMA_FETCH_ERROR = None # Optional: Store error if initial fetch fails

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
            "foreign_keys": [],
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
                    "name": "customer_id",
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
                    "type": "USER-DEFINED"
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
            "foreign_keys": [],
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
            "foreign_keys": [],
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
        "deprecation_report": {
            "columns": [
                {
                    "default": None,
                    "max_length": 255,
                    "name": "deprecation_report_id",
                    "nullable": False,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": 255,
                    "name": "inventory_item_id",
                    "nullable": True,
                    "type": "character varying"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "date",
                    "nullable": True,
                    "type": "timestamp without time zone"
                },
                {
                    "default": None,
                    "max_length": None,
                    "name": "method",
                    "nullable": True,
                    "type": "USER-DEFINED"
                }
            ],
            "foreign_keys": [
                {
                    "column": "inventory_item_id",
                    "references_column": "item_id",
                    "references_schema": "admin",
                    "references_table": "item_master_data"
                }
            ],
            "primary_key": "deprecation_report_id"
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
                    "references_column": "partner_id",
                    "references_schema": "admin",
                    "references_table": "business_partner_master"
                }
            ],
            "primary_key": "invoice_id"
        }
    }
}

# --- Modify execute_query to use django.db.connection ---
def execute_query(query): # Remove connection parameter
    """Execute SQL query using Django's connection and return results"""
    if not query:
        # Return structure consistent with frontend expectation if possible
        return {"headers": [], "rows": [], "error": "No SQL query provided"}

    try:
        # --- Use Django's connection ---
        with connection.cursor() as cursor:
            cursor.execute(query)

            if cursor.description:
                column_names = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                # --- Format rows for JSON serialization ---
                formatted_rows = []
                for row in rows:
                    formatted_row = []
                    for item in row:
                        if isinstance(item, (datetime, date)):
                            formatted_row.append(item.isoformat())
                        elif isinstance(item, Decimal):
                            formatted_row.append(float(item)) # Convert Decimal
                        else:
                            formatted_row.append(item)
                    formatted_rows.append(formatted_row)

                # --- Return structure expected by frontend ---
                return {
                    "headers": column_names,
                    "rows": formatted_rows
                    # Add row_count if needed: "row_count": len(rows)
                }
            else:
                return None # Or {"message": "Query executed, no results returned."}

    except Exception as e:
        print(f"Error executing query via Django connection: {e}")
        # --- Return error structure consistent with success case ---
        return {"headers": [], "rows": [], "error": str(e)}

def get_database_schema():
    """Get database schema information using Django's connection"""
    schema_info = {}
    try:
        with connection.cursor() as cursor:
            # ... (rest of the schema fetching logic) ...
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
        print("Database schema fetched successfully for caching.") # Log success
        return schema_info
    except Exception as e:
        # Store the error globally if needed, and return empty
        global SCHEMA_FETCH_ERROR
        SCHEMA_FETCH_ERROR = e
        print(f"CRITICAL Error fetching Kinetiq DB schema for caching: {e}")
        return {} # Return empty dict on error

# --- Function to get the cached schema ---
def get_cached_schema():
    """Returns the globally cached database schema."""
    if not ENABLE_SCHEMA_CACHING:
        return {} # Return empty immediately if caching is disabled

    if CACHED_DB_SCHEMA is None and SCHEMA_FETCH_ERROR is None:
        # This case should ideally not happen if _initialize_cache runs,
        # but as a fallback, attempt to fetch now.
        print("Warning: Schema cache was empty, attempting to fetch now.")
        _initialize_cache() # Try to initialize it
    elif SCHEMA_FETCH_ERROR:
        print(f"Warning: Returning empty schema due to initial fetch error: {SCHEMA_FETCH_ERROR}")
        return {} # Return empty if initial fetch failed
    return CACHED_DB_SCHEMA if CACHED_DB_SCHEMA is not None else {}

# --- Helper function to load history from DB (keep previous version) ---
def _load_chat_history_from_db(conversation_id, limit=MAX_MEMORY_INTERACTIONS):
    # ... (implementation remains the same) ...
    if not conversation_id:
        return {"chat_history": []} # Return empty list if no ID

    try:
        # Fetch the last N * 2 messages (N user, N bot)
        messages = Message.objects.filter(conversation_id=conversation_id).order_by('-created_at')[:limit * 2]
        # Reverse to get chronological order (oldest first)
        messages = reversed(messages)

        history_messages = []
        for msg in messages:
            # Use LangChain message types directly
            if msg.sender == 'user':
                history_messages.append(HumanMessage(content=msg.message))
            elif msg.sender == 'bot':
                history_messages.append(AIMessage(content=msg.message))

        return {"chat_history": history_messages}
    except Exception as e:
        print(f"Error loading chat history for conversation {conversation_id}: {e}")
        return {"chat_history": []} # Return empty on error


def setup_langchain_agent():
    """Sets up and returns the core LangChain agent components (excluding dynamic memory)."""
    try:
        ai_config = settings.AI_CONFIG['default']
        # --- Initialize LLM globally or here ---
        # Consider initializing LLM globally if it's expensive
        llm = ChatGoogleGenerativeAI(
            model=ai_config["model"],
            google_api_key=ai_config["api_key"],
            temperature=0.1
        )

        # --- Updated Prompt focusing on specific reports and schema subset ---
        prompt = ChatPromptTemplate.from_template(
            """You are an expert assistant for a database chatbot focused *only* on Financial and Accounting reports.
            Current time is {current_time}.

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
            (You can add more report types here later)

            Based on the user's input and previous conversation:
            1. Identify the intent:
               - generate_sql: If the user asks for data or a report related *specifically* to the listed Financial & Accounting reports and the provided schema subset.
               - database_insight: If the user asks a question about the *provided* Financial & Accounting schema or data concepts related to the listed reports.
               - chitchat: Small talk like "hello there".
               - out_of_scope: If the input asks about reports, data, or schema *outside* the listed Financial & Accounting domain (e.g., detailed Sales Orders, HR employee performance, specific Inventory movements not related to depreciation/assets). Politely state you can only handle Financial/Accounting reports listed above.
               - unrecognized: Input does not fall into any other category.
            2. Provide a natural language answer in the "answer" field. If the intent is "out_of_scope", explain the limitation clearly.
            3. If the intent is "generate_sql", include the generated SQL query (using *only* the provided schema subset) in the "sql_query" field. Otherwise, set "sql_query" to null.
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

            Remember: Only generate SQL for the specified Financial & Accounting reports using the provided schema subset. Decline requests outside this scope. Be precise and use the correct table and column names from the provided schema.
            """
        )

        # # --- Prompt remains the same, expecting 'chat_history' ---
        # prompt = ChatPromptTemplate.from_template(
        #     """You are an expert at understanding user input and responding with structured JSON.
        #     Current time is {current_time}.
        #     You are a helpful assistant for a database chatbot.
        #     Database Schema:
        #     {db_schema}
        #     You are not allowed to modify any contents in the Postgres database and is only limited to selecting tables and records.
        #     Any attempts to modify the database will be ignored. You are also not allowed to access any external databases or APIs.
        #     You can only use the information provided in the user input and the database schema.
        #     Your task is to:
        #     1. Identify the intent of the user's input from the following categories:
        #        - generate_sql: Should generate an SQL query.
        #        - database_insight: Should answer a database-related question.
        #        - chitchat: Small talk like "hello there".
        #        - unrecognized: Input does not fall into your supported domain.
        #     2. Provide a natural language answer to the input in the "answer" field.
        #     3. If the intent is "generate_sql", include the generated SQL query in the "sql_query" field.
        #     4. Return your response as a JSON object.
        #     Always respond in this JSON format:
        #     {{
        #       "intent": "intent_category",
        #       "answer": "Your natural language response here",
        #       "sql_query": "SQL query if applicable, otherwise null"
        #     }}
        #     Previous conversation:
        #     {chat_history}
        #     User query: {input}
        #     Make sure to handle context from previous interactions when generating SQL queries or answers."""
        # )

        # --- Build the core chain, dynamically loading history ---
        chain = (
            RunnablePassthrough.assign(
                # Load history dynamically based on conversation_id passed in input 'x'
                chat_history=lambda x: _load_chat_history_from_db(x.get('conversation_id'))["chat_history"],
                current_time=lambda _: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                db_schema_subset=lambda x: json.dumps(DB_SCHEMA_ACC_FINANCE, indent=2),
                # db_schema=lambda x: json.dumps(get_cached_schema(), indent=2) 
            )
            | prompt
            | llm
            | StrOutputParser()
        )
        return chain
    except Exception as e:
        print(f"CRITICAL Error initializing LangChain Agent Chain: {e}")
        return None # Or raise error

# --- Initialize AGENT_CHAIN at module level ---
AGENT_CHAIN = setup_langchain_agent()

# --- process_user_input now uses the passed chain directly ---
def process_user_input(user_input, conversation_id, chain_instance): # Added conversation_id
    """Process user input and generate a response using the provided LangChain instance"""
    if len(user_input) > MAX_INPUT_LENGTH:
        return {
            "intent": "error",
            "answer": f"Your input exceeds the maximum length of {MAX_INPUT_LENGTH} characters. Please shorten your message.",
            "sql_query": None
        }

    # Pass input in the expected dictionary format for the wrapper
    input_dict = {
        "input": user_input,
        "conversation_id": conversation_id # Pass the ID here
    }

    try:
        # --- Invoke the passed chain instance ---
        if not chain_instance:
            raise ValueError("LangChain agent chain is not initialized.")
        response = chain_instance.invoke(input_dict) # Pass the dictionary
        clean_text = (response.strip()
                .removeprefix("'''json")
                .removeprefix("```json")
                .removesuffix("'''")
                .removesuffix("```"))
        return json.loads(clean_text)
    except json.JSONDecodeError:
        print(f"JSONDecodeError processing LLM response: {response}") # Log the raw response
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


# --- analyze_sql_results  ---
def analyze_sql_results(results, user_input, conversation_id, chain_instance): # Added conversation_id
    """Analyze SQL query results using the provided LangChain instance"""
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
    # --- End Revised Analysis Prompt ---


    # --- Pass input AND conversation_id  ---
    input_dict = {
        "input": analysis_prompt_text,
        "conversation_id": conversation_id
        # Note: We are *not* passing db_schema_subset or chat_history here,
        # as the analysis should focus *only* on the provided results and original question.
        # The main chain instance might still use its default prompt structure,
        # but the content of 'input' here guides the LLM for this specific task.
    }

    try:
        if not chain_instance:
            raise ValueError("LangChain agent chain is not initialized.")
        # Invoke the same chain, but with the specific analysis prompt as input
        response = chain_instance.invoke(input_dict)
        clean_text = (response.strip()
                    .removeprefix("```json")
                    .removeprefix("'''json")
                    .removesuffix("```")
                    .removesuffix("'''"))
        json_response = json.loads(clean_text)
        # Ensure the response contains the 'answer' key
        return json_response.get("answer", "Analysis could not be generated.")
    except json.JSONDecodeError:
        print(f"JSONDecodeError processing analysis response: {response}")
        # Fallback: return the raw text if JSON parsing fails but it might be the answer
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
        return None

title_generation_chain = initialize_title_generation_chain()

def _initialize_cache():
    """Fetches and caches data needed globally."""
    if not ENABLE_SCHEMA_CACHING:
        print("Schema caching is disabled. Skipping initial fetch.")
        return # Do nothing if caching is off

    global CACHED_DB_SCHEMA
    print("Attempting to cache database schema...")
    CACHED_DB_SCHEMA = get_database_schema()
    # Add other caching initializations here if needed

# --- Initialize the cache when the module is loaded ---
_initialize_cache()
