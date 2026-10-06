import pytest

from cot5.future_work import ideas_from_future_work, is_future_work_payload


def payload():
    return {
        "future_work_proposals": [
            {
                "id": 3,
                "reference_papers": ["Paper A", "Paper B"],
                "background_and_gap": "Existing systems do not handle the gap.",
                "proposed_direction": "Build a grounded system to address the gap.",
                "expected_contribution": "Improve reliability.",
                "novelty_assessment": "REFINED",
                "novelty_note": "Uses a narrower unexplored setting.",
            }
        ]
    }


def test_converts_future_work_proposal_to_cot5_idea():
    idea = ideas_from_future_work(payload())[0]
    assert idea.problem == "Existing systems do not handle the gap."
    assert idea.proposed_method == "Build a grounded system to address the gap."
    assert [paper.title for paper in idea.seed_papers] == ["Paper A", "Paper B"]
    assert "Expected contribution: Improve reliability." in idea.motivation
    assert "Upstream novelty note:" in idea.motivation


def test_detects_payload_and_rejects_missing_required_text():
    assert is_future_work_payload(payload())
    broken = {"future_work_proposals": [{"proposed_direction": "method"}]}
    with pytest.raises(ValueError, match="background_and_gap"):
        ideas_from_future_work(broken)
