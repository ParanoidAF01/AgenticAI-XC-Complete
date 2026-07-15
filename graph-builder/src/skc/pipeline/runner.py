import time
from datetime import datetime

import structlog

from skc.pipeline.base import PipelineStage, StageResult
from skc.pipeline.checkpoint import CheckpointManager
from skc.pipeline.context import CompilationContext
from skc.pipeline.reporting import BuildReporter
from skc.ir.common import StageStatus

logger = structlog.get_logger(__name__)


class PipelineRunner:
    """
    Runs a pipeline of compilation stages.
    """

    def __init__(self, context: CompilationContext, stages: list[PipelineStage]) -> None:
        """
        Initializes the PipelineRunner with a compilation context and a list of stages.

        Args:
            context: The compilation context for the pipeline run.
            stages: A list of PipelineStage objects to be executed.
        """
        self.context = context
        self.stages = stages

    def topological_sort(self) -> list[PipelineStage]:
        """
        Sorts the stages based on their dependencies (requires property).

        Returns:
            A list of PipelineStage objects sorted in topological order.

        Raises:
            ValueError: If a stage requires a non-existent stage, or if a circular dependency is detected.
        """
        stage_map = {stage.name: stage for stage in self.stages}
        if len(stage_map) != len(self.stages):
            raise ValueError("Duplicate pipeline stage names are not allowed.")

        # Check for missing dependencies
        for stage in self.stages:
            for req in stage.requires:
                if req not in stage_map:
                    raise ValueError(
                        f"Stage '{stage.name}' requires '{req}', which is not in the pipeline."
                    )

        visited: set[str] = set()
        temp_visited: set[str] = set()
        sorted_stages: list[PipelineStage] = []

        def visit(stage_name: str) -> None:
            if stage_name in temp_visited:
                raise ValueError(
                    f"Circular dependency detected involving stage '{stage_name}'."
                )
            if stage_name in visited:
                return

            temp_visited.add(stage_name)

            stage = stage_map[stage_name]
            for req in stage.requires:
                visit(req)

            temp_visited.remove(stage_name)
            visited.add(stage_name)
            sorted_stages.append(stage)

        for stage in self.stages:
            if stage.name not in visited:
                visit(stage.name)

        return sorted_stages

    async def run(self) -> dict[str, StageResult]:
        """
        Executes the pipeline stages in topological order.

        Returns:
            A dictionary mapping stage names to their StageResult.
        """
        log = structlog.get_logger(__name__)
        sorted_stages = self.topological_sort()
        checkpoints = CheckpointManager(self.context.output_dir)

        for stage in sorted_stages:
            if self.context.is_stage_complete(stage.name):
                log.info("stage_skipped_already_complete", stage_name=stage.name)
                continue

            log.info("stage_starting", stage_name=stage.name)
            started_at = datetime.utcnow()
            start_time = time.monotonic()

            # Validate inputs
            validation_errors = await stage.validate_inputs(self.context)
            if validation_errors:
                fail_fast = self.context.config.pipeline.fail_fast
                status = StageStatus.FAILED if fail_fast else StageStatus.SKIPPED
                completed_at = datetime.utcnow()
                duration_ms = int((time.monotonic() - start_time) * 1000.0)

                result = StageResult(
                    stage_name=stage.name,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    errors=validation_errors,
                )
                self.context.record_stage_result(result)
                self._checkpoint(checkpoints, stage.name)

                if fail_fast:
                    log.error(
                        "stage_validation_failed",
                        stage_name=stage.name,
                        errors=validation_errors,
                        status=str(status),
                    )
                    raise ValueError(
                        f"Stage '{stage.name}' validation failed: {validation_errors}"
                    )
                else:
                    log.warning(
                        "stage_validation_skipped",
                        stage_name=stage.name,
                        errors=validation_errors,
                        status=str(status),
                    )
                    continue

            # Run stage
            try:
                result = await stage.run(self.context)
                self.context.record_stage_result(result)
                self._checkpoint(checkpoints, stage.name)
                
                duration_ms = int((time.monotonic() - start_time) * 1000.0)
                log.info(
                    "stage_completed",
                    stage_name=stage.name,
                    status=str(result.status),
                    duration_ms=duration_ms,
                )
                if result.status == StageStatus.FAILED and self.context.config.pipeline.fail_fast:
                    raise ValueError(f"Stage '{stage.name}' failed: {result.errors}")
            except Exception as e:
                completed_at = datetime.utcnow()
                duration_ms = int((time.monotonic() - start_time) * 1000.0)
                log.exception(
                    "stage_execution_error",
                    stage_name=stage.name,
                    error=str(e),
                    duration_ms=duration_ms,
                )
                
                result = StageResult(
                    stage_name=stage.name,
                    status=StageStatus.FAILED,
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    errors=[str(e)],
                )
                self.context.record_stage_result(result)
                self._checkpoint(checkpoints, stage.name)

                if self.context.config.pipeline.fail_fast:
                    raise

        self.context.write_artefact("build_manifest", "build_manifest.json", self.context.get_build_summary())
        BuildReporter().write_build_report(self.context)
        return self.context.stage_results

    def _checkpoint(self, checkpoints: CheckpointManager, stage_name: str) -> None:
        if self.context.config.pipeline.checkpoint_enabled:
            checkpoints.write_checkpoint(self.context, stage_name)
