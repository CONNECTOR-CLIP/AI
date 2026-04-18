# test_tree_builder.py
"""
TDD-based pytest test suite for tree_builder.py.
Tests cover all 5 mandatory cases plus additional invariant checks.
"""

import os
import sqlite3
import tempfile

import pytest

from tree_builder import TreeBuilder, build_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def leaf_ids(tree: dict) -> list[str]:
    """Collect all paper_id values from every leaf in the tree."""
    out = []
    for r in tree["roots"]:
        for m in r["intermediate_nodes"]:
            for c in m["children"]:
                out.append(c["paper_id"])
    return out


def _make_paper(
    paper_id: str,
    title: str = "A Paper Title",
    abstract: str = "This paper studies something important.",
    arxiv_id: str | None = None,
    primary_cat: str | None = "cs.AI",
    categories: list | None = None,
    source: str = "arxiv_api",
) -> dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "arxiv_primary_category": primary_cat,
        "arxiv_categories": categories or (["cs.AI"] if primary_cat else []),
        "authors": ["Test Author"],
        "year": 2025,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Mock CSO classifier: deterministic, keyword-rich
# ---------------------------------------------------------------------------

class _MockCSO:
    """
    Minimal mock that mimics a CSO-based classifier.
    Deterministic: paper_id suffix drives which of 3 labels is top-1.
    """

    _LABELS = {
        "planning": {
            "keywords": ["planning", "uncertainty", "decision", "agent", "policy"],
            "parents": ["artificial_intelligence"],
        },
        "machine_learning": {
            "keywords": ["machine learning", "neural network", "training", "model", "gradient"],
            "parents": ["artificial_intelligence"],
        },
        "knowledge_representation": {
            "keywords": ["knowledge", "ontology", "reasoning", "logic", "representation"],
            "parents": ["artificial_intelligence"],
        },
    }

    _LABEL_LIST = list(_LABELS.keys())

    def classify(self, text: str, top_k: int = 5) -> list[dict]:
        """Return deterministic scores based on keyword overlap with text."""
        text_lower = text.lower()
        scores = []
        for label_id, data in self._LABELS.items():
            score = sum(1.0 for kw in data["keywords"] if kw in text_lower)
            score = (score / len(data["keywords"])) * 0.6 + 0.3
            scores.append({"label_id": label_id, "score": round(score, 4)})
        scores.sort(key=lambda x: (-x["score"], x["label_id"]))
        return scores[:top_k]

    def initial_keywords(self, label_id: str) -> list[str]:
        return list(self._LABELS.get(label_id, {}).get("keywords", []))

    def parents(self, label_id: str) -> list[str]:
        return list(self._LABELS.get(label_id, {}).get("parents", []))

    def info(self) -> dict:
        return {"name": "MockCSO", "version": "test", "citations": []}


class _AmbiguousMockCSO(_MockCSO):
    """
    Variant where all papers get nearly identical scores for two labels,
    triggering soft-overlap detection and re-expression.
    """

    def classify(self, text: str, top_k: int = 5) -> list[dict]:
        # planning and machine_learning have scores only 0.02 apart → within margin 0.08
        return [
            {"label_id": "planning", "score": 0.72},
            {"label_id": "machine_learning", "score": 0.70},
            {"label_id": "knowledge_representation", "score": 0.40},
        ][:top_k]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_tree.db")


@pytest.fixture
def mock_cso():
    return _MockCSO()


@pytest.fixture
def ambiguous_cso():
    return _AmbiguousMockCSO()


@pytest.fixture
def sample_input():
    """4 cs.AI papers with enough variety to create ≥2 intermediate nodes."""
    return {
        "run_config": {
            "max_iterations": 3,
            "top_k": 3,
            "ambiguity_margin": 0.08,
            "max_intermediate_nodes_per_root": 3,
            "allow_arxiv_fetch": False,
            "root_allowlist": ["cs.AI"],
        },
        "input_papers": [
            _make_paper(
                "p1",
                title="Planning with Uncertainty in LLM Agents",
                abstract="We study planning under uncertainty for agent policy decision making.",
            ),
            _make_paper(
                "p2",
                title="Knowledge Representation for Tool-Using Agents",
                abstract="We propose an ontology reasoning knowledge representation logic framework.",
            ),
            _make_paper(
                "p3",
                title="Deep Learning for Vision",
                abstract="Neural network machine learning gradient training model for image tasks.",
            ),
            _make_paper(
                "p4",
                title="Uncertainty Quantification in Neural Models",
                abstract="Machine learning model uncertainty estimation via neural network training.",
            ),
        ],
    }


