"""
Tiered Classifier — The central orchestrator for the 3-layer classification pipeline.

Routes errors through:
  L1a: CSV exact match by error_code        (~10ms, $0)
  L1b: CSV keyword match via TF-IDF         (~50ms, $0)
  L2:  ChromaDB consensus (3/5 must agree)  (~200ms, $0)
  L3:  LLM fallback (for truly novel errors) (~3s, $0.01)

After L3 classifies a novel error, the result is stored back into:
  - CSV knowledge base (L1 for next time)
  - ChromaDB (L2 for next time)

This module replaces direct calls to classify_error() in error_processor.py.
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.knowledge_base import get_knowledge_base
from intelligence.chroma_store import (
    search_similar_errors, store_error, compute_consensus
)
from intelligence.error_classifier import classify_error
from config.settings import KnowledgeBaseConfig


def extract_error_code(error_details: dict) -> str:
    """
    Extract the most likely error code from the error details.

    Checks (in order):
      1. error_details["error_code"] if present
      2. First failed activity's error code
      3. Regex pattern from the combined error message
    """
    # Direct field
    code = error_details.get("error_code", "")
    if code:
        return str(code).strip()

    # From failed activities
    activities = error_details.get("failed_activities", [])
    if activities:
        for act in activities:
            code = act.get("error_code", "") or act.get("errorCode", "")
            if code:
                return str(code).strip()

    # Regex fallback: look for common ADF error code patterns in the message
    message = error_details.get("combined_error", "")
    if message:
        # Match patterns like "Error 3200", "error_code: 3200", "ErrorCode=3200"
        patterns = [
            r'Error\s+(\d{3,5})',
            r'error[_\s]?code[:\s=]+["\']?(\w+)',
            r'AADSTS(\d+)',
            r'(\d{4,5})\s*[-:]\s*\w+Error',
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).strip()

    return ""


def extract_category(error_details: dict) -> str:
    """
    Try to extract the error category from the error details.
    Falls back to empty string if not determinable.
    """
    # Direct field
    cat = error_details.get("category", "")
    if cat:
        return cat.strip()

    # From failed activities
    activities = error_details.get("failed_activities", [])
    if activities:
        for act in activities:
            act_type = act.get("activityType", "") or act.get("activity_type", "")
            if act_type:
                return act_type.strip()

    return ""


def classify_tiered(error_details: dict,
                    pipeline_metadata: dict = None) -> dict:
    """
    3-layer tiered error classification.

    Flow:
      L1a → L1b → L2 → L3 (with feedback loop after L3)

    Args:
        error_details: Dict with pipeline_name, combined_error, failed_activities, etc.
        pipeline_metadata: Optional pipeline metadata from SQLite.

    Returns:
        Classification result dict with standard fields plus 'classified_by'.
    """
    pipeline_name = error_details.get("pipeline_name", "unknown")
    error_text = error_details.get("combined_error", "")
    error_code = extract_error_code(error_details)
    category = extract_category(error_details)

    kb = get_knowledge_base()

    # ── Layer 1a: Exact code match ─────────────────────────────
    if error_code:
        print(f"   [L1a] Trying exact code lookup: '{error_code}' (category: '{category}')...")
        result = kb.lookup_by_code(error_code, category)
        if result:
            print(f"   [L1a] ✅ MATCH → Type {result['error_type']} "
                  f"({result['error_type_name']}), code='{error_code}'")
            return result
        print(f"   [L1a] No exact match for code '{error_code}'")

    # ── Layer 1b: Keyword (TF-IDF) match ───────────────────────
    if error_text:
        print(f"   [L1b] Trying keyword match on error message...")
        result = kb.lookup_by_keywords(error_text)
        if result:
            print(f"   [L1b] ✅ MATCH → Type {result['error_type']} "
                  f"({result['error_type_name']}), score={result.get('keyword_score', '?')}")
            return result
        print(f"   [L1b] No keyword match above threshold "
              f"({KnowledgeBaseConfig.KEYWORD_THRESHOLD})")

    # ── Layer 2: ChromaDB consensus ────────────────────────────
    print(f"   [L2] Searching ChromaDB for similar past errors...")
    similar_errors = search_similar_errors(
        error_text=error_text,
        namespace=pipeline_name,
        top_k=5
    )

    if similar_errors:
        print(f"   [L2] Found {len(similar_errors)} similar errors. "
              f"Checking consensus...")
        consensus = compute_consensus(
            similar_errors,
            score_threshold=KnowledgeBaseConfig.CONSENSUS_THRESHOLD,
            min_agree=KnowledgeBaseConfig.CONSENSUS_MIN_AGREE,
        )
        if consensus:
            print(f"   [L2] ✅ CONSENSUS → Type {consensus['error_type']} "
                  f"({consensus['error_type_name']}), "
                  f"{consensus['consensus_count']}/5 agree, "
                  f"avg_score={consensus['consensus_avg_score']}")
            return consensus
        print(f"   [L2] No consensus reached.")
    else:
        print(f"   [L2] No similar errors found in ChromaDB.")

    # ── Layer 3: LLM fallback ──────────────────────────────────
    print(f"   [L3] Falling back to LLM classification...")
    classification = classify_error(
        error_details, similar_errors or [], pipeline_metadata
    )
    classification["classified_by"] = "L3_llm_fallback"

    print(f"   [L3] ✅ LLM → Type {classification['error_type']} "
          f"({classification['error_type_name']}), "
          f"confidence={classification.get('confidence', '?')}")

    # ── Feedback loop: store L3 result for future L1/L2 ────────
    _feedback_loop(error_code, category, error_text, classification, pipeline_name)

    return classification


def _feedback_loop(error_code: str, category: str, error_text: str,
                   classification: dict, pipeline_name: str):
    """
    After L3 (LLM) classifies a novel error, store it back so future
    occurrences can be caught by L1 or L2.
    """
    try:
        # Feed back into CSV knowledge base (L1)
        if error_code:
            kb = get_knowledge_base()
            kb.add_new_error(
                error_code=error_code,
                category=category or "LLM-Classified",
                message=error_text[:500],
                cause=classification.get("root_cause_summary", ""),
                our_type=classification.get("error_type", 1),
                resolution=classification.get("recommended_action", ""),
            )

        # ChromaDB storage is already handled by error_processor.py (Step 4)
        # so we don't duplicate it here.

        print(f"   [FEEDBACK] Stored L3 result for future L1/L2 matching.")
    except Exception as e:
        print(f"   [FEEDBACK][WARN] Feedback loop failed: {e}")
