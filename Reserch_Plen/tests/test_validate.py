import copy
import json
import unittest
from pathlib import Path

from research_plan.schemas import FIELD_KEYS, PLAN_SCHEMA
from research_plan.validate import (
    PLAN_HEADINGS,
    SKELETON_HEADINGS,
    validate_markdown,
    validate_output_dir,
    validate_plan,
    validate_research_plan,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "examples" / "golden" / "idea06_unsupported_token"


def load_golden_plan() -> dict:
    return json.loads((GOLDEN / "plan.json").read_text(encoding="utf-8"))


class GoldenExampleTests(unittest.TestCase):
    def test_golden_output_dir_passes_all_checks(self):
        report = validate_output_dir(GOLDEN)
        for name, errors in report.items():
            self.assertEqual(errors, [], name)

    def test_golden_has_all_18_fields(self):
        self.assertEqual(list(load_golden_plan()["fields"]), FIELD_KEYS)


class SchemaFileTests(unittest.TestCase):
    def test_schema_file_matches_code(self):
        on_disk = json.loads((ROOT / "schema" / "plan.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk, PLAN_SCHEMA)


class PlanRuleTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_golden_plan()
        self.fields = self.plan["fields"]

    def test_missing_field_is_reported(self):
        del self.fields["risks_and_fallbacks"]
        self.assertIn("risks_and_fallbacks: 필드 누락", validate_plan(self.plan))

    def test_empty_source_requires_inferred(self):
        self.fields["research_topic"] = {"value": "T", "source": [], "inferred": False}
        self.assertIn("research_topic: source가 비어 있으면 inferred=true여야 함", validate_plan(self.plan))

    def test_unknown_source_prefix_is_reported(self):
        self.fields["research_topic"]["source"] = ["llm.guess"]
        errors = validate_plan(self.plan)
        self.assertTrue(any("허용되지 않은 근거 경로" in e for e in errors))

    def test_claim_with_unknown_target_is_reported(self):
        self.fields["target_claims"]["value"][0]["validated_by"] = ["V9"]
        self.assertIn("C1: 존재하지 않는 검증 대상 V9 참조", validate_plan(self.plan))

    def test_target_without_experiment_is_reported(self):
        designs = self.fields["experimental_design"]["value"]
        self.fields["experimental_design"]["value"] = [e for e in designs if "V2" not in e["validates"]]
        self.assertIn("V2: 어떤 실험(E)에서도 검증되지 않음", validate_plan(self.plan))

    def test_component_without_target_is_reported(self):
        for target in self.fields["validation_targets"]["value"]:
            target["components"] = [c for c in target["components"] if c != "M4"]
        self.assertIn("M4: 어떤 검증 대상(V)에서도 다뤄지지 않음", validate_plan(self.plan))

    def test_experiment_without_failure_interpretation_is_reported(self):
        self.fields["experimental_design"]["value"][0]["failure_interpretation"] = ""
        self.assertIn("E1: failure_interpretation가 비어 있음", validate_plan(self.plan))

    def test_bad_id_format_is_reported(self):
        self.fields["baselines"]["value"][0]["id"] = "X1"
        errors = validate_plan(self.plan)
        self.assertTrue(any("B<숫자> 형식" in e for e in errors))

    def test_citation_outside_whitelist_is_reported(self):
        self.fields["expected_novelty"]["value"][0]["vs"] = ["2401.99999"]
        self.assertIn("화이트리스트에 없는 인용 2401.99999", validate_plan(self.plan))

    def test_novelty_must_be_tested_by_an_existing_experiment(self):
        novelty = self.fields["expected_novelty"]["value"][0]
        novelty["tested_by"] = []
        self.assertTrue(any("tested_by가 비어 있음" in e for e in validate_plan(self.plan)))
        novelty["tested_by"] = ["E9"]
        self.assertTrue(any("존재하지 않는 실험 E9" in e for e in validate_plan(self.plan)))

    def test_novelty_needs_mechanism_and_known_axis(self):
        novelty = self.fields["expected_novelty"]["value"][0]
        novelty["existing_mechanism"] = " "
        novelty["difference_axis"] = "완전히 새로움"
        errors = validate_plan(self.plan)
        self.assertTrue(any("existing_mechanism" in e for e in errors))
        self.assertTrue(any("difference_axis" in e for e in errors))

    def test_valid_plan_is_not_mutated(self):
        before = copy.deepcopy(self.plan)
        validate_plan(self.plan)
        self.assertEqual(self.plan, before)


class MarkdownRuleTests(unittest.TestCase):
    def test_result_assertion_is_reported(self):
        text = "\n".join(SKELETON_HEADINGS) + "\nOur method achieves 90% accuracy."
        errors = validate_markdown(text, SKELETON_HEADINGS, set())
        self.assertIn("결과 단정 표현: 'achieves'", errors)

    def test_korean_result_assertion_is_reported(self):
        text = "\n".join(SKELETON_HEADINGS) + "\n정확도가 향상되었다."
        self.assertIn("결과 단정 표현: '향상되었다'", validate_markdown(text, SKELETON_HEADINGS, set()))

    def test_missing_heading_is_reported(self):
        errors = validate_markdown("## 1. Title candidates", SKELETON_HEADINGS, set())
        self.assertIn("필수 제목 누락: ## 5. Contribution bullets", errors)

    def test_heading_order_is_checked(self):
        text = "\n".join(reversed(SKELETON_HEADINGS))
        self.assertIn("필수 제목의 순서가 명세와 다름", validate_markdown(text, SKELETON_HEADINGS, set()))

    def test_unknown_citation_in_markdown_is_reported(self):
        text = "\n".join(SKELETON_HEADINGS) + "\nSee [2401.99999]."
        self.assertIn("화이트리스트에 없는 인용 2401.99999", validate_markdown(text, SKELETON_HEADINGS, set()))


class TemplateTests(unittest.TestCase):
    def test_research_plan_template_has_fixed_structure(self):
        text = (ROOT / "templates" / "research_plan.md.tmpl").read_text(encoding="utf-8")
        self.assertEqual(validate_research_plan(text, set()), [])

    def test_paper_skeleton_template_has_fixed_headings(self):
        text = (ROOT / "templates" / "paper_skeleton.md.tmpl").read_text(encoding="utf-8")
        self.assertEqual(validate_markdown(text, SKELETON_HEADINGS, set()), [])

    def test_plan_headings_cover_pdf_sections(self):
        for heading in ("### 1.1 문제 정의 및 연구 배경", "### 1.2 제안 방법",
                        "### 2.1 Experimental Validation Plan", "### 2.2 Target Claims",
                        "### 2.3 Expected Novelty & Contribution"):
            self.assertIn(heading, PLAN_HEADINGS)


if __name__ == "__main__":
    unittest.main()
