"""
Run Elfin evaluation scenarios against an OpenAI-compatible chat endpoint.

Initial scope:
- general-mode text scenarios
- deterministic substring checks for smoke testing
- JSON report output for later comparison
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Scenario:
    id: str
    category: str
    mode: str
    user_input: str
    expected_behaviors: list[str]
    must_include: list[str]
    must_not_include: list[str]


def load_scenarios(scenario_dir: Path, limit: int | None) -> list[Scenario]:
    scenarios: list[Scenario] = []
    files = sorted(scenario_dir.rglob("*.json"))
    for path in files[: limit or None]:
        payload = json.loads(path.read_text())
        scenarios.append(
            Scenario(
                id=payload["id"],
                category=payload["category"],
                mode=payload["mode"],
                user_input=payload["user_input"],
                expected_behaviors=payload["expected_behaviors"],
                must_include=payload.get("must_include", []),
                must_not_include=payload.get("must_not_include", []),
            )
        )
    return scenarios


def call_chat(llama_url: str, model: str, user_input: str, system_prompt: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "stream": False,
        }
    ).encode()

    request = urllib.request.Request(
        llama_url.rstrip("/") + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    return payload["choices"][0]["message"]["content"]


def score_response(text: str, scenario: Scenario) -> dict:
    lowered = text.lower()
    missing = [needle for needle in scenario.must_include if needle.lower() not in lowered]
    forbidden = [needle for needle in scenario.must_not_include if needle.lower() in lowered]
    passed = not missing and not forbidden
    return {
        "passed": passed,
        "missing": missing,
        "forbidden": forbidden,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Elfin eval scenarios")
    parser.add_argument("--scenario-dir", default="./src/evals/scenarios", help="Directory containing eval scenarios")
    parser.add_argument("--llama-url", default="http://localhost:8081", help="OpenAI-compatible chat endpoint base URL")
    parser.add_argument("--model", default="gemma-4-E4B-it-Q5_K_M", help="Model name passed to chat endpoint")
    parser.add_argument("--out", default="./data/evals/latest-report.json", help="Path for JSON report")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of scenarios")
    parser.add_argument("--dry-run", action="store_true", help="Validate load path only, do not call model")
    args = parser.parse_args()

    scenarios = load_scenarios(Path(args.scenario_dir), args.limit)
    if not scenarios:
        print("no scenarios loaded")
        return 1

    results = []
    system_prompt = (
        "You are Elfin, survival assistant. Be practical, cautious, and concise. "
        "If critical information is missing, ask follow-up questions before giving risky advice. "
        "Do not bluff certainty."
    )

    for scenario in scenarios:
        if scenario.mode != "general":
            results.append(
                {
                    "id": scenario.id,
                    "category": scenario.category,
                    "mode": scenario.mode,
                    "status": "skipped",
                    "reason": "mode not yet implemented in smoke harness",
                }
            )
            continue

        if args.dry_run:
            results.append(
                {
                    "id": scenario.id,
                    "category": scenario.category,
                    "mode": scenario.mode,
                    "status": "loaded",
                }
            )
            continue

        response_text = call_chat(args.llama_url, args.model, scenario.user_input, system_prompt)
        score = score_response(response_text, scenario)
        results.append(
            {
                "id": scenario.id,
                "category": scenario.category,
                "mode": scenario.mode,
                "status": "completed",
                "response": response_text,
                "score": score,
                "expected_behaviors": scenario.expected_behaviors,
            }
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"results": results}, indent=2))
    print(f"wrote report: {out_path}")

    failures = [
        result for result in results
        if result.get("status") == "completed" and not result.get("score", {}).get("passed", False)
    ]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
