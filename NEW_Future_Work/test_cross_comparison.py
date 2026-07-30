# 3단계(교차비교) end-to-end 단독 테스트 — 다운로드 → CoT1 → CoT2 → Step0 → CoT3 생성 → step3 정적검증까지
# 명령어 한 방으로 잇는다. (step4 판정자/CoT4/재탐색 루프는 아직 미배선 — 이 스크립트 범위 밖.)
#
# CoT3은 여러 논문을 교차비교하는 단계이므로 최소 2편이 필요하다. 각 논문은:
#   - CoT1(goal_decomposition): 원문을 읽는 LLM 에이전트 + 정적검증 재시도
#   - CoT2(limitation_extraction): 원문 .tex에 대한 순수 정규식 추출 + 정적검증 (LLM 없음)
# 을 거쳐 PaperInput으로 묶이고, 그걸 build_evidence_pool → format → 생성 에이전트에 투입한다.
#
# 실행 예:
#   python test_cross_comparison.py \
#     --papers "LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation" \
#              "Inductive Representation Learning on Large Graphs"
#
# 주의: 실제 LLM API(CoT1 + CoT3)를 호출하므로 비용이 발생하고, arxiv에서 논문을 다운로드하므로 네트워크가 필요하다.

import argparse
import asyncio
import json
import os
import re

from dotenv import load_dotenv

from research_agent.inno.core import MetaChain
from research_agent.inno.workflow.flowcache import AgentModule, ToolModule
from research_agent.inno.tools.arxiv_source import download_arxiv_source_by_title
from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser

# CoT1
from research_agent.future_work.goal_decomposition_agent import get_goal_decomposition_agent
from research_agent.future_work.goal_decomposition_validation import run_goal_decomposition_with_retry
# CoT2
from research_agent.future_work.limitation_extraction import extract_limitation_candidates
from research_agent.future_work.limitation_validation import validate_limitation_extraction
# CoT3 (Step0 + 생성 + step3)
from research_agent.future_work.cross_comparison_agent import get_cross_comparison_agent
from research_agent.future_work.cross_comparison_validation import (
    PaperInput, build_evidence_pool, format_cross_comparison_input, run_cross_comparison_with_retry,
)
from research_agent.future_work.cross_comparison_judge import judge_candidates

load_dotenv()

DEFAULT_PAPERS = [
    "LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation",
    "Inductive Representation Learning on Large Graphs",
]


def get_args():
    parser = argparse.ArgumentParser(description="3단계(교차비교) end-to-end 단독 테스트")
    parser.add_argument("--papers", type=str, nargs="+", default=DEFAULT_PAPERS,
                        help="논문 제목 2편 이상 (arxiv에서 찾을 수 있는 정확한 제목)")
    parser.add_argument("--model", type=str, default=os.environ.get("COMPLETION_MODEL", "gpt-4o-2024-08-06"),
                        help="생성(CoT1+CoT3 생성)용 모델")
    parser.add_argument("--judge_model", type=str,
                        default=os.environ.get("JUDGE_MODEL", "openrouter/qwen/qwen-2.5-72b-instruct"),
                        help="step4 판정자 모델 (Qwen2.5 + Likert)")
    parser.add_argument("--workplace_name", type=str, default="workplace_test")
    parser.add_argument("--cache_path", type=str, default="cache_cross_comparison_test")
    parser.add_argument("--max_retries", type=int, default=2)
    return parser.parse_args()


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


