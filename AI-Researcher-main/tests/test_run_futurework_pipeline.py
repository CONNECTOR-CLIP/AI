import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integration.run_futurework_pipeline import build_futurework_draft, run_pipeline
import main_ai_researcher


def _make_db(tmp_path: Path) -> str:
    db_path = tmp_path / "arxiv_cs_ai.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY, title TEXT, abstract TEXT, categories TEXT, primary_category TEXT, created_date TEXT, updated_date TEXT, is_deleted INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY AUTOINCREMENT, arxiv_id TEXT, position INTEGER, keyname TEXT, forenames TEXT)")
    conn.execute("INSERT INTO papers VALUES ('1111.0001', 'Paper One', 'Abstract One', 'cs.AI', 'cs.AI', '2024-02-01', '2024-02-02', 0)")
    conn.execute("INSERT INTO authors (arxiv_id, position, keyname, forenames) VALUES ('1111.0001', 1, 'Kim', 'Dana')")
    conn.commit()
    conn.close()
    return str(db_path)


def test_run_pipeline_writes_selected_input_and_draft(tmp_path: Path) -> None:
    db_path = _make_db(tmp_path)
    selected_path = tmp_path / "runtime_inputs" / "selected_papers.json"
    output_path = tmp_path / "runtime_outputs" / "futurework_draft.md"
    payload = run_pipeline(
        query="future work",
        db_path=db_path,
        selected_papers_path=str(selected_path),
        output_path=str(output_path),
        search_results=[{"arxiv_id": "1111.0001", "title": "ignored", "abstract": "ignored", "authors": [], "categories": ["cs.AI"], "published": "ignored"}],
    )
    assert selected_path.exists()
    selected_payload = json.loads(selected_path.read_text(encoding="utf-8"))
    assert selected_payload["query"] == "future work"
    assert selected_payload["selected_papers"][0]["paper_id"] == "1111.0001"
    assert output_path.exists()
    draft = output_path.read_text(encoding="utf-8")
    assert "# Future Work" in draft
    assert "# Draft" in draft
    assert payload["selected_papers"][0]["selection_index"] == 1


def test_build_futurework_draft_shape() -> None:
    draft = build_futurework_draft(
        {
            "query": "test query",
            "selected_papers": [
                {
                    "selection_index": 1,
                    "paper_id": "1111.0001",
                    "title": "Paper One",
                    "abstract": "Abstract One",
                    "authors": ["Dana Kim"],
                    "arxiv_primary_category": "cs.AI",
                    "arxiv_categories": ["cs.AI"],
                    "published": "2024-02-01",
                    "node_id": "cs.AI::topic",
                    "cfo_label_id": "topic",
                }
            ],
        }
    )
    assert "# Selected Papers" in draft
    assert "# Future Work" in draft
    assert "# Draft" in draft


def test_main_ai_researcher_disables_legacy_modes(monkeypatch) -> None:
    for mode in ["Detailed Idea Description", "Reference-Based Ideation", "Paper Generation Agent"]:
        try:
            main_ai_researcher.main_ai_researcher("q", None, mode)
        except RuntimeError as exc:
            assert str(exc) == main_ai_researcher.DISABLED_MODE_MESSAGE
        else:
            raise AssertionError(f"Expected RuntimeError for {mode}")


def test_main_ai_researcher_runs_narrowed_mode(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_runner(*, query: str, reference: str | None, db_path: str, repo_root: str | None = None):
        captured.update({"query": query, "reference": reference, "db_path": db_path, "repo_root": repo_root})
        return {"query": query, "selected_papers": []}

    monkeypatch.setattr(main_ai_researcher, "_run_narrowed_futurework_pipeline", fake_runner)
    monkeypatch.setenv("SEARCHENGINE_SQLITE_DB_PATH", str(tmp_path / "arxiv_cs_ai.db"))
    result = main_ai_researcher.main_ai_researcher("topic query", "results.json", "Narrowed Future Work Pipeline")
    assert result["query"] == "topic query"
    assert captured["query"] == "topic query"
    assert captured["reference"] == "results.json"