@pytest.fixture
def dup_input():
    """Two papers sharing the same paper_id."""
    return {
        "input_papers": [
            _make_paper("dup1"),
            _make_paper("dup1"),  # duplicate!
        ]
    }


@pytest.fixture
def singleton_root_input():
    """Exactly 1 paper with cs.AI primary category."""
    return {
        "run_config": {
            "max_iterations": 2,
            "top_k": 3,
            "ambiguity_margin": 0.08,
            "max_intermediate_nodes_per_root": 3,
            "allow_arxiv_fetch": False,
            "root_allowlist": ["cs.AI"],
        },
        "input_papers": [
            _make_paper(
                "single",
                title="Only Paper",
                abstract="This is the only paper in this root category.",
            )
        ],
    }


@pytest.fixture
def missing_primary_input():
    """Paper with arxiv_primary_category=None, allow_arxiv_fetch=False."""
    return {
        "run_config": {
            "max_iterations": 2,
            "top_k": 3,
            "ambiguity_margin": 0.08,
            "max_intermediate_nodes_per_root": 3,
            "allow_arxiv_fetch": False,
            "root_allowlist": None,  # accept all roots
        },
        "input_papers": [
            _make_paper(
                "noprim1",
                primary_cat=None,
                categories=["cs.LG", "stat.ML"],
                abstract="Neural network training gradient descent optimization.",
            ),
            _make_paper(
                "noprim2",
                primary_cat=None,
                categories=["cs.LG"],
                abstract="Deep learning model machine learning classification.",
            ),
        ],
    }


