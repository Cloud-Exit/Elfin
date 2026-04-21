from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.chat import discover_kiwix_books, fetch_guessed_kiwix_article, fetch_kiwix_article_text, guess_article_titles, kiwix_search, kiwix_suggest_titles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kiwix-url", default="http://localhost:8083")
    parser.add_argument("--zim-dir", default="./data/datasets/zim")
    parser.add_argument("--query", default="who was adolf hitler?")
    args = parser.parse_args()

    books = discover_kiwix_books(Path(args.zim_dir))
    print("Books:")
    for book in books:
        print(f"- {book}")

    guessed_titles = guess_article_titles(args.query)
    print("\nGuessed titles:")
    for title in guessed_titles:
        print(f"- {title}")

    for book in books[:3]:
        print(f"\nBook: {book}")

        for title in guessed_titles[:3]:
            print(f"  Suggest term: {title!r}")
            try:
                suggestions = kiwix_suggest_titles(args.kiwix_url, book, title, count=8)
            except Exception as exc:
                print(f"    suggest failed: {exc}")
                continue
            if not suggestions:
                print("    suggestions: none")
                continue
            for item in suggestions[:5]:
                print(f"    - title={item['title']!r} path={item['path']!r}")

        guessed = None
        for title in guessed_titles[:2]:
            guessed = fetch_guessed_kiwix_article(args.kiwix_url, book, title)
            if guessed:
                print(f"  direct fetch for {title!r}: ok path={guessed[0]!r} text={guessed[1][:160]!r}")
                break
        if not guessed:
            print("  direct fetch: none")

        for term in guessed_titles[:2] + [args.query]:
            print(f"  Search term: {term!r}")
            try:
                results = kiwix_search(args.kiwix_url, book, term, limit=5)
            except Exception as exc:
                print(f"    search failed: {exc}")
                continue
            print(f"    results: {len(results)}")
            for result in results[:5]:
                print(f"    - title={result['title']!r} path={result['path']!r}")
                try:
                    text = fetch_kiwix_article_text(args.kiwix_url, result["book"], result["path"])
                except Exception as exc:
                    print(f"      fetch failed: {exc}")
                    continue
                print(f"      fetch ok: {text[:160]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
