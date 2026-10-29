"""Output-only deduplication must preserve evidence and internal state."""
import pytest
import CoT5
from cot5 import pipeline


@pytest.mark.parametrize("module", [CoT5, pipeline])
def test_exact_duplicates_are_serialized_once(module):
    candidates = [{"paper_id": "p1", "equivalent": False}]
    overlaps = {"paper": {"checked_count": 1, "candidates": candidates}}
    result = module.NoveltyCheckResult(
        idea_title="idea", verdict=module.Verdict("NOVEL", "reason"),
        review="review", evaluated_paper_count=1,
        dropped_by_cutoff_count=0, iterations=1,
        equivalence_results=candidates, overlaps=overlaps,
    )
    output = result.as_dict()
    assert "equivalence_results" not in output
    assert "evaluated_paper_count" not in output
    assert output["overlaps"] == overlaps
    assert result.equivalence_results == candidates
    assert result.evaluated_paper_count == 1
    assert result.as_dict() == output


@pytest.mark.parametrize("module", [CoT5, pipeline])
def test_distinct_or_missing_values_are_not_dropped(module):
    result = module.NoveltyCheckResult(
        idea_title="idea", verdict=module.Verdict("NOVEL", "reason"),
        review="review", evaluated_paper_count=2,
        dropped_by_cutoff_count=0, iterations=1,
        equivalence_results=[{"paper_id": "p1"}],
        overlaps={"paper": {"checked_count": 1, "candidates": []}},
    )
    output = result.as_dict()
    assert output["evaluated_paper_count"] == 2
    assert output["equivalence_results"] == [{"paper_id": "p1"}]
    result.overlaps = {}
    assert "equivalence_results" in result.as_dict()
    assert "evaluated_paper_count" in result.as_dict()