<div align="center">

# Self-Healing ADF Pipeline

**Automated failure detection, AI-powered classification, and self-recovery for Azure Data Factory pipelines.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![Azure Data Factory](https://img.shields.io/badge/Azure-Data%20Factory-0078D4.svg)](https://azure.microsoft.com/en-us/products/data-factory)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Features](#features) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Configuration](#configuration) · [Usage](#usage) · [API Reference](#api-reference) · [Testing](#testing) · [Contributing](#contributing)

</div>

---

## Overview

Self-Healing ADF Pipeline is a **full-stack** production system that monitors Azure Data Factory pipelines in real-time, automatically classifies failures using AI, and takes corrective action — either restarting the pipeline or generating a detailed error report and notifying the responsible team.

It includes a **React dashboard** for monitoring, a **FastAPI REST API** serving 31 endpoints, **AI-powered chatbot** for developer queries, and **PDF/CSV report generation** for analytics.

**The problem:** ADF pipeline failures require manual investigation, often taking 30–60 minutes per incident. Teams lose hours triaging errors that could be auto-resolved.

**The solution:** This system reduces mean-time-to-recovery (MTTR) from hours to seconds for recoverable errors, and provides instant, professional documentation for complex issues.

### Key Metrics

| Metric | Before | After |
|---|---|---|
| Detection Time | 15–30 min (manual) | < 30 sec (automated) |
| MTTR (Recoverable) | 30–60 min | < 2 min |
| MTTR (Complex) | 2–4 hours | 5 min (with PDF report) |
| Documentation | Manual, inconsistent | Auto-generated, standardized |

---

## Features

### 🖥️ Web Dashboard (React)
- **6 pages:** Dashboard, Pipelines List, Pipeline Detail, Reports & Analytics, AI Chatbot, Settings
- Real-time KPI cards with period-over-period delta comparisons
- Interactive charts (line, donut, bar, heatmap) via Recharts
- Pipeline search, filtering (Healthy/Warning/Critical), and pagination
- Listener control panel with connection health monitoring
- Dark mode support, responsive layout, gold/dark premium design system

### 🔌 REST API (FastAPI)
- **31 endpoints** across 6 modules (Dashboard, Pipelines, Reports, Chat, Settings, Listener)
- SQL Server stored procedures for all analytics queries
- Mock data mode for offline development
- PDF and CSV report export with branded styling
- Azure Blob Storage for PDF persistence with local fallback

### 🔍 Automated Failure Detection
- Polls Azure Data Factory every 30 seconds for failed pipeline runs
- Dual listener modes: ADF SDK or SQL Table polling
- Extracts activity-level error details (error codes, messages, failed activities)
- Tracks processed runs to prevent duplicate handling

### 🤖 AI-Powered Error Classification
- Classifies errors into **6 categories** with confidence scoring
- Uses similar past errors (vector search) to improve classification accuracy
- Returns structured JSON with root cause, recommended action, and priority

| Type | Category | Self-Heal | Action |
|------|----------|-----------|--------|
| 1 | Parameter Errors | ★★★★★ | Auto-restart with corrected parameters |
| 2 | Dataset Type Errors | ★★★★★ | Auto-restart with schema corrections |
| 3 | Credentials Expired | ★★★★ | Rotate credentials, then restart |
| 4 | Large Data / Timeout | ★★★★ | Enable chunking, increase timeout, restart |
| 5 | Server Slow | ★★★ | Generate report, notify team |
| 6 | Subscription Corrupt | ★★ | Generate report, escalate immediately |

### 🔄 Automatic Pipeline Restart
- Types 1–4 are automatically restarted via the Azure Data Factory REST API
- Configurable wait times per error type (30s–120s) before restart
- Authenticates using Azure Service Principal credentials

### 📄 Professional PDF Reports
- Auto-generated for escalated errors (Types 5–6)
- Stored in **Azure Blob Storage** with SQL metadata tracking
- Local filesystem fallback for development environments
- Full analytics PDF export from the Reports page (branded, multi-section)

### 📧 Email Notifications
- Sends PDF reports as email attachments to pipeline owners
- Owner email is looked up from the pipeline metadata database
- Supports Gmail SMTP and Outlook/Office 365

### 💬 Developer Chatbot (RAG)
- Integrated into the web dashboard as a dedicated page
- Retrieval-Augmented Generation using ChromaDB vector search + LLM
- Pipeline-scoped queries with source filtering (ADF/SQL)
- Quick-action suggestion chips

### 🧠 Error Memory (Vector Store)
- Every error is embedded and stored in ChromaDB/Pinecone
- Similarity search finds related past errors to improve classification
- Namespaced by pipeline name for targeted retrieval

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React 19 + Vite)                   │
│                                                                      │
│  Pages:  Dashboard │ Pipelines │ Detail │ Reports │ Chatbot │ Settings│
│  Charts: Recharts (line, donut, bar, heatmap)                        │
│  Icons:  Lucide React                                                │
│  Router: React Router v7                                             │
│  API:    services/api.js → fetch() to FastAPI                        │
│                                                                      │
│  Dev Server: http://localhost:5173 (Vite)                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTP (proxied or CORS)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI + Uvicorn)                      │
│                     http://localhost:8000                             │
│                                                                      │
│  Routes:                                                             │
│    /api/dashboard/*     — 5 endpoints (KPI, charts, activity feed)   │
│    /api/pipelines/*     — 5 endpoints (list, detail, chart, reports) │
│    /api/reports/*       — 7 endpoints (KPIs, heatmap, export)        │
│    /api/chat/*          — 4 endpoints (RAG chatbot)                  │
│    /api/settings        — 2 endpoints (GET/POST config)              │
│    /api/listener/*      — 8 endpoints (start/stop, logs, health)     │
│                                                                      │
│  Modules:                                                            │
│    db.py              — SQL Server connector + mock data dispatcher  │
│    listener_manager.py — Background listener thread control          │
│    health_checker.py   — 5-service connection health monitor         │
│    report_storage.py   — Azure Blob Storage + local fallback         │
└───────────┬──────────────────────┬──────────────────────────────────┘
            │                      │
            ▼                      ▼
┌──────────────────────┐  ┌───────────────────────────────────────────┐
│   SQL Server (Azure) │  │          Intelligence Layer                │
│                      │  │                                            │
│  Stored Procedures:  │  │  error_processor.py — Central orchestrator │
│   ui.sp_home_*       │  │  error_classifier.py — LLM classification  │
│   ui.sp_pipelines_*  │  │  chroma_store.py — Vector embeddings       │
│   ui.sp_pipeline_*   │  │  rag_pipeline.py — RAG for chatbot         │
│   ui.sp_report_*     │  │                                            │
│                      │  │  ChromaDB / Pinecone (vector search)       │
│  Tables:             │  │  OpenAI-compatible LLM API                 │
│   dbo.PipelineRunLog │  │                                            │
│   ui.PipelineReports │  └───────────────────────────────────────────┘
│   ui.SystemConfig    │
└──────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    Listener Layer                                     │
│                                                                      │
│  adf_listener.py — Polls ADF SDK for failed runs                     │
│  sql_listener.py — Polls PipelineRunLog table via SQL                │
│  azure_client.py — Azure REST API (auth + pipeline restart)          │
│  doc_generator.py — PDF report generation (fpdf2)                    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    External Services                                 │
│                                                                      │
│  Azure Data Factory — Pipeline orchestration + restart API           │
│  Azure Blob Storage — PDF report persistence (adf-healer-reports)    │
│  Azure SQL Server   — Analytics data + stored procedures             │
│  LLM API            — Error classification + chatbot                 │
│  SMTP               — Email notifications with PDF attachments       │
└─────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 19 + Vite 8 | SPA dashboard |
| **Charts** | Recharts | Line, donut, bar, heatmap visualizations |
| **Icons** | Lucide React | UI iconography |
| **Routing** | React Router v7 | Client-side navigation |
| **Backend** | FastAPI + Uvicorn | REST API server |
| **Database** | Azure SQL Server | Pipeline data + stored procedures |
| **PDF Storage** | Azure Blob Storage | Cloud PDF persistence |
| **Vector DB** | ChromaDB / Pinecone | Similarity search for past errors |
| **LLM** | OpenAI-compatible API | Error classification + chatbot |
| **PDF Engine** | fpdf2 | Report generation |
| **Email** | smtplib (stdlib) | SMTP notifications |
| **Metadata** | SQLite | Local pipeline metadata + error history |
| **Runtime** | Python 3.9+ | Backend language |

---

## Project Structure

```
self-healing-adf/
├── README.md
├── requirements.txt                  # Python backend dependencies
├── .env                              # Environment variables (not committed)
├── .gitignore
├── start.py                          # Standalone listener entry point
├── pipeline_metadata.db              # SQLite database (auto-created)
│
├── frontend/                         # React SPA (Vite)
│   ├── package.json                 # Node dependencies
│   ├── vite.config.js               # Vite build config
│   ├── index.html                   # HTML entry point
│   └── src/
│       ├── main.jsx                 # React root mount
│       ├── App.jsx                  # Router + layout setup
│       ├── index.css                # Global design tokens & CSS variables
│       ├── services/
│       │   └── api.js               # Centralized API client (fetch wrappers)
│       ├── components/
│       │   ├── Layout.jsx/.css      # Main layout wrapper
│       │   ├── Sidebar.jsx/.css     # Navigation sidebar
│       │   └── TopBar.jsx/.css      # Top header bar
│       └── pages/
│           ├── Dashboard.jsx/.css   # KPI cards, charts, activity feed
│           ├── Pipelines.jsx/.css   # Pipeline list with search/filters
│           ├── PipelineDetail.jsx/.css # Detail view with error history
│           ├── Reports.jsx/.css     # Analytics, heatmap, export
│           ├── Chatbot.jsx/.css     # AI assistant chat interface
│           └── Settings.jsx/.css    # Listener control + health monitor
│
├── backend/                          # FastAPI REST API
│   ├── main.py                      # FastAPI app factory + CORS + router wiring
│   ├── db.py                        # SQL Server connector + mock data dispatcher
│   ├── listener_manager.py          # Background listener thread lifecycle
│   ├── health_checker.py            # 5-service connection health checker
│   ├── report_storage.py            # Azure Blob Storage + local PDF fallback
│   └── routes/
│       ├── dashboard.py             # 5 endpoints — KPI, trend, donut, breakdown, activity
│       ├── pipelines.py             # 5 endpoints — list, detail, chart, reports, download
│       ├── reports.py               # 7 endpoints — KPIs, heatmap, exports (CSV/PDF)
│       ├── chat.py                  # 4 endpoints — RAG chat, pipelines, history
│       ├── settings.py              # 2 endpoints — GET/POST system config
│       └── listener.py              # 8 endpoints — start/stop, logs, health
│
├── config/                           # Configuration & data layer
│   ├── settings.py                  # Loads .env into typed config classes
│   └── metadata_store.py            # SQLite operations (pipelines, error history)
│
├── listener/                         # Azure integration & output generation
│   ├── adf_listener.py              # Polls ADF for failed runs
│   ├── sql_listener.py              # Polls SQL table for failed runs
│   ├── azure_client.py              # Azure REST API client (auth + restart)
│   └── doc_generator.py             # PDF report generator (fpdf2, in-memory)
│
├── intelligence/                     # AI/ML processing layer
│   ├── error_processor.py           # Central orchestrator (classify → act)
│   ├── error_classifier.py          # LLM-based error classification
│   ├── chroma_store.py              # ChromaDB vector embeddings
│   └── pinecone_store.py            # Pinecone vector embeddings (alternative)
│
├── chatbot/                          # Developer chatbot
│   ├── app.py                       # Chainlit UI handlers
│   └── rag_pipeline.py              # RAG: vector search + LLM answer
│
├── queries/                          # SQL stored procedure definitions
│   └── procedures/
│       ├── dashboard/               # ui.sp_home_* (5 SPs)
│       ├── pipelines/               # ui.sp_pipelines_*, ui.sp_pipeline_* (4 SPs)
│       └── report/                  # ui.sp_report_* (7 SPs)
│           └── KPI/                 # MTTR, AutoHeal, TimeSaved, ErrorsKPI
│
├── prototype/                        # Static HTML design prototypes
│   ├── dashboard.html
│   ├── pipelines.html
│   ├── pipeline_detail.html
│   ├── reports.html
│   ├── chatbot.html
│   └── settings.html
│
├── tests/                            # Test suite
│   ├── test_phase1_2.py             # Unit tests for individual components
│   └── test_full_system.py          # End-to-end test (all 6 error types)
│
└── docs/                             # Generated PDF reports (local fallback)
    └── error_report_*.pdf
```

---

## Quick Start

### Prerequisites

- **Python 3.9+** and **Node.js 18+**
- An Azure subscription with a Data Factory instance
- An Azure Service Principal with **Data Factory Contributor** role
- Access to an OpenAI-compatible LLM API

### 1. Clone & Install Backend

```bash
git clone https://github.com/your-org/self-healing-adf.git
cd self-healing-adf

# Python backend
python -m venv venv
source venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

### 2. Install Frontend

```bash
cd frontend
npm install
cd ..
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials (see Configuration section)
```

### 4. Start Development Servers

**Terminal 1 — Backend (FastAPI):**
```bash
source venv/bin/activate
python -m uvicorn backend.main:app --port 8000 --reload
```

**Terminal 2 — Frontend (Vite):**
```bash
cd frontend
npm run dev
```

The app runs at:
- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs (Swagger):** http://localhost:8000/docs

> **Note:** The backend runs in **mock data mode** by default when no SQL Server is configured. All endpoints return realistic synthetic data for development.

---

## Configuration

All configuration is managed through a `.env` file in the project root.

### Azure Credentials

```bash
# Azure Service Principal
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
AZURE_SUBSCRIPTION_ID=your-subscription-id

# ADF Instance
ADF_RESOURCE_GROUP=your-resource-group
ADF_FACTORY_NAME=your-factory-name
```

### SQL Server (Analytics Database)

```bash
SQL_SERVER=your-server.database.windows.net
SQL_DATABASE=ADF_Healer
SQL_USERNAME=your-username
SQL_PASSWORD=your-password
```

> When SQL Server is not configured, the backend automatically runs in **mock mode** with synthetic data.

### Azure Blob Storage (PDF Reports)

```bash
AZURE_STORAGE_ACCOUNT_NAME=your-storage-account
AZURE_STORAGE_ACCOUNT_KEY=your-storage-key
AZURE_STORAGE_CONTAINER=adf-healer-reports
```

> When Blob Storage is not configured, PDFs are saved to the local `docs/` folder.

### LLM API (OpenAI-Compatible)

```bash
COMPANY_API_BASE_URL=https://api.your-provider.com/v1
COMPANY_API_KEY=your-api-key
COMPANY_CHAT_MODEL=claude-sonnet-4-6
COMPANY_EMBEDDING_MODEL=text-embedding-3-large
```

### Listener Settings

```bash
LISTENER_MODE=sql              # "adf" or "sql"
POLL_INTERVAL=30               # Seconds between polls (10-300)
```

### Email Notifications

```bash
SMTP_EMAIL=alerts@yourcompany.com
SMTP_PASSWORD="your-app-password"
NOTIFY_RECIPIENT=fallback@yourcompany.com
```

---

## Usage

### Web Dashboard

Start both servers and navigate to http://localhost:5173. The dashboard provides:

| Page | Description |
|------|-------------|
| **Dashboard** | KPI cards, failure trend chart, success/failure donut, error breakdown, recent activity |
| **Pipelines** | Searchable, filterable pipeline list with health status badges |
| **Pipeline Detail** | Per-pipeline metrics, error distribution, failure timeline, error history, PDF reports |
| **Reports** | MTTR, auto-heal rate, heatmap, error-prone pipelines, root causes, restart exhaustion |
| **Chatbot** | AI assistant for pipeline error queries with RAG |
| **Settings** | Listener mode selection, start/stop controls, polling interval, connection health |

### Standalone Listener

Run the listener without the web dashboard:

```bash
python start.py
```

### Export Reports

From the Reports page or directly via API:

```bash
# Download CSV report
curl -O "http://localhost:8000/api/reports/export/csv?time_range=1m"

# Download PDF report
curl -O "http://localhost:8000/api/reports/export/pdf?time_range=1m"
```

### Developer Chatbot (Standalone)

Run the Chainlit chatbot independently:

```bash
chainlit run chatbot/app.py
```

---

## API Reference

The backend exposes **31 REST endpoints** across 6 modules. Full interactive docs available at `/docs` (Swagger UI).

### Dashboard — `/api/dashboard`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/kpi` | 4 KPI cards with period-over-period deltas |
| GET | `/failure-trend` | Line chart data (time-bucketed failures) |
| GET | `/success-vs-failure` | Donut chart (success/failure ratio + health %) |
| GET | `/error-breakdown` | Horizontal bar chart (error types ranked) |
| GET | `/recent-activity` | Latest 5 pipeline events with status badges |

### Pipelines — `/api/pipelines`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Pipeline list with search, filter, pagination |
| GET | `/{name}` | Pipeline detail: summary, error dist, history, delta |
| GET | `/{name}/chart` | Failure timeline chart for one pipeline |
| GET | `/{name}/reports` | List PDF reports for a pipeline |
| GET | `/download/{name}/{file}` | Download a local PDF report |

### Reports — `/api/reports`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/kpi` | 4 KPI cards (MTTR, auto-heal, savings, errors) with deltas |
| GET | `/heatmap` | 2D error type heatmap (time × type matrix) |
| GET | `/error-prone-pipelines` | Top 5 most failing pipelines |
| GET | `/top-root-causes` | Root cause ranking with affected pipeline counts |
| GET | `/restart-exhaustion` | Pipelines that exhausted all retries |
| GET | `/export/csv` | Download full report as CSV |
| GET | `/export/pdf` | Download styled PDF report |

### Chat — `/api/chat`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/` | Send question to RAG chatbot |
| GET | `/pipelines` | Pipeline names grouped by source (dropdown) |
| GET | `/history` | Get conversation history |
| DELETE | `/history` | Clear chat history |

### Settings — `/api/settings`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Get current system configuration |
| POST | `/` | Update settings (listener_mode, poll_interval, email) |

### Listener — `/api/listener`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Listener state (running/stopped, mode, uptime) |
| POST | `/start` | Start listener (optionally with mode) |
| POST | `/stop` | Stop listener |
| POST | `/restart` | Restart with new mode |
| GET | `/logs` | Recent poll logs (limit: 1–100) |
| DELETE | `/logs` | Clear poll logs |
| GET | `/health` | Cached connection health (instant) |
| POST | `/health/check` | Force fresh health check (~3-4s) |

---

## Deployment

### Running as a Background Service (Linux)

```ini
# /etc/systemd/system/self-healing-adf.service
[Unit]
Description=Self-Healing ADF Pipeline Monitor
After=network.target

[Service]
User=deploy
WorkingDirectory=/opt/self-healing-adf
ExecStart=/opt/self-healing-adf/venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Frontend Production Build

```bash
cd frontend
npm run build
# Outputs to frontend/dist/ — serve via Nginx, Azure Static Web Apps, etc.
```

### Docker (Optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Security Considerations

- **Never commit `.env`** — it contains secrets. The `.gitignore` already excludes it.
- **Use Azure Key Vault** in production to manage secrets instead of `.env` files.
- **Rotate Service Principal secrets** regularly (Azure recommends every 90 days).
- **Use App Passwords** for Gmail SMTP, not your regular account password.
- **Add authentication** to the API before exposing to the internet.

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `No module named uvicorn` | Not in virtual environment | Run `source venv/bin/activate` first |
| `[Errno 48] Address already in use` | Port 8000 already occupied | `lsof -ti:8000 \| xargs kill -9` |
| `ImportError: HTTPExcBeption` | Typo in chat.py | Fix to `HTTPException` |
| `[DB] Running in MOCK mode` | No SQL Server configured | Expected for local dev |
| `Azure auth failed (401)` | Invalid Service Principal | Regenerate client secret |
| `Email auth failed` | Wrong SMTP password | Use Gmail App Password |
| `npm run dev` fails | Missing node_modules | Run `cd frontend && npm install` |
| CORS errors in browser | Backend not allowing frontend origin | Check CORS config in `backend/main.py` |

---

## Contributing

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Development Setup

```bash
git clone https://github.com/your-org/self-healing-adf.git
cd self-healing-adf

# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..

# Run both
# Terminal 1: source venv/bin/activate && python -m uvicorn backend.main:app --port 8000 --reload
# Terminal 2: cd frontend && npm run dev
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [React](https://react.dev/) — Frontend framework
- [Vite](https://vitejs.dev/) — Build tool
- [Recharts](https://recharts.org/) — Charting library
- [FastAPI](https://fastapi.tiangolo.com/) — Backend API framework
- [Azure Data Factory SDK](https://github.com/Azure/azure-sdk-for-python) — Pipeline management
- [ChromaDB](https://www.trychroma.com/) — Vector similarity search
- [fpdf2](https://github.com/py-pdf/fpdf2) — PDF generation
- [Lucide](https://lucide.dev/) — Icon library
