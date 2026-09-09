# CoT3(교차비교) end-to-end 단독 테스트 — 다운로드 → CoT1 → CoT2 → CoT3.setup → CoT3.gen1/gen2 →
# CoT3.static → CoT3.recheck → CoT3.judge까지 명령어 한 방으로 잇는다. (CoT4/재탐색 루프는 아직 미배선.)
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
# CoT3 (CoT3.setup + CoT3.gen1/gen2 + CoT3.static)
from research_agent.future_work.cross_comparison_agent import get_cross_comparison_agent
from research_agent.future_work.cross_comparison_validation import (
    PaperInput, build_evidence_pool, format_cross_comparison_input, run_cross_comparison_with_retry,
    CrossComparisonCandidate, GAP_STATUSES,
)
from research_agent.future_work.cross_comparison_judge import judge_candidates
# CoT3 (CoT3.recheck 원문 재대조 — achieved 역량에만 기댄 위험 후보만 검증)
from research_agent.future_work.cross_comparison_source_check import verify_candidates_against_source

load_dotenv()

DEFAULT_PAPERS = [
    "LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation",
    "Inductive Representation Learning on Large Graphs",
]


def get_args():
    parser = argparse.ArgumentParser(description="CoT3(교차비교) end-to-end 단독 테스트")
    parser.add_argument("--papers", type=str, nargs="+", default=DEFAULT_PAPERS,
                        help="논문 제목 2편 이상 (arxiv에서 찾을 수 있는 정확한 제목)")
    parser.add_argument("--model", type=str, default=os.environ.get("COMPLETION_MODEL", "gpt-4o-2024-08-06"),
                        help="생성(CoT1+CoT3 생성)용 모델")
    parser.add_argument("--judge_model", type=str,
                        default=os.environ.get("JUDGE_MODEL", "openrouter/qwen/qwen-2.5-72b-instruct"),
                        help="CoT3.judge 판정자 모델 (Qwen2.5 + Likert)")
    parser.add_argument("--workplace_name", type=str, default="workplace_test")
    parser.add_argument("--cache_path", type=str, default="cache_cross_comparison_test")
    parser.add_argument("--max_retries", type=int, default=2)
    parser.add_argument("--inject-canary", action="store_true",
                        help="judge 직전에 대조군(음성 2 + 양성 2) 카나리를 섞어 게이트 변별력을 시험한다")
    parser.add_argument("--canary-repeat", type=int, default=1,
                        help="판정자가 stochastic이므로 동일 후보·카나리 위에서 judge만 N회 반복해 "
                             "catch율(음성)/survive율(양성)로 집계한다 (--inject-canary 필요, 기본 1)")
    return parser.parse_args()


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def build_canaries(pool):
    """카나리 배터리 — 정답을 우리가 미리 아는 대조군 후보를 pool에서 파생한다. judge 직전에만 섞어
    판정자/게이트의 변별력을 양방향으로 시험한다(정적층은 통과시키지 않는다).

    두 극성:
      - 음성(negative): 명백한 오답 → 특정 축이 ≤2로 '잡혀야' 한다. 게이트가 나쁜 걸 거르는지 시험.
      - 양성(positive): 정당한 후보(어휘가 안 겹쳐도) → min 점수 ≥3으로 '살아야' 한다. 게이트가
        좋은 걸 잘못 죽이지(과조임) 않는지 시험. 음성만 있으면 게이트를 과하게 조여도 못 알아챈다.

    반환: [(CrossComparisonCandidate, spec), ...]
      spec(음성) = {"polarity": "negative", "axis": <≤2여야 하는 축>, "reason": ...}
      spec(양성) = {"polarity": "positive", "reason": ...}
    논문셋/순서가 바뀌어도 동작하도록 하드코딩 대신 pool의 실재 id를 골라 만든다."""
    specs = []

    # pool에서 achieved subgoal 1개, open(=partial/not_achieved) gap들을 미리 수집.
    achieved = None
    open_gaps = []  # [(pk, gid, label), ...]
    for pk, p in pool.items():
        for gid, sg in p["subgoals"].items():
            if sg.status in GAP_STATUSES:
                open_gaps.append((pk, gid, sg.label))
            elif achieved is None:
                achieved = (pk, gid, sg.label)

    # (구 음성 CANARY_NOV[novelty]는 제거됨 — novelty는 CoT3 판정자에서 빠지고 CoT4로 이관되어 여기서 검증 대상 아님.)

    # ── 음성: grounding FAIL 이어야 함 — 실재 id를 인용하되 그 내용이 전혀 뒷받침하지 않는 무관한 주제.
    #    첫 논문은 주제가 겹칠 수 있어(예: LLM-judge 논문) 마지막 논문에서 인용해 topical halo를 줄인다.
    keys = list(pool.keys())
    if keys:
        gnd_pk = keys[-1]
        gnd_sub = pool[gnd_pk]["subgoals"]
        if gnd_sub:
            gid0 = next(iter(gnd_sub))
            specs.append((
                CrossComparisonCandidate(
                    candidate_id="CANARY_GND",
                    source_type="synthesized",
                    source_papers=[gnd_pk],
                    source_evidence=[f"{gnd_pk}:{gid0}"],
                    gap_statement=(
                        "Large language model judges systematically overrate responses written entirely "
                        "in emoji, a scoring bias no existing benchmark measures."
                    ),
                    proposed_direction=(
                        "Build an emoji-only response benchmark to quantify this LLM-judge scoring bias."
                    ),
                    rationale="[NEGATIVE CONTROL] Cites a real id whose content is unrelated to the claim — a correct judge must give grounding=1.",
                ),
                {"polarity": "negative", "axis": "grounding", "reason": f"{gnd_pk}:{gid0} 내용과 무관한 주제 인용"},
            ))

    # ── 양성 1(강): 실재 open gap을 확장하는 정당한 unstated 후보 — 루브릭상 cite된 coverage-gap에
    #    연결된 unstated gap은 grounding=5여야 한다. reference-aware 게이트가 "verbatim이 아니다"라고
    #    이런 후보를 죽이지 않는지 시험. 통과(min≥3)해야 정상.
    if open_gaps:
        pk, gid, label = open_gaps[0]
        specs.append((
            CrossComparisonCandidate(
                candidate_id="CANARY_POS_GAP",
                source_type="synthesized",
                source_papers=[pk],
                source_evidence=[f"{pk}:{gid}"],
                gap_statement=(
                    f"The paper only partially establishes {label}; a systematic and complete treatment "
                    f"of it is left unaddressed and remains an open direction."
                ),
                proposed_direction=(
                    f"Extend the paper's partial result on {label} into a full method and evaluate it "
                    f"under the same setting."
                ),
                rationale="[POSITIVE CONTROL] Legitimate unstated gap traced to a real coverage gap — must survive (grounding high).",
            ),
            {"polarity": "positive", "reason": f"실재 open gap {pk}:{gid} 의 정당한 확장(=살아야 함)"},
        ))

    # ── 양성 2(과조임 스트레스): 서로 다른 두 논문의 open gap을 엮는 combination 후보 — 어휘 교집합이
    #    자연히 낮다(C8류). 게이트가 어휘 불일치만으로 이런 valid 결합을 죽이지 않는지 시험. min≥3이면 정상.
    distinct = []
    seen_p = set()
    for pk, gid, label in open_gaps:
        if pk not in seen_p:
            seen_p.add(pk)
            distinct.append((pk, gid, label))
        if len(distinct) == 2:
            break
    if len(distinct) == 2:
        (pk1, gid1, label1), (pk2, gid2, label2) = distinct
        specs.append((
            CrossComparisonCandidate(
                candidate_id="CANARY_POS_COMBO",
                source_type="combination",
                source_papers=[pk1, pk2],
                source_evidence=[f"{pk1}:{gid1}", f"{pk2}:{gid2}"],
                gap_statement=(
                    f"No work connects these: the open problem of {label1} in {pk1} may be informed by "
                    f"the techniques underlying {label2} in {pk2}, yet this link is unexplored."
                ),
                proposed_direction=(
                    f"Investigate whether methods addressing {label2} ({pk2}) can be adapted to make "
                    f"progress on {label1} ({pk1})."
                ),
                rationale="[POSITIVE CONTROL] Valid cross-paper combination with low lexical overlap — must survive (over-flag stress test).",
            ),
            {"polarity": "positive", "reason": f"{pk1}:{gid1} × {pk2}:{gid2} 정당한 결합(어휘 안 겹침, 살아야 함)"},
        ))

    return specs