async def main():
    args = get_args()
    if len(args.papers) < 2:
        raise SystemExit("교차비교(CoT3)는 최소 2편이 필요합니다. --papers 에 2편 이상 주세요.")

    local_root = os.path.join(os.getcwd(), "workplace_future_work")
    os.makedirs(local_root, exist_ok=True)

    # 논문별로 독립된 브라우저를 만든다 — 하나의 file_env를 공유하면 논문 A의 open_local_file이
    # 논문 B의 현재 페이지/뷰포트/히스토리를 덮어써서 병렬 실행 시 브라우징 상태가 깨진다.
    def make_file_env():
        return RequestsMarkdownBrowser(
            viewport_size=1024 * 4,
            local_root=local_root,
            workplace_name=args.workplace_name,
            downloads_folder=os.path.join(local_root, args.workplace_name, "downloads"),
        )

    # [다운로드] 여러 논문 한 번에 — 기존 arxiv_source.py 그대로 재사용
    download_paper = ToolModule(download_arxiv_source_by_title, args.cache_path)
    download_res = download_paper({
        "paper_list": args.papers,
        "local_root": local_root,
        "workplace_name": args.workplace_name,
    })
    paper_paths = re.findall(r'The paper is downloaded to path:\s*(\S+\.tex)', download_res)
    if len(paper_paths) < 2:
        raise RuntimeError(f"논문을 2편 이상 다운로드하지 못했습니다:\n{download_res}")

    client = MetaChain()

    # [CoT1 + CoT2] 논문 간 병렬 — 각 논문이 자기만의 file_env·agent·context_variables를 갖고
    # 독립적으로 CoT1(원문 읽는 LLM)+CoT2(정규식)를 수행한다. N편을 asyncio.gather로 동시에 돌린다.
    # (기존에는 for 루프 + await 라 P1이 완전히 끝나야 P2가 시작되는 완전 순차였다.)
    #
    # (주의) AgentModule.check_cache는 대화형 메뉴(single_select_menu)를 띄운다. 캐시가 이미
    #        존재하는 상태로 병렬 실행하면 여러 프롬프트가 동시에 떠 stdin이 엉킨다 —
    #        병렬 실행은 캐시가 비어 있는(신규) --cache_path 로 돌리는 것을 권장한다.
    async def process_paper(i, title, path_hint):
        try:
            banner(f"[CoT1] 목표추론 시작 — P{i+1}: {title}")
            # 논문별 독립 리소스: 자기 전용 브라우저에 바인딩된 agent
            gd_module = AgentModule(
                get_goal_decomposition_agent(model=args.model, file_env=make_file_env()),
                client, args.cache_path, interactive_cache=False,
            )
            gd, _ctx, err = await run_goal_decomposition_with_retry(
                gd_module, title, path_hint, {}, paper_index=i, max_retries=args.max_retries,
            )
            if err:
                return i, None, f"[SKIP] P{i+1} CoT1 실패 — {err}"

            # [CoT2] 원문 .tex 정규식 추출 (LLM 없음, 파일 읽기만 — 논문 간 독립)
            rel_path = path_hint.lstrip("/\\")
            abs_path = os.path.join(local_root, rel_path)
            with open(abs_path, "r", encoding="utf-8") as f:
                paper_text = f.read()
            raw_lims = extract_limitation_candidates(paper_text)
            lims, _lim_warns = validate_limitation_extraction(raw_lims, paper_text)

            log = (
                f"[DONE] P{i+1}: {title}\n"
                f"  subgoals={len(gd.subgoals)} "
                f"(not_achieved={sum(1 for s in gd.subgoals if s.status=='not_achieved')})\n"
                f"  limitations={len(lims)} (raw {len(raw_lims)} → validated {len(lims)})"
            )
            return i, PaperInput(goal_decomposition=gd, limitations=lims), log
        except Exception as e:
            return i, None, f"[SKIP] P{i+1} 예외 — {type(e).__name__}: {e}"

    tasks = [
        process_paper(i, title, paper_paths[i])
        for i, title in enumerate(args.papers)
        if i < len(paper_paths)
    ]
    for i, title in enumerate(args.papers):
        if i >= len(paper_paths):
            print(f"[SKIP] '{title}': 다운로드 경로 없음")

    # 논문 간 동시 실행. 한 편이 실패해도 (worker가 예외를 잡아 로그로 반환하므로) 나머지는 계속된다.
    results = await asyncio.gather(*tasks)

    # 원래 논문 순서를 보존해서 조립
    paper_inputs = []
    for i, paper_input, log in sorted(results, key=lambda r: r[0]):
        print(log)
        if paper_input is not None:
            paper_inputs.append(paper_input)

    if len(paper_inputs) < 2:
        raise RuntimeError(f"교차비교에 쓸 유효 논문이 {len(paper_inputs)}편뿐입니다(최소 2편 필요).")

    # CoT3는 CoT1의 논문별 컨텍스트에 의존하지 않으므로 새 컨텍스트로 시작한다.
    context_variables = {}

    # [Step 0] evidence_pool + 입력 블록
    pool = build_evidence_pool(paper_inputs)
    input_block = format_cross_comparison_input(pool)
    banner("[Step 0-b] 생성 에이전트 입력 블록")
    print(input_block)

    # [CoT3 step1+2 생성 + step3 정적검증]
    cc_agent = get_cross_comparison_agent(model=args.model)
    cc_module = AgentModule(cc_agent, client, args.cache_path)
    validated, warnings, context_variables, err = await run_cross_comparison_with_retry(
        cc_module, pool, context_variables, max_retries=args.max_retries,
    )

    banner("[step3 정적검증] 드롭/경고 로그")
    for w in warnings:
        print("  -", w)

    if err:
        print(f"\n[생성 실패, 재시도 소진] {err}")
        return

    banner(f"[step3 통과] {len(validated)}개 → step4 판정자로")
    print(f"후보 id: {[c.candidate_id for c in validated]}")
    if not validated:
        print("step3 통과 후보가 없어 step4를 건너뜁니다.")
        return

    # [CoT3 step4 판정자] Qwen2.5 + Likert 루브릭 채점
    banner(f"[step4 판정자] {args.judge_model}")
    passed, judge_log = judge_candidates(validated, input_block, model=args.judge_model)
    for l in judge_log:
        print("  -", l)

    # [CoT3 최종 산출물] — 판정 통과(+미채점 유지) 후보. CoT4로 넘어갈 대상.
    banner(f"[CoT3 최종] {len(passed)}개 (→ CoT4로)")
    print(json.dumps([c.model_dump(exclude_none=True) for c in passed], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
