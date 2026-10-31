"""Stage 4: plan(심사 통과본) → research_plan.md, paper_skeleton.md.

plan에만 근거한다(evidence는 LLM에 주지 않는다). 새 내용이 끼어드는 것을 막기 위해서다.
- 표와 목록(L, M, 데이터, V, B, Design Table, C, R, S, 신규성 검증 범위)은 코드가 plan에서 그대로 옮긴다.
- LLM은 연구계획서의 연결 문단 3개와 논문의 틀(제목, 구조화 초록, 장별 개요, 그림·표 계획, 기여 문장)만 쓴다.
- 렌더링한 문서를 validate.py의 Markdown 검사(고정 제목, 결과 단정 표현, 인용 범위)와 ID·표기 검사로 확인하고,
  LLM이 쓴 부분에 문제가 있으면 오류를 붙여 그 부분만 다시 쓴다(최대 max_rounds회).
"""

from __future__ import annotations

import hashlib
import json
import re

from .extract import PROMPTS, PAPER_LABEL
from .provider import LLMProvider
from .schemas import FIELD_KEYS, ID_PREFIXES
from .validate import validate_markdown, validate_paper_skeleton, validate_research_plan

OUTLINE_HEADINGS = [
    "1 Introduction",
    "2 Related Work",
    "3 Method",
    "4 Experimental Setup",
    "5 Results",
    "6 Analysis",
    "7 Limitations",
    "8 Conclusion",
]
ABSTRACT_KEYS = [
    ("background", "Background"),
    ("gap", "Gap"),
    ("method", "Method"),
    ("planned_evaluation", "Planned Evaluation"),
    ("expected_contribution", "Expected Contribution"),
]
CONTRIBUTION_LABELS = {"method": "방법", "resource": "자원", "analysis": "분석", "other": "기타"}
SCOPE_LABELS = [("paper", "논문"), ("web", "웹"), ("patent", "특허")]
ID_REF = re.compile(r"(?<![A-Za-z0-9])([LMBVECRS])(\d+)(?![A-Za-z0-9])")

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}


