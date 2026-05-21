"""
Knowledge Base — Layer 1 Engine for the Tiered Error Classification Pipeline.

Loads ADF errors from CSV into memory and provides:
  - L1a: O(1) exact lookup by error_code
  - L1b: TF-IDF keyword matching against error messages (cosine similarity)
  - Feedback loop: append newly classified errors back to CSV + refresh index

Thread-safe for concurrent access from listener background threads.
"""
import csv
import os
import re
import json
import threading
from typing import Optional, Dict

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import KnowledgeBaseConfig

# Lazy import — scikit-learn is heavy, only load when keyword matching is used
_vectorizer = None
_tfidf_matrix = None


class ErrorEntry:
    """A single known error from the CSV knowledge base."""
    __slots__ = ["error_code", "category", "message", "cause",
                 "recommendation", "resolution", "our_type", "type_reason"]

    def __init__(self, error_code, category, message, cause,
                 recommendation, resolution, our_type, type_reason=""):
        self.error_code = error_code
        self.category = category
        self.message = message
        self.cause = cause
        self.recommendation = recommendation
        self.resolution = resolution
        self.our_type = our_type
        self.type_reason = type_reason


# ── Type name mapping ──────────────────────────────────────────
TYPE_NAMES = {
    1: "Parameter Errors",
    2: "Dataset Type Errors",
    3: "Credentials Expired",
    4: "Large Data / Timeout",
    5: "Server Slow",
    6: "Subscription Corrupt",
}


