# [CoT3.recheck] 교차비교 원문 재대조(source re-check). AI 사용(읽기 검증).
#
# 왜 필요한가: CoT3 생성 에이전트는 "논문이 말하지 않은 한계(unstated)"까지 파내도록 설계됐고,
# 그 중 SCAMPER가 논문이 '해결한 역량(achieved subgoal)'을 물고 만든 후보는 위험하다 —
# 그 한계 주장은 (a) CoT2처럼 원문 verbatim도 아니고 (b) CoT1처럼 not_achieved로 검증된 것도 아닌,
# 모델이 새로 "주장"한 한계라서 환각일 수 있다. 판정자(CoT3.judge)는 압축 프로필만 보므로 원문에만 있는
# 반증을 못 잡는다. 그래서 이 위험 후보에 한해서만 실제 원문을 다시 읽어 "논문이 이미 이 한계를
# 다뤘/배제했는가"를 확인한다 — CoT1이 하던 '원문 대조' 패턴을 소수 후보에만 얇게 재사용.
#
# 비용 원칙: 전체 후보가 아니라 '검증된 앵커가 전혀 없고 achieved subgoal에만 기댄' 후보에만 LLM을
# 호출한다. 나머지(명시 한계·커버리지 공백에 grounding된 후보)는 그대로 통과(source_check=None).
#
# 보수적 판정: 명확히 ADDRESSED(논문이 이미 처리)일 때만 드롭한다. OPEN/UNCLEAR/API실패는 유지 —
# 좋은 후보를 잘못 죽이는 쪽보다 살려서 다음 단계/사람이 재확인하게 하는 편이 안전하다
# (판정자의 api_unavailable→KEEP 철학과 동일).

import json
import time
from typing import Dict, List, Optional, Tuple

from litellm import completion
from litellm.exceptions import ServiceUnavailableError

from research_agent.constant import JUDGE_MODEL, API_BASE_URL
from research_agent.future_work.cross_comparison_validation import CrossComparisonCandidate

# 위험 후보 원문 재대조 시 논문당 넣는 원문 텍스트 상한(문자). .tex 전문이 수십만 자일 수 있어
# 컨텍스트/비용 폭주를 막되, 검증에 쓸 만큼은 준다. 잘리면 프롬프트에 '(truncated)'로 표기.
MAX_SOURCE_CHARS = 30000


def _split_ref(ref: str) -> Tuple[Optional[str], Optional[str]]:
    """'P1:G2' -> ('P1','G2'). 형식이 깨졌으면 (None, None). (CoT3.static를 이미 통과했으므로 정상일 것)"""
    if ":" not in ref:
        return None, None
    pk, local = ref.split(":", 1)
    return pk.strip(), local.strip()


def classify_candidate(candidate: CrossComparisonCandidate, evidence_pool: Dict) -> Tuple[bool, List[Tuple[str, str]]]:
    """후보가 '원문 재대조가 필요한 위험 후보'인지 판별한다.

    위험 = source_evidence에 검증된 앵커(명시 한계 Lx, 또는 not_achieved/partially subgoal)가
           하나도 없고, achieved subgoal id에만 기댄 경우 → 모델이 '주장'한 unstated 한계라
           원문 반증 여지가 있다.

    Returns: (needs_verification, achieved_refs)
      achieved_refs: [(paper_key, subgoal_id), ...] — 이 후보가 물고 있는 achieved subgoal들.
    """
    has_verified_anchor = False
    achieved_refs: List[Tuple[str, str]] = []

    for ref in candidate.source_evidence:
        pk, local = _split_ref(ref)
        if pk is None or pk not in evidence_pool:
            continue  # CoT3.static에서 이미 걸렀어야 함 — 방어적으로 무시
        limitations = evidence_pool[pk]["limitations"]
        subgoals = evidence_pool[pk]["subgoals"]
        if local in limitations:
            has_verified_anchor = True  # 논문이 명시한 한계 = 검증된 앵커
        elif local in subgoals:
            if subgoals[local].status in ("not_achieved", "partially_achieved"):
                has_verified_anchor = True  # CoT1이 미달로 검증한 공백 = 검증된 앵커
            else:
                achieved_refs.append((pk, local))  # achieved 역량 = 주장 기반

    needs = (not has_verified_anchor) and bool(achieved_refs)
    return needs, achieved_refs


