from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.training.generate_sft_dataset import (
    EXAMPLE_KINDS,
    build_user_prompt,
    format_record,
    http_openrouter,
    pick_passages,
    run_generation,
    _parse_completion_text,
)


SAMPLE_PASSAGE = {
    "id": "wound_care#0001.abcdef1234",
    "source_file": "wound_care.md",
    "chunk_index": 1,
    "topic": "wounds",
    "text": "Irrigate the wound with clean water and apply a sterile dressing.",
}


def _fake_completion(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class BuildPromptTests(unittest.TestCase):
    def test_prompt_embeds_passage_and_citation(self) -> None:
        prompt = build_user_prompt(SAMPLE_PASSAGE, "positive")
        self.assertIn(SAMPLE_PASSAGE["text"], prompt)
        self.assertIn("wound_care.md#chunk_1", prompt)
        self.assertIn("Example kind: positive", prompt)


class FormatRecordTests(unittest.TestCase):
    def test_record_has_provenance_and_messages(self) -> None:
        record = format_record(SAMPLE_PASSAGE, "follow-up", "u", "a", "model-x")
        self.assertEqual(record["id"], f"{SAMPLE_PASSAGE['id']}::follow-up")
        self.assertEqual(record["provenance"]["passage_id"], SAMPLE_PASSAGE["id"])
        self.assertEqual(record["provenance"]["kind"], "follow-up")
        self.assertEqual(record["provenance"]["model"], "model-x")
        roles = [m["role"] for m in record["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertTrue(record["negative_example"])

    def test_positive_is_not_negative(self) -> None:
        record = format_record(SAMPLE_PASSAGE, "positive", "u", "a", "m")
        self.assertFalse(record["negative_example"])


class ParseCompletionTests(unittest.TestCase):
    def test_parses_clean_json(self) -> None:
        parsed = _parse_completion_text(_fake_completion({"user": "u", "assistant": "a"}))
        self.assertEqual(parsed, {"user": "u", "assistant": "a"})

    def test_parses_json_with_prose_wrapper(self) -> None:
        raw = 'Here you go:\n{"user": "u", "assistant": "a"}\nThanks.'
        response = {"choices": [{"message": {"content": raw}}]}
        parsed = _parse_completion_text(response)
        self.assertEqual(parsed["assistant"], "a")

    def test_missing_keys_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_completion_text(_fake_completion({"foo": "bar"}))


class PickPassagesTests(unittest.TestCase):
    def test_respects_max_per_topic(self) -> None:
        import random
        manifest = [
            {"id": f"wounds-{i}", "topic": "wounds", "source_file": "w.md", "chunk_index": i, "text": "x"}
            for i in range(6)
        ] + [
            {"id": f"frac-{i}", "topic": "fractures", "source_file": "f.md", "chunk_index": i, "text": "x"}
            for i in range(2)
        ]
        picked = pick_passages(manifest, max_per_topic=3, rng=random.Random(0))
        topics = [p["topic"] for p in picked]
        self.assertEqual(topics.count("wounds"), 3)
        self.assertEqual(topics.count("fractures"), 2)


class HttpOpenRouterTests(unittest.TestCase):
    def test_missing_api_key_raises(self) -> None:
        env = os.environ.copy()
        env.pop("OPENROUTER_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                http_openrouter([{"role": "user", "content": "x"}], {})


class RunGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.manifest_path = Path(self._tmp.name) / "manifest.jsonl"
        self.out_path = Path(self._tmp.name) / "out.jsonl"
        with self.manifest_path.open("w") as fh:
            fh.write(json.dumps(SAMPLE_PASSAGE) + "\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_one_record_per_kind_with_stub_client(self) -> None:
        calls: list[str] = []

        def stub_client(messages: list[dict], options: dict) -> dict:
            user_prompt = messages[-1]["content"]
            kind_line = [line for line in user_prompt.splitlines() if line.startswith("Example kind:")][0]
            kind = kind_line.split(":", 1)[1].strip()
            calls.append(kind)
            return _fake_completion(
                {"user": f"what about {kind}?", "assistant": f"answer for {kind}."}
            )

        summary = run_generation(
            self.manifest_path,
            self.out_path,
            max_per_topic=5,
            model="stub",
            client=stub_client,
        )
        self.assertEqual(summary["record_count"], len(EXAMPLE_KINDS))
        self.assertCountEqual(calls, list(EXAMPLE_KINDS))

        lines = [json.loads(line) for line in self.out_path.read_text().splitlines() if line]
        self.assertEqual(len(lines), len(EXAMPLE_KINDS))
        for record in lines:
            self.assertEqual(record["provenance"]["passage_id"], SAMPLE_PASSAGE["id"])
            self.assertEqual(record["provenance"]["source_file"], SAMPLE_PASSAGE["source_file"])
            self.assertEqual(record["provenance"]["model"], "stub")

    def test_errors_are_collected_and_record_count_still_reported(self) -> None:
        def flaky_client(messages: list[dict], options: dict) -> dict:
            raise RuntimeError("HTTP 500")

        summary = run_generation(
            self.manifest_path,
            self.out_path,
            max_per_topic=5,
            model="stub",
            client=flaky_client,
        )
        self.assertEqual(summary["record_count"], 0)
        self.assertEqual(len(summary["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
