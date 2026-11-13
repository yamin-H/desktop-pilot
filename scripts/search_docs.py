"""Search the document library and show what was found.

Usage: uv run python scripts/search_docs.py "how do we handle a missing_in_ledger break?"
"""

import argparse
import asyncio
import sys

from deskpilot.config import get_settings
from deskpilot.rag import DocumentStore, FastEmbedEmbedder, hybrid_search
from deskpilot.storage import create_pool


async def main(query: str, limit: int) -> int:
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as error:
        print(f"Cannot reach the database ({error}). Run: make db-up && make migrate")
        return 2
    try:
        hits = await hybrid_search(DocumentStore(pool), FastEmbedEmbedder(), query, limit=limit)
    finally:
        await pool.close()

    if not hits:
        print("nothing found (is the library empty? run scripts/ingest_docs.py)")
        return 1
    for number, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.content.split())
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        print(
            f"{number}. [{hit.citation}]  found by: "
            f"{', '.join(hit.found_by)}  score {hit.score:.4f}"
        )
        print(f"   {snippet}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search the document library.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args()
    sys.exit(asyncio.run(main(arguments.query, arguments.limit)))
