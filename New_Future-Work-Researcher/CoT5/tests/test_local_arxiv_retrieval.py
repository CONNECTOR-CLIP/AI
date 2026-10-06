import asyncio
import sqlite3

import pytest

from noveltychecker.utils import s2_api


@pytest.fixture()
def arxiv_db(tmp_path, monkeypatch):
    path = tmp_path / "arxiv.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE papers (
            arxiv_id TEXT PRIMARY KEY, title TEXT NOT NULL, abstract TEXT,
            categories TEXT NOT NULL, primary_category TEXT, license TEXT,
            submitter TEXT, created_date TEXT, updated_date TEXT,
            oai_identifier TEXT, oai_datestamp TEXT, is_deleted INTEGER NOT NULL,
            harvested_at TEXT NOT NULL
        );
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY, arxiv_id TEXT NOT NULL, position INTEGER NOT NULL,
            keyname TEXT NOT NULL, forenames TEXT
        );
        CREATE TABLE cso_keywords (
            arxiv_id TEXT NOT NULL, keyword TEXT NOT NULL, score REAL NOT NULL,
            source TEXT NOT NULL, PRIMARY KEY (arxiv_id, keyword)
        );
        CREATE INDEX idx_cso_keyword ON cso_keywords(keyword);
        """
    )
    papers = [
        ("2401.00001", "Retrieval augmented language models", "Grounded generation", "cs.AI cs.CL", "cs.AI", "2024-01-01"),
        ("2402.00002", "Graph reasoning systems", "Reasoning over graphs", "cs.AI", "cs.AI", "2024-02-01"),
        ("2301.00003", "Old retrieval work", "Earlier retrieval", "cs.IR", "cs.IR", "2023-01-01"),
    ]
    connection.executemany(
        "INSERT INTO papers(arxiv_id,title,abstract,categories,primary_category,created_date,is_deleted,harvested_at) VALUES(?,?,?,?,?,?,0,'now')",
        papers,
    )
    connection.executemany(
        "INSERT INTO authors(id,arxiv_id,position,keyname,forenames) VALUES(?,?,?,?,?)",
        [(1, "2401.00001", 0, "Kim", "Min"), (2, "2402.00002", 0, "Lee", "Jin")],
    )
    connection.executemany(
        "INSERT INTO cso_keywords(arxiv_id,keyword,score,source) VALUES(?,?,?,?)",
        [
            ("2401.00001", "retrieval augmented generation", 1.0, "semantic"),
            ("2401.00001", "language models", 0.9, "semantic"),
            ("2402.00002", "graph reasoning", 1.0, "semantic"),
            ("2301.00003", "retrieval augmented generation", 0.8, "semantic"),
        ],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("ARXIV_DB_PATH", str(path))
    return path


def test_keyword_search_returns_local_paper_shape(arxiv_db):
    result = asyncio.run(
        s2_api.papers_from_search_api("retrieval augmented generation", limit=10)
    )
    assert [paper["paperId"] for paper in result["data"]] == ["2401.00001", "2301.00003"]
    assert result["data"][0]["authors"] == [{"name": "Min Kim"}]
    assert result["data"][0]["url"] == "https://arxiv.org/abs/2401.00001"


def test_snippet_search_preserves_upstream_wrapper(arxiv_db):
    result = asyncio.run(
        s2_api.papers_from_search_api("graph reasoning", search_type="snippet", limit=10)
    )
    assert result["data"][0]["paper"]["corpusId"] == "2402.00002"


def test_batch_lookup_and_recommendations_are_local(arxiv_db):
    papers = asyncio.run(s2_api.get_paper_data(["ARXIV:2401.00001"], batch_wise=True))
    assert papers[0]["title"] == "Retrieval augmented language models"

    recommendations = asyncio.run(
        s2_api.papers_from_recommendation_api_allCs("2401.00001", limit=10)
    )
    assert [p["paperId"] for p in recommendations["recommendedPapers"]] == ["2301.00003"]


def test_empty_database_fails_with_actionable_message(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    path.touch()
    monkeypatch.setenv("ARXIV_DB_PATH", str(path))
    with pytest.raises(RuntimeError, match="missing or empty"):
        asyncio.run(s2_api.papers_from_search_api("graph reasoning"))
