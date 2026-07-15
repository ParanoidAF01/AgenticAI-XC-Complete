"""Mutable compilation context passed through all pipeline stages.

The :class:`CompilationContext` is the single shared state object that
flows through every stage of the SKC compilation pipeline.  It holds
references to the MIR and KIR intermediate representations, tracks
artefact outputs and stage results, and carries build metadata.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from skc.config import SKCConfig, load_config
from skc.ir.kir import KnowledgeGraph
from skc.ir.mir import MIRDatabase, MIRProfileSet
from skc.pipeline.base import StageResult
from skc.utils.versioning import generate_build_version


class CompilationContext(BaseModel):
    """Mutable state shared across all pipeline stages.

    Unlike most SKC models, this class is **not** frozen — stages
    mutate it as they progress through the pipeline.

    Attributes:
        build_id: Unique identifier for this compilation run.
        build_version: Semantic version label for this build.
        started_at: UTC timestamp when the build was initiated.
        config: Loaded and validated configuration.
        output_dir: Filesystem directory where artefacts are written.
        mir: The Metadata Intermediate Representation, populated by the
            schema-parser stage.
        profiles: Column-level profiling data, populated by the
            data-profiler stage.
        kir: The Knowledge Intermediate Representation — the mutable
            accumulator of semantic knowledge.
        artefacts: Registry mapping artefact names to their filesystem
            paths.
        stage_results: Registry mapping stage names to their execution
            results.
        previous_build: Optional reference to a prior build context,
            enabling incremental recompilation.
    """

    model_config = ConfigDict(frozen=False)

    build_id: str = Field(default_factory=lambda: str(uuid4()))
    build_version: str = Field(default_factory=generate_build_version)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    config: SKCConfig = Field(default_factory=load_config)
    output_dir: Path = Path("output")
    mir: MIRDatabase | None = None
    profiles: MIRProfileSet | None = None
    kir: KnowledgeGraph = Field(default_factory=KnowledgeGraph)
    artefacts: dict[str, Path] = Field(default_factory=dict)
    stage_results: dict[str, StageResult] = Field(default_factory=dict)
    previous_build: CompilationContext | None = None

    def model_post_init(self, __context: Any) -> None:
        """Keep ``output_dir`` aligned with the loaded pipeline config."""
        if self.output_dir == Path("output") and self.config.pipeline.output_dir:
            self.output_dir = Path(self.config.pipeline.output_dir)

    def set_mir(self, mir: MIRDatabase) -> None:
        """Assign the Metadata Intermediate Representation.

        Called by the schema-parser stage after it has finished
        extracting structural metadata from the source database.

        Parameters:
            mir: Fully populated MIR database model.
        """
        self.mir = mir

    def get_mir(self) -> MIRDatabase:
        """Return the current MIR or raise a clear stage-input error."""
        if self.mir is None:
            raise ValueError("MIR is not available in the compilation context")
        return self.mir

    def set_profiles(self, profiles: MIRProfileSet) -> None:
        """Assign the data-profiling results.

        Called by the data-profiler stage after it has sampled and
        analysed column-level statistics.

        Parameters:
            profiles: Profiling results for all analysed columns.
        """
        self.profiles = profiles

    def get_kir(self) -> KnowledgeGraph:
        """Return the mutable KIR container."""
        return self.kir

    def update_kir(self, kir: KnowledgeGraph) -> None:
        """Replace the current KIR container."""
        self.kir = kir

    def record_stage_result(self, result: StageResult) -> None:
        """Store a stage's execution result.

        Parameters:
            result: The completed stage result to record.
        """
        self.stage_results[result.stage_name] = result

    def register_artefact(self, name: str, path: Path) -> None:
        """Register a named artefact and its filesystem path.

        Parameters:
            name: Logical artefact name (e.g. ``"mir_json"``).
            path: Absolute or relative path where the artefact was
                written.
        """
        self.artefacts[name] = path

    def get_artefact(self, name: str) -> Path | None:
        """Look up a previously registered artefact by name.

        Parameters:
            name: Logical artefact name.

        Returns:
            The filesystem path if the artefact has been registered,
            or ``None`` otherwise.
        """
        return self.artefacts.get(name)

    def write_artefact(self, name: str, path: Path | str, content: Any = None) -> Path:
        """Write an optional artifact payload and register its path.

        Relative paths are resolved beneath ``output_dir``. When *content* is
        ``None`` only the registry entry is created.
        """
        artefact_path = Path(path)
        if not artefact_path.is_absolute():
            artefact_path = self.output_dir / artefact_path
        artefact_path.parent.mkdir(parents=True, exist_ok=True)

        if content is not None:
            if isinstance(content, bytes):
                artefact_path.write_bytes(content)
            elif isinstance(content, str):
                artefact_path.write_text(content, encoding="utf-8")
            elif isinstance(content, BaseModel):
                artefact_path.write_text(content.model_dump_json(indent=2), encoding="utf-8")
            else:
                artefact_path.write_text(
                    json.dumps(content, default=str, indent=2),
                    encoding="utf-8",
                )

        self.register_artefact(name, artefact_path)
        return artefact_path

    def is_stage_complete(self, stage_name: str) -> bool:
        """Check whether a stage has completed successfully.

        Parameters:
            stage_name: The stage identifier to check.

        Returns:
            ``True`` if the stage has a recorded result with status
            ``COMPLETED``, ``False`` otherwise.
        """
        result = self.stage_results.get(stage_name)
        if result is None:
            return False
        from skc.ir.common import StageStatus

        return result.status == StageStatus.COMPLETED

    def get_build_summary(self) -> dict[str, Any]:
        """Generate a summary dictionary of the current build state.

        Returns:
            A dictionary containing build metadata, stage statuses,
            and node/edge counts from the KIR.  Suitable for
            serialisation and logging.
        """
        stage_statuses: dict[str, str] = {}
        for name, result in self.stage_results.items():
            stage_statuses[name] = result.status.value

        return {
            "build_id": self.build_id,
            "build_version": self.build_version,
            "started_at": self.started_at.isoformat(),
            "stages": stage_statuses,
            "artefacts": {k: str(v) for k, v in self.artefacts.items()},
            "kir_node_count": self.kir.node_count,
            "kir_edge_count": self.kir.edge_count,
            "mir_table_count": (
                self.mir.table_count if self.mir is not None else 0
            ),
            "has_profiles": self.profiles is not None,
            "has_previous_build": self.previous_build is not None,
        }
