import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_plan.cli import main
from research_plan.evidence import build_evidence
from research_plan.inputs import InputError, load_run, title_matches
from research_plan.schemas import SOURCE_PREFIXES

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"


def _sources(obj):
    """evidence 안의 모든 source 값을 모은다."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "source" and isinstance(value, str):
                yield value
            else:
                yield from _sources(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _sources(value)


class RealRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load_run(RUN)

    def test_all_eight_candidates_are_paired(self):
        self.assertEqual(len(self.loaded.candidates), 8)
        self.assertEqual([c.cot3_id for c in self.loaded.candidates], [f"C{i}" for i in range(2, 10)])
        self.assertEqual(self.loaded.warnings, [])

    def test_future_work_hash_matches_manifest(self):
        self.assertTrue(self.loaded.input_files["future_work"]["matches_manifest_sha256"])

    def test_classification_counts_match_manifest(self):
        counts = {}
        for c in self.loaded.candidates:
            counts[c.classification] = counts.get(c.classification, 0) + 1
        self.assertEqual(counts, self.loaded.manifest["cot5_classifications"])

    def test_papers_follow_cot3_order(self):
        self.assertEqual([(p.key, p.arxiv_id) for p in self.loaded.papers],
                         [("P1", "2005.11401"), ("P2", "2310.11511")])

    def test_idea6_is_unsupported_token(self):
        candidate = self.loaded.candidate(6)
        self.assertEqual(candidate.cot3_id, "C7")
        self.assertEqual(candidate.classification, "NOVEL")
        self.assertIn('"unsupported" reflection token', candidate.title)

    def test_idea6_resolves_self_rag_limitation_quote(self):
        upstream = build_evidence(self.loaded, 6)["upstream_evidence"]
        self.assertEqual([e["id"] for e in upstream], ["P2:L1"])
        self.assertIn("we do not consider", upstream[0]["text"])
        self.assertEqual(upstream[0]["arxiv_id"], "2310.11511")

    def test_subgoal_reference_is_resolved(self):
        upstream = build_evidence(self.loaded, 3)["upstream_evidence"]
        self.assertEqual([e["id"] for e in upstream], ["P1:G4", "P2:L1"])
        self.assertIn("not_achieved", upstream[0]["text"])

    def test_seed_papers_describe_what_each_paper_did(self):
        seeds = build_evidence(self.loaded, 6)["seed_papers"]
        self.assertEqual([(s["paper"], s["arxiv_id"]) for s in seeds],
                         [("P1", "2005.11401"), ("P2", "2310.11511")])
        rag = {g["id"]: g for g in seeds[0]["subgoals"]}
        self.assertIn("provenance", rag["G2"]["text"])
        self.assertEqual(rag["G2"]["source"], "cot1.P1.subgoals[1]")
        self.assertEqual(rag["G4"]["status"], "not_achieved")
        self.assertTrue(seeds[1]["research_problem"]["text"])

    def test_every_source_uses_allowed_prefix(self):
        for index in range(1, 9):
            evidence = build_evidence(self.loaded, index, allow_not_novel=True)
            for source in _sources(evidence):
                self.assertTrue(source.startswith(SOURCE_PREFIXES), source)

    def test_whitelist_has_seeds_and_cot5_papers(self):
        evidence = build_evidence(self.loaded, 6)
        ids = [w["arxiv_id"] for w in evidence["citation_whitelist"]]
        self.assertEqual(ids[:2], ["2005.11401", "2310.11511"])
        paper_ids = {r["id"] for r in evidence["novelty"]["related"] if r["kind"] == "paper"}
        self.assertTrue(paper_ids <= set(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_not_novel_is_refused_by_default(self):
        with self.assertRaises(InputError):
            build_evidence(self.loaded, 1)
        evidence = build_evidence(self.loaded, 1, allow_not_novel=True)
        self.assertTrue(any("NOT_NOVEL" in w for w in evidence["warnings"]))

    def test_failed_search_and_weak_grounding_are_warned(self):
        warnings = build_evidence(self.loaded, 4, allow_not_novel=True)["warnings"]
        self.assertTrue(any("grounding=UNSURE" in w for w in warnings))
        self.assertTrue(any("web 검색 실패" in w for w in warnings))

    def test_build_is_repeatable(self):
        self.assertEqual(build_evidence(self.loaded, 6), build_evidence(self.loaded, 6))

    def test_index_out_of_range(self):
        for index in (0, 9):
            with self.assertRaises(InputError):
                self.loaded.candidate(index)


class BrokenInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.run_dir = self.tmp / "run"
        shutil.copytree(RUN, self.run_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _edit(self, rel, change):
        path = self.run_dir / rel
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_swapped_order_is_rejected(self):
        self._edit("CoT4/examples/result.json", lambda d: d["results"].reverse())
        with self.assertRaisesRegex(InputError, "CoT4 제목"):
            load_run(self.run_dir)

    def test_count_mismatch_is_rejected(self):
        self._edit("CoT5/examples/result.json", lambda d: d["results"].pop())
        with self.assertRaisesRegex(InputError, "후보 수"):
            load_run(self.run_dir)

    def test_cot3_text_mismatch_is_rejected(self):
        def change(d):
            d[0]["proposed_direction"] = "Something else entirely."
        self._edit("CoT3/examples/result.json", change)
        with self.assertRaisesRegex(InputError, "CoT3 C2"):
            load_run(self.run_dir)

    def test_hash_mismatch_is_only_a_warning(self):
        path = self.run_dir / "FutureWork" / "examples" / "result.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        run = load_run(self.run_dir)
        self.assertFalse(run.input_files["future_work"]["matches_manifest_sha256"])
        self.assertTrue(any("해시" in w for w in run.warnings))

    def test_crlf_checkout_still_matches_hash(self):
        path = self.run_dir / "FutureWork" / "examples" / "result.json"
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertTrue(load_run(self.run_dir).input_files["future_work"]["matches_manifest_sha256"])

    def test_works_without_upstream_files(self):
        shutil.rmtree(self.run_dir / "CoT1")
        shutil.rmtree(self.run_dir / "CoT3")
        (self.run_dir / "examples_upstream_manifest.json").unlink()
        run = load_run(self.run_dir)
        self.assertEqual(len(run.candidates), 8)
        self.assertTrue(any("CoT3" in w for w in run.warnings))
        evidence = build_evidence(run, 6)
        self.assertIsNone(evidence["meta"]["cot3_candidate_id"])
        self.assertEqual(evidence["upstream_evidence"], [])
        self.assertEqual(evidence["seed_papers"], [])  # CoT1 폴더를 지웠으므로 원 논문 정리가 없음

    def test_missing_future_work_is_rejected(self):
        (self.run_dir / "FutureWork" / "examples" / "result.json").unlink()
        with self.assertRaisesRegex(InputError, "FutureWork"):
            load_run(self.run_dir)


class TitleMatchTests(unittest.TestCase):
    def test_truncated_with_ellipsis(self):
        self.assertTrue(title_matches("Train an explicit token...", "Train an explicit token and more."))

    def test_different_text(self):
        self.assertFalse(title_matches("Train a different...", "Train an explicit token."))

    def test_empty_title_never_matches(self):
        self.assertFalse(title_matches("...", "Anything."))


class CliTests(unittest.TestCase):
    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_list_shows_all_candidates(self):
        code, out, _ = self._run("list", "--run-dir", str(RUN))
        self.assertEqual(code, 0)
        self.assertIn("후보 8개", out)
        self.assertIn("6 | C7 | NOVEL", out)

    def test_select_writes_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self._run("select", "--run-dir", str(RUN), "--idea", "6", "--out", tmp)
            self.assertEqual(code, 0)
            path = Path(tmp) / "cot45_public_run_20261029_154552" / "idea06" / "evidence.json"
            evidence = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["meta"]["candidate_index"], 6)

    def test_select_not_novel_exits_2(self):
        code, _, err = self._run("select", "--run-dir", str(RUN), "--idea", "1", "--out", "unused")
        self.assertEqual(code, 2)
        self.assertIn("--allow-not-novel", err)


if __name__ == "__main__":
    unittest.main()
