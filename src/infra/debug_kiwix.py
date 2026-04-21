from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote


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
        if tag == "a" and self.in_link:
            title = " ".join(part.strip() for part in self.current_text if part.strip()).strip()
            self.results.append({"href": self.current_href, "title": title})
            self.in_link = False
            self.current_href = ""
            self.current_text = []


def http_text(url: str, timeout: int = 60) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode(errors="ignore")


def http_json(url: str, timeout: int = 60) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


def normalize_zim_name(path: Path) -> str:
    return re.sub(r"_\d{4}-\d{2}$", "", path.stem)


def discover_books(zim_dir: Path) -> list[str]:
    books: list[str] = []
    for path in sorted(zim_dir.glob("*.zim")):
        normalized = normalize_zim_name(path)
        if normalized.startswith("wikipedia_en_") or normalized.startswith("wikimed_en_") or "medicine" in normalized:
            books.append(path.stem)
    return books


def parse_results(html: str) -> list[dict]:
    parser = SearchResultsParser()
    parser.feed(html)
    cleaned: list[dict] = []
    for result in parser.results:
        match = re.search(r"/content/([^/]+)/(.+)$", result["href"])
        if not match:
            continue
        cleaned.append(
            {
                "book": unquote(match.group(1)),
                "path": unquote(match.group(2)),
                "title": result["title"],
                "href": result["href"],
            }
        )
    return cleaned


def try_fetch(kiwix_url: str, book: str, path: str) -> tuple[bool, str]:
    url = kiwix_url.rstrip("/") + "/raw/" + quote(book) + "/content/" + quote(path, safe="/")
    try:
        text = http_text(url, timeout=30)
    except Exception as exc:
        return False, f"{url} -> {exc}"
    return True, f"{url} -> {text[:160]!r}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kiwix-url", default="http://localhost:8083")
    parser.add_argument("--zim-dir", default="./data/datasets/zim")
    parser.add_argument("--query", default="who was adolf hitler?")
    args = parser.parse_args()

    books = discover_books(Path(args.zim_dir))
    print("Books:")
    for book in books:
        print(f"- {book}")

    for book in books[:3]:
        suggest_url = (
            args.kiwix_url.rstrip("/")
            + "/suggest?content="
            + quote(book)
            + "&term="
            + quote(args.query)
            + "&count=8"
        )
        print(f"\nSuggest URL: {suggest_url}")
        try:
            print(http_json(suggest_url, timeout=30))
        except Exception as exc:
            print(f"suggest failed: {exc}")

        url = (
            args.kiwix_url.rstrip("/")
            + "/search?content="
            + quote(book)
            + "&pattern="
            + quote(args.query)
            + "&pageLength=5"
        )
        print(f"\nSearch URL: {url}")
        try:
            html = http_text(url, timeout=30)
        except Exception as exc:
            print(f"search failed: {exc}")
            continue
        results = parse_results(html)
        print(f"results: {len(results)}")
        for result in results[:5]:
            print(f"- title={result['title']!r} path={result['path']!r}")
            ok, detail = try_fetch(args.kiwix_url, result["book"], result["path"])
            print(f"  fetch={ok} {detail}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
