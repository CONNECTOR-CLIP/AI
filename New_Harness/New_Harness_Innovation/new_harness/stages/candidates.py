from __future__ import annotations

from typing import Any

SELECTION_OPTIONS_JSON_PATH = "selection_options.json"
SELECTION_OPTIONS_MD_PATH = "selection_options.md"

from ..config import HarnessConfig
from ..llm.base import CandidateCardProvider
from ..llm.fake import FakeLLMProvider
from ..runner import StageResult, StageRunner, WorkerContext
from ..schemas import CandidateCard, EvidenceCard
from .critic import CandidateCriticStage
from .external_check import ExternalChecker


class CandidateGenerationStage:
    """Generate deterministic innovation candidates from evidence cards."""

    def __init__(
        self,
        *,
        round_index: int,
        candidates_per_round: int,
        provider: CandidateCardProvider | None = None,
    ) -> None:
        self.round_index = round_index
        self.candidates_per_round = candidates_per_round
        self.provider = provider or FakeLLMProvider()

    def run(self, context: WorkerContext) -> StageResult:
        evidence_cards = _load_evidence_cards(context)
        if not evidence_cards:
            return StageResult(
                status="failed",
                artifacts=(round_candidates_relative_path(self.round_index),),
                error="evidence_cards/index.json does not contain cards",
            )

        worker_context = WorkerContext(
            run_id=context.run_id,
            stage_name=f"{context.stage_name}:round_{self.round_index}",
            artifacts=context.artifacts,
            settings={
                "round_index": self.round_index,
                "candidates_per_round": self.candidates_per_round,
            },
            retry_metadata=context.retry_metadata,
        )
        context.artifacts.append_event(
            "worker_started",
            stage=worker_context.stage_name,
            status="running",
            metadata=dict(worker_context.settings),
            artifacts=[],
        )
        candidates = self.provider.generate_candidate_cards(
            worker_context,
            tuple(evidence_cards),
            round_index=self.round_index,
            candidates_per_round=self.candidates_per_round,
        )
        candidate_payload = [candidate.to_dict() for candidate in candidates]
        output_path = round_candidates_relative_path(self.round_index)
        context.artifacts.write_json(
            output_path,
            {
                "round_index": self.round_index,
                "candidates": candidate_payload,
                "candidate_count": len(candidate_payload),
            },
        )
        context.artifacts.append_event(
            "worker_completed",
            stage=worker_context.stage_name,
            status="success",
            metadata={"candidate_count": len(candidate_payload), **dict(worker_context.settings)},
            artifacts=[output_path],
        )
        return StageResult(
            status="success",
            artifacts=(output_path,),
            metadata={
                "round_index": self.round_index,
                "candidate_count": len(candidate_payload),
                "provider": type(self.provider).__name__,
            },
        )


