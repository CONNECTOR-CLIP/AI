from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from new_harness.artifacts import RunArtifacts
from new_harness.llm import FakeLLMProvider
from new_harness.runner import StageRunner
from new_harness.stages.evidence import EvidenceStage
from new_harness.stages.ingest import IngestStage


class EvidenceStageTests(unittest.TestCase):
    def test_evidence_stage_creates_one_card_per_selected_paper_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-evidence")
            runner = StageRunner(artifacts)

            ingest_payload = {
                "selected_papers": [
                    {
                        "source": "2401.14196",
                        "title": "Benchmarking agent systems",
                    },
                    {
                        "source": "cs/9901001",
                        "title": "Legacy reasoning methods",
                    },
                ]
            }
            runner.run_stage(
                "ingest",
                IngestStage(ingest_payload),
                {"selected_papers.normalized.json": ("selected_papers",)},
            )

            normalized = artifacts.read_json("selected_papers.normalized.json")
            normalized["selected_papers"][0]["abstract"] = (
                "This paper introduces a benchmark method and evaluation pipeline. "
                "Results show strong accuracy improvements. Future work explores scaling."
            )
            normalized["selected_papers"][1]["abstract"] = (
                "The approach uses a symbolic algorithm, but the method has limitations. "
                "Experiments report baseline scores."
            )
            artifacts.write_json("selected_papers.normalized.json", normalized)

            evidence_stage = EvidenceStage(FakeLLMProvider())
            outputs = {
                "evidence_cards/2401.14196.json": ("paper_id", "claims", "confidence"),
                "evidence_cards/cs__9901001.json": ("paper_id", "claims", "confidence"),
                "evidence_cards/index.json": ("cards", "card_count"),
            }
            result = runner.run_stage("evidence", evidence_stage, outputs)

            self.assertEqual(result.status, "success")
            first_card = artifacts.read_json("evidence_cards/2401.14196.json")
            second_card = artifacts.read_json("evidence_cards/cs__9901001.json")
            index_payload = artifacts.read_json("evidence_cards/index.json")

            self.assertEqual(first_card["schema_version"], 1)
            self.assertEqual(first_card["paper_id"], "2401.14196")
            self.assertTrue(first_card["claims"])
            self.assertTrue(first_card["methods"])
            self.assertTrue(first_card["quotes_or_snippets"])
            self.assertEqual(second_card["paper_id"], "cs/9901001")
            self.assertEqual(index_payload["card_count"], 2)
            self.assertEqual(len(index_payload["cards"]), 2)
            self.assertEqual(index_payload["cards"][0]["card_path"], "evidence_cards/2401.14196.json")

            events = [json.loads(line) for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()]
            event_types = [event["event_type"] for event in events]
            self.assertIn("stage_started", event_types)
            self.assertIn("stage_completed", event_types)
            self.assertEqual(len([event for event in events if event["event_type"] == "worker_started"]), 2)
            self.assertEqual(len([event for event in events if event["event_type"] == "worker_completed"]), 2)

    def test_evidence_stage_skips_on_rerun_when_existing_artifacts_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-skip")
            runner = StageRunner(artifacts)

            runner.run_stage(
                "ingest",
                IngestStage(
                    {
                        "selected_papers": [
                            {
                                "source": "2401.14196",
                                "title": "One paper",
                            }
                        ]
                    }
                ),
                {"selected_papers.normalized.json": ("selected_papers",)},
            )
            normalized = artifacts.read_json("selected_papers.normalized.json")
            normalized["selected_papers"][0]["abstract"] = "A method with evaluation results."
            artifacts.write_json("selected_papers.normalized.json", normalized)

            stage = EvidenceStage(FakeLLMProvider())
            outputs = {
                "evidence_cards/2401.14196.json": ("paper_id", "claims", "confidence"),
                "evidence_cards/index.json": ("cards", "card_count"),
            }
            first = runner.run_stage("evidence", stage, outputs)
            second = runner.run_stage("evidence", stage, outputs)

            self.assertEqual(first.status, "success")
            self.assertEqual(second.status, "success")
            self.assertTrue(second.metadata["skipped"])

            events = [json.loads(line) for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()]
            skipped_events = [event for event in events if event["event_type"] == "stage_skipped" and event["stage"] == "evidence"]
            self.assertEqual(len(skipped_events), 1)
