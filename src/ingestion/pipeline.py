"""
Elfin ingestion pipeline.

Reads PDFs/MDs/TXTs from data/datasets/raw, chunks them deterministically, embeds via
llama-embed (OpenAI-compatible), and stores vectors in Qdrant. Idempotent via
SHA256 hash. Supports dry-run planning without runtime dependencies.

Usage:
    python pipeline.py [--force] [--dry-run] [--verify-queryable]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import logging
import re
import sys
import uuid
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("elfin-ingest")

DEFAULT_SOURCE_DIR = "./data/datasets/raw"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_EMBED_URL = "http://localhost:8082"
DEFAULT_REPORT_OUT = "./data/ingestion/latest-run.json"
COLLECTION_NAME = "elfin_docs"
SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 200
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768
BATCH_SIZE = 16


@dataclass
class LocalDocument:
    text: str
    metadata: dict = field(default_factory=dict)


def sanitize_text(text: str) -> str:
    cleaned = []
    for ch in text:
        if ch in "\n\t":
            cleaned.append(ch)
            continue
        if ord(ch) < 32:
            continue
        cleaned.append(ch)
    normalized = "".join(cleaned)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


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

    normalized = sanitize_text(text)
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
    """Retrieve all document hashes already in the collection via Qdrant HTTP."""
    hashes = set()
    offset: str | int | None = None

    while True:
        body: dict[str, object] = {
            "limit": 100,
            "with_payload": ["file_hash"],
            "with_vectors": False,
        }
        if offset is not None:
            body["offset"] = offset

        try:
            response = http_json(
                "POST",
                client.rstrip("/") + f"/collections/{collection}/points/scroll",
                body,
            )
        except Exception:
            return set()

        result = response.get("result", {})
        for point in result.get("points", []):
            payload = point.get("payload", {})
            file_hash = payload.get("file_hash")
            if file_hash:
                hashes.add(file_hash)

        offset = result.get("next_page_offset")
        if offset is None:
            break

    return hashes


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}: {exc.reason}"
        try:
            error_body = exc.read().decode(errors="ignore").strip()
        except Exception:
            error_body = ""
        if error_body:
            detail += f" body={error_body[:400]}"
        raise RuntimeError(detail) from exc
    return json.loads(body) if body else {}


def ensure_runtime_dependencies() -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Missing ingestion runtime dependencies. Run `make setup-python` before live ingestion."
        ) from exc


def ensure_collection(qdrant_url: str, collection: str, dim: int) -> None:
    """Create the Qdrant collection if it doesn't exist, with on-disk vectors."""
    collections = http_json("GET", qdrant_url.rstrip("/") + "/collections")
    names = [entry["name"] for entry in collections.get("result", {}).get("collections", [])]
    if collection in names:
        log.info("Collection '%s' already exists", collection)
        return

    log.info("Creating collection '%s' (dim=%d, on_disk=true)", collection, dim)
    http_json(
        "PUT",
        qdrant_url.rstrip("/") + f"/collections/{collection}",
        {
            "vectors": {
                "size": dim,
                "distance": "Cosine",
                "on_disk": True,
            }
        },
    )


