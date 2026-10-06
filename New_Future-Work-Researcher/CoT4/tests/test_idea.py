import unittest

from cot4.idea import Constraints, ResearchIdea


class ConstraintsTests(unittest.TestCase):
    def test_is_empty_true_when_all_blank(self):
        self.assertTrue(Constraints().is_empty())

    def test_is_empty_false_when_one_field_set(self):
        self.assertFalse(Constraints(timeline="3 months").is_empty())

    def test_to_text_placeholder_when_empty(self):
        self.assertEqual(Constraints().to_text(), "(제약 조건이 제공되지 않음)")

    def test_to_text_includes_only_set_fields(self):
        text = Constraints(compute_budget="1 GPU").to_text()
        self.assertIn("Compute budget: 1 GPU", text)
        self.assertNotIn("Timeline:", text)

    def test_from_dict_none_is_empty(self):
        self.assertTrue(Constraints.from_dict(None).is_empty())


class ResearchIdeaTests(unittest.TestCase):
    def test_to_text_includes_required_fields(self):
        idea = ResearchIdea(title="T", problem="P", proposed_method="M")
        text = idea.to_text()
        self.assertIn("Title: T", text)
        self.assertIn("Problem: P", text)
        self.assertIn("Proposed method: M", text)

    def test_to_text_omits_empty_evaluation_plan(self):
        idea = ResearchIdea(title="T", problem="P", proposed_method="M")
        self.assertNotIn("Evaluation plan:", idea.to_text())

    def test_from_dict_builds_constraints(self):
        data = {
            "title": "T", "problem": "P", "proposed_method": "M",
            "constraints": {"timeline": "6 weeks"},
        }
        idea = ResearchIdea.from_dict(data)
        self.assertEqual(idea.constraints.timeline, "6 weeks")
        self.assertFalse(idea.constraints.is_empty())

    def test_from_dict_missing_constraints_key_is_empty(self):
        data = {"title": "T", "problem": "P", "proposed_method": "M"}
        idea = ResearchIdea.from_dict(data)
        self.assertTrue(idea.constraints.is_empty())


if __name__ == "__main__":
    unittest.main()
