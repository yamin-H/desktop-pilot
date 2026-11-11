"""Print live Binance prices.

Usage: uv run python scripts/live_binance.py [how_many_ticks]
"""

import asyncio
import logging
import os
import sys
from contextlib import suppress

from deskpilot.ingestion import BinanceFeed
from deskpilot.ingestion.binance import BINANCE_WS_URL


async def main(limit: int) -> None:
    seen = 0
    done = asyncio.Event()

    async def show(tick):
        nonlocal seen
        seen += 1
        when = tick.exchange_time.strftime("%H:%M:%S.%f")[:-3]
        print(f"{when}  {tick.exchange.value}  {tick.symbol:<9} {tick.price}")
        if seen >= limit:
            done.set()

    feed = BinanceFeed(
        ["BTC/USDT", "ETH/USDT"],
        show,
        base_url=os.environ.get("BINANCE_WS_URL", BINANCE_WS_URL),
    )
    task = asyncio.create_task(feed.run())
    try:
        await done.wait()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))