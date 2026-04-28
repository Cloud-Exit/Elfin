"""
Verified trust model for Elfin.

Cross-references AI visual identification against Qdrant (survival knowledge base)
and Kiwix (offline encyclopedia) to produce verified/unverified/conflicted status
for each identified entity.

Validates Slice 7: only results confirmed by local knowledge sources are flagged
as verified.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VERIFICATION_STATUS = Literal["verified", "unverified", "conflicted", "uncertain"]

# Entities that the AI commonly identifies in survival-relevant images
ENTITY_PATTERNS: dict[str, list[str]] = {
    "plant": [
        r"\b(poison\s+ivy|poison\s+oak|poison\s+sumac)\b",
        r"\b(plantain|yarrow|mullen|plantago|achillea)\b",
        r"\b(lichen|moss|fern|cactus|sage|mint|thyme|lavender)\b",
        r"\b(wild\s+(onion|garlic|strawberry|raspberry|blackberry|blueberry))\b",
        r"\b(hemlock|nightshade|jimson\s+weed|deadly\s+(nightshade|hemo))\b",
    ],
    "animal": [
        r"\b(snake|viper|rattlesnake|copperhead|coral\s+snake|garter\s+snake)\b",
        r"\b(spider|black\s+widow|brown\s+recluse|tarantula)\b",
        r"\b(scorpion|beetle|wasp|hornet|bee|ant)\b",
        r"\b(tick|mosquito|fly|maggot|larva)\b",
        r"\b(bear|wolf|coyote|mountain\s+lion|bobcat|raccoon)\b",
    ],
    "injury": [
        r"\b(fracture|broken\s+(bone|arm|leg|finger|toe))\b",
        r"\b(dislocation|sprain|strain|twist)\b",
        r"\b(burn|scald|blister|sunburn)\b",
        r"\b(cut|laceration|gash|puncture|abrasion)\b",
        r"\b(wound|bleeding|hemorrhage|bruise|contusion)\b",
        r"\b(infection|pus|abscess|cellulitis)\b",
        r"\b(rash|hives|swelling|inflammation)\b",
        r"\b(bite|sting|venom|toxin|poison)\b",
    ],
    "hazard": [
        r"\b(flood|flash\s+flood|landslide|mudslide)\b",
        r"\b(fire|smoke|burning|flame)\b",
        r"\b(fall|collapse|debris|unstable)\b",
        r"\b(contamination|chemical|spill|toxic|hazardous)\b",
        r"\b(hypothermia|frostbite|heat\s+exhaustion|heat\s+stroke)\b",
    ],
    "object": [
        r"\b(first\s+aid\s+kit|bandage|gauze|splint|tourniquet)\b",
        r"\b(water\s+(purif|filter|bottle|container))\b",
        r"\b(shelter|tarp|tent|blanket|sleeping\s+bag)\b",
        r"\b(knife|tool|rope|cord|paracord)\b",
    ],
}

# Thresholds for verification confidence
MIN_LEXICAL_OVERLAP_VERIFIED = 0.25
MIN_SOURCE_COUNT_VERIFIED = 1
MIN_KIWIX_CHARS = 40


@dataclass
class EntityVerification:
    """Result of verifying a single entity against knowledge sources."""
    entity: str
    category: str
    status: VERIFICATION_STATUS
    confidence: float
    qdrant_matches: int
    kiwix_matches: int
    qdrant_evidence: list[str] = field(default_factory=list)
    kiwix_evidence: list[str] = field(default_factory=list)
    ai_description: str = ""
    kb_description: str = ""


@dataclass
class VerificationResult:
    """Complete trust model verification result for a visual analysis."""
    visual_answer: str
    entities: list[EntityVerification]
    overall_status: VERIFICATION_STATUS
    verified_count: int
    unverified_count: int
    conflicted_count: int
    uncertain_count: int


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Extract survival-relevant entities from AI visual analysis text.

    Returns list of (entity_name, category) tuples. Substring matches are
    removed in favor of longer, more specific matches (e.g., "rattlesnake"
    wins over "snake").
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for category, patterns in ENTITY_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity = match.group(1) if match.lastindex else match.group(0)
                entity_key = entity.lower().strip()
                if entity_key not in seen:
                    seen.add(entity_key)
                    found.append((entity, category))

    # Remove entities that are substrings of longer, more specific matches
    result: list[tuple[str, str]] = []
    for entity, category in found:
        entity_lower = entity.lower()
        is_substring = False
        for other_entity, _ in found:
            if entity_lower != other_entity.lower() and entity_lower in other_entity.lower():
                is_substring = True
                break
        if not is_substring:
            result.append((entity, category))

    return result


def _http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    import urllib.error
    import urllib.request

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
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
    return json.loads(body) if body else {}


def embed_query(embed_url: str, text: str, model_name: str = "nomic-embed-text") -> list[float]:
    """Get embedding vector for a query text."""
    response = _http_json(
        "POST",
        embed_url.rstrip("/") + "/v1/embeddings",
        {"input": text, "model": model_name},
        timeout=60,
    )
    return response["data"][0]["embedding"]


def search_qdrant(
    qdrant_url: str,
    collection: str,
    vector: list[float],
    limit: int = 3,
) -> list[dict]:
    """Search Qdrant for semantically similar chunks."""
    response = _http_json(
        "POST",
        qdrant_url.rstrip("/") + f"/collections/{collection}/points/query",
        {
            "query": vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        },
        timeout=60,
    )
    result = response.get("result", {})
    return result.get("points", [])


def lexical_overlap(query: str, text: str) -> float:
    """Compute normalized lexical overlap between query and text."""
    query_tokens = set(re.findall(r"[A-Za-z0-9]{2,}", query.lower()))
    doc_tokens = set(re.findall(r"[A-Za-z0-9]{2,}", text.lower()))
    if not query_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def search_kiwix_for_entity(
    kiwix_url: str,
    zim_dir: str,
    entity: str,
    max_chars: int = 500,
) -> list[dict]:
    """Search Kiwix for articles about a given entity.

    Returns list of {title, text, source} dicts.
    """
    from html.parser import HTMLParser
    from urllib.parse import quote, unquote, urlparse, urljoin

    results: list[dict] = []

    zim_path = Path(zim_dir)
    if not zim_path.is_dir():
        return results

    # Discover ZIM books, prefer medical/Wikipedia
    books: list[str] = []
    for p in sorted(zim_path.glob("*.zim")):
        stem = p.stem
        normalized = re.sub(r"_\d{4}-\d{2}$", "", stem)
        if normalized.startswith("wikipedia_") or normalized.startswith("wikimed_") or "medicine" in normalized:
            books.insert(0, stem)
        else:
            books.append(stem)

    entity_lower = entity.lower()

    for book in books[:3]:  # Search top 3 books
        # Try direct suggest endpoint first
        try:
            suggest_url = f"{kiwix_url.rstrip('/')}/{book}/suggest?q={quote(entity)}&count=3&socket=1"
            response = _http_json("GET", suggest_url, timeout=10)
            suggestions = response if isinstance(response, list) else []

            for suggestion in suggestions[:2]:
                if isinstance(suggestion, dict):
                    title = suggestion.get("title", "")
                    if title and _title_matches_entity(title, entity):
                        # Fetch article content
                        article_path = suggestion.get("path", "")
                        if article_path:
                            text = _fetch_kiwix_text(kiwix_url, book, article_path, max_chars)
                            if text and len(text) >= MIN_KIWIX_CHARS:
                                overlap = lexical_overlap(entity, text)
                                results.append({
                                    "title": title,
                                    "text": text,
                                    "source": f"kiwix:{book}",
                                    "lexical_overlap": overlap,
                                })
        except Exception:
            continue

        # Fallback: search endpoint
        if not results:
            try:
                search_url = f"{kiwix_url.rstrip('/')}/search?lang=en&pattern={quote(entity)}&count=3&book={quote(book)}"
                import urllib.request as ur
                req = ur.Request(search_url)
                with ur.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode(errors="ignore")

                # Parse links from search results
                class LinkParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.links: list[dict] = []
                        self.in_a = False
                        self.href = ""
                        self.text_parts: list[str] = []

                    def handle_starttag(self, tag, attrs):
                        if tag == "a":
                            self.in_a = True
                            self.href = dict(attrs).get("href", "")
                            self.text_parts = []

                    def handle_data(self, data):
                        if self.in_a:
                            self.text_parts.append(data)

                    def handle_endtag(self, tag):
                        if tag == "a" and self.in_a:
                            title = " ".join(p.strip() for p in self.text_parts if p.strip()).strip()
                            if title and any(m in self.href for m in ("/content/", "/raw/")):
                                self.links.append({"href": self.href, "title": title})
                            self.in_a = False

                parser = LinkParser()
                parser.feed(html)

                for link in parser.links[:2]:
                    parsed = urlparse(urljoin(kiwix_url + "/", link["href"]))
                    match = re.search(r"/content/([^/]+)/(.+)$", parsed.path)
                    if match:
                        b = unquote(match.group(1))
                        path = unquote(match.group(2))
                        text = _fetch_kiwix_text(kiwix_url, b, path, max_chars)
                        if text and len(text) >= MIN_KIWIX_CHARS:
                            overlap = lexical_overlap(entity, text)
                            results.append({
                                "title": link["title"],
                                "text": text,
                                "source": f"kiwix:{b}",
                                "lexical_overlap": overlap,
                            })
            except Exception:
                continue

        if results:
            break

    return results


def _title_matches_entity(title: str, entity: str) -> bool:
    """Check if a Kiwix article title is relevant to the entity."""
    title_lower = title.lower()
    entity_words = re.findall(r"[A-Za-z]+", entity.lower())
    if not entity_words:
        return False
    # At least the first word of the entity should appear in the title
    return any(word in title_lower for word in entity_words[:2])


def _fetch_kiwix_text(kiwix_url: str, book: str, path: str, max_chars: int) -> str:
    """Fetch and extract text from a Kiwix article."""
    import urllib.error
    import urllib.request
    import html as html_mod
    from html.parser import HTMLParser

    # Try raw endpoint first, then content
    urls_to_try = [
        kiwix_url.rstrip("/") + f"/raw/{book}/content/{path}",
        kiwix_url.rstrip("/") + f"/content/{book}/{path}",
    ]

    for url in urls_to_try:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode(errors="ignore")

            # Strip HTML
            class SimpleTextExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts: list[str] = []
                    self.skip = 0

                def handle_starttag(self, tag, attrs):
                    if tag in ("script", "style", "table"):
                        self.skip += 1
                    if tag in ("p", "br", "li"):
                        self.parts.append("\n")

                def handle_endtag(self, tag):
                    if tag in ("script", "style", "table") and self.skip > 0:
                        self.skip -= 1

                def handle_data(self, data):
                    if self.skip == 0 and data.strip():
                        self.parts.append(data.strip())

            extractor = SimpleTextExtractor()
            extractor.feed(raw)
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(extractor.parts)).strip()
            text = html_mod.unescape(text)

            # Remove Wikipedia-style junk
            text = re.sub(r"\[\s*(?:citation needed|clarification needed)\s*\]", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+", " ", text)

            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "..."
            return text if len(text) >= MIN_KIWIX_CHARS else ""
        except Exception:
            continue

    return ""


def verify_entity(
    entity: str,
    category: str,
    ai_description: str,
    qdrant_points: list[dict],
    kiwix_results: list[dict],
) -> EntityVerification:
    """Verify a single entity against knowledge base sources.

    Returns EntityVerification with status and evidence.
    """
    entity_lower = entity.lower()
    combined_query = f"{entity} {ai_description}".strip()

    # Analyze Qdrant matches
    qdrant_evidence: list[str] = []
    qdrant_confirmed = False
    for point in qdrant_points:
        payload = point.get("payload", {}) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue
        overlap = lexical_overlap(combined_query, text)
        # Check if the entity name or related terms appear in the text
        entity_words = set(re.findall(r"[A-Za-z]{2,}", entity_lower))
        text_words = set(re.findall(r"[A-Za-z]{2,}", text.lower()))
        entity_in_text = bool(entity_words & text_words)

        if entity_in_text or overlap >= MIN_LEXICAL_OVERLAP_VERIFIED:
            qdrant_confirmed = True
            source_file = payload.get("source_file", "unknown")
            chunk_index = payload.get("chunk_index", "?")
            score = point.get("score", 0)
            snippet = text[:200] if len(text) > 200 else text
            qdrant_evidence.append(
                f"[{source_file}#chunk_{chunk_index} score={score:.3f} overlap={overlap:.2f}] {snippet}"
            )

    # Analyze Kiwix matches
    kiwix_evidence: list[str] = []
    kiwix_confirmed = False
    for result in kiwix_results:
        text = result.get("text", "")
        title = result.get("title", "")
        overlap = result.get("lexical_overlap", 0.0)
        if overlap > 0 or entity_lower in text.lower():
            kiwix_confirmed = True
            snippet = text[:200] if len(text) > 200 else text
            kiwix_evidence.append(
                f"[{result.get('source', 'kiwix')} '{title}' overlap={overlap:.2f}] {snippet}"
            )

    # Determine status
    qdrant_matches = len(qdrant_evidence)
    kiwix_matches = len(kiwix_evidence)
    total_matches = qdrant_matches + kiwix_matches

    # Build combined KB description from evidence
    kb_parts = []
    for ev in qdrant_evidence[:2]:
        kb_parts.append(ev.split("] ", 1)[-1] if "] " in ev else ev)
    for ev in kiwix_evidence[:2]:
        kb_parts.append(ev.split("] ", 1)[-1] if "] " in ev else ev)
    kb_description = " ".join(kb_parts) if kb_parts else ""

    if qdrant_confirmed and kiwix_confirmed:
        # Both sources confirm - strong verification
        status = "verified"
        confidence = min(1.0, 0.6 + (qdrant_matches + kiwix_matches) * 0.1)
    elif qdrant_confirmed or kiwix_confirmed:
        # One source confirms - verified with lower confidence
        status = "verified"
        confidence = min(0.8, 0.4 + total_matches * 0.1)
    elif total_matches >= 2:
        # Multiple weak matches - uncertain
        status = "uncertain"
        confidence = 0.3
    elif total_matches == 1:
        # Single weak match - uncertain
        status = "uncertain"
        confidence = 0.2
    else:
        # No matches - unverified
        status = "unverified"
        confidence = 0.0

    # Check for conflict: if KB describes the entity differently than AI's description
    if status == "verified" and ai_description and kb_description:
        ai_words = set(re.findall(r"[A-Za-z]{3,}(?:-[A-Za-z]{3,})*", ai_description.lower()))
        kb_words = set(re.findall(r"[A-Za-z]{3,}(?:-[A-Za-z]{3,})*", kb_description.lower()))
        # If AI mentions things that directly contradict KB (e.g., "safe to eat" vs "poisonous")
        contradiction_pairs = [
            ("safe", "poisonous"),
            ("safe", "toxic"),
            ("safe", "dangerous"),
            ("edible", "poisonous"),
            ("edible", "toxic"),
            ("harmless", "dangerous"),
            ("harmless", "toxic"),
            ("benign", "malignant"),
            ("non-venomous", "venomous"),
            ("harmless", "venomous"),
        ]
        for a_word, b_word in contradiction_pairs:
            if a_word in ai_words and b_word in kb_words:
                status = "conflicted"
                confidence = 0.3
                break
            if b_word in ai_words and a_word in kb_words:
                status = "conflicted"
                confidence = 0.3
                break

    return EntityVerification(
        entity=entity,
        category=category,
        status=status,
        confidence=confidence,
        qdrant_matches=qdrant_matches,
        kiwix_matches=kiwix_matches,
        qdrant_evidence=qdrant_evidence,
        kiwix_evidence=kiwix_evidence,
        ai_description=ai_description,
        kb_description=kb_description,
    )


def verify_visual_id(
    visual_answer: str,
    embed_url: str,
    qdrant_url: str,
    kiwix_url: str,
    zim_dir: str,
    collection: str = "elfin_docs",
    embed_model: str = "nomic-embed-text",
    top_k: int = 3,
) -> VerificationResult:
    """Main entry point: verify AI visual identification against knowledge sources.

    1. Extracts entities from the visual analysis text
    2. Searches Qdrant and Kiwix for each entity
    3. Cross-references AI claims with knowledge base descriptions
    4. Returns structured verification result
    """
    entities = extract_entities(visual_answer)

    if not entities:
        return VerificationResult(
            visual_answer=visual_answer,
            entities=[],
            overall_status="unverified",
            verified_count=0,
            unverified_count=0,
            conflicted_count=0,
            uncertain_count=0,
        )

    verifications: list[EntityVerification] = []

    for entity_name, category in entities:
        # Embed the entity for Qdrant search
        try:
            vector = embed_query(embed_url, entity_name, embed_model)
        except Exception:
            vector = []

        # Search Qdrant
        qdrant_points: list[dict] = []
        if vector:
            try:
                qdrant_points = search_qdrant(qdrant_url, collection, vector, top_k)
            except Exception:
                pass

        # Search Kiwix
        kiwix_results: list[dict] = []
        try:
            kiwix_results = search_kiwix_for_entity(kiwix_url, zim_dir, entity_name)
        except Exception:
            pass

        # Extract the AI's description relevant to this entity
        entity_desc = _extract_entity_description(visual_answer, entity_name)

        verification = verify_entity(
            entity=entity_name,
            category=category,
            ai_description=entity_desc,
            qdrant_points=qdrant_points,
            kiwix_results=kiwix_results,
        )
        verifications.append(verification)

    # Compute overall status
    verified_count = sum(1 for v in verifications if v.status == "verified")
    unverified_count = sum(1 for v in verifications if v.status == "unverified")
    conflicted_count = sum(1 for v in verifications if v.status == "conflicted")
    uncertain_count = sum(1 for v in verifications if v.status == "uncertain")

    if conflicted_count > 0:
        overall_status = "conflicted"
    elif verified_count > unverified_count and verified_count >= len(verifications) / 2:
        overall_status = "verified"
    elif unverified_count > verified_count:
        overall_status = "unverified"
    else:
        overall_status = "uncertain"

    return VerificationResult(
        visual_answer=visual_answer,
        entities=verifications,
        overall_status=overall_status,
        verified_count=verified_count,
        unverified_count=unverified_count,
        conflicted_count=conflicted_count,
        uncertain_count=uncertain_count,
    )


def _extract_entity_description(text: str, entity: str) -> str:
    """Extract the sentence(s) describing a specific entity from the visual analysis."""
    entity_lower = entity.lower()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    relevant: list[str] = []
    for sentence in sentences:
        if entity_lower in sentence.lower():
            relevant.append(sentence.strip())
    # If no sentence mentions the entity directly, return the full text
    return " ".join(relevant) if relevant else text


def format_verification_report(result: VerificationResult) -> str:
    """Format a human-readable verification report."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("ELFIN TRUST MODEL VERIFICATION REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Visual analysis: {result.visual_answer[:200]}")
    if len(result.visual_answer) > 200:
        lines[-1] += "..."
    lines.append("")
    lines.append(f"Overall status: {result.overall_status.upper()}")
    lines.append(f"  Verified:    {result.verified_count}")
    lines.append(f"  Unverified:  {result.unverified_count}")
    lines.append(f"  Conflicted:  {result.conflicted_count}")
    lines.append(f"  Uncertain:   {result.uncertain_count}")
    lines.append("")

    if not result.entities:
        lines.append("No survival-relevant entities detected in visual analysis.")
        return "\n".join(lines)

    lines.append("-" * 60)
    lines.append("ENTITY DETAILS:")
    lines.append("-" * 60)

    for entity in result.entities:
        status_marker = {
            "verified": "[V]",
            "unverified": "[?]",
            "conflicted": "[!]",
            "uncertain": "[~]",
        }.get(entity.status, "[?]")

        lines.append("")
        lines.append(f"  {status_marker} {entity.entity} ({entity.category})")
        lines.append(f"      Status:     {entity.status.upper()}")
        lines.append(f"      Confidence: {entity.confidence:.0%}")
        lines.append(f"      Qdrant:     {entity.qdrant_matches} matches")
        lines.append(f"      Kiwix:      {entity.kiwix_matches} matches")

        if entity.ai_description:
            lines.append(f"      AI says:    {entity.ai_description[:120]}")
            if len(entity.ai_description) > 120:
                lines[-1] += "..."

        if entity.kb_description:
            lines.append(f"      KB says:    {entity.kb_description[:120]}")
            if len(entity.kb_description) > 120:
                lines[-1] += "..."

        if entity.qdrant_evidence:
            lines.append(f"      Qdrant evidence:")
            for ev in entity.qdrant_evidence[:2]:
                lines.append(f"        - {ev[:150]}")

        if entity.kiwix_evidence:
            lines.append(f"      Kiwix evidence:")
            for ev in entity.kiwix_evidence[:2]:
                lines.append(f"        - {ev[:150]}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def verification_to_json(result: VerificationResult) -> dict:
    """Convert verification result to JSON-serializable dict."""
    return {
        "visual_answer": result.visual_answer,
        "overall_status": result.overall_status,
        "verified_count": result.verified_count,
        "unverified_count": result.unverified_count,
        "conflicted_count": result.conflicted_count,
        "uncertain_count": result.uncertain_count,
        "entities": [
            {
                "entity": e.entity,
                "category": e.category,
                "status": e.status,
                "confidence": round(e.confidence, 3),
                "qdrant_matches": e.qdrant_matches,
                "kiwix_matches": e.kiwix_matches,
                "qdrant_evidence": e.qdrant_evidence,
                "kiwix_evidence": e.kiwix_evidence,
                "ai_description": e.ai_description,
                "kb_description": e.kb_description,
            }
            for e in result.entities
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Elfin verified trust model - cross-reference AI visual ID against Qdrant + Kiwix"
    )
    parser.add_argument(
        "--visual-answer",
        required=True,
        help="AI visual analysis text to verify",
    )
    parser.add_argument("--embed-url", default="http://localhost:8082", help="llama-embed base URL")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant base URL")
    parser.add_argument("--kiwix-url", default="http://localhost:8083", help="Kiwix base URL")
    parser.add_argument("--zim-dir", default="./data/datasets/zim", help="Directory with ZIM files")
    parser.add_argument("--collection", default="elfin_docs", help="Qdrant collection name")
    parser.add_argument("--embed-model", default="nomic-embed-text", help="Embedding model name")
    parser.add_argument("--top-k", type=int, default=3, help="Number of Qdrant results per entity")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human-readable report")
    args = parser.parse_args()

    try:
        result = verify_visual_id(
            visual_answer=args.visual_answer,
            embed_url=args.embed_url,
            qdrant_url=args.qdrant_url,
            kiwix_url=args.kiwix_url,
            zim_dir=args.zim_dir,
            collection=args.collection,
            embed_model=args.embed_model,
            top_k=args.top_k,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(verification_to_json(result), indent=2))
    else:
        print(format_verification_report(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
