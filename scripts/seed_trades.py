"""Store the made-up paper trades (no real money involved).

Safe to run again and again: the trades have fixed IDs, so repeats are ignored.
First start the database:  make db-up && make migrate
Usage: uv run python scripts/seed_trades.py
"""

import asyncio
import logging
import sys

from deskpilot.config import get_settings
from deskpilot.evals.dataset import PAPER_TRADES
from deskpilot.storage import TradeRepository, create_pool


async def main() -> int:
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as exc:
        raise SystemExit(
            f"Cannot reach the database ({exc}). Run: make db-up && make migrate"
        ) from None

    try:
        repo = TradeRepository(pool)
        result = await repo.save_trades(list(PAPER_TRADES))
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