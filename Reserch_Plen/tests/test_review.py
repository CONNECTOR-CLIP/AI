import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from research_plan.cli import run_review
from research_plan.evidence import build_evidence
from research_plan.extract import extract_plan
from research_plan.inputs import load_run
from research_plan.review import (
    JUDGE_SCHEMA,
    JUDGED_FIELDS,
    ReviewError,
    check_judgement,
    fixes_from,
    review_plan,
    summarize,
)
from research_plan.schemas import FIELD_GROUPS
from test_extract import FakeProvider, golden_group, good_responses

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"


def judgement(scores: dict | None = None, issues: list | None = None) -> dict:
    scores = scores or {}
    return {
        "field_scores": [{"field": f, "score": scores.get(f, 5), "reason": "ok"} for f in JUDGED_FIELDS],
        "issues": issues or [],
    }


def issue(field, severity="major", check="quote_fidelity", item_id=""):
    return {"field": field, "item_id": item_id, "severity": severity, "check": check,
            "problem": "인용문을 넓게 해석함", "evidence": "cot2.P2.candidates[0]", "suggestion": "평가 범위로 좁힐 것"}


def changed_group(group: str, field: str) -> dict:
    """정답 예시 묶음에서 field 하나의 내용을 바꾼 응답. 보완이 실제로 글을 바꾼 경우를 흉내 낸다."""
    out = golden_group(group)
    value = out[field]["value"]
    if isinstance(value, str):
        out[field]["value"] = value + " (보완함)"
    else:
        item = value[0]
        key = next(k for k in ("text", "setup", "question", "why", "claim") if k in item)
        item[key] += " (보완함)"
    return out


class Providers:
    """작성기와 판정기를 각각 FakeProvider로 둔다."""

    def __init__(self, judgements, writer_responses=None):
        self.judge = FakeProvider({"judge": judgements})
        self.judge.model = "fake/judge"
        self.writer = FakeProvider(writer_responses or {})
        self.writer.model = "fake/writer"


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = build_evidence(load_run(RUN), 6)
        cls.plan, _, ok = extract_plan(cls.evidence, FakeProvider(good_responses()))
        assert ok

    def test_passing_plan_is_not_rewritten(self):
        p = Providers([judgement()])
        final, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "pass")
        self.assertEqual(len(report["rounds"]), 1)
        self.assertEqual(p.writer.documents, [])
        self.assertEqual(final["fields"], self.plan["fields"])
        self.assertEqual(final["meta"]["review"]["status"], "pass")

    def test_major_issue_rewrites_only_that_group(self):
        first = judgement({"limitations_of_existing_approaches": 2},
                          [issue("limitations_of_existing_approaches", item_id="L1")])
        p = Providers([first, judgement()], {"problem": [changed_group("problem", "limitations_of_existing_approaches")]})
        final, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "pass")
        self.assertEqual(report["refine"]["groups"], ["problem"])
        rereview = p.judge.documents[1][1]
        self.assertEqual(rereview["changed_fields"], ["limitations_of_existing_approaches"])
        self.assertEqual(rereview["previous_judgement"], first)
        self.assertEqual([g for g, _ in p.writer.documents], ["problem"])
        fix = p.writer.documents[0][1]["fix_errors"]
        self.assertTrue(any("quote_fidelity" in m and "L1" in m for m in fix))
        self.assertEqual(len(report["rounds"]), 2)

    def test_still_failing_after_refine_needs_review(self):
        bad = judgement({"experimental_design": 3}, [issue("experimental_design", check="baseline_fit")])
        p = Providers([bad, bad], {"validation": [golden_group("validation")]})
        _, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "needs_review")
        self.assertEqual(report["rounds"][-1]["summary"]["low_fields"], ["experimental_design"])

    def test_no_refine_only_judges(self):
        p = Providers([judgement({"baselines": 3}, [issue("baselines", "minor", "baseline_fit")])])
        final, report, status = review_plan(self.evidence, self.plan, None, p.judge, refine=False)
        self.assertEqual(status, "needs_review")
        self.assertNotIn("refine", report)
        self.assertEqual(final["fields"], self.plan["fields"])

    def test_refine_breaking_rules_keeps_original(self):
        broken = golden_group("method")
        broken["method_components"]["value"][0]["addresses"] = ["L99"]
        first = judgement({"method_components": 2}, [issue("method_components", check="component_quality")])
        p = Providers([first], {"method": [broken] * 6})
        final, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "needs_review")
        self.assertFalse(report["refine"]["rules_passed"])
        self.assertTrue(report["refine"]["unlocked_retry"])  # 고정 → 고정 없이 재시도 → 그래도 실패
        self.assertEqual(final["fields"], self.plan["fields"])

    def test_untargeted_fields_in_rewritten_group_are_locked(self):
        rewritten = changed_group("validation", "experimental_design")
        for key in ("baselines", "validation_targets"):
            rewritten[key]["value"][0]["why" if key == "baselines" else "question"] = "모델이 바꿔 쓴 내용"
        first = judgement({"experimental_design": 3}, [issue("experimental_design", check="baseline_fit")])
        p = Providers([first, judgement()], {"validation": [rewritten]})
        final, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "pass")
        self.assertEqual(report["refine"]["target_fields"], ["experimental_design"])
        self.assertIn("validation_targets", report["refine"]["locked_fields"])
        for key in ("baselines", "validation_targets"):
            self.assertEqual(final["fields"][key], self.plan["fields"][key])
        self.assertIn("baselines", p.writer.documents[0][1]["keep_unchanged"])

    def test_regression_drift_and_new_findings_are_separated(self):
        first = judgement({"research_problem": 3}, [issue("research_problem")])
        # 바뀐 research_problem은 더 떨어지고(퇴행), 그대로인 research_topic은 판정이 흔들림(편차)
        second = judgement({"research_problem": 2, "research_topic": 3},
                           [issue("research_problem"), issue("research_topic", "major", "other")])
        p = Providers([first, second], {"problem": [changed_group("problem", "research_problem")]})
        final, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        s = report["rounds"][1]["summary"]
        self.assertEqual(status, "needs_review")
        self.assertEqual(s["changed_fields"], ["research_problem"])
        self.assertEqual(s["regressed_fields"], ["research_problem"])
        self.assertEqual(s["drift_fields"], ["research_topic"])
        self.assertEqual([i["field"] for i in s["new_findings"]], ["research_topic"])
        self.assertEqual(s["low_fields"], ["research_problem"])  # research_topic은 1회차 5점 유지
        self.assertEqual(s["major_issues"], 1)

    def test_drift_alone_does_not_fail_review(self):
        first = judgement({"research_problem": 3}, [issue("research_problem")])
        second = judgement({"validation_targets": 3}, [issue("validation_targets", "major", "metric_fit", "V1")])
        p = Providers([first, second], {"problem": [changed_group("problem", "research_problem")]})
        _, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "pass")
        self.assertEqual(report["rounds"][1]["summary"]["drift_fields"], ["validation_targets"])

    def test_problem_caused_by_change_counts(self):
        first = judgement({"experimental_design": 3}, [issue("experimental_design", check="baseline_fit")])
        caused = issue("validation_targets", "major", "metric_fit", "V1")
        caused["evidence"] = "변경된 필드 experimental_design 때문: E1이 바뀌어 V1과 맞지 않음"
        second = judgement({"validation_targets": 3}, [caused])
        p = Providers([first, second], {"validation": [changed_group("validation", "experimental_design")]})
        _, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        s = report["rounds"][1]["summary"]
        self.assertEqual(status, "needs_review")
        self.assertEqual(s["affected_by_change"], ["validation_targets"])
        self.assertEqual(s["drift_fields"], [])

    def test_unchanged_rewrite_keeps_first_verdict(self):
        first = judgement({"research_problem": 3}, [issue("research_problem")])
        p = Providers([first, judgement()], {"problem": [golden_group("problem")]})
        _, report, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(report["rounds"][1]["summary"]["changed_fields"], [])
        self.assertEqual(status, "needs_review")  # 글이 그대로면 1회차 판정 그대로

    def test_plan_failing_rules_is_refused(self):
        plan = copy.deepcopy(self.plan)
        plan["fields"]["research_background"]["value"] = "P1-style 배경"
        with self.assertRaises(ReviewError):
            review_plan(self.evidence, plan, None, Providers([]).judge)

    def test_malformed_judgement_is_retried(self):
        missing = judgement()
        missing["field_scores"].pop()
        p = Providers([missing, judgement()])
        _, _, status = review_plan(self.evidence, self.plan, p.writer, p.judge)
        self.assertEqual(status, "pass")
        self.assertIn("fix_errors", p.judge.documents[1][1])

    def test_run_review_writes_files_and_keeps_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "evidence.json").write_text(json.dumps(self.evidence, ensure_ascii=False), encoding="utf-8")
            plan_path = out / "plan.json"
            plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
            before = plan_path.read_text(encoding="utf-8")
            p = Providers([judgement()])
            with redirect_stdout(io.StringIO()):
                code = run_review(plan_path, model=None, judge_model=None, refine=True,
                                  writer=p.writer, judge_provider=p.judge)
            self.assertEqual(code, 0)
            self.assertEqual(plan_path.read_text(encoding="utf-8"), before)
            self.assertTrue((out / "plan.reviewed.json").is_file())
            self.assertIn("judge", json.loads((out / "review.json").read_text(encoding="utf-8"))["calls"])


