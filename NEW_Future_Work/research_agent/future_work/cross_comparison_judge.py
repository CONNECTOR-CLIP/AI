# [3단계: 교차비교] step4 판정자 — Qwen2.5-72B + Likert(1~5).
# step3 정적체크(cross_comparison_validation)를 통과한 후보만 받아, "이 공백이 믿을 만한가"를
# 의미론적으로 채점한다. 생성(COMPLETION_MODEL, gpt/gemini/grok)과 판정(JUDGE_MODEL, Qwen2.5)을
# 역할 분리하는 게 핵심 — JuStRank 근거로 Likert가 판단 경계(threshold) 인지에 안정적이라 채택.
#
# 왜 정적체크로 못 잡고 여기서 AI가 필요한가: "이 비교가 논리적으로 타당한가", "이미 세트 내 논문이
# 푼 거 아닌가" 같은 판단은 규칙(정규식/스키마)으로 못 잡는 의미 판단이라서.
#
# ── 루브릭을 고치려면? 이 파일의 RUBRIC 상수와 PASS_THRESHOLD 만 수정하면 된다. (아래 큰 배너 참고)
#    프롬프트/파싱/호출 로직은 그대로 두고 채점 기준만 바꿔 끼울 수 있게 분리해 뒀다.

import json
import time
from typing import List, Optional, Tuple

from litellm import completion
from litellm.exceptions import ServiceUnavailableError

from research_agent.constant import JUDGE_MODEL, API_BASE_URL
from research_agent.future_work.cross_comparison_validation import CrossComparisonCandidate


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  RUBRIC — 여기가 루브릭 본문이다. 논문 조사 후 이 블록만 수정하면 된다.        ║
# ║  각 축은 정수 1~5 Likert. Likert의 핵심은 1과 5의 뜻(양끝 anchor)을 명시해     ║
# ║  판정자가 일관되게 채점하게 하는 것 — anchor 문구를 바꾸면 판정 성향이 바뀐다.  ║
# ╚══════════════════════════════════════════════════════════════════════════╝
RUBRIC = """\
Score EACH dimension as an integer from 1 to 5. The endpoints and midpoint mean:

(1) grounding — Is this gap actually derivable from the paper evidence it cites?
    1 = free-floating speculation, unrelated to the cited subgoals/limitations (hallucination)
    3 = related to the cited evidence, but mixes in interpretation/extrapolation that
        goes somewhat beyond what the evidence directly supports
    5 = follows directly from the cited evidence ids (e.g. P1:G2, P2:L1)

(2) validity — Are the gap statement and the proposed direction logically sound?
    1 = logical leap or contradiction (e.g. claims paper A solves paper B's limitation
        when it does not)
    3 = the solved-vs-unsolved contrast is mostly correct but partly imprecise, or there
        is one weak link in the gap -> direction reasoning
    5 = the solved-vs-unsolved contrast is correct and the gap -> direction link is clear

(3) novelty — Is this gap NOT already solved by one of the papers in THIS set?
    FIRST check the status of EVERY cited subgoal in the profiles above. A subgoal tagged
    "[not_achieved]" or "[partially_achieved]" is OPEN; a subgoal named in an
    "Achieved (cross-ref only)" line (or otherwise marked achieved) is ALREADY SOLVED in the set.
    If the candidate treats an ALREADY-SOLVED (achieved) capability as an open/unsolved gap, that
    directly contradicts the evidence -> novelty = 1 (do NOT give it a middle score).
    1 = already solved in-set: a cited subgoal is achieved in the same context, OR the candidate
        falsely claims an achieved capability is still unsolved -> redundant / factually wrong
    3 = partially addressed by another paper in the set but not fully solved (genuine partial overlap)
    5 = no paper in the set addresses it -> a genuine open gap
"""

# 통과 규칙: 세 축이 모두 이 값 이상이어야 통과. 하나라도 미만이면 드롭. (이 숫자도 루브릭의 일부)
PASS_THRESHOLD = 3

# cause_tag(공백 원인 경량 태그) 허용값 — CS/ML 도메인용으로 각색한 것. 필요 없으면 비워도 됨.
CAUSE_TAGS = ("unexplored", "partially_solved", "combination_missing")
# ── 루브릭 관련 수정은 여기 위까지 ─────────────────────────────────────────────


def _build_judge_prompt(candidate: CrossComparisonCandidate, input_block: str) -> str:
    """공유 컨텍스트(Step0 입력 블록: 논문별 subgoal/limitation/achieved) + 채점할 후보 1개 + 루브릭."""
    return f"""\
You are a strict, calibrated reviewer. You are given the gap profiles of a closed set of papers, then ONE \
proposed research-gap candidate derived from them. Score the candidate against the rubric.

[Paper gap profiles — shared context]
{input_block}

[Candidate to score]
candidate_id: {candidate.candidate_id}
source_type: {candidate.source_type}
source_papers: {candidate.source_papers}
cited_evidence: {candidate.source_evidence}
gap_statement: {candidate.gap_statement}
proposed_direction: {candidate.proposed_direction}

[Rubric]
{RUBRIC}

Return ONLY a JSON object (no markdown, no code fences, no text before or after):
{{"grounding": <1-5>, "validity": <1-5>, "novelty": <1-5>, "cause_tag": "{'|'.join(CAUSE_TAGS)}", "justification": "<one short sentence>"}}
"""


