import copy
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

from research_plan.cli import run_verify
from research_plan.evidence import build_evidence
from research_plan.extract import extract_plan
from research_plan.inputs import load_run
from research_plan.verify import TITLE_MIN_SIMILARITY, ArxivLookup, check_names, check_numbers, title_similarity, verify
from research_plan.write import write_documents
from test_extract import FakeProvider, good_responses
from test_write import PROSE, skeleton

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"


class FakeArxiv:
    """arXiv 대신 화이트리스트 제목을 돌려준다. overrides로 특정 ID의 결과를 바꾼다."""

    def __init__(self, plan, overrides=None):
        self.titles = {w["arxiv_id"]: w["title"] for w in plan["citation_whitelist"]}
        self.overrides = overrides or {}
        self.calls = 0

    def __call__(self, ids):
        self.calls += 1
        return {i: self.overrides.get(i, {"found": i in self.titles, "title": self.titles.get(i, "")}) for i in ids}


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = build_evidence(load_run(RUN), 6)
        cls.plan, _, _ = extract_plan(evidence, FakeProvider(good_responses()))
        docs, _, ok = write_documents(
            cls.plan, FakeProvider({"research_plan": [PROSE], "paper_skeleton": [skeleton()]})
        )
        assert ok
        cls.docs = docs

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def lookup(self, overrides=None, offline=False):
        fetch = FakeArxiv(self.plan, overrides)
        return ArxivLookup(self.cache, offline=offline, fetch=fetch), fetch

    def test_clean_documents_pass(self):
        lookup, _ = self.lookup()
        report = verify(self.plan, self.docs, lookup)
        self.assertEqual(report["status"], "pass", report["errors"])
        self.assertTrue(report["citations"])
        self.assertTrue(all(c["status"] == "확인" for c in report["citations"]))

    def test_cache_is_reused_offline(self):
        lookup, fetch = self.lookup()
        verify(self.plan, self.docs, lookup)
        self.assertEqual(fetch.calls, 1)
        offline, fetch2 = self.lookup(offline=True)
        report = verify(self.plan, self.docs, offline)
        self.assertEqual(fetch2.calls, 0)
        self.assertEqual(report["status"], "pass")

    def test_offline_without_cache_only_warns(self):
        lookup, _ = self.lookup(offline=True)
        report = verify(self.plan, self.docs, lookup)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(any("확인하지 못함" in w for w in report["warnings"]))

    def test_missing_and_mismatched_papers_fail(self):
        lookup, _ = self.lookup({
            "2310.11511": {"found": False, "title": ""},
            "2005.11401": {"found": True, "title": "A Completely Different Paper About Vision"},
        })
        report = verify(self.plan, self.docs, lookup)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("2310.11511" in e and "존재하지 않음" in e for e in report["errors"]))
        self.assertTrue(any("2005.11401" in e and "제목" in e for e in report["errors"]))

    def test_network_error_is_a_warning(self):
        def broken(ids):
            raise urllib.error.URLError("no network")
        report = verify(self.plan, self.docs, ArxivLookup(self.cache, fetch=broken))
        self.assertEqual(report["status"], "pass")
        self.assertTrue(any("arXiv 조회 실패" in w for w in report["warnings"]))

    def test_citation_outside_whitelist_fails(self):
        docs = dict(self.docs)
        docs["paper_skeleton.md"] += "\n- See [2401.00001].\n"
        lookup, _ = self.lookup()
        report = verify(self.plan, docs, lookup)
        self.assertTrue(any("2401.00001" in e and "화이트리스트" in e for e in report["errors"]))

    def test_invented_number_is_an_error(self):
        docs = dict(self.docs)
        docs["research_plan.md"] += "\n학습에는 약 73000개의 질의를 쓴다.\n"
        errors = check_numbers(self.plan, docs)
        self.assertEqual(len(errors), 1)
        self.assertIn("73000", errors[0])

    def test_structure_numbers_are_ignored(self):
        self.assertEqual(check_numbers(self.plan, self.docs), [])

    def test_unknown_name_is_a_warning(self):
        docs = dict(self.docs)
        docs["paper_skeleton.md"] += "\n- We evaluate on HotpotQA with GPT-9 and Self-RAG-based variants.\n"
        warnings = check_names(self.plan, docs)
        names = " ".join(warnings)
        self.assertIn("HotpotQA", names)
        self.assertIn("GPT-9", names)
        self.assertNotIn("Self-RAG", names)

    def test_new_forbidden_phrases(self):
        docs = dict(self.docs)
        docs["paper_skeleton.md"] += "\n- This is state-of-the-art and results show gains.\n"
        docs["research_plan.md"] += "\n성능이 개선되었다.\n"
        lookup, _ = self.lookup()
        errors = verify(self.plan, docs, lookup)["errors"]
        joined = " ".join(errors)
        for phrase in ("state-of-the-art", "results show", "개선되었다"):
            self.assertIn(phrase, joined)

    def test_arxiv_id_at_sentence_end_is_a_citation_not_a_number(self):
        docs = dict(self.docs)
        docs["research_plan.md"] += "\n참고: Self-RAG, arXiv:2310.11511.\n없는 논문 2401.00001.\n"
        self.assertEqual(check_numbers(self.plan, docs), [])
        lookup, _ = self.lookup()
        errors = verify(self.plan, docs, lookup)["errors"]
        self.assertTrue(any("2401.00001" in e for e in errors))

    def test_section_numbers_and_tags_are_ignored(self):
        docs = dict(self.docs)
        docs["paper_skeleton.md"] += "\n- 2.1 Related work\n4.2. Training details\n- H1과 RQ1을 검증한다. DB를 쓴다.\n"
        self.assertEqual(check_numbers(self.plan, docs), [])
        self.assertEqual(check_names(self.plan, docs), [])

    def test_title_similarity(self):
        self.assertEqual(title_similarity("Self-RAG: Learning", "self rag learning"), 1.0)
        self.assertLess(title_similarity("Retrieval-Augmented Generation", "Image Segmentation"), TITLE_MIN_SIMILARITY)

    def test_cli_writes_report(self):
        folder = Path(self.tmp.name)
        plan_path = folder / "plan.reviewed.json"
        plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
        for name, text in self.docs.items():
            (folder / name).write_text(text, encoding="utf-8")
        lookup, _ = self.lookup()
        with redirect_stdout(io.StringIO()):
            code = run_verify(plan_path, offline=False, lookup=lookup)
        self.assertEqual(code, 0)
        report = json.loads((folder / "verify_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")


if __name__ == "__main__":
    unittest.main()
