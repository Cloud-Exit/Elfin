"""
Build dataset inventory for Elfin Slice 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


RAW_EXTENSIONS = {".pdf", ".md", ".txt"}
ZIM_EXTENSION = ".zim"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_entries(base_dir: Path, allowed_extensions: set[str]) -> list[dict]:
    entries: list[dict] = []
    if not base_dir.is_dir():
        return entries

    for path in sorted(base_dir.iterdir()):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if path.suffix.lower() not in allowed_extensions:
            continue
        entries.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def render_markdown(raw_entries: list[dict], zim_entries: list[dict]) -> str:
    lines = [
        "# Dataset Inventory",
        "",
        f"- Raw documents: {len(raw_entries)}",
        f"- ZIM archives: {len(zim_entries)}",
        "",
        "## Raw Documents",
        "",
        "| File | Size (bytes) | SHA256 |",
        "|---|---:|---|",
    ]
    for entry in raw_entries:
        lines.append(f"| {entry['name']} | {entry['bytes']} | `{entry['sha256']}` |")

    lines.extend([
        "",
        "## ZIM Archives",
        "",
        "| File | Size (bytes) | SHA256 |",
        "|---|---:|---|",
    ])
    for entry in zim_entries:
        lines.append(f"| {entry['name']} | {entry['bytes']} | `{entry['sha256']}` |")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Elfin dataset inventory")
    parser.add_argument("--raw-dir", default="./datasets/raw", help="Directory containing raw PDFs/docs")
    parser.add_argument("--zim-dir", default="./datasets/zim", help="Directory containing ZIM archives")
    parser.add_argument("--json-out", default="./data/datasets/inventory.json", help="JSON inventory output path")
    parser.add_argument("--md-out", default="./data/datasets/inventory.md", help="Markdown inventory output path")
    args = parser.parse_args()

    raw_entries = collect_entries(Path(args.raw_dir), RAW_EXTENSIONS)
    zim_entries = collect_entries(Path(args.zim_dir), {ZIM_EXTENSION})

    inventory = {
        "raw_documents": raw_entries,
        "zim_archives": zim_entries,
        "counts": {
            "raw_documents": len(raw_entries),
            "zim_archives": len(zim_entries),
        },
    }

    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(inventory, indent=2))
    md_out.write_text(render_markdown(raw_entries, zim_entries))

    print(f"wrote inventory json: {json_out}")
    print(f"wrote inventory md: {md_out}")
    print(f"raw documents: {len(raw_entries)}")
    print(f"zim archives: {len(zim_entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
