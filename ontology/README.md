# Ontology-Driven Insurance Chatbot

> Natural language → SQL powered by a Neo4j metadata graph, LangGraph orchestration, and OpenAI LLMs.

Ask business questions in plain English — the system maps them to your insurance data model via an ontology graph, generates validated SQL, executes it against MSSQL, and returns a human-readable answer.

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                            │
│  POST /ask   ·   WebSocket /ws   ·   GET /health                │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                  LangGraph Orchestrator                          │
│                                                                  │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌───────────┐       │
│  │  Input    │→│  Intent    │→│ Entity   │→│ Clarity   │       │
│  │ Processor │  │ Classifier │  │Extractor │  │ Checker   │       │
│  └──────────┘  └───────────┘  └─────────┘  └─────┬─────┘       │
│                                                    │              │
│                          ┌────────────────────────┘              │
│                          ▼                                        │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌───────────┐       │
│  │ GraphRAG │→│ Ontology   │→│  SQL     │→│   SQL     │       │
│  │ Retriever│  │  Lookup    │  │Generator │  │ Validator  │       │
│  └──────────┘  └───────────┘  └─────────┘  └─────┬─────┘       │
│                                                    │              │
│                          ┌────────────────────────┘              │
│                          ▼                                        │
│  ┌──────────┐  ┌───────────┐                                     │
│  │   SQL    │→│ Response   │                                     │
│  │ Executor │  │ Generator  │                                     │
│  └──────────┘  └───────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
         │              │               │              │
         ▼              ▼               ▼              ▼
    ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Neo4j   │   │  OpenAI  │   │  MSSQL   │   │  Redis   │
    │ (Graph) │   │  (LLM)   │   │  (Data)  │   │ (Cache)  │
    └─────────┘   └──────────┘   └──────────┘   └──────────┘
```

### Component Responsibilities

| Component | Purpose |
|-----------|---------|
| **FastAPI** | HTTP/WebSocket API, request validation, CORS, error handling |
| **LangGraph** | DAG-based workflow orchestration with conditional edges |
| **Neo4j** | Ontology graph — tables, columns, joins, concepts, embeddings |
| **OpenAI** | Intent classification, entity extraction, SQL generation, NL response |
| **MSSQL** | Insurance data warehouse (source of truth) |
| **Redis** | Query result caching, conversation history |
| **SpaCy** | Named-entity recognition (NER) pre-processing |

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Neo4j Aura / Self-hosted | 5.x |
| Microsoft SQL Server | 2019+ |
| ODBC Driver for SQL Server | 17 or 18 |
| Redis | 7.x |

---

## Setup

### 1. Clone & navigate

```bash
git clone <repo-url>
cd ontology
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Download the SpaCy model

```bash
python -m spacy download en_core_web_sm
```

### 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in every value (see [Configuration](#configuration) below).

### 6. Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The interactive API docs are available at **http://localhost:8000/docs**.

---

## API Reference

### `POST /ask` — Ask a question

Submit a natural-language question and receive a structured answer.

**Request**

```json
{
  "question": "How many active policies are in California?",
  "session_id": "optional-session-id"
}
```

**Response — Success (200)**

```json
{
  "session_id": "sess_abc123",
  "answer": "There are 1,247 active policies in California.",
  "generated_sql": "SELECT COUNT(*) AS cnt FROM POL_POLICY WHERE ENTITY_STATUS = 'Active' AND POLICY_STATE_CODE = 'CA'",
  "query_result": [{"cnt": 1247}],
  "intent": "COUNT",
  "entities": ["Policy", "State"],
  "needs_clarification": false,
  "execution_time_ms": 832.5
}
```

**Response — Clarification needed (200)**

```json
{
  "session_id": "sess_abc123",
  "answer": "Which state are you asking about?",
  "needs_clarification": true,
  "execution_time_ms": 245.1
}
```

**Response — Error (500)**

```json
{
  "detail": "SQL execution timed out",
  "session_id": "sess_abc123"
}
```

---

### `WebSocket /ws` — Real-time streaming

Maintains a persistent connection with per-node progress updates.

**Client → Server**

