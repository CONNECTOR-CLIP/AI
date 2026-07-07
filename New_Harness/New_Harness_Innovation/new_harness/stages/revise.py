from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from ..runner import StageResult, WorkerContext
from ..schemas import RevisionRecord, SchemaValidationError, SelectedCandidate


DRAFT_PATH = "draft.md"
CLAIM_MAP_PATH = "draft.claim_map.json"
SELECTED_CANDIDATE_PATH = "selected_candidate.json"
REVISIONS_DIR = "revisions"
SUPPORTED_MODES = {"qa_suggest", "auto_edit"}


class RevisionStage:
    """Deterministic offline revision/Q&A stage bound to a specific run."""

    def __init__(
        self,
        *,
        requested_run_id: str,
        mode: str,
        user_request: str,
    ) -> None:
        if not isinstance(requested_run_id, str) or not requested_run_id.strip():
            raise ValueError("requested_run_id must be a non-empty string")
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"unsupported revision mode: {mode}")
        if not isinstance(user_request, str) or not user_request.strip():
            raise ValueError("user_request must be a non-empty string")
        self.requested_run_id = requested_run_id
        self.mode = mode
        self.user_request = user_request.strip()

    def run(self, context: WorkerContext) -> StageResult:
        if self.requested_run_id != context.run_id:
            return _revision_failed(
                "run_id_mismatch",
                f"requested run_id {self.requested_run_id!r} does not match context run_id {context.run_id!r}",
            )

        loaded = _load_revision_context(context)
        if isinstance(loaded, StageResult):
            return loaded
        selected_candidate, claim_map, draft_text = loaded

        if selected_candidate.run_id != context.run_id:
            return _revision_failed(
                "selected_candidate_run_id_mismatch",
                f"selected_candidate.json run_id {selected_candidate.run_id!r} does not match context run_id {context.run_id!r}",
            )
        if claim_map.get("run_id") != context.run_id:
            return _revision_failed(
                "claim_map_run_id_mismatch",
                f"draft.claim_map.json run_id {claim_map.get('run_id')!r} does not match context run_id {context.run_id!r}",
            )
        if claim_map.get("candidate_id") != selected_candidate.candidate_id:
            return _revision_failed(
                "claim_map_candidate_id_mismatch",
                "draft.claim_map.json candidate_id does not match selected_candidate.json",
            )

        evidence_refs = _collect_evidence_refs(selected_candidate, claim_map)
        answer_summary = _build_revision_summary(
            mode=self.mode,
            user_request=self.user_request,
            selected_candidate=selected_candidate,
            claim_map=claim_map,
            evidence_refs=evidence_refs,
        )
        files_changed: tuple[str, ...] = ()
        revision_artifacts: list[str] = []

        if self.mode == "auto_edit":
            updated_draft = _apply_auto_edit(
                draft_text=draft_text,
                user_request=self.user_request,
                selected_candidate=selected_candidate,
                claim_map=claim_map,
                evidence_refs=evidence_refs,
            )
            context.artifacts.write_text(DRAFT_PATH, updated_draft)
            files_changed = (DRAFT_PATH,)
            revision_artifacts.append(DRAFT_PATH)

        record = RevisionRecord(
            mode=self.mode,
            user_request=self.user_request,
            answer_or_diff_summary=answer_summary,
            files_changed=files_changed,
            evidence_refs=evidence_refs,
            run_id=context.run_id,
            selected_candidate_id=selected_candidate.candidate_id,
            draft_path=DRAFT_PATH,
            claim_map_path=CLAIM_MAP_PATH,
            selected_candidate_path=SELECTED_CANDIDATE_PATH,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        record_path = _revision_record_path(context, self.mode, self.user_request)
        context.artifacts.write_json(record_path, record.to_dict())
        revision_artifacts.append(record_path)
        context.artifacts.append_event(
            "revision_applied",
            stage=context.stage_name,
            status="success",
            metadata={
                "mode": self.mode,
                "record_path": record_path,
                "selected_candidate_id": selected_candidate.candidate_id,
            },
            artifacts=revision_artifacts,
        )
        return StageResult(
            status="success",
            artifacts=tuple(revision_artifacts),
            metadata={
                "mode": self.mode,
                "record_path": record_path,
                "files_changed": list(files_changed),
                "selected_candidate_id": selected_candidate.candidate_id,
            },
        )


def _load_revision_context(
    context: WorkerContext,
) -> tuple[SelectedCandidate, dict[str, Any], str] | StageResult:
    try:
        selected_payload = context.artifacts.read_json(SELECTED_CANDIDATE_PATH)
    except FileNotFoundError:
        return _revision_failed("selected_candidate_missing", "selected_candidate.json is required")
    try:
        claim_map = context.artifacts.read_json(CLAIM_MAP_PATH)
    except FileNotFoundError:
        return _revision_failed("claim_map_missing", "draft.claim_map.json is required")
    try:
        draft_text = context.artifacts.read_text(DRAFT_PATH)
    except FileNotFoundError:
        return _revision_failed("draft_missing", "draft.md is required")

    try:
        selected_candidate = SelectedCandidate.from_dict(selected_payload)
    except SchemaValidationError as exc:
        return _revision_failed("invalid_selected_candidate", str(exc))

    if not isinstance(claim_map.get("claims"), list):
        return _revision_failed("invalid_claim_map", "draft.claim_map.json must contain claims")
    return selected_candidate, claim_map, draft_text


def _collect_evidence_refs(selected_candidate: SelectedCandidate, claim_map: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = list(selected_candidate.candidate.supporting_evidence_refs)
    for claim in claim_map.get("claims", []):
        if not isinstance(claim, dict):
            continue
        trace = claim.get("trace")
        if not isinstance(trace, dict):
            continue
        for evidence_entry in trace.get("evidence_refs", []):
            if not isinstance(evidence_entry, dict):
                continue
            paper_id = evidence_entry.get("paper_id")
            if isinstance(paper_id, str) and paper_id not in refs:
                refs.append(paper_id)
    return tuple(refs)


def _build_revision_summary(
    *,
    mode: str,
    user_request: str,
    selected_candidate: SelectedCandidate,
    claim_map: dict[str, Any],
    evidence_refs: tuple[str, ...],
) -> str:
    risk_notes = claim_map.get("risk_notes", {}) if isinstance(claim_map.get("risk_notes"), dict) else {}
    candidate_risks = risk_notes.get("candidate_risks", [])
    critic_weaknesses = risk_notes.get("critic_weaknesses", [])
    fixes = risk_notes.get("required_fixes", [])
    lead_risk = _first_list_item(candidate_risks) or _first_list_item(critic_weaknesses) or "No explicit risk note was recorded."
    lead_fix = _first_list_item(fixes) or "Retain the current evidence boundaries from the claim map."
    prefix = "Suggested response" if mode == "qa_suggest" else "Applied edit"
    return (
        f"{prefix} for request: {user_request}. "
        f"Candidate {selected_candidate.candidate_id} remains grounded in evidence refs {', '.join(evidence_refs)}. "
        f"Primary risk: {lead_risk}. "
        f"Next revision focus: {lead_fix}."
    )


def _apply_auto_edit(
    *,
    draft_text: str,
    user_request: str,
    selected_candidate: SelectedCandidate,
    claim_map: dict[str, Any],
    evidence_refs: tuple[str, ...],
) -> str:
    risk_notes = claim_map.get("risk_notes", {}) if isinstance(claim_map.get("risk_notes"), dict) else {}
    weak = _first_list_item(risk_notes.get("critic_weaknesses", [])) or "No critic weakness recorded."
    fix = _first_list_item(risk_notes.get("required_fixes", [])) or "No required fix recorded."
    evidence_line = ", ".join(evidence_refs)
    section = "\n".join(
        [
            "## Revision Update",
            f"Request addressed: {user_request}",
            f"Selected candidate: {selected_candidate.candidate_id}",
            f"Evidence anchors: {evidence_line}",
            f"Critic weakness: {weak}",
            f"Required fix: {fix}",
            "",
        ]
    )
    return draft_text.rstrip() + "\n\n" + section


def _revision_record_path(context: WorkerContext, mode: str, user_request: str) -> str:
    digest = hashlib.sha256(f"{mode}\n{user_request}".encode("utf-8")).hexdigest()[:12]
    prefix = f"{mode}-{digest}"
    first_relative = f"{REVISIONS_DIR}/{prefix}.json"
    if not context.artifacts.artifact_path(first_relative).exists():
        return first_relative

    counter = 2
    while True:
        if counter > 999:
            raise RuntimeError(f"too many revision records already exist for prefix {prefix!r}")
        relative = f"{REVISIONS_DIR}/{prefix}-{counter:02d}.json"
        if not context.artifacts.artifact_path(relative).exists():
            return relative
        counter += 1


def _first_list_item(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    for item in value:
        if isinstance(item, str) and item.strip():
            return item.strip()
    return ""


def _revision_failed(reason: str, message: str) -> StageResult:
    return StageResult(
        status="failed",
        metadata={"reason": reason},
        error=f"{reason}: {message}",
    )
