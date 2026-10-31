"""Stage 3: plan.json 심사(LLM 판정기)와 1회 보완.

1. 규칙 검사(rule_errors)를 다시 돌린다. 통과하지 못한 plan은 심사하지 않는다.
2. 판정기가 필드별 점수(1~5)와 지적 사항을 낸다. 기준은 docs/field_definitions.md의 "좋은 값" 열이다.
3. 기준 점수 미만이거나 major 지적이 있는 필드의 묶음만, 지적 사항을 붙여 2단계 작성기로 다시 쓰게 한다(1회).
4. 다시 쓴 plan을 한 번 더 심사한다. 그래도 남은 문제는 사람이 확인하도록 needs_review로 표시한다.
"""

from __future__ import annotations

import copy
import json

from .extract import (
    GROUP_OF_FIELD,
    PROMPTS,
    compact_evidence,
    extract_plan,
    field_guidance,
    plan_outputs,
    rule_errors,
)
from .provider import LLMProvider
from .schemas import FIELD_GROUPS, FIELD_KEYS

DEFAULT_JUDGE_MODEL = "openai/gpt-6-luna-pro"
PASS_SCORE = 4
# novelty_search_scope는 CoT5 결과를 코드로 옮긴 것이므로 심사하지 않는다.
JUDGED_FIELDS = [k for k in FIELD_KEYS if k != "novelty_search_scope"]
CHECKS = [
    "quote_fidelity",
    "closest_work_difference",
    "baseline_fit",
    "metric_fit",
    "claim_quality",
    "component_quality",
    "side_effect",
    "source_honesty",
    "internal_consistency",
    "other",
]

_STR = {"type": "string"}
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["field_scores", "issues"],
    "properties": {
        "field_scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "score", "reason"],
                "properties": {
                    "field": {"type": "string", "enum": JUDGED_FIELDS},
                    "score": {"type": "integer"},
                    "reason": _STR,
                },
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "item_id", "severity", "check", "problem", "evidence", "suggestion"],
                "properties": {
                    "field": {"type": "string", "enum": JUDGED_FIELDS},
                    "item_id": _STR,
                    "severity": {"type": "string", "enum": ["major", "minor"]},
                    "check": {"type": "string", "enum": CHECKS},
                    "problem": _STR,
                    "evidence": _STR,
                    "suggestion": _STR,
                },
            },
        },
    },
}


class ReviewError(RuntimeError):
    pass


def judge_instructions() -> str:
    parts = [(PROMPTS / "judge.md").read_text(encoding="utf-8"), field_guidance(JUDGED_FIELDS)]
    return "\n\n".join(part.strip() for part in parts) + "\n"


def judge_document(evidence: dict, plan: dict, fix_errors: list[str] | None = None,
                   previous: dict | None = None, changed: list[str] | None = None) -> str:
    payload = {"evidence": compact_evidence(evidence), "plan_fields": plan["fields"]}
    if previous is not None:
        payload["previous_judgement"] = previous
        payload["changed_fields"] = changed or []
    if fix_errors:
        payload["fix_errors"] = fix_errors
    return json.dumps(payload, ensure_ascii=False, indent=1)


def check_judgement(judgement: dict) -> list[str]:
    """판정기 출력 자체의 형식 검사."""
    errors = []
    scored = [s.get("field") for s in judgement.get("field_scores", [])]
    for field in JUDGED_FIELDS:
        if scored.count(field) != 1:
            errors.append(f"field_scores: {field}의 점수가 정확히 하나여야 함 (현재 {scored.count(field)}개)")
    with_issue = {i.get("field") for i in judgement.get("issues", [])}
    for s in judgement.get("field_scores", []):
        if not 1 <= int(s.get("score", 0)) <= 5:
            errors.append(f"field_scores: {s.get('field')} 점수 {s.get('score')}는 1~5 밖임")
        elif s["score"] < PASS_SCORE and s.get("field") not in with_issue:
            errors.append(f"field_scores: {s.get('field')}에 {s['score']}점을 줬지만 issues가 없음")
    return errors


