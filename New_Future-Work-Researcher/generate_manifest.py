"""Create or refresh a CoT experiment manifest from saved stage artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


STAGES = ("CoT1", "CoT2", "CoT3", "CoT4", "CoT5")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _result_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            return len(results)
        return 1
    raise ValueError("stage result must be a JSON object or array")


def _papers_from_input(input_path: Path | None) -> list[dict] | None:
    if input_path is None:
        return None
    payload = _read_json(input_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("source_papers"), list):
        return None
    papers = []
    for paper in payload["source_papers"]:
        if not isinstance(paper, dict):
            continue
        paper_id = paper.get("id") or paper.get("arxiv_id")
        title = paper.get("title")
        if paper_id and title:
            papers.append({"id": paper_id, "title": title})
    return papers


def write_manifest(
    output_dir: Path,
    *,
    papers: list[dict] | None = None,
    models: Mapping[str, str] | None = None,
    log: str | None = None,
    input_path: Path | None = None,
    stage_results: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write manifest.json beside the saved results, returning its contents.

    ``stage_results`` supplies in-memory results for a runner that saves a
    combined report rather than separate stage files. It takes precedence over
    artifact discovery for those stages.
    """
    output_dir = Path(output_dir)
    old_path = output_dir / "manifest.json"
    previous = _read_json(old_path) if old_path.is_file() else {}
    if papers is None:
        papers = _papers_from_input(input_path)
    if papers is None:
        papers = previous.get("papers", [])

    counts: dict[str, int] = {}
    for stage in STAGES:
        if stage_results is not None and stage in stage_results:
            counts[stage] = _result_count(stage_results[stage])
        elif stage in ("CoT1", "CoT2"):
            counts[stage] = len(list((output_dir / stage).glob("*.json")))
        else:
            nested = output_dir / stage / "result.json"
            flat = output_dir / f"{stage}.result.json"
            result_path = nested if nested.is_file() else flat
            counts[stage] = _result_count(_read_json(result_path)) if result_path.is_file() else 0

    if log is None:
        log = next((name for name in ("run.jsonl", "cot4_cot5_run.jsonl", "run_summary.json")
                    if (output_dir / name).is_file()), previous.get("log"))
    manifest = {
        "papers": papers,
        "models": dict(previous.get("models", {}) if models is None else models),
        "counts": counts,
        "log": log,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    old_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or refresh manifest.json from saved CoT results")
    parser.add_argument("output_dir", type=Path, help="experiment/results directory")
    parser.add_argument("--input", type=Path, help="FutureWork/result.json for source paper metadata")
    parser.add_argument("--papers-json", type=Path, help="JSON list of {id, title} papers")
    parser.add_argument("--cot4-model")
    parser.add_argument("--cot5-model")
    parser.add_argument("--log", help="relative run log filename")
    args = parser.parse_args()
    papers = _read_json(args.papers_json) if args.papers_json else None
    models = {stage: model for stage, model in (("CoT4", args.cot4_model), ("CoT5", args.cot5_model))
              if model is not None}
    manifest = write_manifest(args.output_dir, papers=papers, models=models or None,
                              log=args.log, input_path=args.input)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
