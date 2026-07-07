from __future__ import annotations

from dataclasses import replace

from ..config import HarnessConfig
from ..runner import StageResult, WorkerContext
from ..schemas import CandidateCard, CriticReport, EvidenceCard
from .external_check import (
    ExternalCheckContext,
    ExternalChecker,
    degraded_external_check_report,
    should_external_check_candidate,
)


class CandidateCriticStage:
    """Score candidates with a balanced evidence/feasibility policy."""

    def __init__(
        self,
        *,
        round_index: int,
        config: HarnessConfig | None = None,
        external_checker: ExternalChecker | None = None,
    ) -> None:
        self.round_index = round_index
        self.config = config or HarnessConfig()
        self.external_checker = external_checker

    def run(self, context: WorkerContext) -> StageResult:
        candidates_payload = context.artifacts.read_json(_round_candidates_relative_path(self.round_index))
        evidence_index = context.artifacts.read_json("evidence_cards/index.json")
        evidence_by_id = {
            card_ref["paper_id"]: EvidenceCard.from_dict(context.artifacts.read_json(card_ref["card_path"]))
            for card_ref in evidence_index.get("cards", [])
            if isinstance(card_ref, dict) and isinstance(card_ref.get("paper_id"), str) and isinstance(card_ref.get("card_path"), str)
        }

        reports: list[CriticReport] = []
        candidates: list[CandidateCard] = []
        for candidate_payload in candidates_payload.get("candidates", []):
            candidate = CandidateCard.from_dict(candidate_payload)
            candidates.append(candidate)
            reports.append(_score_candidate(candidate, evidence_by_id, self.config))

        reports = _apply_external_verification(
            reports=reports,
            candidates=candidates,
            evidence_by_id=evidence_by_id,
            context=context,
            round_index=self.round_index,
            config=self.config,
            external_checker=self.external_checker,
        )

        output_path = _round_critic_relative_path(self.round_index)
        pass_ids = [report.candidate_id for report in reports if report.verdict == "pass"]
        revise_ids = [report.candidate_id for report in reports if report.verdict == "revise"]
        fail_ids = [report.candidate_id for report in reports if report.verdict == "fail"]
        context.artifacts.write_json(
            output_path,
            {
                "round_index": self.round_index,
                "reports": [report.to_dict() for report in reports],
                "report_count": len(reports),
                "pass_candidate_ids": pass_ids,
                "revise_candidate_ids": revise_ids,
                "fail_candidate_ids": fail_ids,
            },
        )
        return StageResult(
            status="success",
            artifacts=(output_path,),
            metadata={
                "round_index": self.round_index,
                "pass_count": len(pass_ids),
                "revise_count": len(revise_ids),
                "fail_count": len(fail_ids),
            },
        )


def _score_candidate(
    candidate: CandidateCard,
    evidence_by_id: dict[str, EvidenceCard],
    config: HarnessConfig,
) -> CriticReport:
    resolved_cards = [
        evidence_by_id[paper_id]
        for paper_id in candidate.supporting_evidence_refs
        if paper_id in evidence_by_id
    ]
    resolved_ref_ratio = len(resolved_cards) / len(candidate.supporting_evidence_refs)
    avg_confidence = (
        sum(card.confidence for card in resolved_cards) / len(resolved_cards)
        if resolved_cards else 0.0
    )
    evidence_score = min(
        1.0,
        0.45 * resolved_ref_ratio
        + 0.25 * min(1.0, len(resolved_cards) / 2.0)
        + 0.30 * avg_confidence,
    )

    method_quality = _method_quality(candidate.proposed_method)
    evaluation_quality = _evaluation_quality(candidate.evaluation_plan)
    benchmark_grounding = 1.0 if _evaluation_is_grounded(candidate.evaluation_plan, resolved_cards) else 0.0
    feasibility_score = min(
        1.0,
        0.35 * method_quality + 0.40 * evaluation_quality + 0.25 * benchmark_grounding,
    )

    novelty_risk = "unknown"
    near_pass = config.is_near_pass(
        evidence_score=evidence_score,
        feasibility_score=feasibility_score,
        novelty_risk=novelty_risk,
    )
    evidence_pass = evidence_score >= config.evidence_pass_threshold
    feasibility_pass = feasibility_score >= config.feasibility_pass_threshold

    weaknesses: list[str] = []
    required_fixes: list[str] = []
    if not evidence_pass:
        weaknesses.append("Selected-paper evidence traceability is below threshold.")
        required_fixes.append("Add stronger or more complete evidence references from the selected papers.")
    if not feasibility_pass:
        weaknesses.append("Experiment/evaluation feasibility is below threshold.")
        required_fixes.append("Specify an executable evaluation plan tied to the evidence card signals.")

    if evidence_pass and feasibility_pass:
        verdict = "pass"
    elif near_pass:
        verdict = "revise"
    else:
        verdict = "fail"

    confidence = (evidence_score + feasibility_score) / 2.0
    rationale = (
        f"Balanced critic scored evidence={evidence_score:.2f} and feasibility={feasibility_score:.2f}; "
        f"novelty_risk={novelty_risk}; verdict={verdict}."
    )
    return CriticReport(
        candidate_id=candidate.candidate_id,
        verdict=verdict,
        evidence_score=evidence_score,
        feasibility_score=feasibility_score,
        novelty_risk=novelty_risk,
        weaknesses=tuple(weaknesses),
        required_fixes=tuple(required_fixes),
        rationale=rationale,
        near_pass=near_pass,
        verification_status="not_checked",
        confidence=confidence,
        metadata={
            "resolved_evidence_refs": [card.paper_id for card in resolved_cards],
            "supporting_evidence_refs": list(candidate.supporting_evidence_refs),
            "evidence_pass_threshold": config.evidence_pass_threshold,
            "feasibility_pass_threshold": config.feasibility_pass_threshold,
        },
    )


