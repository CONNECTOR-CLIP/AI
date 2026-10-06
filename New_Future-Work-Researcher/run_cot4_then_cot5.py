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
