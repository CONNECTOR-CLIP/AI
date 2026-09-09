# 판정자(step4) 변별력 테스트 — "step3는 통과하지만 의미적으로 명백히 나쁜" 후보를 손으로 만들어
# judge_candidates에 직접 먹인다. 판정자가 각 불량을 낮게 주고 DROP하면 변별력이 있는 것.
#
# 핵심 설계: 불량 후보도 반드시 "실재하는 id를 인용"해야 step3를 통과해 판정자까지 도달한다
# (가짜 id를 쓰면 step3 grounding에서 먼저 잘려 판정자를 못 만난다). 그래서 각 후보는 진짜 id를
# 인용하되, 인용한 근거와 '내용'이 어긋나게 만들어 각 루브릭 축을 하나씩 저격한다.
#
# 합성 논문 풀을 쓰므로 arxiv 다운로드/CoT1 불필요 — 판정자 API 호출(Qwen)만 필요. 사용자 환경에서 실행.
#   python3 test_judge_discrimination.py
#   python3 test_judge_discrimination.py --judge_model openrouter/qwen/qwen-2.5-72b-instruct

import argparse
import os

from dotenv import load_dotenv

from research_agent.future_work.goal_decomposition_validation import GoalDecomposition, Subgoal
from research_agent.future_work.limitation_validation import LimitationCandidate
from research_agent.future_work.cross_comparison_validation import (
    PaperInput, build_evidence_pool, format_cross_comparison_input, CrossComparisonCandidate,
)
from research_agent.future_work.cross_comparison_judge import judge_candidates

load_dotenv()


def get_args():
    p = argparse.ArgumentParser(description="step4 판정자 변별력 테스트")
    p.add_argument("--judge_model", type=str,
                   default=os.environ.get("JUDGE_MODEL", "openrouter/qwen/qwen-2.5-72b-instruct"))
    return p.parse_args()


# ── 합성 논문 풀: 내용을 우리가 통제해서, 불량 후보가 근거와 어긋나게 만들 수 있다 ──
P1 = PaperInput(
    goal_decomposition=GoalDecomposition(
        paper_title="Efficient Comparison-Based Sorting",
        research_problem="Sort n numbers as efficiently as possible.",
        subgoals=[
            Subgoal(subgoal_id="G1", label="in-memory comparison sort",
                    description="Sort data that fits in RAM.", status="achieved",
                    rationale="Presents an O(n log n) merge sort with a correctness proof and benchmarks."),
            Subgoal(subgoal_id="G2", label="external-memory sorting",
                    description="Sort data too large for RAM (disk / I-O).", status="not_achieved",
                    rationale="Assumes all data fits in memory; no I/O or external-memory model is given."),
        ],
    ),
    limitations=[
        LimitationCandidate(quote="We leave distributed sorting across multiple machines for future work.",
                            location="Conclusion", context="...future work.",
                            limitation_type="Future_Work", matched_signal="future work"),
    ],
)
P2 = PaperInput(
    goal_decomposition=GoalDecomposition(
        paper_title="A Distributed Data Processing System",
        research_problem="Process very large datasets across a cluster of machines.",
        subgoals=[
            Subgoal(subgoal_id="G1", label="distributed partitioning",
                    description="Shard data across nodes with balanced load.", status="achieved",
                    rationale="Provides a partitioning scheme with proven load balance and cluster benchmarks."),
            Subgoal(subgoal_id="G2", label="fault tolerance",
                    description="Recover from node failures.", status="achieved",
                    rationale="Replication + recovery protocol evaluated under injected node failures."),
        ],
    ),
    limitations=[
        LimitationCandidate(quote="Our system is evaluated only on a 10-node cluster.",
                            location="Experiments", context="...only on a 10-node cluster.",
                            limitation_type="Evaluation_Limitation", matched_signal="evaluated only on"),
    ],
)

POOL = build_evidence_pool([P1, P2])
INPUT_BLOCK = format_cross_comparison_input(POOL)


