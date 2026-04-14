"""
Validate Elfin ingestion source documents and write a manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


SUPPORTED_SUFFIXES = {".pdf", ".md", ".txt"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_source_entries(source_dir: Path) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    errors: list[str] = []

    if not source_dir.is_dir():
        return entries, [f"source directory does not exist: {source_dir}"]

    for path in sorted(source_dir.iterdir()):
        if path.name == ".gitkeep":
            continue
        if not path.is_file():
            errors.append(f"unsupported non-file entry: {path}")
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            errors.append(f"unsupported source file type: {path}")
            continue

        entries.append(
            {
                "path": str(path.relative_to(source_dir)),
                "suffix": path.suffix.lower(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    if not entries:
        errors.append(f"no supported source documents found in {source_dir}")

    return entries, errors


def build_manifest(entries: list[dict]) -> dict:
    by_suffix: dict[str, int] = {}
    total_bytes = 0
    for entry in entries:
        by_suffix[entry["suffix"]] = by_suffix.get(entry["suffix"], 0) + 1
        total_bytes += entry["bytes"]

    return {
        "document_count": len(entries),
        "total_bytes": total_bytes,
        "by_suffix": by_suffix,
        "documents": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Elfin ingestion source corpus")
    parser.add_argument("--source-dir", default="./data/datasets/raw", help="Directory containing raw source documents")
    parser.add_argument(
        "--out",
        default="./data/ingestion/source-manifest.json",
        help="Where to write the manifest JSON",
    )
    args = parser.parse_args()

    entries, errors = collect_source_entries(Path(args.source_dir))
    if errors:
        for error in errors:
            print(error)
        return 1

    manifest = build_manifest(entries)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    print(f"validated {manifest['document_count']} ingestion source document(s)")
    print(f"wrote manifest: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
