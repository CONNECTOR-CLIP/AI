"""
Backend compatibility API.

These endpoints are the contract used by the Spring backend:
- POST /api/search
- POST /api/search/mindmap
- POST /api/gap
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.dependencies import get_search_service
from app.schemas.search import SearchRequest

ROOT_DIR = Path(__file__).resolve().parents[3]
CATEGORY_DIR = ROOT_DIR / "Category_CSO"
FUTURE_WORK_DIR = ROOT_DIR / "Future-Work-Researcher"

for path in (CATEGORY_DIR, FUTURE_WORK_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

router = APIRouter(prefix="/api")


class SearchCompatRequest(BaseModel):
    keyword: str | None = None
    query: str | None = None
    category: str | None = None
    categories: list[str] | None = None
    page: int = 1
    size: int = Field(default=20, ge=1, le=100)


class PapersRequest(BaseModel):
    query: str | None = ""
    papers: list[dict[str, Any]]


class DraftRequest(BaseModel):
    proposal: dict[str, Any]
    workplace_name: str | None = None


def _normalise_page(page: int) -> int:
    return max(1, page)


def _paper_id(paper: dict[str, Any]) -> str:
    return str(
        paper.get("paper_id")
        or paper.get("paperId")
        or paper.get("arxiv_id")
        or paper.get("arxivId")
        or ""
    )


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split() if v.strip()]


def _published_year(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None


def _search_result_to_paper(result: Any) -> dict[str, Any]:
    raw = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    authors = raw.get("authors") or []
    categories = raw.get("categories") or []
    published = raw.get("published")
    return {
        "arxiv_id": raw.get("arxiv_id", ""),
        "paper_id": raw.get("arxiv_id", ""),
        "title": raw.get("title", ""),
        "abstract": raw.get("abstract") or "",
        "authors": authors,
        "submitter": ", ".join(authors) if isinstance(authors, list) else str(authors),
        "categories": categories,
        "primary_category": categories[0] if categories else None,
        "published": published,
        "created_date": published,
        "score": raw.get("score"),
        "highlight": raw.get("highlight"),
    }


def _to_tree_input(papers: list[dict[str, Any]]) -> dict[str, Any]:
    input_papers = []
    for index, paper in enumerate(papers):
        pid = _paper_id(paper) or f"paper-{index + 1}"
        title = str(paper.get("title") or pid)
        categories = _as_list(paper.get("arxiv_categories") or paper.get("categories"))
        primary = (
            paper.get("arxiv_primary_category")
            or paper.get("primary_category")
            or paper.get("privaryCategory")
            or (categories[0] if categories else None)
        )
        input_papers.append(
            {
                "paper_id": pid,
                "title": title,
                "abstract": str(paper.get("abstract") or paper.get("abstracts") or ""),
                "arxiv_id": str(paper.get("arxiv_id") or paper.get("arxivId") or pid),
                "arxiv_primary_category": primary,
                "arxiv_categories": categories,
                "authors": _as_list(paper.get("authors") or paper.get("author")),
                "year": _published_year(paper.get("published") or paper.get("created_date")),
                "source": "user_search",
            }
        )
    return {
        "run_config": {
            "max_iterations": 2,
            "top_k": 5,
            "subtopic_expansion_threshold": 10,
            "root_allowlist": None,
        },
        "input_papers": input_papers,
    }


def _build_roadmap(papers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not papers:
        return None
    try:
        from tree_builder import TreeBuilder

        db_path = os.getenv("ROADMAP_DB_PATH", "/tmp/clip_roadmap.db")
        builder = TreeBuilder(db_path=db_path)
        return builder.build_tree(_to_tree_input(papers))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"roadmap generation failed: {exc}") from exc


def _roadmap_to_graph(roadmap: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if not roadmap:
        return {"nodes": nodes, "edges": edges}

    for root in roadmap.get("roots", []):
        root_id = root.get("arxiv_primary_category", "root")
        nodes.append({"id": root_id, "label": root_id, "type": "root", "category": root_id})
        for topic in root.get("intermediate_nodes", []):
            topic_id = topic.get("node_id")
            nodes.append(
                {
                    "id": topic_id,
                    "label": topic.get("label"),
                    "type": "topic",
                    "category": root_id,
                    "paperCount": len(topic.get("children", [])),
                }
            )
            edges.append({"source": root_id, "target": topic_id})
            for child in topic.get("children", []):
                paper_id = child.get("paper_id")
                nodes.append(
                    {
                        "id": paper_id,
                        "label": paper_id,
                        "type": "paper",
                        "category": root_id,
                        "score": child.get("assignment", {}).get("score"),
                    }
                )
                edges.append({"source": topic_id, "target": paper_id})
    return {"nodes": nodes, "edges": edges}


@router.post("/search")
def search_papers_compat(payload: SearchCompatRequest) -> dict[str, Any]:
    keyword = (payload.keyword or payload.query or "").strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword is required")

    categories = payload.categories
    if categories is None and payload.category:
        categories = [payload.category]

    service = get_search_service()
    response = service.search(
        SearchRequest(
            query=keyword,
            categories=categories,
            page=_normalise_page(payload.page),
            size=payload.size,
        )
    )
    papers = [_search_result_to_paper(item) for item in response.results]
    roadmap = _build_roadmap(papers)
    return {
        "total": response.total,
        "page": response.page,
        "size": response.size,
        "papers": papers,
        "roadmap": roadmap,
    }


@router.post("/search/mindmap")
def create_mindmap(payload: PapersRequest) -> dict[str, Any]:
    roadmap = _build_roadmap(payload.papers)
    graph = _roadmap_to_graph(roadmap)
    return {"roadmap": roadmap, **graph}


@router.post("/gap")
async def analyze_gap(payload: PapersRequest) -> dict[str, Any]:
    titles = [str(p.get("title") or _paper_id(p)) for p in payload.papers if p.get("title") or _paper_id(p)]
    if not titles:
        raise HTTPException(status_code=422, detail="papers with title or id are required")

    paper_ids = {
        str(p.get("title") or _paper_id(p)): str(p.get("arxiv_id") or p.get("arxivId") or p.get("paper_id") or "")
        for p in payload.papers
        if (p.get("title") or _paper_id(p)) and (p.get("arxiv_id") or p.get("arxivId") or p.get("paper_id"))
    }

    try:
        from research_agent.future_work.future_work_flow import FutureWorkFlow
        from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser

        local_root = os.getenv("FUTURE_WORK_ROOT", "/tmp/clip_future_work")
        workplace_name = os.getenv("FUTURE_WORKPLACE_NAME", "workplace")
        file_env = RequestsMarkdownBrowser(
            viewport_size=1024 * 4,
            local_root=local_root,
            workplace_name=workplace_name,
            downloads_folder=os.path.join(local_root, workplace_name, "downloads"),
        )
        flow = FutureWorkFlow(
            cache_path=os.path.join(local_root, "cache"),
            model=os.getenv("COMPLETION_MODEL", "openrouter/google/gemini/gemini-2.5-pro"),
            file_env=file_env,
        )
        raw = await flow(
            paper_titles=titles,
            date_limit=os.getenv("FUTURE_WORK_DATE_LIMIT", "2010-01-01"),
            local_root=local_root,
            workplace_name=workplace_name,
            paper_ids=paper_ids,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"future work analysis failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None

    return {
        "gap_content": raw,
        "future_work": parsed,
        "papers": titles,
    }


@router.post("/gap/draft")
async def generate_paper_draft(payload: DraftRequest) -> dict[str, Any]:
    """사용자가 선택한 퓨처워크 제안 하나로 논문 초안 생성."""
    if not payload.proposal:
        raise HTTPException(status_code=422, detail="proposal is required")

    try:
        from research_agent.future_work.future_work_flow import FutureWorkFlow
        from research_agent.inno.environment.markdown_browser import RequestsMarkdownBrowser

        local_root = os.getenv("FUTURE_WORK_ROOT", "/tmp/clip_future_work")
        workplace_name = payload.workplace_name or os.getenv("FUTURE_WORKPLACE_NAME", "workplace")
        file_env = RequestsMarkdownBrowser(
            viewport_size=1024 * 4,
            local_root=local_root,
            workplace_name=workplace_name,
            downloads_folder=os.path.join(local_root, workplace_name, "downloads"),
        )
        flow = FutureWorkFlow(
            cache_path=os.path.join(local_root, "cache"),
            model=os.getenv("COMPLETION_MODEL", "openrouter/google/gemini-2.5-flash"),
            file_env=file_env,
        )
        draft = await flow.generate_paper_draft(
            proposal=payload.proposal,
            workplace_name=workplace_name,
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"paper draft generation failed: {exc}") from exc

    return {"paper_draft": draft}
