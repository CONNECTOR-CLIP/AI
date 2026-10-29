import asyncio
import threading
import unittest

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
    def __init__(self):
        self.events = []

    def check(self, idea):
        self.events.append(("CoT4", idea.title))
        return {"idea_title": idea.title, "resource_guidance": {"compute_resources": "GPU access"}}


class Cot4ThenCot5Tests(unittest.TestCase):
    def test_cot4_checks_overlap_and_keep_input_order(self):
        barrier = threading.Barrier(2, timeout=2)

        class ConcurrentPipeline:
            def check(self, idea):
                barrier.wait()
                return {"idea_title": idea.title, "resource_guidance": {"compute_resources": "GPU access"}}

        async def cot5_check(idea):
            return {"idea_title": idea.title}

        report = asyncio.run(run_cot4_then_cot5(
            PAYLOAD, cot4_pipeline=ConcurrentPipeline(), cot5_check=cot5_check,
        ))
        self.assertTrue(report["gate"]["passed"])
        self.assertEqual(
            [result["idea_title"] for result in report["CoT4"]["results"]],
            [item["proposed_direction"] for item in PAYLOAD["future_work_proposals"]],
        )

    def test_cot5_runs_only_after_all_cot4_results_pass(self):
        cot4 = FakeCot4Pipeline()
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

    def test_cot5_checks_overlap_after_cot4_gate(self):
        cot4 = FakeCot4Pipeline()
        entered = 0
        both_started = asyncio.Event()

        async def cot5_check(idea):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=2)
            return {"idea_title": idea.title, "classification": "NOVEL"}

        report = asyncio.run(run_cot4_then_cot5(
            PAYLOAD, cot4_pipeline=cot4, cot5_check=cot5_check,
        ))
        self.assertEqual(entered, 2)
        self.assertEqual(report["CoT5"]["status"], "completed")

    def test_cot5_runs_without_feasibility_classification(self):
        cot4 = FakeCot4Pipeline()
        cot5_calls = []

        async def cot5_check(idea):
            cot5_calls.append(idea.title)
            return {"idea_title": idea.title, "classification": "NOVEL"}

        report = asyncio.run(
            run_cot4_then_cot5(PAYLOAD, cot4_pipeline=cot4, cot5_check=cot5_check)
        )
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["gate"]["passed"])
        self.assertEqual(report["gate"]["name"], "CoT4 resource guidance")
        self.assertEqual(len(cot5_calls), 2)

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
        self.assertEqual(report["CoT4"]["results"][0]["status"], "error")
        self.assertEqual(report["CoT5"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
