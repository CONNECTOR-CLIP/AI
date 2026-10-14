import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request


BASE_DIR = Path(__file__).resolve().parent
RESULT_MARKER = "[Future Work 최종 결과]"
# CoT3.NO_CANDIDATES_EXIT_CODE와 같은 값. (CoT3를 import하면 무거운 의존성이 함께 로드되므로 값만 맞춘다.)
NO_CANDIDATES_EXIT_CODE = 3
# 파이프라인 전체 제한 시간(초). 초과 시 하위 프로세스를 종료하고 504를 반환한다.
PIPELINE_TIMEOUT_SECONDS = int(os.environ.get("COT_PIPELINE_TIMEOUT", "1800"))
# 끝난 작업을 메모리에 보관하는 시간(초)
JOB_RETENTION_SECONDS = 60 * 60
# 진행 패널에 표시하는 단계 순서. CoT3.emit()의 stage 값과 같다.
STAGES = ["download", "CoT1", "CoT2", "CoT3", "FutureWork", "CoT4", "CoT5"]

# CoT3는 workplace_future_work/ 아래 같은 작업 폴더를 쓰므로 파이프라인은 한 번에 하나만 실행한다.
PIPELINE_LOCK = threading.Lock()
JOBS = {}
JOBS_LOCK = threading.Lock()

app = Flask(__name__)


def parse_papers(body):
    """요청 본문에서 (제목 목록, arXiv ID 목록)을 꺼낸다. 형식 오류면 (None, 오류 메시지)."""
    papers = body.get("papers")

    if not isinstance(papers, list) or len(papers) < 2:
        return None, "papers must contain at least 2 items"

    titles = []
    paper_ids = []

    for paper in papers:
        if not isinstance(paper, dict):
            return None, "each paper must be an object"

        title = str(paper.get("title") or "").strip()
        paper_id = str(paper.get("paper_id") or "").strip()

        if not title or not paper_id:
            return None, "paper_id and title are required"

        titles.append(title)
        paper_ids.append(paper_id.removeprefix("arXiv:").strip())

    return (titles, paper_ids), None


def run_pipeline(titles, paper_ids, work_dir, progress_file=None):
    """CoT3.py(CoT1 → CoT5)를 하위 프로세스로 실행하고 결과를 분류해 돌려준다.

    반환: {"kind": "completed" | "no_candidates" | "timeout" | "failed", "payload"?, "error"?, "detail"?}
    """
    # 제목을 argv로 넘기면 '-'로 시작하는 제목이 argparse 옵션으로 해석되므로 JSON 파일로 전달한다.
    papers_file = Path(work_dir) / "papers.json"
    papers_file.write_text(
        json.dumps({"papers": titles, "paper_ids": paper_ids}, ensure_ascii=False),
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "-u",
        str(BASE_DIR / "CoT3.py"),
        "--papers_file",
        str(papers_file),
        "--cache_path",
        str(work_dir),
    ]
    if progress_file:
        command += ["--progress_file", str(progress_file)]

    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 하위 프로세스가 멈춰도 서버가 계속 붙잡혀 있지 않도록 제한 시간 후 강제 종료한다.
    timed_out = threading.Event()

    def kill_on_timeout():
        timed_out.set()
        process.kill()

    timer = threading.Timer(PIPELINE_TIMEOUT_SECONDS, kill_on_timeout)
    timer.start()

    output_lines = []

    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            output_lines.append(line)
        return_code = process.wait()
    finally:
        timer.cancel()

    output = "".join(output_lines)

    if timed_out.is_set():
        return {
            "kind": "timeout",
            "error": f"CoT pipeline timed out after {PIPELINE_TIMEOUT_SECONDS}s",
            "detail": output[-4000:],
        }

    if return_code == NO_CANDIDATES_EXIT_CODE:
        return {"kind": "no_candidates", "error": "No validated CoT3 candidates for Future Work generation"}

    if return_code != 0:
        return {"kind": "failed", "error": "CoT pipeline failed", "detail": output[-4000:]}

    marker_position = output.rfind(RESULT_MARKER)

    if marker_position < 0:
        return {"kind": "failed", "error": "Future Work result marker not found", "detail": output[-4000:]}

    result_text = output[marker_position + len(RESULT_MARKER):]
    json_start = result_text.find("{")

    if json_start < 0:
        return {"kind": "failed", "error": "Future Work JSON not found"}

    try:
        payload, _ = json.JSONDecoder().raw_decode(result_text[json_start:])
    except json.JSONDecodeError as error:
        return {"kind": "failed", "error": "Invalid Future Work JSON", "detail": str(error)}

    return {"kind": "completed", "payload": payload}


