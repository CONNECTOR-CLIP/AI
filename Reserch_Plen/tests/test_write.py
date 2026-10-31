import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_plan.cli import run_check, run_write
from research_plan.evidence import build_evidence
from research_plan.extract import extract_plan
from research_plan.inputs import load_run
from research_plan.validate import PLAN_HEADINGS, SKELETON_HEADINGS
from research_plan.write import (
    OUTLINE_HEADINGS,
    PROSE_SCHEMA,
    SKELETON_SCHEMA,
    check_llm_output,
    check_reader_text,
    plan_content_errors,
    render_research_plan,
    write_documents,
)
from test_extract import FakeProvider, good_responses

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"

PROSE = {
    "short_title": "응답 수준 미지원 상태와 인용 기반 거절",
    "overview": "검색 증강 모델이 근거로 답할 수 없을 때를 스스로 판단하게 하는 방법을 계획한다.",
    "current_approach": "Self-RAG [2310.11511]는 reflection token으로 검색과 생성 결과를 평가한다.",
    "method_overview": "응답 수준 상태(M1)를 학습하고, 그 상태에 따라 인용 기반 거절(M3)을 생성하는지 검증한다.",
}


def skeleton(**changes) -> dict:
    sk = {
        "titles": ["Knowing When Evidence Is Not Enough", "Cite Before You Refuse"],
        "abstract": {
            "background": "Retrieval-augmented models such as Self-RAG [2310.11511] critique their outputs.",
            "gap": "They do not treat insufficient evidence as an explicit response-level state.",
            "method": "We propose an unsupported state and citation-coupled refusals.",
            "planned_evaluation": "We compare against the closest baseline on detection ([RESULT: E1 F1]).",
            "expected_contribution": "A method, a data procedure, and an analysis.",
        },
        "outline": [{"heading": h, "items": [f"내용 — 근거: L1"]} for h in OUTLINE_HEADINGS],
        "figures": [{"label": f"Table {n}", "content": "결과 표", "basis": "E1"} for n in (1, 2, 3)],
        "contributions": ["We propose an unsupported state.", "We evaluate whether it reduces errors."],
    }
    for section in sk["outline"]:
        if section["heading"] == "5 Results":
            section["items"] = ["판별 성능 — E1 → [RESULT: E1 F1] (C1)"]
    sk.update(changes)
    return sk


class WriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = build_evidence(load_run(RUN), 6)
        cls.plan, _, ok = extract_plan(cls.evidence, FakeProvider(good_responses()))
        assert ok

    def provider(self, prose=None, skeletons=None):
        return FakeProvider({"research_plan": prose or [PROSE], "paper_skeleton": skeletons or [skeleton()]})

    def test_documents_pass_validators(self):
        docs, log, ok = write_documents(self.plan, self.provider())
        self.assertTrue(ok, log)
        self.assertEqual(set(docs), {"research_plan.md", "paper_skeleton.md"})
        lines = docs["research_plan.md"].splitlines()
        for heading in PLAN_HEADINGS:
            self.assertIn(heading, lines)
        for heading in SKELETON_HEADINGS:
            self.assertIn(heading, docs["paper_skeleton.md"].splitlines())

    def test_tables_come_from_plan_not_llm(self):
        docs, _, _ = write_documents(self.plan, self.provider())
        text = docs["research_plan.md"]
        for exp in self.plan["fields"]["experimental_design"]["value"]:
            self.assertIn(f"| {exp['id']} | {', '.join(exp['validates'])} |", text)
        for lim in self.plan["fields"]["limitations_of_existing_approaches"]["value"]:
            self.assertIn(lim["text"], text)
        self.assertIn(self.plan["fields"]["novelty_search_scope"]["value"]["statement"], text)

    def test_llm_gets_plan_only(self):
        provider = self.provider()
        write_documents(self.plan, provider)
        doc = provider.documents[0][1]
        self.assertEqual(set(doc), {"plan_meta", "plan_fields", "citation_whitelist"})

    def test_result_claim_in_prose_is_rewritten(self):
        bad = dict(PROSE, overview="이 방법은 정확도를 향상시켰다.")
        provider = self.provider(prose=[bad, PROSE])
        _, log, ok = write_documents(self.plan, provider)
        self.assertTrue(ok)
        self.assertTrue(any("향상시켰다" in e for e in log["parts"]["research_plan"]["rounds"][0]["errors"]))
        self.assertIn("fix_errors", provider.documents[1][1])

    def test_unknown_id_and_citation_are_rejected(self):
        bad = skeleton(contributions=["We propose M9.", "We compare with [2401.99999]."])
        _, log, ok = write_documents(self.plan, self.provider(skeletons=[bad, skeleton()]))
        errors = log["parts"]["paper_skeleton"]["rounds"][0]["errors"]
        self.assertTrue(ok)
        self.assertTrue(any("M9" in e for e in errors))
        self.assertTrue(any("2401.99999" in e for e in errors))

    def test_english_result_claim_is_rejected(self):
        bad = skeleton()
        bad["abstract"]["gap"] = "Our method outperforms Self-RAG."
        _, log, _ = write_documents(self.plan, self.provider(skeletons=[bad, skeleton()]))
        self.assertTrue(any("outperforms" in e for e in log["parts"]["paper_skeleton"]["rounds"][0]["errors"]))

    def test_skeleton_structure_is_enforced(self):
        bad = skeleton(titles=["Only one"])
        bad["outline"] = bad["outline"][:5]
        bad["abstract"]["planned_evaluation"] = "We compare against the closest baseline."
        _, log, ok = write_documents(self.plan, self.provider(skeletons=[bad] * 3), max_rounds=3)
        self.assertFalse(ok)
        errors = log["parts"]["paper_skeleton"]["rounds"][-1]["errors"]
        self.assertEqual(len(errors), 3)

    def test_problem_in_plan_is_reported_not_retried(self):
        plan = copy.deepcopy(self.plan)
        plan["fields"]["research_objective"]["value"] = "이 방법은 성능을 입증했다."
        self.assertTrue(plan_content_errors(plan))
        provider = self.provider()
        docs, log, ok = write_documents(plan, provider)
        self.assertFalse(ok)
        self.assertEqual(len(log["parts"]["research_plan"]["rounds"]), 1)  # LLM 탓이 아니므로 다시 쓰지 않음
        self.assertIn("research_plan.md", docs)

    def test_short_title_used_in_both_documents(self):
        docs, _, _ = write_documents(self.plan, self.provider())
        for name in docs:
            self.assertTrue(docs[name].startswith(f"# "), name)
            self.assertIn(PROSE["short_title"], docs[name].splitlines()[0])
        self.assertIn("**연구 주제.**", docs["research_plan.md"])

    def test_sentence_title_is_rewritten(self):
        bad = dict(PROSE, short_title="응답 수준 미지원 상태를 학습하는 방법을 연구한다.")
        _, log, ok = write_documents(self.plan, self.provider(prose=[bad, PROSE]))
        self.assertTrue(ok)
        self.assertTrue(any("명사구" in e for e in log["parts"]["research_plan"]["rounds"][0]["errors"]))

    def test_field_name_and_ids_in_abstract_are_rejected(self):
        bad = skeleton()
        bad["abstract"]["expected_contribution"] = "A method and an analysis (expected_contribution)."
        bad["abstract"]["gap"] = "Existing work lacks this state (L1, L2)."
        _, log, ok = write_documents(self.plan, self.provider(skeletons=[bad, skeleton()]))
        errors = log["parts"]["paper_skeleton"]["rounds"][0]["errors"]
        self.assertTrue(ok)
        self.assertTrue(any("expected_contribution" in e for e in errors))
        self.assertTrue(any("L1, L2" in e for e in errors))

    def test_ids_inside_result_slot_and_outline_are_allowed(self):
        self.assertEqual(check_reader_text({"a": "Detection ([RESULT: E1 F1])."}, allow_ids=False), [])
        docs, log, ok = write_documents(self.plan, self.provider())  # 개요 항목에 "근거: L1"
        self.assertTrue(ok, log)

    def test_paper_labels_are_rejected(self):
        self.assertTrue(check_llm_output({"x": "P1-style citation"}, self.plan))
        self.assertEqual(check_llm_output({"x": "E1, C1, B3"}, self.plan), [])

    def test_schemas_are_strict(self):
        def walk(s):
            if "properties" in s:
                self.assertFalse(s["additionalProperties"])
                self.assertEqual(s["required"], list(s["properties"]))
                for sub in s["properties"].values():
                    walk(sub)
            if "items" in s:
                walk(s["items"])
        walk(PROSE_SCHEMA)
        walk(SKELETON_SCHEMA)

    def test_render_without_review_marks_it(self):
        text = render_research_plan(self.plan, PROSE)
        self.assertIn("3단계 심사를 거치지 않은 plan", text)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = build_evidence(load_run(RUN), 6)
        cls.plan, _, _ = extract_plan(cls.evidence, FakeProvider(good_responses()))

    def _folder(self, tmp: str, plan: dict) -> Path:
        out = Path(tmp)
        (out / "evidence.json").write_text(json.dumps(self.evidence, ensure_ascii=False), encoding="utf-8")
        path = out / "plan.reviewed.json"
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return path

    def test_write_creates_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._folder(tmp, self.plan)
            provider = FakeProvider({"research_plan": [PROSE], "paper_skeleton": [skeleton()]})
            with redirect_stdout(io.StringIO()):
                code = run_write(path, model=None, max_rounds=3, provider=provider)
            self.assertEqual(code, 0)
            for name in ("research_plan.md", "paper_skeleton.md", "write_log.json"):
                self.assertTrue((Path(tmp) / name).is_file(), name)

    def test_check_and_write_refuse_broken_human_edit(self):
        plan = copy.deepcopy(self.plan)
        plan["fields"]["method_components"]["value"][0]["addresses"] = ["L99"]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._folder(tmp, plan)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(run_check(path), 1)
            self.assertIn("L99", out.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(run_write(path, model=None, max_rounds=1, provider=FakeProvider({})), 2)


if __name__ == "__main__":
    unittest.main()
