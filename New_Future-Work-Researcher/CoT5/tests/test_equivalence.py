import asyncio
import unittest

from cot5.equivalence import check_all_papers

NOT_EQUIVALENT = {
    "equivalent": False,
    "purpose_overlap": "",
    "mechanism_overlap": "",
    "evaluation_overlap": "",
    "application_overlap": "",
    "critical_difference": "다른 접근",
    "evidence_from_abstract": "",
    "confidence": 0.2,
}

EQUIVALENT = dict(NOT_EQUIVALENT, equivalent=True, critical_difference="", confidence=0.9)


class FakeProvider:
    model = "fake"

    def __init__(self, verdict_by_title=None, default=NOT_EQUIVALENT):
        self.verdict_by_title = verdict_by_title or {}
        self.default = default
        self.calls = 0

    def evaluate(self, *, instructions, document, schema, schema_name):
        self.calls += 1
        for title, verdict in self.verdict_by_title.items():
            if title in document:
                return verdict
        return self.default


class CheckAllPapersTests(unittest.TestCase):
    def test_empty_paper_list_returns_false_without_calling_provider(self):
        provider = FakeProvider()
        found, results = asyncio.run(check_all_papers(provider, "idea text", []))
        self.assertFalse(found)
        self.assertEqual(results, [])
        self.assertEqual(provider.calls, 0)

    def test_no_equivalent_paper_returns_false(self):
        provider = FakeProvider()
        papers = [{"title": "A", "abstract": "..."}, {"title": "B", "abstract": "..."}]
        found, results = asyncio.run(check_all_papers(provider, "idea text", papers))
        self.assertFalse(found)
        self.assertEqual(len(results), 2)

    def test_one_equivalent_paper_returns_true(self):
        provider = FakeProvider(verdict_by_title={"B": EQUIVALENT})
        papers = [{"title": "A", "abstract": "..."}, {"title": "B", "abstract": "..."}]
        found, results = asyncio.run(check_all_papers(provider, "idea text", papers))
        self.assertTrue(found)
        # 하나를 찾아도 나머지 논문 비교 결과까지 전부 남긴다(감사용).
        self.assertEqual(len(results), 2)
        self.assertEqual(provider.calls, 2)

    def test_result_carries_paper_title(self):
        provider = FakeProvider(verdict_by_title={"B": EQUIVALENT})
        papers = [{"title": "B", "abstract": "...", "paperId": "p1"}]
        found, results = asyncio.run(check_all_papers(provider, "idea text", papers))
        self.assertTrue(found)
        self.assertEqual(results[0]["paper_title"], "B")
        self.assertEqual(results[0]["paper_id"], "p1")


if __name__ == "__main__":
    unittest.main()
