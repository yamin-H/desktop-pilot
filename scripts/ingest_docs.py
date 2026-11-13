"""Load documents (Markdown, text, PDF) into the searchable library.

Usage: uv run python scripts/ingest_docs.py [FOLDER] [--prune]
Default folder: data/docs

The first run downloads a small embedding model (internet needed once). Running it again
only processes files that changed. With --prune, documents whose file is gone are removed.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from deskpilot.config import get_settings
from deskpilot.rag import DocumentStore, FastEmbedEmbedder, ingest_directory
from deskpilot.storage import create_pool

DEFAULT_FOLDER = Path(__file__).resolve().parent.parent / "data" / "docs"


async def main(folder: Path, prune: bool) -> int:
    if not folder.is_dir():
        print(f"{folder} is not a folder")
        return 2
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as error:
        print(f"Cannot reach the database ({error}). Run: make db-up && make migrate")
        return 2
    try:
        print("loading the embedding model (the first run downloads it)...", flush=True)
        results = await ingest_directory(
            DocumentStore(pool), FastEmbedEmbedder(), folder, prune=prune
        )
    finally:
        await pool.close()

    for result in results:
        detail = f"{result.chunks} chunks" if result.chunks else (result.error or "")
        print(f"{result.status:<10}{result.source:<40}{detail}")
    counts = {
        status: sum(r.status == status for r in results) for status in {r.status for r in results}
    }
    print("\n" + ", ".join(f"{number} {status}" for status, number in sorted(counts.items())))
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load documents into the library.")
    parser.add_argument("folder", nargs="?", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--prune", action="store_true", help="remove documents whose file is gone")
    arguments = parser.parse_args()
    sys.exit(asyncio.run(main(arguments.folder, arguments.prune)))
