"""
Knowledge Base — Layer 1 Engine for the Tiered Error Classification Pipeline.

Loads ADF errors from CSV (v4 format) into memory and provides:
  - L1a: 3-step waterfall lookup:
      Step 1: Exact match by error_code_number
      Step 2: If multiple rows share the same code number → TF-IDF match on error_code_name
      Step 3: If still ambiguous → fall through to L1b (error message matching)
  - L1b: TF-IDF keyword matching against error messages (cosine similarity)
  - Feedback loop: append newly classified errors back to CSV + refresh index

CSV v4 columns: category, error_code_number, error_code_name, message, cause, recommendation, resolution

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
    __slots__ = ["error_code_number", "error_code_name", "category", "message",
                 "cause", "recommendation", "resolution", "our_type", "type_reason"]

    def __init__(self, error_code_number, error_code_name, category, message,
                 cause, recommendation, resolution, our_type, type_reason=""):
        self.error_code_number = error_code_number
        self.error_code_name = error_code_name
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
    In-memory knowledge base loaded from CSV (v4) + category_type_map.json.

    Usage:
        kb = KnowledgeBase()
        result = kb.lookup_by_code("3200", "ActionTimedOut", "Azure Databricks")
        result = kb.lookup_by_keywords("access token expired")
        kb.add_new_error(...)  # feedback loop
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Index by error_code_number → [ErrorEntry, ...]
        self._by_code_number: Dict[str, list] = {}
        # Index by error_code_name → [ErrorEntry, ...]
        self._by_code_name: Dict[str, list] = {}
        self._all_entries: list = []
        self._messages: list = []  # parallel list of messages for TF-IDF
        self._type_map: dict = {}
        self._tfidf_ready = False

        self._load_type_map()
        self._load_csv()
        print(f"[KB] Knowledge base loaded: {len(self._all_entries)} errors, "
              f"{len(self._by_code_number)} unique code numbers, "
              f"{len(self._by_code_name)} unique code names, "
              f"{len(self._type_map)} categories")

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
        """Load all errors from CSV v4 into memory."""
        csv_path = KnowledgeBaseConfig.CSV_PATH
        if not os.path.exists(csv_path):
            print(f"[KB][WARN] CSV not found at {csv_path}")
            return

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row.get("category", "").strip()
                error_code_number = row.get("error_code_number", "").strip()
                error_code_name = row.get("error_code_name", "").strip()
                message = row.get("message", "").strip()
                cause = row.get("cause", "").strip()
                recommendation = row.get("recommendation", "").strip()
                resolution = row.get("resolution", "").strip()

                # Use error_code_number for type resolution; fallback to name
                resolve_code = error_code_number or error_code_name
                our_type, type_reason = self._resolve_type(category, resolve_code)

                entry = ErrorEntry(
                    error_code_number=error_code_number,
                    error_code_name=error_code_name,
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

                # Index by error_code_number (multiple entries can share a code number)
                if error_code_number:
                    if error_code_number not in self._by_code_number:
                        self._by_code_number[error_code_number] = []
                    self._by_code_number[error_code_number].append(entry)

                # Index by error_code_name (for direct name matching)
                if error_code_name:
                    name_lower = error_code_name.lower()
                    if name_lower not in self._by_code_name:
                        self._by_code_name[name_lower] = []
                    self._by_code_name[name_lower].append(entry)

    # ── L1a: 3-step waterfall lookup ───────────────────────────

    def lookup_by_code(self, error_code_number: str = "",
                       error_code_name: str = "",
                       category: str = None) -> Optional[dict]:
        """
        3-step waterfall lookup:
          Step 1: Exact match by error_code_number → unique match? → done
          Step 2: Multiple rows with same number → TF-IDF match on error_code_name
          Step 3: Direct match by error_code_name (for codes that are text-only)

        Returns classification dict or None.
        """
        # ── Step 1: Exact match by error_code_number ──
        if error_code_number:
            entries = self._by_code_number.get(error_code_number)
            if entries:
                # Filter by category if provided
                if category:
                    cat_entries = [e for e in entries
                                  if e.category.lower() == category.lower()]
                    if cat_entries:
                        entries = cat_entries

                if len(entries) == 1:
                    # Unique match — done
                    return self._entry_to_result(entries[0], "L1_exact_code_number")

                # ── Step 2: Multiple rows share this code number ──
                # Try to disambiguate using error_code_name similarity
                if error_code_name and len(entries) > 1:
                    result = self._disambiguate_by_name(
                        entries, error_code_name
                    )
                    if result:
                        return result

                # Multiple rows, can't disambiguate — return first match
                # (let L1b message matching handle it if needed)
                return self._entry_to_result(entries[0], "L1_code_number_first")

        # ── Step 3: Direct match by error_code_name ──
        # Handles the case where incoming error has a text code like "ActionTimedOut"
        if error_code_name:
            name_lower = error_code_name.lower()
            name_entries = self._by_code_name.get(name_lower)
            if name_entries:
                # Filter by category if provided
                if category:
                    cat_entries = [e for e in name_entries
                                  if e.category.lower() == category.lower()]
                    if cat_entries:
                        name_entries = cat_entries

                if len(name_entries) >= 1:
                    return self._entry_to_result(name_entries[0], "L1_exact_code_name")

        return None

    def _disambiguate_by_name(self, entries: list,
                              query_name: str) -> Optional[dict]:
        """
        When multiple CSV rows share the same error_code_number,
        use TF-IDF cosine similarity on error_code_name to pick the best match.

        Uses a higher threshold (CODE_NAME_THRESHOLD = 0.75) since code names
        are short and should match closely.
        """
        # Collect the error_code_names from these entries
        entry_names = [e.error_code_name for e in entries]

        # If none of the entries have names, can't disambiguate
        if not any(entry_names):
            return None

        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        # Build a mini TF-IDF just for these names
        corpus = entry_names + [query_name]
        try:
            vectorizer = TfidfVectorizer(
                analyzer="char_wb",  # character n-grams work better for code names
                ngram_range=(3, 5),
            )
            matrix = vectorizer.fit_transform(corpus)
            query_vec = matrix[-1]  # last item is the query
            entry_vecs = matrix[:-1]  # all others are entries

            scores = cosine_similarity(query_vec, entry_vecs)[0]
            best_idx = int(scores.argmax())
            best_score = float(scores[best_idx])

            if best_score >= KnowledgeBaseConfig.CODE_NAME_THRESHOLD:
                result = self._entry_to_result(entries[best_idx], "L1_code_name_disambig")
                result["code_name_score"] = round(best_score, 4)
                return result
        except Exception:
            pass

        return None

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

    def add_new_error(self, error_code_number: str = "", error_code_name: str = "",
                      category: str = "", message: str = "",
                      cause: str = "", our_type: int = 1, resolution: str = ""):
        """
        Add a newly classified error back into the knowledge base.
        Thread-safe. Appends to CSV and updates in-memory indexes.
        """
        with self._lock:
            entry = ErrorEntry(
                error_code_number=error_code_number,
                error_code_name=error_code_name,
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

            # Index by code number
            if error_code_number:
                if error_code_number not in self._by_code_number:
                    self._by_code_number[error_code_number] = []
                self._by_code_number[error_code_number].append(entry)

            # Index by code name
            if error_code_name:
                name_lower = error_code_name.lower()
                if name_lower not in self._by_code_name:
                    self._by_code_name[name_lower] = []
                self._by_code_name[name_lower].append(entry)

            # Invalidate TF-IDF index so it's rebuilt on next keyword search
            self._tfidf_ready = False

            # Append to CSV file (v4 format: 7 columns)
            try:
                csv_path = KnowledgeBaseConfig.CSV_PATH
                with open(csv_path, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        category or "LLM-Classified",
                        error_code_number,
                        error_code_name,
                        message,
                        cause,
                        "",  # recommendation
                        resolution,
                    ])
                print(f"[KB][FEEDBACK] Added new error "
                      f"(code={error_code_number or error_code_name}) "
                      f"to knowledge base (Type {our_type}). "
                      f"Total: {len(self._all_entries)}")
            except Exception as e:
                print(f"[KB][WARN] Failed to write to CSV: {e}")

    # ── Helpers ────────────────────────────────────────────────

    def _entry_to_result(self, entry: ErrorEntry, classified_by: str) -> dict:
        """Convert an ErrorEntry to the standard classification result dict."""
        error_type = entry.our_type
        return {
            "error_type": error_type,
            "error_type_name": TYPE_NAMES.get(error_type, "Unknown"),
            "confidence": 1.0 if "exact" in classified_by else 0.90,
            "root_cause_summary": entry.cause or entry.message[:200],
            "is_auto_recoverable": error_type in (3, 4, 5),
            "recommended_action": entry.resolution or entry.recommendation or "See documentation.",
            "priority": self._type_to_priority(error_type),
            "classified_by": classified_by,
            "csv_category": entry.category,
            "csv_error_code_number": entry.error_code_number,
            "csv_error_code_name": entry.error_code_name,
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
            "unique_code_numbers": len(self._by_code_number),
            "unique_code_names": len(self._by_code_name),
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
