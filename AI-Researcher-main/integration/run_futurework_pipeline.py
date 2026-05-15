from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from integration.searchengine_cso_adapter import HttpSearchEngineClient, SearchEngineCSOAdapter
except ModuleNotFoundError as exc:
    if exc.name != "integration":
        raise
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from integration.searchengine_cso_adapter import HttpSearchEngineClient, SearchEngineCSOAdapter


def build_futurework_draft(payload: dict[str, Any]) -> str:
    selected = payload["selected_papers"]
    lines: list[str] = [
        f"# Selected Papers",
        "",
        f"Query: {payload['query']}",
        "",
    ]
    for paper in selected:
        authors = ", ".join(paper["authors"]) if paper["authors"] else "Unknown authors"
        lines.extend(
            [
                f"- [{paper['selection_index']}] **{paper['title']}**",
                f"  - arXiv ID: {paper['paper_id']}",
                f"  - Category: {paper['arxiv_primary_category'] or 'unknown'} / {paper['cfo_label_id'] or 'unassigned'}",
                f"  - Published: {paper['published'] or 'unknown'}",
                f"  - Authors: {authors}",
            ]
        )
    lines.extend(["", "# Future Work", ""])
    unique_labels = [paper["cfo_label_id"] for paper in selected if paper.get("cfo_label_id")]
    unique_categories = [paper["arxiv_primary_category"] for paper in selected if paper.get("arxiv_primary_category")]
    lines.append(
        "This narrowed pipeline highlights follow-up directions by clustering the selected leaf papers around "
        f"CSO labels ({', '.join(sorted(set(unique_labels))) or 'unassigned topics'}) and primary arXiv categories "
        f"({', '.join(sorted(set(unique_categories))) or 'unknown categories'})."
    )
    lines.append(
        "Future work should compare the common assumptions in these papers, identify unresolved evaluation gaps, "
        "and test a lighter-weight synthesis that keeps the strongest idea threads while removing benchmark-specific overhead."
    )
    lines.extend(["", "# Draft", ""])
    lines.append("## Working Title")
    lines.append(f"A Future-Work-Oriented Synthesis for {payload['query']}")
    lines.extend(["", "## Problem Statement"])
    lines.append(
        "Prior work in the selected set converges on related subtopics, but the implementation paths remain fragmented. "
        "This draft focuses on extracting a compact research direction that can be validated without the full original AI-Researcher pipeline."
    )
    lines.extend(["", "## Proposed Direction"])
    lines.append(
        "We propose a reduced pipeline that uses SearchEngine retrieval, CSO leaf-paper selection, and a future-work-first writing flow. "
        "The method preserves canonical metadata from arxiv_cs_ai.db while narrowing the downstream writing target to a concise research draft."
    )
    lines.extend(["", "## Expected Contribution"])
    lines.append(
        "The expected contribution is an interpretable shortlist of papers, a reusable future-work synthesis, and a draft artifact that can be refined into a fuller manuscript later if needed."
    )
    return "\n".join(lines) + "\n"


def run_pipeline(
    *,
    query: str,
    db_path: str,
    selected_papers_path: str,
    output_path: str,
    search_results: list[dict[str, Any]] | None = None,
    search_url: str = "http://127.0.0.1:8000",
) -> dict[str, Any]:
    adapter = SearchEngineCSOAdapter(
        db_path=db_path,
        search_client=_InlineSearchClient(search_results) if search_results is not None else HttpSearchEngineClient(base_url=search_url),
    )
    if search_results is not None:
        payload = adapter.build_from_search_results(query=query, raw_results=search_results)
    else:
        payload = adapter.run(query=query)

    selected_path = Path(selected_papers_path)
    selected_path.parent.mkdir(parents=True, exist_ok=True)
    selected_path.write_text(json.dumps({"query": payload["query"], "selected_papers": payload["selected_papers"]}, ensure_ascii=False, indent=2), encoding="utf-8")

    draft = build_futurework_draft(payload)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(draft, encoding="utf-8")
    return payload


class _InlineSearchClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = results

    def search(self, *, query: str, size: int = 100) -> list[dict[str, Any]]:
        del query, size
        return self._results


def run_pipeline_from_mode(
    *,
    query: str,
    reference: str | None,
    db_path: str,
    repo_root: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    selected = root / "runtime_inputs" / "selected_papers.json"
    output = root / "runtime_outputs" / "futurework_draft.md"
    search_results = None
    if reference:
        ref_path = Path(reference)
        if ref_path.exists():
            search_results = json.loads(ref_path.read_text(encoding="utf-8"))
    return run_pipeline(
        query=query,
        db_path=db_path,
        selected_papers_path=str(selected),
        output_path=str(output),
        search_results=search_results,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--selected-papers-path", default="runtime_inputs/selected_papers.json")
    parser.add_argument("--output-path", default="runtime_outputs/futurework_draft.md")
    parser.add_argument("--search-results-file")
    parser.add_argument("--search-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    search_results = None
    if args.search_results_file:
        search_results = json.loads(Path(args.search_results_file).read_text(encoding="utf-8"))
    run_pipeline(
        query=args.query,
        db_path=args.db_path,
        selected_papers_path=args.selected_papers_path,
        output_path=args.output_path,
        search_results=search_results,
        search_url=args.search_url,
    )


if __name__ == "__main__":
    main()
