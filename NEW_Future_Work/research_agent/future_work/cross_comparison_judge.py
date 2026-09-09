# [CoT3.judge] 교차비교 판정자 — "도출 여부 바닥 검사"(분해 + 함의 이진 게이트).
#
# 옛 버전은 grounding/validity/novelty를 1~5 Likert로 채점했는데, 중형 판정 모델의 leniency로 전원
# 5/5/5로 포화돼 필터가 사실상 무력화됐다(실측). 그래서 과제를 "미세 랭킹"에서 "이 gap이 인용 근거에서
# 실제로 도출되는가"라는 이진 바닥 검사로 좁혔다. warrant gap("진짜 id를 인용하고 주제도 인접하지만
# 근거로부터 도출되지 않는 갭")을 잡는 게 목적.
#
# ── 두 검사(후보 1개당, pointwise):
#   (1) grounding : gap_statement를 원자 sub-claim으로 분해 → 각 claim을 '인용 근거의 실제 텍스트'에
#       대해 entail/neutral/contradict로 판정 + 근거 문장 인용 강제. 하나라도 neutral/contradict면 FAIL.
#       ※ 최종 grounding(PASS/FAIL/UNSURE)은 LLM 말이 아니라 '조각 라벨'로부터 코드가 계산한다 — LLM이
#         PASS라 우겨도 neutral 조각이 있으면 FAIL로 확정(포화 2차 방어). entail인데 인용문이 비면 neutral로 강등.
#   (2) validity  : proposed_direction이 gap_statement의 공백을 닫는 논리로 성립하나(자기 정합성) PASS/FAIL/UNSURE.
#
# ── 판정: grounding 또는 validity가 FAIL → drop / 둘 중 UNSURE → 보류(keep, 플래그) / 둘 다 PASS → keep.
#   판정 API가 죽으면(응답 자체 못 받음) 후보 잘못 아니니 KEEP-UNJUDGED로 살린다(공정성).
#
# ── 유지: OpenRouter provider 고정(openrouter_provider_extra_body), 벽시계 하드캡(_completion_with_deadline),
#   백오프 재시도. 폐기: RUBRIC(1~5)·COMPARATIVE_CALIBRATION·cause_tag·novelty(→CoT4).

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from litellm import completion
from litellm.exceptions import ServiceUnavailableError

# 일시적(재시도로 복구 가능한) 판정자 오류 클래스들. 설치된 litellm 버전에 없을 수도 있어 방어적으로 모은다.
_TRANSIENT_EXC = [ServiceUnavailableError]
for _name in ("RateLimitError", "Timeout", "APIConnectionError", "InternalServerError"):
    try:
        _TRANSIENT_EXC.append(getattr(__import__("litellm.exceptions", fromlist=[_name]), _name))
    except (AttributeError, ImportError):
        pass
_TRANSIENT_EXC = tuple(_TRANSIENT_EXC)

# 예외 타입으론 안 잡히지만 메시지로 판별하는 일시적 신호들(느린 provider·타임아웃·일부 폴백 케이스).
_TRANSIENT_MSG = (
    "rate-limit", "temporarily", "provider returned error",
    "timeout", "overloaded", "please retry", "try again", "429", "502", "503", "504",
)

