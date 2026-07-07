from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .artifacts import RunArtifacts


_STAGE_SUCCESS_STATUSES = {"success", "selection_required", "regenerated", "blocked", "failed"}


class Stage(Protocol):
    def run(self, context: "WorkerContext") -> "StageResult": ...


@dataclass(frozen=True)
class WorkerContext:
    run_id: str
    stage_name: str
    artifacts: RunArtifacts
    settings: Mapping[str, Any] = field(default_factory=dict)
    retry_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))
        object.__setattr__(self, "retry_metadata", MappingProxyType(dict(self.retry_metadata)))


@dataclass(frozen=True)
class StageResult:
    status: str
    artifacts: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _STAGE_SUCCESS_STATUSES:
            raise ValueError(f"unsupported stage status: {self.status}")
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class StageRunner:
    """Serial stage supervisor seam with skip/restart validation."""

    def __init__(self, artifacts: RunArtifacts) -> None:
        self.artifacts = artifacts

    def run_stage(
        self,
        stage_name: str,
        stage: Stage,
        outputs: dict[str, tuple[str, ...]],
        *,
        force: bool = False,
    ) -> StageResult:
        expected_outputs = tuple(outputs.keys())
        validation_failures = self._collect_validation_failures(outputs)

        if not force and not validation_failures and expected_outputs:
            result = StageResult(
                status="success",
                artifacts=expected_outputs,
                metadata={"skipped": True},
            )
            self.artifacts.append_event(
                "stage_skipped",
                stage=stage_name,
                status=result.status,
                metadata=dict(result.metadata),
                artifacts=list(result.artifacts),
            )
            return result

        if validation_failures:
            self.artifacts.append_event(
                "stage_invalidated",
                stage=stage_name,
                status="rerun_required",
                metadata={"reasons": validation_failures},
                artifacts=list(expected_outputs),
            )

        self.artifacts.append_event(
            "stage_started",
            stage=stage_name,
            status="running",
            metadata={"force": force},
            artifacts=list(expected_outputs),
        )

        context = WorkerContext(
            run_id=self.artifacts.run_id,
            stage_name=stage_name,
            artifacts=self.artifacts,
            retry_metadata={"force": force, "validation_failures": validation_failures},
        )

        try:
            result = stage.run(context)
        except Exception as exc:
            preserved_dir = self.artifacts.preserve_failed_partials(
                stage_name,
                expected_outputs,
                error=f"{type(exc).__name__}: {exc}",
            )
            result = StageResult(
                status="failed",
                artifacts=expected_outputs,
                metadata={
                    "preserved_partials_dir": str(preserved_dir.relative_to(self.artifacts.run_dir)),
                    "exception_type": type(exc).__name__,
                },
                error=str(exc),
            )
            self.artifacts.append_event(
                "stage_failed",
                stage=stage_name,
                status=result.status,
                metadata=dict(result.metadata),
                artifacts=list(result.artifacts),
                error=result.error,
            )
            return result

        if result.status == "failed":
            preserved_dir = self.artifacts.preserve_failed_partials(
                stage_name,
                expected_outputs,
                error=result.error,
            )
            result = StageResult(
                status=result.status,
                artifacts=result.artifacts or expected_outputs,
                metadata={
                    **dict(result.metadata),
                    "preserved_partials_dir": str(preserved_dir.relative_to(self.artifacts.run_dir)),
                },
                error=result.error,
            )
            self.artifacts.append_event(
                "stage_failed",
                stage=stage_name,
                status=result.status,
                metadata=dict(result.metadata),
                artifacts=list(result.artifacts),
                error=result.error,
            )
            return result

        self.artifacts.append_event(
            "stage_completed",
            stage=stage_name,
            status=result.status,
            metadata=dict(result.metadata),
            artifacts=list(result.artifacts),
        )
        return result

    def _collect_validation_failures(
        self, outputs: Mapping[str, tuple[str, ...]]
    ) -> dict[str, str]:
        failures: dict[str, str] = {}
        for relative, required_fields in outputs.items():
            validation = self.artifacts.validate_artifact(relative, required_fields)
            if not validation.valid:
                failures[relative] = validation.reason or "invalid"
        return failures