def judge(evidence: dict, plan: dict, provider: LLMProvider, *, attempts: int = 2,
          previous: dict | None = None, changed: list[str] | None = None) -> dict:
    fix_errors: list[str] | None = None
    for _ in range(attempts):
        judgement = provider.evaluate(
            instructions=judge_instructions(),
            document=judge_document(evidence, plan, fix_errors, previous, changed),
            schema=JUDGE_SCHEMA,
            schema_name="judge",
        )
        fix_errors = check_judgement(judgement)
        if not fix_errors:
            return judgement
    raise ReviewError(f"판정기 출력이 형식 검사를 통과하지 못함: {fix_errors}")


def summarize(judgement: dict) -> dict:
    scores = {s["field"]: s["score"] for s in judgement["field_scores"]}
    major = [i for i in judgement["issues"] if i["severity"] == "major"]
    low = sorted(f for f, score in scores.items() if score < PASS_SCORE)
    return {
        "passed": not major and not low,
        "mean_score": round(sum(scores.values()) / len(scores), 2),
        "min_score": min(scores.values()),
        "low_fields": low,
        "major_issues": len(major),
        "minor_issues": len(judgement["issues"]) - len(major),
    }


CAUSED_PREFIX = "변경된 필드"
MISSED_PREFIX = "이전 심사에서 놓침"


def reconcile(first: dict, second: dict, changed: list[str]) -> tuple[dict, dict]:
    """2회차 판정에서 상태 판단에 쓸 판정(effective)과 분류 정보를 만든다.

    같은 글에는 같은 판정을 쓴다는 원칙에 따라, 내용이 바뀌지 않은 필드는 1회차 판정을 유지한다.
    단 바뀐 필드 때문에 생긴 문제(evidence가 "변경된 필드"로 시작)는 2회차 판정을 쓴다.
    바뀌지 않은 필드에 대한 그 밖의 새 지적은 상태 판단에서 빼고 사람이 확인하도록 따로 모은다.
    """
    s1 = {s["field"]: s for s in first["field_scores"]}
    s2 = {s["field"]: s for s in second["field_scores"]}
    caused = {i["field"] for i in second["issues"] if i["evidence"].startswith(CAUSED_PREFIX)}
    use_second = set(changed) | caused
    effective = {
        "field_scores": [s2[f] if f in use_second else s1[f] for f in JUDGED_FIELDS],
        "issues": [i for i in second["issues"] if i["field"] in use_second]
        + [i for i in first["issues"] if i["field"] not in use_second],
    }
    info = {
        "changed_fields": sorted(changed),
        "affected_by_change": sorted(caused - set(changed)),
        # 바뀐 필드인데 점수가 떨어짐: 보완이 오히려 나빠지게 함
        "regressed_fields": sorted(f for f in changed if s2[f]["score"] < s1[f]["score"]),
        # 바뀌지 않았고 바뀐 필드 탓도 아닌데 점수가 달라짐: 판정기 편차(1회차 판정 유지)
        "drift_fields": sorted(
            f for f in JUDGED_FIELDS if f not in use_second and s2[f]["score"] != s1[f]["score"]
        ),
        # 바뀌지 않은 필드에서 새로 나온 지적: 상태 판단에 넣지 않고 사람이 확인
        "new_findings": [i for i in second["issues"] if i["field"] not in use_second],
    }
    return effective, info


def fix_targets(judgement: dict) -> set[str]:
    """고쳐야 할 필드: 기준 점수 미만이거나 major 지적이 있는 필드."""
    targets = {s["field"] for s in judgement["field_scores"] if s["score"] < PASS_SCORE}
    return targets | {i["field"] for i in judgement["issues"] if i["severity"] == "major"}


