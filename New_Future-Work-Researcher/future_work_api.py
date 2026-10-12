import json
import subprocess
import sys
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request


BASE_DIR = Path(__file__).resolve().parent
RESULT_MARKER = "[Future Work 최종 결과]"

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
        command = [
            sys.executable,
            "-u",
            str(BASE_DIR / "CoT3.py"),
            "--papers",
            *titles,
            "--paper_ids",
            *paper_ids,
            "--cache_path",
            cache_path,
        ]

        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines = []

        for line in process.stdout:
            print(line, end="", flush=True)
            output_lines.append(line)

        return_code = process.wait()
        output = "".join(output_lines)

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
