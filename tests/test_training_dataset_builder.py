from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.training.dataset_builder import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    build_passages,
    chunk_text,
    classify_topic,
    discover_documents,
    passage_id,
    summarize,
    write_manifest,
)


class ChunkTextTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self) -> None:
        text = "Keep the wound clean and dry."
        self.assertEqual(chunk_text(text), [text])

    def test_long_text_splits_with_overlap(self) -> None:
        paragraph = "Splinting immobilizes the fracture and reduces pain. " * 40
        chunks = chunk_text(paragraph, chunk_size=500, chunk_overlap=100)
        self.assertGreater(len(chunks), 1)
        joined = " ".join(chunks)
        self.assertIn("Splinting immobilizes", joined)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    def test_blank_input_returns_empty(self) -> None:
        self.assertEqual(chunk_text(""), [])


class ClassifyTopicTests(unittest.TestCase):
    def test_fracture_keyword_wins(self) -> None:
        self.assertEqual(classify_topic("Splint the fracture and immobilize the joint."), "fractures")

    def test_dehydration_detected(self) -> None:
        self.assertEqual(classify_topic("Give oral rehydration salts for dehydration after diarrhea."), "dehydration")

    def test_general_default(self) -> None:
        self.assertEqual(classify_topic("Elfin is a field assistant."), "general")


class PassageIdTests(unittest.TestCase):
    def test_ids_are_stable_for_identical_input(self) -> None:
        a = passage_id("doc.pdf", 3, "Clean the wound thoroughly.")
        b = passage_id("doc.pdf", 3, "Clean the wound thoroughly.")
        self.assertEqual(a, b)

    def test_ids_differ_on_chunk_or_text_change(self) -> None:
        base = passage_id("doc.pdf", 3, "Clean the wound thoroughly.")
        self.assertNotEqual(base, passage_id("doc.pdf", 4, "Clean the wound thoroughly."))
        self.assertNotEqual(base, passage_id("doc.pdf", 3, "Clean the wound."))


class BuildPassagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.source = Path(self._tmp.name)
        (self.source / "wound_care.md").write_text(
            "Irrigate the wound with clean water. Apply a sterile dressing and monitor for infection. "
            "Watch for spreading redness, swelling, fever, or foul odor as warning signs of infection. "
            "Change the dressing daily and keep the limb elevated if possible to reduce swelling."
        )
        (self.source / "fracture_care.md").write_text(
            "Immobilize the fracture with a splint. Check distal circulation before and after splinting. "
            "Pad bony prominences and secure the splint firmly but not so tight that it cuts off blood flow. "
            "If circulation worsens, loosen the splint and reassess."
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_discover_documents_returns_supported_files(self) -> None:
        docs = discover_documents(self.source)
        self.assertEqual({p.name for p in docs}, {"wound_care.md", "fracture_care.md"})

    def test_build_passages_yields_tagged_records(self) -> None:
        records = build_passages(self.source, chunk_size=400, chunk_overlap=50)
        self.assertGreaterEqual(len(records), 2)
        sources = {r["source_file"] for r in records}
        self.assertEqual(sources, {"wound_care.md", "fracture_care.md"})
        topics = {r["topic"] for r in records}
        self.assertTrue(topics.intersection({"wounds", "fractures"}))
        for record in records:
            self.assertIn("id", record)
            self.assertIn("text", record)
            self.assertGreater(len(record["text"]), 0)

    def test_build_passages_is_deterministic(self) -> None:
        first = build_passages(self.source, chunk_size=400, chunk_overlap=50)
        second = build_passages(self.source, chunk_size=400, chunk_overlap=50)
        self.assertEqual(first, second)

    def test_write_manifest_emits_jsonl(self) -> None:
        records = build_passages(self.source, chunk_size=400, chunk_overlap=50)
        out = Path(self._tmp.name) / "manifest.jsonl"
        write_manifest(records, out)
        lines = [json.loads(line) for line in out.read_text().splitlines() if line]
        self.assertEqual(len(lines), len(records))
        self.assertEqual(set(lines[0].keys()), {"id", "source_file", "chunk_index", "topic", "text"})

    def test_summarize_counts_topics_and_sources(self) -> None:
        records = build_passages(self.source, chunk_size=400, chunk_overlap=50)
        summary = summarize(records)
        self.assertEqual(summary["passage_count"], len(records))
        self.assertEqual(sum(summary["source_counts"].values()), len(records))
        self.assertEqual(sum(summary["topic_counts"].values()), len(records))


if __name__ == "__main__":
    unittest.main()
