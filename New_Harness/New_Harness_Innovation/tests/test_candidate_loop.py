from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from new_harness.artifacts import RunArtifacts
from new_harness.config import HarnessConfig
from new_harness.llm.fake import FakeLLMProvider
from new_harness.runner import StageRunner, WorkerContext
from new_harness.schemas import CandidateCard, CriticReport, EvidenceCard
from new_harness.stages.candidates import CandidateGenerationStage, CandidateLoopStage
from new_harness.stages.critic import CandidateCriticStage


class WeakCandidateProvider(FakeLLMProvider):
    def generate_candidate_cards(
        self,
        context: WorkerContext,
        evidence_cards: tuple[EvidenceCard, ...],
        *,
        round_index: int,
        candidates_per_round: int,
    ) -> tuple[CandidateCard, ...]:
        del context, evidence_cards
        return tuple(
            CandidateCard(
                candidate_id=f"weak-r{round_index}-{idx + 1}",
                title=f"Weak candidate {idx + 1}",
                gap_statement="A vague gap with limited traceability.",
                hypothesis="This may help somehow.",
                supporting_evidence_refs=("paper-a",),
                proposed_method="Sketch a direction.",
                evaluation_plan="Benchmark pilot.",
                expected_contribution="Possibly useful insight.",
                risks=("Weak evidence grounding.",),
            )
            for idx in range(candidates_per_round)
        )


