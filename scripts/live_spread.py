"""Watch the live price gap between Binance and Kraken.

Usage: uv run python scripts/live_spread.py [seconds]
"""

import asyncio
import logging
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime
from deskpilot.analytics import PriceBoard
from deskpilot.ingestion import BinanceFeed, KrakenFeed, run_feeds
from deskpilot.ingestion.binance import BINANCE_WS_URL
from deskpilot.ingestion.kraken import KRAKEN_WS_URL

SYMBOLS = ["BTC/USDT", "ETH/USDT"]


async def show_spreads(board: PriceBoard, every: float = 1.0) -> None:
    while True:
        await asyncio.sleep(every)
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        spreads = {spread.symbol: spread for spread in board.spreads()}
        for symbol in SYMBOLS:
            spread = spreads.get(symbol)
            if spread is None:
                print(f"{stamp}  {symbol:<9} waiting for fresh prices from both exchanges")
                continue
            print(
                f"{stamp}  {symbol:<9} "
                f"{spread.high.exchange.value} {spread.high.price:.2f}  vs  "
                f"{spread.low.exchange.value} {spread.low.price:.2f}  "
                f"gap {spread.amount:.2f} ({spread.percent:.4f}%)"
            )


async def main(seconds: float) -> None:
    board = PriceBoard(max_age=30)
    feeds = [
        BinanceFeed(
            SYMBOLS,
            board.on_tick,
            base_url=os.environ.get("BINANCE_WS_URL", BINANCE_WS_URL),
        ),
        KrakenFeed(
            SYMBOLS,
            board.on_tick,
            url=os.environ.get("KRAKEN_WS_URL", KRAKEN_WS_URL),
        ),
    ]
    with suppress(TimeoutError):
        async with asyncio.timeout(seconds):
            async with asyncio.TaskGroup() as group:
                group.create_task(run_feeds(feeds))
                group.create_task(show_spreads(board))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with suppress(KeyboardInterrupt):
        asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 30))