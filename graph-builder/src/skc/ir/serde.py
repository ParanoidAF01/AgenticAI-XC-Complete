"""JSONL serialisation and deserialisation helpers for IR models.

All IR artefacts are persisted as ``.jsonl`` files with a leading header line
that records schema metadata.  This module provides three entry points:

* :func:`write_jsonl` — write a list of Pydantic models to a ``.jsonl`` file.
* :func:`read_jsonl` — eagerly read an entire ``.jsonl`` file into a list.
* :func:`stream_jsonl` — lazily yield models one-by-one (memory-efficient).

Header format
~~~~~~~~~~~~~
The first line of every ``.jsonl`` file is a JSON object with at least::

    {"_header": true, "schema_version": "1.0",
     "model_type": "MIRDatabase", "created_at": "2025-01-01T00:00:00"}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def write_jsonl(
    path: Path,
    models: list[BaseModel],
    schema_version: str = "1.0",
) -> None:
    """Serialise a list of Pydantic models to a JSONL file with a header.

    Parameters
    ----------
    path:
        Destination file path.  Parent directories are created automatically.
    models:
        Pydantic model instances to serialise (one JSON line each).
    schema_version:
        Semantic version embedded in the header for forward compatibility.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Derive model_type from the first model (or "Unknown" for empty lists).
    model_type = type(models[0]).__name__ if models else "Unknown"

    header = {
        "_header": True,
        "schema_version": schema_version,
        "model_type": model_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for model in models:
            fh.write(model.model_dump_json() + "\n")


def read_jsonl(path: Path, model_type: type[T]) -> list[T]:
    """Eagerly read a JSONL file into a list of Pydantic model instances.

    The first line (header) is automatically detected and skipped.

    Parameters
    ----------
    path:
        Source ``.jsonl`` file.
    model_type:
        The Pydantic model class to deserialise each line into.

    Returns
    -------
    list[T]
        Parsed model instances (excluding the header).
    """
    results: list[T] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            # Skip the header line.
            if data.get("_header") is True:
                continue
            results.append(model_type.model_validate(data))
    return results


def stream_jsonl(path: Path, model_type: type[T]) -> Iterator[T]:
    """Lazily stream a JSONL file, yielding one model instance at a time.

    Ideal for large IR artefacts that should not be loaded entirely into
    memory.  The header line is automatically detected and skipped.

    Parameters
    ----------
    path:
        Source ``.jsonl`` file.
    model_type:
        The Pydantic model class to deserialise each line into.

    Yields
    ------
    T
        Parsed model instances (excluding the header).
    """
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if data.get("_header") is True:
                continue
            yield model_type.model_validate(data)
