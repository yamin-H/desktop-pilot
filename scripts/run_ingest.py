"""Feeds -> Redis stream (no database needed). Pair with scripts/run_recorder.py.

Usage: uv run python scripts/run_ingest.py [seconds]   (no number = until Ctrl+C)
"""

import asyncio
import logging
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime

from redis import exceptions as redis_errors

from deskpilot.bus import REDIS_RETRYABLE, StreamTickSaver, make_redis
from deskpilot.config import get_settings
from deskpilot.ingestion import BinanceFeed, KrakenFeed, run_feeds
from deskpilot.ingestion.binance import BINANCE_WS_URL
from deskpilot.ingestion.kraken import KRAKEN_WS_URL
from deskpilot.storage import Recorder

SYMBOLS = ["BTC/USDT", "ETH/USDT"]


def status_line(publisher: Recorder) -> str:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    return (
        f"{stamp}  published {publisher.saved_count}  waiting {publisher.pending}  "
        f"dropped {publisher.dropped_count}  redis retries {publisher.retry_count}"
    )


async def report(publisher: Recorder, every: float = 5.0) -> None:
    while True:
        await asyncio.sleep(every)
        print(status_line(publisher), flush=True)


async def main(seconds: float | None) -> int:
    settings = get_settings()
    redis = make_redis(settings.redis_url)
    try:
        await redis.ping()
    except (OSError, redis_errors.RedisError) as error:
        print(f"Cannot reach Redis ({error}). Run: make db-up")
        await redis.aclose()
        return 2

    # The Recorder gives us a bounded buffer, retry and drain; its "save" is an XADD.
    publisher = Recorder(
        StreamTickSaver(redis, settings.tick_stream, settings.tick_stream_maxlen),
        retry_on=(*Recorder.retry_on, *REDIS_RETRYABLE),
    )
    feeds = [
        BinanceFeed(
            SYMBOLS, publisher.on_tick, base_url=os.environ.get("BINANCE_WS_URL", BINANCE_WS_URL)
        ),
        KrakenFeed(SYMBOLS, publisher.on_tick, url=os.environ.get("KRAKEN_WS_URL", KRAKEN_WS_URL)),
    ]
    try:
        try:
            with suppress(TimeoutError):
                async with asyncio.timeout(seconds):
                    async with asyncio.TaskGroup() as group:
                        group.create_task(run_feeds(feeds))
                        group.create_task(publisher.run())
                        group.create_task(report(publisher))
        finally:
            await publisher.drain()
            print("stopped. " + status_line(publisher))
    finally:
        await redis.aclose()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else None)))
