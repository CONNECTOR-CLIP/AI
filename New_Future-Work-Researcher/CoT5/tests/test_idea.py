import unittest

from cot5.idea import ResearchIdea, SeedPaper


class IdeaTests(unittest.TestCase):
    def test_to_text_includes_required_fields(self):
        idea = ResearchIdea(title="T", problem="P", proposed_method="M")
        text = idea.to_text()
        self.assertIn("Title: T", text)
        self.assertIn("Problem and purpose: P", text)
        self.assertIn("Proposed mechanism: M", text)

    def test_to_text_omits_empty_optional_fields(self):
        idea = ResearchIdea(title="T", problem="P", proposed_method="M")
        text = idea.to_text()
        self.assertNotIn("Motivation:", text)
        self.assertNotIn("Evaluation:", text)
        self.assertNotIn("Application domain:", text)

    def test_to_text_includes_optional_fields_when_present(self):
        idea = ResearchIdea(title="T", problem="P", proposed_method="M", motivation="why", evaluation_plan="how", application_domain="where")
        text = idea.to_text()
        self.assertIn("Motivation: why", text)
        self.assertIn("Evaluation: how", text)
        self.assertIn("Application domain: where", text)

    def test_seed_paper_ids_filters_empty(self):
        idea = ResearchIdea(
            title="T", problem="P", proposed_method="M",
            seed_papers=[SeedPaper(semantic_scholar_id="abc"), SeedPaper(semantic_scholar_id="")],
        )
        self.assertEqual(idea.seed_paper_ids, ["abc"])

    def test_from_dict_roundtrip(self):
        data = {
            "title": "T", "problem": "P", "proposed_method": "M",
            "seed_papers": [{"title": "S", "doi": "", "semantic_scholar_id": "abc"}],
            "cutoff_date": "2026-08-18",
        }
        idea = ResearchIdea.from_dict(data)
        self.assertEqual(idea.seed_paper_ids, ["abc"])
        self.assertEqual(idea.cutoff_date, "2026-08-18")


if __name__ == "__main__":
    unittest.main()
