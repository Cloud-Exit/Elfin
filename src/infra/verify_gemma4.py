"""
Verify local Gemma 4 standalone runtime.
"""

from __future__ import annotations

import argparse
import atexit
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_MODEL_FILES = [
    "gemma-4-E4B-it-Q5_K_M.gguf",
    "mmproj-F16.gguf",
]


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


def check_files(models_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    for filename in REQUIRED_MODEL_FILES:
        path = models_dir / filename
        if path.is_file():
            notes.append(f"model present: {filename}")
        else:
            errors.append(f"missing model: {path}")
    return errors, notes


def check_health(base_url: str) -> tuple[list[str], list[str]]:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=5) as response:
            status = response.status
    except urllib.error.URLError as exc:
        return [f"llama-server health failed: {exc}"], []
    return [], [f"llama-server healthy: {status}"]


def wait_for_health(base_url: str, timeout_secs: int) -> tuple[bool, str]:
    last_error = "unknown error"
    for _ in range(timeout_secs):
        errors, _ = check_health(base_url)
        if not errors:
            return True, ""
        last_error = errors[0]
        time.sleep(1)
    return False, last_error


def stop_process(process: subprocess.Popen[bytes] | subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start_llama_server(
    llama_server_bin: str,
    models_dir: Path,
    model_file: str,
    mmproj_file: str,
    host: str,
    port: int,
    ctx_size: int,
    startup_timeout: int,
    log_file: Path,
) -> tuple[subprocess.Popen[str] | None, list[str], list[str]]:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file.open("w")

    command = [
        llama_server_bin,
        "-m",
        str(models_dir / model_file),
        "--mmproj",
        str(models_dir / mmproj_file),
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        str(ctx_size),
        "-ngl",
        "0",
    ]

    try:
        process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError:
        log_handle.close()
        return None, [f"llama-server binary not found: {llama_server_bin}"], []

    def cleanup() -> None:
        stop_process(process)
        log_handle.close()

    atexit.register(cleanup)

    ok, error = wait_for_health(f"http://{host}:{port}", startup_timeout)
    if not ok:
        stop_process(process)
        log_handle.close()
        return None, [f"failed to start llama-server: {error}", f"see log: {log_file}"], []

    return process, [], [f"started local llama-server: {' '.join(command)}", f"log file: {log_file}"]


def smoke_chat(base_url: str, model: str) -> tuple[list[str], list[str]]:
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Answer briefly."},
                {"role": "user", "content": "Reply with exactly: ok"},
            ],
            "stream": False,
            "max_tokens": 8,
        }
        response = http_json("POST", base_url.rstrip("/") + "/v1/chat/completions", payload, timeout=60)
        text = response["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return [f"chat completion failed: {exc}"], []

    if "ok" not in text.lower():
        return [f"unexpected chat response: {text!r}"], []
    return [], [f"chat completion ok: {text!r}"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local Gemma 4 runtime")
    parser.add_argument("--models-dir", default="./data/models", help="Directory containing Gemma model files")
    parser.add_argument("--llama-url", default="http://localhost:8081", help="llama-server base URL")
    parser.add_argument("--llama-server-bin", default="llama-server", help="llama-server executable name/path")
    parser.add_argument("--model", default="gemma-4-E4B-it-Q5_K_M", help="Model name passed to llama-server")
    parser.add_argument("--model-file", default="gemma-4-E4B-it-Q5_K_M.gguf", help="Gemma GGUF filename")
    parser.add_argument("--mmproj-file", default="mmproj-F16.gguf", help="Gemma mmproj GGUF filename")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind when auto-starting llama-server")
    parser.add_argument("--port", type=int, default=8081, help="Port to bind when auto-starting llama-server")
    parser.add_argument("--ctx-size", type=int, default=8192, help="Context size for local llama-server")
    parser.add_argument("--startup-timeout", type=int, default=60, help="Seconds to wait for local llama-server startup")
    parser.add_argument("--log-file", default="./data/logs/llama-server-gemma4.log", help="Log path when auto-starting llama-server")
    parser.add_argument("--no-launch", action="store_true", help="Only probe an already-running llama-server")
    parser.add_argument("--chat", action="store_true", help="Run chat smoke test in addition to health check")
    args = parser.parse_args()

    errors: list[str] = []
    notes: list[str] = []
    started_process: subprocess.Popen[str] | None = None

    models_dir = Path(args.models_dir)
    file_errors, file_notes = check_files(models_dir)
    errors.extend(file_errors)
    notes.extend(file_notes)

    if not errors:
        health_errors, health_notes = check_health(args.llama_url)
        if health_errors and not args.no_launch:
            started_process, start_errors, start_notes = start_llama_server(
                llama_server_bin=args.llama_server_bin,
                models_dir=models_dir,
                model_file=args.model_file,
                mmproj_file=args.mmproj_file,
                host=args.host,
                port=args.port,
                ctx_size=args.ctx_size,
                startup_timeout=args.startup_timeout,
                log_file=Path(args.log_file),
            )
            errors.extend(start_errors)
            notes.extend(start_notes)
            if not start_errors:
                args.llama_url = f"http://{args.host}:{args.port}"
                health_errors, health_notes = check_health(args.llama_url)

        errors.extend(health_errors)
        notes.extend(health_notes)

    if args.chat and not errors:
        chat_errors, chat_notes = smoke_chat(args.llama_url, args.model)
        errors.extend(chat_errors)
        notes.extend(chat_notes)

    print("Gemma 4 verification")
    for note in notes:
        print(f"[ok] {note}")
    for error in errors:
        print(f"[error] {error}")
    stop_process(started_process)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
