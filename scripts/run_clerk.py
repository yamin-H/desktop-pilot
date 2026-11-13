"""Watch announcement pages and send alerts.

Usage:
  uv run python scripts/run_clerk.py [--sources FILE] [--once] [--interval SECONDS]

Default sources file: config/announcement_sources.yaml (copy the .example.yaml first).
Needs the database (make db-up && make migrate) and Chromium (uv run playwright install chromium).
The first check of a source only records what is already there (a baseline): alerts start
with announcements that appear afterwards.
"""

import argparse
import asyncio
import logging
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from deskpilot.clerk.alerts import build_alerter
from deskpilot.clerk.fetcher import PlaywrightFetcher
from deskpilot.clerk.runner import SourceResult, run_clerk
from deskpilot.clerk.sources import SourceConfigError, load_sources
from deskpilot.clerk.store import AnnouncementStore
from deskpilot.config import get_settings
from deskpilot.storage import create_pool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = ROOT / "config" / "announcement_sources.yaml"


def show(result: SourceResult) -> None:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    if result.source_error:
        print(f"{stamp}  {result.source:<20} SOURCE ERROR: {result.source_error}", flush=True)
        return
    note = "baseline (no alerts)" if result.baseline else f"alerted {result.alerted}"
    line = f"{stamp}  {result.source:<20} read {result.fetched}, new {result.new}, {note}"
    if result.alert_error:
        line += f"  ALERT ERROR: {result.alert_error}"
    print(line, flush=True)


async def main(args: argparse.Namespace) -> int:
    try:
        sources = load_sources(args.sources, root=ROOT)
    except (OSError, SourceConfigError) as error:
        print(f"Cannot load the sources: {error}")
        return 2
    settings = get_settings()
    try:
        alerter = build_alerter(settings)
        pool = await create_pool(settings.database_url)
    except (ValueError, OSError) as error:
        print(f"Cannot start: {error}")
        return 2

    try:
        async with PlaywrightFetcher() as fetcher:
            await run_clerk(
                sources,
                fetcher,
                AnnouncementStore(pool),
                alerter,
                interval=args.interval,
                max_cycles=1 if args.once else None,
                on_result=show,
            )
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watch announcement pages and send alerts.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--once", action="store_true", help="check every source once and stop")
    parser.add_argument("--interval", type=float, default=300.0, help="seconds between checks")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main(parser.parse_args())))