@pytest.fixture
def ambiguous_input():
    """Papers that will get near-identical top-1/top-2 scores."""
    return {
        "run_config": {
            "max_iterations": 4,
            "top_k": 3,
            "ambiguity_margin": 0.08,
            "max_intermediate_nodes_per_root": 3,
            "allow_arxiv_fetch": False,
            "root_allowlist": ["cs.AI"],
        },
        "input_papers": [
            _make_paper(
                "amb1",
                title="Ambiguous Paper A",
                abstract="Some text about planning and machine learning equally.",
            ),
            _make_paper(
                "amb2",
                title="Ambiguous Paper B",
                abstract="Another ambiguous text about agents and neural networks.",
            ),
            _make_paper(
                "amb3",
                title="Ambiguous Paper C",
                abstract="More ambiguous content about decisions and gradients.",
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Test 1: duplicate paper_id → ValueError
# ---------------------------------------------------------------------------

def test_duplicate_paper_id_raises_value_error(mock_cso, dup_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        builder.build_tree(dup_input)


# ---------------------------------------------------------------------------
# Test 2: singleton root → infeasible warning, children==1 allowed
# ---------------------------------------------------------------------------

def test_singleton_root_warns_infeasible(mock_cso, singleton_root_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(singleton_root_input)

    warnings = tree["validation"]["warnings"]
    assert any(
        "infeasible" in w.lower() or "singleton" in w.lower() for w in warnings
    ), f"Expected infeasible/singleton warning, got: {warnings}"

    # children == 1 must be allowed (not an error)
    errors = tree["validation"]["errors"]
    assert not any("children" in e.lower() for e in errors), \
        f"Unexpected children error for singleton: {errors}"

    # The single paper must still appear in the tree
    ids = leaf_ids(tree)
    assert "single" in ids


# ---------------------------------------------------------------------------
# Test 3: ambiguous top1/top2 → was_reexpressed flag set
# ---------------------------------------------------------------------------

def test_ambiguous_triggers_reexpression(ambiguous_cso, ambiguous_input, tmp_db):
    builder = TreeBuilder(cso_instance=ambiguous_cso, db_path=tmp_db)
    tree = builder.build_tree(ambiguous_input)

    found = any(
        c["assignment"]["was_reexpressed"]
        for r in tree["roots"]
        for m in r["intermediate_nodes"]
        for c in m["children"]
    )
    assert found, "Expected at least one leaf with was_reexpressed=True"


# ---------------------------------------------------------------------------
# Test 4: missing primary category + allow_arxiv_fetch=False → warning/error
# ---------------------------------------------------------------------------

def test_missing_primary_category_without_fetch(mock_cso, missing_primary_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(missing_primary_input)

    all_messages = tree["validation"]["warnings"] + tree["validation"]["errors"]
    assert any(
        "primary" in m.lower() or "missing" in m.lower() or "unknown" in m.lower()
        or "estimated" in m.lower() or "inferred" in m.lower()
        for m in all_messages
    ), f"Expected primary-category warning/error, got: {all_messages}"


# ---------------------------------------------------------------------------
# Test 5: all paper_ids in output exactly once (no missing, no duplicate)
# ---------------------------------------------------------------------------

def test_all_paper_ids_in_output_exactly_once(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)

    input_ids = {p["paper_id"] for p in sample_input["input_papers"]}
    output_ids = leaf_ids(tree)

    # Coverage: no missing
    assert input_ids == set(output_ids), \
        f"Missing or extra papers. Input: {input_ids}, Output: {set(output_ids)}"

    # Uniqueness: no duplicates
    assert len(output_ids) == len(set(output_ids)), \
        f"Duplicate paper_ids in output: {output_ids}"


# ---------------------------------------------------------------------------
# Additional invariant tests
# ---------------------------------------------------------------------------

def test_no_duplicate_assignment(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)
    ids = leaf_ids(tree)
    assert len(ids) == len(set(ids)), f"Duplicate assignment detected: {ids}"


def test_intermediate_count_per_root(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)
    for r in tree["roots"]:
        count = len(r["intermediate_nodes"])
        assert 1 <= count <= 3, \
            f"Root {r['arxiv_primary_category']} has {count} intermediate nodes (expected 1-3)"


def test_output_schema_valid(mock_cso, sample_input, tmp_db):
    from jsonschema import Draft202012Validator
    from schemas import OUTPUT_SCHEMA

    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)

    validator = Draft202012Validator(OUTPUT_SCHEMA)
    errors = list(validator.iter_errors(tree))
    assert not errors, f"Output schema errors: {[e.message for e in errors]}"


def test_sqlite_persistence(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    builder.build_tree(sample_input)

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT COUNT(*) FROM cfo_runs").fetchone()[0]
    conn.close()
    assert rows >= 1, "Expected at least 1 row in cfo_runs after build_tree"


def test_validation_stats_correct(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)

    stats = tree["validation"]["stats"]
    n = len(sample_input["input_papers"])
    assert stats["num_input_papers"] == n
    assert stats["num_assigned_leaves"] == n
    assert stats["num_roots"] >= 1
    assert stats["num_intermediate_nodes"] >= 1


def test_build_tree_module_function(mock_cso, sample_input, tmp_db):
    """Module-level build_tree() convenience function works."""
    tree = build_tree(sample_input, cso_instance=mock_cso, db_path=tmp_db)
    assert "roots" in tree
    assert len(leaf_ids(tree)) == len(sample_input["input_papers"])


def test_provenance_recorded(mock_cso, sample_input, tmp_db):
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)
    prov = tree["provenance"]
    assert "cfo_classifier_info" in prov
    assert "assumptions" in prov
    assert isinstance(prov["adapter_fallbacks"], list)


def test_children_min2_when_possible(mock_cso, sample_input, tmp_db):
    """When root has ≥2 papers, every intermediate node must have ≥2 children."""
    builder = TreeBuilder(cso_instance=mock_cso, db_path=tmp_db)
    tree = builder.build_tree(sample_input)

    for r in tree["roots"]:
        root_papers = sum(len(m["children"]) for m in r["intermediate_nodes"])
        if root_papers < 2:
            continue  # singleton root: exception allowed
        for m in r["intermediate_nodes"]:
            assert len(m["children"]) >= 2, (
                f"Intermediate node '{m['node_id']}' has only "
                f"{len(m['children'])} children (expected ≥2)"
            )
