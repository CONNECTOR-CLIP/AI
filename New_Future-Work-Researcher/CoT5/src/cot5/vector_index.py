"""Chunked, resumable SPECTER2 index over the local arXiv database.

The manifest is committed only after its chunk has been atomically written. A
query never reads an incomplete index, so interrupted builds are safe to resume.
"""

from __future__ import annotations

import json
import heapq
import os
import sqlite3
from pathlib import Path

import numpy as np


_VERSION = 2
_MANIFEST = "manifest.json"


class IndexUnavailable(RuntimeError):
    """The full-corpus index is missing, incomplete, or stale."""


def _encoder_signature() -> dict:
    return {
        "base": os.getenv("SPECTER2_BASE_MODEL", "allenai/specter2_base"),
        "adapter": os.getenv("SPECTER2_ADAPTER_MODEL", "allenai/specter2"),
        "max_length": int(os.getenv("SPECTER2_MAX_LENGTH", "512")),
    }


def _encode(papers: list[dict]) -> np.ndarray:
    # Lazy import avoids model initialization for status checks and tests.
    from noveltychecker.ranking.embedding import _encode_papers

    values = np.asarray(_encode_papers(papers), dtype=np.float32)
    if values.ndim != 2 or len(values) != len(papers) or not np.isfinite(values).all():
        raise ValueError("SPECTER2 returned invalid vectors")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("SPECTER2 returned a zero vector")
    return values / norms


