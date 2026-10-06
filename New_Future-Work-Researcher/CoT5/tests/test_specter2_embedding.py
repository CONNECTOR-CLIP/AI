import asyncio

from noveltychecker.ranking import embedding


def test_embedding_results_are_attached_by_corpus_id(monkeypatch):
    captured = []

    def fake_encode(papers):
        captured.extend(papers)
        return [[1.0, 2.0], [3.0, 4.0]]

    monkeypatch.setattr(embedding, "_encode_papers", fake_encode)
    result = asyncio.run(
        embedding.get_embeddings_ideapapers(
            [
                {"corpusId": "a", "title": "A", "abstract": "first"},
                {"corpusId": "b", "title": "B", "abstract": None},
            ]
        )
    )
    assert [paper["title"] for paper in captured] == ["A", "B"]
    assert result["a"]["embedding"] == [1.0, 2.0]
    assert result["b"]["embedding"] == [3.0, 4.0]


def test_missing_runtime_dependencies_have_actionable_error(monkeypatch):
    monkeypatch.setattr(embedding, "_model", None)
    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    try:
        embedding._load_model()
    except RuntimeError as exc:
        assert "torch, transformers, and adapters" in str(exc)
    else:
        raise AssertionError("missing dependencies should fail clearly")
