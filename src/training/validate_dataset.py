"""
Validate Elfin behavior fine-tuning dataset files and write a summary manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


VALID_ROLES = {"system", "user", "assistant"}
VALID_SPLITS = {"train", "validation", "test", "holdout", "smoke"}


def detect_split(path: Path) -> str:
    for part in path.parts:
        if part in VALID_SPLITS:
            return part
    return "unknown"


def validate_record(record: dict, path: Path, line_number: int) -> list[str]:
    prefix = f"{path}:{line_number}"
    errors: list[str] = []

    if not isinstance(record.get("id"), str) or not record["id"].strip():
        errors.append(f"{prefix}: missing or invalid 'id'")
    if not isinstance(record.get("category"), str) or not record["category"].strip():
        errors.append(f"{prefix}: missing or invalid 'category'")

    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        errors.append(f"{prefix}: missing or invalid 'messages'")
        return errors

    roles_seen: set[str] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            errors.append(f"{prefix}: message {index} must be object")
            continue

        role = message.get("role")
        content = message.get("content")
        if role not in VALID_ROLES:
            errors.append(f"{prefix}: message {index} has invalid role '{role}'")
        else:
            roles_seen.add(role)

        if not isinstance(content, str) or not content.strip():
            errors.append(f"{prefix}: message {index} must have non-empty string content")

    if "user" not in roles_seen:
        errors.append(f"{prefix}: record must include at least one user message")
    if "assistant" not in roles_seen:
        errors.append(f"{prefix}: record must include at least one assistant message")

    tags = record.get("tags")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
        errors.append(f"{prefix}: 'tags' must be list[str]")

    negative_example = record.get("negative_example")
    if negative_example is not None and not isinstance(negative_example, bool):
        errors.append(f"{prefix}: 'negative_example' must be boolean")

    for optional_key in ("source", "language", "modality"):
        value = record.get(optional_key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{prefix}: '{optional_key}' must be string")

    return errors


def load_records(dataset_dir: Path) -> tuple[list[dict], list[str]]:
    files = sorted(dataset_dir.rglob("*.jsonl"))
    if not files:
        return [], [f"no dataset files found in {dataset_dir}"]

    records: list[dict] = []
    errors: list[str] = []

    for path in files:
        for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: invalid json: {exc}")
                continue
            if not isinstance(record, dict):
                errors.append(f"{path}:{line_number}: record must be json object")
                continue

            errors.extend(validate_record(record, path, line_number))
            record["_path"] = str(path.relative_to(dataset_dir))
            record["_split"] = detect_split(path.relative_to(dataset_dir))
            records.append(record)

    return records, errors


def build_summary(records: list[dict]) -> dict:
    split_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    negative_examples = 0

    for record in records:
        split = record["_split"]
        category = record["category"]
        split_counts[split] = split_counts.get(split, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if record.get("negative_example"):
            negative_examples += 1

    return {
        "record_count": len(records),
        "split_counts": split_counts,
        "category_counts": category_counts,
        "negative_examples": negative_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Elfin fine-tuning dataset")
    parser.add_argument("--dataset-dir", default="./datasets/training", help="Directory containing JSONL dataset files")
    parser.add_argument(
        "--out",
        default="./data/training/dataset-summary.json",
        help="Where to write the summary JSON",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    records, errors = load_records(dataset_dir)
    if errors:
        for error in errors:
            print(error)
        return 1

    summary = build_summary(records)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"validated {summary['record_count']} training record(s)")
    print(f"wrote summary: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
