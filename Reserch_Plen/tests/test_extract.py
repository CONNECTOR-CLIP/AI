import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from research_plan.cli import run_extract
from research_plan.evidence import build_evidence
from research_plan.extract import (
    check_paper_labels,
    check_sources,
    clean_group,
    extract_plan,
    field_guidance,
    groups_for_error,
    known_sources,
)
from research_plan.inputs import load_run
from research_plan.provider import OpenRouterProvider, ProviderError, parse_json_text
from research_plan.schemas import FIELD_GROUPS, strict_group_schema
from research_plan.validate import validate_plan

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "cot45_public_run_20261029_154552"
GOLDEN = ROOT / "examples" / "golden" / "idea06_unsupported_token" / "plan.json"


def golden_group(group: str) -> dict:
    """정답 예시의 묶음 하나를 LLM 응답 모양으로 만든다. 근거 경로는 비우고 inferred=true로 둔다."""
    fields = json.loads(GOLDEN.read_text(encoding="utf-8"))["fields"]
    out = {}
    for key in FIELD_GROUPS[group]:
        wrapper = copy.deepcopy(fields[key])
        wrapper["source"], wrapper["inferred"] = [], True
        if isinstance(wrapper["value"], list):
            for item in wrapper["value"]:
                if isinstance(item, dict):
                    item.pop("source", None)
                    item.pop("source_hint", None)
        out[key] = wrapper
    return out


class FakeProvider:
    model = "fake/model"

    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = {g: list(r) for g, r in responses.items()}
        self.documents: list[tuple[str, dict]] = []

    def evaluate(self, *, instructions, document, schema, schema_name):
        group = schema_name.removeprefix("plan_")
        self.documents.append((group, json.loads(document)))
        return copy.deepcopy(self.responses[group].pop(0))


def good_responses() -> dict[str, list[dict]]:
    return {g: [golden_group(g)] for g in FIELD_GROUPS}


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = build_evidence(load_run(RUN), 6)

    def test_passes_in_one_round(self):
        provider = FakeProvider(good_responses())
        plan, log, ok = extract_plan(self.evidence, provider)
        self.assertTrue(ok, log["rounds"])
        self.assertEqual(len(log["rounds"]), 1)
        self.assertEqual([g for g, _ in provider.documents], ["problem", "method", "validation"])
        self.assertEqual(validate_plan(plan), [])
        self.assertEqual(plan["meta"]["generated_by"], "llm:fake/model")

    def test_later_groups_see_earlier_ids(self):
        provider = FakeProvider(good_responses())
        extract_plan(self.evidence, provider)
        validation_doc = provider.documents[2][1]
        self.assertEqual(set(validation_doc["previous_groups"]), {"problem", "method"})
        self.assertNotIn("input_files", validation_doc["evidence"]["meta"])

    def test_only_failing_group_is_regenerated(self):
        responses = good_responses()
        broken = golden_group("validation")
        broken["experimental_design"]["value"] = [
            e for e in broken["experimental_design"]["value"] if e["id"] != "E4"
        ]
        responses["validation"] = [broken, golden_group("validation")]
        provider = FakeProvider(responses)
        plan, log, ok = extract_plan(self.evidence, provider)
        self.assertTrue(ok)
        self.assertEqual(log["rounds"][1]["regenerated"], ["validation"])
        self.assertTrue(any("V4" in e for e in log["rounds"][0]["errors"]))
        retry_doc = provider.documents[-1][1]
        self.assertIn("fix_errors", retry_doc)
        self.assertEqual(len(retry_doc["previous_attempt"]["experimental_design"]["value"]), 3)

    def test_invented_source_path_is_rejected(self):
        responses = good_responses()
        bad = golden_group("method")
        bad["proposed_method"]["source"] = ["cot4.requirements.made_up_field[3]"]
        bad["proposed_method"]["inferred"] = False
        responses["method"] = [bad, golden_group("method")]
        _, log, ok = extract_plan(self.evidence, FakeProvider(responses))
        self.assertTrue(ok)
        self.assertTrue(any("made_up_field" in e for e in log["rounds"][0]["errors"]))
        self.assertEqual(log["rounds"][1]["regenerated"], ["method"])

    def test_paper_label_triggers_rewrite_of_that_group(self):
        responses = good_responses()
        bad = golden_group("method")
        bad["proposed_method"]["value"] += " P1-style 인용을 쓴다."
        responses["method"] = [bad, golden_group("method")]
        _, log, ok = extract_plan(self.evidence, FakeProvider(responses))
        self.assertTrue(ok)
        self.assertEqual(log["rounds"][1]["regenerated"], ["method"])

    def test_gives_up_after_max_rounds(self):
        responses = good_responses()
        bad = golden_group("problem")
        bad["research_background"]["value"] += " (9999.99999 참고)"
        responses["problem"] = [bad, bad]
        plan, log, ok = extract_plan(self.evidence, FakeProvider(responses), max_rounds=2)
        self.assertFalse(ok)
        self.assertEqual(len(log["rounds"]), 2)
        self.assertTrue(any("9999.99999" in e for e in log["rounds"][-1]["errors"]))

    def test_search_scope_comes_from_cot5(self):
        plan, _, _ = extract_plan(self.evidence, FakeProvider(good_responses()))
        scope = plan["fields"]["novelty_search_scope"]
        self.assertEqual(scope["value"]["web"]["status"], "확인불가")
        self.assertIn("TimeoutError", scope["value"]["statement"])
        self.assertFalse(scope["inferred"])

    def test_run_extract_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            path.write_text(json.dumps(self.evidence, ensure_ascii=False), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = run_extract(path, model=None, max_rounds=3, provider=FakeProvider(good_responses()))
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "plan.json").is_file())
            log = json.loads((Path(tmp) / "extract_log.json").read_text(encoding="utf-8"))
            self.assertEqual(set(log["prompt_sha256"]), set(FIELD_GROUPS))


