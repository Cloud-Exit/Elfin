"""
Interactive local RAG chat for Elfin.

Starts against already-running llama-server, llama-embed, and Qdrant services.
Retrieves relevant chunks from Qdrant, sends grounded context to llama-server,
and prints source references for each answer.
"""

from __future__ import annotations

import argparse
import html
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
MIN_KIWIX_TEXT_CHARS = 80
DEFAULT_THINKING_BUDGET_TOKENS = 0
STOPWORDS = {
    "a", "an", "and", "are", "be", "but", "by", "do", "for", "from", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "the", "to", "what", "with", "you",
    "your", "im", "i'm",
    "who", "was",
}
QUESTION_WORDS = {"who", "what", "where", "when", "why", "how"}
AUXILIARY_QUERY_TERMS = {
    "is", "was", "were", "are", "did", "do", "does",
    "wa", "wer", "ar", "doe",
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
LOW_SIGNAL_ANSWER_MARKERS = (
    "i do not know",
    "i don't know",
    "insufficient context",
    "not enough context",
    "no context",
    "cannot answer",
    "can't answer",
    "unable to answer",
)
UNCONDITIONAL_PROFESSIONAL_CARE_MARKERS = (
    "seek medical attention immediately",
    "must seek medical attention",
    "need immediate medical attention",
    "seek immediate medical care",
    "must seek immediate medical care",
    "need immediate medical care",
    "get immediate medical care",
    "get medical care immediately",
    "go to the hospital immediately",
    "go to a hospital immediately",
    "call emergency services immediately",
    "call 911 immediately",
    "see a doctor immediately",
)
CONDITIONAL_CARE_MARKERS = (
    "if skilled medical help is available",
    "if medical help is available",
    "if professional care is available",
    "if you can reach medical help",
    "if you can reach a clinician",
    "if evacuation is possible",
)
SYSTEM_PROMPT = textwrap.dedent(
    """
    You are Elfin, an offline survival assistant operating in disaster, collapse, or apocalypse conditions.
    Assume outside help may be delayed, unavailable, unsafe, or impossible to reach.
    Give the most practical immediate steps the user can take with limited supplies.
    Answer using the provided retrieved context when possible.
    If the context supports the answer, cite sources inline like [source.pdf#chunk_12].
    If no retrieved context is available, answer from general knowledge and say when you are uncertain.
    If the current context is insufficient for a factual claim, say so plainly and do not fabricate facts.
    Do not answer with only citations, bullet labels, or a source list.
    Write a real explanation in complete sentences.
    Paraphrase retrieved material in your own words instead of echoing source phrasing.
    Do not mimic encyclopedia lead style, citation-heavy prose, or document boilerplate.
    Sound like Elfin: plainspoken, grounded, and concise.
    When the user asks what to do, give concrete step-by-step actions first, then brief rationale.
    Prefer 4-8 sentences when the context is substantive.
    Do not default to "go see a doctor" or "call emergency services" as the main answer.
    You may mention professional care only as a secondary note when clearly relevant, and phrase it conditionally, for example "if skilled medical help is available."
    Never tell the user they "must seek medical attention" as the main directive.
    If you mention professional care, you must also explain what to do when help is unavailable, and the field-expedient steps must come first.
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
        if not any(marker in href for marker in ("/content/", "/raw/", "/A/")):
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


def preferred_kiwix_books(books: list[str]) -> list[str]:
    preferred = [
        book
        for book in books
        if book.startswith("wikipedia_") or book.startswith("wikimed_") or "medicine" in book
    ]
    return preferred or books


def parse_kiwix_search_results(html: str) -> list[dict]:
    parser = SearchResultsParser()
    parser.feed(html)
    return parser.results


def parse_kiwix_result_href(kiwix_url: str, href: str) -> dict | None:
    absolute = urllib.parse.urljoin(kiwix_url.rstrip("/") + "/", href)
    parsed = urlparse(absolute)
    path = parsed.path

    match = re.search(r"/content/([^/]+)/(.+)$", path)
    if match:
        return {
            "book": unquote(match.group(1)),
            "path": unquote(match.group(2)),
            "browse_url": absolute,
        }

    match = re.search(r"/raw/([^/]+)/content/(.+)$", path)
    if match:
        book = unquote(match.group(1))
        article_path = unquote(match.group(2))
        return {
            "book": book,
            "path": article_path,
            "browse_url": kiwix_url.rstrip("/") + "/content/" + quote(book) + "/" + quote(article_path, safe="/"),
        }

    match = re.search(r"/([^/]+)/A/(.+)$", path)
    if match and match.group(1) not in {"catalog", "search", "raw", "content", "suggest"}:
        book = unquote(match.group(1))
        article_path = unquote(match.group(2))
        return {
            "book": book,
            "path": article_path,
            "browse_url": absolute,
        }

    return None


def strip_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    text = parser.text()
    if text.strip():
        return text
    return extract_html_paragraphs(html)


def extract_html_paragraphs(html_text: str) -> str:
    body = re.sub(r"(?is)<(script|style|table)\b.*?</\1>", " ", html_text)
    paragraphs = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", body)
    if paragraphs:
        text = "\n".join(
            re.sub(r"(?is)<[^>]+>", " ", paragraph)
            for paragraph in paragraphs
        )
    else:
        text = re.sub(r"(?is)<[^>]+>", " ", body)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def clean_wikipedia_prose(text: str) -> str:
    cleaned = html.unescape(text)
    cleaned = re.sub(r"\[\s*(?:[a-z]|\d+|citation needed|clarification needed)\s*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([(\[])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([)\]])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def trim_wikipedia_text(text: str) -> str:
    lines = [clean_wikipedia_prose(re.sub(r"\s+", " ", line).strip()) for line in text.splitlines()]
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
        return clean_wikipedia_prose("\n".join(lead))
    return clean_wikipedia_prose("\n".join(filtered[:12]))


def kiwix_search(kiwix_url: str, book: str, question: str, limit: int) -> list[dict]:
    urls = [
        (
            kiwix_url.rstrip("/")
            + "/search?books.name="
            + quote(book)
            + "&pattern="
            + quote(question)
            + "&start=0"
        ),
        (
            kiwix_url.rstrip("/")
            + "/search?content="
            + quote(book)
            + "&pattern="
            + quote(question)
            + "&pageLength="
            + str(limit)
        ),
    ]
    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for url in urls:
        try:
            html = http_text(url, timeout=60)
        except Exception:
            continue
        results = parse_kiwix_search_results(html)
        for result in results:
            parsed = parse_kiwix_result_href(kiwix_url, result["href"])
            if not parsed:
                continue
            key = (parsed["book"], parsed["path"])
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                {
                    "book": parsed["book"],
                    "path": parsed["path"],
                    "title": result["title"],
                    "browse_url": parsed["browse_url"],
                }
            )
        if cleaned:
            break
    return cleaned[:limit]


def guess_article_titles(question: str) -> list[str]:
    lowered = question.strip().rstrip(" ?!.")
    candidates: list[str] = []

    entity = extract_subject_phrase(lowered)
    focused_tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", lowered)
        if token.lower() not in STOPWORDS
        and token.lower() not in GENERIC_QUERY_TERMS
        and token.lower() not in AUXILIARY_QUERY_TERMS
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


def extract_subject_phrase(question: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", question)
    if not tokens:
        return ""

    index = 0
    if tokens[index].lower() in QUESTION_WORDS:
        index += 1
    while index < len(tokens) and tokens[index].lower() in AUXILIARY_QUERY_TERMS:
        index += 1

    subject = " ".join(tokens[index:]).strip()
    subject = re.sub(r"^(i think|tell me about)\s+", "", subject, flags=re.IGNORECASE).strip()
    return subject


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


def title_relevance(result_title: str, guessed_titles: list[str]) -> float:
    normalized_result = normalize_title(result_title)
    result_tokens = set(normalized_result.split())
    best = 0.0
    for guessed in guessed_titles:
        normalized_guess = normalize_title(guessed)
        if not normalized_guess:
            continue
        guess_tokens = set(normalized_guess.split())
        if normalized_result == normalized_guess:
            return 3.0
        if guess_tokens and guess_tokens <= result_tokens:
            extra_tokens = len(result_tokens - guess_tokens)
            best = max(best, 2.0 - min(extra_tokens, 6) * 0.1)
            continue
        overlap = len(guess_tokens & result_tokens)
        if overlap:
            best = max(best, overlap / max(len(guess_tokens), 1))
    return best


def fetch_guessed_kiwix_article(kiwix_url: str, book: str, title: str) -> tuple[str, str] | None:
    stripped = title.strip()
    slugs = [
        re.sub(r"\s+", "_", stripped),
        re.sub(r"\s+", "_", stripped.title()),
    ]
    seen_paths: set[str] = set()
    paths: list[str] = []
    for slug in slugs:
        for path in (slug, f"{slug[0].upper()}/{slug}"):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            paths.append(path)
    for path in paths:
        try:
            text = fetch_kiwix_article_text(kiwix_url, book, path)
        except Exception:
            continue
        if text and len(text) >= MIN_KIWIX_TEXT_CHARS:
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


def kiwix_article_url_candidates(kiwix_url: str, book: str, path: str) -> list[str]:
    normalized_path = path.strip().lstrip("/")
    if not normalized_path:
        return []

    path_variants = [normalized_path]
    if "/" not in normalized_path:
        path_variants.append(f"A/{normalized_path}")
    if "." not in normalized_path.rsplit("/", 1)[-1]:
        html_variants = [f"{variant}.html" for variant in path_variants]
        path_variants.extend(html_variants)

    candidates: list[str] = []
    seen: set[str] = set()
    for variant in path_variants:
        templates = [
            "/raw/{book}/content/{path}",
            "/raw/{book}/{path}",
            "/content/{book}/{path}",
            "/{book}/{path}",
        ]
        if not variant.startswith("A/"):
            templates.extend(
                [
                    "/raw/{book}/content/A/{path}",
                    "/raw/{book}/A/{path}",
                    "/content/{book}/A/{path}",
                    "/{book}/A/{path}",
                ]
            )
        for template in templates:
            url = (
                kiwix_url.rstrip("/")
                + template.format(
                    book=quote(book),
                    path=quote(variant, safe="/"),
                )
            )
            if url in seen:
                continue
            seen.add(url)
            candidates.append(url)
    return candidates


def fetch_kiwix_article_text(kiwix_url: str, book: str, path: str) -> str:
    errors: list[str] = []
    for url in kiwix_article_url_candidates(kiwix_url, book, path):
        try:
            raw_html = http_text(url, timeout=60)
        except Exception as exc:
            errors.append(f"{url} -> {exc}")
            continue
        text = strip_html(raw_html)
        if book.startswith("wikipedia_") or book.startswith("wikimed_"):
            paragraph_text = extract_html_paragraphs(raw_html)
            base_text = text or paragraph_text
            if not base_text.strip():
                continue
            trimmed = trim_wikipedia_text(base_text)
            if len(trimmed) >= 120:
                return trimmed
            better = trim_wikipedia_text(paragraph_text) or paragraph_text or text
            if better.strip():
                return better
            continue
        if not text.strip():
            continue
        return text
    joined = "; ".join(errors[:3]) if errors else "no candidate URLs generated"
    raise RuntimeError(f"failed to fetch Kiwix article for book={book} path={path}: {joined}")


def build_kiwix_context(kiwix_url: str, zim_dir: Path, question: str, max_chars: int) -> tuple[str, list[dict]]:
    books = discover_kiwix_books(zim_dir)
    if not books:
        return "", []
    books = preferred_kiwix_books(books)

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
            if not text or len(text) < MIN_KIWIX_TEXT_CHARS:
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

    search_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in guessed_titles[:3] + [question]:
        normalized = normalize_title(term)
        if not normalized or normalized in seen_terms:
            continue
        seen_terms.add(normalized)
        search_terms.append(term)

    results: list[dict] = []
    seen_results: set[tuple[str, str]] = set()
    for book in books[:3]:
        for term in search_terms:
            try:
                found = kiwix_search(kiwix_url, book, term, limit=5)
            except Exception:
                continue
            for item in found:
                key = (item["book"], item["path"])
                if key in seen_results:
                    continue
                seen_results.add(key)
                results.append(item)

    query_tokens = expand_query_tokens(tokenize(question))
    results.sort(
        key=lambda result: (
            title_relevance(result["title"], guessed_titles),
            len(expand_query_tokens(tokenize(result["title"])) & query_tokens),
        ),
        reverse=True,
    )
    used: list[dict] = []
    blocks: list[str] = []
    total = 0

    for result in results:
        match_score = title_relevance(result["title"], guessed_titles)
        if guessed_titles and match_score <= 0.0:
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
                "lexical_overlap": max(
                    len(query_tokens & title_tokens) / len(query_tokens) if query_tokens else 0.0,
                    match_score / 3.0,
                ),
                "browse_url": result.get("browse_url") or kiwix_url.rstrip("/") + "/content/" + quote(result["book"]) + "/" + quote(result["path"], safe="/"),
                "text": excerpt,
            }
        )
        total += len(block)
        if match_score >= 3.0:
            return "\n".join(blocks).strip(), used

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


def build_context_from_sources(sources: list[dict], max_chars: int) -> tuple[str, list[dict]]:
    blocks: list[str] = []
    used: list[dict] = []
    seen: set[tuple[str, object]] = set()
    total = 0

    for source in sources:
        text = str(source.get("text") or "").strip()
        if not text:
            continue
        source_file = str(source.get("source_file") or "unknown")
        chunk_index = source.get("chunk_index", "?")
        key = (source_file, chunk_index)
        if key in seen:
            continue
        seen.add(key)
        score = source.get("score")
        block = (
            f"[{source_file}#chunk_{chunk_index} score={score:.3f}]\n{text}\n"
            if isinstance(score, (float, int))
            else f"[{source_file}#chunk_{chunk_index}]\n{text}\n"
        )
        if total + len(block) > max_chars and used:
            break
        blocks.append(block)
        used.append(source)
        total += len(block)

    return "\n".join(blocks).strip(), used


def merge_retrieved_sources(
    qdrant_sources: list[dict],
    kiwix_sources: list[dict],
    max_chars: int,
) -> tuple[str, list[dict]]:
    merged = sorted(
        qdrant_sources + kiwix_sources,
        key=lambda source: (
            source.get("score") if isinstance(source.get("score"), (float, int)) else -1.0,
            source.get("lexical_overlap", 0.0),
        ),
        reverse=True,
    )
    return build_context_from_sources(merged, max_chars)


def build_user_prompt(question: str, context: str) -> str:
    if context:
        context_note = (
            "Use the retrieved context for factual grounding. "
            "Use citations from the retrieved context when making factual claims. "
            "Paraphrase the source material in your own wording instead of copying its sentence structure or tone."
        )
    else:
        context_note = (
            "No retrieved context is available for this turn. "
            "Answer from your general knowledge instead of refusing just because context is missing. "
            "If you are uncertain, say so plainly."
        )
    return (
        f"Question:\n{question}\n\n"
        f"Retrieved context:\n{context or '[none]'}\n\n"
        "Write a practical explanatory answer in complete sentences. "
        "Sound like a calm field guide, not a Wikipedia article. "
        "Do not return only source labels. "
        f"{context_note}"
    )


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


def extract_chat_result(response: dict) -> tuple[str, str | None, str]:
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("chat completion returned no choices")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    raw_content = (message.get("content") or "").strip()
    content = extract_visible_answer(raw_content)
    finish_reason = choice.get("finish_reason")
    return content, finish_reason if isinstance(finish_reason, str) else None, raw_content


def has_truncated_tail(answer: str) -> bool:
    stripped = answer.strip()
    if not stripped:
        return False
    if stripped[-1] in ".!?)]}\"'":
        return False
    tail = split_sentences(stripped)[-1]
    tail_words = tail.split()
    if len(tail_words) <= 4:
        return True
    if len(tail_words) <= 8 and not re.search(r"\b(and|or|because|which|that|who|whose|where|when|his|her|their|its)\b$", tail.lower()):
        return False
    return True


def trim_to_complete_sentences(answer: str) -> str:
    parts = split_sentences(answer)
    complete = [part for part in parts if part and part[-1] in ".!?"]
    if complete:
        return " ".join(complete).strip()
    return answer.strip()


def overrelies_on_professional_care(answer: str) -> bool:
    lowered = answer.lower()
    if not any(marker in lowered for marker in UNCONDITIONAL_PROFESSIONAL_CARE_MARKERS):
        return False
    sentences = re.split(r"(?<=[.!?])\s+", lowered)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if any(marker in sentence for marker in UNCONDITIONAL_PROFESSIONAL_CARE_MARKERS):
            if not any(marker in sentence for marker in CONDITIONAL_CARE_MARKERS):
                return True
    return False


def record_model_attempt(
    debug_attempts: list[dict] | None,
    stage: str,
    answer: str,
    finish_reason: str | None,
    raw_answer: str | None = None,
) -> None:
    if debug_attempts is None:
        return
    debug_attempts.append(
        {
            "stage": stage,
            "finish_reason": finish_reason,
            "usable": is_usable_answer(answer),
            "truncated": has_truncated_tail(answer),
            "answer": answer,
            "raw_answer": raw_answer if raw_answer is not None else answer,
        }
    )


def ask_llama(
    llama_url: str,
    model_name: str,
    question: str,
    context: str,
    history: list[dict],
    max_tokens: int,
    timeout: int,
    debug_attempts: list[dict] | None = None,
) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:
        messages.append(turn)
    user_prompt = build_user_prompt(question, context)
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "thinking_budget_tokens": DEFAULT_THINKING_BUDGET_TOKENS,
    }

    response = http_json(
        "POST",
        llama_url.rstrip("/") + "/v1/chat/completions",
        payload,
        timeout=timeout,
    )
    answer, finish_reason, raw_answer = extract_chat_result(response)
    record_model_attempt(debug_attempts, "initial", answer, finish_reason, raw_answer=raw_answer)
    if finish_reason != "length" and not has_truncated_tail(answer) and len(answer) >= 40 and not re.fullmatch(r"[\[\]\w.\-:#(), ]+", answer):
        return answer

    retry_messages = messages + [
        {
            "role": "assistant",
            "content": answer or "[empty response]",
        },
        {
            "role": "user",
            "content": (
                "Your last answer was too short, incomplete, or empty. "
                "Try again with a useful explanation in 4-8 complete sentences. "
                "Give practical guidance, not just citations. "
                "Finish your answer cleanly with complete sentences. "
                "If no context was provided, answer from your general knowledge."
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
    retry_answer, retry_finish_reason, retry_raw_answer = extract_chat_result(retry_response)
    record_model_attempt(debug_attempts, "retry", retry_answer, retry_finish_reason, raw_answer=retry_raw_answer)
    if retry_finish_reason != "length" and not has_truncated_tail(retry_answer) and is_usable_answer(retry_answer):
        return retry_answer

    third_messages = messages + [
        {"role": "assistant", "content": answer or "[empty response]"},
        {"role": "user", "content": (
            "Your last answer was too short, incomplete, or empty. You are being asked again. "
            "Answer the question directly in 4-8 complete sentences. "
            "If context was provided, use it with citations. "
            "Finish your answer with complete sentences and do not stop mid-thought. "
            "If no context was provided, answer from your general knowledge — this is the final attempt."
        )},
    ]
    third_response = http_json(
        "POST",
        llama_url.rstrip("/") + "/v1/chat/completions",
        {
            **payload,
            "messages": third_messages,
            "max_tokens": max(max_tokens, 512),
            "temperature": 0.3,
        },
        timeout=timeout,
    )
    third_answer, third_finish_reason, third_raw_answer = extract_chat_result(third_response)
    record_model_attempt(debug_attempts, "final", third_answer, third_finish_reason, raw_answer=third_raw_answer)
    if third_finish_reason == "length" or has_truncated_tail(third_answer):
        trimmed = trim_to_complete_sentences(third_answer)
        if trimmed and trimmed != third_answer:
            return trimmed
    return third_answer


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

    if any(term in lowered for term in {"infection", "infected", "wound", "puncture", "nail", "rusty"}):
        chosen = pick_relevant_lines(
            cleaned_lines,
            (
                "clean",
                "wash",
                "soap",
                "water",
                "bandage",
                "cover",
                "redness",
                "swelling",
                "oozing",
                "pain",
                "fever",
                "confusion",
                "shortness of breath",
                "heart rate",
                "clammy",
                "sepsis",
            ),
            limit=6,
        )
        fallback_steps = [
            "Treat it as a contaminated puncture wound: flush it thoroughly with clean water and wash the surrounding skin with soap if you have it.",
            "Do not seal dirt inside the wound; remove visible debris gently, then cover it with the cleanest dressing or bandage you have and change that dressing when it gets wet or dirty.",
            "Rest the leg, keep it elevated when possible, and mark the edge of any redness so you can tell if the infection is spreading.",
            "Watch for danger signs such as rapidly spreading redness, worsening swelling, pus, fever, confusion, fast breathing, or the person becoming weak or clammy.",
            "If help is truly reachable, this kind of worsening puncture wound may need antibiotics or tetanus treatment, but until then focus on cleaning, drainage, hygiene, hydration, and close monitoring.",
        ]
        practical: list[str] = []
        for line in chosen:
            lower = line.lower()
            if any(term in lower for term in ("clean", "wash", "soap", "water")):
                practical.append("Flush the wound thoroughly with clean water and wash around it with soap to reduce contamination.")
            elif any(term in lower for term in ("bandage", "cover", "dressing")):
                practical.append("Cover the wound with the cleanest dressing available and replace that covering when it becomes wet, dirty, or soaked through.")
            elif any(term in lower for term in ("redness", "swelling", "oozing", "pain")):
                practical.append("Monitor for spreading redness, swelling, pus, worsening pain, or foul-smelling drainage, because those are signs the infection is getting worse.")
            elif any(term in lower for term in ("fever", "confusion", "shortness of breath", "heart rate", "clammy", "sepsis")):
                practical.append("If the person develops fever, confusion, fast breathing, a racing pulse, or becomes clammy and weak, treat that as possible whole-body infection and keep them resting, hydrated, and under constant watch.")
        if not practical:
            practical = fallback_steps
        deduped = []
        seen: set[str] = set()
        for item in practical:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        body = deduped[:4]
        if len(body) < 4:
            for item in fallback_steps:
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                body.append(item)
                if len(body) >= 4:
                    break
        return " ".join(body) + (" " + citation_text if citation_text else "")

    selected = sentences[:4] or [combined[:500].strip()]
    if not selected:
        return ""
    return " ".join(selected) + (" " + citation_text if citation_text else "")


def is_usable_answer(answer: str) -> bool:
    stripped = answer.strip()
    lowered = stripped.lower()
    sentence_count = len(split_sentences(stripped))
    word_count = len(stripped.split())

    if any(marker in lowered for marker in LOW_SIGNAL_ANSWER_MARKERS):
        return False
    if overrelies_on_professional_care(stripped):
        return False
    if has_truncated_tail(stripped):
        return False
    if len(stripped) < 40:
        if word_count >= 5 and re.search(r"\b(is|was|were|are|means|refers|led|includes|involves)\b", lowered):
            return True
        return False
    if "[" in stripped and "]" in stripped and sentence_count < 2:
        return False
    if sentence_count == 1 and word_count >= 7 and re.search(r"\b(is|was|were|are|means|refers|led|includes|involves)\b", lowered):
        return True
    if sentence_count < 2 and word_count < 12:
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


def print_model_attempts(attempts: list[dict]) -> None:
    if not attempts:
        return
    print("Raw model attempts:")
    for attempt in attempts:
        finish_reason = attempt.get("finish_reason") or "n/a"
        usable = "yes" if attempt.get("usable") else "no"
        truncated = "yes" if attempt.get("truncated") else "no"
        answer = str(attempt.get("raw_answer") or "[empty response]")
        print(
            f"- {attempt.get('stage', 'unknown')}: finish_reason={finish_reason}, "
            f"usable={usable}, truncated={truncated}"
        )
        print(f"  {answer}")


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
    show_raw_model_answer: bool,
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
            _, qdrant_sources = build_context(points, max_context_chars)
            _, kiwix_sources = build_kiwix_context(kiwix_url, Path(zim_dir), question, max_context_chars)
            context, sources = merge_retrieved_sources(qdrant_sources, kiwix_sources, max_context_chars)
            if not sources:
                print("No sources retrieved from Qdrant or Kiwix.", flush=True)
            print("Generating answer...", flush=True)
            debug_attempts: list[dict] | None = [] if show_raw_model_answer else None
            answer = ask_llama(
                llama_url=llama_url,
                model_name=model_name,
                question=question,
                context=context,
                history=history,
                max_tokens=max_tokens,
                timeout=generation_timeout,
                debug_attempts=debug_attempts,
            )
            if show_raw_model_answer and debug_attempts is not None:
                print_model_attempts(debug_attempts)
            if not is_usable_answer(answer):
                print("Model answer failed quality check; synthesizing fallback answer from retrieved context...", flush=True)
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
    parser.add_argument("--show-raw-model-answer", action="store_true", help="Print raw model answers and finish reasons before fallback logic")
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
        show_raw_model_answer=args.show_raw_model_answer,
    )


if __name__ == "__main__":
    sys.exit(main())