```json
{
  "question": "Show me the top 5 agencies by premium volume",
  "session_id": "optional-session-id"
}
```

**Server → Client (progress)**

```json
{"type": "progress",  "message": "Understanding your question…",  "session_id": "sess_abc123"}
{"type": "progress",  "message": "Identifying intent…",           "session_id": "sess_abc123"}
{"type": "progress",  "message": "Extracting entities…",          "session_id": "sess_abc123"}
{"type": "progress",  "message": "Looking up schema…",            "session_id": "sess_abc123"}
{"type": "progress",  "message": "Generating SQL…",               "session_id": "sess_abc123"}
{"type": "progress",  "message": "Executing query…",              "session_id": "sess_abc123"}
{"type": "progress",  "message": "Formatting answer…",            "session_id": "sess_abc123"}
```

**Server → Client (final answer)**

```json
{
  "type": "final",
  "message": "Here are the top 5 agencies by premium volume: …",
  "session_id": "sess_abc123",
  "generated_sql": "SELECT TOP 5 …",
  "query_result": [],
  "intent": "LIST",
  "entities": ["Agency", "Premium"],
  "execution_time_ms": 1234.5
}
```

---

### `GET /health` — Health check

```json
{
  "status": "healthy",
  "neo4j_connected": true,
  "mssql_connected": true,
  "redis_connected": true
}
```

Returns `"degraded"` when any service is unreachable.

---

### Swagger / OpenAPI docs

| URL | Description |
|-----|-------------|
| `/docs` | Swagger UI (interactive) |
| `/redoc` | ReDoc (read-only) |
| `/openapi.json` | Raw OpenAPI spec |

---

## Configuration

All settings are loaded from environment variables or a `.env` file in the project root.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *required* | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | Chat model name |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | *required* | Neo4j password |
| `MSSQL_SERVER` | `localhost` | MSSQL host |
| `MSSQL_DATABASE` | `insurance_db` | MSSQL database name |
| `MSSQL_USER` | `sa` | MSSQL username |
| `MSSQL_PASSWORD` | *required* | MSSQL password |
| `MSSQL_DRIVER` | `ODBC Driver 17 for SQL Server` | ODBC driver string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `SPACY_MODEL` | `en_core_web_sm` | SpaCy model to load |
| `APP_NAME` | `Ontology Chatbot` | Display name in API docs |
| `APP_VERSION` | `1.0.0` | Semantic version |
| `DEBUG` | `false` | Enable debug logging |
| `SQL_RESULT_LIMIT` | `100` | Default TOP N for generated SQL |
| `REDIS_CACHE_TTL` | `300` | Cache TTL in seconds |
| `DB_SCHEMA` | `idp_stage` | Default SQL Server schema prefix |

---

## Project Structure

```text
ontology/
├── app/
│   ├── __init__.py
│   ├── config.py               # Pydantic-settings configuration
│   ├── main.py                 # FastAPI app, lifespan, middleware
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Pydantic request/response models
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── chat.py             # POST /ask  &  WebSocket /ws
│   │   └── health.py           # GET /health
│   ├── services/
│   │   ├── __init__.py
│   │   ├── neo4j_service.py    # Neo4j driver wrapper
│   │   ├── llm_service.py      # OpenAI / LangChain wrapper
│   │   ├── sql_service.py      # MSSQL query execution
│   │   └── redis_service.py    # Redis cache & session store
│   └── graph/
│       ├── __init__.py
│       ├── workflow.py         # LangGraph state graph definition
│       └── nodes/
│           ├── __init__.py
│           ├── input_processor.py
│           ├── intent_classifier.py
│           ├── entity_extractor.py
│           ├── clarity_checker.py
│           ├── graphrag_retriever.py
│           ├── ontology_lookup.py
│           ├── sql_generator.py
│           ├── sql_validator.py
│           ├── sql_executor.py
│           └── response_generator.py
├── ontology_definition.yaml    # Domain ontology (injected into LLM prompts)
├── neo4j_graph_schema.cypher   # Cypher to bootstrap the Neo4j graph
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

Private — all rights reserved.