def _build_recheck_prompt(
    candidate: CrossComparisonCandidate,
    achieved_refs: List[Tuple[str, str]],
    evidence_pool: Dict,
    paper_texts: Dict[str, str],
) -> str:
    """위험 후보 1개 + 그것이 물고 있는 achieved 역량(들) + 해당 논문 원문(상한 내)으로 재대조 프롬프트를 만든다."""
    blocks = []
    seen_papers = []
    for pk, gid in achieved_refs:
        sg = evidence_pool[pk]["subgoals"].get(gid)
        title = evidence_pool[pk]["title"]
        if sg is not None:
            blocks.append(
                f"[{pk}] {title}\n"
                f"Capability the paper CLAIMS to have achieved ({pk}:{gid}):\n"
                f"  - {sg.label}: {sg.description}\n"
                f"  - why it was judged achieved: {sg.rationale}"
            )
        if pk not in seen_papers:
            seen_papers.append(pk)

    source_blocks = []
    for pk in seen_papers:
        text = paper_texts.get(pk, "")
        truncated = ""
        if len(text) > MAX_SOURCE_CHARS:
            text = text[:MAX_SOURCE_CHARS]
            truncated = " (truncated)"
        source_blocks.append(f"===== Paper text for {pk}{truncated} =====\n{text}")

    return f"""\
You are a strict fact-checker. A research-gap candidate claims a paper has a SPECIFIC UNSTATED \
limitation or missed opportunity — a weakness the paper did NOT explicitly admit, inferred from a \
capability the paper CLAIMS to have achieved. Your ONLY job: using the paper's own text, decide \
whether the paper ALREADY addresses, resolves, or explicitly rules out this claimed limitation. If \
the paper already handles it, the "gap" is not real and must be rejected.

[Achieved capabilities the claim builds on]
{chr(10).join(blocks)}

[Claimed unstated limitation / opportunity]
gap_statement: {candidate.gap_statement}
proposed_direction: {candidate.proposed_direction}

{chr(10).join(source_blocks)}

Decide ONE verdict:
- ADDRESSED — the paper already addresses, resolves, or explicitly rules out this exact limitation, \
so it is NOT an open gap. Point to the sentence/section that shows this.
- OPEN — the paper does NOT address it; it is a genuine unstated limitation/opportunity.
- UNCLEAR — the provided text is insufficient or ambiguous to decide.

Return ONLY a JSON object (no markdown, no code fences, no text before or after):
{{"verdict": "ADDRESSED|OPEN|UNCLEAR", "evidence": "<one short sentence or quote justifying it>"}}
"""


def _call_llm(prompt: str, model: str) -> Optional[str]:
    """재대조 LLM 호출. 503류는 백오프 재시도, API가 끝내 죽으면 None(응답 자체를 못 받음).
    (cross_comparison_judge._call_judge와 동일 패턴 — 파일 간 결합 대신 지역 복제, 코드베이스 관행)."""
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
            time.sleep(10 * (2 ** attempt))
        except Exception as e:
            print(f"[CoT3.recheck] LLM call failed ({type(e).__name__}): {e}")
            return None
    print(f"[CoT3.recheck] LLM call failed after retries: {type(last_exc).__name__}: {last_exc}")
    return None


