from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from new_harness.artifacts import RunArtifacts
from new_harness.runner import StageRunner
from new_harness.stages.ingest import IngestStage


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "selected_papers_arxiv.json"


class IngestStageTests(unittest.TestCase):
    def test_ingest_normalizes_selected_papers_from_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-ingest")
            runner = StageRunner(artifacts)

            result = runner.run_stage(
                "ingest",
                IngestStage(FIXTURE_PATH),
                {"selected_papers.normalized.json": ("selected_papers",)},
            )

            self.assertEqual(result.status, "success")
            payload = artifacts.read_json("selected_papers.normalized.json")
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(len(payload["selected_papers"]), 5)
            self.assertEqual(payload["selected_papers"][0]["paper_id"], "2401.14196")
            self.assertEqual(
                payload["selected_papers"][0]["abs_url"],
                "https://arxiv.org/abs/2401.14196",
            )
            self.assertEqual(
                payload["selected_papers"][-1]["paper_id"],
                "cs/9901001",
            )

    def test_ingest_persists_optional_user_draft_without_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-draft")
            runner = StageRunner(artifacts)
            payload = {
                "selected_papers": [{"source": "https://arxiv.org/abs/2401.14196"}],
                "user_draft": {
                    "draft_text": "Draft body only.",
                    "memo_text": "Memo only.",
                },
            }

            result = runner.run_stage(
                "ingest",
                IngestStage(payload),
                {
                    "selected_papers.normalized.json": ("selected_papers",),
                    "user_draft.json": ("draft_text",),
                },
            )

            self.assertEqual(result.status, "success")
            draft_payload = artifacts.read_json("user_draft.json")
            self.assertEqual(draft_payload["schema_version"], 1)
            self.assertEqual(draft_payload["draft_text"], "Draft body only.")
            self.assertEqual(draft_payload["memo_text"], "Memo only.")
            self.assertNotIn("pdf_path", draft_payload)
            self.assertTrue(result.metadata["user_draft_persisted"])