def _apply_external_verification(
    *,
    reports: list[CriticReport],
    candidates: list[CandidateCard],
    evidence_by_id: dict[str, EvidenceCard],
    context: WorkerContext,
    round_index: int,
    config: HarnessConfig,
    external_checker: ExternalChecker | None,
) -> list[CriticReport]:
    if config.verification_depth == "selected_only":
        return [
            _with_novelty_note(
                report,
                verification_status="selected_only",
                note="External novelty verification intentionally deferred by selected_only policy.",
                fix="Run light_external or strong_external verification before selection if novelty must be verified.",
                metadata_updates={"external_verification_depth": config.verification_depth},
            )
            for report in reports
        ]

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    target_ids = [
        report.candidate_id
        for report in sorted(
            reports,
            key=lambda report: (-report.confidence, report.candidate_id),
        )
        if should_external_check_candidate(report, verification_depth=config.verification_depth)
    ]
    if config.verification_depth == "light_external":
        target_ids = target_ids[: config.external_check_top_k]
    target_id_set = set(target_ids)
    check_context = ExternalCheckContext(
        round_index=round_index,
        config=config,
        evidence_by_id=evidence_by_id,
    )

    updated_reports: list[CriticReport] = []
    for report in reports:
        if report.candidate_id not in target_id_set:
            updated_reports.append(
                replace(
                    report,
                    verification_status="light_external_skipped",
                    metadata={
                        **report.metadata,
                        "external_verification_depth": config.verification_depth,
                    },
                )
            )
            continue
        candidate = candidate_by_id[report.candidate_id]
        external_report = _run_external_check(
            candidate=candidate,
            check_context=check_context,
            external_checker=external_checker,
        )
        external_path = f"external_checks/round_{round_index}/{candidate.candidate_id}.json"
        context.artifacts.write_json(external_path, external_report.to_dict())
        updated_reports.append(
            _merge_external_report(
                report,
                external_report,
                external_path=external_path,
                verification_depth=config.verification_depth,
                config=config,
            )
        )
    return updated_reports


def _run_external_check(
    *,
    candidate: CandidateCard,
    check_context: ExternalCheckContext,
    external_checker: ExternalChecker | None,
):
    if external_checker is None:
        return degraded_external_check_report(
            query=candidate.title,
            source="external_checker_unavailable",
            reason="No external checker configured for non-selected_only verification depth.",
        )
    try:
        return external_checker.check_candidate(candidate, check_context)
    except Exception as exc:
        return degraded_external_check_report(
            query=candidate.title,
            source=type(external_checker).__name__,
            reason=f"{type(exc).__name__}: {exc}",
        )


