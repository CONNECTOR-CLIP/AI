from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from new_harness.artifacts import RunArtifacts
from new_harness.runner import StageRunner
from new_harness.schemas import RevisionRecord
from new_harness.stages.draft import DraftGenerationStage
from new_harness.stages.revise import RevisionStage
from new_harness.stages.selection import CandidateSelectionStage
from tests.test_selection_and_draft import _seed_selection_inputs


class RevisionStageTests(unittest.TestCase):
    def test_revision_qa_suggest_does_not_modify_draft_and_writes_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-revise")
            original_draft = artifacts.read_text("draft.md")

            result = StageRunner(artifacts).run_stage(
                "revise_qa_suggest",
                RevisionStage(
                    requested_run_id="run-revise",
                    mode="qa_suggest",
                    user_request="Explain how to strengthen the evaluation section.",
                ),
                {},
                force=True,
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(artifacts.read_text("draft.md"), original_draft)
            record = _load_single_revision_record(artifacts)
            self.assertEqual(record.mode, "qa_suggest")
            self.assertEqual(record.files_changed, ())
            self.assertEqual(record.run_id, "run-revise")
            self.assertEqual(record.selected_candidate_id, "cand-pass")
            self.assertIn("Explain how to strengthen the evaluation section.", record.answer_or_diff_summary)
            self.assertTrue(record.evidence_refs)

    def test_revision_auto_edit_modifies_draft_and_logs_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-auto-edit")
            original_draft = artifacts.read_text("draft.md")

            result = StageRunner(artifacts).run_stage(
                "revise_auto_edit",
                RevisionStage(
                    requested_run_id="run-auto-edit",
                    mode="auto_edit",
                    user_request="Add a revision update that clarifies the ablation split.",
                ),
                {},
                force=True,
            )

            self.assertEqual(result.status, "success")
            updated_draft = artifacts.read_text("draft.md")
            self.assertNotEqual(updated_draft, original_draft)
            self.assertIn("## Revision Update", updated_draft)
            self.assertIn("clarifies the ablation split", updated_draft)
            record = _load_single_revision_record(artifacts)
            self.assertEqual(record.mode, "auto_edit")
            self.assertEqual(record.files_changed, ("draft.md",))
            self.assertIn("cand-pass", record.answer_or_diff_summary)
            self.assertTrue(record.created_at)

    def test_repeated_identical_requests_write_distinct_revision_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-repeat")
            runner = StageRunner(artifacts)

            for stage_name in ("revise_qa_suggest_a", "revise_qa_suggest_b"):
                result = runner.run_stage(
                    stage_name,
                    RevisionStage(
                        requested_run_id="run-repeat",
                        mode="qa_suggest",
                        user_request="Repeat this same review request.",
                    ),
                    {},
                    force=True,
                )
                self.assertEqual(result.status, "success")

            revisions = sorted(artifacts.artifact_path("revisions").glob("*.json"))
            self.assertEqual(len(revisions), 2)
            self.assertNotEqual(revisions[0].name, revisions[1].name)
            first = RevisionRecord.from_dict(artifacts.read_json(str(revisions[0].relative_to(artifacts.run_dir))))
            second = RevisionRecord.from_dict(artifacts.read_json(str(revisions[1].relative_to(artifacts.run_dir))))
            self.assertEqual(first.mode, "qa_suggest")
            self.assertEqual(second.mode, "qa_suggest")
            self.assertEqual(first.user_request, second.user_request)

    def test_repeated_request_record_path_never_overwrites_existing_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-repeat-gap")
            artifacts.artifact_path("revisions").mkdir(parents=True, exist_ok=True)
            request = "Repeat this same review request with a preexisting suffix."

            first = StageRunner(artifacts).run_stage(
                "revise_qa_suggest_first",
                RevisionStage(
                    requested_run_id="run-repeat-gap",
                    mode="qa_suggest",
                    user_request=request,
                ),
                {},
                force=True,
            )
            self.assertEqual(first.status, "success")
            first_record = first.metadata["record_path"]
            artifacts.artifact_path(str(first_record).replace(".json", "-02.json")).write_text(
                '{"reserved": true}\n',
                encoding="utf-8",
            )

            second = StageRunner(artifacts).run_stage(
                "revise_qa_suggest_second",
                RevisionStage(
                    requested_run_id="run-repeat-gap",
                    mode="qa_suggest",
                    user_request=request,
                ),
                {},
                force=True,
            )

            self.assertEqual(second.status, "success")
            self.assertTrue(str(second.metadata["record_path"]).endswith("-03.json"))

    def test_sequential_auto_edit_preserves_prior_revision_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-auto-edit-sequential")
            runner = StageRunner(artifacts)

            first = runner.run_stage(
                "revise_auto_edit_first",
                RevisionStage(
                    requested_run_id="run-auto-edit-sequential",
                    mode="auto_edit",
                    user_request="Add the first revision update.",
                ),
                {},
                force=True,
            )
            second = runner.run_stage(
                "revise_auto_edit_second",
                RevisionStage(
                    requested_run_id="run-auto-edit-sequential",
                    mode="auto_edit",
                    user_request="Add the second revision update.",
                ),
                {},
                force=True,
            )

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            updated_draft = artifacts.read_text("draft.md")
            self.assertEqual(updated_draft.count("## Revision Update"), 2)
            self.assertIn("Add the first revision update.", updated_draft)
            self.assertIn("Add the second revision update.", updated_draft)

    def test_revision_rejects_mismatched_run_id_or_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = _seed_ready_run(Path(tmp_dir), run_id="run-mismatch")
            runner = StageRunner(artifacts)
            mismatch = runner.run_stage(
                "revise_bad_run",
                RevisionStage(
                    requested_run_id="other-run",
                    mode="qa_suggest",
                    user_request="Answer a question.",
                ),
                {},
                force=True,
            )
            self.assertEqual(mismatch.status, "failed")
            self.assertIn("run_id_mismatch", mismatch.error or "")

            artifacts.artifact_path("draft.claim_map.json").unlink()
            missing = runner.run_stage(
                "revise_missing_claim_map",
                RevisionStage(
                    requested_run_id="run-mismatch",
                    mode="qa_suggest",
                    user_request="Answer a question.",
                ),
                {},
                force=True,
            )
            self.assertEqual(missing.status, "failed")
            self.assertIn("claim_map_missing", missing.error or "")


def _seed_ready_run(root: Path, *, run_id: str) -> RunArtifacts:
    artifacts = RunArtifacts(root, run_id=run_id)
    runner = StageRunner(artifacts)
    _seed_selection_inputs(artifacts, run_id=run_id)
    selection = runner.run_stage(
        "selection",
        CandidateSelectionStage(requested_run_id=run_id, candidate_id="cand-pass"),
        {"selected_candidate.json": ("run_id", "candidate_id", "selected_at", "source_paths")},
        force=True,
    )
    assert selection.status == "success"
    draft = runner.run_stage(
        "draft",
        DraftGenerationStage(),
        {"draft.md": (), "draft.claim_map.json": ("run_id", "candidate_id", "claims", "risk_notes")},
        force=True,
    )
    assert draft.status == "success"
    return artifacts


def _load_single_revision_record(artifacts: RunArtifacts) -> RevisionRecord:
    revisions = sorted(artifacts.artifact_path("revisions").glob("*.json"))
    if len(revisions) != 1:
        raise AssertionError(f"expected exactly one revision record, found {len(revisions)}")
    return RevisionRecord.from_dict(artifacts.read_json(str(revisions[0].relative_to(artifacts.run_dir))))


if __name__ == "__main__":
    unittest.main()
