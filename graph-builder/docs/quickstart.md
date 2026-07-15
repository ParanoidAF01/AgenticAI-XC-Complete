# Running SKC — Your Setup Guide

> **Your stack**: MSSQL database · DDL file · Neo4j Aura · Anthropic-compatible LLM

---

## Step 1 — Install on Your Work Machine

```bash
# Clone / copy the project to your work machine
cd "Graph Builder"

# Install the package + dependencies
pip install -e ".[dev]"

# Install the MSSQL driver (pick one)
pip install pymssql          # simpler, no ODBC driver needed
# OR
pip install pyodbc           # if you already have ODBC Driver 18 installed
```

---

## Step 2 — Create Your Config File

Create `configs/settings.yaml` (this overrides defaults — **don't commit this file**):

```yaml
# Database Connection
connector:
  type: mssql
  # pymssql format:
  connection_string: "mssql+pymssql://USERNAME:PASSWORD@HOST:1433/DATABASE_NAME"
  # OR pyodbc format:
  # connection_string: "mssql+pyodbc://USERNAME:PASSWORD@HOST:1433/DATABASE_NAME?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
  
  # If you want to use DDL as the primary source (no live DB needed):
  # type: ddl_file
  # ddl_path: "/path/to/your/schema.sql"

# Neo4j Aura
neo4j:
  uri: "neo4j+s://xxxxxxxx.databases.neo4j.io"
  username: "neo4j"
  password: "YOUR_AURA_PASSWORD"
  database: "neo4j"

# LLM (Anthropic-compatible wrapper)
llm:
  provider: anthropic
  model: claude-sonnet-4-20250514
  temperature: 0.1
  max_tokens: 4096
  rate_limit_rpm: 30
  cache_responses: true

# Pipeline
pipeline:
  output_dir: ./output
  fail_fast: true

# Review
review:
  auto_approve_high: true
  mode: batch
```

---

## Step 3 — Set Your API Key

```bash
# For Anthropic:
export ANTHROPIC_API_KEY="your-api-key-here"

# If your company wrapper uses an OpenAI-compatible endpoint:
# export OPENAI_API_KEY="your-key"
# export OPENAI_API_BASE="https://your-company-proxy.com/v1"
```

---

## Step 4 — Run the Compiler

### Option A: DDL File Only (No Live DB Needed)

```bash
skc compile --source /path/to/your/schema.sql --output ./output
```

### Option B: Live MSSQL Connection

```bash
skc compile --source "mssql+pymssql://user:pass@host:1433/mydb" --output ./output
```

### Option C: DDL First, Then Live DB for Profiling

```bash
skc compile --source /path/to/schema.sql --output ./output --stages schema_parser schema_graph_builder
skc compile --source "mssql+pymssql://user:pass@host:1433/mydb" --resume ./output --output ./output
```

---

## Step 5 — Enable the Insurance Plugin (Optional)

```bash
skc compile --source /path/to/schema.sql --plugin insurance --output ./output
```

---

## Step 6 — Review the Results

```bash
skc inspect mir output/mir/database.jsonl
skc inspect kir output/kir/knowledge_graph.jsonl
skc graph stats --plan output/graph/cypher_plan.json
skc review --store output/review/candidates.sqlite
skc review-api --store output/review/candidates.sqlite --port 8000
```

---

## Step 7 — Query Your Knowledge Graph in Neo4j Aura

```cypher
MATCH (e:BusinessEntity)
RETURN e.name, e.description, e.entity_type, e.confidence_score
ORDER BY e.confidence_score DESC

MATCH (e1:BusinessEntity)-[r:RELATED_TO]->(e2:BusinessEntity)
RETURN e1.name, r.relationship_type, e2.name, r.cardinality

MATCH (m:Metric)
RETURN m.name, m.formula, m.formula_type, m.unit
```

---

## Output Directory Structure

```
output/
  mir/database.jsonl
  mir/profiles.jsonl
  kir/knowledge_graph.jsonl
  graph/cypher_plan.json
  review/candidates.sqlite
  reports/validation_report.json
  build_manifest.json
  build_report.json
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: pymssql` | `pip install pymssql` |
| MSSQL connection timeout | Add `?timeout=30` to connection string |
| `ANTHROPIC_API_KEY not set` | `export ANTHROPIC_API_KEY="sk-..."` |
| Neo4j Aura refused | URI must start with `neo4j+s://` (TLS required) |
| LLM rate limited | Lower `rate_limit_rpm` or set `cache_responses: true` |
| Skip LLM stages | `semantic_inferencer: {enabled: false}` in config |
| Resume failed build | `skc compile --resume ./output --source ...` |

---

## Quick Reference

```bash
skc compile --help
skc inspect mir <path>
skc inspect kir <path>
skc review
skc review-api
skc plugins list
skc graph stats
skc graph export
```