def _canary_ok(cand, exp):
    """이번 판정에서 카나리가 기대대로 나왔는지 — 음성=해당 축이 'FAIL'로 잡힘, 양성=어느 축도 FAIL이
    아니라 살아남음. 판정 자체를 못 받았으면(judge_verdict None) 실패로 본다."""
    v = cand.judge_verdict
    if not v:
        return False
    if exp["polarity"] == "negative":
        return v.get(exp["axis"]) == "FAIL"
    return v.get("grounding") != "FAIL" and v.get("validity") != "FAIL"


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
    # 성공한 논문만 제목→경로로 매핑한다. 다운로드 실패(비-gzip/추출실패/HTTP오류)한 논문은 리포트에
    # 'downloaded to path' 줄이 없으므로 자연히 제외된다. (negative lookahead로 각 논문 블록 안에서만
    # 매칭해 다음 논문 경로로 새지 않게 한다.) — positional 인덱싱은 중간 논문이 빠지면 제목/경로가
    # 어긋나므로 쓰지 않는다.
    path_by_title = dict(re.findall(
        r"Download paper '([^']+)' successfully(?:(?!Download paper ').)*?"
        r"The paper is downloaded to path:\s*(\S+\.tex)",
        download_res, re.DOTALL,
    ))
    for t in args.papers:
        if t not in path_by_title:
            print(f"[SKIP] '{t}': 다운로드 실패로 pool에서 제외")
    if len(path_by_title) < 2:
        raise RuntimeError(
            f"논문을 2편 이상 다운로드하지 못했습니다 (성공 {len(path_by_title)}편):\n{download_res}"
        )

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
                return i, None, None, f"[SKIP] P{i+1} CoT1 실패 — {err}"

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
            # paper_text는 CoT3.recheck 원문 재대조에서 위험 후보 검증용으로 재사용된다.
            return i, PaperInput(goal_decomposition=gd, limitations=lims), paper_text, log
        except Exception as e:
            return i, None, None, f"[SKIP] P{i+1} 예외 — {type(e).__name__}: {e}"

    # 성공한 논문만 CoT1+CoT2에 투입한다. 원래 인덱스 i를 보존해 P번호/로그/캐시태그가 일관되게 한다.
    # (실패 논문은 위에서 이미 제외 로그를 찍었다.)
    tasks = [
        process_paper(i, title, path_by_title[title])
        for i, title in enumerate(args.papers)
        if title in path_by_title
    ]

    # 논문 간 동시 실행. 한 편이 실패해도 (worker가 예외를 잡아 로그로 반환하므로) 나머지는 계속된다.
    results = await asyncio.gather(*tasks)

    # 원래 논문 순서를 보존해서 조립. paper_inputs와 paper_texts_ordered는 같은 순서를 유지해야
    # build_evidence_pool이 부여하는 P1,P2,... 키와 원문 매핑이 일치한다.
    paper_inputs = []
    paper_texts_ordered = []
    for i, paper_input, paper_text, log in sorted(results, key=lambda r: r[0]):
        print(log)
        if paper_input is not None:
            paper_inputs.append(paper_input)
            paper_texts_ordered.append(paper_text)

    if len(paper_inputs) < 2:
        raise RuntimeError(f"교차비교에 쓸 유효 논문이 {len(paper_inputs)}편뿐입니다(최소 2편 필요).")

    # CoT3는 CoT1의 논문별 컨텍스트에 의존하지 않으므로 새 컨텍스트로 시작한다.
    context_variables = {}

    # [CoT3.setup] evidence_pool + 입력 블록
    pool = build_evidence_pool(paper_inputs)
    input_block = format_cross_comparison_input(pool)
    banner("[CoT3.setup] 생성 에이전트 입력 블록")
    print(input_block)

    # [CoT3.gen1+gen2 생성 + CoT3.static 정적검증]
    cc_agent = get_cross_comparison_agent(model=args.model)
    cc_module = AgentModule(cc_agent, client, args.cache_path)
    validated, warnings, context_variables, err = await run_cross_comparison_with_retry(
        cc_module, pool, context_variables, max_retries=args.max_retries,
    )

    banner("[CoT3.static] 정적검증 드롭/경고 로그")
    for w in warnings:
        print("  -", w)

    if err:
        print(f"\n[생성 실패, 재시도 소진] {err}")
        return

    banner(f"[CoT3.static 통과] {len(validated)}개 → CoT3.recheck 원문 재대조로")
    print(f"후보 id: {[c.candidate_id for c in validated]}")
    if not validated:
        print("CoT3.static 통과 후보가 없어 이후 단계를 건너뜁니다.")
        return

    # [CoT3.recheck 원문 재대조] achieved 역량에만 기댄 '주장된 한계' 위험 후보만 원문에 되대조.
    # pool 키(P1,P2,...) 순서에 맞춰 원문 매핑을 만든다(paper_texts_ordered는 paper_inputs와 동순서).
    paper_texts = {f"P{idx}": txt for idx, txt in enumerate(paper_texts_ordered, start=1)}
    banner(f"[CoT3.recheck 원문 재대조] {args.judge_model}")
    verified, source_log = verify_candidates_against_source(
        validated, pool, paper_texts, model=args.judge_model,
    )
    for l in source_log:
        print("  -", l)
    if not verified:
        print("CoT3.recheck 통과 후보가 없어 CoT3.judge를 건너뜁니다.")
        return

    # [CANARY 주입] 대조군 — 정답을 우리가 아는 후보(음성=잡혀야, 양성=살아야)를 judge 직전에 섞는다.
    # static/recheck는 건너뛴다(그건 judge가 아니라 정적층을 시험하게 됨). 게이트 변별력을 양방향으로 시험.
    canary_specs = build_canaries(pool) if args.inject_canary else []
    if canary_specs:
        n_neg = sum(1 for _, e in canary_specs if e["polarity"] == "negative")
        n_pos = len(canary_specs) - n_neg
        banner(f"[CANARY] 대조 후보 {len(canary_specs)}개 주입 (음성 {n_neg} + 양성 {n_pos})")
        for cand, exp in canary_specs:
            if exp["polarity"] == "negative":
                print(f"  - {cand.candidate_id} [음성]: 기대 {exp['axis']}<=2로 잡힘 ({exp['reason']})")
            else:
                print(f"  - {cand.candidate_id} [양성]: 기대 통과 min>=3 ({exp['reason']})")
            print(f"      cite={cand.source_evidence} gap={cand.gap_statement[:90]}")
        verified = verified + [c for c, _ in canary_specs]

    # [CoT3.judge 판정자] 판정자는 stochastic이라 실행마다 점수가 흔들린다. --canary-repeat N 이면
    # 동일 후보·카나리 위에서 judge만 N회 반복해 catch율(음성)/survive율(양성)로 집계한다
    # (1회 pass/fail는 대표성이 없다). 생성·static·recheck는 이미 끝났으니 judge만 재호출한다.
    repeat = max(1, args.canary_repeat) if canary_specs else 1

    if repeat == 1:
        # [단일 실행] 종전과 동일 — 상세 judge 로그 + 카나리 1회 판정.
        banner(f"[CoT3.judge 판정자] {args.judge_model} ({len(verified)}개)")
        passed, judge_log = judge_candidates(verified, input_block, pool, model=args.judge_model)
        for l in judge_log:
            print("  -", l)

        if canary_specs:
            banner("[CANARY 판정 결과] 음성=잡힘? / 양성=살아남음?")
            neg_total = neg_missed = pos_total = pos_dropped = 0
            for cand, exp in canary_specs:
                v = cand.judge_verdict
                ok = _canary_ok(cand, exp)
                if exp["polarity"] == "negative":
                    neg_total += 1
                    if not ok:
                        neg_missed += 1
                    tag = "CAUGHT ✅" if ok else ("⚠️ UNJUDGED" if v is None else "MISSED ❌")
                    print(f"  - {cand.candidate_id} [음성]: {tag} — verdict={v}, 기대 {exp['axis']}=FAIL ({exp['reason']})")
                else:
                    pos_total += 1
                    if not ok:
                        pos_dropped += 1
                    tag = "SURVIVED ✅" if ok else ("⚠️ UNJUDGED" if v is None else "WRONGLY-DROPPED ❌")
                    print(f"  - {cand.candidate_id} [양성]: {tag} — verdict={v}, 기대 grounding·validity≠FAIL ({exp['reason']})")

            lines = []
            if neg_missed == 0 and pos_dropped == 0:
                lines.append("[CANARY 결론] 게이트 신뢰 가능 — 음성 전부 잡고 양성 전부 살림 (단, 1회는 대표성 낮음)")
            else:
                if neg_missed:
                    lines.append(f"[CANARY 결론] 게이트 무름 — 음성 {neg_missed}/{neg_total}개 놓침"
                                 "(=나쁜 후보 통과 / 문제 B 미봉). 통과 후보를 그대로 신뢰하지 말 것.")
                if pos_dropped:
                    lines.append(f"[CANARY 결론] 게이트 과조임 — 양성 {pos_dropped}/{pos_total}개 잘못 드롭"
                                 "(=좋은 후보 죽임). combination/unstated 후보가 유실되는 중.")
            banner("\n".join(lines))
    else:
        # [반복 측정] judge를 N회 재호출해 카나리별 catch/survive '율'을 집계. before/after 비교의 정직한 근거.
        banner(f"[CoT3.judge 반복 측정] {args.judge_model} — judge {repeat}회 (동일 후보·카나리, 판정자 변동성)")
        tally = {c.candidate_id: [] for c, _ in canary_specs}  # cid -> [bool, ...] (기대대로였는지)
        passed = None
        for r in range(repeat):
            passed, _judge_log = judge_candidates(verified, input_block, pool, model=args.judge_model)
            parts = []
            for cand, exp in canary_specs:
                ok = _canary_ok(cand, exp)
                tally[cand.candidate_id].append(ok)
                v = cand.judge_verdict
                sc = tuple(v.values()) if v else "unjudged"
                parts.append(f"{cand.candidate_id}={'O' if ok else 'X'}{sc}")
            print(f"  run {r+1}/{repeat}: " + "  ".join(parts))

        banner("[CANARY 집계] 음성=catch율 / 양성=survive율 (기대: 전부 N/N)")
        neg_stable = pos_stable = True
        for cand, exp in canary_specs:
            good = sum(1 for x in tally[cand.candidate_id] if x)
            if exp["polarity"] == "negative":
                if good < repeat:
                    neg_stable = False
                print(f"  - {cand.candidate_id} [음성]: caught {good}/{repeat}  ({exp['reason']})")
            else:
                if good < repeat:
                    pos_stable = False
                print(f"  - {cand.candidate_id} [양성]: survived {good}/{repeat}  ({exp['reason']})")
        if neg_stable and pos_stable:
            banner(f"[CANARY 결론] {repeat}회 전부 통과 — 게이트 안정적(음성 항상 잡고 양성 항상 살림)")
        else:
            banner("[CANARY 결론] 불안정 — 실행마다 판정이 흔들림. 음성 catch율<100%=게이트가 운에 의존(B 미봉), "
                   "양성 survive율<100%=과조임. 이 비율을 before/after 비교의 기준으로 삼을 것.")

    # [CoT3 최종 산출물] — 판정 통과(+미채점 유지) 후보. 카나리는 제외하고 진짜 후보만.
    canary_ids = {c.candidate_id for c, _ in canary_specs}
    real_passed = [c for c in passed if c.candidate_id not in canary_ids]
    banner(f"[CoT3 최종] {len(real_passed)}개 (→ CoT4로)")
    print(json.dumps([c.model_dump(exclude_none=True) for c in real_passed], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
