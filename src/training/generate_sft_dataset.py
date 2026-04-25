"""
Synthesize Elfin SFT training examples from a local passage manifest.

Calls an OpenRouter chat-completions endpoint to produce per-passage training
records of several behavior kinds (positive, follow-up, refuse-certainty,
defer-to-reference, escalate-risk). Each record carries provenance back to the
local source chunk so the generated corpus is auditable.

Design:
- network client is a single function that can be replaced in tests
- API key read from OPENROUTER_API_KEY env var; missing key fails loudly
- generation is reproducible: ordering is deterministic by (passage_id, kind)
- no S3, no remote shell, no cloud side effects
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"

EXAMPLE_KINDS: tuple[str, ...] = (
    "positive",
    "follow-up",
    "refuse-certainty",
    "defer-to-reference",
    "escalate-risk",
)


KIND_INSTRUCTIONS: dict[str, str] = {
    "positive": (
        "Write a single training example where the user asks a practical survival question "
        "grounded in the passage and the assistant gives a direct, field-appropriate answer "
        "with concrete steps, without overclaiming and without unconditional medical referral."
    ),
    "follow-up": (
        "Write a training example where the assistant must ask one or more critical follow-up "
        "questions before giving advice, because the user input is incomplete for a safe "
        "recommendation."
    ),
    "refuse-certainty": (
        "Write a training example where the assistant should acknowledge uncertainty and avoid "
        "claiming a definitive diagnosis or outcome. The assistant should still give practical "
        "monitoring/stabilization steps."
    ),
    "defer-to-reference": (
        "Write a training example where the assistant answers from the passage and defers to "
        "the cited source for details beyond what the passage supports."
    ),
    "escalate-risk": (
        "Write a training example where the assistant must flag a danger sign or urgent risk "
        "using conditional framing for professional care (e.g. 'if skilled medical help is "
        "available') rather than unconditional referral."
    ),
}


SYSTEM_PROMPT = (
    "You generate supervised fine-tuning data for Elfin, an offline survival assistant. "
    "Assume skilled medical help may be unreachable. Output strict JSON only, no prose. "
    "The assistant text must be plainspoken, practical, and concise. "
    "Avoid unconditional directives like 'call 911' or 'seek medical attention immediately' as the main answer; "
    "if professional care is mentioned, phrase it conditionally."
)


@dataclass
class GeneratedExample:
    record: dict
    kind: str
    passage_id: str


ClientFn = Callable[[list[dict], dict], dict]


def http_openrouter(messages: list[dict], options: dict) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required; not found in environment")
    body = json.dumps(
        {
            "model": options.get("model", DEFAULT_MODEL),
            "messages": messages,
            "temperature": options.get("temperature", 0.2),
            "max_tokens": options.get("max_tokens", 800),
            "response_format": {"type": "json_object"},
        }
    ).encode()
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cloud-exit.com/elfin",
            "X-Title": "Elfin Fine-Tune Pipeline",
        },
        method="POST",
    )
    timeout = int(options.get("timeout", 60))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode()
    return json.loads(raw)


def load_manifest(path: Path) -> list[dict]:
    records: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def build_user_prompt(passage: dict, kind: str) -> str:
    citation = f"[{passage['source_file']}#chunk_{passage['chunk_index']}]"
    return (
        f"Passage:\n{passage['text']}\n\n"
        f"Source citation: {citation}\n"
        f"Example kind: {kind}\n"
        f"Instruction: {KIND_INSTRUCTIONS[kind]}\n\n"
        "Respond with a JSON object of the form:\n"
        '{"user": "...", "assistant": "..."}'
    )


def _parse_completion_text(response: dict) -> dict:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("openrouter response has no choices")
    content = (choices[0].get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("openrouter response has no content")
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError(f"openrouter content is not JSON object: {content[:120]}")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict) or "user" not in parsed or "assistant" not in parsed:
        raise ValueError("openrouter JSON missing user/assistant keys")
    return parsed


def format_record(passage: dict, kind: str, user_text: str, assistant_text: str, model: str) -> dict:
    return {
        "id": f"{passage['id']}::{kind}",
        "category": passage.get("topic", "general"),
        "tags": sorted({kind, passage.get("topic", "general")}),
        "negative_example": kind in {"follow-up", "refuse-certainty", "escalate-risk"},
        "source": "openrouter-synthetic",
        "language": "en",
        "modality": "text",
        "provenance": {
            "passage_id": passage["id"],
            "source_file": passage["source_file"],
            "chunk_index": passage["chunk_index"],
            "kind": kind,
            "model": model,
        },
        "messages": [
            {
                "role": "system",
                "content": "You are Elfin, an offline survival assistant. Be practical, cautious, concise.",
            },
            {"role": "user", "content": user_text.strip()},
            {"role": "assistant", "content": assistant_text.strip()},
        ],
    }


def generate_for_passage(
    passage: dict,
    kinds: Iterable[str],
    client: ClientFn,
    model: str,
    temperature: float,
    max_tokens: int,
) -> list[GeneratedExample]:
    examples: list[GeneratedExample] = []
    for kind in kinds:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(passage, kind)},
        ]
        options = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
        response = client(messages, options)
        parsed = _parse_completion_text(response)
        record = format_record(passage, kind, parsed["user"], parsed["assistant"], model)
        examples.append(GeneratedExample(record=record, kind=kind, passage_id=passage["id"]))
    return examples


def pick_passages(
    manifest: list[dict],
    max_per_topic: int,
    rng: random.Random,
) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for passage in manifest:
        grouped.setdefault(passage["topic"], []).append(passage)
    selected: list[dict] = []
    for topic in sorted(grouped):
        bucket = sorted(grouped[topic], key=lambda r: r["id"])
        if len(bucket) > max_per_topic:
            rng.shuffle(bucket)
            bucket = bucket[:max_per_topic]
            bucket.sort(key=lambda r: r["id"])
        selected.extend(bucket)
    return selected


def run_generation(
    manifest_path: Path,
    out_path: Path,
    *,
    kinds: Iterable[str] = EXAMPLE_KINDS,
    max_per_topic: int = 5,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 800,
    seed: int = 7,
    client: ClientFn = http_openrouter,
    throttle_seconds: float = 0.0,
) -> dict:
    manifest = load_manifest(manifest_path)
    if not manifest:
        raise RuntimeError(f"empty manifest: {manifest_path}")
    rng = random.Random(seed)
    passages = pick_passages(manifest, max_per_topic=max_per_topic, rng=rng)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    produced: list[GeneratedExample] = []
    errors: list[str] = []
    with out_path.open("w") as fh:
        for passage in passages:
            try:
                for example in generate_for_passage(
                    passage,
                    kinds,
                    client=client,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    fh.write(json.dumps(example.record, sort_keys=True))
                    fh.write("\n")
                    produced.append(example)
                    if throttle_seconds:
                        time.sleep(throttle_seconds)
            except Exception as exc:
                errors.append(f"{passage['id']}: {exc}")

    return {
        "record_count": len(produced),
        "passage_count": len(passages),
        "errors": errors,
        "kinds": sorted(set(ex.kind for ex in produced)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Elfin SFT dataset via OpenRouter")
    parser.add_argument("--manifest", default="./data/training/passage-manifest.jsonl")
    parser.add_argument("--out", default="./datasets/training/synthetic/openrouter.jsonl")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-per-topic", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--kinds", nargs="+", default=list(EXAMPLE_KINDS))
    parser.add_argument("--throttle-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)

    invalid_kinds = [k for k in args.kinds if k not in EXAMPLE_KINDS]
    if invalid_kinds:
        print(f"[error] unknown kinds: {invalid_kinds}", file=sys.stderr)
        return 2

    try:
        summary = run_generation(
            Path(args.manifest),
            Path(args.out),
            kinds=args.kinds,
            max_per_topic=args.max_per_topic,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            seed=args.seed,
            throttle_seconds=args.throttle_seconds,
        )
    except Exception as exc:
        print(f"[error] generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"generated {summary['record_count']} records across {summary['passage_count']} passages")
    for err in summary["errors"]:
        print(f"[warn] {err}", file=sys.stderr)
    return 0 if not summary["errors"] else (0 if summary["record_count"] > 0 else 1)


if __name__ == "__main__":
    sys.exit(main())
