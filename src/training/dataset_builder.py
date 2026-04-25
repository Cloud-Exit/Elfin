"""
Build a passage manifest from Elfin's local downloaded corpus.

Reads PDFs and markdown files from the local dataset dir, chunks them into
survival-relevant passages, tags each by topic, and emits a JSONL manifest with
stable ids and provenance. Downstream SFT generation reads this manifest.

No remote calls, no cloud storage. Local only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


SUPPORTED_SUFFIXES = {".pdf", ".md", ".txt"}
DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 150
MIN_PASSAGE_CHARS = 200


TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "wounds": (
        "wound", "bleed", "hemorrhage", "laceration", "puncture", "infection",
        "antiseptic", "irrigate", "dressing", "bandage", "suture", "debride",
    ),
    "fractures": (
        "fracture", "splint", "break", "broken bone", "immobilize", "dislocation",
        "joint", "traction",
    ),
    "burns": (
        "burn", "scald", "thermal injury", "blister", "char", "inhalation injury",
    ),
    "dehydration": (
        "dehydration", "fluid loss", "oral rehydration", "ors", "electrolyte",
        "diarrhea", "vomiting",
    ),
    "sanitation": (
        "sanitation", "hygiene", "water treatment", "disinfect", "chlorine",
        "potable", "contamination", "latrine", "waste",
    ),
    "exposure": (
        "hypothermia", "heat stroke", "heat exhaustion", "heat illness",
        "frostbite", "exposure", "shelter",
    ),
    "navigation": (
        "navigation", "map", "compass", "bearing", "landmark", "route",
        "evacuation",
    ),
    "mental_state": (
        "psychological first aid", "anxiety", "panic", "ptsd", "stress",
        "trauma", "depression", "grief",
    ),
    "sepsis": (
        "sepsis", "septic", "systemic infection", "organ failure",
    ),
    "uncertainty": (
        "monitor", "watch for", "if unsure", "unknown", "danger signs",
        "warning signs",
    ),
}


def sanitize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r" ", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def discover_documents(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        return []
    return sorted(p for p in source_dir.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES and p.is_file())


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pypdf is required to read PDF sources") from exc
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    raise ValueError(f"unsupported suffix: {suffix}")


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    text = sanitize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + chunk_size)
        if end < length:
            window = text[start:end]
            break_at = max(window.rfind("\n\n"), window.rfind(". "))
            if break_at > chunk_size // 2:
                end = start + break_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == length:
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def classify_topic(text: str) -> str:
    lowered = text.lower()
    best_topic = "general"
    best_score = 0
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic


def passage_id(source_file: str, chunk_index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    stem = Path(source_file).stem
    return f"{stem}#{chunk_index:04d}.{digest}"


def build_passages(source_dir: Path, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[dict]:
    records: list[dict] = []
    for doc in discover_documents(source_dir):
        try:
            raw = read_document(doc)
        except Exception as exc:
            print(f"[warn] failed to read {doc}: {exc}", file=sys.stderr)
            continue
        rel = doc.relative_to(source_dir).as_posix()
        for index, chunk in enumerate(chunk_text(raw, chunk_size=chunk_size, chunk_overlap=chunk_overlap)):
            if len(chunk) < MIN_PASSAGE_CHARS:
                continue
            records.append(
                {
                    "id": passage_id(rel, index, chunk),
                    "source_file": rel,
                    "chunk_index": index,
                    "topic": classify_topic(chunk),
                    "text": chunk,
                }
            )
    records.sort(key=lambda r: (r["source_file"], r["chunk_index"]))
    return records


def write_manifest(records: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True))
            fh.write("\n")


def summarize(records: list[dict]) -> dict:
    topic_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for record in records:
        topic_counts[record["topic"]] = topic_counts.get(record["topic"], 0) + 1
        source_counts[record["source_file"]] = source_counts.get(record["source_file"], 0) + 1
    return {
        "passage_count": len(records),
        "topic_counts": dict(sorted(topic_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build local passage manifest for Elfin fine-tune pipeline")
    parser.add_argument("--source-dir", default="./data/datasets/raw", help="Directory containing PDFs / markdown")
    parser.add_argument("--out", default="./data/training/passage-manifest.jsonl", help="Output manifest path")
    parser.add_argument("--summary-out", default="./data/training/passage-summary.json", help="Output summary path")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(f"[error] source dir not found: {source_dir}", file=sys.stderr)
        return 1

    records = build_passages(source_dir, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    if not records:
        print(f"[error] no passages produced from {source_dir}", file=sys.stderr)
        return 1

    write_manifest(records, Path(args.out))
    summary = summarize(records)
    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote {len(records)} passages to {args.out}")
    print(f"wrote summary to {args.summary_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
