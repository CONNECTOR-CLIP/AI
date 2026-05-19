from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from integration.searchengine_cso_adapter import HttpSearchEngineClient, SearchEngineCSOAdapter
except ModuleNotFoundError as exc:
    if exc.name != "integration":
        raise

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from integration.searchengine_cso_adapter import HttpSearchEngineClient, SearchEngineCSOAdapter


def _write_paper_stubs(selected_papers: list[dict[str, Any]], papers_dir: Path) -> None:
    """selected_papers의 abstract를 로컬 .md 파일로 저장해서 idea_agent가 읽을 수 있게 한다."""
    papers_dir.mkdir(parents=True, exist_ok=True)
    for paper in selected_papers:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in paper["paper_id"])
        md_path = papers_dir / f"{safe_name}.md"
        authors = ", ".join(paper.get("authors") or []) or "Unknown"
        content = (
            f"# {paper['title']}\n\n"
            f"**arXiv ID:** {paper['paper_id']}  \n"
            f"**Authors:** {authors}  \n"
            f"**Published:** {paper.get('published') or 'unknown'}  \n"
            f"**Category:** {paper.get('arxiv_primary_category') or 'unknown'}  \n\n"
            f"## Abstract\n\n{paper.get('abstract') or '(no abstract)'}\n"
        )
        md_path.write_text(content, encoding="utf-8")


def _run_idea_agent(
    query: str,
    selected_papers: list[dict[str, Any]],
    papers_dir: Path,
    model: str = "gpt-4o-2024-08-06",
) -> dict[str, Any] | None:
    """idea_agent를 실행하고 JSON 결과를 반환한다. 실패 시 None."""
    _repo_root = Path(__file__).resolve().parents[1]
    research_agent_path = str(_repo_root / "research_agent")
    if research_agent_path not in sys.path:
        sys.path.insert(0, research_agent_path)
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser
    from research_agent.inno.agents.inno_agent.idea_agent import get_idea_agent
    from research_agent.inno.core import MetaChain

    # papers_dir의 부모를 local_root, 폴더명을 workplace_name으로 사용
    file_env = RequestsMarkdownBrowser(
        local_root=str(papers_dir.parent),
        workplace_name=papers_dir.name,
    )

    agent = get_idea_agent(model=model, file_env=file_env)
    client = MetaChain()

    paper_list = "\n".join(
        f"- {p['title']} ({p['paper_id']})" for p in selected_papers
    )
    task_message = (
        f"Query: {query}\n\n"
        f"Papers available in {file_env.docker_workplace}/:\n{paper_list}\n\n"
        "Read all papers and generate one comprehensive research idea as JSON."
    )

    response = client.run(
        agent=agent,
        messages=[{"role": "user", "content": task_message}],
        context_variables={},
    )

    # 마지막 assistant 메시지에서 JSON 추출
    for msg in reversed(response.messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            content = msg["content"]
            # ```json ... ``` 블록 또는 { ... } 추출
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                raw = json_match.group(1)
            else:
                start = content.find("{")
                end = content.rfind("}") + 1
                raw = content[start:end] if start != -1 and end > start else ""
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
    return None


def _append_idea_to_draft(draft: str, idea: dict[str, Any]) -> str:
    """futurework_draft에 idea_agent 결과 섹션을 추가한다."""
    lines = [
        "",
        "---",
        "",
        "# AI-Generated Research Idea",
        "",
        f"## {idea.get('title', 'Untitled Idea')}",
        "",
    ]

    if idea.get("motivation"):
        m = idea["motivation"]
        lines += ["### Motivation", "", m.get("importance", ""), "", m.get("gaps", ""), ""]

    if idea.get("proposed_method"):
        pm = idea["proposed_method"]
        lines += ["### Proposed Method", "", pm.get("summary", ""), ""]
        for step in pm.get("methodology", []):
            lines.append(f"- {step}")
        lines.append("")

    if idea.get("future_work"):
        fw = idea["future_work"]
        lines += ["### Publishable Topics", ""]
        for topic in fw.get("publishable_topics", []):
            lines.append(f"- **{topic.get('topic', '')}** — {topic.get('novelty', '')} (difficulty: {topic.get('difficulty', '?')})")
        lines.append("")

    return draft.rstrip() + "\n" + "\n".join(lines) + "\n"


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
    run_idea_agent: bool = True,
    idea_model: str = "gpt-4o-2024-08-06",
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

    if run_idea_agent and payload["selected_papers"]:
        papers_dir = selected_path.parent / "papers"
        _write_paper_stubs(payload["selected_papers"], papers_dir)
        print(f"[IdeaAgent] Running on {len(payload['selected_papers'])} papers...")
        idea = _run_idea_agent(
            query=query,
            selected_papers=payload["selected_papers"],
            papers_dir=papers_dir,
            model=idea_model,
        )
        if idea:
            draft = _append_idea_to_draft(draft, idea)
            idea_path = selected_path.parent / "idea_result.json"
            idea_path.write_text(json.dumps(idea, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[IdeaAgent] Done. Idea saved to {idea_path}")
        else:
            print("[IdeaAgent] Failed to parse idea JSON from agent response.")

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