def read_events(progress_file):
    if not progress_file or not Path(progress_file).exists():
        return []
    events = []
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # 하위 프로세스가 쓰는 중인 마지막 줄일 수 있으므로 건너뛴다.
                continue
    return events


def fold_stages(events, job_status):
    """진행 이벤트를 단계별 현재 상태로 접는다. 같은 단계의 이벤트는 마지막 것이 현재 상태다."""
    stages = {
        name: {"stage": name, "status": "pending", "started_at": None, "finished_at": None, "data": {}}
        for name in STAGES
    }
    for event in events:
        stage = stages.get(event.get("stage"))
        if stage is None:
            continue
        status = event.get("status")
        if stage["started_at"] is None:
            stage["started_at"] = event.get("time")
        if status in ("done", "skipped"):
            stage["finished_at"] = event.get("time")
        stage["status"] = status
        stage["data"] = event.get("data") or {}

    # 파이프라인이 실패/시간 초과로 끝났다면 진행 중이던 단계를 실패로 표시한다.
    if job_status in ("failed", "timeout"):
        for stage in stages.values():
            if stage["status"] == "running":
                stage["status"] = "failed"
    return [stages[name] for name in STAGES]


def run_job(job_id, titles, paper_ids):
    with PIPELINE_LOCK:
        with tempfile.TemporaryDirectory(prefix="cot3_") as work_dir:
            progress_file = Path(work_dir) / "progress.jsonl"
            with JOBS_LOCK:
                job = JOBS[job_id]
                job["status"] = "running"
                job["started_at"] = time.time()
                job["progress_file"] = str(progress_file)
            try:
                outcome = run_pipeline(titles, paper_ids, work_dir, progress_file)
            except Exception as exc:
                outcome = {"kind": "failed", "error": f"{type(exc).__name__}: {exc}"}
            # 작업 폴더가 지워지기 전에 이벤트를 메모리로 옮긴다.
            events = read_events(progress_file)

    with JOBS_LOCK:
        job = JOBS[job_id]
        job["status"] = outcome["kind"]
        job["finished_at"] = time.time()
        job["events"] = events
        job["progress_file"] = None
        job["error"] = outcome.get("error")
        if outcome["kind"] == "completed":
            job["gap_content"] = json.dumps(outcome["payload"], ensure_ascii=False)


def prune_jobs():
    now = time.time()
    with JOBS_LOCK:
        for job_id in [
            jid for jid, job in JOBS.items()
            if job.get("finished_at") and now - job["finished_at"] > JOB_RETENTION_SECONDS
        ]:
            del JOBS[job_id]


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/gap")
def analyze_gap():
    """동기 실행: 파이프라인이 끝날 때까지 기다렸다가 결과를 반환한다."""
    parsed, error = parse_papers(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    titles, paper_ids = parsed

    with PIPELINE_LOCK:
        with tempfile.TemporaryDirectory(prefix="cot3_") as work_dir:
            outcome = run_pipeline(titles, paper_ids, work_dir)

    status_codes = {"timeout": 504, "no_candidates": 422, "failed": 500}
    if outcome["kind"] != "completed":
        body = {"error": outcome["error"]}
        if outcome.get("detail"):
            body["detail"] = outcome["detail"]
        return jsonify(body), status_codes[outcome["kind"]]

    return jsonify({
        "gap_content": json.dumps(outcome["payload"], ensure_ascii=False)
    })


@app.post("/api/gap/jobs")
def start_gap_job():
    """비동기 실행: 작업을 시작하고 job_id를 바로 반환한다. 진행 상황은 GET /api/gap/jobs/<job_id>로 조회."""
    parsed, error = parse_papers(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    titles, paper_ids = parsed

    prune_jobs()
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            # 다른 분석이 실행 중이면 끝날 때까지 queued 상태로 기다린다.
            "status": "queued",
            "papers": titles,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "progress_file": None,
            "events": [],
            "error": None,
            "gap_content": None,
        }
    threading.Thread(target=run_job, args=(job_id, titles, paper_ids), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "queued"}), 202


@app.get("/api/gap/jobs/<job_id>")
def get_gap_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404
        job = dict(job)

    events = read_events(job["progress_file"]) if job["progress_file"] else job["events"]
    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "papers": job["papers"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "stages": fold_stages(events, job["status"]),
        "error": job["error"],
        "gap_content": job["gap_content"],
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8001,
        # 진행 상황 조회가 실행 중인 분석에 막히지 않도록 요청별 스레드를 쓴다.
        # 파이프라인 자체는 PIPELINE_LOCK으로 한 번에 하나만 실행된다.
        threaded=True,
    )
