"""HTTP API: 후보 목록 조회, 생성 작업 시작, 진행 상태 조회, 결과 조회.

    python -m uvicorn research_plan.api:app --port 8002

전체 실행이 몇 분 걸리므로 요청 하나로 기다리게 하지 않는다. POST로 작업을 만들고 GET으로 상태를 확인한다.
형식은 docs/api.md에 있다.

실행 모드(환경변수 RESEARCH_PLAN_API_MODE)
- mock(기본): LLM을 부르지 않고 단계만 흉내 낸다. 비용이 없고 결과는 examples/demo에서 읽는다.
- live: 실제 파이프라인을 돌린다. API 키 비용이 들고 결과는 out에서 읽는다.

작업은 한 번에 하나씩 돌린다. 작업 기록은 메모리에만 있어 서버를 다시 켜면 사라진다(결과 파일은 남는다).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .inputs import RUN_MANIFEST, InputError, Run, load_run
from .pipeline import MANIFEST, STAGES, run_pipeline
from .provider import load_dotenv
from .verify import DOCS

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/api/research-plan"
MODES = ("mock", "live")
DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:5173"
MOCK_STAGE_SECONDS = 1.0

log = logging.getLogger("research_plan.api")

# (실행 폴더, 후보 번호, 출력 루트, NOT_NOVEL 허용, 단계 알림) → 종료 코드
Runner = Callable[[Path, int, Path, bool, Callable[[str], None]], int]


class JobRequest(BaseModel):
    force: bool = False  # 결과가 이미 있어도 다시 생성한다. live에서는 비용이 다시 든다.
    allow_not_novel: bool = False


def _error(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _live_runner(run_dir: Path, idea: int, out: Path, allow_not_novel: bool, on_stage) -> int:
    return run_pipeline(run_dir, idea, out=out, allow_not_novel=allow_not_novel, on_stage=on_stage,
                        argv=["api", "--run-dir", run_dir.name, "--idea", str(idea)])


def _mock_runner(delay: float) -> Runner:
    def run(run_dir: Path, idea: int, out: Path, allow_not_novel: bool, on_stage) -> int:
        for stage in STAGES:
            on_stage(stage)
            time.sleep(delay)
        return 1 if _has_docs(out / run_dir.name / f"idea{idea:02d}") else 2
    return run


def _has_docs(folder: Path) -> bool:
    return all((folder / name).is_file() for name in DOCS)


def create_app(*, data_dir: Path = ROOT / "data", out_dir: Path = ROOT / "out",
               demo_dir: Path = ROOT / "examples" / "demo", mode: str | None = None,
               runner: Runner | None = None, origins: str | None = None) -> FastAPI:
    mode = mode or os.getenv("RESEARCH_PLAN_API_MODE", "mock")
    if mode not in MODES:
        raise ValueError(f"RESEARCH_PLAN_API_MODE는 {MODES} 중 하나여야 함: {mode}")
    results_dir = out_dir if mode == "live" else demo_dir
    runner = runner or (_live_runner if mode == "live" else _mock_runner(MOCK_STAGE_SECONDS))

    app = FastAPI(title="Research Plan API", description="연구계획서와 논문의 틀을 생성합니다.", version="0.1.0")
    # 작업 시작이 비용을 쓰므로 모든 출처를 열지 않는다.
    allowed = (origins if origins is not None else os.getenv("RESEARCH_PLAN_CORS_ORIGINS", DEFAULT_ORIGINS))
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in allowed.split(",") if o.strip()],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    jobs: dict[str, dict] = {}
    lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=1)

    def run_dirs() -> dict[str, Path]:
        found = {}
        for path in sorted(data_dir.iterdir()) if data_dir.is_dir() else []:
            if (path / RUN_MANIFEST).is_file():
                found[_read_json(path / RUN_MANIFEST).get("run_id", path.name)] = path
        return found

    def get_run(run_id: str) -> Run:
        path = run_dirs().get(run_id)
        if path is None:
            raise _error(404, "RUN_NOT_FOUND", f"실행을 찾을 수 없음: {run_id}")
        try:
            return load_run(path)
        except InputError as exc:
            raise _error(500, "RUN_INVALID", str(exc))

    def get_candidate(run: Run, idea: int):
        try:
            return run.candidate(idea)
        except InputError as exc:
            raise _error(404, "IDEA_NOT_FOUND", str(exc))

    def folder_of(run_id: str, idea: int) -> Path:
        return results_dir / run_id / f"idea{idea:02d}"

    def active_job(run_id: str, idea: int) -> dict | None:
        return next((j for j in jobs.values() if j["run_id"] == run_id and j["idea"] == idea
                     and j["status"] in ("queued", "running")), None)

    def public(job: dict) -> dict:
        return {k: v for k, v in job.items() if not k.startswith("_")}

    def execute(job: dict, run_root: Path) -> None:
        def on_stage(stage: str) -> None:
            with lock:
                if job["current_stage"]:
                    job["completed_stages"].append(job["current_stage"])
                job["current_stage"] = stage

        with lock:
            job["status"] = "running"
            job["started_at"] = _now()
        try:
            code = runner(run_root, job["idea"], results_dir, job["_allow_not_novel"], on_stage)
        except Exception:
            log.exception("작업 %s 실패", job["job_id"])
            code = 2
        folder = folder_of(job["run_id"], job["idea"])
        manifest = _read_json(folder / MANIFEST) if code != 2 else {}
        with lock:
            job["finished_at"] = _now()
            job["result_ready"] = code != 2 and _has_docs(folder)
            if job["result_ready"]:
                job["status"] = "done"
                job["final_status"] = manifest.get("final_status")
                job["total_cost_usd"] = manifest.get("total_cost_usd") if mode == "live" else 0
                if job["current_stage"]:
                    job["completed_stages"].append(job["current_stage"])
                job["current_stage"] = None
            else:
                # 원인에 경로나 키 관련 내용이 섞일 수 있어 응답에는 단계만 알리고 자세한 내용은 서버 로그에 남긴다.
                job["status"] = "failed"
                job["error"] = {"code": "JOB_FAILED", "message": f"{job['current_stage']} 단계에서 실패함. 서버 로그를 확인할 것"}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "mode": mode}

    @app.get(f"{PREFIX}/runs")
    def list_runs() -> dict:
        return {"runs": [{"run_id": run_id} for run_id in run_dirs()]}

    @app.get(f"{PREFIX}/runs/{{run_id}}/candidates")
    def list_candidates(run_id: str) -> dict:
        run = get_run(run_id)
        return {"run_id": run.run_id, "candidates": [
            {"idea": c.index, "title": c.title, "classification": c.classification, "cot3_candidate_id": c.cot3_id,
             "warnings": c.warnings, "has_result": _has_docs(folder_of(run.run_id, c.index))}
            for c in run.candidates
        ]}

    @app.post(f"{PREFIX}/runs/{{run_id}}/candidates/{{idea}}/jobs", status_code=202)
    def create_job(run_id: str, idea: int, body: JobRequest | None = None) -> dict:
        body = body or JobRequest()
        run = get_run(run_id)
        candidate = get_candidate(run, idea)
        if candidate.classification != "NOVEL" and not body.allow_not_novel:
            raise _error(422, "NOT_NOVEL", f"CoT5 판정이 {candidate.classification or '없음'}인 후보임. 진행하려면 allow_not_novel을 켤 것")
        if mode == "live":
            load_dotenv(ROOT / ".env")
            if not os.getenv("OPENROUTER_API_KEY"):
                raise _error(503, "NO_API_KEY", "서버에 OPENROUTER_API_KEY가 설정되어 있지 않음")
        with lock:
            active = active_job(run.run_id, idea)
            if active:
                raise _error(409, "JOB_ALREADY_RUNNING", "이 후보의 작업이 이미 진행 중임", job_id=active["job_id"])
            if _has_docs(folder_of(run.run_id, idea)) and not body.force:
                raise _error(409, "RESULT_EXISTS", "결과가 이미 있음. 다시 생성하려면 force를 켤 것")
            job = {
                "job_id": uuid.uuid4().hex, "run_id": run.run_id, "idea": idea, "status": "queued",
                "stages": STAGES, "current_stage": None, "completed_stages": [], "created_at": _now(),
                "started_at": None, "finished_at": None, "result_ready": False, "final_status": None,
                "total_cost_usd": None, "error": None, "_allow_not_novel": body.allow_not_novel,
            }
            jobs[job["job_id"]] = job
            snapshot = public(job)
        executor.submit(execute, job, run.root)
        return snapshot

    @app.get(f"{PREFIX}/jobs/{{job_id}}")
    def get_job(job_id: str) -> dict:
        with lock:
            job = jobs.get(job_id)
            if job is None:
                raise _error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없음. 서버를 다시 켰다면 기록이 사라졌을 수 있음")
            return json.loads(json.dumps(public(job)))

    @app.get(f"{PREFIX}/runs/{{run_id}}/candidates/{{idea}}/result")
    def get_result(run_id: str, idea: int) -> dict:
        run = get_run(run_id)
        get_candidate(run, idea)
        with lock:
            active = active_job(run.run_id, idea)
        if active:
            raise _error(409, "JOB_RUNNING", "작업이 진행 중임. 끝난 뒤 다시 요청할 것", job_id=active["job_id"])
        folder = folder_of(run.run_id, idea)
        if not _has_docs(folder):
            raise _error(404, "RESULT_NOT_FOUND", "이 후보의 결과가 아직 없음")
        manifest = _read_json(folder / MANIFEST)
        report = _read_json(folder / "verify_report.json")
        return {
            "run_id": run.run_id,
            "idea": idea,
            "source": "live" if mode == "live" else "demo",
            "final_status": manifest.get("final_status"),
            "finished_at": manifest.get("finished_at"),
            "total_cost_usd": manifest.get("total_cost_usd"),
            "stages": [{"stage": s.get("stage"), "status": s.get("status"), "seconds": s.get("seconds"),
                        "cost_usd": s.get("cost_usd")} for s in manifest.get("stages", [])],
            "verify": {"status": report.get("status"), "errors": report.get("errors", []),
                       "warnings": report.get("warnings", []), "citation_count": len(report.get("citations", []))},
            "research_plan_md": (folder / "research_plan.md").read_text(encoding="utf-8"),
            "paper_skeleton_md": (folder / "paper_skeleton.md").read_text(encoding="utf-8"),
        }

    return app


app = create_app()