def _fingerprint(db_path: Path) -> dict:
    try:
        stat = db_path.resolve().stat()
    except OSError as exc:
        raise IndexUnavailable(f"arXiv database unavailable: {db_path}") from exc
    return {"path": str(db_path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _read_manifest(index_dir: Path) -> dict | None:
    path = index_dir / _MANIFEST
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as stream:
            manifest = json.load(stream)
    except (OSError, ValueError) as exc:
        raise IndexUnavailable(f"Invalid vector index manifest: {path}") from exc
    if manifest.get("version") != _VERSION:
        raise IndexUnavailable("Unsupported vector index version; rebuild the index")
    return manifest


def _write_manifest(index_dir: Path, manifest: dict) -> None:
    temporary = index_dir / "manifest.json.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, index_dir / _MANIFEST)


def index_status(index_dir: str | Path, db_path: str | Path) -> dict:
    """Return state without loading model weights or vector chunks."""
    index_dir, db_path = Path(index_dir), Path(db_path)
    try:
        fingerprint = _fingerprint(db_path)
        manifest = _read_manifest(index_dir)
    except IndexUnavailable as exc:
        return {"state": "unavailable", "complete": False, "reason": str(exc)}
    if manifest is None:
        return {"state": "missing", "complete": False, "reason": "index not built"}
    if manifest.get("database") != fingerprint:
        return {"state": "stale", "complete": False, "reason": "database changed since indexing"}
    if manifest.get("encoder") != _encoder_signature():
        return {"state": "stale", "complete": False, "reason": "SPECTER2 configuration changed"}
    chunks = manifest.get("chunks", [])
    if sum(chunk.get("count", 0) for chunk in chunks) != manifest.get("count"):
        return {"state": "unavailable", "complete": False, "reason": "index chunk counts inconsistent"}
    for chunk in chunks:
        path = index_dir / chunk["file"]
        if not path.is_file() or path.stat().st_size != chunk.get("bytes"):
            return {"state": "unavailable", "complete": False, "reason": "index chunk missing or truncated"}
    complete = bool(manifest.get("complete"))
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as connection:
        eligible = connection.execute(
            "SELECT count(*) FROM papers WHERE is_deleted=0 "
            "AND trim(coalesce(title,''))!='' AND trim(coalesce(abstract,''))!=''"
        ).fetchone()[0]
    if complete and manifest.get("count") != eligible:
        return {"state": "stale", "complete": False, "reason": "index coverage differs from database"}
    return {
        "state": "complete" if complete else "building",
        "complete": complete,
        "count": manifest.get("count", 0),
        "eligible_papers": eligible,
        "covered_papers": manifest.get("count", 0),
        "chunks": len(chunks),
        "reason": "" if complete else "build interrupted; resume with build",
    }


def build_index(
    db_path: str | Path, index_dir: str | Path, *, chunk_size: int = 512
) -> dict:
    """Encode every active paper with a title and abstract; resume at last commit.

    A changed DB requires an explicit fresh index directory. This avoids mixing
    vectors from different snapshots and never silently discards a prior build.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    db_path, index_dir = Path(db_path), Path(index_dir)
    fingerprint = _fingerprint(db_path)
    index_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_manifest(index_dir)
    if manifest is None:
        manifest = {
            "version": _VERSION, "database": fingerprint, "dimension": None,
            "encoder": _encoder_signature(), "count": 0, "last_id": "",
            "chunks": [], "complete": False,
        }
        _write_manifest(index_dir, manifest)
    elif manifest.get("database") != fingerprint:
        raise IndexUnavailable("Database changed since indexing; use a fresh index directory")
    elif manifest.get("encoder") != _encoder_signature():
        raise IndexUnavailable("SPECTER2 configuration changed; use a fresh index directory")
    if manifest["complete"]:
        return index_status(index_dir, db_path)

    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        while True:
            rows = connection.execute(
                "SELECT arxiv_id, title, abstract, created_date FROM papers "
                "WHERE is_deleted=0 AND trim(coalesce(title,''))!='' "
                "AND trim(coalesce(abstract,''))!='' AND arxiv_id>? "
                "ORDER BY arxiv_id LIMIT ?",
                (manifest["last_id"], chunk_size),
            ).fetchall()
            if not rows:
                break
            papers = [dict(row) for row in rows]
            vectors = _encode(papers)
            dimension = int(vectors.shape[1])
            if manifest["dimension"] not in (None, dimension):
                raise IndexUnavailable("Embedding dimension changed; use a fresh index directory")
            number = len(manifest["chunks"])
            filename = f"chunk-{number:06d}.npz"
            temporary = index_dir / (filename + ".tmp")
            with temporary.open("wb") as stream:
                np.savez(
                    stream,
                    ids=np.asarray([row["arxiv_id"] for row in rows]),
                    dates=np.asarray([row["created_date"] or "" for row in rows]),
                    vectors=vectors,
                )
            os.replace(temporary, index_dir / filename)
            manifest["chunks"].append({
                "file": filename, "count": len(rows),
                "bytes": (index_dir / filename).stat().st_size,
            })
            manifest["count"] += len(rows)
            manifest["last_id"] = rows[-1]["arxiv_id"]
            manifest["dimension"] = dimension
            if _fingerprint(db_path) != fingerprint:
                raise IndexUnavailable("Database changed during indexing; use a fresh index directory")
            _write_manifest(index_dir, manifest)
    finally:
        connection.close()
    manifest["complete"] = True
    _write_manifest(index_dir, manifest)
    return index_status(index_dir, db_path)


def search_index(
    idea_text: str, *, index_dir: str | Path, db_path: str | Path,
    top_k: int = 100, cutoff_date: str | None = None,
) -> list[dict]:
    """Return nearest active papers in the existing s2_api paper shape."""
    from noveltychecker.utils import s2_api

    if top_k < 1:
        return []
    index_dir, db_path = Path(index_dir), Path(db_path)
    status = index_status(index_dir, db_path)
    if not status["complete"]:
        raise IndexUnavailable(f"Vector index {status['state']}: {status['reason']}")
    manifest = _read_manifest(index_dir)
    if manifest["count"] == 0:
        return []
    query = _encode([{"title": idea_text, "abstract": ""}])[0]
    if len(query) != manifest["dimension"]:
        raise IndexUnavailable("Query embedding dimension differs from indexed vectors")
    # Keep only scores and on-disk positions in memory; do not copy each vector
    # into Python. Load embeddings only for the final top-k papers.
    best: list[tuple[float, str, str, int]] = []
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for chunk in manifest["chunks"]:
            with np.load(index_dir / chunk["file"], allow_pickle=False) as data:
                ids, dates, vectors = data["ids"], data["dates"], data["vectors"]
                if (vectors.ndim != 2 or vectors.shape != (len(ids), len(query))
                        or len(dates) != len(ids) or len(ids) != chunk["count"]):
                    raise IndexUnavailable(f"Corrupt vector index chunk: {chunk['file']}")
                scores = vectors @ query
                if cutoff_date:
                    scores[(dates != "") & (dates > cutoff_date)] = -np.inf
                candidate_count = min(top_k, len(scores))
                if not candidate_count:
                    continue
                positions = np.argpartition(scores, -candidate_count)[-candidate_count:]
                for position in positions:
                    score = float(scores[position])
                    if not np.isfinite(score):
                        continue
                    candidate = (score, str(ids[position]), chunk["file"], int(position))
                    if len(best) < top_k:
                        heapq.heappush(best, candidate)
                    elif candidate > best[0]:
                        heapq.heapreplace(best, candidate)
        best.sort(reverse=True)
        ids = [item[1] for item in best]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"SELECT * FROM papers WHERE is_deleted=0 AND arxiv_id IN ({placeholders})", ids
        ).fetchall()
        by_id = {row["arxiv_id"]: row for row in rows}
        authors = s2_api._authors_for(connection, ids)
        embeddings: dict[tuple[str, int], list[float]] = {}
        by_chunk: dict[str, list[int]] = {}
        for _, _, filename, position in best:
            by_chunk.setdefault(filename, []).append(position)
        for filename, positions in by_chunk.items():
            with np.load(index_dir / filename, allow_pickle=False) as data:
                vectors = data["vectors"]
                for position in positions:
                    embeddings[(filename, position)] = vectors[position].tolist()
        return [
            {**s2_api._paper_dict(by_id[paper_id], authors.get(paper_id)),
             "source": "vector", "vector_score": score,
             "embedding": embeddings[(filename, position)]}
            for score, paper_id, filename, position in best if paper_id in by_id
        ]
    finally:
        connection.close()
