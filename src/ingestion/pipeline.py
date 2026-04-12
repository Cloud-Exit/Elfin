"""
LefinOS ingestion pipeline.

Reads PDFs/MDs/TXTs from datasets/raw, chunks them, embeds via llama-server
(OpenAI-compatible), and stores vectors in Qdrant. Idempotent via SHA256 hash.

Usage:
    python pipeline.py [--force] [--source-dir DIR] [--qdrant-url URL] [--embed-url URL]
"""

import argparse
import hashlib
import logging
import sys
from pathlib import Path

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("lefin-ingest")

DEFAULT_SOURCE_DIR = "./datasets/raw"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_EMBED_URL = "http://localhost:8082"
COLLECTION_NAME = "lefin_docs"
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 200
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_indexed_hashes(client: QdrantClient, collection: str) -> set:
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


def ensure_collection(client: QdrantClient, collection: str, dim: int):
    """Create the Qdrant collection if it doesn't exist, with on-disk storage."""
    collections = [c.name for c in client.get_collections().collections]
    if collection in collections:
        log.info("Collection '%s' already exists", collection)
        return

    log.info("Creating collection '%s' (dim=%d, on_disk=true)", collection, dim)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(
            size=dim,
            distance=Distance.COSINE,
            on_disk=True,
        ),
    )
    # Index the file_hash field for efficient dedup lookups
    client.create_payload_index(
        collection_name=collection,
        field_name="file_hash",
        field_schema=PayloadSchemaType.KEYWORD,
    )


def discover_documents(source_dir: Path) -> list[Path]:
    exts = {".pdf", ".md", ".txt"}
    return sorted(p for p in source_dir.iterdir() if p.suffix.lower() in exts)


def run_pipeline(
    source_dir: str,
    qdrant_url: str,
    embed_url: str,
    force: bool = False,
):
    source_path = Path(source_dir)
    if not source_path.is_dir():
        log.error("Source directory does not exist: %s", source_dir)
        sys.exit(1)

    all_docs = discover_documents(source_path)
    if not all_docs:
        log.warning("No documents found in %s", source_dir)
        return

    log.info("Found %d documents in %s", len(all_docs), source_dir)

    # Connect to Qdrant
    client = QdrantClient(url=qdrant_url)
    ensure_collection(client, COLLECTION_NAME, EMBED_DIM)

    # Check which documents are already indexed
    if force:
        log.info("Force mode: re-indexing all documents")
        docs_to_index = all_docs
    else:
        indexed_hashes = get_indexed_hashes(client, COLLECTION_NAME)
        docs_to_index = []
        for doc_path in all_docs:
            h = file_hash(doc_path)
            if h in indexed_hashes:
                log.info("Skipping (already indexed): %s", doc_path.name)
            else:
                docs_to_index.append(doc_path)

    if not docs_to_index:
        log.info("All documents already indexed. Nothing to do.")
        return

    log.info("Indexing %d new documents", len(docs_to_index))

    # Set up embedding model (OpenAI-compatible, pointing at llama-embed)
    embed_model = OpenAIEmbedding(
        api_base=embed_url + "/v1",
        api_key="not-needed",
        model_name=EMBED_MODEL,
    )

    # Set up Qdrant vector store via LlamaIndex
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Process each document
    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    for doc_path in docs_to_index:
        log.info("Processing: %s", doc_path.name)
        h = file_hash(doc_path)

        try:
            reader = SimpleDirectoryReader(input_files=[str(doc_path)])
            documents = reader.load_data()

            # Inject metadata
            for doc in documents:
                doc.metadata["source_file"] = doc_path.name
                doc.metadata["file_hash"] = h

            nodes = splitter.get_nodes_from_documents(documents)
            log.info("  %d chunks from %s", len(nodes), doc_path.name)

            # Ensure metadata propagates to nodes
            for node in nodes:
                node.metadata["source_file"] = doc_path.name
                node.metadata["file_hash"] = h

            VectorStoreIndex(
                nodes,
                storage_context=storage_context,
                embed_model=embed_model,
            )
            log.info("  Indexed: %s", doc_path.name)

        except Exception:
            log.exception("  Failed to process: %s", doc_path.name)

    log.info("Ingestion complete.")


def main():
    parser = argparse.ArgumentParser(description="LefinOS document ingestion pipeline")
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR, help="Directory with source documents")
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL, help="Qdrant HTTP URL")
    parser.add_argument("--embed-url", default=DEFAULT_EMBED_URL, help="Embedding server URL (OpenAI-compatible)")
    parser.add_argument("--force", action="store_true", help="Re-index all documents")
    args = parser.parse_args()

    run_pipeline(
        source_dir=args.source_dir,
        qdrant_url=args.qdrant_url,
        embed_url=args.embed_url,
        force=args.force,
    )


if __name__ == "__main__":
    main()
