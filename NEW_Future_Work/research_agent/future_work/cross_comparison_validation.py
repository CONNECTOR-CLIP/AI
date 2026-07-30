# [3단계: 교차비교] 정적 검증 계층 — AI 미사용. 생성 에이전트(cross_comparison_agent.py)가
# 뱉은 공백 후보 JSON을 (a) 스키마 검증 (b) grounding-by-reference (c) 포맷 정합성
# (d) 중복 제거 (e) 기각목록 필터까지 순수 정적으로 처리한다.
#
# 왜 CoT3에는 grounding "재확인"이 아니라 grounding "검사"가 필요한가:
#   2단계(limitation)는 quote를 원문에서 정규식으로 슬라이싱하므로 애초에 grounded였고, 거기 validation의
#   grounding check는 "혹시 모를 버그"용 방어선일 뿐이었다. 반면 3단계 후보는 LLM이 "생성"한 것이라
#   근거를 날조할 수 있다. 그래서 여기서는 후보가 스스로 지목한 source_evidence(예: "P1:G2", "P2:L1")가
#   실제 CoT1 subgoal / CoT2 limitation 풀에 존재하는지를 대조하는 게 핵심 방어 로직이다.
#   단, 대조 자체는 사전(evidence_pool) 조회라 순수 정적 — 판정자(step4, LLM)의 "타당성" 평가와는 별개.
#
# 왜 정적체크(step3)를 판정자(step4)보다 먼저 두나: 정적체크는 공짜, 판정자는 토큰 비용. 싼 필터로
# 날조·중복·기각재등장을 먼저 쳐내야 판정자 호출을 낭비하지 않는다.
#
# 이 파일이 "하드 실패(=재시도 유발)"로 보는 것과 "후보 단위 드롭(=경고만)"으로 보는 것을 구분한다:
#   - 하드 실패(error 반환): JSON 파싱 불가 / 최상위 스키마가 통째로 깨짐 → 생성 재시도가 의미 있음.
#   - 후보 단위 드롭(warnings): 특정 후보의 스키마·grounding·중복 문제 → 그 후보만 버리고 나머지는 살림
#     (limitation_validation.py와 동일 철학. 후보 하나의 결함이 다른 후보를 막을 이유가 없다).
#   - "후보 수가 목표(8~10)보다 적음"은 여기서 실패로 보지 않는다 — 그건 CoT3+CoT4를 감싸는
#     flow 레벨의 재탐색 루프가 처리할 문제다. 여기서는 soft warning만 남긴다.

from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ValidationError, field_validator

# 1·2단계 검증 유틸 재사용 (DRY) — 코드펜스 제거 / pydantic 에러 포맷은 이미 있는 걸 그대로 쓴다.
from research_agent.future_work.goal_decomposition_validation import (
    GoalDecomposition,
    strip_code_fence,
    format_pydantic_errors,
)
from research_agent.future_work.limitation_validation import LimitationCandidate

# 과생성 목표 하한(soft). 이보다 적어도 하드 실패 아님 — 재탐색 루프 소관이라 경고만.
MIN_CANDIDATES_WARN = 8
SOURCE_TYPES = ("paper_stated", "synthesized", "combination")

# 입력 블록에서 "공백"으로 상세히 펼칠 subgoal 상태. achieved는 한 줄 요약으로만 넣어 토큰을 아낀다.
GAP_STATUSES = ("not_achieved", "partially_achieved")


class PaperInput(BaseModel):
    """CoT3 입력 1편 = 그 논문의 CoT1 결과(목표/커버리지) + CoT2 결과(한계/언급 목록).
    limitations는 비어 있을 수 있다(명시적 한계를 안 쓴 논문). goal_decomposition은 항상 있어야 한다."""
    goal_decomposition: GoalDecomposition
    limitations: List[LimitationCandidate]