def _call_judge(prompt: str, model: str) -> Optional[str]:
    """판정자 LLM 호출. 503 등 일시 오류는 백오프 재시도(arxiv_novelty_check와 동일 패턴).
    응답 텍스트를 반환하고, API가 끝내 죽으면 None을 반환한다(= 응답 자체를 못 받음).
    None과 '응답은 왔지만 형식 불량'은 상위(_judge_candidate)에서 다르게 처리한다."""
    last_exc = None
    for attempt in range(3):
        try:
            resp = completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                base_url=API_BASE_URL,
            )
            return resp.choices[0].message.content
        except ServiceUnavailableError as e:
            last_exc = e
            time.sleep(10 * (2 ** attempt))  # 10s, 20s, 40s
        except Exception as e:
            # 실제 원인(모델 id/인증/요청 오류 등)을 삼키지 않고 드러낸다 — 안 그러면 전부
            # 'api_unavailable'로 뭉뚱그려져 왜 실패했는지 알 수 없다.
            print(f"[judge] LLM call failed ({type(e).__name__}): {e}")
            return None
    print(f"[judge] LLM call failed after retries: {type(last_exc).__name__}: {last_exc}")
    return None


def _strip_fence(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.strip()
    return text


def _parse_judge_output(raw: Optional[str]) -> Optional[dict]:
    """판정자 출력에서 세 점수(+cause_tag/justification)를 뽑는다. 형식이 깨지거나 점수가
    1~5 범위를 벗어나면 None (상위에서 1회 재시도, 그래도 실패면 DROP)."""
    if not raw:
        return None
    try:
        data = json.loads(_strip_fence(raw))
        g = int(data["grounding"]); v = int(data["validity"]); n = int(data["novelty"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if not all(1 <= x <= 5 for x in (g, v, n)):
        return None
    tag = data.get("cause_tag")
    if tag not in CAUSE_TAGS:
        tag = None
    return {"grounding": g, "validity": v, "novelty": n,
            "cause_tag": tag, "justification": str(data.get("justification", ""))[:200]}


def _judge_candidate(prompt: str, model: str) -> Tuple[str, Optional[dict]]:
    """후보 1개를 채점한다. 형식 불량이면 1회 재시도한 뒤 결과 상태를 구분해 반환한다.

    Returns (status, scores):
      ("ok", {...scores...})     정상 채점됨
      ("api_unavailable", None)  API가 죽어 응답 자체를 못 받음 → 상위에서 KEEP(판정 기회조차 없었음)
      ("unparseable", None)      응답은 왔으나 재시도 후에도 형식 불량 → 상위에서 DROP(판정 기회를 줬는데 실패)
    """
    raw = _call_judge(prompt, model)
    if raw is None:
        return "api_unavailable", None      # 인프라 실패 — 후보 잘못 아님
    scores = _parse_judge_output(raw)
    if scores is not None:
        return "ok", scores

    # 형식 깨짐 → 더 강하게 JSON만 요구하며 1회 재시도(LLM 형식 실수는 재시도로 대부분 복구됨)
    retry_prompt = prompt + (
        "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object — "
        "integer scores 1-5 for grounding/validity/novelty — and nothing else."
    )
    raw2 = _call_judge(retry_prompt, model)
    if raw2 is None:
        return "api_unavailable", None      # 재시도 중 API 죽음 → 공정한 판정 못 준 걸로 봄 → KEEP
    scores = _parse_judge_output(raw2)
    if scores is not None:
        return "ok", scores
    return "unparseable", None              # 두 번 다 형식 불량 → 판정 실패로 확정 → DROP


def judge_candidates(
    candidates: List[CrossComparisonCandidate],
    input_block: str,
    model: str = JUDGE_MODEL,
    pass_threshold: int = PASS_THRESHOLD,
) -> Tuple[List[CrossComparisonCandidate], List[str]]:
    """
    step3를 통과한 후보들을 루브릭으로 채점하고, 임계 미달을 드롭한다.
    통과 후보에는 judge_scores / cause_tag가 채워져 반환된다.

    Args:
        candidates: step3 통과 후보 목록
        input_block: Step0 입력 블록(format_cross_comparison_input 결과) — grounding/novelty 판단용 공유 컨텍스트
    Returns:
        (passed_candidates, log)  — passed는 CoT4로 넘어갈 대상, log는 PASS/DROP/미채점 사유
    """
    passed: List[CrossComparisonCandidate] = []
    log: List[str] = []

    for cand in candidates:
        status, scores = _judge_candidate(_build_judge_prompt(cand, input_block), model)

        if status == "api_unavailable":
            # API가 죽어 판정 기회조차 없었음 → 후보 잘못 아니니 버리지 않고 미채점 통과(CoT4/사람이 재확인).
            cand.judge_scores = None
            cand.cause_tag = None
            log.append(f"[KEEP-UNJUDGED] {cand.candidate_id}: judge API unavailable — kept (never got a fair judgment)")
            passed.append(cand)
            continue

        if status == "unparseable":
            # 판정 기회를 줬는데(재시도 포함) 형식 불량만 냄 → 점수를 확보 못 하므로 DROP.
            log.append(f"[DROP] {cand.candidate_id}: judge produced unparseable output twice — dropped")
            continue

        # status == "ok"
        cand.judge_scores = {"grounding": scores["grounding"], "validity": scores["validity"], "novelty": scores["novelty"]}
        cand.cause_tag = scores["cause_tag"]

        low = min(cand.judge_scores.values())
        if low < pass_threshold:
            log.append(
                f"[DROP] {cand.candidate_id}: {cand.judge_scores} below threshold {pass_threshold} "
                f"— {scores['justification']}"
            )
            continue

        log.append(f"[PASS] {cand.candidate_id}: {cand.judge_scores} tag={cand.cause_tag}")
        passed.append(cand)

    if not passed:
        log.append("[WARN] no candidate passed the judge — check rubric/threshold or generation quality")

    return passed, log
