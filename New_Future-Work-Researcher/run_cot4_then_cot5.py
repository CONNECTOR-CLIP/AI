"""Run the downstream idea checks in the safe order: CoT4 -> CoT5.

CoT4 is the feasibility gate for the downstream novelty check.  CoT5 is
started only after every proposal has received a ``FEASIBLE`` CoT4 result.
This is intentionally a batch barrier: a partial CoT5 run would make the
output set difficult to interpret and could let an unvalidated proposal
through the downstream stage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import CoT4
import CoT5


Cot5Check = Callable[[Any], Awaitable[Any]]


def _as_result_dict(result: Any) -> dict[str, Any]:
    """Normalize a pipeline result without coupling the runner to dataclasses."""

    if hasattr(result, "as_dict"):
        result = result.as_dict()
    if not isinstance(result, Mapping):
        raise TypeError(f"pipeline result must be a mapping, got {type(result).__name__}")
    return dict(result)


def _classification(result: Mapping[str, Any]) -> str | None:
    """Read the CoT4 classification from either supported result shape."""

    value = result.get("classification")
    if value is not None:
        return str(value)

    judgment = result.get("judgment")
    if isinstance(judgment, Mapping) and judgment.get("classification") is not None:
        return str(judgment["classification"])
    return None


def cot4_validation_passed(result: Mapping[str, Any]) -> bool:
    """Return whether a CoT4 result is allowed to cross the stage barrier."""

    return _classification(result) == "FEASIBLE"


async def run_cot4_then_cot5(
    payload: dict[str, Any],
    *,
    cot4_pipeline: Any | None = None,
    cot5_check: Cot5Check | None = None,
) -> dict[str, Any]:
    """Run CoT4 first and conditionally run CoT5.

    The two modules use different ``ResearchIdea`` dataclasses, so the same
    Future-Work payload is adapted independently for each stage.  CoT5 is a
    batch-level downstream stage: if any CoT4 result is not ``FEASIBLE`` (or
    CoT4 raises for a proposal), no CoT5 call is made.
    """

    cot4_pipeline = cot4_pipeline or CoT4.CoT4Pipeline()
    cot5_check = cot5_check or CoT5.check_novelty

    cot4_ideas = CoT4.ideas_from_future_work(payload)
    cot5_ideas = CoT5.ideas_from_future_work(payload)
    if len(cot4_ideas) != len(cot5_ideas):
        raise ValueError("CoT5 and CoT4 adapted a different number of proposals")

    cot4_results: list[dict[str, Any]] = []
    failed_titles: list[str] = []
    for idea in cot4_ideas:
        try:
            result = _as_result_dict(cot4_pipeline.check(idea))
        except Exception as exc:  # A failed validation must also stop CoT5.
            result = {
                "idea_title": idea.title,
                "classification": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }

        cot4_results.append(result)
        if not cot4_validation_passed(result):
            failed_titles.append(idea.title)

    gate_passed = not failed_titles
    report: dict[str, Any] = {
        "status": "completed" if gate_passed else "blocked",
        "pipeline": ["CoT4", "CoT5"],
        "gate": {
            "name": "CoT4 feasibility",
            "required_classification": "FEASIBLE",
            "passed": gate_passed,
            "failed_ideas": failed_titles,
        },
        "CoT4": {"results": cot4_results},
    }

    if not gate_passed:
        report["CoT5"] = {
            "status": "skipped",
            "results": [],
            "reason": "CoT4 validation did not pass for every proposal.",
        }
        return report

    cot5_results: list[dict[str, Any]] = []
    for idea in cot5_ideas:
        cot5_results.append(_as_result_dict(await cot5_check(idea)))

    report["CoT5"] = {"status": "completed", "results": cot5_results}
    return report


# 제안별 게이트에서 CoT5로 보내는 CoT4 판정. QUESTIONABLE은 "AI가 판단할 근거가 부족함"이지
# 실현 불가가 아니므로 일단 통과로 간주한다(2026-10-09 팀 결정). INFEASIBLE·ERROR만 걸러낸다.
FILTERED_GATE_CLASSIFICATIONS = ("FEASIBLE", "QUESTIONABLE")


def cot4_filtered_gate_passed(result: Mapping[str, Any]) -> bool:
    return _classification(result) in FILTERED_GATE_CLASSIFICATIONS


async def run_cot4_then_cot5_filtered(
    payload: dict[str, Any],
    *,
    cot4_pipeline: Any | None = None,
    cot5_check: Cot5Check | None = None,
    on_cot4_done: Callable[[list[dict[str, Any]], list[str]], None] | None = None,
) -> dict[str, Any]:
    """제안별 게이트: CoT4 판정이 FILTERED_GATE_CLASSIFICATIONS(FEASIBLE·QUESTIONABLE)인 제안만 CoT5로 보낸다.

    on_cot4_done(cot4_results, passed_titles)는 CoT4가 끝나고 CoT5가 시작되기 전에 호출된다
    (진행 상황을 단계별로 알리기 위한 훅).

    run_cot4_then_cot5(배치 게이트)와 달리 일부 제안이 INFEASIBLE이어도 나머지는 CoT5로 진행한다.
    모든 CoT4 결과(QUESTIONABLE 포함)는 CoT4 results에 그대로 남겨 근거 자료로 쓴다.
    CoT4·CoT5 모두 제안 간 병렬로 실행하며, 한 제안의 실패는 그 제안의 결과에만 기록된다.
    CoT4·CoT5 결과마다 원래 제안의 id(proposal_id)를 붙인다. 일부 제안만 검증한 결과를
    원래 분석 결과에 합칠 때 순서가 아니라 이 값으로 맞춘다.
    """

    cot4_pipeline = cot4_pipeline or CoT4.CoT4Pipeline()
    cot5_check = cot5_check or CoT5.check_novelty

    cot4_ideas = CoT4.ideas_from_future_work(payload)
    cot5_ideas = CoT5.ideas_from_future_work(payload)
    if len(cot4_ideas) != len(cot5_ideas):
        raise ValueError("CoT5 and CoT4 adapted a different number of proposals")

    async def check_cot4(idea: Any) -> dict[str, Any]:
        try:
            # CoT4Pipeline.check는 동기 LLM 호출이므로 스레드로 돌려 제안 간 병렬 실행한다.
            return _as_result_dict(await asyncio.to_thread(cot4_pipeline.check, idea))
        except Exception as exc:
            return {
                "idea_title": idea.title,
                "classification": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }

    cot4_results = list(await asyncio.gather(*[check_cot4(idea) for idea in cot4_ideas]))

    # 제안 id가 없으면 1부터 매긴 순번을 쓴다 (CoT4·CoT5 어댑터의 기본값과 같다).
    proposal_ids = [
        proposal.get("id", index) if isinstance(proposal, dict) else index
        for index, proposal in enumerate(payload["future_work_proposals"], 1)
    ]
    for result, proposal_id in zip(cot4_results, proposal_ids):
        result["proposal_id"] = proposal_id

    passed_pairs = [
        (cot5_idea, proposal_id)
        for cot5_idea, result, proposal_id in zip(cot5_ideas, cot4_results, proposal_ids)
        if cot4_filtered_gate_passed(result)
    ]
    passed = [idea for idea, _ in passed_pairs]
    failed_titles = [
        idea.title
        for idea, result in zip(cot4_ideas, cot4_results)
        if not cot4_filtered_gate_passed(result)
    ]

    report: dict[str, Any] = {
        "status": "completed",
        "pipeline": ["CoT4", "CoT5"],
        "gate": {
            "name": "CoT4 feasibility",
            "mode": "per_proposal",
            "passing_classifications": list(FILTERED_GATE_CLASSIFICATIONS),
            "passed_ideas": [idea.title for idea in passed],
            "failed_ideas": failed_titles,
        },
        "CoT4": {"results": cot4_results},
    }

    if on_cot4_done is not None:
        on_cot4_done(cot4_results, [idea.title for idea in passed])

    if not passed:
        report["CoT5"] = {
            "status": "skipped",
            "results": [],
            "reason": "No proposal passed the CoT4 gate (FEASIBLE or QUESTIONABLE).",
        }
        return report

    async def check_cot5(idea: Any) -> dict[str, Any]:
        try:
            return _as_result_dict(await cot5_check(idea))
        except Exception as exc:
            return {
                "idea_title": idea.title,
                "classification": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }

    # CoT5.submodule_cwd()는 프로세스 전역 cwd를 바꿨다가 되돌린다. 병렬 실행 중 먼저 끝난 작업이
    # cwd를 원래대로 돌려놓으면 아직 실행 중인 작업의 상대경로 open이 깨지므로, gather 전체를
    # 서브모듈 디렉터리 안에서 실행해 각 작업의 복원 대상도 서브모듈 디렉터리가 되게 한다.
    with CoT5.submodule_cwd():
        cot5_results = list(await asyncio.gather(*[check_cot5(idea) for idea in passed]))
    for result, (_, proposal_id) in zip(cot5_results, passed_pairs):
        result["proposal_id"] = proposal_id

    report["CoT5"] = {"status": "completed", "results": cot5_results}
    return report


def _load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CoT4 feasibility before CoT5 novelty checking")
    parser.add_argument("future_work_json", type=Path, help="Future-Work-Researcher result JSON")
    parser.add_argument("--cot5-config", default=None, help="CoT5 config.yml path")
    parser.add_argument("--cot5-model", default=None, help="CoT5 equivalence-check model")
    parser.add_argument("--cot4-model", default=None, help="CoT4 model")
    parser.add_argument("--output", type=Path, default=None, help="Optional report output path")
    args = parser.parse_args()

    cot4_pipeline = CoT4.CoT4Pipeline(provider=CoT4.OpenAIProvider(model=args.cot4_model))
    cot5_provider: Any | None = None

    async def check_with_cot5_config(idea: Any) -> Any:
        nonlocal cot5_provider
        if cot5_provider is None:
            cot5_provider = CoT5.OpenAIProvider(model=args.cot5_model)
        return await CoT5.check_novelty(
            idea,
            config_path=args.cot5_config,
            provider=cot5_provider,
        )

    report = asyncio.run(
        run_cot4_then_cot5(
            _load_payload(args.future_work_json),
            cot4_pipeline=cot4_pipeline,
            cot5_check=check_with_cot5_config,
        )
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