from research_agent.constant import JUDGE_MODEL, API_BASE_URL, openrouter_provider_extra_body
from research_agent.future_work.cross_comparison_validation import CrossComparisonCandidate


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CRITERIA — 판정 기준(구 RUBRIC 자리). 채점 기준을 바꾸려면 이 블록만 수정.    ║
# ║  1~5 점수가 아니라 '분해 + 함의(entail/neutral/contradict) + 인용 강제'다.     ║
# ╚══════════════════════════════════════════════════════════════════════════╝
CRITERIA = """\
Do TWO checks on this ONE candidate.

[Check 1 — GROUNDING of the gap_statement]
Decompose gap_statement into atomic claims, then check each against the VERIFIED EVIDENCE.
VERIFIED EVIDENCE = the [Cited evidence] block PLUS the [Background] block. Both are equally valid,
verified facts about the SAME cited paper(s): [Cited evidence] is what the candidate explicitly cited,
[Background] is that paper's other verified sub-goals and limitations. A factual claim counts as
grounded if EITHER block supports it — this exists so a true scene-setting premise (e.g. "the paper
does X / achieved X") is NOT marked neutral merely because the candidate cited only the gap id and not
the achieved id. Do NOT treat a claim as grounded from outside these two blocks — anything not in the
cited paper(s)' own profile is still neutral.

WHAT TO EXTRACT: extract ONLY factual PREMISES about the cited paper(s) — what a cited paper DID, what
it DID NOT achieve, or what it stated as a limitation. These are the claims the cited evidence can confirm.
WHAT TO SKIP (do NOT add these as sub-claims): the gap's novelty / absence conclusion — any claim
asserting absence in the broader literature. This is critical — the following ALL must be SKIPPED, not
labeled: "no prior work…", "no work has tested/examined…", "has never been applied", "never explored",
"neither evaluates/explores…", "none does/optimizes…", "no ablation removes/…", "has not received…",
"has not been applied/tested/combined…", "unexplored", "the absence of …", "the two techniques have not
been combined", "X lacks Y (relative to another paper)". These assert NOVELTY across the field, which a
SEPARATE later stage (CoT4) checks — they are NOT grounding failures here, so do NOT add them as
sub-claims at all. If no factual premise remains after skipping, return an empty "subclaims" list.

NEGATION RULE (important, decides "keep vs skip" for "does not …" clauses): a clause of the form
"paper A does not / did not / does not address / does not consider X" is handled by WHAT it is about,
not by the words:
  - KEEP it as a sub-claim only if it is paper A's OWN limitation that the CITED EVIDENCE supports —
    e.g. a cited coverage-gap / limitation id of A literally says A does not do X. Then it is a normal
    factual claim (it will be "entail"). Example: "P3 does not consider in-plane rotations" when P3's
    cited limitation says exactly that.
  - SKIP it (do NOT add it, do NOT label it "neutral") if X is a capability belonging to ANOTHER paper
    and no cited evidence of A supports the claim — this is a cross-paper "A does not do what B does"
    NOVELTY setup, which CoT4 checks. Example: "P1 does not address parameter-efficient adaptation"
    (PEFT is P2's capability; P1's cited evidence is silent on it) → skip.

For EACH extracted atomic claim, decide its relation to the VERIFIED EVIDENCE (Cited + Background) and
quote the exact evidence sentence that justifies your label:
  - "entail"     — a sentence in the Cited evidence OR the Background supports / makes this claim true.
                   You MUST quote it (from whichever block).
  - "neutral"    — neither the Cited evidence nor the Background supports or contradicts this claim; you
                   cannot establish it from either. (Topic-adjacent is NOT enough — that is still neutral.)
  - "contradict" — the Cited evidence or Background conflicts with this claim; quote the conflicting sentence.
Rule: an "entail" without a real quote from the Cited evidence or Background is invalid — if you cannot
quote a supporting sentence from either, the correct label is "neutral".

ATOMICITY: if a sentence bundles a factual assertion with a hypothesis / proposal (e.g. "X, which
could benefit from Y", "X could be mitigated by Y", "X could be made rotation-equivariant"), SPLIT it:
keep ONLY the factual assertion about the cited paper as a sub-claim, and DROP the speculative
"could / might / may / would help" part — that is a proposal, not a fact to be grounded (skip it, like
the absence claims above). One sub-claim = one checkable factual assertion.

DECISION CHECKLIST — for EACH atomic claim, walk these in order before assigning a label:
  (1) Is the claim's subject/entity actually present in the Cited evidence OR Background at all? If NOT → "neutral".
  (2) Does a sentence in the Cited evidence or Background EXPLICITLY state this claim? If yes → "entail" (quote it).
  (3) If not explicit, is it a DIRECT, necessary inference from the Cited evidence or Background (not a guess)?
      direct/necessary inference → "entail" (quote the basis); only a loose or speculative link → "neutral".
  (4) Does the Cited evidence or Background state the OPPOSITE of the claim? → "contradict" (quote it).

[Check 2 — VALIDITY of the proposed_direction]
Judge ONLY whether proposed_direction is a sound, on-target way to close the gap stated in
gap_statement (internal coherence — do NOT require external evidence for this check):
  - "PASS"   — the direction plausibly addresses that specific gap
  - "FAIL"   — the direction does not address that gap / is logically disconnected from it
  - "UNSURE" — you genuinely cannot tell
"""

