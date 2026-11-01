import json
import shutil
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    raise unittest.SkipTest("fastapi·httpx가 없어 API 테스트를 건너뜀 (pip install -e .[api,dev])")

from research_plan.api import PREFIX, create_app
from research_plan.pipeline import MANIFEST, STAGES

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "cot45_public_run_20261029_154552"
DEMO_FOLDER = ROOT / "examples" / "demo" / RUN_ID / "idea06"
BASE = f"{PREFIX}/runs/{RUN_ID}/candidates"


def write_docs(out: Path, idea: int, final_status="needs_review") -> None:
    folder = out / RUN_ID / f"idea{idea:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research_plan.md").write_text("# 계획서", encoding="utf-8")
    (folder / "paper_skeleton.md").write_text("# 논문의 틀", encoding="utf-8")
    (folder / MANIFEST).write_text(json.dumps({"final_status": final_status, "total_cost_usd": 0.01}), encoding="utf-8")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"
        self.out.mkdir()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, runner=None, mode="live", **kwargs) -> TestClient:
        def default(run_dir, idea, out, allow_not_novel, on_stage):
            self.calls.append((idea, allow_not_novel))
            for stage in STAGES:
                on_stage(stage)
            write_docs(out, idea)
            return 1

        return TestClient(create_app(mode=mode, out_dir=self.out, demo_dir=self.out, runner=runner or default, **kwargs))

    def wait(self, client, job_id) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"{PREFIX}/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(0.01)
        self.fail("작업이 끝나지 않음")

    def set_key(self):
        patcher = unittest.mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lists_runs_and_candidates(self):
        client = self.client()
        self.assertEqual(client.get(f"{PREFIX}/runs").json()["runs"], [{"run_id": RUN_ID}])
        candidates = client.get(BASE).json()["candidates"]
        self.assertEqual(len(candidates), 8)
        self.assertEqual(candidates[5]["idea"], 6)
        self.assertEqual(candidates[5]["classification"], "NOVEL")
        self.assertFalse(candidates[5]["has_result"])

    def test_unknown_ids_return_404(self):
        client = self.client()
        self.assertEqual(client.get(f"{PREFIX}/runs/없음/candidates").json()["detail"]["code"], "RUN_NOT_FOUND")
        self.assertEqual(client.get(f"{PREFIX}/runs/..%2F..%2Fsrc/candidates").status_code, 404)
        self.assertEqual(client.get(f"{BASE}/99/result").json()["detail"]["code"], "IDEA_NOT_FOUND")
        self.assertEqual(client.get(f"{BASE}/6/result").json()["detail"]["code"], "RESULT_NOT_FOUND")
        self.assertEqual(client.get(f"{PREFIX}/jobs/없음").json()["detail"]["code"], "JOB_NOT_FOUND")

    def test_job_runs_to_result(self):
        self.set_key()
        client = self.client()
        response = client.post(f"{BASE}/6/jobs")
        self.assertEqual(response.status_code, 202)
        job = self.wait(client, response.json()["job_id"])
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["completed_stages"], STAGES)
        self.assertEqual(job["final_status"], "needs_review")
        self.assertTrue(job["result_ready"])
        result = client.get(f"{BASE}/6/result").json()
        self.assertEqual(result["research_plan_md"], "# 계획서")
        self.assertEqual(result["source"], "live")

    def test_existing_result_needs_force(self):
        self.set_key()
        write_docs(self.out, 6)
        client = self.client()
        self.assertEqual(client.post(f"{BASE}/6/jobs").json()["detail"]["code"], "RESULT_EXISTS")
        self.assertEqual(self.calls, [])
        response = client.post(f"{BASE}/6/jobs", json={"force": True})
        self.wait(client, response.json()["job_id"])
        self.assertEqual(self.calls, [(6, False)])

    def test_same_idea_cannot_run_twice_at_once(self):
        self.set_key()
        release = threading.Event()

        def blocking(run_dir, idea, out, allow_not_novel, on_stage):
            on_stage("select")
            release.wait(5)
            write_docs(out, idea)
            return 0

        client = self.client(blocking)
        first = client.post(f"{BASE}/6/jobs").json()
        second = client.post(f"{BASE}/6/jobs")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"]["job_id"], first["job_id"])
        self.assertEqual(client.get(f"{BASE}/6/result").json()["detail"]["code"], "JOB_RUNNING")
        release.set()
        self.assertEqual(self.wait(client, first["job_id"])["status"], "done")

    def test_not_novel_blocked_by_default(self):
        self.set_key()
        client = self.client()
        response = client.post(f"{BASE}/1/jobs")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "NOT_NOVEL")
        self.assertEqual(self.calls, [])
        job = client.post(f"{BASE}/1/jobs", json={"allow_not_novel": True}).json()
        self.wait(client, job["job_id"])
        self.assertEqual(self.calls, [(1, True)])

    def test_live_without_key_refuses_before_running(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=False), \
                unittest.mock.patch("research_plan.api.load_dotenv"):
            import os
            os.environ.pop("OPENROUTER_API_KEY", None)
            client = self.client()
            response = client.post(f"{BASE}/6/jobs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "NO_API_KEY")
        self.assertEqual(self.calls, [])

    def test_failure_hides_exception_text(self):
        self.set_key()

        def broken(run_dir, idea, out, allow_not_novel, on_stage):
            on_stage("extract")
            raise RuntimeError("비밀 경로 C:/secret")

        client = self.client(broken)
        with self.assertLogs("research_plan.api", level="ERROR"):
            job = self.wait(client, client.post(f"{BASE}/6/jobs").json()["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["result_ready"])
        self.assertIn("extract", job["error"]["message"])
        self.assertNotIn("secret", json.dumps(job))

    def test_cors_only_allows_listed_origins(self):
        client = self.client(origins="http://localhost:3000")
        allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")
        blocked = client.get("/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(blocked.headers.get("access-control-allow-origin"))

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            create_app(mode="paid")


class MockModeTests(unittest.TestCase):
    """기본 mock 모드는 LLM을 부르지 않고, 저장소에 든 데모 결과로 전체 흐름을 보여 준다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.demo = Path(self.tmp.name) / "demo"
        shutil.copytree(DEMO_FOLDER, self.demo / RUN_ID / "idea06")

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, client, job_id) -> dict:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = client.get(f"{PREFIX}/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(0.05)
        self.fail("작업이 끝나지 않음")

    def test_mock_serves_demo_and_never_calls_pipeline(self):
        with unittest.mock.patch("research_plan.api.run_pipeline") as pipeline, \
                unittest.mock.patch("research_plan.api.MOCK_STAGE_SECONDS", 0):
            client = TestClient(create_app(mode="mock", demo_dir=self.demo, out_dir=Path(self.tmp.name) / "out"))
            self.assertEqual(client.get("/health").json(), {"status": "ok", "mode": "mock"})
            result = client.get(f"{BASE}/6/result").json()
            self.assertEqual(result["source"], "demo")
            self.assertIn("논문의 틀", result["paper_skeleton_md"])
            job = client.post(f"{BASE}/6/jobs", json={"force": True}).json()
            self.assertEqual(self.wait(client, job["job_id"])["status"], "done")
            other = client.post(f"{BASE}/2/jobs", json={"allow_not_novel": True}).json()
            self.assertEqual(self.wait(client, other["job_id"])["status"], "failed")
        pipeline.assert_not_called()

    def test_demo_has_no_local_paths(self):
        for path in DEMO_FOLDER.iterdir():
            self.assertNotIn("C:/Users", path.read_text(encoding="utf-8").replace("\\\\", "/"), path.name)


class PipelineCallbackTests(unittest.TestCase):
    def test_on_stage_reports_stage(self):
        from research_plan.pipeline import run_pipeline

        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            # 1번은 NOT_NOVEL이라 select에서 멈춘다. LLM을 부르지 않는다.
            code = run_pipeline(ROOT / "data" / RUN_ID, 1, out=Path(tmp), on_stage=seen.append)
        self.assertEqual(code, 2)
        self.assertEqual(seen, ["select"])


if __name__ == "__main__":
    unittest.main()
