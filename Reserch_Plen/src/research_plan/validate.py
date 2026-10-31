"""plan.json과 Markdown 산출물의 규칙 검사 (docs/output_spec.md 3절·6절).

외부 의존성 없이 동작한다. JSON Schema 전체 검증이 아니라, 명세의 필수 규칙과
ID 연결 규칙을 직접 검사한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .schemas import DIFFERENCE_AXES, FIELD_KEYS, ID_PREFIXES, SCHEMA_VERSION, SOURCE_PREFIXES, TEXT_FIELDS

PLAN_HEADINGS = [
    "## 0. 개요",
    "## 1. Proposed Method",
    "### 1.1 문제 정의 및 연구 배경",
    "### 1.2 제안 방법",
    "### 1.3 연구 대상 및 데이터",
    "## 2. Validation & Target Claims",
    "### 2.1 Experimental Validation Plan",
    "### 2.2 Target Claims",
    "### 2.3 Expected Novelty & Contribution",
    "### 2.4 위험 요소와 대응",
    "### 2.5 마일스톤",
    "## 부록. 신규성 검증 범위",
]

SKELETON_HEADINGS = [
    "## 1. Title candidates",
    "## 2. Structured Abstract",
    "## 3. Section outline",
    "## 4. Figures & Tables plan",
    "## 5. Contribution bullets",
]

DESIGN_TABLE_HEADER = "| ID | 검증 대상 | 설정 | 지표 | Baseline | 성공 기준 | 실패 시 해석 |"

ABSTRACT_PARTS = ["Background", "Gap", "Method", "Planned Evaluation", "Expected Contribution"]

# 실험이 끝난 것처럼 단정하는 표현.
FORBIDDEN_PATTERNS = [
    r"\bachiev(?:es|ed)\b",
    r"\boutperform(?:s|ed)\b",
    r"\bwe show that\b",
    r"\bwe demonstrate\b",
    r"\bdemonstrates that\b",
    r"달성했다",
    r"입증했다",
    r"입증되었다",
    r"향상되었다",
    r"향상시켰다",
    # 5단계에서 추가: 결과 단정과 근거 없는 최상급 표현
    r"\bwe (?:achieve|outperform)\b",  # "aim to achieve"는 계획이므로 단독 achieve는 막지 않는다
    r"\bstate-of-the-art\b",
    r"\bSOTA\b",
    r"\bsignificantly (?:improves?|improved|outperforms?|outperformed|reduces?|reduced)\b",
    r"\bresults (?:show|showed|demonstrate)\b",
    r"\bwe found\b",
    r"\bfor the first time\b",
    r"증명했다",
    r"증명되었다",
    r"개선되었다",
    r"개선했다",
    r"확인되었다",
    r"보여주었다",
    r"최초로",
]

# 문장 끝 마침표("…2005.11401.")는 허용하고, 더 긴 숫자("2005.11401.3")의 일부는 제외한다.
ARXIV_ID = re.compile(r"(?<![\d.])\d{4}\.\d{4,5}(?!\d|\.\d)")


def _ids(items: list[dict]) -> set[str]:
    return {item["id"] for item in items if isinstance(item, dict) and "id" in item}


def _whitelist(plan: dict) -> set[str]:
    return {entry.get("arxiv_id", "") for entry in plan.get("citation_whitelist", [])}


def validate_plan(plan: dict) -> list[str]:
    """plan.json 규칙 위반 목록을 돌려준다. 빈 목록이면 통과."""
    errors: list[str] = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version은 {SCHEMA_VERSION!r}여야 함")
    fields = plan.get("fields")
    if not isinstance(fields, dict):
        return errors + ["fields가 없음"]

    for key in FIELD_KEYS:
        if key not in fields:
            errors.append(f"{key}: 필드 누락")
    for key in fields:
        if key not in FIELD_KEYS:
            errors.append(f"{key}: 정의되지 않은 필드")
    if errors:
        return errors

    for key in FIELD_KEYS:
        wrapper = fields[key]
        if not isinstance(wrapper, dict) or not {"value", "source", "inferred"} <= wrapper.keys():
            errors.append(f"{key}: value/source/inferred 래퍼가 아님")
            continue
        value, source = wrapper["value"], wrapper["source"]
        if key in TEXT_FIELDS and not (isinstance(value, str) and value.strip()):
            errors.append(f"{key}: 빈 문자열")
        elif key not in TEXT_FIELDS and key != "novelty_search_scope":
            if not isinstance(value, list) or not value:
                errors.append(f"{key}: 비어 있지 않은 목록이어야 함")
        if not source and wrapper["inferred"] is not True:
            errors.append(f"{key}: source가 비어 있으면 inferred=true여야 함")
        for path in source:
            if not path.startswith(SOURCE_PREFIXES):
                errors.append(f"{key}: 허용되지 않은 근거 경로 {path!r}")
        prefix = ID_PREFIXES.get(key)
        if prefix and isinstance(value, list):
            seen: set[str] = set()
            for item in value:
                item_id = item.get("id", "") if isinstance(item, dict) else ""
                if not re.fullmatch(rf"{prefix}\d+", item_id):
                    errors.append(f"{key}: id {item_id!r}는 {prefix}<숫자> 형식이어야 함")
                if item_id in seen:
                    errors.append(f"{key}: 중복 id {item_id}")
                seen.add(item_id)
    if errors:
        return errors

    errors += _check_links(fields)
    errors += _check_citations(plan)
    scope = fields["novelty_search_scope"]["value"]
    for name in ("paper", "web", "patent", "statement"):
        if name not in scope:
            errors.append(f"novelty_search_scope: {name} 누락")
    return errors


def _check_links(fields: dict) -> list[str]:
    """output_spec.md 3절의 연결 규칙 1~6."""
    errors: list[str] = []
    value = lambda key: fields[key]["value"]  # noqa: E731
    limitations = _ids(value("limitations_of_existing_approaches"))
    components = _ids(value("method_components"))
    baselines = _ids(value("baselines"))
    targets = _ids(value("validation_targets"))

    for comp in value("method_components"):
        for ref in comp.get("addresses", []):
            if ref not in limitations:
                errors.append(f"{comp['id']}: 존재하지 않는 한계 {ref} 참조")
    for rel in value("component_relations"):
        for end in ("from", "to"):
            if rel.get(end) not in components:
                errors.append(f"component_relations: 존재하지 않는 구성요소 {rel.get(end)!r}")

    covered_components = set()
    for target in value("validation_targets"):
        for ref in target.get("components", []):
            if ref not in components:
                errors.append(f"{target['id']}: 존재하지 않는 구성요소 {ref} 참조")
            covered_components.add(ref)
    for comp in sorted(components - covered_components):
        errors.append(f"{comp}: 어떤 검증 대상(V)에서도 다뤄지지 않음")

    validated = set()
    for exp in value("experimental_design"):
        for ref in exp.get("validates", []):
            if ref not in targets:
                errors.append(f"{exp['id']}: 존재하지 않는 검증 대상 {ref} 참조")
            validated.add(ref)
        if not exp.get("baselines"):
            errors.append(f"{exp['id']}: baseline이 없음")
        for ref in exp.get("baselines", []):
            if ref not in baselines:
                errors.append(f"{exp['id']}: 존재하지 않는 baseline {ref} 참조")
        for name in ("success_criterion", "failure_interpretation"):
            if not str(exp.get(name, "")).strip():
                errors.append(f"{exp['id']}: {name}가 비어 있음")
    for target in sorted(targets - validated):
        errors.append(f"{target}: 어떤 실험(E)에서도 검증되지 않음")

    for claim in value("target_claims"):
        if not claim.get("validated_by"):
            errors.append(f"{claim['id']}: validated_by가 비어 있음")
        for ref in claim.get("validated_by", []):
            if ref not in targets:
                errors.append(f"{claim['id']}: 존재하지 않는 검증 대상 {ref} 참조")

    experiments = _ids(value("experimental_design"))
    for n, item in enumerate(value("expected_novelty"), 1):
        where = f"expected_novelty[{n - 1}]"
        if not str(item.get("existing_mechanism", "")).strip():
            errors.append(f"{where}: existing_mechanism(비교 대상의 기존 장치)이 비어 있음")
        if item.get("difference_axis") not in DIFFERENCE_AXES:
            errors.append(f"{where}: difference_axis는 {DIFFERENCE_AXES} 중 하나여야 함")
        if not item.get("tested_by"):
            errors.append(f"{where}: tested_by가 비어 있음. 이 차이가 필요한지 가리는 실험(E)을 연결할 것")
        for ref in item.get("tested_by", []):
            if ref not in experiments:
                errors.append(f"{where}: 존재하지 않는 실험 {ref} 참조")
    return errors


def _check_citations(plan: dict) -> list[str]:
    """plan.json 안의 모든 arXiv ID가 화이트리스트에 있는지 검사."""
    allowed = _whitelist(plan)
    text = json.dumps(plan["fields"], ensure_ascii=False)
    return [
        f"화이트리스트에 없는 인용 {arxiv_id}"
        for arxiv_id in sorted(set(ARXIV_ID.findall(text)) - allowed)
    ]


def validate_markdown(text: str, required_headings: list[str], whitelist: set[str]) -> list[str]:
    """Markdown 산출물의 고정 제목, 금지 표현, 인용 범위를 검사한다."""
    errors: list[str] = []
    lines = [line.rstrip() for line in text.splitlines()]
    positions = []
    for heading in required_headings:
        if heading in lines:
            positions.append(lines.index(heading))
        else:
            errors.append(f"필수 제목 누락: {heading}")
    if positions != sorted(positions):
        errors.append("필수 제목의 순서가 명세와 다름")
    for pattern in FORBIDDEN_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            errors.append(f"결과 단정 표현: {match.group(0)!r}")
    for arxiv_id in sorted(set(ARXIV_ID.findall(text)) - whitelist):
        errors.append(f"화이트리스트에 없는 인용 {arxiv_id}")
    return errors


def validate_research_plan(text: str, whitelist: set[str]) -> list[str]:
    errors = validate_markdown(text, PLAN_HEADINGS, whitelist)
    if DESIGN_TABLE_HEADER not in text:
        errors.append("Design Table 헤더가 명세와 다름")
    return errors


def validate_paper_skeleton(text: str, whitelist: set[str]) -> list[str]:
    errors = validate_markdown(text, SKELETON_HEADINGS, whitelist)
    for part in ABSTRACT_PARTS:
        if f"**{part}:**" not in text:
            errors.append(f"Structured Abstract 항목 누락: {part}")
    if "[RESULT:" not in text:
        errors.append("결과 자리표시자 [RESULT: ...]가 없음")
    return errors


def validate_output_dir(directory: Path) -> dict[str, list[str]]:
    """아이디어 1개의 산출물 폴더(plan.json, research_plan.md, paper_skeleton.md)를 검사한다."""
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    whitelist = _whitelist(plan)
    return {
        "plan.json": validate_plan(plan),
        "research_plan.md": validate_research_plan(
            (directory / "research_plan.md").read_text(encoding="utf-8"), whitelist
        ),
        "paper_skeleton.md": validate_paper_skeleton(
            (directory / "paper_skeleton.md").read_text(encoding="utf-8"), whitelist
        ),
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m research_plan.validate <output_dir>", file=sys.stderr)
        return 2
    report = validate_output_dir(Path(argv[0]))
    failed = False
    for name, errors in report.items():
        status = "OK" if not errors else f"FAIL ({len(errors)})"
        print(f"[{status}] {name}")
        for error in errors:
            print(f"  - {error}")
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
