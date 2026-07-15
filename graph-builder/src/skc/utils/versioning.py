from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path
from typing import Any

def generate_build_version() -> str:
    """
    Generate a semantic build version string.
    
    Format: YYYYMMDD.HHMMSS.<shortuuid>
    Uses the current UTC time and the first 6 characters of a UUID4.
    
    Returns:
        str: The generated build version string.
    """
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d.%H%M%S")
    short_uuid = str(uuid.uuid4())[:6]
    return f"{timestamp}.{short_uuid}"

def generate_build_id() -> str:
    """
    Generate a full UUID4 build ID.
    
    Returns:
        str: A full UUID4 string.
    """
    return str(uuid.uuid4())


def write_build_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    """Write a build manifest as pretty JSON and return the path."""
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, default=str, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path
