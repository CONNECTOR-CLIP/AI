"""List CoT4 resource needs before running the CoT5 novelty check."""

from __future__ import annotations

import argparse
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
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


async def run_cot4_then_cot5(
    payload: dict[str, Any],
    *,
    cot4_pipeline: Any | None = None,
    cot5_check: Cot5Check | None = None,
) -> dict[str, Any]:
    """Run resource guidance before CoT5.

    The two modules use different ``ResearchIdea`` dataclasses, so the same
    Future-Work payload is adapted independently for each stage.  CoT5 is a
    batch-level downstream stage: only a CoT4 error stops CoT5.
    """

    cot4_pipeline = cot4_pipeline or CoT4.CoT4Pipeline()
    cot5_check = cot5_check or CoT5.check_novelty

    cot4_ideas = CoT4.ideas_from_future_work(payload)
    cot5_ideas = CoT5.ideas_from_future_work(payload)
    if len(cot4_ideas) != len(cot5_ideas):
        raise ValueError("CoT5 and CoT4 adapted a different number of proposals")

    cot4_results: list[dict[str, Any]] = []
    failed_titles: list[str] = []
    async def check_cot4(idea: CoT4.ResearchIdea, executor: ThreadPoolExecutor) -> dict[str, Any]:
        try:
            return _as_result_dict(await asyncio.get_running_loop().run_in_executor(
                executor, cot4_pipeline.check, idea,
            ))
        except Exception as exc:  # A CoT4 error stops CoT5.
            return {
                "idea_title": idea.title,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    # Gather preserves proposal order and completes all CoT4 calls before CoT5.
    with ThreadPoolExecutor(max_workers=max(1, len(cot4_ideas))) as executor:
        cot4_results = list(await asyncio.gather(*(
            check_cot4(idea, executor) for idea in cot4_ideas
        )))
    for idea, result in zip(cot4_ideas, cot4_results):
        if result.get("status") == "error":
            failed_titles.append(idea.title)

    gate_passed = not failed_titles
    report: dict[str, Any] = {
        "status": "completed" if gate_passed else "blocked",
        "pipeline": ["CoT4", "CoT5"],
        "gate": {
            "name": "CoT4 resource guidance",
            "passed": gate_passed,
            "failed_ideas": failed_titles,
        },
        "CoT4": {"results": cot4_results},
    }

    if not gate_passed:
        report["CoT5"] = {
            "status": "skipped",
            "results": [],
            "reason": "CoT4 resource guidance failed for at least one proposal.",
        }
        return report

    cot5_results = [
        _as_result_dict(result)
        for result in await asyncio.gather(*(cot5_check(idea) for idea in cot5_ideas))
    ]

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
    parser = argparse.ArgumentParser(description="Run CoT4 resource guidance before CoT5 novelty checking")
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
