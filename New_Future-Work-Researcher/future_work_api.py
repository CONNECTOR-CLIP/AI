import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from flask import Flask, jsonify, request


BASE_DIR = Path(__file__).resolve().parent
RESULT_MARKER = "[Future Work 최종 결과]"
# CoT3.NO_CANDIDATES_EXIT_CODE와 같은 값. (CoT3를 import하면 무거운 의존성이 함께 로드되므로 값만 맞춘다.)
NO_CANDIDATES_EXIT_CODE = 3
# 파이프라인 전체 제한 시간(초). 초과 시 하위 프로세스를 종료하고 504를 반환한다.
PIPELINE_TIMEOUT_SECONDS = int(os.environ.get("COT_PIPELINE_TIMEOUT", "1800"))

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/gap")
def analyze_gap():
    body = request.get_json(silent=True) or {}
    papers = body.get("papers")

    if not isinstance(papers, list) or len(papers) < 2:
        return jsonify({"error": "papers must contain at least 2 items"}), 400

    titles = []
    paper_ids = []

    for paper in papers:
        if not isinstance(paper, dict):
            return jsonify({"error": "each paper must be an object"}), 400

        title = str(paper.get("title") or "").strip()
        paper_id = str(paper.get("paper_id") or "").strip()

        if not title or not paper_id:
            return jsonify({"error": "paper_id and title are required"}), 400

        titles.append(title)
        paper_ids.append(paper_id.removeprefix("arXiv:").strip())

    with tempfile.TemporaryDirectory(prefix="cot3_") as cache_path:
        # 제목을 argv로 넘기면 '-'로 시작하는 제목이 argparse 옵션으로 해석되므로 JSON 파일로 전달한다.
        papers_file = Path(cache_path) / "papers.json"
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
            cache_path,
        ]

        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # 하위 프로세스가 멈춰도 단일 스레드 서버 전체가 막히지 않도록 제한 시간 후 강제 종료한다.
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
        return jsonify({
            "error": f"CoT pipeline timed out after {PIPELINE_TIMEOUT_SECONDS}s",
            "detail": output[-4000:],
        }), 504

    if return_code == NO_CANDIDATES_EXIT_CODE:
        return jsonify({
            "error": "No validated CoT3 candidates for Future Work generation",
        }), 422

    if return_code != 0:
        return jsonify({
            "error": "CoT pipeline failed",
            "detail": output[-4000:],
        }), 500

    marker_position = output.rfind(RESULT_MARKER)

    if marker_position < 0:
        return jsonify({
            "error": "Future Work result marker not found",
            "detail": output[-4000:],
        }), 500

    result_text = output[marker_position + len(RESULT_MARKER):]
    json_start = result_text.find("{")

    if json_start < 0:
        return jsonify({"error": "Future Work JSON not found"}), 500

    try:
        payload, _ = json.JSONDecoder().raw_decode(result_text[json_start:])
    except json.JSONDecodeError as error:
        return jsonify({
            "error": "Invalid Future Work JSON",
            "detail": str(error),
        }), 500

    return jsonify({
        "gap_content": json.dumps(payload, ensure_ascii=False)
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8001,
        threaded=False,
    )
