"""
Simple verification script for the duckduckgo_search library.

Usage:
    python verify_duckduckgo.py "FastAPI tutorial" --max-results 3
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from duckduckgo_search import DDGS


def run_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """
    Execute a DuckDuckGo text search and return the raw result objects.
    """
    with DDGS(timeout=10) as ddgs:
        return list(ddgs.text(query, max_results=max_results))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DuckDuckGo search access.")
    parser.add_argument("query", help="Search query text.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Number of results to retrieve (default: 5).",
    )
    args = parser.parse_args()

    try:
        results = run_search(args.query, args.max_results)
    except Exception as exc:  # pragma: no cover - used for manual verification only
        print(f"Search failed: {exc}", file=sys.stderr)
        return 1

    if not results:
        print("No results returned.")
        return 0

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