def _strip_fence(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.strip()
    return text


def _parse_verdict(raw: Optional[str]) -> Optional[dict]:
    """{'verdict': 'ADDRESSED|OPEN|UNCLEAR', 'evidence': '...'} 파싱. 형식/값 불량이면 None."""
    if not raw:
        return None
    try:
        data = json.loads(_strip_fence(raw))
    except json.JSONDecodeError:
        return None
    verdict = str(data.get("verdict", "")).strip().upper()
    if verdict not in ("ADDRESSED", "OPEN", "UNCLEAR"):
        return None
    return {"verdict": verdict, "evidence": str(data.get("evidence", ""))[:200]}


def verify_candidates_against_source(
    candidates: List[CrossComparisonCandidate],
    evidence_pool: Dict,
    paper_texts: Dict[str, str],
    model: str = JUDGE_MODEL,
) -> Tuple[List[CrossComparisonCandidate], List[str]]:
    """CoT3.static를 통과한 후보들 중 '위험 후보(achieved 역량에만 기댄 주장된 한계)'만 원문에 재대조한다.

    - 위험 아님: 그대로 통과, source_check=None.
    - 위험 & ADDRESSED: 논문이 이미 처리한 한계 → DROP.
    - 위험 & OPEN: 진짜 unstated 한계로 확인 → 유지, source_check="OPEN: ...".
    - 위험 & UNCLEAR / 파싱실패 / API실패: 보수적으로 유지, source_check로 상태 표기(다음 단계/사람 재확인).

    Args:
        paper_texts: {"P1": <원문 .tex 전체 텍스트>, ...} — evidence_pool의 논문 키와 동일해야 함.
    Returns:
        (kept_candidates, log)
    """
    kept: List[CrossComparisonCandidate] = []
    log: List[str] = []
    risky_count = 0

    for cand in candidates:
        needs, achieved_refs = classify_candidate(cand, evidence_pool)
        if not needs:
            cand.source_check = None
            kept.append(cand)
            continue
        risky_count += 1

        # 물고 있는 논문의 원문이 하나라도 없으면 검증 불가 → 보수적으로 유지(표기만)
        ref_papers = {pk for pk, _ in achieved_refs}
        if any(pk not in paper_texts or not paper_texts.get(pk) for pk in ref_papers):
            cand.source_check = "UNVERIFIED (source text unavailable)"
            log.append(f"[KEEP-UNVERIFIED] {cand.candidate_id}: source text missing for {sorted(ref_papers)} — kept")
            kept.append(cand)
            continue

        prompt = _build_recheck_prompt(cand, achieved_refs, evidence_pool, paper_texts)
        raw = _call_llm(prompt, model)
        if raw is None:
            cand.source_check = "UNVERIFIED (recheck API unavailable)"
            log.append(f"[KEEP-UNVERIFIED] {cand.candidate_id}: recheck API unavailable — kept (no fair verification)")
            kept.append(cand)
            continue

        parsed = _parse_verdict(raw)
        if parsed is None:
            cand.source_check = "UNVERIFIED (unparseable recheck output)"
            log.append(f"[KEEP-UNVERIFIED] {cand.candidate_id}: recheck output unparseable — kept conservatively")
            kept.append(cand)
            continue

        verdict, evidence = parsed["verdict"], parsed["evidence"]
        if verdict == "ADDRESSED":
            # 논문이 이미 다룬 한계 = 실재하지 않는 공백 → DROP (환각/재탕 제거)
            log.append(f"[DROP] {cand.candidate_id}: paper already addresses this — {evidence}")
            continue

        cand.source_check = f"{verdict}: {evidence}"
        log.append(f"[KEEP] {cand.candidate_id}: {verdict} — {evidence}")
        kept.append(cand)

    if risky_count == 0:
        log.append(f"[INFO] 0 risky candidates (all {len(candidates)} grounded on stated limitations or "
                   f"verified coverage gaps) — nothing to re-check, all passed through")
    if not kept:
        log.append("[WARN] no candidate survived source re-check — check generation/verification quality")

    return kept, log
