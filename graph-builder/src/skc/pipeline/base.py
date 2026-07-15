"""Pipeline stage abstract base class and result models.

Defines the ``PipelineStage`` ABC that every compilation stage must
subclass, along with the ``StageResult`` value object that captures
execution outcomes, timing, and diagnostics for a single stage run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from skc.ir.common import StageStatus

if TYPE_CHECKING:
    from skc.pipeline.context import CompilationContext


class StageResult(BaseModel):
    """Immutable record of a single pipeline-stage execution.

    Attributes:
        stage_name: Identifier of the stage that produced this result.
        status: Final execution status (COMPLETED, FAILED, etc.).
        started_at: UTC timestamp when the stage began executing.
        completed_at: UTC timestamp when the stage finished.
        duration_ms: Wall-clock duration in milliseconds.
        artefacts_written: List of artefact names written by this stage.
        warnings: Non-fatal diagnostic messages emitted during execution.
        errors: Fatal error messages (populated when *status* is FAILED).
        stats: Arbitrary key/value metrics collected during execution
            (e.g. row counts, entity counts).
    """

    model_config = ConfigDict(frozen=True)

    stage_name: str
    status: StageStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    artefacts_written: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)

    @property
    def execution_time_ms(self) -> int:
        """Backward-compatible alias for ``duration_ms``."""
        return self.duration_ms

    @property
    def metadata(self) -> dict[str, Any]:
        """Backward-compatible alias for ``stats``."""
        return self.stats


class PipelineStage(ABC):
    """Abstract base class for all SKC pipeline stages.

    Every stage in the compilation pipeline must subclass
    ``PipelineStage`` and implement :meth:`run` and
    :meth:`validate_inputs`.  The class-level attributes describe the
    stage's identity and its position in the dependency graph.

    Attributes:
        name: Unique stage identifier (e.g. ``"schema_parser"``).
        version: Semantic version of the stage implementation.
        description: Human-readable summary of the stage's purpose.
        requires: Stage names that must complete successfully before
            this stage can run.
        produces: Artefact names that this stage writes to the
            compilation context.
    """

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    requires: list[str] = []
    produces: list[str] = []

    @abstractmethod
    async def run(self, ctx: CompilationContext) -> StageResult:
        """Execute the stage logic.

        Parameters:
            ctx: The mutable compilation context shared across all
                stages.  Stages read their inputs from *ctx* and write
                results back into it.

        Returns:
            A :class:`StageResult` capturing timing, status, and
            diagnostics for this execution.
        """

    @abstractmethod
    async def validate_inputs(self, ctx: CompilationContext) -> list[str]:
        """Validate that all required inputs are present in *ctx*.

        Parameters:
            ctx: The compilation context to validate against.

        Returns:
            A list of human-readable error messages.  An empty list
            signals that all inputs are valid and the stage is ready
            to run.
        """

    def _create_result(
        self,
        status: StageStatus,
        started_at: datetime,
        artefacts: list[str] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        stats: dict[str, Any] | None = None,
    ) -> StageResult:
        """Build a :class:`StageResult` with auto-computed duration.

        This convenience helper captures the current UTC time as the
        completion timestamp and derives ``duration_ms`` from the
        difference between *started_at* and now.

        Parameters:
            status: Final execution status.
            started_at: UTC timestamp recorded at the start of
                :meth:`run`.
            artefacts: Names of artefacts written during execution.
            warnings: Non-fatal diagnostic messages.
            errors: Error messages (typically non-empty only when
                *status* is ``FAILED``).
            stats: Arbitrary execution metrics.

        Returns:
            A fully populated :class:`StageResult`.
        """
        completed_at = datetime.utcnow()
        duration_ms = int(
            (completed_at - started_at).total_seconds() * 1000
        )
        return StageResult(
            stage_name=self.name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            artefacts_written=artefacts or [],
            warnings=warnings or [],
            errors=errors or [],
            stats=stats or {},
        )
