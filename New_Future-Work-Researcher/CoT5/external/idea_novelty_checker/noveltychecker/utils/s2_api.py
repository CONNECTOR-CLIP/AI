"""Local arXiv SQLite retrieval adapter.

This module keeps the function names used by the upstream novelty checker, but
does not contact Semantic Scholar.  Papers are read from ``ARXIV_DB_PATH`` and
returned in the small Semantic-Scholar-like shape expected by the rest of the
pipeline.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path(r"D:\experiment\arxiv_cs_ai.db")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+#-]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "about", "after", "against", "also", "based", "between", "from", "into",
    "method", "model", "paper", "research", "that", "their", "this", "using",
    "with", "for", "and", "the", "are", "our", "we", "will", "can",
}


def _db_path() -> Path:
    return Path(os.getenv("ARXIV_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(
            f"arXiv database is missing or empty: {path}. "
            "Set ARXIV_DB_PATH to a populated arxiv_cs_ai.db file."
        )
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _normalise_id(value: Any) -> str:
    paper_id = str(value or "").strip()
    for prefix in ("ARXIV:", "arXiv:", "CorpusId:"):
        if paper_id.startswith(prefix):
            return paper_id[len(prefix):]
    return paper_id


def _query_terms(query: str, maximum: int = 40) -> list[str]:
    tokens = [t.lower() for t in _TOKEN_RE.findall(query) if t.lower() not in _STOPWORDS]
    ordered: list[str] = []
    # CSO contains both single concepts and phrases, so try short n-grams first.
    for size in (3, 2, 1):
        for index in range(len(tokens) - size + 1):
            term = " ".join(tokens[index:index + size])
            if term not in ordered:
                ordered.append(term)
            if len(ordered) >= maximum:
                return ordered
    return ordered


def _paper_dict(row: sqlite3.Row, authors: list[dict[str, str]] | None = None) -> dict[str, Any]:
    arxiv_id = row["arxiv_id"]
    created = row["created_date"]
    return {
        "corpusId": arxiv_id,
        "paperId": arxiv_id,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "title": row["title"],
        "year": int(created[:4]) if created and created[:4].isdigit() else None,
        "publicationDate": created,
        "abstract": row["abstract"],
        "authors": authors or [],
        "fieldsOfStudy": (row["categories"] or "").split(),
        "s2FieldsOfStudy": [],
        "citationCount": None,
        "venue": "arXiv",
        "openAccessPdf": {"url": f"https://arxiv.org/pdf/{arxiv_id}"},
    }


def _authors_for(connection: sqlite3.Connection, arxiv_ids: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    ids = list(dict.fromkeys(arxiv_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    result: dict[str, list[dict[str, str]]] = {paper_id: [] for paper_id in ids}
    sql = f"SELECT arxiv_id, keyname, forenames FROM authors WHERE arxiv_id IN ({placeholders}) ORDER BY arxiv_id, position"
    for row in connection.execute(sql, ids):
        name = " ".join(part for part in (row["forenames"], row["keyname"]) if part)
        result[row["arxiv_id"]].append({"name": name})
    return result


def _get_papers_sync(ids: Iterable[Any]) -> list[dict[str, Any] | None]:
    requested = [_normalise_id(value) for value in ids]
    valid = [value for value in requested if value]
    if not valid:
        return []
    with _connect() as connection:
        placeholders = ",".join("?" for _ in valid)
        rows = connection.execute(
            f"SELECT * FROM papers WHERE is_deleted=0 AND arxiv_id IN ({placeholders})", valid
        ).fetchall()
        by_id = {row["arxiv_id"]: row for row in rows}
        authors = _authors_for(connection, by_id)
        return [
            _paper_dict(by_id[paper_id], authors.get(paper_id)) if paper_id in by_id else None
            for paper_id in requested
        ]


def _candidate_scores(
    connection: sqlite3.Connection, terms: Iterable[str], *, exclude: str = "",
    per_term_limit: int = 250,
) -> dict[str, tuple[int, float]]:
    """Use the indexed equality lookup without grouping millions of common-keyword rows."""
    scores: dict[str, tuple[int, float]] = {}
    recent_floor = os.getenv("ARXIV_RECENT_ID_FLOOR", "2001")
    for term_index, term in enumerate(terms):
        # Include both an unrestricted slice and a recent-ID slice. The latter
        # prevents insertion-order bias toward very old papers for common CSO concepts.
        rows = list(connection.execute(
            "SELECT arxiv_id, score FROM cso_keywords WHERE keyword=? LIMIT ?",
            (term, max(1, per_term_limit // 2)),
        ))
        rows.extend(connection.execute(
            "SELECT arxiv_id, score FROM cso_keywords WHERE keyword=? AND arxiv_id>=? LIMIT ?",
            (term, recent_floor, per_term_limit),
        ))
        for row in rows:
            paper_id = row["arxiv_id"]
            if paper_id == exclude:
                continue
            matches, total = scores.get(paper_id, (0, 0.0))
            scores[paper_id] = (matches + 1, total + float(row["score"]))
        # Terms are ordered from specific n-grams to single words. Once several
        # specific terms produced a healthy pool, avoid dozens of broad lookups.
        if term_index >= 5 and len(scores) >= 1000:
            break
    return scores


def _candidate_papers(
    connection: sqlite3.Connection, scores: dict[str, tuple[int, float]], limit: int,
    *, recent: bool = False, start_year: str = "", end_year: str = "",
) -> list[sqlite3.Row]:
    # Bound the detail query while leaving enough headroom for deleted/date-filtered rows.
    candidate_ids = sorted(scores, key=lambda pid: scores[pid], reverse=True)[: max(limit * 10, 500)]
    if not candidate_ids:
        return []
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = connection.execute(
        f"SELECT * FROM papers WHERE is_deleted=0 AND arxiv_id IN ({placeholders})",
        candidate_ids,
    ).fetchall()
    if start_year:
        rows = [row for row in rows if (row["created_date"] or "") >= f"{start_year}-01-01"]
    if end_year:
        rows = [row for row in rows if (row["created_date"] or "") <= f"{end_year}-12-31"]
    if recent:
        rows.sort(key=lambda row: ((row["created_date"] or ""), scores[row["arxiv_id"]]), reverse=True)
    else:
        rows.sort(key=lambda row: (scores[row["arxiv_id"]], row["created_date"] or ""), reverse=True)
    return rows[:limit]


async def get_paper_data(id_: Any, id_type: str = "corpus_id", batch_wise: bool = False):
    del id_type  # arXiv IDs are the only local identifier.
    ids = list(id_) if batch_wise and not isinstance(id_, str) else [id_]
    papers = await asyncio.to_thread(_get_papers_sync, ids)
    return papers if batch_wise else (papers[0] if papers else None)


def _search_sync(query: str, limit: int, start_year: str = "", end_year: str = "") -> list[dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return []
    limit = max(1, min(int(limit), 1000))
    with _connect() as connection:
        scores = _candidate_scores(connection, terms)
        rows = _candidate_papers(
            connection, scores, limit, start_year=start_year, end_year=end_year
        )
        authors = _authors_for(connection, (row["arxiv_id"] for row in rows))
        return [_paper_dict(row, authors.get(row["arxiv_id"])) for row in rows]


async def papers_from_search_api(
    query: str = "", start_year: str = "", end_year: str = "",
    search_type: str = "keyword", limit: int = 100,
):
    papers = await asyncio.to_thread(_search_sync, query, limit, start_year, end_year)
    if search_type == "snippet":
        return {"data": [{"paper": paper} for paper in papers]}
    return {"data": papers}


def _recommend_sync(arxiv_id: str, limit: int, recent: bool) -> list[dict[str, Any]]:
    arxiv_id = _normalise_id(arxiv_id)
    with _connect() as connection:
        concepts = connection.execute(
            "SELECT keyword FROM cso_keywords WHERE arxiv_id=? ORDER BY score DESC LIMIT 20",
            (arxiv_id,),
        ).fetchall()
        terms = [row["keyword"] for row in concepts]
        if not terms:
            return []
        limit = max(1, min(int(limit), 1000))
        scores = _candidate_scores(connection, terms, exclude=arxiv_id)
        rows = _candidate_papers(connection, scores, limit, recent=recent)
        authors = _authors_for(connection, (row["arxiv_id"] for row in rows))
        return [_paper_dict(row, authors.get(row["arxiv_id"])) for row in rows]


async def papers_from_recommendation_api_allCs(corpus_id=None, limit: int = 100):
    papers = await asyncio.to_thread(_recommend_sync, corpus_id, limit, False)
    return {"recommendedPapers": papers}


async def papers_from_recommendation_api_recent(corpus_id=None, limit: int = 100):
    papers = await asyncio.to_thread(_recommend_sync, corpus_id, limit, True)
    return {"recommendedPapers": papers}


async def getSpecterEmbedding_paperIDs(paperIDs):
    # Retained only for upstream API compatibility. CoT5 embeds locally retrieved
    # title/abstract text with its configured OpenAI embedding model.
    papers = await get_paper_data(paperIDs, batch_wise=True)
    return [{"corpusId": p["corpusId"], "embedding": None} for p in papers if p]