class CrossComparisonCandidate(BaseModel):
    candidate_id: str                       # C1, C2, ...
    source_type: Literal["paper_stated", "synthesized", "combination"]
    source_papers: List[str]                # ["P1", "P2"] — evidence_pool의 논문 키
    source_evidence: List[str]              # ["P1:G2", "P2:L1"] — 근거로 지목한 subgoal/limitation 참조
    gap_statement: str
    proposed_direction: str
    rationale: str
    # step4(판정자)가 나중에 채워 넣는 필드 — 생성 시점엔 없음(그래서 Optional/None 기본값).
    judge_scores: Optional[Dict[str, int]] = None
    cause_tag: Optional[str] = None

    @field_validator("candidate_id", "gap_statement", "proposed_direction", "rationale")
    @classmethod
    def not_empty(cls, v: str, info):
        if not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v

    @field_validator("source_papers", "source_evidence")
    @classmethod
    def not_empty_list(cls, v: List[str], info):
        # source_evidence가 비면 grounding 자체가 불가능한 후보 → 스키마 단계에서 거른다.
        if not v:
            raise ValueError(f"{info.field_name} must contain at least one item")
        if any(not str(x).strip() for x in v):
            raise ValueError(f"{info.field_name} must not contain empty strings")
        return v


def build_evidence_pool(papers: List[PaperInput]) -> Dict:
    """CoT1·CoT2 결과 N편을 grounding 대조용 evidence 풀로 조립한다(Step 0).
    각 논문에 입력 순서대로 P1, P2, ... 키를 부여하고, subgoal은 원래 G-id를,
    limitation은 인덱스 기반 L-id(L1, L2, ...)를 부여한다.

    반환 구조:
      { "P1": {"title", "research_problem",
               "subgoals": {"G1": Subgoal, ...},
               "limitations": {"L1": LimitationCandidate, ...}},
        "P2": {...}, ... }
    이 풀은 (1) 생성 에이전트에게 보여줄 입력 포맷의 원천이자, (2) 이 파일의 grounding 대조 기준이다."""
    pool: Dict[str, Dict] = {}
    for idx, paper in enumerate(papers, start=1):
        pkey = f"P{idx}"
        gd = paper.goal_decomposition
        pool[pkey] = {
            "title": gd.paper_title,
            "research_problem": gd.research_problem,
            # subgoal_id는 CoT1 검증에서 논문 내 유일성이 보장됨 → dict 키로 안전.
            "subgoals": {sg.subgoal_id: sg for sg in gd.subgoals},
            "limitations": {f"L{i}": lim for i, lim in enumerate(paper.limitations, start=1)},
        }
    return pool


def format_cross_comparison_input(evidence_pool: Dict) -> str:
    """evidence_pool(Step 0-a, 기계용 dict)을 생성 에이전트에게 넣을 압축 텍스트 블록(Step 0-b)으로 변환한다.
    토큰 절약 원칙: 공백(not_achieved/partially)은 근거(rationale)까지 상세히, achieved는 라벨만 한 줄로.
    모든 subgoal/limitation에 'Pk:Gx'/'Pk:Lx' id를 노출해 — 에이전트가 이 id로만 근거를 달게 하고,
    validate_cross_comparison이 같은 id를 evidence_pool에 대조하도록(계약 일치) 한다."""
    lines = [f"=== Cross-Comparison Input ({len(evidence_pool)} papers) ===", ""]
    for pk, p in evidence_pool.items():
        lines.append(f"[{pk}] {p['title']}")
        lines.append(f"Research problem: {p['research_problem']}")

        gap_lines, achieved_labels = [], []
        for gid, sg in p["subgoals"].items():
            if sg.status in GAP_STATUSES:
                gap_lines.append(f"  - {pk}:{gid} [{sg.status}] {sg.label} — {sg.rationale}")
            else:  # achieved — 교차참조용 한 줄 요약만
                achieved_labels.append(f"{gid} {sg.label}")
        lines.append("Coverage gaps (CoT1):")
        lines.extend(gap_lines if gap_lines else ["  (none flagged)"])
        if achieved_labels:
            lines.append("Achieved (cross-ref only): " + ", ".join(achieved_labels))

        lines.append("Paper-stated limitations (CoT2):")
        if p["limitations"]:
            for lid, lim in p["limitations"].items():
                lines.append(f'  - {pk}:{lid} [{lim.limitation_type}] "{lim.quote}"')
        else:
            lines.append("  (none extracted)")
        lines.append("")

    lines.append("=== Paper key map ===")
    for pk, p in evidence_pool.items():
        lines.append(f"{pk} = {p['title']}")
    return "\n".join(lines)


