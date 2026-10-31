import copy
import io
import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

from research_plan.cli import run_evaluate
from research_plan.evaluate import (
    EVAL_SCHEMA,
    BASELINE_SCHEMA,
    auto_metrics,
    evaluate,
    human_sheet,
    judge_documents,
    summarize_judgements,
)
from research_plan.evidence import build_evidence
from research_plan.inputs import load_run
from research_plan.review import JUDGED_FIELDS
from research_plan.verify import ArxivLookup
from test_extract import FakeProvider
from test_pipeline import writer as pipeline_writer
from test_review import judgement as stage3_judgement
from test_verify import FakeArxiv

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"

FREE = {
    "research_plan": "# 계획\n\nRAG [2005.11401]를 개선한다. 73000개 질의를 쓰고 P1 방식을 따른다. [2401.00001]\n",
    "paper_skeleton": "# Skeleton\n\nWe achieve better results.\n",
}
TEMPLATE = {
    "research_plan": "## 0. 개요\n\n계획이다. Self-RAG [2310.11511].\n",
    "paper_skeleton": "## 1. Title candidates\n\n1. A Title\n",
}


def eval_judgement(score: int = 4, majors: int = 0) -> dict:
    return {
        "element_scores": [{"element": f, "present": score > 1, "score": score, "reason": "-"} for f in JUDGED_FIELDS],
        "issues": [{"check": "other", "severity": "major", "problem": "p", "evidence": "e"}] * majors,
    }


class Repeat:
    """같은 응답을 계속 돌려주는 가짜 모델. sequence를 주면 차례로 돌려주고 마지막 것을 반복한다."""

    def __init__(self, model: str, sequence: list[dict]):
        self.model = model
        self.sequence = sequence
        self.calls_made = 0

    def evaluate(self, *, instructions, document, schema, schema_name):
        response = self.sequence[min(self.calls_made, len(self.sequence) - 1)]
        self.calls_made += 1
        return copy.deepcopy(response)


class BaselineWriter:
    model = "fake/writer"

    def evaluate(self, *, instructions, document, schema, schema_name):
        assert schema is BASELINE_SCHEMA
        return copy.deepcopy(FREE if schema_name == "baseline_free" else TEMPLATE)


class EvaluateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = build_evidence(load_run(RUN), 6)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.lookup = ArxivLookup(self.root / "cache.json", fetch=FakeArxiv(self.evidence))

    def tearDown(self):
        self.tmp.cleanup()

    def pipeline_providers(self):
        return {
            "writer": pipeline_writer(),
            "judge": FakeProvider({"judge": [stage3_judgement()]}),
            "lookup": self.lookup,
        }

    def run_eval(self, **kwargs):
        judges = [Repeat("fake/judge-a", [eval_judgement(4)]), Repeat("fake/judge-b", [eval_judgement(3, 1)])]
        with redirect_stdout(io.StringIO()):
            report = evaluate(RUN, [6], writer=BaselineWriter(), judges=judges, lookup=self.lookup,
                              out_root=self.root / "eval", samples=2,
                              pipeline_providers=self.pipeline_providers(), **kwargs)
        return report, judges

    def test_all_conditions_and_golden_are_scored(self):
        report, judges = self.run_eval()
        conditions = [r["condition"] for r in report["results"]]
        self.assertEqual(conditions, ["free", "template", "pipeline", "golden"])
        self.assertTrue(all(r["status"] in ("ok", "needs_review") for r in report["results"]))
        self.assertEqual(set(report["summary"]), {"free", "template", "pipeline", "golden"})
        self.assertEqual(judges[0].calls_made, 4 * 2)  # 조건 4개 × 2회
        folder = Path(report["folder"])
        for name in ("report.json", "summary.md", "human/idea06_sheet.md", "human/idea06_key.json"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertTrue((folder / "idea06" / "pipeline" / "research_plan.md").is_file())

    def test_summary_keeps_judges_separate(self):
        report, _ = self.run_eval(include_golden=False)
        free = report["summary"]["free"]["judges"]
        self.assertEqual(free["fake/judge-a"]["mean_score"], 4)
        self.assertEqual(free["fake/judge-b"]["mean_score"], 3)
        self.assertEqual(free["fake/judge-b"]["major_issues"], 1)
        md = (Path(report["folder"]) / "summary.md").read_text(encoding="utf-8")
        self.assertIn("fake/judge-a", md)
        self.assertIn("근거에 없는 숫자", md)

    def test_human_sheet_is_blinded(self):
        report, _ = self.run_eval()
        folder = Path(report["folder"]) / "human"
        key = json.loads((folder / "idea06_key.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(key.values()), ["free", "pipeline", "template"])
        sheet = (folder / "idea06_sheet.md").read_text(encoding="utf-8")
        for condition in ("free", "template", "pipeline"):
            self.assertNotIn(f"· {condition}", sheet)
        self.assertIn("## 문서 A", sheet)
        self.assertIn("정답 예시", sheet)

    def test_auto_metrics_catch_fabrication(self):
        docs = {"research_plan.md": FREE["research_plan"], "paper_skeleton.md": FREE["paper_skeleton"]}
        m = auto_metrics(self.evidence, docs, self.lookup)
        self.assertEqual(m["citations_outside_whitelist"], ["2401.00001"])
        self.assertTrue(any("73000" in e for e in m["numbers_not_in_evidence"]))
        self.assertEqual(m["internal_labels"], ["P1"])
        self.assertTrue(any("achieve" in e for e in m["result_claims"]))
        self.assertTrue(m["missing_headings"])

    def test_judge_retries_malformed_output(self):
        bad = eval_judgement()
        bad["element_scores"].pop()
        judge = Repeat("fake/j", [bad, eval_judgement(5)])
        out = judge_documents(self.evidence, {"research_plan.md": "x", "paper_skeleton.md": "y"}, judge, samples=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(judge.calls_made, 2)

    def test_summary_reports_sample_spread(self):
        s = summarize_judgements([eval_judgement(4), eval_judgement(2)])
        self.assertEqual(s["mean_score"], 3)
        self.assertEqual(s["sample_spread"], 2)

    def test_sheet_key_is_reproducible(self):
        docs = {c: {"research_plan.md": c} for c in ("free", "template", "pipeline")}
        self.assertEqual(human_sheet(6, docs, seed=1)[1], human_sheet(6, docs, seed=1)[1])

    def test_eval_schema_is_strict(self):
        def walk(s):
            if "properties" in s:
                self.assertFalse(s["additionalProperties"])
                self.assertEqual(s["required"], list(s["properties"]))
                for sub in s["properties"].values():
                    walk(sub)
            if "items" in s:
                walk(s["items"])
        walk(EVAL_SCHEMA)
        walk(BASELINE_SCHEMA)

    def test_cli_defaults_to_novel_ideas(self):
        args = Namespace(run_dir=RUN, ideas=None, conditions="free", judges="", samples=1, model=None,
                         out=self.root / "eval", no_golden=True, offline=True)
        judge = Repeat("fake/j", [eval_judgement()])
        with redirect_stdout(io.StringIO()) as out:
            code = run_evaluate(args, writer=BaselineWriter(), judges=[judge], lookup=self.lookup)
        self.assertEqual(code, 0)
        self.assertEqual(judge.calls_made, 6)  # NOVEL 후보 6개 × free 1조건 × 1회
        self.assertIn("평가 요약", out.getvalue())


if __name__ == "__main__":
    unittest.main()