class CandidateLoopTests(unittest.TestCase):
    def test_candidate_generation_reads_evidence_cards_and_writes_n_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-candidates")
            runner = StageRunner(artifacts)
            _seed_evidence_cards(artifacts)

            result = runner.run_stage(
                "candidate_generation_round_1",
                CandidateGenerationStage(round_index=1, candidates_per_round=3),
                {"candidates/candidates_round_1.json": ("candidates", "candidate_count", "round_index")},
            )

            self.assertEqual(result.status, "success")
            payload = artifacts.read_json("candidates/candidates_round_1.json")
            self.assertEqual(payload["candidate_count"], 3)
            self.assertEqual(payload["round_index"], 1)
            self.assertEqual(len(payload["candidates"]), 3)
            self.assertTrue(payload["candidates"][0]["supporting_evidence_refs"])
            self.assertIn("paper-a", payload["candidates"][0]["supporting_evidence_refs"])

    def test_critic_passes_grounded_candidate_and_fails_or_revises_weaker_ones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-critic")
            runner = StageRunner(artifacts)
            _seed_evidence_cards(artifacts)
            strong = CandidateCard(
                candidate_id="cand-strong",
                title="Grounded benchmark extension",
                gap_statement="Evidence shows current evaluation leaves an open cross-domain gap.",
                hypothesis="A benchmark-calibrated extension can improve generalization.",
                supporting_evidence_refs=("paper-a", "paper-b"),
                proposed_method="Adapt the benchmarked agent pipeline into a cross-domain controller.",
                evaluation_plan="Run an ablation and benchmark comparison with reported metrics from paper-a and paper-b.",
                expected_contribution="A feasible evidence-grounded improvement.",
                risks=("Novelty not externally verified yet.",),
            )
            weak = CandidateCard(
                candidate_id="cand-weak",
                title="Underspecified idea",
                gap_statement="Something might be missing.",
                hypothesis="An idea may help.",
                supporting_evidence_refs=("paper-a",),
                proposed_method="Sketch a direction.",
                evaluation_plan="Benchmark pilot.",
                expected_contribution="A maybe useful idea.",
                risks=("No strong evaluation tie.",),
            )
            artifacts.write_json(
                "candidates/candidates_round_1.json",
                {
                    "round_index": 1,
                    "candidates": [strong.to_dict(), weak.to_dict()],
                    "candidate_count": 2,
                },
            )

            runner.run_stage(
                "candidate_critic_round_1",
                CandidateCriticStage(round_index=1, config=HarnessConfig()),
                {
                    "critic_reports/critic_reports_round_1.json": (
                        "reports",
                        "report_count",
                        "pass_candidate_ids",
                        "revise_candidate_ids",
                        "fail_candidate_ids",
                    )
                },
            )

            reports_payload = artifacts.read_json("critic_reports/critic_reports_round_1.json")
            reports = {report["candidate_id"]: report for report in reports_payload["reports"]}
            self.assertEqual(reports["cand-strong"]["verdict"], "pass")
            self.assertGreaterEqual(reports["cand-strong"]["evidence_score"], 0.65)
            self.assertGreaterEqual(reports["cand-strong"]["feasibility_score"], 0.65)
            self.assertIn(reports["cand-weak"]["verdict"], {"fail", "revise"})
            self.assertLess(reports["cand-weak"]["feasibility_score"], 0.65)

    def test_near_pass_heuristic_is_controlled_by_config_thresholds_and_margin(self) -> None:
        config = HarnessConfig(
            evidence_pass_threshold=0.65,
            feasibility_pass_threshold=0.65,
            near_pass_margin=0.15,
        )

        self.assertTrue(
            config.is_near_pass(
                evidence_score=0.70,
                feasibility_score=0.52,
                novelty_risk="unknown",
            )
        )
        self.assertFalse(
            config.is_near_pass(
                evidence_score=0.70,
                feasibility_score=0.49,
                novelty_risk="unknown",
            )
        )
        self.assertTrue(
            config.is_near_pass(
                evidence_score=0.70,
                feasibility_score=0.70,
                novelty_risk="unknown",
            )
        )
        self.assertFalse(
            config.is_near_pass(
                evidence_score=0.70,
                feasibility_score=0.70,
                novelty_risk="low",
            )
        )

    def test_no_pass_loop_regenerates_bounded_rounds_and_reports_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-blocked")
            runner = StageRunner(artifacts)
            _seed_evidence_cards(artifacts)
            config = HarnessConfig(candidates_per_round=2, max_candidate_rounds=2)

            result = runner.run_stage(
                "candidate_loop",
                CandidateLoopStage(config=config, provider=WeakCandidateProvider()),
                {"candidate_loop.json": ("status", "rounds_completed", "best_revise_candidate_ids")},
            )

            self.assertEqual(result.status, "blocked")
            loop_payload = artifacts.read_json("candidate_loop.json")
            self.assertEqual(loop_payload["status"], "blocked")
            self.assertEqual(loop_payload["rounds_completed"], 2)
            self.assertEqual(len(loop_payload["round_summaries"]), 2)
            self.assertTrue(loop_payload["best_revise_candidate_ids"])
            self.assertEqual(loop_payload["round_summaries"][-1]["round_index"], 2)

    def test_candidate_loop_propagates_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-generation-failure")
            artifacts.write_json("evidence_cards/index.json", {"cards": [], "card_count": 0})

            result = StageRunner(artifacts).run_stage(
                "candidate_loop",
                CandidateLoopStage(config=HarnessConfig(candidates_per_round=2, max_candidate_rounds=2)),
                {"candidate_loop.json": ("status", "rounds_completed", "best_revise_candidate_ids")},
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error, "evidence_cards/index.json does not contain cards")
            self.assertIn("candidates/candidates_round_1.json", result.artifacts)
            self.assertFalse(artifacts.artifact_path("candidate_loop.json").exists())
            self.assertFalse(artifacts.artifact_path("critic_reports/critic_reports_round_1.json").exists())

    def test_candidate_loop_propagates_critic_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-critic-failure")
            _seed_evidence_cards(artifacts)
            artifacts.write_json(
                "candidates/candidates_round_1.json",
                {
                    "round_index": 1,
                    "candidate_count": 1,
                    "candidates": [{"candidate_id": "invalid-candidate"}],
                },
            )

            result = StageRunner(artifacts).run_stage(
                "candidate_loop",
                CandidateLoopStage(config=HarnessConfig(candidates_per_round=1, max_candidate_rounds=1)),
                {"candidate_loop.json": ("status", "rounds_completed", "best_revise_candidate_ids")},
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.metadata["failed_child_stage"], "candidate_critic_round_1")
            self.assertIn("critic_reports/critic_reports_round_1.json", result.artifacts)
            self.assertIn("title must be a non-empty string", result.error or "")
            self.assertFalse(artifacts.artifact_path("candidate_loop.json").exists())

    def test_pass_loop_stops_early_and_returns_selection_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-pass-loop")
            runner = StageRunner(artifacts)
            _seed_evidence_cards(artifacts)
            config = HarnessConfig(candidates_per_round=3, max_candidate_rounds=2)

            result = runner.run_stage(
                "candidate_loop",
                CandidateLoopStage(config=config),
                {"candidate_loop.json": ("status", "rounds_completed", "pass_candidate_ids")},
            )

            self.assertEqual(result.status, "selection_required")
            loop_payload = artifacts.read_json("candidate_loop.json")
            options_payload = artifacts.read_json("selection_options.json")
            options_markdown = artifacts.read_text("selection_options.md")
            self.assertEqual(loop_payload["status"], "selection_required")
            self.assertEqual(loop_payload["rounds_completed"], 1)
            self.assertTrue(loop_payload["pass_candidate_ids"])
            self.assertEqual(len(loop_payload["round_summaries"]), 1)
            self.assertEqual(
                loop_payload["round_summaries"][0]["critic_path"],
                "critic_reports/critic_reports_round_1.json",
            )
            self.assertEqual(options_payload["run_id"], "run-pass-loop")
            self.assertEqual(options_payload["status"], "selection_required")
            self.assertEqual(options_payload["pass_candidate_ids"], loop_payload["pass_candidate_ids"])
            self.assertTrue(options_payload["candidate_summaries"])
            self.assertEqual(
                options_payload["source_paths"]["candidate_loop"],
                "candidate_loop.json",
            )
            self.assertIn("select --run-id run-pass-loop --candidate-id", options_markdown)


