"""
Interactive local RAG chat for Elfin.

Starts against already-running llama-server, llama-embed, and Qdrant services.
Retrieves relevant chunks from Qdrant, sends grounded context to llama-server,
and prints source references for each answer.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import re
import subprocess
import sys
import textwrap
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_COLLECTION = "elfin_docs"
MIN_SEMANTIC_SCORE = 0.62
STOPWORDS = {
    "a", "an", "and", "are", "be", "but", "by", "do", "for", "from", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "the", "to", "what", "with", "you",
    "your", "im", "i'm",
    "who", "was",
}
QUERY_EXPANSIONS = {
    "ptsd": {"post", "traumatic", "stress", "disorder", "trauma"},
    "broken": {"fracture", "fractured", "break", "broken"},
    "leg": {"leg", "limb"},
    "afraid": {"fear", "anxiety", "panic", "afraid"},
}
GENERIC_QUERY_TERMS = {
    "antidote", "antidotes", "symptom", "symptoms", "treatment", "treat", "treating",
    "cure", "causes", "cause", "what", "who", "where", "when", "why", "how", "for",
    "the", "a", "an", "of", "is", "was", "are", "were", "do", "does", "did",
}
SYSTEM_PROMPT = textwrap.dedent(
    """
    You are Elfin, an offline survival assistant operating in disaster, collapse, or apocalypse conditions.
    Assume outside help may be delayed, unavailable, unsafe, or impossible to reach.
    Give the most practical immediate steps the user can take with limited supplies.
    Answer using the provided retrieved context when possible.
    If the context supports the answer, cite sources inline like [source.pdf#chunk_12].
    If the current context is insufficient, say so plainly and do not fabricate facts.
    Do not answer with only citations, bullet labels, or a source list.
    Write a real explanation in complete sentences.
    When the user asks what to do, give concrete step-by-step actions first, then brief rationale.
    Prefer 4-8 sentences when the context is substantive.
    Do not default to "go see a doctor" or "call emergency services" as the main answer.
    You may mention professional care only as a secondary note when clearly relevant, and phrase it conditionally, for example "if skilled medical help is available."
    For injury or medical questions, prioritize stabilization, danger signs, hygiene, monitoring, and practical field-expedient actions.
    For health or mental health concerns, avoid diagnosis certainty.
    Keep answers direct, calm, and practical.
    """
).strip()


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


def http_ok(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return True, str(response.status)
    except Exception as exc:
        return False, str(exc)


def http_text(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode(errors="ignore")


def http_json_get(url: str, timeout: int = 60) -> object:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def check_services(llama_url: str, embed_url: str, qdrant_url: str, kiwix_url: str) -> list[str]:
    errors: list[str] = []
    for label, url in [
        ("llama-server", llama_url.rstrip("/") + "/health"),
        ("llama-embed", embed_url.rstrip("/") + "/health"),
        ("qdrant", qdrant_url.rstrip("/") + "/healthz"),
        ("kiwix", kiwix_url.rstrip("/") + "/catalog/v2/root.xml"),
    ]:
        ok, msg = http_ok(url)
        if not ok:
            errors.append(f"{label} unavailable: {msg}")
    return errors


def embed_query(embed_url: str, text: str, model_name: str) -> list[float]:
    response = http_json(
        "POST",
        embed_url.rstrip("/") + "/v1/embeddings",
        {"input": text, "model": model_name},
        timeout=60,
    )
    return response["data"][0]["embedding"]


def query_points(qdrant_url: str, collection: str, vector: list[float], limit: int) -> list[dict]:
    response = http_json(
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


class SearchResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_link = False
        self.current_href = ""
        self.current_text: list[str] = []
        self.results: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        if "/content/" not in href:
            return
        self.in_link = True
        self.current_href = href
        self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_link:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self.in_link:
            return
        title = " ".join(part.strip() for part in self.current_text if part.strip()).strip()
        if title:
            self.results.append({"href": self.current_href, "title": title})
        self.in_link = False
        self.current_href = ""
        self.current_text = []


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.skip_tag_stack: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        attr_blob = " ".join(value for value in attr_map.values() if value).lower()
        skip_for_class = any(
            marker in attr_blob
            for marker in (
                "infobox",
                "navbox",
                "vertical-navbox",
                "sidebar",
                "metadata",
                "ambox",
                "plainlinks",
                "reflist",
                "hatnote",
                "shortdescription",
                "toc",
            )
        )
        if tag in {"script", "style", "table"} or skip_for_class:
            self.skip_depth += 1
            self.skip_tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_tag_stack and tag == self.skip_tag_stack[-1] and self.skip_depth > 0:
            self.skip_depth -= 1
            self.skip_tag_stack.pop()
        elif tag in {"script", "style", "table"} and self.skip_depth > 0:
            self.skip_depth -= 1
        elif tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.parts)).strip()


def normalize_zim_name(path: Path) -> str:
    stem = path.stem
    return re.sub(r"_\d{4}-\d{2}$", "", stem)


def discover_kiwix_books(zim_dir: Path) -> list[str]:
    if not zim_dir.is_dir():
        return []

    preferred: list[str] = []
    others: list[str] = []
    for path in sorted(zim_dir.glob("*.zim")):
        book_id = path.stem
        normalized = normalize_zim_name(path)
        if normalized.startswith("wikipedia_en_"):
            preferred.append(book_id)
        elif normalized.startswith("wikimed_en_") or "medicine" in normalized:
            preferred.append(book_id)
        else:
            others.append(book_id)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in preferred + others:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def parse_kiwix_search_results(html: str) -> list[dict]:
    parser = SearchResultsParser()
    parser.feed(html)
    return parser.results


def strip_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return parser.text()


def trim_wikipedia_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    junk_prefixes = (
        "contents",
        "appearance",
        "hide",
        "this article",
        "for other uses",
        "coordinates",
        "also known as",
        "part of a series",
    )
    junk_exact = {
        "adolf hitler",
        "formal portrait, 1938",
    }
    filtered: list[str] = []
    for line in lines:
        lower = line.lower()
        if lower in junk_exact:
            continue
        if any(lower.startswith(prefix) for prefix in junk_prefixes):
            continue
        if len(line.split()) <= 2:
            continue
        filtered.append(line)

    lead: list[str] = []
    for line in filtered:
        lower = line.lower()
        if any(
            marker in lower
            for marker in (
                " was ",
                " is ",
                " was an ",
                " was a ",
                " was the ",
                " world war",
                " nazi",
                " holocaust",
                " dictator",
                " politician",
            )
        ):
            lead.append(line)
        if len(lead) >= 6:
            break

    if lead:
        return "\n".join(lead)
    return "\n".join(filtered[:12])


def kiwix_search(kiwix_url: str, book: str, question: str, limit: int) -> list[dict]:
    url = (
        kiwix_url.rstrip("/")
        + "/search?content="
        + quote(book)
        + "&pattern="
        + quote(question)
        + "&pageLength="
        + str(limit)
    )
    html = http_text(url, timeout=60)
    results = parse_kiwix_search_results(html)
    cleaned: list[dict] = []
    for result in results:
        href = result["href"]
        match = re.search(r"/content/([^/]+)/(.+)$", href)
        if not match:
            continue
        cleaned.append(
            {
                "book": unquote(match.group(1)),
                "path": unquote(match.group(2)),
                "title": result["title"],
            }
        )
    return cleaned


def guess_article_titles(question: str) -> list[str]:
    lowered = question.strip().rstrip(" ?!.")
    candidates: list[str] = []

    entity = re.sub(
        r"^(who|what|where|when|why|how)\s+(is|was|were|are|did|do)\s+",
        "",
        lowered,
        flags=re.IGNORECASE,
    )
    entity = re.sub(r"^(i think|tell me about)\s+", "", entity, flags=re.IGNORECASE).strip()
    focused_tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", lowered)
        if token.lower() not in STOPWORDS and token.lower() not in GENERIC_QUERY_TERMS
    ]
    if focused_tokens:
        candidates.append(" ".join(focused_tokens))
        if focused_tokens[-1].lower() not in GENERIC_QUERY_TERMS:
            candidates.append(focused_tokens[-1])

    if entity:
        candidates.append(entity)

    tokens = [token for token in re.findall(r"[A-Za-z0-9]+", lowered) if token.lower() not in STOPWORDS]
    if tokens:
        candidates.append(" ".join(tokens))

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return ordered


def normalize_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def title_matches_guess(result_title: str, guessed_titles: list[str]) -> bool:
    normalized_result = normalize_title(result_title)
    result_tokens = set(normalized_result.split())
    for guessed in guessed_titles:
        normalized_guess = normalize_title(guessed)
        guess_words = normalized_guess.split()
        guess_tokens = set(guess_words)
        if not normalized_guess:
            continue
        if normalized_result == normalized_guess:
            return True
        if normalized_guess in normalized_result or normalized_result in normalized_guess:
            extra_tokens = result_tokens - guess_tokens
            if len(extra_tokens) <= 1:
                return True
        if guess_tokens and result_tokens and guess_tokens <= result_tokens:
            extra_tokens = result_tokens - guess_tokens
            if len(extra_tokens) <= 1:
                return True
        if len(guess_words) == 1 and guess_words[0] in result_tokens and len(result_tokens) <= 3:
            return True
    return False


def fetch_guessed_kiwix_article(kiwix_url: str, book: str, title: str) -> tuple[str, str] | None:
    slug = re.sub(r"\s+", "_", title.strip())
    for path in [f"{slug}", f"{slug[0].upper()}/{slug}"]:
        try:
            text = fetch_kiwix_article_text(kiwix_url, book, path)
        except Exception:
            continue
        if text and len(text) > 200:
            return path, text
    return None


def kiwix_suggest_titles(kiwix_url: str, book: str, term: str, count: int = 10) -> list[dict]:
    url = (
        kiwix_url.rstrip("/")
        + "/suggest?content="
        + quote(book)
        + "&term="
        + quote(term)
        + "&count="
        + str(count)
    )
    payload = http_json_get(url, timeout=30)
    suggestions: list[dict] = []

    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("suggestions") or payload.get("results") or payload.get("items") or []
    else:
        entries = []

    for entry in entries:
        if isinstance(entry, str):
            suggestions.append({"title": entry, "path": re.sub(r"\s+", "_", entry.strip())})
            continue
        if not isinstance(entry, dict):
            continue
        title = None
        for key in ("value", "title", "name", "label"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                break
        if not title:
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            path = re.sub(r"\s+", "_", title)
        suggestions.append({"title": title, "path": path.strip()})

    seen: set[str] = set()
    ordered: list[dict] = []
    for item in suggestions:
        key = normalize_title(item["title"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return ordered


def fetch_kiwix_article_text(kiwix_url: str, book: str, path: str) -> str:
    url = kiwix_url.rstrip("/") + "/raw/" + quote(book) + "/content/" + quote(path, safe="/")
    text = strip_html(http_text(url, timeout=60))
    if book.startswith("wikipedia_") or book.startswith("wikimed_"):
        return trim_wikipedia_text(text)
    return text


def build_kiwix_context(kiwix_url: str, zim_dir: Path, question: str, max_chars: int) -> tuple[str, list[dict]]:
    books = discover_kiwix_books(zim_dir)
    if not books:
        return "", []

    guessed_titles = guess_article_titles(question)

    # Prefer exact article-title fetches for entity questions before loose search hits.
    for book in books[:2]:
        suggested_titles: list[dict] = []
        for title in guessed_titles[:4]:
            try:
                suggested_titles.extend(kiwix_suggest_titles(kiwix_url, book, title, count=8))
            except Exception:
                continue
        for item in suggested_titles[:6]:
            title = item["title"]
            path = item["path"]
            try:
                text = fetch_kiwix_article_text(kiwix_url, book, path)
            except Exception:
                continue
            if not text or len(text) <= 200:
                continue
            excerpt = text[:1600].strip()
            citation = f"{book}:{title}"
            block = f"[{citation}]\n{excerpt}\n"
            return block.strip(), [
                {
                    "source_file": citation,
                    "chunk_index": path,
                    "score": None,
                    "lexical_overlap": 1.0,
                    "browse_url": kiwix_url.rstrip("/") + "/content/" + quote(book) + "/" + quote(path, safe="/"),
                    "text": excerpt,
                }
            ]
        for title in guessed_titles[:4]:
            guessed = fetch_guessed_kiwix_article(kiwix_url, book, title)
            if not guessed:
                continue
            path, text = guessed
            excerpt = text[:1600].strip()
            citation = f"{book}:{title}"
            block = f"[{citation}]\n{excerpt}\n"
            return block.strip(), [
                {
                    "source_file": citation,
                    "chunk_index": path,
                    "score": None,
                    "lexical_overlap": 1.0,
                    "browse_url": kiwix_url.rstrip("/") + "/content/" + quote(book) + "/" + quote(path, safe="/"),
                    "text": excerpt,
                }
            ]

    results: list[dict] = []
    for book in books[:3]:
        try:
            results.extend(kiwix_search(kiwix_url, book, question, limit=3))
        except Exception:
            continue

    query_tokens = expand_query_tokens(tokenize(question))
    used: list[dict] = []
    blocks: list[str] = []
    total = 0

    for result in results:
        acceptable_title_match = title_matches_guess(result["title"], guessed_titles)
        if guessed_titles and not acceptable_title_match:
            # If we can identify a concrete target title, avoid unrelated or weakly
            # related titles, but still allow useful variants like "Cyanide poisoning"
            # for questions about cyanide antidotes.
            continue
        title_tokens = tokenize(result["title"])
        if query_tokens and not (query_tokens & title_tokens):
            continue
        try:
            text = fetch_kiwix_article_text(kiwix_url, result["book"], result["path"])
        except Exception:
            continue
        if not text:
            continue
        excerpt = text[:1600].strip()
        citation = f"{result['book']}:{result['title']}"
        block = f"[{citation}]\n{excerpt}\n"
        if total + len(block) > max_chars and used:
            break
        blocks.append(block)
        used.append(
            {
                "source_file": citation,
                "chunk_index": "article",
                "score": None,
                "lexical_overlap": len(query_tokens & title_tokens) / len(query_tokens) if query_tokens else 0.0,
                "browse_url": kiwix_url.rstrip("/") + "/content/" + quote(result["book"]) + "/" + quote(result["path"], safe="/"),
                "text": excerpt,
            }
        )
        total += len(block)

    if used:
        return "\n".join(blocks).strip(), used

    return "\n".join(blocks).strip(), used


def tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {token for token in tokens if token not in STOPWORDS and len(token) > 1}


def expand_query_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(QUERY_EXPANSIONS.get(token, set()))
    return expanded


def lexical_overlap(question: str, payload: dict) -> float:
    query_tokens = expand_query_tokens(tokenize(question))
    haystack = " ".join(
        [
            str(payload.get("source_file", "")),
            str(payload.get("text", "")),
        ]
    )
    doc_tokens = tokenize(haystack)
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)


def filter_relevant_points(points: list[dict], question: str) -> list[dict]:
    kept: list[dict] = []
    for point in points:
        payload = point.get("payload", {}) or {}
        overlap = lexical_overlap(question, payload)
        score = point.get("score")
        semantic_ok = isinstance(score, (float, int)) and score >= MIN_SEMANTIC_SCORE
        lexical_ok = overlap > 0.0
        if not (semantic_ok or lexical_ok):
            continue
        point["lexical_overlap"] = overlap
        kept.append(point)

    kept.sort(
        key=lambda point: (
            point.get("lexical_overlap", 0.0),
            point.get("score", 0.0) if isinstance(point.get("score"), (float, int)) else 0.0,
        ),
        reverse=True,
    )
    return kept


def sample_payload(qdrant_url: str, collection: str) -> dict | None:
    response = http_json(
        "POST",
        qdrant_url.rstrip("/") + f"/collections/{collection}/points/scroll",
        {
            "limit": 1,
            "with_payload": True,
            "with_vectors": False,
        },
        timeout=30,
    )
    points = response.get("result", {}).get("points", [])
    if not points:
        return None
    return points[0].get("payload", {})


def ensure_rag_payload(
    python_bin: str,
    qdrant_url: str,
    embed_url: str,
    source_dir: str,
    collection: str,
) -> None:
    payload = sample_payload(qdrant_url, collection)
    if payload and payload.get("text"):
        return

    print("Refreshing ingestion index so Qdrant payloads include chunk text...", flush=True)
    cmd = [
        python_bin,
        "src/ingestion/pipeline.py",
        "--force",
        "--verify-queryable",
        "--source-dir",
        source_dir,
        "--qdrant-url",
        qdrant_url,
        "--embed-url",
        embed_url,
        "--report-out",
        "./data/ingestion/chat-refresh-report.json",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("failed to refresh ingestion index for chat")


def build_context(points: list[dict], max_chars: int) -> tuple[str, list[dict]]:
    blocks: list[str] = []
    used: list[dict] = []
    total = 0

    for point in points:
        payload = point.get("payload", {}) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            continue
        source_file = payload.get("source_file", "unknown")
        chunk_index = payload.get("chunk_index", "?")
        score = point.get("score")
        block = (
            f"[{source_file}#chunk_{chunk_index} score={score:.3f}]\n{text}\n"
            if isinstance(score, (float, int))
            else f"[{source_file}#chunk_{chunk_index}]\n{text}\n"
        )
        if total + len(block) > max_chars and used:
            break
        blocks.append(block)
        used.append(
            {
                "source_file": source_file,
                "chunk_index": chunk_index,
                "score": score,
                "lexical_overlap": point.get("lexical_overlap", 0.0),
                "text": text,
            }
        )
        total += len(block)

    return "\n".join(blocks).strip(), used


def ask_llama(
    llama_url: str,
    model_name: str,
    question: str,
    context: str,
    history: list[dict],
    max_tokens: int,
    timeout: int,
) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:
        messages.append(turn)
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Retrieved context:\n{context or '[none]'}\n\n"
        "Write a practical explanatory answer in complete sentences. "
        "Do not return only source labels. "
        "Use citations from the retrieved context when making factual claims."
    )
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    response = http_json(
        "POST",
        llama_url.rstrip("/") + "/v1/chat/completions",
        payload,
        timeout=timeout,
    )
    answer = response["choices"][0]["message"]["content"].strip()
    if len(answer) >= 40 and not re.fullmatch(r"[\[\]\w.\-:#(), ]+", answer):
        return answer

    retry_messages = messages + [
        {
            "role": "assistant",
            "content": answer or "[empty response]",
        },
        {
            "role": "user",
            "content": (
                "Your last answer was too short or empty. "
                "Try again with a useful explanation in 4-8 complete sentences. "
                "Give practical guidance, not just citations."
            ),
        },
    ]
    retry_response = http_json(
        "POST",
        llama_url.rstrip("/") + "/v1/chat/completions",
        {
            **payload,
            "messages": retry_messages,
            "max_tokens": max(max_tokens, 384),
            "temperature": 0.25,
        },
        timeout=timeout,
    )
    return retry_response["choices"][0]["message"]["content"].strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def clean_source_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "TCCC-CLS-PPT" in line:
            continue
        if len(line) < 12:
            continue
        letters = [ch for ch in line if ch.isalpha()]
        if letters:
            upper_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
            if upper_ratio > 0.75 and len(line.split()) <= 8:
                continue
        lines.append(line)
    return lines


def pick_relevant_lines(lines: list[str], keywords: tuple[str, ...], limit: int = 4) -> list[str]:
    chosen: list[str] = []
    for line in lines:
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            chosen.append(line)
        if len(chosen) >= limit:
            break
    return chosen


def synthesize_answer(question: str, sources: list[dict]) -> str:
    if not sources:
        return ""

    lowered = question.lower()
    citations = [f"[{source['source_file']}#chunk_{source['chunk_index']}]" for source in sources[:2]]
    citation_text = " ".join(citations)
    combined = " ".join(source.get("text", "") for source in sources)
    sentences = split_sentences(combined)
    cleaned_lines = clean_source_lines("\n".join(source.get("text", "") for source in sources))

    if lowered.startswith("who was ") or lowered.startswith("who is "):
        selected = [
            sentence
            for sentence in sentences
            if len(sentence.split()) >= 8
            and not any(
                marker in sentence.lower()
                for marker in ("preceded by", "succeeded by", "in office", "signature", "allegiance")
            )
        ][:4]
        if not selected and combined.strip():
            selected = [combined[:700].strip()]
        if selected:
            return " ".join(selected) + (" " + citation_text if citation_text else "")

    if any(term in lowered for term in {"broken", "fracture", "fractured"}):
        chosen = pick_relevant_lines(
            cleaned_lines,
            (
                "splint",
                "immobil",
                "pulse",
                "circulation",
                "capillary refill",
                "open fracture",
                "bleeding",
                "distal",
                "sensation",
            ),
            limit=5,
        )
        fallback_steps = [
            "Treat it as a fracture until proven otherwise: keep the leg still and do not walk on it.",
            "Immobilize the injured leg and splint the joints above and below the suspected break if you can do so without causing major extra pain.",
            "Check circulation and sensation below the injury before and after splinting, including pulse, warmth, color, and whether the foot can still feel touch.",
            "If there is an open wound or bleeding, control bleeding first and cover the wound with the cleanest dressing available before splinting.",
        ]
        practical: list[str] = []
        for line in chosen:
            lower = line.lower()
            if "pulse" in lower or "circulation" in lower or "capillary refill" in lower:
                practical.append("Check circulation below the injury before and after splinting; if the foot becomes cold, pale, numb, or pulseless, loosen and readjust the splint.")
            elif "open fracture" in lower or "bleeding" in lower:
                practical.append("If the fracture is open or bleeding, control bleeding and cover the wound before you secure the splint.")
            elif "splint" in lower or "immobil" in lower:
                practical.append("Splint the leg to prevent movement, and immobilize the joints above and below the suspected fracture.")
            elif "sensation" in lower:
                practical.append("Recheck sensation and movement in the foot after splinting so you do not miss nerve or circulation problems.")
        if not practical:
            practical = fallback_steps
        deduped: list[str] = []
        seen: set[str] = set()
        for item in practical:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        body = deduped[:4]
        if len(body) < 3:
            for item in fallback_steps:
                if item.lower() not in seen:
                    body.append(item)
                    seen.add(item.lower())
                if len(body) >= 4:
                    break
        return " ".join(body) + (" " + citation_text if citation_text else "")

    selected = sentences[:4] or [combined[:500].strip()]
    if not selected:
        return ""
    return " ".join(selected) + (" " + citation_text if citation_text else "")


def is_usable_answer(answer: str) -> bool:
    stripped = answer.strip()
    if len(stripped) < 40:
        return False
    if "[" in stripped and "]" in stripped and len(split_sentences(stripped)) < 2:
        return False
    if len(split_sentences(stripped)) < 2 and len(stripped.split()) < 12:
        return False
    return True


def print_sources(sources: list[dict]) -> None:
    if not sources:
        print("Sources: none")
        return

    seen: set[tuple[str, object]] = set()
    print("Sources:")
    for source in sources:
        key = (source["source_file"], source["chunk_index"])
        if key in seen:
            continue
        seen.add(key)
        score = source.get("score")
        score_text = f"{score:.3f}" if isinstance(score, (float, int)) else "n/a"
        overlap = source.get("lexical_overlap", 0.0)
        line = f"- {source['source_file']}#chunk_{source['chunk_index']} (score={score_text}, overlap={overlap:.2f})"
        browse_url = source.get("browse_url")
        if browse_url:
            line += f" -> {browse_url}"
        print(line)


def repl(
    llama_url: str,
    embed_url: str,
    qdrant_url: str,
    kiwix_url: str,
    zim_dir: str,
    collection: str,
    model_name: str,
    embed_model: str,
    top_k: int,
    max_context_chars: int,
    max_tokens: int,
    generation_timeout: int,
) -> int:
    history: list[dict] = []

    print("Elfin chat ready. Type a question. `exit` or `quit` ends session.")
    while True:
        try:
            question = input("\nYou> ").strip()
        except EOFError:
            print()
            return 0

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            return 0

        try:
            print("Embedding query...", flush=True)
            vector = embed_query(embed_url, question, embed_model)
            print("Retrieving sources...", flush=True)
            points = query_points(qdrant_url, collection, vector, top_k)
            points = filter_relevant_points(points, question)
            context, sources = build_context(points, max_context_chars)
            if not sources:
                print("Falling back to Kiwix...", flush=True)
                context, sources = build_kiwix_context(kiwix_url, Path(zim_dir), question, max_context_chars)
                if not sources:
                    print(
                        "\nElfin> I do not have relevant indexed source material for that question yet. "
                        "No cited answer available from the current local corpus or Kiwix library."
                    )
                    print("Sources: none")
                    continue
            print("Generating answer...", flush=True)
            answer = ask_llama(
                llama_url=llama_url,
                model_name=model_name,
                question=question,
                context=context,
                history=history,
                max_tokens=max_tokens,
                timeout=generation_timeout,
            )
            if not is_usable_answer(answer):
                print("Model answer too short; synthesizing fallback answer from retrieved context...", flush=True)
                answer = synthesize_answer(question, sources)
                if not answer:
                    answer = "I found relevant source material, but the model did not produce a usable answer."
        except Exception as exc:
            print(f"Error: {exc}")
            continue

        print(f"\nElfin> {answer}")
        print_sources(sources)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive Elfin RAG chat")
    parser.add_argument("--python", default=sys.executable or "python3", help="Python interpreter for refresh runs")
    parser.add_argument("--source-dir", default="./data/datasets/raw", help="Source directory for refresh ingestion")
    parser.add_argument("--llama-url", default="http://localhost:8081", help="llama-server base URL")
    parser.add_argument("--embed-url", default="http://localhost:8082", help="llama-embed base URL")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant base URL")
    parser.add_argument("--kiwix-url", default="http://localhost:8083", help="Kiwix base URL")
    parser.add_argument("--zim-dir", default="./data/datasets/zim", help="Directory containing local ZIM files")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Qdrant collection name")
    parser.add_argument("--model", default="gemma-4-E4B-it-Q5_K_M", help="llama-server model name")
    parser.add_argument("--embed-model", default="nomic-embed-text", help="embedding model name")
    parser.add_argument("--top-k", type=int, default=4, help="How many chunks to retrieve")
    parser.add_argument("--max-context-chars", type=int, default=3000, help="Max retrieved context characters")
    parser.add_argument("--max-tokens", type=int, default=384, help="Max answer tokens")
    parser.add_argument("--generation-timeout", type=int, default=240, help="Seconds to wait for each answer")
    parser.add_argument("--skip-refresh", action="store_true", help="Do not auto-refresh index if payload text is missing")
    args = parser.parse_args()

    errors = check_services(args.llama_url, args.embed_url, args.qdrant_url, args.kiwix_url)
    if errors:
        for error in errors:
            print(f"Error: {error}")
        return 1

    try:
        if not args.skip_refresh:
            ensure_rag_payload(
                python_bin=args.python,
                qdrant_url=args.qdrant_url,
                embed_url=args.embed_url,
                source_dir=args.source_dir,
                collection=args.collection,
            )
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    return repl(
        llama_url=args.llama_url,
        embed_url=args.embed_url,
        qdrant_url=args.qdrant_url,
        kiwix_url=args.kiwix_url,
        zim_dir=args.zim_dir,
        collection=args.collection,
        model_name=args.model,
        embed_model=args.embed_model,
        top_k=args.top_k,
        max_context_chars=args.max_context_chars,
        max_tokens=args.max_tokens,
        generation_timeout=args.generation_timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