class KnowledgeBase:
    """
    In-memory knowledge base loaded from CSV + category_type_map.json.

    Usage:
        kb = KnowledgeBase()
        result = kb.lookup_by_code("3200", "Azure Databricks")
        result = kb.lookup_by_keywords("access token expired")
        kb.add_new_error(...)  # feedback loop
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_code: Dict[str, list] = {}  # error_code → [ErrorEntry, ...]
        self._all_entries: list = []
        self._messages: list = []  # parallel list of messages for TF-IDF
        self._type_map: dict = {}
        self._tfidf_ready = False

        self._load_type_map()
        self._load_csv()
        print(f"[KB] Knowledge base loaded: {len(self._all_entries)} errors, "
              f"{len(self._by_code)} unique codes, {len(self._type_map)} categories")

    def _load_type_map(self):
        """Load category_type_map.json."""
        try:
            with open(KnowledgeBaseConfig.TYPE_MAP_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Filter out metadata keys starting with _
            self._type_map = {k: v for k, v in raw.items() if not k.startswith("_")}
        except Exception as e:
            print(f"[KB][WARN] Could not load type map: {e}")
            self._type_map = {}

    def _resolve_type(self, category: str, error_code: str) -> tuple:
        """
        Resolve the our_type for a given category + error_code.
        Returns (type_int, reason_str).
        """
        cat_entry = self._type_map.get(category)
        if not cat_entry:
            return (1, "Unknown category — defaulting to Parameter Errors")

        # Check code-specific overrides first
        overrides = cat_entry.get("overrides", {})
        if error_code in overrides:
            override = overrides[error_code]
            return (override["type"], override.get("reason", ""))

        # Fall back to category default
        default_type = cat_entry.get("default_type", 1)
        return (default_type, f"Category default for {category}")

    def _load_csv(self):
        """Load all errors from CSV into memory."""
        csv_path = KnowledgeBaseConfig.CSV_PATH
        if not os.path.exists(csv_path):
            print(f"[KB][WARN] CSV not found at {csv_path}")
            return

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row.get("category", "").strip()
                error_code = row.get("error_code", "").strip()
                message = row.get("message", "").strip()
                cause = row.get("cause", "").strip()
                recommendation = row.get("recommendation", "").strip()
                resolution = row.get("resolution", "").strip()

                our_type, type_reason = self._resolve_type(category, error_code)

                entry = ErrorEntry(
                    error_code=error_code,
                    category=category,
                    message=message,
                    cause=cause,
                    recommendation=recommendation,
                    resolution=resolution,
                    our_type=our_type,
                    type_reason=type_reason,
                )

                self._all_entries.append(entry)
                self._messages.append(message)

                # Index by error_code (multiple entries can share a code)
                if error_code not in self._by_code:
                    self._by_code[error_code] = []
                self._by_code[error_code].append(entry)

    # ── L1a: Exact code lookup ─────────────────────────────────

    def lookup_by_code(self, error_code: str,
                       category: str = None) -> Optional[dict]:
        """
        O(1) exact match by error_code.
        If category is provided, filters to matching category.
        Returns classification dict or None.
        """
        if not error_code:
            return None

        entries = self._by_code.get(error_code)
        if not entries:
            return None

        # If category provided, try to match category first
        if category:
            for entry in entries:
                if entry.category.lower() == category.lower():
                    return self._entry_to_result(entry, "L1_exact_code")

        # Return first match if no category filter
        return self._entry_to_result(entries[0], "L1_exact_code")

    # ── L1b: Keyword (TF-IDF) matching ────────────────────────

    def _ensure_tfidf(self):
        """Lazy-build the TF-IDF matrix on first keyword search."""
        if self._tfidf_ready:
            return

        global _vectorizer, _tfidf_matrix
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not self._messages:
            return

        _vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=10000,
            ngram_range=(1, 2),
        )
        _tfidf_matrix = _vectorizer.fit_transform(self._messages)
        self._tfidf_ready = True
        print(f"[KB] TF-IDF index built: {_tfidf_matrix.shape[0]} documents, "
              f"{_tfidf_matrix.shape[1]} features")

    def lookup_by_keywords(self, error_message: str) -> Optional[dict]:
        """
        TF-IDF cosine similarity search against all CSV error messages.
        Returns classification if best match score >= threshold, else None.
        """
        if not error_message or not self._messages:
            return None

        with self._lock:
            self._ensure_tfidf()

        global _vectorizer, _tfidf_matrix
        if _vectorizer is None or _tfidf_matrix is None:
            return None

        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = _vectorizer.transform([error_message])
        scores = cosine_similarity(query_vec, _tfidf_matrix)[0]
        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        if best_score >= KnowledgeBaseConfig.KEYWORD_THRESHOLD:
            entry = self._all_entries[best_idx]
            result = self._entry_to_result(entry, "L1_keyword_match")
            result["keyword_score"] = round(best_score, 4)
            return result

        return None

    # ── Feedback loop ──────────────────────────────────────────

    def add_new_error(self, error_code: str, category: str, message: str,
                      cause: str, our_type: int, resolution: str = ""):
        """
        Add a newly classified error back into the knowledge base.
        Thread-safe. Appends to CSV and updates in-memory indexes.
        """
        with self._lock:
            entry = ErrorEntry(
                error_code=error_code,
                category=category or "LLM-Classified",
                message=message,
                cause=cause,
                recommendation="",
                resolution=resolution,
                our_type=our_type,
                type_reason="Classified by LLM (L3 fallback)",
            )

            self._all_entries.append(entry)
            self._messages.append(message)

            if error_code not in self._by_code:
                self._by_code[error_code] = []
            self._by_code[error_code].append(entry)

            # Invalidate TF-IDF index so it's rebuilt on next keyword search
            self._tfidf_ready = False

            # Append to CSV file
            try:
                csv_path = KnowledgeBaseConfig.CSV_PATH
                with open(csv_path, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        category or "LLM-Classified",
                        error_code,
                        message,
                        cause,
                        "",  # recommendation
                        resolution,
                    ])
                print(f"[KB][FEEDBACK] Added new error '{error_code}' to knowledge base "
                      f"(Type {our_type}). Total: {len(self._all_entries)}")
            except Exception as e:
                print(f"[KB][WARN] Failed to write to CSV: {e}")

    # ── Helpers ────────────────────────────────────────────────

    def _entry_to_result(self, entry: ErrorEntry, classified_by: str) -> dict:
        """Convert an ErrorEntry to the standard classification result dict."""
        error_type = entry.our_type
        return {
            "error_type": error_type,
            "error_type_name": TYPE_NAMES.get(error_type, "Unknown"),
            "confidence": 1.0 if classified_by == "L1_exact_code" else 0.85,
            "root_cause_summary": entry.cause or entry.message[:200],
            "is_auto_recoverable": error_type in (3, 4, 5),
            "recommended_action": entry.resolution or entry.recommendation or "See documentation.",
            "priority": self._type_to_priority(error_type),
            "classified_by": classified_by,
            "csv_category": entry.category,
            "csv_error_code": entry.error_code,
        }

    @staticmethod
    def _type_to_priority(error_type: int) -> str:
        """Map error type to priority level."""
        return {
            1: "P2", 2: "P2", 3: "P3",
            4: "P3", 5: "P4", 6: "P1",
        }.get(error_type, "P2")

    def get_stats(self) -> dict:
        """Return stats about the knowledge base for monitoring."""
        return {
            "total_errors": len(self._all_entries),
            "unique_codes": len(self._by_code),
            "categories": len(self._type_map),
            "tfidf_ready": self._tfidf_ready,
        }


# ── Module-level singleton ─────────────────────────────────────
_kb_instance = None
_kb_lock = threading.Lock()


def get_knowledge_base() -> KnowledgeBase:
    """Get or create the global KnowledgeBase singleton."""
    global _kb_instance
    if _kb_instance is None:
        with _kb_lock:
            if _kb_instance is None:
                _kb_instance = KnowledgeBase()
    return _kb_instance
