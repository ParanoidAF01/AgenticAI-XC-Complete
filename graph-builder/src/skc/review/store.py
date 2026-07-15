"""SQLite-backed candidate knowledge store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from skc.ir.common import CandidateKnowledge, ReviewStatus


class CandidateStore:
    """Persistence layer for review candidates."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    serialized_node TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    confidence_tier TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    reviewer TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(review_status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_type ON candidates(node_type)"
            )

    def upsert_candidate(
        self,
        candidate: CandidateKnowledge,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Insert or update a candidate."""
        now = datetime.utcnow().isoformat()
        payload = candidate.model_dump_json()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at, reviewer, notes FROM candidates WHERE id = ?",
                (candidate.id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            reviewer = reviewer if reviewer is not None else (existing["reviewer"] if existing else None)
            notes = notes if notes is not None else (existing["notes"] if existing else None)
            connection.execute(
                """
                INSERT OR REPLACE INTO candidates (
                    id, node_type, name, serialized_node, confidence_score,
                    confidence_tier, review_status, reviewer, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.id,
                    candidate.candidate_type,
                    candidate.name,
                    payload,
                    candidate.confidence.score,
                    candidate.confidence.threshold_tier.value,
                    candidate.review_status.value,
                    reviewer,
                    notes,
                    created_at,
                    now,
                ),
            )

    def get_pending(self) -> list[dict[str, Any]]:
        """Return candidates waiting for review."""
        return self.get_by_status(ReviewStatus.PENDING_REVIEW)

    def get_by_status(self, status: ReviewStatus | str) -> list[dict[str, Any]]:
        """Return candidates by review status."""
        value = status.value if isinstance(status, ReviewStatus) else status
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM candidates WHERE review_status = ? ORDER BY confidence_score ASC, name ASC",
                (value,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def approve(self, candidate_id: str, reviewer: str | None = None, notes: str | None = None) -> None:
        """Mark a candidate approved."""
        self._update_status(candidate_id, ReviewStatus.APPROVED, reviewer, notes)

    def reject(self, candidate_id: str, reason: str, reviewer: str | None = None) -> None:
        """Mark a candidate rejected."""
        self._update_status(candidate_id, ReviewStatus.REJECTED, reviewer, reason)

    def modify(
        self,
        candidate_id: str,
        updated_node: CandidateKnowledge,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Store a modified candidate node."""
        updated = updated_node.model_copy(
            update={"id": candidate_id, "review_status": ReviewStatus.MODIFIED}
        )
        self.upsert_candidate(updated, reviewer=reviewer, notes=notes)

    def all(self) -> list[dict[str, Any]]:
        """Return all stored candidates."""
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM candidates ORDER BY node_type, name").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        """Return candidate counts grouped by status."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT review_status, COUNT(*) AS count FROM candidates GROUP BY review_status"
            ).fetchall()
        return {row["review_status"]: int(row["count"]) for row in rows}

    def _update_status(
        self,
        candidate_id: str,
        status: ReviewStatus,
        reviewer: str | None,
        notes: str | None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT serialized_node FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Candidate not found: {candidate_id}")
            payload = json.loads(row["serialized_node"])
            payload["review_status"] = status.value
            connection.execute(
                """
                UPDATE candidates
                SET serialized_node = ?, review_status = ?, reviewer = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(payload), status.value, reviewer, notes, now, candidate_id),
            )

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["serialized_node"] = json.loads(data["serialized_node"])
        return data
