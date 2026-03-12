# Self-Healing ADF Pipeline System

An automated system that monitors Azure Data Factory pipelines, classifies errors using AI, and either auto-restarts pipelines or generates detailed resolution documents.

## Architecture

```
ADF Pipelines → Python Listener → Pinecone + Gemini → n8n → Auto-Restart / Notify
                                                         ↕
                                              Chainlit Chatbot (Developer UI)
```

## Quick Start

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure — edit .env with your API keys

# 3. Start n8n
docker run -d --name n8n -p 5678:5678 n8nio/n8n

# 4. Start the system
python start.py

# 5. Start the chatbot (new terminal)
source venv/bin/activate
chainlit run chatbot/app.py -w --port 8501
```

## Project Structure

```
├── config/              # Settings & metadata store
├── listener/            # ADF poller & doc generator
├── intelligence/        # Embeddings, classification, processing
├── chatbot/             # Chainlit RAG chatbot
├── tests/               # Test scripts
├── docs/                # Generated error documents
├── n8n/                 # n8n workflow data
├── start.py             # Master startup
└── requirements.txt     # Dependencies
```

## Error Types

| Type | Action |
|------|--------|
| 1 - Transient/Timeout | Auto-restart |
| 2 - Resource Contention | Auto-restart |
| 3 - Data Quality/Schema | Generate doc & notify |
| 4 - Auth/Permission | Generate doc & notify |
| 5 - Config/Deployment | Generate doc & notify |
| 6 - Logic/Transformation | Generate doc & notify |

## Testing

```bash
# Test Phase 1 & 2 (Pinecone + Gemini)
python tests/test_phase1_2.py

# Full system test (all 6 error types)
python tests/test_full_system.py
```
