"""
Verify Elfin Slice 2 dataset procurement outputs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def load_raw_doc_filenames(path: Path) -> list[str]:
    filenames: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) < 3:
            continue
        filenames.append(parts[1])
    return filenames


def load_zim_specs(path: Path) -> list[str]:
    specs: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        specs.append(stripped)
    return specs


def verify_raw_docs(raw_dir: Path, config_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if not config_path.is_file():
        return [f"missing raw docs config: {config_path}"], notes

    for filename in load_raw_doc_filenames(config_path):
        path = raw_dir / filename
        if path.is_file() and path.stat().st_size > 0:
            notes.append(f"raw doc present: {filename}")
        else:
            errors.append(f"missing raw doc: {path}")
    return errors, notes


def verify_zims(zim_dir: Path, config_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    if not config_path.is_file():
        return [f"missing zim config: {config_path}"], notes

    files = [path.name for path in zim_dir.glob("*.zim")]
    for spec in load_zim_specs(config_path):
        name = spec.split("|", 1)[0]
        if any(filename.startswith(name + "_") or filename == name + ".zim" for filename in files):
            notes.append(f"zim present for spec: {spec}")
        else:
            errors.append(f"missing zim for spec: {spec}")
    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Elfin Slice 2 datasets")
    parser.add_argument("--raw-dir", default="./datasets/raw", help="Directory containing raw source docs")
    parser.add_argument("--zim-dir", default="./datasets/zim", help="Directory containing ZIM archives")
    parser.add_argument("--raw-config", default="./config/raw-docs.tsv", help="Raw docs config file")
    parser.add_argument("--zim-config", default="./config/kiwix-zims.txt", help="Kiwix ZIM config file")
    args = parser.parse_args()

    errors: list[str] = []
    notes: list[str] = []

    raw_errors, raw_notes = verify_raw_docs(Path(args.raw_dir), Path(args.raw_config))
    zim_errors, zim_notes = verify_zims(Path(args.zim_dir), Path(args.zim_config))

    errors.extend(raw_errors)
    errors.extend(zim_errors)
    notes.extend(raw_notes)
    notes.extend(zim_notes)

    print("Slice 2 verification")
    for note in notes:
        print(f"[ok] {note}")
    for error in errors:
        print(f"[error] {error}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
