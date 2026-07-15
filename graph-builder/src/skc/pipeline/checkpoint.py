"""Checkpoint persistence and resume helpers for pipeline runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from skc.ir.common import StageStatus
from skc.ir.kir import KnowledgeGraph
from skc.ir.mir import MIRColumnProfile, MIRDatabase, MIRProfileSet
from skc.ir.serde import read_jsonl
from skc.pipeline.base import StageResult
from skc.pipeline.context import CompilationContext


KIR_ARTEFACT_PRIORITY = [
    "kir_reviewed",
    "kir_confident",
    "kir_rules",
    "kir_metrics",
    "kir_relationships",
    "kir_initial",
]


class CheckpointManager:
    """Write and restore build checkpoints between pipeline stages."""

    checkpoint_version = "1.0"

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = self.output_dir / "checkpoints"

    def write_checkpoint(self, ctx: CompilationContext, stage_name: str) -> Path:
        """Persist a point-in-time snapshot after *stage_name* finishes."""
        payload = self.build_checkpoint(ctx, stage_name)
        path = self.checkpoint_dir / f"{stage_name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        ctx.register_artefact(f"checkpoint_{stage_name}", path)
        return path

    def build_checkpoint(self, ctx: CompilationContext, stage_name: str) -> dict[str, Any]:
        """Create the serialisable checkpoint payload for *ctx*."""
        return {
            "checkpoint_version": self.checkpoint_version,
            "stage_name": stage_name,
            "checkpointed_at": datetime.utcnow().isoformat(),
            "build": {
                "build_id": ctx.build_id,
                "build_version": ctx.build_version,
                "started_at": ctx.started_at.isoformat(),
                "output_dir": str(ctx.output_dir),
            },
            "completed_stages": [
                name
                for name, result in ctx.stage_results.items()
                if result.status == StageStatus.COMPLETED
            ],
            "stage_results": {
                name: result.model_dump(mode="json")
                for name, result in ctx.stage_results.items()
            },
            "artefacts": {name: str(path) for name, path in ctx.artefacts.items()},
            "ir": {
                "mir": self._first_existing(ctx, ["mir_enriched", "mir_database"]),
                "profiles": self._first_existing(ctx, ["mir_profiles"]),
                "kir": self._first_existing(ctx, KIR_ARTEFACT_PRIORITY),
            },
        }

    @classmethod
    def load_checkpoint(cls, checkpoint: str | Path) -> dict[str, Any]:
        """Load a checkpoint file, or the newest checkpoint in a directory."""
        checkpoint_path = cls.resolve_checkpoint_path(checkpoint)
        return json.loads(checkpoint_path.read_text(encoding="utf-8"))

    @classmethod
    def resolve_checkpoint_path(cls, checkpoint: str | Path) -> Path:
        """Resolve either a JSON checkpoint path or a checkpoint directory."""
        path = Path(checkpoint).expanduser()
        if path.is_dir():
            candidates = sorted(path.glob("*.json"), key=lambda item: item.stat().st_mtime)
            if not candidates:
                raise FileNotFoundError(f"No checkpoint JSON files found in {path}")
            return candidates[-1]
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint does not exist: {path}")
        return path

    @classmethod
    def restore_context(cls, ctx: CompilationContext, checkpoint: dict[str, Any]) -> None:
        """Restore stage results, artefact registry, and latest IR snapshots."""
        build = checkpoint.get("build", {})
        if build.get("build_id"):
            ctx.build_id = build["build_id"]
        if build.get("build_version"):
            ctx.build_version = build["build_version"]
        if build.get("started_at"):
            ctx.started_at = datetime.fromisoformat(build["started_at"])

        ctx.artefacts.update(
            {
                name: Path(path)
                for name, path in checkpoint.get("artefacts", {}).items()
                if isinstance(path, str)
            }
        )
        ctx.stage_results.update(
            {
                name: StageResult.model_validate(payload)
                for name, payload in checkpoint.get("stage_results", {}).items()
            }
        )

        cls._restore_mir(ctx, checkpoint)
        cls._restore_profiles(ctx, checkpoint)
        cls._restore_kir(ctx, checkpoint)

    @staticmethod
    def _first_existing(ctx: CompilationContext, names: list[str]) -> str | None:
        for name in names:
            path = ctx.get_artefact(name)
            if path is not None:
                return str(path)
        return None

    @classmethod
    def _restore_mir(cls, ctx: CompilationContext, checkpoint: dict[str, Any]) -> None:
        path = cls._checkpoint_ir_path(checkpoint, "mir")
        if path is not None and path.exists():
            ctx.set_mir(MIRDatabase.from_jsonl(path))

    @classmethod
    def _restore_profiles(cls, ctx: CompilationContext, checkpoint: dict[str, Any]) -> None:
        path = cls._checkpoint_ir_path(checkpoint, "profiles")
        if path is not None and path.exists():
            ctx.set_profiles(MIRProfileSet(profiles=read_jsonl(path, MIRColumnProfile)))

    @classmethod
    def _restore_kir(cls, ctx: CompilationContext, checkpoint: dict[str, Any]) -> None:
        path = cls._checkpoint_ir_path(checkpoint, "kir")
        if path is not None and path.exists():
            graphs = read_jsonl(path, KnowledgeGraph)
            if graphs:
                ctx.update_kir(graphs[0])

    @staticmethod
    def _checkpoint_ir_path(checkpoint: dict[str, Any], key: str) -> Path | None:
        value = checkpoint.get("ir", {}).get(key)
        return Path(value) if isinstance(value, str) and value else None