def _merge_external_report(
    report: CriticReport,
    external_report,
    *,
    external_path: str,
    verification_depth: str,
    config: HarnessConfig,
) -> CriticReport:
    metadata = {
        **report.metadata,
        "external_check_path": external_path,
        "external_check_report": external_report.to_dict(),
        "external_verification_depth": verification_depth,
    }
    if external_report.degraded_reason:
        return _with_novelty_note(
            replace(
                report,
                novelty_risk="unknown",
                verification_status="degraded",
                metadata=metadata,
            ),
            verification_status="degraded",
            note=f"External novelty verification degraded: {external_report.degraded_reason}",
            fix="Re-run novelty verification with a working metadata-only checker before treating novelty as cleared.",
            metadata_updates=metadata,
        )

    updated = replace(
        report,
        novelty_risk=external_report.duplicate_risk,
        verification_status="checked",
        near_pass=config.is_near_pass(
            evidence_score=report.evidence_score,
            feasibility_score=report.feasibility_score,
            novelty_risk=external_report.duplicate_risk,
        ),
        metadata=metadata,
    )
    updated = _with_external_signal_notes(updated, external_report)
    if verification_depth == "strong_external":
        updated = _apply_strong_external_policy(updated, external_report.duplicate_risk)
    return updated


def _apply_strong_external_policy(report: CriticReport, duplicate_risk: str) -> CriticReport:
    if duplicate_risk == "high":
        return _append_feedback(
            replace(report, verdict="fail", near_pass=False),
            weakness="External metadata check indicates a high duplicate/publication overlap risk.",
            fix="Differentiate the core contribution against the flagged prior work or narrow the claim before proceeding.",
        )
    if duplicate_risk == "medium" and report.verdict == "pass":
        return _append_feedback(
            replace(report, verdict="revise", near_pass=False),
            weakness="External metadata check indicates a medium duplicate risk that blocks a pass under strong_external.",
            fix="Clarify novelty boundaries and add explicit differentiation from similar arXiv metadata matches.",
        )
    return report


def _with_external_signal_notes(report: CriticReport, external_report) -> CriticReport:
    note = (
        f"External metadata check completed via {external_report.source}; "
        f"duplicate_risk={external_report.duplicate_risk}."
    )
    updated = replace(
        report,
        rationale=f"{report.rationale} {note}",
    )
    if external_report.duplicate_risk in {"medium", "high"}:
        updated = _append_feedback(
            updated,
            weakness=f"External metadata checks found {external_report.duplicate_risk} duplicate-risk signals.",
            fix="Review the external matches and sharpen the novelty claim against them.",
        )
    return updated


def _with_novelty_note(
    report: CriticReport,
    *,
    verification_status: str,
    note: str,
    fix: str,
    metadata_updates: dict[str, object],
) -> CriticReport:
    updated = replace(
        report,
        verification_status=verification_status,
        metadata={**report.metadata, **metadata_updates},
    )
    return _append_feedback(updated, weakness=note, fix=fix)


def _append_feedback(report: CriticReport, *, weakness: str, fix: str) -> CriticReport:
    weaknesses = list(report.weaknesses)
    required_fixes = list(report.required_fixes)
    if weakness not in weaknesses:
        weaknesses.append(weakness)
    if fix not in required_fixes:
        required_fixes.append(fix)
    return replace(report, weaknesses=tuple(weaknesses), required_fixes=tuple(required_fixes))


def _round_candidates_relative_path(round_index: int) -> str:
    return f"candidates/candidates_round_{round_index}.json"


def _round_critic_relative_path(round_index: int) -> str:
    return f"critic_reports/critic_reports_round_{round_index}.json"


def _meaningful_text(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    generic_markers = ("tbd", "todo", "unknown", "n/a")
    return not any(marker == cleaned.lower() for marker in generic_markers)


def _method_quality(value: str) -> float:
    if not _meaningful_text(value):
        return 0.0
    return 1.0 if len(value.strip()) >= 40 else 0.5


def _evaluation_quality(value: str) -> float:
    if not _meaningful_text(value):
        return 0.0
    return 1.0 if len(value.strip()) >= 45 else 0.4


def _evaluation_is_grounded(plan: str, evidence_cards: list[EvidenceCard]) -> bool:
    normalized = plan.lower()
    if any(keyword in normalized for keyword in ("benchmark", "evaluate", "evaluation", "ablation", "compare", "metric", "experiment")):
        return True
    return False
