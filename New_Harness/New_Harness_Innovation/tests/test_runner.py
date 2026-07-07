from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from new_harness.artifacts import RunArtifacts
from new_harness.runner import StageResult, StageRunner, WorkerContext


class RecordingStage:
    def __init__(self, result: StageResult | None = None, *, writes_invalid: bool = False) -> None:
        self.calls = 0
        self.contexts: list[WorkerContext] = []
        self.result = result or StageResult(
            status="success",
            artifacts=("outputs/result.json",),
            metadata={"producer": "recording-stage"},
        )
        self.writes_invalid = writes_invalid

    def run(self, context: WorkerContext) -> StageResult:
        self.calls += 1
        self.contexts.append(context)
        if self.writes_invalid:
            output_path = context.artifacts.artifact_path("outputs/result.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("{\"partial\": true}\n", encoding="utf-8")
        return self.result


class ExplodingStage:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, context: WorkerContext) -> StageResult:
        self.calls += 1
        context.artifacts.artifact_path("outputs/result.json").parent.mkdir(parents=True, exist_ok=True)
        context.artifacts.artifact_path("outputs/result.json").write_text(
            json.dumps({"partial": True}) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("boom")


class StageRunnerTests(unittest.TestCase):
    def test_skips_only_when_existing_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")
            artifacts.write_json("outputs/result.json", {"value": 7})
            runner = StageRunner(artifacts)
            stage = RecordingStage()

            result = runner.run_stage(
                "demo_stage",
                stage,
                {"outputs/result.json": ("value",)},
            )

            self.assertEqual(stage.calls, 0)
            self.assertEqual(result.status, "success")
            self.assertTrue(result.metadata["skipped"])
            event = json.loads(artifacts.events_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["event_type"], "stage_skipped")
            self.assertEqual(event["stage"], "demo_stage")
            self.assertEqual(event["status"], "success")

    def test_invalid_or_missing_output_reruns_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")
            artifacts.write_json("outputs/result.json", {"wrong": 7})
            runner = StageRunner(artifacts)
            stage = RecordingStage()

            result = runner.run_stage(
                "demo_stage",
                stage,
                {"outputs/result.json": ("value",)},
            )

            self.assertEqual(stage.calls, 1)
            self.assertFalse(result.metadata.get("skipped", False))
            self.assertEqual(stage.contexts[0].run_id, "run-123")
            self.assertEqual(stage.contexts[0].stage_name, "demo_stage")
            lines = artifacts.events_path.read_text(encoding="utf-8").splitlines()
            invalidated = json.loads(lines[0])
            started = json.loads(lines[1])
            completed = json.loads(lines[2])
            self.assertEqual(invalidated["event_type"], "stage_invalidated")
            self.assertEqual(started["event_type"], "stage_started")
            self.assertEqual(completed["event_type"], "stage_completed")

    def test_exception_preserves_partial_outputs_and_returns_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")
            runner = StageRunner(artifacts)
            stage = ExplodingStage()

            result = runner.run_stage(
                "demo_stage",
                stage,
                {"outputs/result.json": ("value",)},
            )

            self.assertEqual(stage.calls, 1)
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.error, "boom")
            preserved_dir = artifacts.run_dir / result.metadata["preserved_partials_dir"]
            self.assertTrue((preserved_dir / "outputs/result.json").exists())
            marker = json.loads((preserved_dir / "error.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["schema_version"], 1)
            self.assertEqual(marker["stage_name"], "demo_stage")
            failed_event = json.loads(artifacts.events_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(failed_event["event_type"], "stage_failed")
            self.assertEqual(failed_event["status"], "failed")

    def test_force_true_reruns_even_when_output_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = RunArtifacts(Path(tmp_dir), run_id="run-123")
            artifacts.write_json("outputs/result.json", {"value": 7})
            runner = StageRunner(artifacts)
            stage = RecordingStage()

            runner.run_stage(
                "demo_stage",
                stage,
                {"outputs/result.json": ("value",)},
                force=True,
            )

            self.assertEqual(stage.calls, 1)


if __name__ == "__main__":
    unittest.main()
