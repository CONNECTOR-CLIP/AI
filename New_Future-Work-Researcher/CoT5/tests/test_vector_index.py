import json
import sqlite3

import pytest

from cot5 import vector_index
from cot5.vector_cli import main
from noveltychecker.ranking import embedding


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "papers.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, "
            "categories TEXT, created_date TEXT, is_deleted INTEGER);"
            "CREATE TABLE authors (arxiv_id TEXT, position INTEGER, keyname TEXT, forenames TEXT);"
        )
        connection.executemany(
            "INSERT INTO papers VALUES(?,?,?,?,?,?)",
            [
                ("1", "alpha", "first", "cs.AI", "2023-01-01", 0),
                ("2", "beta", "second", "cs.AI", "2024-01-01", 0),
                ("3", "gamma", "third", "cs.AI", "2025-01-01", 0),
                ("4", "deleted", "fourth", "cs.AI", "2022-01-01", 1),
                ("5", "no abstract", "", "cs.AI", "2022-01-01", 0),
            ],
        )
    return path


def fake_encode(papers):
    mapping = {
        "alpha": [1.0, 0.0], "beta": [0.7, 0.7], "gamma": [0.0, 1.0],
        "alpha idea": [2.0, 0.0],
    }
    return [mapping[paper["title"]] for paper in papers]


def test_build_search_coverage_and_cutoff(database, tmp_path, monkeypatch):
    monkeypatch.setattr(embedding, "_encode_papers", fake_encode)
    index = tmp_path / "index"
    assert vector_index.index_status(index, database)["state"] == "missing"
    status = vector_index.build_index(database, index, chunk_size=2)
    assert status["state"] == "complete"
    assert status["covered_papers"] == status["eligible_papers"] == 3
    assert status["chunks"] == 2
    papers = vector_index.search_index("alpha idea", index_dir=index, db_path=database, top_k=2)
    assert [paper["paperId"] for paper in papers] == ["1", "2"]
    assert papers[0]["source"] == "vector"
    assert papers[0]["vector_score"] == pytest.approx(1.0)
    assert papers[0]["embedding"] == [1.0, 0.0]
    earlier = vector_index.search_index(
        "alpha idea", index_dir=index, db_path=database, top_k=3, cutoff_date="2023-12-31"
    )
    assert [paper["paperId"] for paper in earlier] == ["1"]


def test_interrupted_build_resumes_and_stale_rejected(database, tmp_path, monkeypatch):
    index = tmp_path / "index"
    calls = 0

    def interrupted(papers):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted")
        return fake_encode(papers)

    monkeypatch.setattr(embedding, "_encode_papers", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        vector_index.build_index(database, index, chunk_size=2)
    assert vector_index.index_status(index, database)["state"] == "building"
    with pytest.raises(vector_index.IndexUnavailable, match="building"):
        vector_index.search_index("alpha idea", index_dir=index, db_path=database)
    monkeypatch.setattr(embedding, "_encode_papers", fake_encode)
    assert vector_index.build_index(database, index, chunk_size=2)["count"] == 3
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE papers SET abstract='changed' WHERE arxiv_id='1'")
    assert vector_index.index_status(index, database)["state"] == "stale"
    with pytest.raises(vector_index.IndexUnavailable, match="stale"):
        vector_index.search_index("alpha idea", index_dir=index, db_path=database)


def test_cli_default_directory(database, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(embedding, "_encode_papers", fake_encode)
    monkeypatch.delenv("COT5_VECTOR_INDEX_DIR", raising=False)
    monkeypatch.setattr("sys.argv", ["vector_cli", "build", "--db", str(database), "--chunk-size", "2"])
    main()
    assert json.loads(capsys.readouterr().out)["count"] == 3
    assert (tmp_path / "papers.db.specter2" / "manifest.json").is_file()
    monkeypatch.setattr("sys.argv", ["vector_cli", "status", "--db", str(database)])
    main()
    assert json.loads(capsys.readouterr().out)["state"] == "complete"


def test_truncated_chunk_is_unavailable(database, tmp_path, monkeypatch):
    monkeypatch.setattr(embedding, "_encode_papers", fake_encode)
    index = tmp_path / "index"
    vector_index.build_index(database, index, chunk_size=2)
    chunk = index / "chunk-000000.npz"
    chunk.write_bytes(chunk.read_bytes()[:20])
    assert vector_index.index_status(index, database)["state"] == "unavailable"
    with pytest.raises(vector_index.IndexUnavailable, match="truncated"):
        vector_index.search_index("alpha idea", index_dir=index, db_path=database)