# 판정자 호출 1회당 응답 대기 상한(초). litellm의 timeout이 이 OpenRouter 경로에서 신뢰성 없어 벽시계 하드캡.
JUDGE_TIMEOUT_S = int(os.getenv("JUDGE_TIMEOUT_S", "150"))
# 판정자 동시 실행 수 — 후보별 판정은 서로 독립이라 병렬 가능(순차 N콜 → 동시). 너무 크게 잡으면 provider
# rate-limit(429)에 걸릴 수 있어 보수적 기본값. env로 조절.
JUDGE_CONCURRENCY = int(os.getenv("JUDGE_CONCURRENCY", "4"))
# ── 판정 기준 관련 수정은 여기 위까지 ─────────────────────────────────────────


def _resolve_cited_evidence(candidate: CrossComparisonCandidate, evidence_pool: dict) -> str:
    """후보가 인용한 source_evidence id들을 evidence_pool에서 실제 텍스트로 풀어 반환한다(= 대조 기준).
    subgoal → '[status] label: description (evidence: rationale)', limitation → '[type] "quote"'."""
    lines = []
    for ref in candidate.source_evidence:
        pk, _, local = ref.partition(":")
        pk, local = pk.strip(), local.strip()
        paper = evidence_pool.get(pk) if evidence_pool else None
        if not paper:
            lines.append(f"  - {ref}: (unresolved — unknown paper key)")
            continue
        sg = paper.get("subgoals", {}).get(local)
        lim = paper.get("limitations", {}).get(local)
        if sg is not None:
            desc = getattr(sg, "description", "")
            lines.append(f"  - {ref} [{sg.status}] {sg.label}: {desc} (evidence: {sg.rationale})")
        elif lim is not None:
            # context(CoT2가 잡아둔 앞뒤 문장)를 함께 인라인 — quote가 "This can be achieved by..." 처럼
            # 지시어로 시작해 자기완결이 안 될 때, 판정자가 앞 문장을 보고 'This'의 선행사를 해소하게 한다.
            ctx = (getattr(lim, "context", "") or "").strip()
            ctx_part = f'\n      surrounding context: "{ctx}"' if ctx and ctx != lim.quote.strip() else ""
            lines.append(f'  - {ref} [{lim.limitation_type}] "{lim.quote}"{ctx_part}')
        else:
            lines.append(f"  - {ref}: (unresolved — id not found in {pk})")
    return "\n".join(lines) if lines else "  (no cited evidence)"


def _resolve_background(candidate: CrossComparisonCandidate, evidence_pool: dict) -> str:
    """후보가 인용한 논문들의 '나머지' 검증된 사실을 배경으로 푼다 — 인용하지 않은 subgoal·limitation 전체.

    왜: gap_statement는 흔히 "논문이 X는 했지만(장면설정) Y가 갭이다"처럼 쓰이는데, 후보가 갭 id(Y)만
    인용하고 achieved id(X)는 인용 안 하면, X 전제가 인용 근거만으론 확인 불가라 neutral→FAIL 위양성이
    난다. 인용 논문의 나머지 프로필을 배경으로 줘서 그런 '형제 id 전제'가 grounding되게 한다. 배경은 인용
    논문의 실제 내용뿐이므로, 그 논문과 무관한 주장(음성 카나리)은 배경에도 없어 여전히 잡힌다.

    이미 [Cited evidence]에 나온 id는 중복이라 제외한다."""
    cited_ids = set(candidate.source_evidence)
    cited_pks = []
    for ref in candidate.source_evidence:
        pk = ref.partition(":")[0].strip()
        if pk and pk not in cited_pks:
            cited_pks.append(pk)

    lines = []
    for pk in cited_pks:
        paper = evidence_pool.get(pk) if evidence_pool else None
        if not paper:
            continue
        for gid, sg in paper.get("subgoals", {}).items():
            ref = f"{pk}:{gid}"
            if ref in cited_ids:
                continue
            desc = getattr(sg, "description", "")
            lines.append(f"  - {ref} [{sg.status}] {sg.label}: {desc} (evidence: {sg.rationale})")
        for lid, lim in paper.get("limitations", {}).items():
            ref = f"{pk}:{lid}"
            if ref in cited_ids:
                continue
            lines.append(f'  - {ref} [{lim.limitation_type}] "{lim.quote}"')
    return "\n".join(lines) if lines else "  (no additional background)"


