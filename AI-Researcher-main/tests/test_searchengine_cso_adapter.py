import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.searchengine_cso_adapter import SearchEngineCSOAdapter


def _make_db(tmp_path: Path) -> str:
    db_path = tmp_path / "arxiv_cs_ai.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, categories TEXT, primary_category TEXT, created_date TEXT, updated_date TEXT, is_deleted INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY AUTOINCREMENT, arxiv_id TEXT, position INTEGER, keyname TEXT, forenames TEXT)")
    conn.execute("INSERT INTO papers VALUES ('1234.5678', 'DB Title A', 'DB Abstract A', 'cs.AI cs.LG', 'cs.AI', '2024-01-02', '2024-01-03', 0)")
    conn.execute("INSERT INTO papers VALUES ('9999.0001', 'DB Title B', 'DB Abstract B', 'cs.LG', 'cs.LG', '2023-05-06', '2023-05-07', 0)")
    conn.execute("INSERT INTO authors (arxiv_id, position, keyname, forenames) VALUES ('1234.5678', 1, 'Kim', 'Ada')")
    conn.execute("INSERT INTO authors (arxiv_id, position, keyname, forenames) VALUES ('1234.5678', 2, 'Lee', 'Bob')")
    conn.execute("INSERT INTO authors (arxiv_id, position, keyname, forenames) VALUES ('9999.0001', 1, 'Park', 'Cara')")
    conn.commit()
    conn.close()
    return str(db_path)


def test_normalize_search_results_uses_db_metadata(tmp_path: Path) -> None:
    adapter = SearchEngineCSOAdapter(db_path=_make_db(tmp_path), tree_builder=lambda payload: {"roots": []})
    cso_input, metadata_map = adapter.normalize_search_results([
        {
            "arxiv_id": "1234.5678",
            "title": "Search Title Override",
            "abstract": "Search Abstract Override",
            "authors": ["Wrong Name"],
            "categories": ["wrong.category"],
            "published": "1999-01-01",
        }
    ])
    paper = cso_input["input_papers"][0]
    assert paper["paper_id"] == "1234.5678"
    assert paper["title"] == "DB Title A"
    assert paper["abstract"] == "DB Abstract A"
    assert paper["arxiv_primary_category"] == "cs.AI"
    assert paper["arxiv_categories"] == ["cs.AI", "cs.LG"]
    assert paper["authors"] == ["Ada Kim", "Bob Lee"]
    assert paper["year"] == 2024
    assert metadata_map["1234.5678"]["published"] == "2024-01-02"


def test_select_first_leaf_papers_is_deterministic(tmp_path: Path) -> None:
    adapter = SearchEngineCSOAdapter(db_path=_make_db(tmp_path), tree_builder=lambda payload: {"roots": []})
    metadata_map = {
        "1234.5678": {
            "paper_id": "1234.5678",
            "title": "DB Title A",
            "abstract": "DB Abstract A",
            "authors": ["Ada Kim"],
            "arxiv_primary_category": "cs.AI",
            "arxiv_categories": ["cs.AI"],
            "published": "2024-01-02",
        },
        "9999.0001": {
            "paper_id": "9999.0001",
            "title": "DB Title B",
            "abstract": "DB Abstract B",
            "authors": ["Cara Park"],
            "arxiv_primary_category": "cs.LG",
            "arxiv_categories": ["cs.LG"],
            "published": "2023-05-06",
        },
    }
    tree = {
        "roots": [
            {
                "arxiv_primary_category": "cs.LG",
                "intermediate_nodes": [{"node_id": "cs.LG::x", "children": [{"paper_id": "9999.0001", "assignment": {"cfo_label_id": "x"}}]}],
            },
            {
                "arxiv_primary_category": "cs.AI",
                "intermediate_nodes": [{"node_id": "cs.AI::y", "children": [{"paper_id": "1234.5678", "assignment": {"cfo_label_id": "y"}}]}],
            },
        ]
    }
    selected = adapter.select_first_leaf_papers(tree_output=tree, metadata_map=metadata_map, limit=10)
    assert [paper["paper_id"] for paper in selected] == ["1234.5678", "9999.0001"]
    assert [paper["selection_index"] for paper in selected] == [1, 2]


def test_build_from_search_results_rejoins_metadata(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)

    def fake_tree_builder(payload: dict) -> dict:
        assert payload["input_papers"][0]["paper_id"] == "1234.5678"
        return {
            "roots": [
                {
                    "arxiv_primary_category": "cs.AI",
                    "intermediate_nodes": [
                        {
                            "node_id": "cs.AI::machine_learning",
                            "children": [
                                {
                                    "paper_id": "1234.5678",
                                    "title": "Leaf title",
                                    "assignment": {"cfo_label_id": "machine_learning"},
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    adapter = SearchEngineCSOAdapter(db_path=db_path, tree_builder=fake_tree_builder)
    payload = adapter.build_from_search_results(
        query="graph learning",
        raw_results=[{"arxiv_id": "1234.5678", "title": "ignored", "abstract": "ignored", "authors": [], "categories": ["cs.AI"], "published": "ignored"}],
    )
    assert payload["query"] == "graph learning"
    assert payload["selected_papers"][0]["title"] == "DB Title A"
    assert payload["selected_papers"][0]["abstract"] == "DB Abstract A"
    assert payload["selected_papers"][0]["published"] == "2024-01-02"
    assert payload["selected_papers"][0]["cfo_label_id"] == "machine_learning"
