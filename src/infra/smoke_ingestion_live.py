"""
Run a live smoke test for the ingestion pipeline against local services.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


RAW_DOC_REQUIRED_SUFFIXES = {".pdf", ".md", ".txt"}


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 30) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}


def http_ok(url: str, timeout: int = 10) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return True, str(response.status)
    except urllib.error.URLError as exc:
        return False, str(exc)


def require_raw_docs(raw_dir: Path) -> tuple[list[str], list[str]]:
    docs = [
        path for path in raw_dir.iterdir()
        if path.is_file() and path.suffix.lower() in RAW_DOC_REQUIRED_SUFFIXES and path.name != ".gitkeep"
    ]
    if not docs:
        return [f"no raw ingestion docs found in {raw_dir}"], []
    return [], [f"raw docs present: {len(docs)}"]


def probe_embed(embed_url: str) -> tuple[list[str], list[str]]:
    health_ok, msg = http_ok(embed_url.rstrip("/") + "/health")
    if not health_ok:
        return [f"llama-embed health failed: {msg}"], []

    try:
        payload = {
            "input": "water purification",
            "model": "nomic-embed-text",
        }
        response = http_json("POST", embed_url.rstrip("/") + "/v1/embeddings", payload, timeout=60)
        vector = response["data"][0]["embedding"]
    except Exception as exc:
        return [f"embedding smoke failed: {exc}"], [f"llama-embed healthy: {msg}"]

    return [], [f"llama-embed healthy: {msg}", f"embedding smoke ok: dim={len(vector)}"]


def probe_qdrant(qdrant_url: str) -> tuple[list[str], list[str]]:
    health_ok, msg = http_ok(qdrant_url.rstrip("/") + "/healthz")
    if not health_ok:
        return [f"Qdrant health failed: {msg}"], []
    return [], [f"Qdrant healthy: {msg}"]


def run_pipeline(py: str, report_out: str, source_dir: str, qdrant_url: str, embed_url: str) -> tuple[list[str], list[str]]:
    cmd = [
        py,
        "src/ingestion/pipeline.py",
        "--source-dir", source_dir,
        "--qdrant-url", qdrant_url,
        "--embed-url", embed_url,
        "--verify-queryable",
        "--report-out", report_out,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        return [f"ingestion pipeline failed: {detail}"], []

    report_path = Path(report_out)
    if not report_path.is_file():
        return [f"ingestion report missing: {report_path}"], []

    payload = json.loads(report_path.read_text())
    queryable = payload.get("queryable")
    if not queryable or not queryable.get("ok", False):
        return [f"collection not queryable: {queryable}"], []

    indexed = payload.get("indexed_documents", [])
    plan = payload.get("plan", [])
    return [], [
        f"ingestion report ok: {report_path}",
        f"planned docs: {len(plan)}",
        f"indexed docs this run: {len(indexed)}",
        f"queryable count: {queryable.get('count')}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test live ingestion pipeline")
    parser.add_argument("--python", default=sys.executable or "python3", help="Python interpreter for pipeline run")
    parser.add_argument("--source-dir", default="./data/datasets/raw", help="Directory containing raw docs")
    parser.add_argument("--embed-url", default="http://localhost:8082", help="llama-embed base URL")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant base URL")
    parser.add_argument("--report-out", default="./data/ingestion/live-smoke-report.json", help="Report path")
    args = parser.parse_args()

    errors: list[str] = []
    notes: list[str] = []

    raw_errors, raw_notes = require_raw_docs(Path(args.source_dir))
    errors.extend(raw_errors)
    notes.extend(raw_notes)

    embed_errors, embed_notes = probe_embed(args.embed_url)
    errors.extend(embed_errors)
    notes.extend(embed_notes)

    qdrant_errors, qdrant_notes = probe_qdrant(args.qdrant_url)
    errors.extend(qdrant_errors)
    notes.extend(qdrant_notes)

    if not errors:
        run_errors, run_notes = run_pipeline(
            py=args.python,
            report_out=args.report_out,
            source_dir=args.source_dir,
            qdrant_url=args.qdrant_url,
            embed_url=args.embed_url,
        )
        errors.extend(run_errors)
        notes.extend(run_notes)

    print("Live ingestion smoke")
    for note in notes:
        print(f"[ok] {note}")
    for error in errors:
        print(f"[error] {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