class JudgementTests(unittest.TestCase):
    def test_low_score_without_issue_is_invalid(self):
        errors = check_judgement(judgement({"baselines": 2}))
        self.assertTrue(any("baselines" in e for e in errors))

    def test_out_of_range_and_duplicates(self):
        j = judgement({"research_topic": 7})
        j["field_scores"].append({"field": "baselines", "score": 5, "reason": ""})
        errors = check_judgement(j)
        self.assertEqual(len(errors), 2)

    def test_summary_and_fixes(self):
        j = judgement({"research_problem": 3, "baselines": 4},
                      [issue("research_problem", "minor"), issue("baselines", "major", "baseline_fit", "B2"),
                       issue("expected_novelty", "minor", "other")])
        s = summarize(j)
        self.assertFalse(s["passed"])
        self.assertEqual(s["low_fields"], ["research_problem"])
        self.assertEqual((s["major_issues"], s["minor_issues"]), (1, 2))
        fixes = fixes_from(j)
        self.assertEqual(set(fixes), {"problem", "validation"})
        self.assertFalse(any("expected_novelty" in m for m in fixes["validation"]))

    def test_scope_field_is_not_judged(self):
        self.assertNotIn("novelty_search_scope", JUDGED_FIELDS)
        self.assertEqual(len(JUDGED_FIELDS), sum(len(v) for v in FIELD_GROUPS.values()))

    def test_judge_schema_is_strict(self):
        def walk(s):
            if "properties" in s:
                self.assertFalse(s["additionalProperties"])
                self.assertEqual(s["required"], list(s["properties"]))
                for sub in s["properties"].values():
                    walk(sub)
            if "items" in s:
                walk(s["items"])
        walk(JUDGE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