def _normalize(text: str) -> str:
    """중복 판정용 정규화 — 소문자화 + 공백 단일화."""
    return " ".join(text.lower().split())


def _check_evidence_refs(candidate: CrossComparisonCandidate, pool: Dict) -> List[str]:
    """후보의 source_papers / source_evidence가 evidence_pool에 실재하는지 대조한다.
    문제가 있으면 사유 문자열 리스트를, 없으면 빈 리스트를 반환한다(빈 리스트 = grounded)."""
    problems: List[str] = []

    # (1) source_papers가 전부 풀에 있는 논문 키인지 (없는 논문 날조 차단)
    for pk in candidate.source_papers:
        if pk not in pool:
            problems.append(f"source_papers references unknown paper key {pk!r}")

    # (2) source_evidence의 각 참조가 "Pk:Gx" / "Pk:Lx" 형식이고 실제로 존재하는지
    evidence_papers = set()
    for ref in candidate.source_evidence:
        if ":" not in ref:
            problems.append(f"evidence ref {ref!r} is malformed (expected 'P<i>:G<j>' or 'P<i>:L<j>')")
            continue
        pk, local_id = ref.split(":", 1)
        pk, local_id = pk.strip(), local_id.strip()
        if pk not in pool:
            problems.append(f"evidence ref {ref!r} points to unknown paper key {pk!r}")
            continue
        evidence_papers.add(pk)
        subgoals = pool[pk]["subgoals"]
        limitations = pool[pk]["limitations"]
        if local_id not in subgoals and local_id not in limitations:
            problems.append(
                f"evidence ref {ref!r} points to {local_id!r} which is not a known "
                f"subgoal/limitation of {pk}"
            )

    # (3) source_evidence가 가리키는 논문은 반드시 source_papers에도 있어야 함(둘의 정합성)
    missing = evidence_papers - set(candidate.source_papers)
    if missing:
        problems.append(
            f"papers {sorted(missing)} appear in source_evidence but not in source_papers"
        )

    return problems


def _collect_rejected_norms(rejected: Optional[List[Union[CrossComparisonCandidate, Dict, str]]]) -> List[str]:
    """재탐색 루프에서 넘어온 '이미 기각된 후보'들을 정규화된 gap_statement 문자열 집합으로 변환.
    후보 객체 / dict / 순수 문자열 어느 형태로 넘겨도 받아준다."""
    if not rejected:
        return []
    norms: List[str] = []
    for r in rejected:
        if isinstance(r, CrossComparisonCandidate):
            norms.append(_normalize(r.gap_statement))
        elif isinstance(r, dict):
            gs = r.get("gap_statement", "")
            if gs:
                norms.append(_normalize(gs))
        elif isinstance(r, str):
            norms.append(_normalize(r))
    return norms


