import asyncio
import unittest

import CoT4
from run_cot4_then_cot5 import run_cot4_then_cot5


PAYLOAD = {
    "future_work_proposals": [
        {
            "id": 1,
            "background_and_gap": "A concrete gap",
            "proposed_direction": "A concrete method",
        },
        {
            "id": 2,
            "background_and_gap": "Another concrete gap",
            "proposed_direction": "Another concrete method",
        },
    ]
}


class FakeCot4Pipeline:
    def __init__(self, classifications):
        self.classifications = iter(classifications)
        self.events = []

    def check(self, idea):
        self.events.append(("CoT4", idea.title))
        return {"idea_title": idea.title, "classification": next(self.classifications)}


class Cot4ThenCot5Tests(unittest.TestCase):
    def test_cot5_runs_only_after_all_cot4_results_pass(self):
        cot4 = FakeCot4Pipeline(["FEASIBLE", "FEASIBLE"])
        events = cot4.events

        async def cot5_check(idea):
            events.append(("CoT5", idea.title))
            return {"idea_title": idea.title, "classification": "NOVEL"}

        report = asyncio.run(
            run_cot4_then_cot5(PAYLOAD, cot4_pipeline=cot4, cot5_check=cot5_check)
        )

        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["gate"]["passed"])
        self.assertEqual(report["CoT5"]["status"], "completed")
        self.assertEqual([stage for stage, _ in events], ["CoT4", "CoT4", "CoT5", "CoT5"])

    def test_cot5_is_skipped_when_any_cot4_result_does_not_pass(self):
        cot4 = FakeCot4Pipeline(["FEASIBLE", "QUESTIONABLE"])
        cot5_calls = []

        async def cot5_check(idea):
            cot5_calls.append(idea.title)
            return {"idea_title": idea.title, "classification": "NOVEL"}

        report = asyncio.run(
            run_cot4_then_cot5(PAYLOAD, cot4_pipeline=cot4, cot5_check=cot5_check)
        )

        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["gate"]["passed"])
        self.assertEqual(report["gate"]["failed_ideas"], ["Another concrete method"])
        self.assertEqual(report["CoT5"], {
            "status": "skipped",
            "results": [],
            "reason": "CoT4 validation did not pass for every proposal.",
        })
        self.assertEqual(cot5_calls, [])

    def test_cot4_error_is_a_gate_failure(self):
        class ErrorPipeline:
            def check(self, idea):
                raise RuntimeError("validation unavailable")

        async def cot5_check(_idea):
            self.fail("CoT5 must not run after a CoT4 error")

        report = asyncio.run(
            run_cot4_then_cot5(PAYLOAD, cot4_pipeline=ErrorPipeline(), cot5_check=cot5_check)
        )

        self.assertFalse(report["gate"]["passed"])
        self.assertEqual(report["CoT4"]["results"][0]["classification"], "ERROR")
        self.assertEqual(report["CoT5"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