def _obj(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


PROSE_SCHEMA = _obj({"short_title": _STR, "overview": _STR, "current_approach": _STR, "method_overview": _STR})
SKELETON_SCHEMA = _obj({
    "titles": _STR_LIST,
    "abstract": _obj({key: _STR for key, _ in ABSTRACT_KEYS}),
    "outline": {"type": "array", "items": _obj({"heading": _STR, "items": _STR_LIST})},
    "figures": {"type": "array", "items": _obj({"label": _STR, "content": _STR, "basis": _STR})},
    "contributions": _STR_LIST,
})
PARTS = {
    # 이름: (프롬프트 파일, 스키마)
    "research_plan": ("write_plan.md", PROSE_SCHEMA),
    "paper_skeleton": ("write_skeleton.md", SKELETON_SCHEMA),
}


class WriteError(RuntimeError):
    pass


# ---------- 렌더링 (LLM 없음) ----------

def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _value(plan: dict, key: str):
    return plan["fields"][key]["value"]


def _cite(ids) -> str:
    ids = [i for i in ids if i]
    return f" [{'; '.join(ids)}]" if ids else ""


def _header(plan: dict, kind: str, short_title: str) -> list[str]:
    meta = plan["meta"]
    lines = [
        f"# {kind}: {short_title.strip()}",
        "",
        f"> run `{meta['run_id']}` · candidate {meta['candidate_index']} · "
        f"CoT5 판정 {meta['cot5_classification']} (검색 범위 한정, 부록 참고)",
    ]
    review = meta.get("review")
    if review:
        lines.append(
            f"> 작성 `{meta.get('generated_by', '')}` · 3단계 심사 {review['status']} "
            f"(평균 {review['mean_score']}, 판정 `{review['judge_model']}`)"
        )
    else:
        lines.append("> 3단계 심사를 거치지 않은 plan으로 작성했다.")
    return lines


def render_research_plan(plan: dict, prose: dict) -> str:
    v = lambda key: _value(plan, key)  # noqa: E731
    out = _header(plan, "연구계획서", prose["short_title"])
    out += ["", "## 0. 개요", "", f"**연구 주제.** {v('research_topic')}", "", prose["overview"].strip(), ""]

    out += ["## 1. Proposed Method", "", "### 1.1 문제 정의 및 연구 배경", ""]
    out += [f"**현재 방식.** {prose['current_approach'].strip()}", "", "**한계.**"]
    out += [f"- {lim['id']}. {lim['text']}{_cite(lim.get('cites', []))}" for lim in v("limitations_of_existing_approaches")]
    out += ["", f"**연구 질문.** {v('research_problem')}", "", f"**연구 목표.** {v('research_objective')}", ""]

    out += ["### 1.2 제안 방법", "", prose["method_overview"].strip(), ""]
    for n, comp in enumerate(v("method_components"), 1):
        addresses = ", ".join(comp.get("addresses", []))
        out += [f"#### 1.2.{n} {comp['id']}: {comp['name']}", "", f"{comp['description']} ({addresses} 대응)", ""]
    out += ["#### 구성요소 관계", ""]
    out += [f"- {rel['from']} → {rel['to']}: {rel['relation']}" for rel in v("component_relations")]
    out += ["", "### 1.3 연구 대상 및 데이터", "", "| 데이터 | 용도 | 상태 |", "|---|---|---|"]
    out += [f"| {_cell(d['name'])} | {_cell(d['use'])} | {_cell(d['status'])} |" for d in v("data_and_subjects")]

    out += ["", "## 2. Validation & Target Claims", "", "### 2.1 Experimental Validation Plan", "", "**검증 대상**"]
    out += [f"- {t['id']}. {t['question']} ({', '.join(t['components'])})" for t in v("validation_targets")]
    out += ["", "**비교 대상**"]
    out += [f"- {b['id']}. {b['name']}{_cite([b.get('arxiv_id', '')])} — {b['why']}" for b in v("baselines")]
    out += ["", "**Design Table**", "", "| ID | 검증 대상 | 설정 | 지표 | Baseline | 성공 기준 | 실패 시 해석 |",
            "|---|---|---|---|---|---|---|"]
    out += [
        f"| {e['id']} | {', '.join(e['validates'])} | {_cell(e['setup'])} | {_cell('; '.join(e['metrics']))} | "
        f"{', '.join(e['baselines'])} | {_cell(e['success_criterion'])} | {_cell(e['failure_interpretation'])} |"
        for e in v("experimental_design")
    ]

    out += ["", "### 2.2 Target Claims", ""]
    for c in v("target_claims"):
        out += [f"- **{c['id']}.** {c['claim']}", f"  - 반증 조건: {c['falsifiable_condition']}",
                f"  - 검증: {', '.join(c['validated_by'])}"]

    out += ["", "### 2.3 Expected Novelty & Contribution", "", "**신규성**"]
    for n in v("expected_novelty"):
        out.append(f"- {n['text']}{_cite(n.get('vs', []))}")
        if n.get("existing_mechanism"):
            out.append(f"  - 기존 장치: {n['existing_mechanism']} · 차이: {n.get('difference_axis', '')} · "
                       f"검증: {', '.join(n.get('tested_by', []))}")
    out += ["", "**기여**"]
    out += [f"- **{CONTRIBUTION_LABELS.get(c['type'], c['type'])}.** {c['text']}" for c in v("expected_contribution")]

    out += ["", "### 2.4 위험 요소와 대응", "", "| ID | 위험 | 대응 |", "|---|---|---|"]
    out += [f"| {r['id']} | {_cell(r['risk'])} | {_cell(r['fallback'])} |" for r in v("risks_and_fallbacks")]
    out += ["", "### 2.5 마일스톤", "", "| ID | 점검 | 기준 |", "|---|---|---|"]
    out += [f"| {s['id']} | {_cell(s['milestone'])} | {_cell(s['criterion'])} |" for s in v("success_criteria_milestones")]

    scope = v("novelty_search_scope")
    out += ["", "## 부록. 신규성 검증 범위", "", "| 소스 | 상태 | 검토 건수 | 비고 |", "|---|---|---|---|"]
    for key, label in SCOPE_LABELS:
        s = scope.get(key, {})
        count = s.get("checked_count")
        out.append(f"| {label} | {_cell(s.get('status', '-'))} | {'-' if count is None else count} | "
                   f"{_cell(s.get('error') or '-')} |")
    out += ["", scope["statement"], ""]
    return "\n".join(out)


def render_paper_skeleton(plan: dict, sk: dict, short_title: str) -> str:
    out = _header(plan, "논문의 틀", short_title)
    out.append("> 실험 전 단계의 틀이다. 결과 자리는 모두 `[RESULT: ...]`로 비워 두었다.")
    out += ["", "## 1. Title candidates", ""]
    out += [f"{n}. {t}" for n, t in enumerate(sk["titles"], 1)]
    out += ["", "## 2. Structured Abstract", ""]
    out += [f"- **{label}:** {sk['abstract'][key].strip()}" for key, label in ABSTRACT_KEYS]
    out += ["", "## 3. Section outline", ""]
    for section in sk["outline"]:
        out += [f"### {section['heading']}", ""] + [f"- {item}" for item in section["items"]] + [""]
    out += ["## 4. Figures & Tables plan", "", "| 번호 | 내용 | 근거 |", "|---|---|---|"]
    out += [f"| {_cell(f['label'])} | {_cell(f['content'])} | {_cell(f['basis'])} |" for f in sk["figures"]]
    out += ["", "## 5. Contribution bullets", ""]
    out += [f"- {c}" for c in sk["contributions"]]
    return "\n".join(out) + "\n"


# ---------- 검사 ----------

def plan_ids(plan: dict) -> set[str]:
    ids = set()
    for key in ID_PREFIXES:
        ids |= {item["id"] for item in plan["fields"][key]["value"] if isinstance(item, dict) and "id" in item}
    return ids


def _texts(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _texts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _texts(value)


def check_llm_output(raw: dict, plan: dict) -> list[str]:
    """LLM이 쓴 부분만 보는 검사: 없는 ID 참조, 내부 논문 표기."""
    known = plan_ids(plan)
    errors = []
    for text in _texts(raw):
        for prefix, number in ID_REF.findall(text):
            if f"{prefix}{number}" not in known:
                errors.append(f"plan에 없는 ID {prefix}{number} 참조: {text[:60]!r}")
        for label in PAPER_LABEL.findall(text):
            errors.append(f"내부 논문 표기 {label} 사용: {text[:60]!r}")
    return sorted(set(errors))


RESULT_SLOT = re.compile(r"\[RESULT:[^\]]*\]")
FIELD_NAME = re.compile(r"\b(" + "|".join(sorted(FIELD_KEYS, key=len, reverse=True)) + r")\b")


def check_short_title(title: str) -> list[str]:
    title = title.strip()
    errors = []
    if not 4 <= len(title) <= 40:
        errors.append(f"short_title은 4~40자여야 함 (현재 {len(title)}자): {title!r}")
    if title.endswith(("다", "다.", ".")):
        errors.append(f"short_title은 문장이 아니라 명사구여야 함: {title!r}")
    return errors


def check_reader_text(texts: dict[str, str], *, allow_ids: bool) -> list[str]:
    """독자가 그대로 읽는 문장(제목, 초록, 기여, 계획서 문단)에 내부 표기가 새지 않았는지.

    필드 이름(expected_contribution 등)은 어디에도 쓰지 않는다. 논문의 틀 개요의 "근거:"는 이 검사 대상이 아니다.
    allow_ids가 False면 [RESULT: ...] 밖의 내부 ID(L1, E2 등)도 쓰지 않는다. 논문 초록과 제목에는 내부 ID가 없다.
    """
    errors = []
    for where, text in texts.items():
        visible = RESULT_SLOT.sub("", text)
        for name in sorted(set(FIELD_NAME.findall(visible))):
            errors.append(f"{where}: 필드 이름 {name}이 문장에 그대로 나옴. 자연어로 바꿀 것")
        if not allow_ids:
            ids = sorted({p + n for p, n in ID_REF.findall(visible)})
            if ids:
                errors.append(f"{where}: 내부 ID {', '.join(ids)} 사용. [RESULT: ...] 밖에서는 자연어로 쓸 것")
    return errors


def check_skeleton_structure(sk: dict) -> list[str]:
    errors = []
    if not 2 <= len(sk["titles"]) <= 3:
        errors.append(f"titles는 2~3개여야 함 (현재 {len(sk['titles'])}개)")
    headings = [s["heading"].strip() for s in sk["outline"]]
    if headings != OUTLINE_HEADINGS:
        errors.append(f"outline 장 제목은 정확히 {OUTLINE_HEADINGS} 순서여야 함 (현재 {headings})")
    if "[RESULT:" not in sk["abstract"]["planned_evaluation"]:
        errors.append("abstract.planned_evaluation에 [RESULT: En 지표] 자리표시자가 없음")
    results = next((s for s in sk["outline"] if s["heading"].strip() == "5 Results"), None)
    if results and not all("[RESULT:" in item for item in results["items"]):
        errors.append("5 Results의 모든 항목에 [RESULT: ...] 자리표시자가 있어야 함")
    if not 3 <= len(sk["figures"]) <= 6:
        errors.append(f"figures는 3~6개여야 함 (현재 {len(sk['figures'])}개)")
    if not 2 <= len(sk["contributions"]) <= 4:
        errors.append(f"contributions는 2~4개여야 함 (현재 {len(sk['contributions'])}개)")
    return errors


def _whitelist(plan: dict) -> set[str]:
    return {w["arxiv_id"] for w in plan.get("citation_whitelist", [])}


_EMPTY_PROSE = {"short_title": "-", "overview": "-", "current_approach": "-", "method_overview": "-"}


def plan_content_errors(plan: dict) -> list[str]:
    """LLM 문단 없이 plan만 렌더링했을 때의 문제. LLM이 고칠 수 없으므로 사람이 plan을 고쳐야 한다."""
    return validate_research_plan(render_research_plan(plan, _EMPTY_PROSE), _whitelist(plan))


def validate_markdown_text(raw: dict, whitelist: set[str]) -> list[str]:
    """렌더링하지 못한 출력도 결과 단정 표현과 인용 범위는 검사한다."""
    return validate_markdown("\n".join(_texts(raw)), [], whitelist)


def _render_and_check(part: str, raw: dict, plan: dict, ignore: set[str], short_title: str) -> tuple[str, list[str]]:
    whitelist = _whitelist(plan)
    errors = check_llm_output(raw, plan)
    if part == "research_plan":
        errors += check_short_title(raw["short_title"])
        errors += check_reader_text({k: v for k, v in raw.items()}, allow_ids=True)
        text = render_research_plan(plan, raw)
        errors += [e for e in validate_research_plan(text, whitelist) if e not in ignore]
    else:
        structure = check_skeleton_structure(raw)
        reader = {f"titles[{i}]": t for i, t in enumerate(raw["titles"])}
        reader |= {f"abstract.{k}": v for k, v in raw["abstract"].items()}
        reader |= {f"contributions[{i}]": c for i, c in enumerate(raw["contributions"])}
        errors += structure + check_reader_text(reader, allow_ids=False)
        # 장 구성이 틀리면 고정 제목 검사가 의미 없으므로 렌더링하지 않는다. 인용·단정 표현은 그래도 본다.
        text = "" if structure else render_paper_skeleton(plan, raw, short_title)
        errors += validate_paper_skeleton(text, whitelist) if text else validate_markdown_text(raw, whitelist)
    return text, errors


def build_document(plan: dict, fix_errors: list[str] | None, previous_attempt: dict | None) -> str:
    payload = {
        "plan_meta": {k: plan["meta"].get(k) for k in ("idea_title", "candidate_index", "cot5_classification")},
        "plan_fields": plan["fields"],
        "citation_whitelist": plan.get("citation_whitelist", []),
    }
    if fix_errors:
        payload["fix_errors"] = fix_errors
        payload["previous_attempt"] = previous_attempt
    return json.dumps(payload, ensure_ascii=False, indent=1)


def write_documents(plan: dict, provider: LLMProvider, *, max_rounds: int = 3) -> tuple[dict, dict, bool]:
    """({파일 이름: 내용}, log, 통과 여부)를 돌려준다."""
    plan_errors = plan_content_errors(plan)
    log = {
        "model": provider.model,
        "prompt_sha256": {
            part: hashlib.sha256((PROMPTS / prompt).read_bytes()).hexdigest() for part, (prompt, _) in PARTS.items()
        },
        "plan_content_errors": plan_errors,
        "parts": {},
    }
    docs: dict[str, str] = {}
    ok = not plan_errors
    short_title = _value(plan, "research_topic")  # 연구계획서 쪽에서 짧은 제목을 받으면 바뀐다
    for part, (prompt, schema) in PARTS.items():
        instructions = (PROMPTS / prompt).read_text(encoding="utf-8")
        raw, errors, rounds = None, None, []
        for round_no in range(1, max_rounds + 1):
            raw = provider.evaluate(
                instructions=instructions,
                document=build_document(plan, errors, raw),
                schema=schema,
                schema_name=part,
            )
            text, errors = _render_and_check(part, raw, plan, set(plan_errors), short_title)
            rounds.append({"round": round_no, "errors": errors})
            if not errors:
                break
        if part == "research_plan" and not check_short_title(raw["short_title"]):
            short_title = raw["short_title"].strip()  # 두 문서의 제목을 같게 맞춘다
        log["parts"][part] = {"rounds": rounds, "passed": not errors}
        ok = ok and not errors
        if text:  # 논문의 틀은 구조 검사를 못 넘으면 렌더링하지 않는다
            docs[f"{part}.md"] = text
    return docs, log, ok
