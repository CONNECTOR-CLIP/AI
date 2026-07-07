from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliSmokeTests(unittest.TestCase):
    def test_cli_run_returns_parseable_json_failure_on_bad_input(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            bad_input = tmp_root / "bad-input.json"
            bad_input.write_text('{"selected_papers": "not-a-list"}\n', encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "new_harness.cli",
                    "run",
                    "--input",
                    str(bad_input),
                    "--run-id",
                    "cli-bad-input",
                    "--run-root",
                    str(tmp_root),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["status"], "failed")
            self.assertIsInstance(payload["error"], str)
            self.assertIn("selected_papers must be a list", payload["error"])
            self.assertEqual(payload["run_id"], "cli-bad-input")

    def test_cli_run_returns_parseable_json_when_openrouter_key_missing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fixture = repo_root / "tests/fixtures/selected_papers_arxiv.json"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            env = dict(os.environ)
            env.pop("OPENROUTER_API_KEY", None)
            env.pop("OPENROUTER_MODEL", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "new_harness.cli",
                    "run",
                    "--input",
                    str(fixture),
                    "--run-id",
                    "cli-missing-openrouter-key",
                    "--run-root",
                    str(tmp_root),
                    "--provider",
                    "openrouter",
                    "--env-file",
                    str(tmp_root / "missing.env"),
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["metadata"]["reason"], "provider_configuration_error")
            self.assertIn("OPENROUTER_API_KEY is required", payload["error"])

    def test_cli_run_rejects_web_external_checker_without_url(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fixture = repo_root / "tests/fixtures/selected_papers_arxiv.json"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "new_harness.cli",
                    "run",
                    "--input",
                    str(fixture),
                    "--run-id",
                    "cli-web-missing-url",
                    "--run-root",
                    str(tmp_root),
                    "--verification-depth",
                    "strong_external",
                    "--external-checker",
                    "web",
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["metadata"]["reason"], "external_checker_configuration_error")
            self.assertIn("--external-search-url is required", payload["error"])

    def test_cli_run_select_draft_revise_happy_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        fixture = repo_root / "tests/fixtures/selected_papers_arxiv.json"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            run_id = "cli-smoke"

            run_payload = self._run_cli(
                repo_root,
                "run",
                "--input",
                str(fixture),
                "--run-id",
                run_id,
                "--run-root",
                str(tmp_root),
            )
            self.assertEqual(run_payload["status"], "selection_required")
            self.assertTrue((tmp_root / "runs" / run_id / "candidate_loop.json").exists())
            self.assertTrue((tmp_root / "runs" / run_id / "selection_options.json").exists())
            self.assertTrue((tmp_root / "runs" / run_id / "selection_options.md").exists())

            loop_payload = json.loads((tmp_root / "runs" / run_id / "candidate_loop.json").read_text(encoding="utf-8"))
            selection_options = json.loads((tmp_root / "runs" / run_id / "selection_options.json").read_text(encoding="utf-8"))
            selection_markdown = (tmp_root / "runs" / run_id / "selection_options.md").read_text(encoding="utf-8")
            self.assertEqual(selection_options["run_id"], run_id)
            self.assertEqual(selection_options["status"], "selection_required")
            self.assertEqual(selection_options["pass_candidate_ids"], loop_payload["pass_candidate_ids"])
            self.assertIn(f"select --run-id {run_id} --candidate-id", selection_markdown)
            candidate_id = loop_payload["pass_candidate_ids"][0]

            select_payload = self._run_cli(
                repo_root,
                "select",
                "--run-id",
                run_id,
                "--candidate-id",
                candidate_id,
                "--run-root",
                str(tmp_root),
            )
            self.assertEqual(select_payload["status"], "success")

            draft_payload = self._run_cli(
                repo_root,
                "draft",
                "--run-id",
                run_id,
                "--run-root",
                str(tmp_root),
            )
            self.assertEqual(draft_payload["status"], "success")
            draft_path = tmp_root / "runs" / run_id / "draft.md"
            self.assertTrue(draft_path.exists())

            qa_payload = self._run_cli(
                repo_root,
                "revise",
                "--run-id",
                run_id,
                "--mode",
                "qa_suggest",
                "--request",
                "What should I change in the conclusion?",
                "--run-root",
                str(tmp_root),
            )
            self.assertEqual(qa_payload["status"], "success")
            draft_after_qa = draft_path.read_text(encoding="utf-8")
            self.assertNotIn("## Revision Update", draft_after_qa)

            edit_payload = self._run_cli(
                repo_root,
                "revise",
                "--run-id",
                run_id,
                "--mode",
                "auto_edit",
                "--request",
                "Add a revision update for the conclusion.",
                "--run-root",
                str(tmp_root),
            )
            self.assertEqual(edit_payload["status"], "success")
            self.assertIn("draft.md", edit_payload["metadata"]["files_changed"])
            self.assertIn("## Revision Update", draft_path.read_text(encoding="utf-8"))

            revisions = sorted((tmp_root / "runs" / run_id / "revisions").glob("*.json"))
            self.assertEqual(len(revisions), 2)

    def _run_cli(self, repo_root: Path, *args: str) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-m", "new_harness.cli", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"CLI command failed with exit {completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
        output = completed.stdout.strip()
        try:
            return json.loads(output.splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:  # pragma: no cover - test failure path
            raise AssertionError(f"unable to parse CLI output: {completed.stdout!r}") from exc


if __name__ == "__main__":
    unittest.main()