def fixes_from(judgement: dict) -> dict[str, list[str]]:
    """고쳐야 할 필드의 지적 사항을 묶음별로 모은다."""
    scores = {s["field"]: s for s in judgement["field_scores"]}
    targets = fix_targets(judgement)
    fixes: dict[str, list[str]] = {}
    for field in JUDGED_FIELDS:
        if field not in targets:
            continue
        messages = [
            f"{field}{(' ' + i['item_id']) if i['item_id'] else ''}: [심사 {i['check']}/{i['severity']}] "
            f"{i['problem']} 근거: {i['evidence']} 고칠 방향: {i['suggestion']}"
            for i in judgement["issues"] if i["field"] == field
        ]
        messages.append(f"{field}: [심사 점수 {scores[field]['score']}/5] {scores[field]['reason']}")
        fixes.setdefault(GROUP_OF_FIELD[field], []).extend(messages)
    return fixes


def review_plan(
    evidence: dict,
    plan: dict,
    writer: LLMProvider | None,
    judge_provider: LLMProvider,
    *,
    refine: bool = True,
    max_rounds: int = 3,
) -> tuple[dict, dict, str]:
    """(최종 plan, review 보고서, 상태)를 돌려준다. 상태는 pass 또는 needs_review."""
    errors = rule_errors(plan, evidence)
    if errors:
        raise ReviewError(f"규칙 검사를 통과하지 못한 plan은 심사하지 않음 (먼저 extract): {errors[:3]}")
    first = judge(evidence, plan, judge_provider)
    report = {
        "judge_model": judge_provider.model,
        "writer_model": writer.model if writer else None,
        "pass_score": PASS_SCORE,
        "rounds": [{"round": 1, "summary": summarize(first), "judgement": first}],
    }
    if report["rounds"][0]["summary"]["passed"] or not refine or writer is None:
        status = "pass" if report["rounds"][0]["summary"]["passed"] else "needs_review"
        return _stamp(plan, report, status), report, status

    fixes = fixes_from(first)
    targets = fix_targets(first)
    # 다시 쓰는 묶음 안에서도 지적받지 않은 필드는 원래 값으로 고정한다.
    locked = {
        k: plan["fields"][k] for g in fixes for k in FIELD_GROUPS[g] if k not in targets and k in plan["fields"]
    }
    refined, log, ok = extract_plan(
        evidence, writer, max_rounds=max_rounds, start=plan_outputs(plan), fixes=fixes, locked=locked
    )
    report["refine"] = {
        "groups": list(fixes),
        "target_fields": sorted(targets),
        "locked_fields": sorted(locked),
        "rules_passed": ok,
        "extract_log": log,
    }
    if not ok and locked:
        # 고정한 필드와 맞출 수 없으면(예: 고친 필드가 고정 필드의 ID와 어긋남) 고정 없이 한 번 더 시도한다.
        refined, log, ok = extract_plan(
            evidence, writer, max_rounds=max_rounds, start=plan_outputs(plan), fixes=fixes
        )
        report["refine"].update({"unlocked_retry": True, "rules_passed": ok, "unlocked_extract_log": log})
    if not ok:
        # 다시 쓴 결과가 규칙 검사를 못 넘으면 원래 plan을 유지한다.
        return _stamp(plan, report, "needs_review"), report, "needs_review"
    changed = [k for k in JUDGED_FIELDS if refined["fields"][k] != plan["fields"][k]]
    second = judge(evidence, refined, judge_provider, previous=first, changed=changed)
    effective, info = reconcile(first, second, changed)
    summary = {**summarize(effective), **info}
    report["rounds"].append(
        {"round": 2, "summary": summary, "judgement": second, "effective_judgement": effective}
    )
    status = "pass" if summary["passed"] else "needs_review"
    return _stamp(refined, report, status), report, status


def _stamp(plan: dict, report: dict, status: str) -> dict:
    out = copy.deepcopy(plan)
    last = report["rounds"][-1]["summary"]
    out["meta"]["review"] = {
        "status": status,
        "judge_model": report["judge_model"],
        "rounds": len(report["rounds"]),
        "mean_score": last["mean_score"],
        "low_fields": last["low_fields"],
        "major_issues": last["major_issues"],
    }
    return out
