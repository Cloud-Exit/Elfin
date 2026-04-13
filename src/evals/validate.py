"""
Validate Elfin eval scenario files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_KEYS = {
    "id": str,
    "category": str,
    "mode": str,
    "user_input": str,
    "expected_behaviors": list,
}


def validate_scenario(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid json: {exc}"]

    for key, expected_type in REQUIRED_KEYS.items():
        if key not in payload:
            errors.append(f"{path}: missing key '{key}'")
            continue
        if not isinstance(payload[key], expected_type):
            errors.append(f"{path}: key '{key}' must be {expected_type.__name__}")

    mode = payload.get("mode")
    if mode not in {"general", "reference", "multimodal", "personal-context"}:
        errors.append(f"{path}: unsupported mode '{mode}'")

    must_include = payload.get("must_include", [])
    must_not_include = payload.get("must_not_include", [])
    if must_include and not isinstance(must_include, list):
        errors.append(f"{path}: key 'must_include' must be list")
    if must_not_include and not isinstance(must_not_include, list):
        errors.append(f"{path}: key 'must_not_include' must be list")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Elfin eval scenario files")
    parser.add_argument(
        "--scenario-dir",
        default="./src/evals/scenarios",
        help="Directory containing eval scenario json files",
    )
    args = parser.parse_args()

    scenario_dir = Path(args.scenario_dir)
    files = sorted(scenario_dir.rglob("*.json"))
    if not files:
        print(f"no scenario files found in {scenario_dir}")
        return 1

    errors: list[str] = []
    for path in files:
        errors.extend(validate_scenario(path))

    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"validated {len(files)} scenario file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
