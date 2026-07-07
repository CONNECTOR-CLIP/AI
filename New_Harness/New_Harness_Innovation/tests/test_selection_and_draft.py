from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from new_harness.artifacts import RunArtifacts
from new_harness.runner import StageRunner
from new_harness.schemas import CandidateCard, CriticReport, EvidenceCard, SelectedCandidate
from new_harness.stages.draft import DraftGenerationStage
from new_harness.stages.selection import CandidateSelectionStage


class SelectionStageTests(unittest.TestCase):
    def test_selection_accepts_only_pass_candidate_for_matching_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-select")
            _seed_selection_inputs(artifacts)

            result = StageRunner(artifacts).run_stage(
                "selection",
                CandidateSelectionStage(requested_run_id="run-select", candidate_id="cand-pass"),
                {"selected_candidate.json": ("run_id", "candidate_id", "selected_at", "source_paths")},
            )

            self.assertEqual(result.status, "success")
            payload = artifacts.read_json("selected_candidate.json")
            selected = SelectedCandidate.from_dict(payload)
            self.assertEqual(selected.run_id, "run-select")
            self.assertEqual(selected.candidate_id, "cand-pass")
            self.assertTrue(selected.selected_at)
            self.assertEqual(
                selected.source_paths,
                {
                    "candidate_loop": "candidate_loop.json",
                    "candidate": "candidates/candidates_round_1.json",
                    "critic_report": "critic_reports/critic_reports_round_1.json",
                },
            )

    def test_selection_rejects_run_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-select")
            _seed_selection_inputs(artifacts)

            result = StageRunner(artifacts).run_stage(
                "selection",
                CandidateSelectionStage(requested_run_id="other-run", candidate_id="cand-pass"),
                {"selected_candidate.json": ("run_id", "candidate_id")},
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("run_id_mismatch", result.error or "")

    def test_selection_rejects_unknown_or_non_pass_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-select")
            _seed_selection_inputs(artifacts)
            runner = StageRunner(artifacts)

            non_pass = runner.run_stage(
                "selection_non_pass",
                CandidateSelectionStage(requested_run_id="run-select", candidate_id="cand-revise"),
                {"selected_candidate.json": ("run_id", "candidate_id")},
            )
            unknown = runner.run_stage(
                "selection_unknown",
                CandidateSelectionStage(requested_run_id="run-select", candidate_id="cand-missing"),
                {"selected_candidate.json": ("run_id", "candidate_id")},
                force=True,
            )

            self.assertEqual(non_pass.status, "failed")
            self.assertIn("non_pass_candidate", non_pass.error or "")
            self.assertEqual(unknown.status, "failed")
            self.assertIn("unknown_candidate_id", unknown.error or "")


class DraftGenerationStageTests(unittest.TestCase):
    def test_draft_generation_writes_markdown_and_claim_map_with_risk_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-draft")
            _seed_selection_inputs(artifacts, run_id="run-draft")
            runner = StageRunner(artifacts)
            selection_result = runner.run_stage(
                "selection",
                CandidateSelectionStage(requested_run_id="run-draft", candidate_id="cand-pass"),
                {"selected_candidate.json": ("run_id", "candidate_id", "selected_at", "source_paths")},
            )
            self.assertEqual(selection_result.status, "success")

            result = runner.run_stage(
                "draft",
                DraftGenerationStage(),
                {
                    "draft.md": (),
                    "draft.claim_map.json": ("run_id", "candidate_id", "claims", "risk_notes"),
                },
            )

            self.assertEqual(result.status, "success")
            draft_text = artifacts.read_text("draft.md")
            claim_map = artifacts.read_json("draft.claim_map.json")

            for heading in (
                "# Evidence-Grounded Controller",
                "## Abstract",
                "## Introduction",
                "## Related and Future-Work Motivation",
                "## Proposed Direction",
                "## Evaluation Plan",
                "## Limitations and Risks",
                "## Conclusion",
            ):
                self.assertIn(heading, draft_text)
            for legacy_heading in ("### Gap", "### Hypothesis", "### Method", "### Evaluation", "### Contribution"):
                self.assertIn(legacy_heading, draft_text)
            self.assertIn("Evidence anchor (Benchmarking Agent Systems / paper-a):", draft_text)
            self.assertIn("Evidence anchor (Symbolic Cross-Domain Control / paper-b):", draft_text)
            self.assertIn("Critic verdict: pass", draft_text)
            self.assertIn("Novelty risk: unknown", draft_text)
            self.assertIn("Candidate risk:", draft_text)
            self.assertIn("Critic weakness:", draft_text)
            self.assertIn("Required fix:", draft_text)
            self.assertIn("## Claim Map and Traceability Notes", draft_text)
            self.assertIn("- Candidate ID: cand-pass", draft_text)
            self.assertEqual(claim_map["run_id"], "run-draft")
            self.assertEqual(claim_map["candidate_id"], "cand-pass")
            self.assertEqual(claim_map["selected_candidate_path"], "selected_candidate.json")
            self.assertEqual(len(claim_map["claims"]), 5)
            first_claim = claim_map["claims"][0]
            self.assertEqual(first_claim["trace"]["selected_candidate_path"], "selected_candidate.json")
            self.assertEqual(first_claim["trace"]["candidate_id"], "cand-pass")
            self.assertTrue(first_claim["trace"]["evidence_refs"])
            self.assertEqual(
                claim_map["risk_notes"]["candidate_risks"],
                ["Novelty is still only metadata-verified."],
            )
            self.assertEqual(
                claim_map["risk_notes"]["critic_weaknesses"],
                ["Cross-domain generalization needs clearer ablation boundaries."],
            )
            self.assertEqual(
                claim_map["risk_notes"]["required_fixes"],
                ["Define the ablation split before final manuscript submission."],
            )


def _seed_selection_inputs(artifacts: RunArtifacts, *, run_id: str | None = None) -> None:
    del run_id
    _seed_selected_papers(artifacts)
    _seed_evidence_cards(artifacts)

    pass_candidate = CandidateCard(
        candidate_id="cand-pass",
        title="Evidence-Grounded Controller",
        gap_statement="Selected papers expose an unresolved cross-domain control gap.",
        hypothesis="A controller aligned to the benchmarked evidence can close the transfer gap.",
        supporting_evidence_refs=("paper-a", "paper-b"),
        proposed_method="Adapt the symbolic controller into the benchmarked agent pipeline.",
        evaluation_plan="Run benchmark comparisons and ablations tied to paper-a and paper-b signals.",
        expected_contribution="A feasible cross-domain controller with evidence-grounded evaluation.",
        risks=("Novelty is still only metadata-verified.",),
    )
    revise_candidate = CandidateCard(
        candidate_id="cand-revise",
        title="Under-specified extension",
        gap_statement="A vague gap remains.",
        hypothesis="A simple change might help.",
        supporting_evidence_refs=("paper-a",),
        proposed_method="Sketch a lightweight change.",
        evaluation_plan="Pilot benchmark.",
        expected_contribution="A possible improvement.",
        risks=("Needs stronger evaluation details.",),
    )
    artifacts.write_json(
        "candidates/candidates_round_1.json",
        {
            "round_index": 1,
            "candidates": [pass_candidate.to_dict(), revise_candidate.to_dict()],
            "candidate_count": 2,
        },
    )

    pass_report = CriticReport(
        candidate_id="cand-pass",
        verdict="pass",
        evidence_score=0.81,
        feasibility_score=0.78,
        novelty_risk="unknown",
        weaknesses=("Cross-domain generalization needs clearer ablation boundaries.",),
        required_fixes=("Define the ablation split before final manuscript submission.",),
        rationale="The candidate is evidence-grounded and feasible enough to draft.",
        near_pass=True,
        verification_status="selected_only",
        confidence=0.795,
        metadata={"resolved_evidence_refs": ["paper-a", "paper-b"]},
    )
    revise_report = CriticReport(
        candidate_id="cand-revise",
        verdict="revise",
        evidence_score=0.65,
        feasibility_score=0.52,
        novelty_risk="unknown",
        weaknesses=("Evaluation is too thin.",),
        required_fixes=("Add a clearer benchmark and ablation plan.",),
        rationale="The candidate remains near pass but not selectable.",
        near_pass=True,
        verification_status="selected_only",
        confidence=0.585,
        metadata={"resolved_evidence_refs": ["paper-a"]},
    )
    artifacts.write_json(
        "critic_reports/critic_reports_round_1.json",
        {
            "round_index": 1,
            "reports": [pass_report.to_dict(), revise_report.to_dict()],
            "report_count": 2,
            "pass_candidate_ids": ["cand-pass"],
            "revise_candidate_ids": ["cand-revise"],
            "fail_candidate_ids": [],
        },
    )
    artifacts.write_json(
        "candidate_loop.json",
        {
            "status": "selection_required",
            "rounds_completed": 1,
            "max_candidate_rounds": 2,
            "pass_candidate_ids": ["cand-pass"],
            "best_revise_candidate_ids": ["cand-revise"],
            "last_round_critic_report": "critic_reports/critic_reports_round_1.json",
            "round_summaries": [
                {
                    "round_index": 1,
                    "generation_path": "candidates/candidates_round_1.json",
                    "critic_path": "critic_reports/critic_reports_round_1.json",
                    "candidate_count": 2,
                    "pass_candidate_ids": ["cand-pass"],
                    "revise_candidate_ids": ["cand-revise"],
                    "critic_status": "success",
                }
            ],
            "summary": "Pass candidates found in round 1; proceed to selection.",
            "blocker": None,
        },
    )


def _seed_selected_papers(artifacts: RunArtifacts) -> None:
    artifacts.write_json(
        "selected_papers.normalized.json",
        {
            "selected_papers": [
                {
                    "paper_id": "paper-a",
                    "title": "Benchmarking Agent Systems",
                    "abstract": "Benchmarks expose a transfer gap and report strong evaluation metrics.",
                    "authors": ["A. Author"],
                    "published": "2024-01-01",
                    "arxiv_primary_category": "cs.AI",
                    "arxiv_categories": ["cs.AI"],
                    "abs_url": "https://arxiv.org/abs/2401.00001",
                    "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
                },
                {
                    "paper_id": "paper-b",
                    "title": "Symbolic Cross-Domain Control",
                    "abstract": "A symbolic controller improves planning reliability but remains domain-limited.",
                    "authors": ["B. Author"],
                    "published": "2024-01-02",
                    "arxiv_primary_category": "cs.LG",
                    "arxiv_categories": ["cs.LG"],
                    "abs_url": "https://arxiv.org/abs/2401.00002",
                    "pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
                },
            ]
        },
    )


def _seed_evidence_cards(artifacts: RunArtifacts) -> None:
    card_a = EvidenceCard(
        paper_id="paper-a",
        claims=("Benchmarking agent systems reveals a cross-domain transfer gap.",),
        methods=("A benchmarked agent pipeline measures transfer performance.",),
        limitations=("Generalization drops on harder cross-domain tasks.",),
        evaluation_signals=("Reported benchmark comparisons and ablations quantify the gap.",),
        future_work_clues=("Future work should target stronger cross-domain control.",),
        quotes_or_snippets=("Benchmarking agent systems reveals a gap.",),
        confidence=0.92,
    )
    card_b = EvidenceCard(
        paper_id="paper-b",
        claims=("Symbolic control improves planning reliability.",),
        methods=("A symbolic controller constrains decision making.",),
        limitations=("The controller is only validated in narrow domains.",),
        evaluation_signals=("Baseline comparisons show higher reliability.",),
        future_work_clues=("Extend the controller into broader domains.",),
        quotes_or_snippets=("Symbolic control improves planning reliability.",),
        confidence=0.88,
    )
    artifacts.write_json("evidence_cards/paper-a.json", card_a.to_dict())
    artifacts.write_json("evidence_cards/paper-b.json", card_b.to_dict())
    artifacts.write_json(
        "evidence_cards/index.json",
        {
            "cards": [
                {"paper_id": "paper-a", "card_path": "evidence_cards/paper-a.json"},
                {"paper_id": "paper-b", "card_path": "evidence_cards/paper-b.json"},
            ],
            "card_count": 2,
        },
    )


if __name__ == "__main__":
    unittest.main()
