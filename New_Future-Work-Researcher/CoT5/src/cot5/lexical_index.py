"""Resumable, read-only-source FTS5 index for local arXiv title/abstract search."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any


# Match Unicode letters/digits (including Hangul) while excluding underscores,
# which FTS5's default unicode61 tokenizer treats as punctuation.
_TOKEN = re.compile(r"[^\W_]{2,}", re.UNICODE)
_STOPWORDS = {"about", "after", "based", "from", "into", "method", "model", "paper",
              "research", "that", "their", "this", "using", "with", "for", "and", "the",
              "title", "problem", "purpose", "proposed", "mechanism", "motivation",
              "evaluation", "application", "domain"}


class MissingLexicalIndexError(RuntimeError):
    """The sidecar index must be built (or rebuilt) before lexical search."""


def _paths(source_path: str | Path | None, index_path: str | Path | None) -> tuple[Path, Path]:
    source = Path(source_path or os.getenv("ARXIV_DB_PATH", r"D:\experiment\arxiv_cs_ai.db")).expanduser().resolve()
    index = Path(index_path or os.getenv("ARXIV_FTS_PATH", f"{source}.fts.sqlite3")).expanduser().resolve()
    if source == index:
        raise ValueError("FTS sidecar must differ from source database")
    return source, index


def _source_signature(source: Path) -> str:
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"arXiv source database is missing or empty: {source}")
    stat = source.stat()
    return f"{source}|{stat.st_size}|{stat.st_mtime_ns}"


def _connect_source(source: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(connection.execute("SELECT key, value FROM metadata"))
    except sqlite3.DatabaseError:
        return {}


def index_status(source_path: str | Path | None = None, index_path: str | Path | None = None) -> dict[str, Any]:
    """Report missing/building/complete/stale without creating or changing either DB."""
    source, index = _paths(source_path, index_path)
    signature = _source_signature(source)
    result: dict[str, Any] = {"state": "missing", "source_path": str(source),
                              "index_path": str(index), "indexed_count": 0}
    if not index.is_file():
        return result
    try:
        with sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True) as connection:
            metadata = _metadata(connection)
            result["indexed_count"] = int(metadata.get("indexed_count", "0"))
            result["state"] = (metadata.get("state", "stale")
                               if metadata.get("signature") == signature else "stale")
            if result["state"] not in {"building", "complete"}:
                result["state"] = "stale"
            if result["state"] == "complete":
                indexed_rows = connection.execute("SELECT count(*) FROM papers_fts").fetchone()[0]
                with _connect_source(source) as source_db:
                    eligible_rows = source_db.execute(
                        "SELECT count(*) FROM papers WHERE is_deleted=0"
                    ).fetchone()[0]
                if indexed_rows != result["indexed_count"] or eligible_rows != indexed_rows:
                    result["state"] = "stale"
    except (sqlite3.DatabaseError, ValueError):
        result["state"] = "stale"
    return result


def build_index(source_path: str | Path | None = None, index_path: str | Path | None = None,
                *, batch_size: int = 1000) -> dict[str, Any]:
    """Index active papers in bounded commits; resume an interrupted same-source build."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    source, index = _paths(source_path, index_path)
    signature = _source_signature(source)
    index.parent.mkdir(parents=True, exist_ok=True)
    with _connect_source(source) as source_db, sqlite3.connect(index, timeout=30) as sidecar:
        sidecar.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        sidecar.execute("CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(arxiv_id UNINDEXED, title, abstract)")
        metadata = _metadata(sidecar)
        if metadata.get("signature") != signature or (
            metadata.get("state") == "complete" and index_status(source, index)["state"] != "complete"
        ):
            sidecar.execute("DELETE FROM papers_fts")
            sidecar.execute("DELETE FROM metadata")
            sidecar.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", [
                ("signature", signature), ("state", "building"), ("last_id", ""),
                ("indexed_count", "0"),
            ])
            sidecar.commit()
            metadata = _metadata(sidecar)
        if metadata.get("state") == "complete":
            return index_status(source, index)
        last_id = metadata.get("last_id", "")
        count = int(metadata.get("indexed_count", "0"))
        while True:
            rows = source_db.execute(
                "SELECT arxiv_id, title, abstract FROM papers "
                "WHERE is_deleted=0 AND arxiv_id>? ORDER BY arxiv_id LIMIT ?",
                (last_id, batch_size),
            ).fetchall()
            if not rows:
                break
            sidecar.executemany("INSERT INTO papers_fts(arxiv_id,title,abstract) VALUES(?,?,?)", rows)
            last_id = rows[-1]["arxiv_id"]
            count += len(rows)
            sidecar.executemany("UPDATE metadata SET value=? WHERE key=?", [
                (last_id, "last_id"), (str(count), "indexed_count"),
            ])
            sidecar.commit()
        if _source_signature(source) != signature:
            raise RuntimeError("arXiv source changed during FTS build; rebuild the sidecar")
        expected = source_db.execute("SELECT count(*) FROM papers WHERE is_deleted=0").fetchone()[0]
        actual = sidecar.execute("SELECT count(*) FROM papers_fts").fetchone()[0]
        if actual != expected or actual != count:
            sidecar.execute("UPDATE metadata SET value='stale' WHERE key='state'")
            sidecar.commit()
            raise RuntimeError("FTS index coverage mismatch; rebuild the sidecar")
        sidecar.execute("UPDATE metadata SET value='complete' WHERE key='state'")
        sidecar.commit()
    return index_status(source, index)


