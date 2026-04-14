"""
Slice 1 verification for Elfin.

Checks static compose/config requirements for PRD Slice 1, required local
assets, and optionally probes runtime service endpoints if the stack is
already running.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_MODEL_FILES = [
    "gemma-4-E4B-it-Q5_K_M.gguf",
    "mmproj-F16.gguf",
    "nomic-embed-text-v1.5.Q8_0.gguf",
]

REQUIRED_COMPOSE_SNIPPETS = [
    "llama-server:",
    "llama-embed:",
    "qdrant:",
    "kiwix:",
    "ghcr.io/ggml-org/llama.cpp:server@sha256:",
    "qdrant/qdrant:latest@sha256:",
    "ghcr.io/kiwix/kiwix-serve:latest@sha256:",
    "gemma-4-E4B-it-Q5_K_M.gguf",
    "mmproj-F16.gguf",
    "nomic-embed-text-v1.5.Q8_0.gguf",
    "QDRANT__STORAGE__ON_DISK_PAYLOAD=true",
    '\"8081:8081\"',
    '\"8082:8082\"',
    '\"6333:6333\"',
    '\"8083:80\"',
]


def check_compose_file(compose_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    if not compose_path.is_file():
        return [f"missing compose file: {compose_path}"], notes

    text = compose_path.read_text()
    for snippet in REQUIRED_COMPOSE_SNIPPETS:
        if snippet in text:
            notes.append(f"compose contains: {snippet}")
        else:
            errors.append(f"compose missing: {snippet}")

    return errors, notes


def check_required_files(models_dir: Path, zim_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    for filename in REQUIRED_MODEL_FILES:
        path = models_dir / filename
        if path.is_file():
            notes.append(f"model present: {filename}")
        else:
            errors.append(f"missing model: {path}")

    zim_files = [p for p in zim_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]
    if zim_files:
        notes.append(f"zim present: {len(zim_files)} file(s)")
    else:
        errors.append(f"missing zim archives in: {zim_dir}")

    return errors, notes


def probe(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return True, f"{url} -> {response.status}"
    except urllib.error.URLError as exc:
        return False, f"{url} -> {exc}"


def check_endpoints() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    checks = [
        ("llama-server", "http://localhost:8081/health"),
        ("llama-embed", "http://localhost:8082/health"),
        ("qdrant", "http://localhost:6333/healthz"),
        ("kiwix", "http://localhost:8083/catalog/v2/root.xml"),
    ]

    for name, url in checks:
        ok, msg = probe(url)
        if ok:
            notes.append(f"{name} healthy: {msg}")
        else:
            errors.append(f"{name} probe failed: {msg}")

    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Elfin PRD Slice 1 prerequisites")
    parser.add_argument("--compose-file", default="./docker-compose.yml", help="Compose file to validate")
    parser.add_argument("--models-dir", default="./data/models", help="Directory containing GGUF files")
    parser.add_argument("--zim-dir", default="./data/datasets/zim", help="Directory containing ZIM files")
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="Only check static compose/config requirements",
    )
    parser.add_argument(
        "--assets-only",
        action="store_true",
        help="Only check local model/ZIM assets",
    )
    parser.add_argument(
        "--check-endpoints",
        action="store_true",
        help="Probe local service endpoints in addition to checking required files",
    )
    args = parser.parse_args()

    compose_path = Path(args.compose_file)
    models_dir = Path(args.models_dir)
    zim_dir = Path(args.zim_dir)

    errors: list[str] = []
    notes: list[str] = []

    if not args.assets_only:
        compose_errors, compose_notes = check_compose_file(compose_path)
        errors.extend(compose_errors)
        notes.extend(compose_notes)

    if not args.config_only:
        asset_errors, asset_notes = check_required_files(models_dir, zim_dir)
        errors.extend(asset_errors)
        notes.extend(asset_notes)

    if args.check_endpoints:
        endpoint_errors, endpoint_notes = check_endpoints()
        errors.extend(endpoint_errors)
        notes.extend(endpoint_notes)

    print("Slice 1 verification")
    for note in notes:
        print(f"[ok] {note}")
    for err in errors:
        print(f"[error] {err}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