def validate_cross_comparison(
    raw_text: str,
    evidence_pool: Dict,
    rejected: Optional[List[Union[CrossComparisonCandidate, Dict, str]]] = None,
) -> Tuple[List[CrossComparisonCandidate], List[str], Optional[str]]:
    """
    생성 에이전트의 원문 출력을 정적 검증한다.

    Returns: (validated_candidates, warnings, error)
      - error is not None  → 하드 실패(JSON/최상위 스키마 붕괴). 상위에서 생성 재시도.
      - error is None      → 사용 가능한 후보 리스트를 얻음(일부가 드롭됐어도 정상). warnings에 드롭 사유.
    """
    import json

    warnings: List[str] = []

    # [하드 실패 1] 코드펜스 제거 후 JSON 파싱
    text = strip_code_fence(raw_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], warnings, f"Invalid JSON: {e}"

    # [하드 실패 2] 최상위는 {"candidates": [...]} 형태여야 함
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return [], warnings, 'Top-level schema invalid: expected a JSON object with a "candidates" list'

    raw_candidates = data["candidates"]
    if not raw_candidates:
        return [], warnings, 'No candidates produced ("candidates" list is empty)'

    rejected_norms = _collect_rejected_norms(rejected)

    validated: List[CrossComparisonCandidate] = []
    seen_ids = set()
    for i, raw in enumerate(raw_candidates):
        # 후보 단위 스키마 검증 — 실패는 그 후보만 드롭
        try:
            cand = CrossComparisonCandidate.model_validate(raw)
        except ValidationError as e:
            warnings.append(f"[DROP] candidate#{i}: schema validation failed — {format_pydantic_errors(e)}")
            continue
        if raw.get("source_type") not in SOURCE_TYPES:
            # Literal이 이미 잡지만, 방어적으로 명시 로그
            warnings.append(f"[DROP] candidate#{i}: invalid source_type")
            continue

        # candidate_id 배치 내 중복 제거(재탐색으로 라운드가 합쳐질 때 재부여는 flow 몫, 배치 내에선 유일해야)
        if cand.candidate_id in seen_ids:
            warnings.append(f"[DROP] candidate#{i}: duplicate candidate_id {cand.candidate_id!r}")
            continue

        # grounding-by-reference — 핵심 방어
        problems = _check_evidence_refs(cand, evidence_pool)
        if problems:
            warnings.append(f"[DROP] {cand.candidate_id}: grounding failed — {'; '.join(problems)}")
            continue

        # 기각목록 필터(재탐색 루프): 이미 기각된 후보와 실질적으로 같으면 드롭
        norm = _normalize(cand.gap_statement)
        if any(norm == rn or norm in rn or rn in norm for rn in rejected_norms):
            warnings.append(f"[DROP] {cand.candidate_id}: matches an already-rejected candidate")
            continue

        seen_ids.add(cand.candidate_id)
        validated.append(cand)

    # 중복 제거: 정규화된 gap_statement가 이미 채택된 후보의 부분집합/상위집합이면 드롭(더 긴 쪽 유지)
    deduped: List[CrossComparisonCandidate] = []
    kept_norms: List[str] = []
    for cand in sorted(validated, key=lambda c: len(c.gap_statement), reverse=True):
        norm = _normalize(cand.gap_statement)
        if any(norm in kept or kept in norm for kept in kept_norms):
            warnings.append(f"[DEDUP] dropped near-duplicate {cand.candidate_id}: {cand.gap_statement[:80]!r}")
            continue
        kept_norms.append(norm)
        deduped.append(cand)

    # 원래 후보 순서(candidate_id 기준) 복원 — dedup 정렬 때문에 섞였으므로
    deduped.sort(key=lambda c: c.candidate_id)

    # soft warning들 (하드 실패 아님)
    if len(deduped) < MIN_CANDIDATES_WARN:
        warnings.append(
            f"[WARN] only {len(deduped)} candidate(s) survived static checks "
            f"(over-generation target ≥ {MIN_CANDIDATES_WARN}) — the re-search loop may need to run"
        )
    if not deduped:
        warnings.append(
            "[WARN] no candidate survived static validation — check generation output / evidence refs"
        )

    return deduped, warnings, None


