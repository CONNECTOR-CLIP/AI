import unittest

from cot5.verdict import Verdict, apply_equivalence_override, resolve_verdict


class VerdictTests(unittest.TestCase):
    def test_zero_papers_is_uncertain(self):
        v = resolve_verdict("novel", 0)
        self.assertEqual(v.classification, "UNCERTAIN")

    def test_parse_failure_is_uncertain(self):
        v = resolve_verdict(None, 5)
        self.assertEqual(v.classification, "UNCERTAIN")

    def test_novel_with_single_paper_is_trusted(self):
        # 문헌이 1건이라도 있으면 novel 판정을 그대로 신뢰한다(최소 문헌 수 임계값 없음).
        v = resolve_verdict("novel", 1)
        self.assertEqual(v.classification, "NOVEL")

    def test_novel_with_many_papers_is_novel(self):
        v = resolve_verdict("novel", 5)
        self.assertEqual(v.classification, "NOVEL")

    def test_not_novel_with_one_paper_is_trusted(self):
        v = resolve_verdict("not novel", 1)
        self.assertEqual(v.classification, "NOT_NOVEL")

    def test_unrecognized_category_is_uncertain(self):
        v = resolve_verdict("maybe", 5)
        self.assertEqual(v.classification, "UNCERTAIN")

    def test_category_is_case_insensitive(self):
        v = resolve_verdict("NOVEL", 5)
        self.assertEqual(v.classification, "NOVEL")


class EquivalenceOverrideTests(unittest.TestCase):
    def test_no_override_when_nothing_equivalent(self):
        original = Verdict("NOVEL", "reason")
        result = apply_equivalence_override(original, equivalent_found=False)
        self.assertIs(result, original)

    def test_overrides_novel_to_not_novel(self):
        original = Verdict("NOVEL", "종합적으로는 새로워 보임")
        result = apply_equivalence_override(original, equivalent_found=True, equivalent_paper_title="X")
        self.assertEqual(result.classification, "NOT_NOVEL")
        self.assertIn("X", result.reason)

    def test_overrides_uncertain_to_not_novel(self):
        # 개별 비교에서 명확한 동등 근거가 나오면, 종합 판단이 UNCERTAIN이었어도 확정한다.
        original = Verdict("UNCERTAIN", "검색 부족")
        result = apply_equivalence_override(original, equivalent_found=True, equivalent_paper_title="Y")
        self.assertEqual(result.classification, "NOT_NOVEL")


if __name__ == "__main__":
    unittest.main()
