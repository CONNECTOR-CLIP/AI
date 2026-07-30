# 2단계(한계/언급 추출) 단독 테스트 — 논문 1편을 넣어서 실제로 어떤 후보가 나오는지 확인용.
# 1단계와 달리 LLM을 호출하지 않는다 — 순수 정규식 기반 정적 추출이므로 API 비용이 발생하지 않는다.
#
# 실행 예:
#   python3 test_limitation_extraction.py --paper "Validation of Modern JSON Schema: Formalization and Complexity"

import argparse
import json
import os
import re

from research_agent.inno.tools.arxiv_source import download_arxiv_source_by_title
from research_agent.inno.workflow.flowcache import ToolModule
from research_agent.future_work.limitation_extraction import extract_limitation_candidates
from research_agent.future_work.limitation_validation import validate_limitation_extraction


def get_args():
    parser = argparse.ArgumentParser(description="2단계(한계/언급 추출) 단독 테스트")
    parser.add_argument("--paper", type=str, required=True, help="논문 제목 (arxiv에서 찾을 수 있는 정확한 제목)")
    parser.add_argument("--workplace_name", type=str, default="workplace_test")
    parser.add_argument("--cache_path", type=str, default="cache_limitation_extraction_test")
    return parser.parse_args()


def main():
    args = get_args()

    local_root = os.path.join(os.getcwd(), "workplace_future_work")
    os.makedirs(local_root, exist_ok=True)

    # [1] 논문 다운로드 — 기존 arxiv_source.py 그대로 재사용 (1단계와 동일한 .tex 파일을 공유)
    download_paper = ToolModule(download_arxiv_source_by_title, args.cache_path)
    download_res = download_paper({
        "paper_list": [args.paper],
        "local_root": local_root,
        "workplace_name": args.workplace_name,
    })
    paper_paths = re.findall(r'The paper is downloaded to path:\s*(\S+\.tex)', download_res)
    if not paper_paths:
        raise RuntimeError(f"논문을 다운로드하지 못했습니다:\n{download_res}")

    # download_arxiv_source가 반환하는 path는 "/workplace_name/papers/xxx.tex" 형태의 상대 경로다
    rel_path = paper_paths[0].lstrip("/\\")
    abs_path = os.path.join(local_root, rel_path)
    print(f"[다운로드 완료] {abs_path}\n")

    with open(abs_path, "r", encoding="utf-8") as f:
        paper_text = f.read()

    # [2] 추출 (LLM 없음, 순수 정규식)
    raw_candidates = extract_limitation_candidates(paper_text)
    print(f"[추출] {len(raw_candidates)}개 원시 후보\n")

    # [3] 정적 검증 (grounding 방어 확인 + 중복 제거)
    validated, warnings = validate_limitation_extraction(raw_candidates, paper_text)

    if warnings:
        print("[경고/드롭 로그]")
        for w in warnings:
            print(f"  - {w}")
        print()

    print(f"[최종 통과] {len(validated)}개 grounded limitation candidate")
    print(json.dumps([c.model_dump() for c in validated], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
