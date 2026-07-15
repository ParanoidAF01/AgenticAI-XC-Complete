"""Shared helpers for semantic enrichment stages."""

from __future__ import annotations

import re
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from skc.ir.common import Confidence, Provenance, SourceType
from skc.ir.mir import MIRColumn, MIRTable
from skc.utils.naming import snake_to_title


def stable_id(prefix: str, *parts: str) -> str:
    """Create a deterministic ID from semantic parts."""
    raw = ":".join([prefix, *parts])
    return f"{prefix}_{uuid5(NAMESPACE_URL, raw).hex[:16]}"


def deterministic_provenance(stage_name: str, build_version: str = "") -> list[Provenance]:
    """Create deterministic provenance for a stage output."""
    return [
        Provenance(
            source_type=SourceType.DETERMINISTIC,
            source_id=stage_name,
            source_detail="deterministic heuristic",
            timestamp=datetime.utcnow(),
            build_version=build_version,
        )
    ]


def confidence(score: float, explanation: str = "") -> Confidence:
    """Create a confidence object with an explanation."""
    return Confidence.from_score(score=score, explanation=explanation)


def table_ref(table: MIRTable) -> str:
    """Return ``schema.table`` for a MIR table."""
    return f"{table.schema_name}.{table.name}"


def column_ref(table: MIRTable, column: MIRColumn) -> str:
    """Return ``schema.table.column`` for a MIR column."""
    return f"{table.schema_name}.{table.name}.{column.name}"


def humanize_identifier(identifier: str) -> str:
    """Convert an identifier into human-readable title case."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", identifier).strip("_")
    return snake_to_title(cleaned)


def singularize(name: str) -> str:
    """Simple English singularization for common table names."""
    if name.endswith("ies") and len(name) > 3:
        return f"{name[:-3]}y"
    if name.endswith("ses"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def entity_name_for_table(table: MIRTable) -> str:
    """Derive an entity name from a table name."""
    return humanize_identifier(singularize(table.name))
