"""
Elfin ingestion pipeline.

Reads PDFs/MDs/TXTs from datasets/raw, chunks them deterministically, embeds via
llama-embed (OpenAI-compatible), and stores vectors in Qdrant. Idempotent via
SHA256 hash. Supports dry-run planning without runtime dependencies.

Usage:
    python pipeline.py [--force] [--dry-run] [--verify-queryable]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("elfin-ingest")

DEFAULT_SOURCE_DIR = "./datasets/raw"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_EMBED_URL = "http://localhost:8082"
DEFAULT_REPORT_OUT = "./data/ingestion/latest-run.json"
COLLECTION_NAME = "elfin_docs"
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 200
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_documents(source_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")

    normalized = text.strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    text_len = len(normalized)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        start = end - chunk_overlap

    return chunks


def plan_documents(paths: list[Path], indexed_hashes: set[str], force: bool = False) -> list[dict]:
    plan: list[dict] = []
    for path in paths:
        digest = file_hash(path)
        skipped = (not force) and digest in indexed_hashes
        plan.append(
            {
                "path": str(path),
                "name": path.name,
                "file_hash": digest,
                "status": "skipped" if skipped else "pending",
            }
        )
    return plan


def apply_source_metadata(item: object, source_file: str, digest: str, chunk_index: int | None = None) -> dict:
    metadata = dict(getattr(item, "metadata", {}) or {})
    metadata["source_file"] = source_file
    metadata["file_hash"] = digest
    if chunk_index is not None:
        metadata["chunk_index"] = chunk_index
    setattr(item, "metadata", metadata)
    return metadata


def build_chunk_records(
    documents: list[object],
    source_file: str,
    digest: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    chunk_records: list[dict] = []
    next_chunk_index = 0

    for document in documents:
        apply_source_metadata(document, source_file, digest)
        text = getattr(document, "text", "") or ""
        for chunk in chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunk_records.append(
                {
                    "text": chunk,
                    "metadata": {
                        "source_file": source_file,
                        "file_hash": digest,
                        "chunk_index": next_chunk_index,
                    },
                }
            )
            next_chunk_index += 1

    return chunk_records


def get_indexed_hashes(client: object, collection: str) -> set[str]:
    """Retrieve all document hashes already in the collection."""
    try:
        hashes = set()
        offset = None
        while True:
            result = client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=["file_hash"],
            )
            points, next_offset = result
            for point in points:
                if point.payload and "file_hash" in point.payload:
                    hashes.add(point.payload["file_hash"])
            if next_offset is None:
                break
            offset = next_offset
        return hashes
    except Exception:
        return set()


def load_runtime() -> dict:
    try:
        from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
        from llama_index.core.schema import TextNode
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams
    except ImportError as exc:
        raise RuntimeError(
            "Missing ingestion runtime dependencies. Run `make setup-python` before live ingestion."
        ) from exc

    return {
        "SimpleDirectoryReader": SimpleDirectoryReader,
        "StorageContext": StorageContext,
        "VectorStoreIndex": VectorStoreIndex,
        "TextNode": TextNode,
        "OpenAIEmbedding": OpenAIEmbedding,
        "QdrantVectorStore": QdrantVectorStore,
        "QdrantClient": QdrantClient,
        "Distance": Distance,
        "PayloadSchemaType": PayloadSchemaType,
        "VectorParams": VectorParams,
    }


def ensure_collection(client: object, collection: str, dim: int, runtime: dict) -> None:
    """Create the Qdrant collection if it doesn't exist, with on-disk storage."""
    collections = [entry.name for entry in client.get_collections().collections]
    if collection in collections:
        log.info("Collection '%s' already exists", collection)
        return

    log.info("Creating collection '%s' (dim=%d, on_disk=true)", collection, dim)
    client.create_collection(
        collection_name=collection,
        vectors_config=runtime["VectorParams"](
            size=dim,
            distance=runtime["Distance"].COSINE,
            on_disk=True,
        ),
    )
    client.create_payload_index(
        collection_name=collection,
        field_name="file_hash",
        field_schema=runtime["PayloadSchemaType"].KEYWORD,
    )


def build_text_nodes(chunk_records: list[dict], runtime: dict) -> list[object]:
    return [
        runtime["TextNode"](text=record["text"], metadata=record["metadata"])
        for record in chunk_records
    ]


