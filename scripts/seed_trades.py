"""Store a few made-up paper trades (no real money involved).

Safe to run again and again: the trades have fixed IDs, so repeats are ignored.
First start the database:  make db-up && make migrate
Usage: uv run python scripts/seed_trades.py
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from deskpilot.config import get_settings
from deskpilot.models import Trade
from deskpilot.storage import TradeRepository, create_pool


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 10, hour, minute, tzinfo=UTC)


PAPER_TRADES = [
    Trade(
        exchange="binance",
        trade_id="PAPER-0001",
        symbol="BTC/USDT",
        side="buy",
        quantity="0.50",
        price="60000",
        fee="0.0005",
        fee_asset="BTC",
        executed_at=at(10, 0),
    ),
    Trade(
        exchange="binance",
        trade_id="PAPER-0002",
        symbol="BTC/USDT",
        side="buy",
        quantity="0.25",
        price="61000",
        fee="15.25",
        fee_asset="USDT",
        executed_at=at(11, 30),
    ),
    Trade(
        exchange="binance",
        trade_id="PAPER-0003",
        symbol="BTC/USDT",
        side="sell",
        quantity="0.40",
        price="62500",
        fee="25.00",
        fee_asset="USDT",
        executed_at=at(14, 15),
    ),
    Trade(
        exchange="kraken",
        trade_id="PAPER-0004",
        symbol="ETH/USDT",
        side="buy",
        quantity="5",
        price="3000",
        fee="15.00",
        fee_asset="USDT",
        executed_at=at(10, 20),
    ),
    Trade(
        exchange="kraken",
        trade_id="PAPER-0005",
        symbol="ETH/USDT",
        side="sell",
        quantity="2",
        price="3100",
        fee="6.20",
        fee_asset="USDT",
        executed_at=at(16, 45),
    ),
]


async def main() -> int:
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as exc:
        raise SystemExit(
            f"Cannot reach the database ({exc}). Run: make db-up && make migrate"
        ) from None

    try:
        repo = TradeRepository(pool)
        result = await repo.save_trades(PAPER_TRADES)
        print(
            f"new: {result.inserted}   already stored: {result.duplicates}   "
            f"conflicts: {len(result.conflicts)}"
        )
        for conflict in result.conflicts:
            print(
                f"  CONFLICT {conflict.existing.trade_id}: "
                f"{', '.join(conflict.differing_fields)} differ (stored version kept)"
            )

        print()
        for t in await repo.list_trades():
            print(
                f"{t.executed_at:%Y-%m-%d %H:%M}  {t.exchange.value:<8} {t.trade_id:<11} "
                f"{t.side.value:<4} {t.symbol:<9} {t.quantity:>6} @ {t.price:<6} "
                f"fee {t.fee} {t.fee_asset}"
            )
        return 1 if result.conflicts else 0
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(main()))
