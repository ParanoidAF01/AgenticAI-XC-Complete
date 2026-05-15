# Tiered Error Classification — HLD & LLD

## Problem Statement

The current system calls the LLM for **every** error, even when the error code is already known and has a deterministic resolution in the CSV knowledge base. This is slow (~2-5s), costly ($0.01-0.05/call), and unnecessary for ~85% of errors.

The user has a comprehensive CSV (`adf_errors_v3`) with columns: `category`, `error_code`, [message](file:///Users/anmolgupta/.gemini/antigravity/playground/rapid-planetary/self-healing-adf/chatbot/app.py#31-54), `cause`, `recommendation`, `resolution` — covering most known ADF error types.

---

## High-Level Design (HLD)

### Architecture: 3-Layer Classification Pipeline

```
  Error Detected by ADF Listener
              │
              ▼
  ┌───────────────────────────┐
  │  LAYER 1 — CSV Lookup     │  Speed: ~10ms  |  Cost: $0
  │  (Deterministic)           │
  │                           │
  │  Match on: error_code     │
  │  Fallback: keyword match  │
  │  on error message         │
  │                           │
  │  Output: category, cause, │
  │  resolution, our_type(1-6)│
  └─────────┬─────────────────┘
            │
       ┌────┴────┐
     MATCH     NO MATCH
       │          │
       ▼          ▼
  Use CSV      ┌───────────────────────────┐
  resolution   │  LAYER 2 — Pinecone       │  Speed: ~200ms  |  Cost: $0
  directly.    │  (Semantic Similarity)     │
  Confidence   │                           │
  = 1.0        │  Embed current error msg  │
               │  Search top-5 similar     │
               │  If best score > 0.90     │
               │  AND 3/5 agree on type    │
               │  → use that type          │
               └─────────┬─────────────────┘
                         │
                    ┌────┴────┐
                  MATCH     NO MATCH
                    │          │
                    ▼          ▼
               Use Pinecone ┌───────────────────────────┐
               consensus.   │  LAYER 3 — LLM            │  Speed: ~3s
               Confidence   │  (Reasoning Fallback)     │  Cost: $0.01
               = top score  │                           │
                            │  Full prompt with:        │
                            │  - Error details          │
                            │  - Similar errors (L2)    │
                            │  - Pipeline metadata      │
                            │  - CSV near-matches       │
                            │                           │
                            │  For truly novel errors   │
                            └───────────────────────────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │  FEEDBACK LOOP    │
                              │                  │
                              │  Store result in │
                              │  Pinecone + CSV  │
                              │  for future L1/2 │
                              │  matches         │
                              └──────────────────┘
```

### Expected Traffic Distribution

| Layer | % of Errors Handled | Avg Latency | Cost |
|-------|-------------------|-------------|------|
| L1 — CSV Lookup | ~70-85% | 10ms | $0 |
| L2 — Pinecone | ~10-20% | 200ms | $0 |
| L3 — LLM | ~2-10% | 3s | $0.01/call |

### CSV-to-Type Mapping

The CSV categories need to be mapped to our 6 self-healing types:

| CSV Category | Our Type | Action |
|---|---|---|
| Azure Databricks (auth/token errors) | Type 3 — Credentials Expired | Auto-restart |
| Azure Databricks (cluster/config errors) | Type 1 — Parameter Errors | Auto-restart |
| Azure Databricks (throttling errors) | Type 4 — Large Data / Timeout | Auto-restart |
| Data Lake Analytics | Type 1 — Parameter Errors | Auto-restart |
| Azure Functions (config errors) | Type 1 — Parameter Errors | Auto-restart |
| Azure Functions (endpoint errors) | Type 2 — Dataset Type Errors | Auto-restart |
| Azure Machine Learning | Type 1 — Parameter Errors | Auto-restart |
| JSON (linked service/format errors) | Type 2 — Dataset Type Errors | Auto-restart |
| JSON (credential errors) | Type 3 — Credentials Expired | Auto-restart |
| *(unmappable / ambiguous)* | → Layer 2 or 3 | Depends |

> [!IMPORTANT]
> The exact CSV → Type mapping needs user review. Some errors could be Type 1 or Type 2. We'll create a mapping file the user can review and adjust.

---

## Low-Level Design (LLD)

### File Changes Overview

```
self-healing-adf/
├── config/
│   ├── settings.py              [MODIFY] Add CSV path config
│   └── knowledge_base.py        [NEW]    CSV loader + error code lookup
│
├── intelligence/
│   ├── error_classifier.py      [MODIFY] → Becomes Layer 3 only
│   ├── pinecone_store.py        [MODIFY] → Add consensus logic for Layer 2
│   ├── error_processor.py       [MODIFY] → Orchestrate 3 layers
│   └── tiered_classifier.py     [NEW]    → Central router: L1 → L2 → L3
│
├── data/
│   ├── adf_errors_v3.csv        [NEW]    User's CSV knowledge base
│   └── category_type_map.json   [NEW]    CSV category → our Type (1-6) mapping
│
└── tests/
    └── test_full_system.py      [MODIFY] Test all 3 layers
```

---

### [NEW] `config/knowledge_base.py` — Layer 1 Engine

**Responsibility:** Load CSV into memory, provide instant lookup by error code and keyword matching.

```python
class KnowledgeBase:
    """
    In-memory error knowledge base loaded from CSV.
    Provides O(1) lookup by error_code and keyword-based fuzzy matching.
    """

    def __init__(self, csv_path, type_map_path):
        # Load CSV into:
        #   self.by_code: dict[str, ErrorEntry]  — exact code lookup
        #   self.by_keyword: list[KeywordEntry]  — for keyword matching
        #   self.type_map: dict[str, int]        — CSV category → our type

    def lookup_by_code(self, error_code: str) -> Optional[dict]:
        """
        O(1) lookup. Returns category, cause, resolution, our_type.
        Returns None if error_code not found.
        """

    def lookup_by_keywords(self, error_message: str) -> Optional[dict]:
        """
        Tokenize error message → match against known error messages.
        Uses TF-IDF or simple word overlap scoring.
        Returns best match if similarity > threshold (0.70).
        Returns None if no confident match.
        """

    def add_new_error(self, error_code, message, category, cause, resolution):
        """
        Feedback loop: add a newly classified error to the KB
        for future Layer 1 matching.
        """
```

**Key design decisions:**
- CSV loaded once at startup, held in memory (fast)
- `by_code` dict for exact matches (primary)
- `by_keywords` uses simple word overlap (no ML needed) — tokenize, remove stopwords, compute Jaccard similarity against all known messages
- Threshold: 0.70 for keyword match (tunable)

---

### [NEW] `intelligence/tiered_classifier.py` — Orchestrator

**Responsibility:** Routes through L1 → L2 → L3, returns a unified result.

```python
def classify_tiered(error_details: dict, pipeline_metadata: dict = None) -> dict:
    """
    3-layer classification. Returns:
    {
        "error_type": int,
        "error_type_name": str,
        "confidence": float,
        "root_cause_summary": str,
        "is_auto_recoverable": bool,
        "recommended_action": str,
        "priority": str,
        "classified_by": "layer_1_exact" | "layer_1_keyword" | "layer_2_pinecone" | "layer_3_llm",
        "csv_resolution": str | None   # From CSV if available
    }
    """

    error_code = extract_error_code(error_details)  # Parse from error message
    error_message = error_details.get("combined_error", "")

    # ── Layer 1: CSV Lookup ──
    if error_code:
        result = knowledge_base.lookup_by_code(error_code)
        if result:
            return format_result(result, confidence=1.0, source="layer_1_exact")

    result = knowledge_base.lookup_by_keywords(error_message)
    if result:
        return format_result(result, confidence=result["score"], source="layer_1_keyword")

    # ── Layer 2: Pinecone Consensus ──
    similar = search_similar_errors(error_message, namespace=pipeline_name, top_k=5)
    consensus = compute_consensus(similar)
    if consensus and consensus["confidence"] >= 0.90:
        return format_result(consensus, source="layer_2_pinecone")

    # ── Layer 3: LLM Fallback ──
    llm_result = classify_error(error_details, similar, pipeline_metadata)
    llm_result["classified_by"] = "layer_3_llm"

    # Feedback: store new error for future L1/L2 matching
    knowledge_base.add_new_error(...)
    store_error(...)  # Pinecone

    return llm_result
```

---

### [MODIFY] [intelligence/pinecone_store.py](file:///Users/anmolgupta/.gemini/antigravity/playground/rapid-planetary/self-healing-adf/intelligence/pinecone_store.py) — Add Consensus Logic

New function for Layer 2 decision-making:

```python
def compute_consensus(similar_errors: list, score_threshold=0.90) -> Optional[dict]:
    """
    Given top-K similar errors, determine if there's consensus.

    Rules:
    - Best match score must be >= score_threshold
    - At least 3 of top 5 must agree on the same error_type
    - Returns the majority type with averaged confidence

    Returns None if no consensus (→ falls through to Layer 3).
    """
```

---

### [MODIFY] [intelligence/error_processor.py](file:///Users/anmolgupta/.gemini/antigravity/playground/rapid-planetary/self-healing-adf/intelligence/error_processor.py) — Use Tiered Classifier

Replace the current classification call:

```diff
-    classification = classify_error(error_details, similar_errors, pipeline_metadata)
+    classification = classify_tiered(error_details, pipeline_metadata)
+    print(f"   [CLASSIFY] {classification['classified_by']}: "
+          f"Type {classification['error_type']} - Confidence: {classification['confidence']}")
```

The processor no longer needs to call [search_similar_errors](file:///Users/anmolgupta/.gemini/antigravity/playground/rapid-planetary/self-healing-adf/intelligence/pinecone_store.py#85-111) separately — `tiered_classifier` handles it internally.

---

### [NEW] `data/category_type_map.json` — Mapping File

User-reviewable mapping from CSV categories to our 6 types:

```json
{
  "Azure Databricks": {
    "default_type": 1,
    "overrides": {
      "3200": 3,
      "3201_auth": 3,
      "3202_throttle": 4
    }
  },
  "Data Lake Analytics": {
    "default_type": 1
  },
  "Azure Functions": {
    "default_type": 1,
    "overrides": {
      "3602_invalid_method": 2,
      "3610_bad_endpoint": 2
    }
  },
  "Azure Machine Learning": {
    "default_type": 1,
    "overrides": {
      "4121_credential": 3,
      "4122_credential": 3
    }
  },
  "JSON": {
    "default_type": 2,
    "overrides": {
      "4121_credential": 3,
      "4122_credential": 3
    }
  }
}
```

> [!IMPORTANT]
> This mapping file is the **most critical piece** for accuracy. It determines which action is taken for each error code. It should be reviewed carefully before going live.

---

### Error Code Extraction

Many ADF errors embed the error code in the message. We need a parser:

```python
def extract_error_code(error_details: dict) -> Optional[str]:
    """
    Extract error code from error details.
    Tries multiple sources:
    1. error_details["failed_activities"][0]["error_code"]  (direct)
    2. Regex on error message: r'Error (\d{4})'
    3. Regex on error message: r'error_code["\s:]+(\d+)'
    """
```

---

## Verification Plan

### Automated Tests

Update [tests/test_full_system.py](file:///Users/anmolgupta/.gemini/antigravity/playground/rapid-planetary/self-healing-adf/tests/test_full_system.py) to test all 3 layers:

```bash
python tests/test_full_system.py
```

**Test cases:**
1. **Layer 1 Exact** — Error with code `3200` → should skip LLM, return Type 3 from CSV
2. **Layer 1 Keyword** — Error message matching a CSV entry but no code → keyword match
3. **Layer 2 Pinecone** — Unknown error similar to past errors → Pinecone consensus
4. **Layer 3 LLM** — Completely novel error → LLM fallback
5. **Feedback loop** — After Layer 3 classifies a new error, re-run the same error → should be caught by Layer 2 now
6. **Verify all 6 types still work** — Same 6 error scenarios as before

### Manual Verification

1. Run `python start.py` and trigger a real ADF failure
2. Check terminal output for `[CLASSIFY] layer_1_exact:` vs `layer_3_llm:` — confirming the tiered routing
3. Verify the pipeline still restarts or generates PDF correctly after tiered classification

> [!NOTE]
> The user needs to provide the actual `adf_errors_v3.csv` file and review the `category_type_map.json` mapping before testing.
