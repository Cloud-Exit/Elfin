from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.training.validate_dataset import (
    DEFAULT_SPLIT_RATIOS,
    assign_splits,
    content_fingerprint,
    detect_duplicates,
    length_lints,
    load_records,
    policy_lints,
    split_bucket,
    write_splits,
)


def make_record(
    rid: str = "ft.example.1",
    user: str = "How do I clean a wound?",
    assistant: str = "Irrigate the wound with clean water, then apply a sterile dressing. Monitor daily for redness, warmth, or fever.",
    category: str = "medical",
    negative: bool = False,
) -> dict:
    return {
        "id": rid,
        "category": category,
        "language": "en",
        "modality": "text",
        "tags": ["positive"],
        "negative_example": negative,
        "source": "seed",
        "messages": [
            {"role": "system", "content": "You are Elfin."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }


class LengthLintTests(unittest.TestCase):
    def test_rejects_short_user_text(self) -> None:
        errors = length_lints(make_record(user="hi"), "p")
        self.assertTrue(any("user text too short" in e for e in errors))

    def test_accepts_normal_lengths(self) -> None:
        errors = length_lints(make_record(), "p")
        self.assertEqual(errors, [])


class PolicyLintTests(unittest.TestCase):
    def test_rejects_unconditional_referral(self) -> None:
        record = make_record(
            assistant="You must seek medical attention immediately. Rest and hydrate."
        )
        errors = policy_lints(record, "p")
        self.assertTrue(any("unconditional medical referral" in e for e in errors))

    def test_accepts_conditional_referral(self) -> None:
        record = make_record(
            assistant=(
                "Clean the wound, apply pressure, monitor for spreading redness. "
                "If skilled medical help is available, seek evaluation for a contaminated puncture wound."
            )
        )
        self.assertEqual(policy_lints(record, "p"), [])

    def test_negative_example_is_exempt_from_referral_lint(self) -> None:
        record = make_record(
            assistant="You must seek medical attention immediately.",
            negative=True,
        )
        self.assertEqual(policy_lints(record, "p"), [])

    def test_flags_online_resources(self) -> None:
        record = make_record(
            assistant="Clean the wound and then google it for more info on healing stages.",
        )
        errors = policy_lints(record, "p")
        self.assertTrue(any("offline-first violation" in e for e in errors))


class DuplicateTests(unittest.TestCase):
    def test_fingerprint_ignores_whitespace_case(self) -> None:
        a = make_record(user="Clean  the wound.", assistant="Apply a dressing.")
        b = make_record(rid="other", user="clean the WOUND.", assistant="apply a DRESSING.")
        self.assertEqual(content_fingerprint(a), content_fingerprint(b))

    def test_detect_duplicates_flags_collision(self) -> None:
        a = make_record(rid="a", user="Clean the wound.", assistant="Apply a dressing.")
        b = make_record(rid="b", user="Clean the wound.", assistant="Apply a dressing.")
        a["_path"] = "train/a.jsonl"
        b["_path"] = "train/b.jsonl"
        errors = detect_duplicates([a, b])
        self.assertTrue(any("duplicate content" in e for e in errors))

    def test_detect_duplicate_ids(self) -> None:
        a = make_record(rid="same"); a["_path"] = "train/a.jsonl"
        b = make_record(rid="same", user="Different question here?"); b["_path"] = "train/b.jsonl"
        errors = detect_duplicates([a, b])
        self.assertTrue(any("duplicate id 'same'" in e for e in errors))


class LoadRecordsTests(unittest.TestCase):
    def test_rejects_invalid_schema_and_unconditional_referral_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            root.mkdir()
            (root / "a.jsonl").write_text(
                json.dumps(make_record(assistant="Call 911 immediately.")) + "\n"
            )
            records, errors = load_records(Path(tmp))
            self.assertEqual(len(records), 1)
            self.assertTrue(any("unconditional medical referral" in e for e in errors))


class SplitAssignmentTests(unittest.TestCase):
    def test_split_bucket_is_deterministic(self) -> None:
        first = split_bucket("abc", DEFAULT_SPLIT_RATIOS)
        for _ in range(5):
            self.assertEqual(split_bucket("abc", DEFAULT_SPLIT_RATIOS), first)

    def test_assign_splits_covers_all_records(self) -> None:
        records = [make_record(rid=f"id-{i}") for i in range(200)]
        buckets = assign_splits(records)
        total = sum(len(v) for v in buckets.values())
        self.assertEqual(total, len(records))
        self.assertEqual(set(buckets), {"train", "validation", "holdout", "frozen"})
        self.assertGreater(len(buckets["train"]), len(buckets["validation"]))
        self.assertGreater(len(buckets["train"]), len(buckets["holdout"]))

    def test_write_splits_produces_stable_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "splits"
            records = [make_record(rid=f"id-{i}") for i in range(20)]
            buckets = assign_splits(records)
            counts = write_splits(buckets, out_dir)
            self.assertEqual(sum(counts.values()), 20)
            train_lines = [
                json.loads(l)
                for l in (out_dir / "train.jsonl").read_text().splitlines()
                if l
            ]
            for line in train_lines:
                self.assertNotIn("_path", line)
                self.assertNotIn("_split", line)


if __name__ == "__main__":
    unittest.main()