class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.known = {"cot4.requirements.implementation_steps[0]", "cot5.paper.candidates[2]", "seed:2310.11511"}

    def test_parent_path_is_allowed(self):
        fields = {"x": {"value": "v", "source": ["cot4.requirements.implementation_steps", "cot5.paper"]}}
        self.assertEqual(check_sources(fields, self.known), [])

    def test_sub_field_path_is_allowed(self):
        fields = {"x": {"value": "v", "source": ["cot5.paper.candidates[2].critical_difference"]}}
        self.assertEqual(check_sources(fields, self.known), [])

    def test_previous_groups_path_is_rejected(self):
        fields = {"x": {"value": "v", "source": ["previous_groups.problem.research_problem"]}}
        self.assertEqual(len(check_sources(fields, self.known)), 1)

    def test_unknown_path_and_item_source_are_reported(self):
        fields = {"r": {"value": [{"id": "R1", "source": "cot4.nope"}], "source": ["seed:2005.11401"]}}
        self.assertEqual(len(check_sources(fields, self.known)), 2)

    def test_paper_labels_in_values_are_reported(self):
        fields = {
            "proposed_method": {"value": "P1-style 인용과 P2:L1 한계를 쓴다", "source": ["cot2.P2.candidates[0]"]},
            "risks_and_fallbacks": {"value": [{"id": "R1", "risk": "GPT-4 비용", "source": "cot2.P1.x"}],
                                    "source": []},
        }
        errors = check_paper_labels(fields)
        self.assertEqual(len(errors), 1)
        self.assertIn("P1, P2", errors[0])

    def test_known_sources_include_seeds(self):
        evidence = build_evidence(load_run(RUN), 6)
        known = known_sources(evidence)
        self.assertIn("seed:2005.11401", known)
        self.assertIn("cot2.P2.candidates[0]", known)


class SchemaAndPromptTests(unittest.TestCase):
    def _assert_strict(self, schema, path="$"):
        if "properties" in schema:
            self.assertFalse(schema.get("additionalProperties", True), path)
            self.assertEqual(schema["required"], list(schema["properties"]), path)
            for key, sub in schema["properties"].items():
                self._assert_strict(sub, f"{path}.{key}")
        if "items" in schema:
            self._assert_strict(schema["items"], f"{path}[]")
        self.assertNotIn("minItems", schema, path)

    def test_group_schemas_are_strict(self):
        for group in FIELD_GROUPS:
            self._assert_strict(strict_group_schema(group))

    def test_field_guidance_has_only_group_rows(self):
        text = field_guidance(FIELD_GROUPS["problem"])
        self.assertIn("`limitations_of_existing_approaches`", text)
        self.assertNotIn("`baselines`", text)

    def test_clean_group_drops_empty_optionals(self):
        raw = {"baselines": {"value": [{"id": "B1", "name": "x", "arxiv_id": "", "why": "y"}],
                             "source": [], "inferred": True}, "extra": {}}
        cleaned = clean_group(raw, "validation")
        self.assertEqual(list(cleaned), ["baselines"])
        self.assertNotIn("arxiv_id", cleaned["baselines"]["value"][0])

    def test_error_routing(self):
        outputs = {"problem": {"x": "2401.00001"}, "method": {}, "validation": {}}
        cases = {
            "research_topic: 빈 문자열": {"problem"},
            "M2: 존재하지 않는 한계 L9 참조": {"method"},
            "M3: 어떤 검증 대상(V)에서도 다뤄지지 않음": {"validation"},
            "V4: 어떤 실험(E)에서도 검증되지 않음": {"validation"},
            "화이트리스트에 없는 인용 2401.00001": {"problem"},
            "component_relations: 존재하지 않는 구성요소 'M7'": {"method"},
        }
        for error, expected in cases.items():
            self.assertEqual(groups_for_error(error, outputs), expected, error)


class ProviderTests(unittest.TestCase):
    def test_missing_key_is_reported(self):
        saved, cwd = os.environ.pop("OPENROUTER_API_KEY", None), os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)  # 작업 폴더의 .env를 읽지 않게 한다
            try:
                with self.assertRaises(ProviderError):
                    OpenRouterProvider()
            finally:
                os.chdir(cwd)
                if saved is not None:
                    os.environ["OPENROUTER_API_KEY"] = saved

    def test_parse_fenced_json(self):
        self.assertEqual(parse_json_text('```json\n{"a": 1}\n```'), {"a": 1})


if __name__ == "__main__":
    unittest.main()
