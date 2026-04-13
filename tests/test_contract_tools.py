from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evals.validate import validate_scenario
from src.ingestion.validate_sources import build_manifest, collect_source_entries
from src.training.validate_dataset import detect_split, validate_record


class EvalValidationTests(unittest.TestCase):
    def test_validate_scenario_accepts_supported_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "general.dehydration.followup.v1",
                        "category": "medical",
                        "mode": "general",
                        "user_input": "I feel dizzy after being in the sun.",
                        "expected_behaviors": ["ask follow-up questions"],
                    }
                )
            )
            self.assertEqual(validate_scenario(path), [])

    def test_validate_scenario_rejects_bad_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "bad.mode",
                        "category": "medical",
                        "mode": "unsupported",
                        "user_input": "hello",
                        "expected_behaviors": [],
                    }
                )
            )
            errors = validate_scenario(path)
            self.assertTrue(any("unsupported mode" in error for error in errors))


class IngestionValidationTests(unittest.TestCase):
    def test_collect_source_entries_hashes_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            (source_dir / "note.md").write_text("# Water\nBoil before drinking.\n")
            entries, errors = collect_source_entries(source_dir)

            self.assertEqual(errors, [])
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["path"], "note.md")
            self.assertEqual(entries[0]["suffix"], ".md")

            manifest = build_manifest(entries)
            self.assertEqual(manifest["document_count"], 1)
            self.assertEqual(manifest["by_suffix"], {".md": 1})

    def test_collect_source_entries_rejects_unsupported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            (source_dir / "note.docx").write_text("bad")
            entries, errors = collect_source_entries(source_dir)

            self.assertEqual(entries, [])
            self.assertTrue(any("unsupported source file type" in error for error in errors))


class TrainingValidationTests(unittest.TestCase):
    def test_validate_record_accepts_basic_example(self) -> None:
        record = {
            "id": "ft.general.dehydration.followup.v1",
            "category": "medical",
            "messages": [
                {"role": "user", "content": "I am dizzy after heat exposure."},
                {"role": "assistant", "content": "How long? Any vomiting, confusion, or inability to drink?"},
            ],
            "tags": ["follow-up", "dehydration"],
            "negative_example": False,
        }
        self.assertEqual(validate_record(record, Path("sample.jsonl"), 1), [])

    def test_validate_record_requires_assistant_message(self) -> None:
        record = {
            "id": "bad.record",
            "category": "medical",
            "messages": [{"role": "user", "content": "Help"}],
        }
        errors = validate_record(record, Path("sample.jsonl"), 1)
        self.assertTrue(any("assistant message" in error for error in errors))

    def test_detect_split_from_path(self) -> None:
        self.assertEqual(detect_split(Path("seed/train/file.jsonl")), "train")
        self.assertEqual(detect_split(Path("seed/holdout/file.jsonl")), "holdout")
        self.assertEqual(detect_split(Path("seed/custom/file.jsonl")), "unknown")


if __name__ == "__main__":
    unittest.main()
