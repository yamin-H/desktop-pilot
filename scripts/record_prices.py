"""Record live Binance and Kraken prices into the database.

First start the database and apply migrations:  make db-up && make migrate
Usage: uv run python scripts/record_prices.py [seconds]
       (no number = run until you press Ctrl+C)
"""

import asyncio
import logging
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime

from deskpilot.config import get_settings
from deskpilot.ingestion import BinanceFeed, KrakenFeed, run_feeds
from deskpilot.ingestion.binance import BINANCE_WS_URL
from deskpilot.ingestion.kraken import KRAKEN_WS_URL
from deskpilot.storage import PriceRepository, Recorder, create_pool

SYMBOLS = ["BTC/USDT", "ETH/USDT"]


def status_line(recorder: Recorder) -> str:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    return (
        f"{stamp}  saved {recorder.saved_count}  duplicates {recorder.duplicate_count}  "
        f"waiting {recorder.pending}  dropped {recorder.dropped_count}  "
        f"db retries {recorder.retry_count}"
    )


async def report(recorder: Recorder, every: float = 5.0) -> None:
    while True:
        await asyncio.sleep(every)
        print(status_line(recorder))


async def main(seconds: float | None) -> None:
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as exc:
        raise SystemExit(
            f"Cannot reach the database ({exc}). Run: make db-up && make migrate"
        ) from None

    try:
        recorder = Recorder(PriceRepository(pool))
        feeds = [
            BinanceFeed(
                SYMBOLS,
                recorder.on_tick,
                base_url=os.environ.get("BINANCE_WS_URL", BINANCE_WS_URL),
            ),
            KrakenFeed(
                SYMBOLS,
                recorder.on_tick,
                url=os.environ.get("KRAKEN_WS_URL", KRAKEN_WS_URL),
            ),
        ]
        try:
            with suppress(TimeoutError):
                async with asyncio.timeout(seconds):  # None means no time limit
                    async with asyncio.TaskGroup() as group:
                        group.create_task(run_feeds(feeds))
                        group.create_task(recorder.run())
                        group.create_task(report(recorder))
        finally:
            await recorder.drain()  # save whatever is still waiting
            print("stopped. " + status_line(recorder))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with suppress(KeyboardInterrupt):
        asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else None))