class SchemaExtensionTests(unittest.TestCase):
    def test_candidate_and_critic_schema_round_trip(self) -> None:
        candidate = CandidateCard(
            candidate_id="cand-1",
            title="A title",
            gap_statement="A grounded gap.",
            hypothesis="A hypothesis.",
            supporting_evidence_refs=("paper-a",),
            proposed_method="A method.",
            evaluation_plan="An evaluation plan.",
            expected_contribution="A contribution.",
            risks=("Novelty unknown.",),
        )
        report = CriticReport(
            candidate_id="cand-1",
            verdict="revise",
            evidence_score=0.7,
            feasibility_score=0.55,
            novelty_risk="unknown",
            weaknesses=("Need stronger evaluation.",),
            required_fixes=("Add benchmark plan.",),
            rationale="Scores show a near-pass candidate.",
            near_pass=True,
            verification_status="not_checked",
            confidence=0.625,
            metadata={"source": "test"},
        )

        self.assertEqual(CandidateCard.from_dict(candidate.to_dict()).candidate_id, "cand-1")
        self.assertTrue(CriticReport.from_dict(report.to_dict()).near_pass)


def _seed_evidence_cards(artifacts: RunArtifacts) -> None:
    card_a = EvidenceCard(
        paper_id="paper-a",
        claims=("Benchmarking agent systems identifies a cross-domain transfer gap.",),
        methods=("A benchmark method and agent pipeline are described.",),
        limitations=("Generalization across tasks remains limited.",),
        evaluation_signals=("Experiments report benchmark accuracy and ablations.",),
        future_work_clues=("Future work should extend the benchmark to harder tasks.",),
        quotes_or_snippets=("Benchmarking agent systems",),
        confidence=0.9,
    )
    card_b = EvidenceCard(
        paper_id="paper-b",
        claims=("A symbolic control method improves planning reliability.",),
        methods=("The approach combines planning constraints with an algorithmic controller.",),
        limitations=("The controller is only tested on narrow domains.",),
        evaluation_signals=("Baseline comparison and experiment scores are reported.",),
        future_work_clues=("Future work can extend the controller to multi-domain settings.",),
        quotes_or_snippets=("Symbolic control for planning",),
        confidence=0.85,
    )
    artifacts.write_json("evidence_cards/paper-a.json", card_a.to_dict())
    artifacts.write_json("evidence_cards/paper-b.json", card_b.to_dict())
    artifacts.write_json(
        "evidence_cards/index.json",
        {
            "cards": [
                {"paper_id": "paper-a", "card_path": "evidence_cards/paper-a.json", "confidence": 0.9},
                {"paper_id": "paper-b", "card_path": "evidence_cards/paper-b.json", "confidence": 0.85},
            ],
            "card_count": 2,
        },
    )


if __name__ == "__main__":
    unittest.main()
