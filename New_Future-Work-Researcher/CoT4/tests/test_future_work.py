import pytest

from cot4.future_work import ideas_from_future_work, is_future_work_payload


def payload():
    return {
        "constraints": {"timeline": "3 months", "team_skills": "Python"},
        "future_work_proposals": [
            {
                "id": 2,
                "reference_papers": ["Paper A"],
                "background_and_gap": "A deployment gap remains.",
                "proposed_direction": "Implement and evaluate an efficient adapter.",
                "expected_contribution": "Reduce deployment cost.",
            }
        ],
    }


def test_converts_future_work_proposal_to_cot4_idea():
    idea = ideas_from_future_work(payload())[0]
    assert idea.proposed_method == "Implement and evaluate an efficient adapter."
    assert "Reference papers: Paper A" in idea.problem
    assert "Expected contribution: Reduce deployment cost." in idea.problem
    assert idea.constraints.timeline == "3 months"
    assert idea.constraints.team_skills == "Python"


def test_detects_payload_and_rejects_missing_required_text():
    assert is_future_work_payload(payload())
    broken = {"future_work_proposals": [{"background_and_gap": "gap"}]}
    with pytest.raises(ValueError, match="proposed_direction"):
        ideas_from_future_work(broken)