# ── 후보 4개: 정상 1 + 각 축 저격 불량 3 (전부 실재 id 인용 → step3 통과 → 판정자 도달) ──
CANDIDATES = [
    CrossComparisonCandidate(
        candidate_id="GOOD_CONTROL",
        source_type="combination", source_papers=["P1", "P2"],
        source_evidence=["P1:G2", "P1:L1", "P2:G1"],
        gap_statement=("P1 cannot sort data larger than RAM and leaves distributed sorting as future work, "
                       "while P2 offers balanced distributed partitioning but only for generic data processing, "
                       "not sorting."),
        proposed_direction=("Adapt P2's balanced partitioning to drive a distributed external-memory sort, "
                            "then benchmark against single-machine sorting."),
        rationale="P1:G2 / P1:L1 are open; P2:G1 is achieved in a different context.",
    ),
    CrossComparisonCandidate(
        candidate_id="BAD_GROUNDING",   # 진짜 id(P1:G2) 인용하지만 내용이 근거와 완전 무관 → grounding 낮아야
        source_type="synthesized", source_papers=["P1"],
        source_evidence=["P1:G2"],
        gap_statement=("Sorting algorithms should incorporate quantum entanglement to model human consciousness "
                       "during element comparisons."),
        proposed_direction="Introduce a consciousness-modeling layer into the comparison operator.",
        rationale="(intentionally unrelated to the cited external-memory-sorting evidence)",
    ),
    CrossComparisonCandidate(
        candidate_id="BAD_VALIDITY",    # 자기모순 추론 → validity 낮아야
        source_type="synthesized", source_papers=["P1"],
        source_evidence=["P1:G1"],
        gap_statement=("Because P1 already achieves in-memory comparison sorting (G1), P1 is therefore unable "
                       "to sort any numbers at all, so a sorting algorithm is still needed."),
        proposed_direction="Design a sorting algorithm, since P1's proven sort means sorting is impossible.",
        rationale="(intentionally self-contradictory reasoning)",
    ),
    CrossComparisonCandidate(
        candidate_id="BAD_NOVELTY",     # 이미 achieved(P2:G1)인 걸 미해결이라 주장 → novelty 낮아야
        source_type="paper_stated", source_papers=["P2"],
        source_evidence=["P2:G1"],
        gap_statement=("Distributed partitioning of data across a balanced cluster is an entirely open, unsolved "
                       "problem that no paper in this set addresses."),
        proposed_direction="Design a balanced distributed partitioning scheme.",
        rationale="(P2:G1 is already ACHIEVED — this falsely claims it is unsolved)",
    ),
]

# 후보별 기대: (설명, 낮아야 하는 축)  — GOOD은 axis=None
INTENT = {
    "GOOD_CONTROL": ("세 축 모두 높음 → PASS 되어야", None),
    "BAD_GROUNDING": ("grounding 낮음 → DROP 되어야", "grounding"),
    "BAD_VALIDITY": ("validity 낮음 → DROP 되어야", "validity"),
    "BAD_NOVELTY": ("novelty 낮음 → DROP 되어야", "novelty"),
}


def main():
    args = get_args()
    print("=" * 70)
    print(f"판정자 변별력 테스트 — judge: {args.judge_model}")
    print("=" * 70)

    # [주의] 판정자 개편(분해+함의) 이후 grounding은 evidence_pool의 인용 텍스트가 있어야 판정된다.
    # 이 하네스는 옛 1~5 판정자용이라 pool 없이 CANDIDATES/INPUT_BLOCK만 넘긴다 — 새 판정자에선 grounding이
    # 전부 UNSURE로 나와 변별이 안 된다. 제대로 쓰려면 CANDIDATES의 인용 id에 맞는 evidence_pool을 만들어
    # judge_candidates(..., evidence_pool=pool)로 넘겨야 한다. (TODO: pool 기반 재설계)
    passed, log = judge_candidates(CANDIDATES, INPUT_BLOCK, model=args.judge_model)

    print("\n[판정 로그]")
    for l in log:
        print("  -", l)

    passed_ids = {c.candidate_id for c in passed}
    print("\n[후보별 결과 vs 기대]")
    all_ok = True
    for c in CANDIDATES:
        desc, axis = INTENT[c.candidate_id]
        verdict = "PASS" if c.candidate_id in passed_ids else "DROP"
        # 성공 판정: GOOD은 PASS, 불량은 DROP(=판정자가 걸러냄)
        ok = (verdict == "PASS") if axis is None else (verdict == "DROP")
        all_ok = all_ok and ok
        axis_note = f" [{axis}={c.judge_verdict.get(axis)}]" if (axis and c.judge_verdict) else ""
        print(f"  {c.candidate_id:14} verdict={c.judge_verdict} → {verdict}{axis_note}"
              f"   [{'OK' if ok else '미변별!'}]   ({desc})")

    print("\n" + "=" * 70)
    if all_ok:
        print("결론: 판정자가 정상/불량을 제대로 변별함 ✅  (불량 3개 모두 걸러지고 정상은 통과)")
    else:
        print("결론: 일부 불량을 못 걸러냄 ⚠️  → 루브릭 anchor 강화 / threshold 상향 검토 필요")
    print("=" * 70)


if __name__ == "__main__":
    main()
