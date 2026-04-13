from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.ingestion.pipeline import (
    build_chunk_records,
    chunk_text,
    discover_documents,
    plan_documents,
    run_pipeline,
)


class FakeDocument:
    def __init__(self, text: str, metadata: dict | None = None) -> None:
        self.text = text
        self.metadata = metadata or {}


class IngestionPipelineTests(unittest.TestCase):
    def test_discover_documents_filters_and_sorts_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "b.txt").write_text("b")
            (root / "a.md").write_text("a")
            (root / "c.pdf").write_text("pdf")
            (root / "skip.json").write_text("{}")

            docs = discover_documents(root)
            self.assertEqual([path.name for path in docs], ["a.md", "b.txt", "c.pdf"])

    def test_chunk_text_is_deterministic(self) -> None:
        text = "abcdefghij"
        self.assertEqual(chunk_text(text, chunk_size=4, chunk_overlap=1), ["abcd", "defg", "ghij"])
        self.assertEqual(chunk_text(text, chunk_size=4, chunk_overlap=1), ["abcd", "defg", "ghij"])

    def test_plan_documents_skips_indexed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "doc.md"
            path.write_text("hello")
            first_plan = plan_documents([path], indexed_hashes=set(), force=False)
            second_plan = plan_documents([path], indexed_hashes={first_plan[0]["file_hash"]}, force=False)
            force_plan = plan_documents([path], indexed_hashes={first_plan[0]["file_hash"]}, force=True)

            self.assertEqual(first_plan[0]["status"], "pending")
            self.assertEqual(second_plan[0]["status"], "skipped")
            self.assertEqual(force_plan[0]["status"], "pending")

    def test_build_chunk_records_adds_metadata(self) -> None:
        docs = [FakeDocument("abcdefghij")]
        chunks = build_chunk_records(docs, source_file="doc.md", digest="abc", chunk_size=4, chunk_overlap=1)

        self.assertEqual([chunk["text"] for chunk in chunks], ["abcd", "defg", "ghij"])
        self.assertEqual(chunks[0]["metadata"]["source_file"], "doc.md")
        self.assertEqual(chunks[0]["metadata"]["file_hash"], "abc")
        self.assertEqual(chunks[2]["metadata"]["chunk_index"], 2)

    def test_run_pipeline_dry_run_writes_report_without_runtime_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            docs_dir = root / "raw"
            docs_dir.mkdir()
            (docs_dir / "note.md").write_text("water water water")
            report_path = root / "report.json"

            summary = run_pipeline(
                source_dir=str(docs_dir),
                qdrant_url="http://localhost:6333",
                embed_url="http://localhost:8082",
                dry_run=True,
                report_out=str(report_path),
            )

            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text())
            self.assertEqual(summary["discovered_documents"], 1)
            self.assertEqual(payload["plan"][0]["status"], "pending")
            self.assertEqual(payload["failed_documents"], [])


if __name__ == "__main__":
    unittest.main()
