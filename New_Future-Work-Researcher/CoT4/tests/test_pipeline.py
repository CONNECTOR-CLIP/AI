import unittest

from cot4.idea import Constraints, ResearchIdea
from cot4.pipeline import CoT4Pipeline

REQUIREMENTS = {
    "compute_requirements": "1x A100 GPU for 2 days",
    "data_requirements": "10k labeled examples",
    "implementation_steps": ["collect data", "train model", "evaluate"],
    "external_dependencies": [],
    "vague_or_unspecified_steps": [],
}

NO_CONCERN = {"present": False, "explanation": ""}


def make_judgment(classification, missing_constraints=None):
    return {
        "classification": classification,
        "resource_concern": NO_CONCERN,
        "data_concern": NO_CONCERN,
        "implementation_concern": NO_CONCERN,
        "methodological_concern": NO_CONCERN,
        "missing_constraints": missing_constraints or [],
        "rationale": "looks fine",
        "confidence": 0.8,
    }


class FakeProvider:
    model = "fake"

    def __init__(self, judgment):
        self.judgment = judgment
        self.calls = []

    def evaluate(self, *, instructions, document, schema, schema_name):
        self.calls.append(schema_name)
        if schema_name == "cot4_requirements":
            return REQUIREMENTS
        return self.judgment


def make_idea(constraints=None):
    return ResearchIdea(
        title="T", problem="P", proposed_method="M",
        constraints=constraints or Constraints(),
    )


class PipelineTests(unittest.TestCase):
    def test_calls_requirements_then_feasibility(self):
        provider = FakeProvider(make_judgment("FEASIBLE"))
        CoT4Pipeline(provider=provider).check(make_idea(Constraints(timeline="1 month")))
        self.assertEqual(provider.calls, ["cot4_requirements", "cot4_feasibility"])

    def test_warns_when_feasible_with_no_constraints(self):
        provider = FakeProvider(make_judgment("FEASIBLE"))
        result = CoT4Pipeline(provider=provider).check(make_idea())
        self.assertTrue(any("제약 조건" in w for w in result.warnings))

    def test_no_warning_when_feasible_with_constraints(self):
        provider = FakeProvider(make_judgment("FEASIBLE"))
        result = CoT4Pipeline(provider=provider).check(make_idea(Constraints(timeline="1 month")))
        self.assertEqual(result.warnings, [])

    def test_no_warning_when_questionable_with_no_constraints(self):
        # 규칙은 FEASIBLE인 경우에만 강제 경고한다. QUESTIONABLE은 이미 불확실성을 담고 있으므로.
        provider = FakeProvider(make_judgment("QUESTIONABLE"))
        result = CoT4Pipeline(provider=provider).check(make_idea())
        self.assertEqual(result.warnings, [])

    def test_as_dict_shape(self):
        provider = FakeProvider(make_judgment("INFEASIBLE"))
        result = CoT4Pipeline(provider=provider).check(make_idea(Constraints(timeline="1 week")))
        d = result.as_dict()
        self.assertEqual(d["classification"], "INFEASIBLE")
        self.assertEqual(set(d["concerns"].keys()), {"resource", "data", "implementation", "methodological"})
        self.assertEqual(d["requirements"], REQUIREMENTS)


if __name__ == "__main__":
    unittest.main()
