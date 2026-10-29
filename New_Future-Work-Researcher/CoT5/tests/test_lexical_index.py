import sqlite3

import pytest

from cot5.lexical_index import (
    MissingLexicalIndexError, build_index, index_status, search_papers,
)


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "papers.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY, title TEXT, abstract TEXT,
                categories TEXT, created_date TEXT, is_deleted INTEGER);
            CREATE TABLE authors (arxiv_id TEXT, keyname TEXT, forenames TEXT, position INTEGER);
        """)
        db.executemany("INSERT INTO papers VALUES(?,?,?,?,?,?)", [
            ("1", "RANSAC for affine estimation", "Robust geometric alignment", "cs.CV", "2024-01-01", 0),
            ("2", "Graph models", "A graph study", "cs.AI", "2023-01-01", 0),
            ("3", "Affine deleted", "RANSAC", "cs.CV", "2022-01-01", 1),
        ])
        db.execute("INSERT INTO authors VALUES('1','Kim','Min',0)")
    return path


def test_missing_build_search_and_source_unchanged(source):
    sidecar = source.with_suffix(".fts.sqlite3")
    original = source.read_bytes()
    assert index_status(source, sidecar)["state"] == "missing"
    with pytest.raises(MissingLexicalIndexError):
        search_papers("affine", source_path=source, index_path=sidecar)
    assert build_index(source, sidecar, batch_size=1)["indexed_count"] == 2
    found = search_papers("RANSAC affine", source_path=source, index_path=sidecar)
    assert [paper["paperId"] for paper in found] == ["1"]
    assert found[0]["authors"] == [{"name": "Min Kim"}]
    assert found[0]["url"] == "https://arxiv.org/abs/1"
    assert source.read_bytes() == original


def test_safe_query_and_stale_detection(source):
    sidecar = source.with_suffix(".fts.sqlite3")
    build_index(source, sidecar)
    assert search_papers('affine OR "', source_path=source, index_path=sidecar)
    assert search_papers('"* ()', source_path=source, index_path=sidecar) == []
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO papers VALUES('4','Transformer retrieval','New','cs.IR','2025-01-01',0)")
    assert index_status(source, sidecar)["state"] == "stale"
    with pytest.raises(MissingLexicalIndexError):
        search_papers("transformer", source_path=source, index_path=sidecar)
    assert build_index(source, sidecar)["indexed_count"] == 3
    assert search_papers("transformer", source_path=source, index_path=sidecar)[0]["paperId"] == "4"


def test_resumes_building_sidecar(source):
    sidecar = source.with_suffix(".fts.sqlite3")
    build_index(source, sidecar, batch_size=1)
    with sqlite3.connect(sidecar) as db:
        db.execute("UPDATE metadata SET value='building' WHERE key='state'")
        db.execute("UPDATE metadata SET value='1' WHERE key='last_id'")
        db.execute("UPDATE metadata SET value='1' WHERE key='indexed_count'")
        db.execute("DELETE FROM papers_fts WHERE arxiv_id='2'")
    assert build_index(source, sidecar, batch_size=1)["indexed_count"] == 2
    assert len(search_papers("graph", source_path=source, index_path=sidecar)) == 1


def test_complete_metadata_cannot_hide_missing_fts_rows(source):
    sidecar = source.with_suffix(".fts.sqlite3")
    build_index(source, sidecar)
    with sqlite3.connect(sidecar) as db:
        db.execute("DELETE FROM papers_fts WHERE arxiv_id='2'")
    assert index_status(source, sidecar)["state"] == "stale"
    with pytest.raises(MissingLexicalIndexError):
        search_papers("graph", source_path=source, index_path=sidecar)
    assert build_index(source, sidecar)["state"] == "complete"
    assert search_papers("graph", source_path=source, index_path=sidecar)[0]["paperId"] == "2"


def test_complete_metadata_cannot_hide_wrong_count(source):
    sidecar = source.with_suffix(".fts.sqlite3")
    build_index(source, sidecar)
    with sqlite3.connect(sidecar) as db:
        db.execute("UPDATE metadata SET value='999' WHERE key='indexed_count'")
    assert index_status(source, sidecar)["state"] == "stale"


def test_korean_query_retrieves_korean_title(source):
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO papers VALUES('5','영상 정합 기술','특징점 기반 정합',"
                   "'cs.CV','2024-01-01',0)")
    sidecar = source.with_suffix(".fts.sqlite3")
    build_index(source, sidecar)
    assert [paper["paperId"] for paper in search_papers(
        "영상 정합", source_path=source, index_path=sidecar
    )] == ["5"]
