from __future__ import annotations

import json
from pathlib import Path
import unittest

from new_harness.schemas import (
    SCHEMA_VERSION,
    HarnessInput,
    SchemaValidationError,
    SelectedPaperInput,
    UserDraftInput,
    parse_arxiv_reference,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "selected_papers_arxiv.json"


class ArxivReferenceTests(unittest.TestCase):
    def test_valid_references_normalize_to_abs_and_pdf_urls(self) -> None:
        expected = {
            "2401.14196": "2401.14196",
            "arXiv:2401.14196": "2401.14196",
            "https://arxiv.org/abs/2401.14196": "2401.14196",
            "https://arxiv.org/pdf/2401.14196.pdf": "2401.14196",
            "cs/9901001": "cs/9901001",
        }

        for raw_value, arxiv_id in expected.items():
            with self.subTest(raw_value=raw_value):
                parsed = parse_arxiv_reference(raw_value)

                self.assertEqual(parsed.arxiv_id, arxiv_id)
                self.assertEqual(parsed.abs_url, f"https://arxiv.org/abs/{arxiv_id}")
                self.assertEqual(parsed.pdf_url, f"https://arxiv.org/pdf/{arxiv_id}.pdf")

    def test_rejects_non_arxiv_urls(self) -> None:
        with self.assertRaises(SchemaValidationError):
            parse_arxiv_reference("https://example.com/abs/2401.14196")


class SchemaInputTests(unittest.TestCase):
    def test_fixture_loads_selected_papers_and_optional_user_draft(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        harness_input = HarnessInput.from_dict(payload)

        self.assertEqual(harness_input.schema_version, SCHEMA_VERSION)
        self.assertEqual(len(harness_input.selected_papers), 5)
        self.assertEqual(harness_input.selected_papers[0].arxiv_id, "2401.14196")
        self.assertEqual(harness_input.selected_papers[-1].arxiv_id, "cs/9901001")
        self.assertIsNotNone(harness_input.user_draft)
        self.assertEqual(
            harness_input.user_draft.draft_text,
            "This is optional draft text for the harness input.",
        )
        self.assertEqual(harness_input.user_draft.memo_text, "This is optional memo text.")

    def test_schema_version_defaults_to_one(self) -> None:
        selected_paper = SelectedPaperInput(source="2401.14196")
        user_draft = UserDraftInput(memo_text="memo")

        self.assertEqual(selected_paper.schema_version, 1)
        self.assertEqual(user_draft.schema_version, 1)

    def test_optional_user_draft_accepts_draft_or_memo_text(self) -> None:
        self.assertEqual(UserDraftInput(draft_text="draft").draft_text, "draft")
        self.assertEqual(UserDraftInput(memo_text="memo").memo_text, "memo")

    def test_rejects_unsupported_schema_version(self) -> None:
        with self.assertRaises(SchemaValidationError):
            SelectedPaperInput(source="2401.14196", schema_version=2)


if __name__ == "__main__":
    unittest.main()
