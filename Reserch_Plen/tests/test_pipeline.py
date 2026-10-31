import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_plan.evidence import build_evidence
from research_plan.inputs import load_run
from research_plan.pipeline import MANIFEST, STAGES, run_pipeline
from research_plan.schemas import FIELD_GROUPS
from research_plan.verify import ArxivLookup
from test_extract import FakeProvider, golden_group
from test_review import issue, judgement
from test_verify import FakeArxiv
from test_write import PROSE, skeleton

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"
RUN_ID = "cot45_public_run_20261029_154552"


def writer(extra: dict | None = None) -> FakeProvider:
    responses = {g: [golden_group(g)] for g in FIELD_GROUPS}
    responses |= {"research_plan": [PROSE], "paper_skeleton": [skeleton()]}
    responses |= extra or {}
    return FakeProvider(responses)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.whitelist = {"citation_whitelist": build_evidence(load_run(RUN), 6)["citation_whitelist"]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"
        self.folder = self.out / RUN_ID / "idea06"

    def tearDown(self):
        self.tmp.cleanup()

    def providers(self, judgements=None, writer_extra=None):
        return {
            "writer": writer(writer_extra),
            "judge": FakeProvider({"judge": judgements or [judgement()]}),
            "lookup": ArxivLookup(Path(self.tmp.name) / "cache.json", fetch=FakeArxiv(self.whitelist)),
        }

    def run_quiet(self, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run_pipeline(RUN, 6, out=self.out, **kwargs)
        return code, out.getvalue() + err.getvalue()

    def manifest(self) -> dict:
        return json.loads((self.folder / MANIFEST).read_text(encoding="utf-8"))

    def test_full_run_passes_and_writes_manifest(self):
        code, _ = self.run_quiet(providers=self.providers())
        self.assertEqual(code, 0)
        m = self.manifest()
        self.assertEqual([s["stage"] for s in m["stages"]], STAGES)
        self.assertTrue(all(s["status"] == "pass" for s in m["stages"]))
        self.assertEqual(m["final_status"], "pass")
        self.assertIn("prompts/judge.md", m["prompts_sha256"])
        self.assertIn("docs/field_definitions.md", m["prompts_sha256"])
        self.assertIn("future_work", m["inputs"])
        for name in ("evidence.json", "plan.json", "plan.reviewed.json", "research_plan.md", "verify_report.json"):
            self.assertTrue((self.folder / name).is_file(), name)
        self.assertIsNone(m["backup"])

    def test_resume_from_write_keeps_human_edit_and_backs_up(self):
        self.run_quiet(providers=self.providers())
        reviewed = self.folder / "plan.reviewed.json"
        plan = json.loads(reviewed.read_text(encoding="utf-8"))
        plan["fields"]["research_topic"]["value"] = "사람이 고친 연구 주제"
        plan["meta"]["human_edits"] = [{"field": "research_topic"}]
        reviewed.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        plan_json_before = (self.folder / "plan.json").read_bytes()

        code, _ = self.run_quiet(start="write", providers=self.providers())
        self.assertEqual(code, 0)
        m = self.manifest()
        self.assertEqual([s["stage"] for s in m["stages"]], ["write", "verify"])
        self.assertIn("사람이 고친 연구 주제", (self.folder / "research_plan.md").read_text(encoding="utf-8"))
        self.assertEqual((self.folder / "plan.json").read_bytes(), plan_json_before)
        backup = Path(m["backup"])
        self.assertTrue((backup / "research_plan.md").is_file())
        self.assertTrue((backup / MANIFEST).is_file())
        self.assertFalse((backup / "plan.json").exists())  # write 이전 단계 파일은 건드리지 않음

    def test_rerunning_review_warns_about_human_edits(self):
        self.run_quiet(providers=self.providers())
        reviewed = self.folder / "plan.reviewed.json"
        plan = json.loads(reviewed.read_text(encoding="utf-8"))
        plan["meta"]["human_edits"] = [{"field": "x"}]
        reviewed.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        _, output = self.run_quiet(start="review", providers=self.providers())
        self.assertIn("--from write", output)
        self.assertTrue((Path(self.manifest()["backup"]) / "plan.reviewed.json").is_file())

    def test_needs_review_still_writes_documents(self):
        low = judgement({"baselines": 3}, [issue("baselines", "minor", "baseline_fit")])
        # 보완 시 baselines가 속한 validation 묶음을 다시 쓰고, 2회차에도 기준 미달이면 needs_review
        code, _ = self.run_quiet(providers=self.providers(
            judgements=[low, low], writer_extra={"validation": [golden_group("validation")] * 2}
        ))
        m = self.manifest()
        self.assertEqual(code, 1)
        self.assertEqual(m["final_status"], "needs_review")
        self.assertEqual([s["stage"] for s in m["stages"]], STAGES)
        self.assertTrue((self.folder / "research_plan.md").is_file())

    def test_extract_failure_stops_pipeline(self):
        broken = golden_group("method")
        broken["method_components"]["value"][0]["addresses"] = ["L99"]
        code, _ = self.run_quiet(providers=self.providers(writer_extra={"method": [broken] * 3}))
        m = self.manifest()
        self.assertEqual(code, 1)
        self.assertEqual([s["stage"] for s in m["stages"]], ["select", "extract"])
        self.assertEqual(m["final_status"], "fail")
        self.assertTrue((self.folder / "plan.draft.json").is_file())
        self.assertFalse((self.folder / "research_plan.md").exists())

    def test_skip_review_uses_fresh_plan_not_stale_reviewed(self):
        self.run_quiet(providers=self.providers())
        reviewed = self.folder / "plan.reviewed.json"
        plan = json.loads(reviewed.read_text(encoding="utf-8"))
        plan["fields"]["research_topic"]["value"] = "오래된 심사본 주제"
        reviewed.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        code, _ = self.run_quiet(start="extract", skip_review=True, providers=self.providers())
        self.assertEqual(code, 0)
        self.assertNotIn("오래된 심사본 주제", (self.folder / "research_plan.md").read_text(encoding="utf-8"))

    def test_resume_without_evidence_is_an_error(self):
        code, output = self.run_quiet(start="write", providers=self.providers())
        self.assertEqual(code, 2)
        self.assertIn("evidence.json", output)

    def test_not_novel_is_refused(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run_pipeline(RUN, 1, out=self.out, providers=self.providers())
        self.assertEqual(code, 2)
        self.assertIn("--allow-not-novel", err.getvalue())


if __name__ == "__main__":
    unittest.main()