class CandidateLoopStage:
    """Bounded regeneration loop for candidate generation and balanced criticism."""

    def __init__(
        self,
        config: HarnessConfig | None = None,
        *,
        provider: CandidateCardProvider | None = None,
        external_checker: ExternalChecker | None = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.provider = provider or FakeLLMProvider()
        self.external_checker = external_checker

    def run(self, context: WorkerContext) -> StageResult:
        runner = StageRunner(context.artifacts)
        round_summaries: list[dict[str, Any]] = []
        pass_candidate_ids: list[str] = []
        revise_candidates: list[dict[str, Any]] = []
        last_critic_path = ""

        for round_index in range(1, self.config.max_candidate_rounds + 1):
            generation_stage_name = f"candidate_generation_round_{round_index}"
            generation_path = round_candidates_relative_path(round_index)
            generation_result = runner.run_stage(
                generation_stage_name,
                CandidateGenerationStage(
                    round_index=round_index,
                    candidates_per_round=self.config.candidates_per_round,
                    provider=self.provider,
                ),
                {generation_path: ("candidates", "candidate_count", "round_index")},
            )
            if generation_result.status == "failed":
                return _child_stage_failed(generation_stage_name, generation_result)

            critic_stage_name = f"candidate_critic_round_{round_index}"
            critic_path = round_critic_relative_path(round_index)
            critic_result = runner.run_stage(
                critic_stage_name,
                CandidateCriticStage(
                    round_index=round_index,
                    config=self.config,
                    external_checker=self.external_checker,
                ),
                {
                    critic_path: (
                        "reports",
                        "report_count",
                        "pass_candidate_ids",
                        "revise_candidate_ids",
                        "fail_candidate_ids",
                    )
                },
            )
            if critic_result.status == "failed":
                return _child_stage_failed(critic_stage_name, critic_result)
            critic_payload = context.artifacts.read_json(critic_path)
            last_critic_path = critic_path
            pass_candidate_ids = list(critic_payload.get("pass_candidate_ids", []))
            revise_ids = set(critic_payload.get("revise_candidate_ids", []))
            round_reports = critic_payload.get("reports", [])
            revise_candidates.extend(
                report for report in round_reports if report.get("candidate_id") in revise_ids
            )
            round_summaries.append(
                {
                    "round_index": round_index,
                    "generation_path": generation_path,
                    "critic_path": critic_path,
                    "candidate_count": critic_payload.get("report_count", 0),
                    "pass_candidate_ids": list(pass_candidate_ids),
                    "revise_candidate_ids": critic_payload.get("revise_candidate_ids", []),
                    "critic_status": critic_result.status,
                }
            )
            if pass_candidate_ids:
                summary_payload = {
                    "status": "selection_required",
                    "rounds_completed": round_index,
                    "max_candidate_rounds": self.config.max_candidate_rounds,
                    "pass_candidate_ids": list(pass_candidate_ids),
                    "best_revise_candidate_ids": [],
                    "last_round_critic_report": critic_path,
                    "round_summaries": round_summaries,
                    "summary": f"Pass candidates found in round {round_index}; proceed to selection.",
                    "blocker": None,
                }
                context.artifacts.write_json("candidate_loop.json", summary_payload)
                selection_options = _build_selection_options(
                    context=context,
                    pass_candidate_ids=pass_candidate_ids,
                    generation_path=generation_path,
                    critic_path=critic_path,
                    candidate_loop_path="candidate_loop.json",
                )
                context.artifacts.write_json(SELECTION_OPTIONS_JSON_PATH, selection_options)
                context.artifacts.write_text(
                    SELECTION_OPTIONS_MD_PATH,
                    _render_selection_options_markdown(selection_options),
                )
                return StageResult(
                    status="selection_required",
                    artifacts=("candidate_loop.json", SELECTION_OPTIONS_JSON_PATH, SELECTION_OPTIONS_MD_PATH),
                    metadata={
                        "rounds_completed": round_index,
                        "pass_candidate_ids": tuple(pass_candidate_ids),
                    },
                )

        best_revise_candidate_ids = [
            report["candidate_id"]
            for report in sorted(
                revise_candidates,
                key=lambda report: (
                    float(report.get("evidence_score", 0.0)) + float(report.get("feasibility_score", 0.0)),
                    float(report.get("confidence", 0.0)),
                ),
                reverse=True,
            )[: self.config.candidates_per_round]
        ]
        summary_payload = {
            "status": "blocked",
            "rounds_completed": self.config.max_candidate_rounds,
            "max_candidate_rounds": self.config.max_candidate_rounds,
            "pass_candidate_ids": [],
            "best_revise_candidate_ids": best_revise_candidate_ids,
            "last_round_critic_report": last_critic_path,
            "round_summaries": round_summaries,
            "summary": "No pass candidates found within the configured rounds.",
            "blocker": "No candidate satisfied evidence and feasibility thresholds.",
        }
        context.artifacts.write_json("candidate_loop.json", summary_payload)
        return StageResult(
            status="blocked",
            artifacts=("candidate_loop.json",),
            metadata={
                "rounds_completed": self.config.max_candidate_rounds,
                "best_revise_candidate_ids": tuple(best_revise_candidate_ids),
            },
        )


def round_candidates_relative_path(round_index: int) -> str:
    return f"candidates/candidates_round_{round_index}.json"


def round_critic_relative_path(round_index: int) -> str:
    return f"critic_reports/critic_reports_round_{round_index}.json"


def _child_stage_failed(child_stage_name: str, result: StageResult) -> StageResult:
    return StageResult(
        status="failed",
        artifacts=result.artifacts,
        metadata={
            **dict(result.metadata),
            "failed_child_stage": child_stage_name,
        },
        error=result.error or f"{child_stage_name} failed",
    )


def _load_evidence_cards(context: WorkerContext) -> list[EvidenceCard]:
    index_payload = context.artifacts.read_json("evidence_cards/index.json")
    cards: list[EvidenceCard] = []
    for card_ref in index_payload.get("cards", []):
        card_path = card_ref.get("card_path")
        if not isinstance(card_path, str) or not card_path:
            continue
        cards.append(EvidenceCard.from_dict(context.artifacts.read_json(card_path)))
    return cards


def _build_selection_options(
    *,
    context: WorkerContext,
    pass_candidate_ids: list[str],
    generation_path: str,
    critic_path: str,
    candidate_loop_path: str,
) -> dict[str, Any]:
    candidates_payload = context.artifacts.read_json(generation_path)
    critic_payload = context.artifacts.read_json(critic_path)
    candidate_lookup = {
        candidate["candidate_id"]: candidate
        for candidate in candidates_payload.get("candidates", [])
        if isinstance(candidate, dict) and isinstance(candidate.get("candidate_id"), str)
    }
    report_lookup = {
        report["candidate_id"]: report
        for report in critic_payload.get("reports", [])
        if isinstance(report, dict) and isinstance(report.get("candidate_id"), str)
    }
    options: list[dict[str, Any]] = []
    for candidate_id in pass_candidate_ids:
        candidate = candidate_lookup.get(candidate_id, {})
        report = report_lookup.get(candidate_id, {})
        options.append(
            {
                "candidate_id": candidate_id,
                "title": candidate.get("title", ""),
                "gap_statement": candidate.get("gap_statement", ""),
                "expected_contribution": candidate.get("expected_contribution", ""),
                "supporting_evidence_refs": list(candidate.get("supporting_evidence_refs", [])),
                "critic_verdict": report.get("verdict", ""),
                "evidence_score": report.get("evidence_score", 0.0),
                "feasibility_score": report.get("feasibility_score", 0.0),
                "novelty_risk": report.get("novelty_risk", "unknown"),
                "source_paths": {
                    "candidate": generation_path,
                    "critic_report": critic_path,
                    "candidate_loop": candidate_loop_path,
                },
            }
        )
    return {
        "run_id": context.run_id,
        "status": "selection_required",
        "pass_candidate_ids": list(pass_candidate_ids),
        "candidate_summaries": options,
        "source_paths": {
            "candidate": generation_path,
            "critic_report": critic_path,
            "candidate_loop": candidate_loop_path,
        },
        "selection_command_template": f"select --run-id {context.run_id} --candidate-id <candidate_id>",
    }


def _render_selection_options_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Selection Options for {payload['run_id']}",
        "",
        "Status: selection_required",
        "",
        "Choose one pass candidate:",
        "",
    ]
    for option in payload.get("candidate_summaries", []):
        if not isinstance(option, dict):
            continue
        lines.extend(
            [
                f"## {option.get('candidate_id', '')}: {option.get('title', '')}",
                f"- Gap: {option.get('gap_statement', '')}",
                f"- Contribution: {option.get('expected_contribution', '')}",
                f"- Evidence refs: {', '.join(option.get('supporting_evidence_refs', []))}",
                (
                    "- Critic: verdict="
                    f"{option.get('critic_verdict', '')}, evidence={option.get('evidence_score', 0.0):.2f}, "
                    f"feasibility={option.get('feasibility_score', 0.0):.2f}, novelty={option.get('novelty_risk', 'unknown')}"
                ),
                (
                    "- Source paths: candidate="
                    f"{option.get('source_paths', {}).get('candidate', '')}, "
                    f"critic_report={option.get('source_paths', {}).get('critic_report', '')}, "
                    f"candidate_loop={option.get('source_paths', {}).get('candidate_loop', '')}"
                ),
                f"- Command: select --run-id {payload['run_id']} --candidate-id {option.get('candidate_id', '')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
