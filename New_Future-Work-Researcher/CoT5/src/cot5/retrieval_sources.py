"""Independent full-corpus vector and title/abstract retrieval sources."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from . import lexical_index, vector_index


def _database() -> Path:
    return Path(os.getenv("ARXIV_DB_PATH", r"D:\experiment\arxiv_cs_ai.db"))


async def vector_candidates(idea: str, cutoff_date: str | None = None) -> tuple[dict, dict]:
    db = _database()
    index_dir = Path(os.getenv("COT5_VECTOR_INDEX_DIR", f"{db}.specter2"))
    status = vector_index.index_status(index_dir, db)
    if not status.get("complete"):
        return {}, status
    try:
        papers = await asyncio.to_thread(
            vector_index.search_index, idea, index_dir=index_dir, db_path=db,
            top_k=100, cutoff_date=cutoff_date,
        )
    except Exception as exc:
        return {}, {"state": "error", "complete": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {str(p["corpusId"]): p for p in papers}, {**status, "candidate_count": len(papers)}


async def lexical_candidates(idea: str) -> tuple[dict, dict]:
    db = _database()
    index_path = Path(os.getenv("ARXIV_FTS_PATH", f"{db}.fts.sqlite3"))
    try:
        status = lexical_index.index_status(db, index_path)
    except Exception as exc:
        return {}, {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if status["state"] != "complete":
        return {}, status
    try:
        papers = await asyncio.to_thread(
            lexical_index.search_papers, idea, source_path=db,
            index_path=index_path, limit=100,
        )
    except Exception as exc:
        return {}, {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}
    for paper in papers:
        paper["source"] = "title_abstract"
    return {str(p["corpusId"]): p for p in papers}, {**status, "candidate_count": len(papers)}


def summarize_trace(trace: dict) -> dict:
    """Keep audit evidence without serializing large DataFrames or embeddings."""
    def count(value):
        try:
            return len(value)
        except (TypeError, ValueError):
            return 0

    vector = trace.get("vector_index", {"state": "not_checked"})
    lexical = trace.get("lexical_index", {"state": "not_checked"})
    warnings = list(trace.get("retrieval_warnings") or [])
    if not vector.get("complete"):
        warnings.append(f"full-corpus vector search unavailable: {vector.get('state', 'unknown')}")
    if lexical.get("state") in ("missing", "building", "stale", "error"):
        warnings.append(f"title/abstract fallback unavailable: {lexical['state']}")
    return {
        "idea_keywords": list(trace.get("idea_keywords") or []),
        "title_keywords": list(trace.get("title_keywords") or []),
        "query_hit_counts": list(trace.get("query_hit_counts") or []),
        "keyword_candidate_count": trace.get("keyword_candidate_count", count(trace.get("keyword_papers"))),
        "vector_candidate_count": trace.get("vector_candidate_count", 0),
        "lexical_candidate_count": trace.get("lexical_candidate_count", 0),
        "ranked_candidate_count": count(trace.get("most_relevant_papers")),
        "vector_index": vector,
        "lexical_index": lexical,
        "coverage": "full_corpus_vector" if vector.get("complete") else "limited_candidates",
        "retrieval_warnings": warnings,
    }
