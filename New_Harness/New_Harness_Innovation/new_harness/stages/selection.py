from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ..runner import StageResult, WorkerContext
from ..schemas import CandidateCard, CriticReport, SelectedCandidate, SchemaValidationError


SELECTED_CANDIDATE_PATH = "selected_candidate.json"
CANDIDATE_LOOP_PATH = "candidate_loop.json"


class CandidateSelectionStage:
    """Run-bound gate that selects only pass candidates from candidate_loop.json."""

    def __init__(
        self,
        requested_run_id: str | None = None,
        candidate_id: str | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        if requested_run_id is not None and run_id is not None and requested_run_id != run_id:
            raise ValueError("requested_run_id and run_id must match when both are provided")
        selected_run_id = requested_run_id if requested_run_id is not None else run_id
        if not isinstance(selected_run_id, str) or not selected_run_id.strip():
            raise ValueError("requested_run_id must be a non-empty string")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("candidate_id must be a non-empty string")
        self.requested_run_id = selected_run_id
        self.candidate_id = candidate_id

    def run(self, context: WorkerContext) -> StageResult:
        if self.requested_run_id != context.run_id:
            return _selection_failed(
                "run_id_mismatch",
                (
                    f"requested run_id {self.requested_run_id!r} does not match "
                    f"context run_id {context.run_id!r}"
                ),
            )

        try:
            loop_payload = context.artifacts.read_json(CANDIDATE_LOOP_PATH)
        except FileNotFoundError:
            return _selection_failed("candidate_loop_missing", "candidate_loop.json is required")

        if loop_payload.get("status") != "selection_required":
            return _selection_failed(
                "selection_not_required",
                "candidate_loop.json status must be selection_required before selection",
            )

        try:
            pass_candidate_ids = _required_str_list(loop_payload, "pass_candidate_ids")
        except SchemaValidationError as exc:
            return _selection_failed("invalid_candidate_loop", str(exc))

        report_lookup = _load_reports_by_candidate_id(context, loop_payload)
        candidate_lookup = _load_candidates_by_candidate_id(context, loop_payload)
        report = report_lookup.get(self.candidate_id)
        candidate = candidate_lookup.get(self.candidate_id)

        if self.candidate_id not in pass_candidate_ids:
            if self.candidate_id in report_lookup or self.candidate_id in candidate_lookup:
                return _selection_failed(
                    "non_pass_candidate",
                    f"candidate_id {self.candidate_id!r} is not listed in pass_candidate_ids",
                )
            return _selection_failed(
                "unknown_candidate_id",
                f"candidate_id {self.candidate_id!r} was not found in candidate artifacts",
            )

        if report is None or candidate is None:
            return _selection_failed(
                "unknown_candidate_id",
                f"candidate_id {self.candidate_id!r} lacks a candidate card or critic report",
            )

        if report.verdict != "pass":
            return _selection_failed(
                "non_pass_candidate",
                f"candidate_id {self.candidate_id!r} critic verdict is {report.verdict!r}",
            )

        candidate_source_path = _candidate_source_path_for_id(context, loop_payload, self.candidate_id)
        critic_report_path = _critic_report_path_for_id(context, loop_payload, self.candidate_id)
        try:
            selected = SelectedCandidate(
                run_id=context.run_id,
                candidate_id=self.candidate_id,
                selected_at=datetime.now(timezone.utc).isoformat(),
                candidate=candidate,
                critic_report=report,
                source_paths={
                    "candidate_loop": CANDIDATE_LOOP_PATH,
                    "candidate": candidate_source_path,
                    "critic_report": critic_report_path,
                },
                pass_candidate_ids=tuple(pass_candidate_ids),
            )
        except SchemaValidationError as exc:
            return _selection_failed("invalid_selected_candidate", str(exc))

        context.artifacts.write_json(SELECTED_CANDIDATE_PATH, selected.to_dict())
        return StageResult(
            status="success",
            artifacts=(SELECTED_CANDIDATE_PATH,),
            metadata={
                "candidate_id": self.candidate_id,
                "run_id": context.run_id,
                "source_paths": dict(selected.source_paths),
            },
        )


SelectionStage = CandidateSelectionStage


def _selection_failed(reason: str, message: str) -> StageResult:
    return StageResult(
        status="failed",
        artifacts=(SELECTED_CANDIDATE_PATH,),
        metadata={"reason": reason},
        error=f"{reason}: {message}",
    )


def _required_str_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise SchemaValidationError(f"{key} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{key} must contain non-empty strings")
        if item not in result:
            result.append(item)
    return result


def _load_reports_by_candidate_id(
    context: WorkerContext,
    loop_payload: dict[str, Any],
) -> dict[str, CriticReport]:
    reports: dict[str, CriticReport] = {}
    for path in _critic_report_paths(loop_payload):
        try:
            payload = context.artifacts.read_json(path)
        except FileNotFoundError:
            continue
        for report_payload in payload.get("reports", []):
            try:
                report = CriticReport.from_dict(report_payload)
            except SchemaValidationError:
                continue
            reports.setdefault(report.candidate_id, report)
    return reports


def _load_candidates_by_candidate_id(
    context: WorkerContext,
    loop_payload: dict[str, Any],
) -> dict[str, CandidateCard]:
    candidates: dict[str, CandidateCard] = {}
    for path in _generation_paths(loop_payload):
        try:
            payload = context.artifacts.read_json(path)
        except FileNotFoundError:
            continue
        for candidate_payload in payload.get("candidates", []):
            try:
                candidate = CandidateCard.from_dict(candidate_payload)
            except SchemaValidationError:
                continue
            candidates.setdefault(candidate.candidate_id, candidate)
    return candidates


def _candidate_source_path_for_id(
    context: WorkerContext,
    loop_payload: dict[str, Any],
    candidate_id: str,
) -> str:
    for path in _generation_paths(loop_payload):
        try:
            payload = context.artifacts.read_json(path)
        except FileNotFoundError:
            continue
        for candidate_payload in payload.get("candidates", []):
            if isinstance(candidate_payload, dict) and candidate_payload.get("candidate_id") == candidate_id:
                return path
    return ""


def _critic_report_path_for_id(
    context: WorkerContext,
    loop_payload: dict[str, Any],
    candidate_id: str,
) -> str:
    for path in _critic_report_paths(loop_payload):
        try:
            payload = context.artifacts.read_json(path)
        except FileNotFoundError:
            continue
        for report_payload in payload.get("reports", []):
            if isinstance(report_payload, dict) and report_payload.get("candidate_id") == candidate_id:
                return path
    return ""


def _critic_report_paths(loop_payload: dict[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    last_path = loop_payload.get("last_round_critic_report")
    if isinstance(last_path, str) and last_path.strip():
        paths.append(last_path)
    for summary in _round_summaries(loop_payload):
        path = summary.get("critic_path")
        if isinstance(path, str) and path.strip():
            paths.append(path)
    return tuple(_unique(paths))


def _generation_paths(loop_payload: dict[str, Any]) -> tuple[str, ...]:
    paths: list[str] = []
    for summary in _round_summaries(loop_payload):
        path = summary.get("generation_path")
        if isinstance(path, str) and path.strip():
            paths.append(path)
    return tuple(_unique(paths))


def _round_summaries(loop_payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    summaries = loop_payload.get("round_summaries", [])
    if not isinstance(summaries, list):
        return ()
    return tuple(summary for summary in summaries if isinstance(summary, dict))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
