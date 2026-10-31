"""Stage 2: evidence.json → plan.json (LLM).

필드 묶음(problem → method → validation)마다 LLM을 한 번씩 부르고, 합친 결과를 검사한다.
검사에 걸리면 오류가 난 묶음만 오류 목록과 함께 다시 쓰게 한다(최대 max_rounds회).
novelty_search_scope는 CoT5 검색 상태를 그대로 옮기며 LLM이 쓰지 않는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from .provider import LLMProvider
from .schemas import FIELD_GROUPS, SCHEMA_VERSION, strict_group_schema
from .validate import validate_plan

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = ROOT / "prompts"
FIELD_DEFINITIONS = ROOT / "docs" / "field_definitions.md"

# strict 모드에서 빈 문자열로 받은 선택 속성. plan.json에서는 지운다.
OPTIONAL_PROPS = ("arxiv_id", "source_hint", "source")
GROUP_OF_ID = {"L": "problem", "M": "method"}  # 나머지(B, V, E, C, R, S)는 validation
GROUP_OF_FIELD = {key: group for group, keys in FIELD_GROUPS.items() for key in keys}


def field_guidance(keys: list[str]) -> str:
    """field_definitions.md 표에서 이 묶음의 행만 뽑는다. 필드 정의의 원본은 그 문서 하나다."""
    lines = FIELD_DEFINITIONS.read_text(encoding="utf-8").splitlines()
    header = [line for line in lines if line.startswith("| # |") or line.startswith("|---")][:2]
    rows = [line for line in lines if any(f"| `{key}` |" in line for key in keys)]
    return "\n".join(["## 필드 정의와 좋은 값의 기준", "", *header, *rows])


def build_instructions(group: str) -> str:
    parts = [
        (PROMPTS / "system.md").read_text(encoding="utf-8"),
        field_guidance(FIELD_GROUPS[group]),
        (PROMPTS / f"{group}.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(part.strip() for part in parts) + "\n"


def compact_evidence(evidence: dict) -> dict:
    """LLM에 넣을 evidence. 입력 파일 해시는 내용 판단에 필요 없으므로 뺀다."""
    compact = {k: v for k, v in evidence.items() if k != "meta"}
    compact["meta"] = {k: v for k, v in evidence["meta"].items() if k != "input_files"}
    return compact


def build_document(evidence: dict, group: str, previous: dict, fix_errors: list[str] | None,
                   previous_attempt: dict | None, keep_unchanged: list[str] | None = None) -> str:
    payload = {
        "task": f"{group} 묶음의 필드 {FIELD_GROUPS[group]}를 채운다.",
        "evidence": compact_evidence(evidence),
        "previous_groups": previous,
    }
    if fix_errors:
        payload["fix_errors"] = fix_errors
        payload["previous_attempt"] = previous_attempt
    if keep_unchanged:
        payload["keep_unchanged"] = keep_unchanged
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _walk_sources(obj, out: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "source" and isinstance(value, str):
                out.add(value)
            else:
                _walk_sources(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _walk_sources(value, out)
    return out


def known_sources(evidence: dict) -> set[str]:
    sources = _walk_sources(evidence, set())
    sources |= {f"seed:{p['arxiv_id']}" for p in evidence.get("papers", []) if p.get("arxiv_id")}
    return sources


def _source_exists(path: str, known: set[str]) -> bool:
    # 상위 경로(cot4.requirements.implementation_steps), 묶음 경로(cot5.paper),
    # 항목 안의 세부 필드(cot5.paper.candidates[0].critical_difference)도 허용한다.
    return path in known or any(
        k.startswith(path + ".") or k.startswith(path + "[") or path.startswith(k + ".") for k in known
    )


def check_sources(fields: dict, known: set[str]) -> list[str]:
    """validate.py는 접두어만 본다. 여기서는 evidence에 실제로 있는 경로인지 확인한다."""
    errors = []
    for key, wrapper in fields.items():
        paths = list(wrapper.get("source", []))
        if isinstance(wrapper.get("value"), list):
            for item in wrapper["value"]:
                if isinstance(item, dict):
                    paths += [item[p] for p in ("source", "source_hint") if item.get(p)]
        for path in paths:
            if not _source_exists(path, known):
                errors.append(f"{key}: evidence에 없는 근거 경로 {path!r}")
    return errors


PAPER_LABEL = re.compile(r"(?<![A-Za-z0-9.])P\d+(?![A-Za-z0-9])")


def _texts(obj, skip=("source", "source_hint")):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key not in skip:
                yield from _texts(value, skip)
    elif isinstance(obj, list):
        for value in obj:
            yield from _texts(value, skip)


def check_paper_labels(fields: dict) -> list[str]:
    """CoT3 내부 표기(P1, P2)가 본문에 남으면 계획서에서 무슨 논문인지 알 수 없다."""
    errors = []
    for key, wrapper in fields.items():
        labels = sorted({m for text in _texts(wrapper.get("value")) for m in PAPER_LABEL.findall(text)})
        if labels:
            errors.append(f"{key}: 내부 논문 표기 {', '.join(labels)} 사용. 논문 이름과 arXiv ID로 바꿀 것")
    return errors


def clean_group(raw: dict, group: str) -> dict:
    """묶음 키만 남기고, 빈 선택 속성을 지운다."""
    out = {}
    for key in FIELD_GROUPS[group]:
        if key not in raw:
            continue
        wrapper = dict(raw[key])
        if isinstance(wrapper.get("value"), list):
            wrapper["value"] = [
                {k: v for k, v in item.items() if not (k in OPTIONAL_PROPS and v == "")}
                if isinstance(item, dict) else item
                for item in wrapper["value"]
            ]
        out[key] = wrapper
    return out


def search_scope(evidence: dict) -> dict:
    novelty = evidence["novelty"]
    status = {
        name: {
            "status": s.get("status"),
            "checked_count": int(s["checked_count"]) if str(s.get("checked_count", "")).isdigit() else None,
            "error": s.get("error"),
        }
        for name, s in novelty["search_status"].items()
    }
    parts = []
    for name, label in (("paper", "논문"), ("web", "웹"), ("patent", "특허")):
        s = status.get(name, {})
        if s.get("error"):
            parts.append(f"{label} 검색은 실패해 확인하지 못했다({s['error']})")
        else:
            parts.append(f"{label} 검색은 {s.get('checked_count') or 0}건을 검토했다(결과: {s.get('status')})")
    coverage = novelty.get("coverage")
    statement = (
        f"CoT5 판정 {novelty.get('classification')}은 검색 범위 안의 판단이며 전 세계적 신규성을 증명하지 않는다. "
        + ", ".join(parts) + "."
        + (f" 논문 검색 범위는 {coverage}였다." if coverage and coverage != "complete" else "")
        + " 가장 가까운 선행연구는 이 검색에서 빠졌을 수 있으므로 연구자가 직접 다시 확인해야 한다."
    )
    for name in ("paper", "web", "patent"):
        status.setdefault(name, {"status": "없음", "checked_count": None, "error": None})
    return {
        "value": {**status, "statement": statement},
        "source": sorted(s["source"] for s in novelty["search_status"].values()),
        "inferred": False,
    }


def assemble(evidence: dict, outputs: dict, model: str) -> dict:
    meta = evidence["meta"]
    fields = {}
    for group in FIELD_GROUPS:
        fields.update(outputs.get(group, {}))
    fields["novelty_search_scope"] = search_scope(evidence)
    evidence_bytes = json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "run_id": meta["run_id"],
            "candidate_index": meta["candidate_index"],
            "cot3_candidate_id": meta.get("cot3_candidate_id"),
            "idea_title": meta["title"],
            "cot5_classification": meta["cot5_classification"],
            "generated_by": f"llm:{model}",
            "language": "ko",
            "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        },
        "citation_whitelist": evidence["citation_whitelist"],
        "fields": fields,
    }


def groups_for_error(error: str, outputs: dict) -> set[str]:
    """오류 메시지를 고쳐야 할 묶음으로 보낸다."""
    cite = re.search(r"화이트리스트에 없는 인용 (\S+)", error)
    if cite:
        found = {g for g, out in outputs.items() if cite.group(1) in json.dumps(out, ensure_ascii=False)}
        return found or {"validation"}
    if "검증 대상(V)에서도" in error:  # M이 어떤 V에도 없음 → V를 쓰는 쪽이 고친다
        return {"validation"}
    match = re.match(r"([a-z_]+):", error)
    if match and match.group(1) in GROUP_OF_FIELD:
        return {GROUP_OF_FIELD[match.group(1)]}
    match = re.match(r"([A-Z])\d+:", error)
    if match:
        return {GROUP_OF_ID.get(match.group(1), "validation")}
    return {"validation"}


def rule_errors(plan: dict, evidence: dict) -> list[str]:
    """LLM 없이 하는 검사 전체: 0단계 검증기 + 근거 경로 실재 + 내부 논문 표기."""
    fields = plan["fields"]
    return validate_plan(plan) + check_sources(fields, known_sources(evidence)) + check_paper_labels(fields)


def plan_outputs(plan: dict) -> dict[str, dict]:
    """plan.json의 fields를 묶음별 출력으로 되돌린다(3단계에서 일부 묶음만 다시 쓸 때)."""
    return {g: {k: plan["fields"][k] for k in keys if k in plan["fields"]} for g, keys in FIELD_GROUPS.items()}


def extract_plan(
    evidence: dict,
    provider: LLMProvider,
    *,
    max_rounds: int = 3,
    start: dict[str, dict] | None = None,
    fixes: dict[str, list[str]] | None = None,
    locked: dict[str, dict] | None = None,
) -> tuple[dict, dict, bool]:
    """(plan, log, 통과 여부)를 돌려준다.

    start와 fixes를 주면 처음부터 쓰지 않고, start의 묶음 중 fixes에 있는 묶음만 지적 사항과 함께 다시 쓴다.
    locked의 필드는 다시 쓴 묶음 안에 있어도 원래 값으로 되돌린다(지적받지 않은 필드가 바뀌어 나빠지는 것을 막는다).
    """
    locked = locked or {}
    outputs: dict[str, dict] = dict(start or {})
    errors_by_group: dict[str, list[str]] = dict(fixes or {})
    pending = [g for g in FIELD_GROUPS if g in errors_by_group] if start else list(FIELD_GROUPS)
    log = {
        "model": provider.model,
        "max_rounds": max_rounds,
        "prompt_sha256": {
            g: hashlib.sha256(build_instructions(g).encode("utf-8")).hexdigest() for g in FIELD_GROUPS
        },
        "rounds": [],
    }
    plan: dict = {}
    for round_no in range(1, max_rounds + 1):
        for group in pending:
            previous = {g: outputs[g] for g in FIELD_GROUPS if g != group and g in outputs}
            keep = [k for k in FIELD_GROUPS[group] if k in locked]
            raw = provider.evaluate(
                instructions=build_instructions(group),
                document=build_document(
                    evidence, group, previous, errors_by_group.get(group), outputs.get(group), keep
                ),
                schema=strict_group_schema(group),
                schema_name=f"plan_{group}",
            )
            outputs[group] = clean_group(raw, group)
            outputs[group].update({k: copy.deepcopy(locked[k]) for k in keep})
        plan = assemble(evidence, outputs, provider.model)
        errors = rule_errors(plan, evidence)
        log["rounds"].append({"round": round_no, "regenerated": pending, "errors": errors})
        if not errors:
            return plan, log, True
        errors_by_group = {}
        for error in errors:
            for group in groups_for_error(error, outputs):
                errors_by_group.setdefault(group, []).append(error)
        pending = [g for g in FIELD_GROUPS if g in errors_by_group]
    return plan, log, False
