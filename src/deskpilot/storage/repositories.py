from collections.abc import Sequence

import asyncpg

from deskpilot.models import Exchange, PriceTick

# One statement saves the whole batch. Rows that already exist are skipped silently.
_INSERT_TICKS = """
INSERT INTO prices (exchange, symbol, price, exchange_time, received_time)
SELECT * FROM unnest(
    $1::text[], $2::text[], $3::numeric[], $4::timestamptz[], $5::timestamptz[]
)
ON CONFLICT (exchange, symbol, exchange_time, price) DO NOTHING
"""

_LATEST_TICK = """
SELECT exchange, symbol, price, exchange_time, received_time
FROM prices
WHERE exchange = $1 AND symbol = $2
ORDER BY exchange_time DESC, received_time DESC
LIMIT 1
"""


class PriceRepository:
    """Saves and reads price ticks. The only code that touches the prices table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save_ticks(self, ticks: Sequence[PriceTick]) -> int:
        """Save ticks. Returns how many were NEW; duplicates change nothing."""
        if not ticks:
            return 0
        status = await self._pool.execute(
            _INSERT_TICKS,
            [t.exchange.value for t in ticks],
            [t.symbol for t in ticks],
            [t.price for t in ticks],
            [t.exchange_time for t in ticks],
            [t.received_time for t in ticks],
        )
        return int(status.rsplit(" ", 1)[-1])  # "INSERT 0 3" -> 3

    async def latest(self, exchange: Exchange, symbol: str) -> PriceTick | None:
        """The most recent tick (by exchange time) for one exchange and symbol."""
        row = await self._pool.fetchrow(_LATEST_TICK, exchange.value, symbol)
        return PriceTick(**dict(row)) if row else None
