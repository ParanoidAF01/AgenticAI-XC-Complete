"""Build report generation for completed SKC runs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from skc.pipeline.context import CompilationContext


class BuildReporter:
    """Generate production-oriented build reports."""

    def build_report(self, ctx: CompilationContext) -> dict[str, Any]:
        """Return a comprehensive report for the current compilation context."""
        completed_at = datetime.utcnow()
        stage_results = {
            name: result.model_dump(mode="json")
            for name, result in ctx.stage_results.items()
        }
        total_duration_ms = int((completed_at - ctx.started_at).total_seconds() * 1000)

        return {
            "build": {
                "build_id": ctx.build_id,
                "build_version": ctx.build_version,
                "started_at": ctx.started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": total_duration_ms,
            },
            "stages": stage_results,
            "timing": self._timing(stage_results),
            "counts": self._counts(ctx),
            "diagnostics": self._diagnostics(stage_results),
            "llm_usage": self._llm_usage(stage_results),
            "artefacts": {name: str(path) for name, path in ctx.artefacts.items()},
        }

    def write_build_report(self, ctx: CompilationContext) -> dict[str, Any]:
        """Write ``build_report.json`` and register it as an artefact."""
        report = self.build_report(ctx)
        ctx.write_artefact("build_report", "build_report.json", report)
        return report

    def _timing(self, stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        durations = {
            name: int(payload.get("duration_ms", 0))
            for name, payload in stage_results.items()
        }
        return {
            "stage_duration_ms": durations,
            "total_stage_duration_ms": sum(durations.values()),
        }

    def _counts(self, ctx: CompilationContext) -> dict[str, Any]:
        confidence_tiers = Counter()
        review_statuses = Counter()
        for candidate in ctx.kir.iter_candidates():
            confidence_tiers[candidate.confidence.threshold_tier.value] += 1
            review_statuses[candidate.review_status.value] += 1

        return {
            "mir": {
                "schemas": len(ctx.mir.schemas) if ctx.mir is not None else 0,
                "tables": ctx.mir.table_count if ctx.mir is not None else 0,
                "profiles": len(ctx.profiles.profiles) if ctx.profiles is not None else 0,
            },
            "kir": {
                "nodes": ctx.kir.node_count,
                "edges": ctx.kir.edge_count,
                "entities": len(ctx.kir.entities),
                "concepts": len(ctx.kir.concepts),
                "metrics": len(ctx.kir.metrics),
                "rules": len(ctx.kir.rules),
                "relationships": len(ctx.kir.relationships),
                "synonyms": len(ctx.kir.synonyms),
                "time_intelligence": len(ctx.kir.time_intelligence),
                "security_tags": len(ctx.kir.security_tags),
            },
            "confidence_tiers": dict(confidence_tiers),
            "review": {
                "status_counts": dict(review_statuses),
                "queue_depth": review_statuses.get("pending_review", 0),
            },
        }

    def _diagnostics(self, stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for stage_name, payload in stage_results.items():
            for warning in payload.get("warnings", []):
                warnings.append({"stage": stage_name, "message": warning})
            for error in payload.get("errors", []):
                errors.append({"stage": stage_name, "message": error})
        return {
            "warning_count": len(warnings),
            "error_count": len(errors),
            "warnings": warnings,
            "errors": errors,
        }

    def _llm_usage(self, stage_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        calls = 0
        prompt_tokens = 0
        completion_tokens = 0
        cost_usd = 0.0
        for payload in stage_results.values():
            usage = payload.get("stats", {}).get("llm_usage")
            if not isinstance(usage, dict):
                continue
            calls += int(usage.get("calls", 0))
            prompt_tokens += int(usage.get("prompt_tokens", 0))
            completion_tokens += int(usage.get("completion_tokens", 0))
            cost_usd += float(usage.get("cost_usd", 0.0))
        return {
            "calls": calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(cost_usd, 6),
        }
