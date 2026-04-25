"""
Validate Elfin behavior fine-tuning dataset files and write a summary manifest.

Checks:
- schema: required keys, role set, non-empty content
- duplicate detection across the corpus (exact and near-duplicate)
- length/format limits for user/assistant turns
- policy lint rules for offline-first Elfin behavior

Also produces deterministic train/validation/held-out/frozen-benchmark splits
keyed on a stable hash of the record id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


VALID_ROLES = {"system", "user", "assistant"}
VALID_SPLITS = {"train", "validation", "test", "holdout", "smoke", "frozen"}

MIN_USER_CHARS = 4
MAX_USER_CHARS = 4000
MIN_ASSISTANT_CHARS = 8
MAX_ASSISTANT_CHARS = 6000


UNCONDITIONAL_REFERRAL_PATTERNS: tuple[str, ...] = (
    r"\bcall 911\b",
    r"\bdial 911\b",
    r"\bcall emergency services\b",
    r"\bgo to the (?:er|emergency room|hospital)(?: immediately)?\b",
    r"\bseek medical attention immediately\b",
    r"\bmust seek medical attention\b",
    r"\bsee a doctor immediately\b",
)

CONDITIONAL_CARE_MARKERS: tuple[str, ...] = (
    "if skilled medical help is available",
    "if medical help is available",
    "if professional care is available",
    "if you can reach medical help",
    "if evacuation is possible",
)

ONLINE_CONTEXT_PATTERNS: tuple[str, ...] = (
    r"\bgoogle (?:it|this|that)\b",
    r"\bsearch online\b",
    r"\bcheck the internet\b",
    r"\blook it up online\b",
)


DEFAULT_SPLIT_RATIOS: dict[str, float] = {
    "train": 0.80,
    "validation": 0.10,
    "holdout": 0.05,
    "frozen": 0.05,
}


def detect_split(path: Path) -> str:
    for part in reversed(path.parts):
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

    errors.extend(length_lints(record, prefix))
    errors.extend(policy_lints(record, prefix))

    return errors


def _user_text(record: dict) -> str:
    return " ".join(m.get("content", "") for m in record.get("messages", []) if m.get("role") == "user")


def _assistant_text(record: dict) -> str:
    return " ".join(m.get("content", "") for m in record.get("messages", []) if m.get("role") == "assistant")


def length_lints(record: dict, prefix: str) -> list[str]:
    errors: list[str] = []
    user_text = _user_text(record)
    assistant_text = _assistant_text(record)
    if len(user_text) < MIN_USER_CHARS:
        errors.append(f"{prefix}: user text too short ({len(user_text)} < {MIN_USER_CHARS})")
    if len(user_text) > MAX_USER_CHARS:
        errors.append(f"{prefix}: user text too long ({len(user_text)} > {MAX_USER_CHARS})")
    if len(assistant_text) < MIN_ASSISTANT_CHARS:
        errors.append(f"{prefix}: assistant text too short ({len(assistant_text)} < {MIN_ASSISTANT_CHARS})")
    if len(assistant_text) > MAX_ASSISTANT_CHARS:
        errors.append(f"{prefix}: assistant text too long ({len(assistant_text)} > {MAX_ASSISTANT_CHARS})")
    return errors


def policy_lints(record: dict, prefix: str) -> list[str]:
    errors: list[str] = []
    assistant_text = _assistant_text(record)
    if not assistant_text:
        return errors
    negative = bool(record.get("negative_example"))
    lowered = assistant_text.lower()

    for pattern in ONLINE_CONTEXT_PATTERNS:
        if re.search(pattern, lowered):
            errors.append(f"{prefix}: assistant references online resources (offline-first violation)")
            break

    if negative:
        return errors

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", lowered) if s.strip()]
    for sentence in sentences:
        if any(re.search(pattern, sentence) for pattern in UNCONDITIONAL_REFERRAL_PATTERNS):
            if not any(marker in sentence for marker in CONDITIONAL_CARE_MARKERS):
                errors.append(f"{prefix}: assistant uses unconditional medical referral without conditional framing")
                break

    return errors


def content_fingerprint(record: dict) -> str:
    user = _user_text(record).strip().lower()
    assistant = _assistant_text(record).strip().lower()
    user = re.sub(r"\s+", " ", user)
    assistant = re.sub(r"\s+", " ", assistant)
    digest = hashlib.sha256()
    digest.update(user.encode("utf-8"))
    digest.update(b"\0")
    digest.update(assistant.encode("utf-8"))
    return digest.hexdigest()


def detect_duplicates(records: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    id_seen: dict[str, str] = {}
    for record in records:
        record_id = record.get("id")
        if isinstance(record_id, str):
            if record_id in id_seen:
                errors.append(f"{record.get('_path','?')}: duplicate id '{record_id}' (first at {id_seen[record_id]})")
            else:
                id_seen[record_id] = record.get("_path", "?")
        fingerprint = content_fingerprint(record)
        if fingerprint in seen:
            errors.append(f"{record.get('_path','?')}: duplicate content with {seen[fingerprint]}")
        else:
            seen[fingerprint] = record.get("_path", "?")
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

    errors.extend(detect_duplicates(records))
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


def split_bucket(record_id: str, ratios: dict[str, float]) -> str:
    digest = hashlib.sha256(record_id.encode("utf-8")).hexdigest()
    fraction = int(digest[:16], 16) / float(1 << 64)
    cumulative = 0.0
    last = "train"
    for name in sorted(ratios):
        last = name
    for name in ("train", "validation", "holdout", "frozen"):
        if name not in ratios:
            continue
        cumulative += ratios[name]
        if fraction < cumulative:
            return name
    return last


def assign_splits(records: list[dict], ratios: dict[str, float] | None = None) -> dict[str, list[dict]]:
    if ratios is None:
        ratios = DEFAULT_SPLIT_RATIOS
    total = sum(ratios.values())
    if total <= 0:
        raise ValueError("split ratios must sum to a positive value")
    normalized = {name: value / total for name, value in ratios.items()}
    buckets: dict[str, list[dict]] = {name: [] for name in normalized}
    for record in records:
        record_id = record.get("id") or ""
        bucket = split_bucket(record_id, normalized)
        buckets.setdefault(bucket, []).append(record)
    for name in buckets:
        buckets[name].sort(key=lambda r: r.get("id", ""))
    return buckets


def write_splits(buckets: dict[str, list[dict]], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, records in buckets.items():
        path = out_dir / f"{name}.jsonl"
        with path.open("w") as fh:
            for record in records:
                clean = {k: v for k, v in record.items() if not k.startswith("_")}
                fh.write(json.dumps(clean, sort_keys=True))
                fh.write("\n")
        counts[name] = len(records)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Elfin fine-tuning dataset")
    parser.add_argument("--dataset-dir", default="./datasets/training", help="Directory containing JSONL dataset files")
    parser.add_argument(
        "--out",
        default="./data/training/dataset-summary.json",
        help="Where to write the summary JSON",
    )
    parser.add_argument(
        "--splits-out",
        default=None,
        help="Optional output dir for deterministic split JSONL files",
    )
    args = parser.parse_args(argv)

    dataset_dir = Path(args.dataset_dir)
    records, errors = load_records(dataset_dir)
    if errors:
        for error in errors:
            print(error)
        return 1

    summary = build_summary(records)
    if args.splits_out:
        buckets = assign_splits(records)
        summary["split_output_counts"] = write_splits(buckets, Path(args.splits_out))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"validated {summary['record_count']} training record(s)")
    print(f"wrote summary: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