def _build_judge_prompt(candidate: CrossComparisonCandidate, evidence_pool: dict) -> str:
    """후보 1개 + 그 후보가 인용한 근거의 '실제 텍스트'(+ 인용 논문의 나머지 배경) + 판정 기준. pointwise."""
    cited = _resolve_cited_evidence(candidate, evidence_pool)
    background = _resolve_background(candidate, evidence_pool)
    return f"""\
You are a strict grounding checker for research-gap candidates. You are given ONE candidate and the \
ACTUAL TEXT of the evidence it cites. Follow the criteria exactly.

{CRITERIA}

[Candidate]
gap_statement: {candidate.gap_statement}
proposed_direction: {candidate.proposed_direction}

[Cited evidence — actual text of the ids this candidate cites]
{cited}

[Background — other verified facts about the SAME cited paper(s) (their non-cited sub-goals / limitations)]
{background}

Return ONLY this JSON object (no markdown, no code fences, no text before or after):
{{"subclaims": [{{"claim": "<one atomic claim from gap_statement>", "verdict": "entail|neutral|contradict", "quote": "<exact sentence from the cited evidence, or empty>"}}], "validity": "PASS|FAIL|UNSURE", "validity_reason": "<one short sentence>"}}
"""


def _completion_with_deadline(deadline_s: int, **kwargs):
    """completion(**kwargs)를 데몬 스레드에서 돌리고 deadline_s 안에 안 끝나면 TimeoutError를 던진다.
    litellm의 timeout이 이 OpenRouter 경로에서 신뢰성 없어(실측) 벽시계로 하드 캡을 건다."""
    box: dict = {}
    def _run():
        try:
            box["resp"] = completion(**kwargs)
        except Exception as e:
            box["exc"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(deadline_s)
    if th.is_alive():
        raise TimeoutError(f"judge call exceeded {deadline_s}s hard wall-clock timeout")
    if "exc" in box:
        raise box["exc"]
    return box["resp"]


def _call_judge(prompt: str, model: str) -> Optional[str]:
    """판정자 LLM 호출. 503/타임아웃 등 일시 오류는 백오프 재시도, API가 끝내 죽으면 None(응답 자체 못 받음).
    provider 고정(openrouter_provider_extra_body)으로 죽은 provider 랜덤 배정을 피한다."""
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp = _completion_with_deadline(
                JUDGE_TIMEOUT_S,
                model=model,
                messages=[{"role": "user", "content": prompt}],
                base_url=API_BASE_URL,
                timeout=JUDGE_TIMEOUT_S,
                num_retries=0,
                max_retries=0,
                **openrouter_provider_extra_body(model),
            )
            return resp.choices[0].message.content
        except Exception as e:
            transient = (isinstance(e, (_TRANSIENT_EXC, TimeoutError))
                         or any(s in str(e).lower() for s in _TRANSIENT_MSG))
            if transient and attempt < max_attempts - 1:
                print(f"[CoT3.judge] transient LLM error, retrying in {10 * (2 ** attempt)}s "
                      f"({type(e).__name__}): {e}")
                time.sleep(10 * (2 ** attempt))  # 10s, 20s
                continue
            print(f"[CoT3.judge] LLM call failed ({type(e).__name__}): {e}")
            return None
    return None


def _strip_fence(text: str) -> str:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if "\n" in text:
            text = text.split("\n", 1)[1]
        text = text.strip()
    return text


_VERDICTS = ("entail", "neutral", "contradict")
_PFU = ("PASS", "FAIL", "UNSURE")

# gap 속 '세상-전체 부재 주장(absence-in-literature)'을 나타내는 표현 — "아무도 안 했다 / never applied /
# no work". 이런 조각은 grounding 검사에서 제외한다: 인용 근거(=논문이 뭘 했나)로는 확인 불가능하고, "이게
# 새로운가"는 CoT4가 판단할 몫이기 때문. (주의: 이건 제거된 'novelty 점수 축'이 아니라, gap 문장 속 부재
# '문장'을 골라내는 필터다.) CRITERIA로 LLM에도 스킵을 지시하지만 중형 모델이 일관되게 못 지켜(실측: 부재
# 조각이 neutral로 새어 FAIL을 유발) 코드로도 한 번 더 걸러 결정론적으로 확정한다. 다어절 '세상-전체 부재'
# 표현만 담아 오탐(논문 자체에 대한 부정 사실, 예: "P2 does not support 2D layers")은 안 걸리게 한다.
_ABSENCE_MARKERS = (
    "no work", "no prior work", "no existing work", "no published work",
    "has never been", "have never been", "never been applied", "never been explored",
    "never been tested", "never been combined", "never been investigated",
    "neither ",                          # "neither evaluates / explores"
    "no ablation",
    "has not received", "have not received",
    "has not been applied", "have not been applied", "not been combined",
    "not been tested across", "not been jointly", "not been investigated",
    "unexplored", "have not been combined",
    # cross-paper 'neither/does not examine' 부재 phrasings (실측 C5 누수 대응)
    "does not examine", "does not test", "does not explore",
    "neither examines", "neither explores", "neither tests",
    "never tested", "not been tested", "has not been tested", "have not been tested",
)


def _is_absence_claim(text: str) -> bool:
    """조각 텍스트가 '세상-전체 부재 주장'인지(= grounding에서 제외 대상, CoT4 몫). 대소문자·공백 정규화 후 부분일치."""
    t = " ".join(str(text).lower().split())
    return any(m in t for m in _ABSENCE_MARKERS)


def _parse_verdict(raw: Optional[str]) -> Optional[dict]:
    """판정 출력 파싱 → {"subclaims":[{claim,verdict,quote}], "validity":PFU, "validity_reason":str}.
    최상위 JSON/스키마가 깨지면 None. 개별 규칙 강제:
      · verdict 값이 entail/neutral/contradict 밖이면 그 조각은 무시(불량).
      · entail인데 quote가 비면 neutral로 강등(인용 문장 강제).
    """
    if not raw:
        return None
    try:
        data = json.loads(_strip_fence(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    raw_subs = data.get("subclaims")
    if not isinstance(raw_subs, list):
        return None
    subclaims = []
    for s in raw_subs:
        if not isinstance(s, dict):
            continue
        verdict = str(s.get("verdict", "")).strip().lower()
        if verdict not in _VERDICTS:
            continue
        claim = str(s.get("claim", "")).strip()
        quote = str(s.get("quote", "")).strip()
        if not claim:
            continue
        # 인용 문장 강제: entail 주장은 근거 문장을 반드시 인용해야 함 — 없으면 neutral로 강등.
        if verdict == "entail" and not quote:
            verdict = "neutral"
        subclaims.append({"claim": claim, "verdict": verdict, "quote": quote})

    # [코드 안전망] LLM이 스킵 못 한 '세상-전체 부재' 조각을 grounding 집합에서 제외(CoT4 몫) — CRITERIA와 이중 방어.
    subclaims = [s for s in subclaims if not _is_absence_claim(s["claim"])]

    validity = str(data.get("validity", "")).strip().upper()
    if validity not in _PFU:
        validity = "UNSURE"
    reason = str(data.get("validity_reason", ""))[:200]
    return {"subclaims": subclaims, "validity": validity, "validity_reason": reason}


def _grounding_from_subclaims(subclaims: List[dict]) -> str:
    """조각 라벨로부터 grounding을 '코드가' 계산한다(LLM 말이 아니라). 포화 2차 방어.
      · 조각 없음 → UNSURE (판정 불가)
      · 하나라도 neutral/contradict → FAIL
      · 전부 entail → PASS
    """
    if not subclaims:
        return "UNSURE"
    verdicts = [s["verdict"] for s in subclaims]
    if any(v in ("neutral", "contradict") for v in verdicts):
        return "FAIL"
    if all(v == "entail" for v in verdicts):
        return "PASS"
    return "UNSURE"


def _judge_one(candidate: CrossComparisonCandidate, evidence_pool: dict, model: str
               ) -> Tuple[str, Optional[dict]]:
    """후보 1개를 판정한다. 형식 불량이면 1회 재시도 후 상태를 구분해 반환한다.

    Returns (status, parsed):
      ("ok", {...})              정상 파싱됨
      ("api_unavailable", None)  API가 죽어 응답 자체를 못 받음 → 상위에서 KEEP-UNJUDGED
      ("unparseable", None)      응답은 왔으나 재시도 후에도 형식 불량 → 상위에서 보수적으로 KEEP-UNSURE
    """
    prompt = _build_judge_prompt(candidate, evidence_pool)
    raw = _call_judge(prompt, model)
    if raw is None:
        return "api_unavailable", None
    parsed = _parse_verdict(raw)
    if parsed is not None:
        return "ok", parsed

    retry_prompt = prompt + (
        "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object "
        "(subclaims + validity + validity_reason) and nothing else."
    )
    raw2 = _call_judge(retry_prompt, model)
    if raw2 is None:
        return "api_unavailable", None
    parsed = _parse_verdict(raw2)
    if parsed is not None:
        return "ok", parsed
    return "unparseable", None


def judge_candidates(
    candidates: List[CrossComparisonCandidate],
    input_block: str = "",
    evidence_pool: dict = None,
    model: str = JUDGE_MODEL,
) -> Tuple[List[CrossComparisonCandidate], List[str]]:
    """CoT3.static/recheck를 통과한 후보들을 '분해+함의 이진 게이트'로 판정한다.

    각 후보의 gap_statement를 인용 근거에 대해 분해·함의 판정(grounding)하고, proposed_direction의
    자기 정합성(validity)을 본다. 결과를 judge_verdict / judge_subclaims에 채워 반환한다.

    Args:
        candidates: static/recheck 통과 후보 목록
        input_block: (하위호환용, 미사용) 옛 시그니처 유지 — pointwise 판정엔 필요 없음
        evidence_pool: build_evidence_pool 결과(dict). grounding 대조의 기준. None이면 대조 불가 → 전원 KEEP-UNSURE.
    Returns:
        (kept_candidates, log)  — kept는 CoT4로 넘어갈 대상(FAIL만 drop), log는 KEEP/DROP/사유
    """
    kept: List[CrossComparisonCandidate] = []
    log: List[str] = []
    if not candidates:
        return kept, log

    if evidence_pool is None:
        for cand in candidates:
            cand.judge_verdict = {"grounding": "UNSURE", "validity": "UNSURE",
                                  "validity_reason": "no evidence_pool — cannot check grounding"}
            log.append(f"[KEEP-UNSURE] {cand.candidate_id}: evidence_pool missing — kept unjudged")
            kept.append(cand)
        return kept, log

    # [병렬 판정] 후보별 판정은 서로 독립(비교 없음) → 동시 실행해 순차 N콜의 대기시간을 줄인다.
    # 각 _judge_one은 내부에서 자기 벽시계 하드캡 스레드를 갖는다. 결과는 원래 순서로 되돌려 처리.
    results: List[Tuple[str, Optional[dict]]] = [("api_unavailable", None)] * len(candidates)
    max_workers = max(1, min(JUDGE_CONCURRENCY, len(candidates)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_judge_one, cand, evidence_pool, model): i for i, cand in enumerate(candidates)}
        for fut, i in futs.items():
            try:
                results[i] = fut.result()
            except Exception as e:  # 워커 예외는 방어적으로 api_unavailable 취급(후보 잘못 아님 → KEEP)
                print(f"[CoT3.judge] worker error ({type(e).__name__}): {e}")
                results[i] = ("api_unavailable", None)

    # 판정 결과를 원래 후보 순서대로 적용(drop/keep 결정 + 필드 채움)
    for i, cand in enumerate(candidates):
        status, parsed = results[i]

        if status == "api_unavailable":
            cand.judge_verdict = None
            cand.judge_subclaims = None
            log.append(f"[KEEP-UNJUDGED] {cand.candidate_id}: judge API unavailable — kept (no fair judgment)")
            kept.append(cand)
            continue

        if status == "unparseable":
            cand.judge_verdict = {"grounding": "UNSURE", "validity": "UNSURE",
                                  "validity_reason": "judge output unparseable after retry"}
            cand.judge_subclaims = None
            log.append(f"[KEEP-UNSURE] {cand.candidate_id}: judge output unparseable — kept conservatively")
            kept.append(cand)
            continue

        # status == "ok": 조각 라벨로부터 grounding을 코드가 계산(LLM 말 아님)
        subclaims = parsed["subclaims"]
        grounding = _grounding_from_subclaims(subclaims)
        validity = parsed["validity"]
        cand.judge_verdict = {"grounding": grounding, "validity": validity,
                              "validity_reason": parsed["validity_reason"]}
        cand.judge_subclaims = subclaims

        bad = [s for s in subclaims if s["verdict"] in ("neutral", "contradict")]
        detail = (f"grounding={grounding} validity={validity}"
                  f"{' | ' + '; '.join(s['verdict'] + ':' + s['claim'][:50] for s in bad) if bad else ''}")

        # 판정: FAIL이면 drop, UNSURE는 보류(keep), 둘 다 PASS면 keep
        if grounding == "FAIL" or validity == "FAIL":
            log.append(f"[DROP] {cand.candidate_id}: {detail}")
            continue
        if grounding == "UNSURE" or validity == "UNSURE":
            log.append(f"[KEEP-UNSURE] {cand.candidate_id}: {detail} — {parsed['validity_reason']}")
            kept.append(cand)
            continue
        log.append(f"[PASS] {cand.candidate_id}: {detail}")
        kept.append(cand)

    if not kept:
        log.append("[WARN] no candidate passed the judge — check criteria or generation quality")
    return kept, log
