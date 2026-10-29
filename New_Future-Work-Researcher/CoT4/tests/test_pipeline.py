import unittest

from cot4.idea import Constraints, ResearchIdea
from cot4.pipeline import CoT4Pipeline
from cot4.schemas import RESOURCE_GUIDANCE_SCHEMA


REQUIREMENTS = {
    "compute_requirements": "GPU training capacity",
    "data_requirements": "Labeled examples",
    "implementation_steps": ["collect data", "train model", "evaluate"],
    "external_dependencies": [],
    "vague_or_unspecified_steps": [],
}

RESOURCE_GUIDANCE = {
    "compute_resources": "GPU capacity for training; size depends on model and dataset",
    "data_resources": "Labeled examples and permission to use them",
    "tools_and_dependencies": ["Training framework"],
    "team_skills": ["Data annotation", "Model evaluation"],
    "time_and_effort": "Plan time for data collection, training, and evaluation",
    "prerequisites": ["Define evaluation metric"],
    "unknowns_to_confirm": ["Available GPU capacity", "Dataset size"],
    "required_performance_conditions": [],
    "proposed_performance_targets": ["Improve runtime without losing labeling quality"],
}


class FakeProvider:
    model = "fake"

    def __init__(self):
        self.calls = []

    def evaluate(self, *, instructions, document, schema, schema_name):
        self.calls.append((schema_name, instructions, document, schema))
        if schema_name == "cot4_requirements":
            return REQUIREMENTS
        if schema_name == "cot4_resource_guidance":
            return RESOURCE_GUIDANCE
        raise AssertionError(f"Unexpected schema name: {schema_name}")


def make_idea(constraints=None):
    return ResearchIdea(
        title="T", problem="P", proposed_method="M",
        constraints=constraints or Constraints(),
    )


class PipelineTests(unittest.TestCase):
    def test_calls_requirements_then_resource_guidance(self):
        provider = FakeProvider()
        CoT4Pipeline(provider=provider).check(make_idea(Constraints(timeline="1 month")))
        self.assertEqual(
            [call[0] for call in provider.calls],
            ["cot4_requirements", "cot4_resource_guidance"],
        )
        self.assertIs(provider.calls[1][3], RESOURCE_GUIDANCE_SCHEMA)
        self.assertIn('"compute_requirements"', provider.calls[1][2])
        self.assertIn("Timeline: 1 month", provider.calls[1][2])
        self.assertIn("Original idea:", provider.calls[1][2])
        self.assertIn("Do not classify feasibility", provider.calls[1][1])
        self.assertIn("Never promote a target", provider.calls[1][1])

    def test_missing_constraints_are_context_not_a_verdict(self):
        provider = FakeProvider()
        result = CoT4Pipeline(provider=provider).check(make_idea())
        self.assertIn("제약 조건이 제공되지 않음", provider.calls[1][2])
        self.assertEqual(result.resource_guidance, RESOURCE_GUIDANCE)
        self.assertNotIn("classification", result.as_dict())

    def test_as_dict_shape(self):
        result = CoT4Pipeline(provider=FakeProvider()).check(make_idea())
        output = result.as_dict()
        self.assertEqual(
            set(output),
            {"idea_title", "requirements", "resource_guidance", "checked_at"},
        )
        self.assertEqual(output["requirements"], REQUIREMENTS)
        self.assertEqual(output["resource_guidance"], RESOURCE_GUIDANCE)
        self.assertEqual(set(output["resource_guidance"]), set(RESOURCE_GUIDANCE_SCHEMA["required"]))


if __name__ == "__main__":
    unittest.main()