def _match_query(query: str) -> str:
    tokens = list(dict.fromkeys(token.lower() for token in _TOKEN.findall(query)
                                if token.lower() not in _STOPWORDS))[:12]
    return " OR ".join(f'"{token}"' for token in tokens)


def search_papers(query: str, *, source_path: str | Path | None = None,
                  index_path: str | Path | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Search FTS and hydrate S2-like metadata from the unchanged source DB."""
    source, index = _paths(source_path, index_path)
    status = index_status(source, index)
    if status["state"] != "complete":
        raise MissingLexicalIndexError(
            f"FTS index is {status['state']}: {index}. Run python -m cot5.lexical_cli build."
        )
    match = _match_query(query)
    if not match or limit <= 0:
        return []
    with sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True) as sidecar:
        ids = [row[0] for row in sidecar.execute(
            "SELECT arxiv_id FROM papers_fts WHERE papers_fts MATCH ? "
            "ORDER BY bm25(papers_fts, 0, 3, 1), arxiv_id LIMIT ?", (match, limit)
        )]
    if not ids:
        return []
    with _connect_source(source) as db:
        placeholders = ",".join("?" for _ in ids)
        rows = db.execute(f"SELECT * FROM papers WHERE is_deleted=0 AND arxiv_id IN ({placeholders})", ids)
        by_id = {row["arxiv_id"]: row for row in rows}
        authors: dict[str, list[dict[str, str]]] = {paper_id: [] for paper_id in ids}
        try:
            for row in db.execute(
                f"SELECT arxiv_id, keyname, forenames FROM authors WHERE arxiv_id IN ({placeholders}) "
                "ORDER BY arxiv_id, position", ids
            ):
                name = " ".join(part for part in (row["forenames"], row["keyname"]) if part)
                authors[row["arxiv_id"]].append({"name": name})
        except sqlite3.OperationalError:
            pass
        results = []
        for paper_id in ids:
            row = by_id.get(paper_id)
            if row is None:
                continue
            created = row["created_date"]
            results.append({
                "corpusId": paper_id, "paperId": paper_id,
                "url": f"https://arxiv.org/abs/{paper_id}", "title": row["title"],
                "year": int(created[:4]) if created and created[:4].isdigit() else None,
                "publicationDate": created, "abstract": row["abstract"],
                "authors": authors[paper_id], "fieldsOfStudy": (row["categories"] or "").split(),
                "s2FieldsOfStudy": [], "citationCount": None, "venue": "arXiv",
                "openAccessPdf": {"url": f"https://arxiv.org/pdf/{paper_id}"},
            })
        return results