def _rejected_display_texts(rejected) -> List[str]:
    """기각목록을 프롬프트에 사람이 읽을 수 있게 넣기 위한 원문 gap_statement 추출(정규화 안 함)."""
    if not rejected:
        return []
    texts: List[str] = []
    for r in rejected:
        if isinstance(r, CrossComparisonCandidate):
            texts.append(r.gap_statement)
        elif isinstance(r, dict):
            if r.get("gap_statement"):
                texts.append(r["gap_statement"])
        elif isinstance(r, str):
            texts.append(r)
    return texts


async def run_cross_comparison_with_retry(
    agent_module,
    evidence_pool: Dict,
    context_variables: Dict,
    rejected: Optional[List[Union[CrossComparisonCandidate, Dict, str]]] = None,
    max_retries: int = 2,
    iter_prefix: str = "gen",
) -> Tuple[List[CrossComparisonCandidate], List[str], Dict, Optional[str]]:
    """생성 에이전트(cross_comparison_agent)를 호출하고 step3 정적검증을 통과할 때까지 재시도한다.
    하드실패(JSON/스키마 붕괴)이거나 생존 후보가 0개면, 그 사유(+드롭 로그)를 다음 턴 피드백으로 넣어
    같은 대화 맥락에서 자가수정을 유도한다 — goal_decomposition_validation의 재시도 루프와 같은 철학.

    주의: "생존 후보가 목표(8~10)보다 적지만 1개 이상"인 경우는 여기서 실패로 보지 않는다(성공 반환).
    그 부족분은 CoT3+CoT4를 감싸는 flow 레벨 재탐색 루프가 rejected 주입으로 처리한다.

    Returns: (validated_candidates, warnings, context_variables, error)
      error is not None → max_retries를 소진해도 유효 후보를 못 뽑음(상위에서 처리).
    """
    input_block = format_cross_comparison_input(evidence_pool)

    query = input_block + "\n\n"
    rej_texts = _rejected_display_texts(rejected)
    if rej_texts:
        query += (
            "The following gaps were ALREADY REJECTED in earlier rounds — do NOT re-emit them or "
            "trivial rephrasings; produce genuinely additional gaps instead:\n"
        )
        for t in rej_texts:
            query += f"  - {t}\n"
        query += "\n"
    query += "Now produce your JSON object of candidates, following your instructions exactly."

    messages: List[Dict] = [{"role": "user", "content": query}]
    last_error = "unknown error"
    last_warnings: List[str] = []

    for attempt in range(max_retries + 1):
        iter_tag = iter_prefix if attempt == 0 else f"{iter_prefix}_retry{attempt}"
        messages, context_variables = await agent_module(messages, context_variables, iter_times=iter_tag)

        # assistant의 마지막 실질 응답만 파싱(중간 tool 결과 등을 잘못 집지 않도록 role 확인)
        raw_output = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "assistant" and m.get("content")),
            None,
        )
        if not raw_output:
            last_error = "you ended your turn without returning the final JSON object"
            last_warnings = []
        else:
            validated, warnings, error = validate_cross_comparison(raw_output, evidence_pool, rejected=rejected)
            last_warnings = warnings
            if error is None and validated:
                return validated, warnings, context_variables, None
            last_error = error or "all generated candidates were dropped by static checks"

        if attempt < max_retries:
            feedback = f"Your previous output failed static validation: {last_error}\n"
            drops = [w for w in last_warnings if w.startswith("[DROP]") or w.startswith("[DEDUP]")]
            if drops:
                feedback += "Dropped candidates and reasons:\n" + "\n".join(f"  {d}" for d in drops) + "\n"
            feedback += (
                "Return ONLY a corrected JSON object. Cite ONLY the P/G/L ids that appear in the "
                "input block above, list in source_papers exactly the papers referenced in "
                "source_evidence, and make each candidate distinct."
            )
            messages.append({"role": "user", "content": feedback})

    return [], last_warnings, context_variables, f"failed after {max_retries + 1} attempts — {last_error}"
