# Ontology-Driven Insurance Database Chatbot

A production-ready, multi-user chatbot that translates natural language questions into SQL queries using an ontology graph (Neo4j), executes them against MSSQL business databases, and returns natural language answers via Anthropic LLM.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│  React + TS  │────▶│   FastAPI    │────▶│  PostgreSQL  │
│   Frontend   │◀────│   Backend    │◀────│  (App DB)    │
└──────────────┘     └──────┬───────┘     └─────────────┘
                            │
                     ┌──────┼──────┐
                     │      │      │
                     ▼      ▼      ▼
                  ┌─────┐┌─────┐┌─────┐
                  │Redis││Neo4j││MSSQL│
                  │Cache││Graph││ Biz  │
                  └─────┘└─────┘└─────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Anthropic  │
                     │     LLM     │
                     └─────────────┘
```

## Query Pipeline

1. **Router** — Classifies question as general_chat / simple_db / complex_db
2. **Ontology Context** — Retrieves entities, metrics, terms, relationships from Neo4j
3. **Planner** — LLM generates structured execution plan (tasks, filters, joins)
4. **Plan Validator** — Validates plan against ontology schema
5. **SQL Compiler** — Deterministically compiles plan tasks into T-SQL
6. **SQL Validator** — Compile-checks via `sp_describe_first_result_set` + LLM repair loop
7. **SQL Safety** — Blocks DML/DDL statements; enforces SELECT-only
8. **Executor** — Runs SQL against MSSQL with timeout
9. **Result Merger** — Combines multi-task results
10. **Answer Generator** — LLM produces natural language answer

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, TypeScript, Vite, TanStack Query, Zustand |
| Backend | FastAPI, SQLAlchemy 2.x (async), Pydantic v2 |
| App Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Ontology Graph | Neo4j Aura |
| Business Data | Microsoft SQL Server |
| LLM | Anthropic Claude |
| Auth | JWT (access + refresh tokens), bcrypt |
| Containers | Docker Compose |

## Prerequisites

- Docker & Docker Compose
- (Optional) Python 3.11+ and Node 20+ for local development
- Access to Neo4j instance with ontology data
- Access to MSSQL instance(s) with business data
- Anthropic API key

## Quick Start

### 1. Clone and configure

```bash
cd ontology-chatbot
cp .env.example .env
# Edit .env with your actual credentials
```

### 2. Start with Docker Compose

```bash
docker compose up --build
```

This starts:
- PostgreSQL on port 5432
- Redis on port 6379
- Backend API on http://localhost:8000
- Frontend on http://localhost:5173

### 3. Access the application

- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/health

## Local Development (Without Docker)

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis (via Docker or locally)
docker compose up postgres redis -d

# Run migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/signup` | Register new user |
| POST | `/api/v1/auth/login` | Login, get tokens |
| POST | `/api/v1/auth/refresh` | Rotate refresh token |
| POST | `/api/v1/auth/logout` | Revoke refresh token |
| GET | `/api/v1/auth/me` | Current user info |

### Chat
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chats` | Create session |
| GET | `/api/v1/chats` | List sessions |
| GET | `/api/v1/chats/{id}` | Get session |
| PATCH | `/api/v1/chats/{id}` | Update session |
| DELETE | `/api/v1/chats/{id}` | Delete session |
| GET | `/api/v1/chats/{id}/messages` | Get messages |
| POST | `/api/v1/chats/{id}/messages` | Send message |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/profiles` | Available DB profiles |
| GET | `/api/v1/health` | Health check |

## Database Schema

```
users ──────────┐
  │              │
  ├── chat_sessions ──── chat_messages
  │       │                    │
  │       ├── query_audits ────┘
  │       │
  │       └── session_context_summaries
  │
  └── refresh_tokens
```

## Environment Variables

See [.env.example](.env.example) for all configuration options.

## Project Structure

```
ontology-chatbot/
├── legacy/                    # Original Streamlit app (preserved)
│   ├── app_streamlit_legacy.py
│   └── README-legacy.md
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI route handlers
│   │   ├── core/              # Config, security, database, logging
│   │   ├── db/
│   │   │   ├── models/        # SQLAlchemy models
│   │   │   └── repositories/  # Data access layer
│   │   ├── services/          # Business logic services
│   │   ├── ontology/          # Neo4j repository
│   │   ├── query_engine/      # Extracted pipeline modules
│   │   ├── schemas/           # Pydantic request/response models
│   │   └── main.py            # FastAPI application
│   ├── tests/                 # Test suite
│   ├── alembic/               # Database migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/               # HTTP client & API functions
│   │   ├── components/        # React components
│   │   ├── pages/             # Page components
│   │   ├── hooks/             # Custom React hooks
│   │   ├── stores/            # Zustand stores
│   │   └── types/             # TypeScript types
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Testing

```bash
cd backend
pytest tests/ -v
```

## Legacy Application

The original Streamlit application is preserved in `legacy/app_streamlit_legacy.py` for reference and parity testing. See [legacy/README-legacy.md](legacy/README-legacy.md) for details.

## Security

- All credentials are server-side environment variables
- MSSQL connections use read-only accounts
- SQL execution is SELECT-only (DML/DDL blocked)
- JWT authentication with refresh token rotation
- Session/message/audit data is ownership-scoped
- No secrets exposed to frontend