def verify_collection_queryable(client: object, collection: str) -> dict:
    try:
        result = client.count(collection_name=collection, exact=False)
        return {"ok": True, "count": getattr(result, "count", None)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def write_report(summary: dict, report_out: str) -> None:
    out_path = Path(report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    log.info("Wrote ingestion report: %s", out_path)


def run_pipeline(
    source_dir: str,
    qdrant_url: str,
    embed_url: str,
    force: bool = False,
    dry_run: bool = False,
    verify_queryable: bool = False,
    report_out: str = DEFAULT_REPORT_OUT,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> dict:
    source_path = Path(source_dir)
    if not source_path.is_dir():
        raise FileNotFoundError(f"source directory does not exist: {source_dir}")

    all_docs = discover_documents(source_path)
    summary = {
        "source_dir": str(source_path),
        "collection_name": COLLECTION_NAME,
        "discovered_documents": len(all_docs),
        "dry_run": dry_run,
        "plan": [],
        "indexed_documents": [],
        "failed_documents": [],
        "queryable": None,
    }

    if not all_docs:
        log.warning("No documents found in %s", source_dir)
        write_report(summary, report_out)
        return summary

    indexed_hashes: set[str] = set()
    runtime: dict | None = None
    client = None

    if not dry_run:
        runtime = load_runtime()
        client = runtime["QdrantClient"](url=qdrant_url)
        ensure_collection(client, COLLECTION_NAME, EMBED_DIM, runtime)
        indexed_hashes = set() if force else get_indexed_hashes(client, COLLECTION_NAME)
    elif force:
        indexed_hashes = set()

    summary["plan"] = plan_documents(all_docs, indexed_hashes=indexed_hashes, force=force)
    pending = [entry for entry in summary["plan"] if entry["status"] == "pending"]

    if dry_run:
        write_report(summary, report_out)
        return summary

    assert runtime is not None
    assert client is not None

    embed_model = runtime["OpenAIEmbedding"](
        api_base=embed_url.rstrip("/") + "/v1",
        api_key="not-needed",
        model_name=EMBED_MODEL,
    )
    vector_store = runtime["QdrantVectorStore"](client=client, collection_name=COLLECTION_NAME)
    storage_context = runtime["StorageContext"].from_defaults(vector_store=vector_store)

    for entry in pending:
        doc_path = Path(entry["path"])
        digest = entry["file_hash"]
        log.info("Processing: %s", doc_path.name)

        try:
            reader = runtime["SimpleDirectoryReader"](input_files=[str(doc_path)])
            documents = reader.load_data()
            chunk_records = build_chunk_records(
                documents,
                source_file=doc_path.name,
                digest=digest,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            nodes = build_text_nodes(chunk_records, runtime)
            runtime["VectorStoreIndex"](
                nodes,
                storage_context=storage_context,
                embed_model=embed_model,
            )
            summary["indexed_documents"].append(
                {
                    "name": doc_path.name,
                    "file_hash": digest,
                    "chunks": len(nodes),
                }
            )
            log.info("  Indexed: %s (%d chunks)", doc_path.name, len(nodes))
        except Exception as exc:
            summary["failed_documents"].append(
                {
                    "name": doc_path.name,
                    "file_hash": digest,
                    "error": str(exc),
                }
            )
            log.exception("  Failed to process: %s", doc_path.name)

    if verify_queryable:
        summary["queryable"] = verify_collection_queryable(client, COLLECTION_NAME)

    write_report(summary, report_out)
    log.info("Ingestion complete.")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Elfin document ingestion pipeline")
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR, help="Directory with source documents")
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL, help="Qdrant HTTP URL")
    parser.add_argument("--embed-url", default=DEFAULT_EMBED_URL, help="Embedding server URL (OpenAI-compatible)")
    parser.add_argument("--report-out", default=DEFAULT_REPORT_OUT, help="Path for JSON report")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help="Deterministic chunk size")
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP, help="Chunk overlap")
    parser.add_argument("--force", action="store_true", help="Re-index all documents")
    parser.add_argument("--dry-run", action="store_true", help="Plan ingestion without runtime dependencies")
    parser.add_argument("--verify-queryable", action="store_true", help="Check Qdrant collection after ingestion")
    args = parser.parse_args()

    try:
        summary = run_pipeline(
            source_dir=args.source_dir,
            qdrant_url=args.qdrant_url,
            embed_url=args.embed_url,
            force=args.force,
            dry_run=args.dry_run,
            verify_queryable=args.verify_queryable,
            report_out=args.report_out,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
    except Exception as exc:
        log.error("%s", exc)
        return 1

    if summary["failed_documents"]:
        return 1
    if args.verify_queryable and summary["queryable"] and not summary["queryable"].get("ok", False):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
