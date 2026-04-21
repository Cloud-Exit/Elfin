"""
Multimodal vision test for Elfin.

Sends a local image to llama-server (with mmproj) and displays the AI's analysis.
Validates Slice 5: multimodal image analysis works end-to-end.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_THINKING_BUDGET_TOKENS = 0
REASONING_MARKERS = (
    "i cannot",
    "i'm unable",
    "i can't",
    "unfortunately",
    "sorry, but",
    "text only",
    "text-based",
    "no image",
    "cannot view",
    "cannot analyze",
    "cannot inspect",
    "do not support",
    "doesn't support",
    "does not support",
    "not supported",
    "unsupported",
    "only accept text",
    "only accept",
)

VISUAL_DETAIL_PATTERNS = [
    r"\b(?:red|blue|green|brown|black|white|yellow|gray|grey|orange|purple|pink)\b",
    r"\b(?:tall|short|wide|narrow|long|round|square|triangular|flat|steep|smooth|rough)\b",
    r"\b(?:tree|person|building|rock|water|field|mountain|river|road|path)\b",
    r"\b(?:wearing|holding|standing|sitting|walking|running|falling)\b",
    r"\b(?:metal|wood|plastic|stone|cloth|fabric|glass)\b",
    r"\b(?:shadow|sunlight|dark|bright|cloud|rain|snow|wind)\b",
]


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = f"HTTP {exc.code}: {exc.reason}"
        try:
            error_body = exc.read().decode(errors="ignore").strip()
        except Exception:
            error_body = ""
        if error_body:
            detail += f" body={error_body[:500]}"
        raise RuntimeError(detail) from exc
    return json.loads(body) if body else {}


def base64_image(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext in (".png",):
        mime = "image/png"
    elif ext in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif ext in (".webp",):
        mime = "image/webp"
    elif ext in (".bmp",):
        mime = "image/bmp"
    else:
        mime = "image/png"
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return encoded, mime


def check_services(llama_url: str) -> list[str]:
    errors: list[str] = []
    try:
        with urllib.request.urlopen(llama_url.rstrip("/") + "/health", timeout=5) as response:
            status = response.status
            if status != 200:
                errors.append(f"llama-server health returned {status}")
    except urllib.error.URLError as exc:
        errors.append(f"llama-server unreachable: {exc}")
    return errors


def _strip_reasoning_block(text: str, label: str) -> str:
    pattern = rf"(?is)^\s*{re.escape(label)}\s*:\s*"
    match = re.match(pattern, text)
    if not match:
        return text
    rest = text[match.end():]
    lines = rest.split("\n")
    drop = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            drop += 1
            continue
        if re.match(r"^\d+[.)]", stripped):
            drop += 1
            continue
        if re.match(r"^[-*•]\s", stripped):
            drop += 1
            continue
        if stripped[0].islower():
            drop += 1
            continue
        break
    return "\n".join(lines[drop:]).strip()


def extract_visible_answer(text: str) -> str:
    cleaned = text.strip()
    if "<channel|>" in cleaned:
        cleaned = cleaned.split("<channel|>")[-1].strip()
    cleaned = re.sub(r"(?is)^.*?</think>", "", cleaned).strip()
    cleaned = _strip_reasoning_block(cleaned, "thinking process")
    cleaned = _strip_reasoning_block(cleaned, "plan")
    if cleaned.startswith("The user is asking") and "<channel|>" not in text:
        paragraphs = [part.strip() for part in cleaned.splitlines() if part.strip()]
        for paragraph in paragraphs:
            if paragraph[:1].isupper() and not paragraph.lower().startswith(("the user is asking", "plan:", "i must ensure", "i need to", "1.", "2.", "3.", "4.", "5.")):
                return paragraph
    return cleaned


def is_usable_answer(answer: str) -> bool:
    stripped = answer.strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    if any(marker in lowered for marker in REASONING_MARKERS):
        return False
    if stripped[-1] not in ".!?)]}\"'":
        tail = re.split(r"[.!?]", stripped)[-1]
        tail_words = tail.split()
        if not tail_words:
            return True
        if len(tail_words) <= 8:
            if re.search(r"\b(and|or|because|which|that|who|whose|where|when|his|her|their|its)\b$", tail.lower()):
                return True
        return False
    if not is_image_specific_enough(stripped):
        return False
    return True


def is_image_specific_enough(text: str) -> bool:
    """Require concrete visual detail as proof the model conditioned on the image."""
    for pattern in VISUAL_DETAIL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def analyze_image(
    llama_url: str,
    model: str,
    image_path: str,
    prompt: str,
    max_tokens: int,
    timeout: int,
) -> tuple[str, str | None, list[str]]:
    image_file = Path(image_path)
    if not image_file.is_file():
        return "", None, [f"image not found: {image_file}"]

    encoded, mime = base64_image(image_file)
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": f"data:{mime};base64,{encoded}",
        },
    ]

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Elfin, an offline survival assistant. "
                    "Analyze the provided image and describe what you see. "
                    "If it contains items relevant to survival (tools, plants, terrain, hazards), note them. "
                    "If it is a person with visible injuries or health concerns, describe what you observe. "
                    "Be direct and practical. Do not fabricate details not visible in the image."
                ),
            },
            {"role": "user", "content": content},
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "thinking_budget_tokens": DEFAULT_THINKING_BUDGET_TOKENS,
    }

    try:
        response = http_json(
            "POST",
            llama_url.rstrip("/") + "/v1/chat/completions",
            payload,
            timeout=timeout,
        )
    except Exception as exc:
        return "", None, [f"chat completion failed: {exc}"]

    choices = response.get("choices") or []
    if not choices:
        return "", None, ["chat completion returned no choices"]

    choice = choices[0] or {}
    finish_reason = choice.get("finish_reason")
    message = choice.get("message") or {}
    raw_content = (message.get("content") or "").strip()
    content_text = extract_visible_answer(raw_content)

    if finish_reason == "length":
        return "", finish_reason, ["model hit max_tokens limit (truncated)"]

    if not content_text:
        return "", finish_reason, ["model returned empty response"]

    return content_text, finish_reason, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Multimodal vision test for Elfin")
    parser.add_argument("--image", required=True, help="Path to the image file to analyze")
    parser.add_argument("--prompt", default="Describe what you see in this image. If relevant to survival or health, note that too.", help="Prompt to send alongside the image")
    parser.add_argument("--llama-url", default="http://localhost:8081", help="llama-server base URL")
    parser.add_argument("--model", default="gemma-4-E4B-it-Q5_K_M", help="Model name passed to llama-server")
    parser.add_argument("--max-tokens", type=int, default=512, help="Max tokens for response")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds to wait for response")
    args = parser.parse_args()

    service_errors = check_services(args.llama_url)
    if service_errors:
        for err in service_errors:
            print(f"[error] {err}", file=sys.stderr)
        return 1

    result, finish_reason, errors = analyze_image(
        llama_url=args.llama_url,
        model=args.model,
        image_path=args.image,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )

    for err in errors:
        print(f"[error] {err}", file=sys.stderr)
        return 1

    if not is_usable_answer(result):
        print(f"[error] response did not pass quality gate (finish_reason={finish_reason!r})", file=sys.stderr)
        print(f"[output] {result}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