def verify_collection_queryable(qdrant_url: str, collection: str) -> dict:
    try:
        result = http_json(
            "POST",
            qdrant_url.rstrip("/") + f"/collections/{collection}/points/count",
            {"exact": False},
        )
        return {"ok": True, "count": result.get("result", {}).get("count")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_document_objects(path: Path) -> list[LocalDocument]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        text = sanitize_text(path.read_text(encoding="utf-8", errors="ignore"))
        if not text:
            raise ValueError(f"document has no extractable text: {path.name}")
        return [LocalDocument(text=text)]

    if suffix == ".pdf":
        header = path.open("rb").read(5)
        if header != b"%PDF-":
            raise ValueError(f"not a valid pdf file: {path.name}")

        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = sanitize_text(page.extract_text() or "")
            if text:
                pages.append(text)
        if not pages:
            raise ValueError(f"pdf has no extractable text: {path.name}")
        return [LocalDocument(text="\n\n".join(pages))]

    raise ValueError(f"unsupported document type: {path}")


def embed_texts(embed_url: str, texts: list[str], model_name: str = EMBED_MODEL) -> list[list[float]]:
    payload_texts = [sanitize_text(text) for text in texts if sanitize_text(text)]
    if not payload_texts:
        raise ValueError("no valid text chunks to embed")
    response = http_json(
        "POST",
        embed_url.rstrip("/") + "/v1/embeddings",
        {"input": payload_texts, "model": model_name},
        timeout=120,
    )
    data = response.get("data", [])
    if len(data) != len(payload_texts):
        raise RuntimeError(f"embedding response mismatch: expected {len(payload_texts)}, got {len(data)}")
    return [item["embedding"] for item in data]


def embed_chunk_records(
    embed_url: str,
    records: list[dict],
    model_name: str = EMBED_MODEL,
) -> tuple[list[tuple[dict, list[float]]], list[dict]]:
    if not records:
        return [], []

    texts = [sanitize_text(record["text"]) for record in records]
    try:
        vectors = embed_texts(embed_url, texts, model_name=model_name)
        return list(zip(records, vectors, strict=True)), []
    except Exception as exc:
        if len(records) == 1:
            return [], [
                {
                    "chunk_index": records[0]["metadata"]["chunk_index"],
                    "error": str(exc),
                }
            ]

        mid = max(1, len(records) // 2)
        log.warning(
            "Embedding batch failed for %d chunks; retrying smaller batches: %s",
            len(records),
            exc,
        )
        left_ok, left_failed = embed_chunk_records(embed_url, records[:mid], model_name=model_name)
        right_ok, right_failed = embed_chunk_records(embed_url, records[mid:], model_name=model_name)
        return left_ok + right_ok, left_failed + right_failed


def upsert_points(qdrant_url: str, collection: str, points: list[dict]) -> None:
    http_json(
        "PUT",
        qdrant_url.rstrip("/") + f"/collections/{collection}/points?wait=true",
        {"points": points},
        timeout=120,
    )


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
    qdrant_client_url = qdrant_url.rstrip("/")

    if not dry_run:
        ensure_runtime_dependencies()
        ensure_collection(qdrant_client_url, COLLECTION_NAME, EMBED_DIM)
        indexed_hashes = set() if force else get_indexed_hashes(qdrant_client_url, COLLECTION_NAME)
    elif force:
        indexed_hashes = set()

    summary["plan"] = plan_documents(all_docs, indexed_hashes=indexed_hashes, force=force)
    pending = [entry for entry in summary["plan"] if entry["status"] == "pending"]

    if dry_run:
        write_report(summary, report_out)
        return summary

    for entry in pending:
        doc_path = Path(entry["path"])
        digest = entry["file_hash"]
        log.info("Processing: %s", doc_path.name)

        try:
            documents = read_document_objects(doc_path)
            chunk_records = build_chunk_records(
                documents,
                source_file=doc_path.name,
                digest=digest,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            chunk_records = [record for record in chunk_records if sanitize_text(record["text"])]
            if not chunk_records:
                raise ValueError(f"document has no valid chunks after sanitization: {doc_path.name}")

            embedded_pairs: list[tuple[dict, list[float]]] = []
            failed_chunks: list[dict] = []
            for start in range(0, len(chunk_records), BATCH_SIZE):
                batch = chunk_records[start : start + BATCH_SIZE]
                for record in batch:
                    record["text"] = sanitize_text(record["text"])
                batch_pairs, batch_failed = embed_chunk_records(embed_url, batch)
                embedded_pairs.extend(batch_pairs)
                failed_chunks.extend(batch_failed)

            if not embedded_pairs:
                raise ValueError(f"document has no embeddable chunks: {doc_path.name}")

            points = []
            for record, vector in embedded_pairs:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{digest}:{record['metadata']['chunk_index']}"))
                points.append(
                    {
                        "id": point_id,
                        "payload": {
                            **record["metadata"],
                            "text": record["text"],
                        },
                        "vector": vector,
                    }
                )

            upsert_points(qdrant_client_url, COLLECTION_NAME, points)
            summary["indexed_documents"].append(
                {
                    "name": doc_path.name,
                    "file_hash": digest,
                    "chunks": len(points),
                    "skipped_chunks": len(failed_chunks),
                }
            )
            if failed_chunks:
                log.warning("  Indexed with %d skipped chunks: %s", len(failed_chunks), doc_path.name)
            log.info("  Indexed: %s (%d chunks)", doc_path.name, len(points))
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
        summary["queryable"] = verify_collection_queryable(qdrant_client_url, COLLECTION_NAME)

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
