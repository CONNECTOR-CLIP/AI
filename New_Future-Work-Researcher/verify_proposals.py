"""심화 검증: Future Work 제안 중 사용자가 고른 것만 CoT4(실현가능성) → CoT5(신규성)로 검증한다.

기본 분석(CoT3.py)은 Future Work까지만 실행하고, 사용자가 아이디어를 골라 검증을 요청하면
future_work_api.py가 이 스크립트를 하위 프로세스로 실행한다.

  python verify_proposals.py --payload_file proposals.json --progress_file progress.jsonl

payload_file: {"future_work_proposals": [제안, ...]} 형식(Future Work 결과의 제안을 그대로)
출력: RESULT_MARKER 뒤에 {"gate", "CoT4", "CoT5"} JSON. CoT4·CoT5 결과마다 proposal_id가 붙는다.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

# CoT4·CoT5 모듈이 불러올 때 환경변수를 읽을 수 있으므로 import 전에 .env를 먼저 적용한다.
load_dotenv()

from run_cot4_then_cot5 import run_cot4_then_cot5_filtered  # noqa: E402

RESULT_MARKER = "[검증 결과]"


async def verify_with_progress(payload, emit):
    """제안을 CoT4 → CoT5로 검증하면서 단계별 진행 이벤트를 emit(stage, status, **data)로 알린다.

    반환: run_cot4_then_cot5_filtered의 결과 ({"gate", "CoT4", "CoT5", ...})
    """
    emit("CoT4", "running", proposals=len(payload["future_work_proposals"]))

    def on_cot4_done(cot4_results, passed_titles):
        emit("CoT4", "done", results=[
            {
                "proposal_id": r.get("proposal_id"),
                "title": r.get("idea_title"),
                "classification": r.get("classification"),
                "confidence": r.get("confidence"),
                "concerns": {k: bool(v.get("present")) for k, v in (r.get("concerns") or {}).items()},
                "rationale": r.get("rationale") or r.get("error"),
            }
            for r in cot4_results
        ])
        if passed_titles:
            emit("CoT5", "running", ideas=passed_titles)
        else:
            emit("CoT5", "skipped", reason="CoT4를 통과한 제안이 없습니다(모두 실현 불가 또는 오류).")

    downstream = await run_cot4_then_cot5_filtered(payload, on_cot4_done=on_cot4_done)
    if downstream["CoT5"]["status"] == "completed":
        emit("CoT5", "done", results=[
            {
                "proposal_id": r.get("proposal_id"),
                "title": r.get("idea_title"),
                "classification": r.get("classification"),
                "reason": r.get("reason") or r.get("error"),
                "evaluated_paper_count": r.get("evaluated_paper_count"),
            }
            for r in downstream["CoT5"]["results"]
        ])
    return downstream


def make_emitter(progress_file):
    """CoT3.emit과 같은 형식으로 진행 이벤트를 JSON lines로 남기는 함수를 만든다."""
    def emit(stage, status, **data):
        if not progress_file:
            return
        event = {"stage": stage, "status": status, "time": time.time(), "data": data}
        with open(progress_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return emit


async def main():
    parser = argparse.ArgumentParser(description="선택한 Future Work 제안을 CoT4 → CoT5로 검증")
    parser.add_argument("--payload_file", type=Path, required=True,
                        help='{"future_work_proposals": [...]} 형식의 JSON 파일')
    parser.add_argument("--progress_file", type=str,
                        help="단계별 진행 이벤트를 JSON lines로 기록할 파일")
    args = parser.parse_args()

    payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
    downstream = await verify_with_progress(payload, make_emitter(args.progress_file))

    result = {key: downstream[key] for key in ("gate", "CoT4", "CoT5")}
    print(RESULT_MARKER)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
