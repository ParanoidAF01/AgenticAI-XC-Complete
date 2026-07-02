# Legacy Streamlit Application

This directory contains the original single-file Streamlit ontology-driven insurance database chatbot.

## File

- `app_streamlit_legacy.py` — The complete legacy application (1765 lines)

## What It Contains

| Component | Lines | Description |
|---|---|---|
| Config & Constants | 1–28 | App title, supported profiles, limits |
| Error Classes | 33–52 | Custom exception hierarchy |
| Session & Logging | 57–85 | Streamlit session state init, console+UI logging |
| Generic Helpers | 90–192 | dedupe, normalize, JSON/SQL text extraction, quote_sql_literal |
| LLM Prompts | 196–299 | Router, Planner, Answer, SQL Repair, General Chat prompts |
| LLM Client | 302–350 | Anthropic REST API via requests |
| Neo4j Repository | 356–584 | OntologyEntity, Metric, Term, Relationship queries, preferred path |
| MSSQL Connection | 589–624 | Connection builder, schema introspection |
| Router | 629–641 | Question classification (general_chat / simple_db / complex_db) |
| Planner Context | 643–723 | Ontology context builder for LLM planner |
| Planner V2 | 728–904 | Structured plan generation with validation and repair |
| SQL Compiler | 908–1075 | Deterministic SQL generation from plan tasks |
| SQL Validator | 1189–1351 | sp_describe_first_result_set validation + LLM repair loop |
| SQL Executor | 1080–1093 | Query execution with result marshalling |
| Execute Plan | 1439–1515 | Multi-task orchestration with result merge |
| Answer Generator | 1519–1548 | LLM-based answer synthesis |
| Streamlit UI | 1550–1765 | Chat interface with developer mode |

## Running (Legacy)

```bash
pip install streamlit requests python-dotenv neo4j sqlalchemy pyodbc
streamlit run app_streamlit_legacy.py
```

Requires `.env` with: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `LLM_API_KEY`, `LLM_ENDPOINT`, `LLM_MODEL`

## Status

**PRESERVED — DO NOT MODIFY.** This file is the reference implementation for migration parity testing.
