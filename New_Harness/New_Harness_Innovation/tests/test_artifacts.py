from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from new_harness.artifacts import RunArtifacts


class RunArtifactsTests(unittest.TestCase):
    def test_event_logging_writes_jsonl_with_run_and_stage_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")

            artifacts.append_event(
                "stage_completed",
                stage="stage_a",
                status="success",
                metadata={"skipped": False},
            )

            lines = artifacts.events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["event_type"], "stage_completed")
            self.assertEqual(event["run_id"], "run-123")
            self.assertEqual(event["stage"], "stage_a")
            self.assertEqual(event["status"], "success")
            self.assertEqual(event["metadata"], {"skipped": False})
            self.assertIn("timestamp_ns", event)

    def test_write_json_persists_schema_version_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")

            path = artifacts.write_json("config.json", {"name": "demo", "schema_version": 99})

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["name"], "demo")


if __name__ == "__main__":
    unittest.main()
