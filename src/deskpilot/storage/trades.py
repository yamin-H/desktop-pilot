import logging
from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg

from deskpilot.models import Exchange, Trade

logger = logging.getLogger(__name__)

_COLUMNS = "exchange, trade_id, symbol, side, quantity, price, fee, fee_asset, executed_at"

_INSERT = f"""
INSERT INTO trades ({_COLUMNS})
SELECT * FROM unnest(
    $1::text[], $2::text[], $3::text[], $4::text[], $5::numeric[],
    $6::numeric[], $7::numeric[], $8::text[], $9::timestamptz[]
)
ON CONFLICT (exchange, trade_id) DO NOTHING
RETURNING exchange, trade_id
"""

_SELECT_KNOWN = f"""
SELECT {_COLUMNS} FROM trades
WHERE (exchange, trade_id) IN (SELECT * FROM unnest($1::text[], $2::text[]))
"""

_LIST = f"""
SELECT {_COLUMNS} FROM trades
WHERE ($1::text IS NULL OR exchange = $1)
  AND ($2::text IS NULL OR symbol = $2)
ORDER BY executed_at, trade_id
"""


@dataclass(frozen=True)
class TradeConflict:
    """The same trade ID arrived with different content. The stored version is kept."""

    existing: Trade
    incoming: Trade

    @property
    def differing_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in Trade.model_fields
            if getattr(self.existing, name) != getattr(self.incoming, name)
        )


@dataclass(frozen=True)
class SaveTradesResult:
    inserted: int  # new trades stored
    duplicates: int  # identical copies of trades we already had (ignored)
    conflicts: tuple[TradeConflict, ...]  # same ID, different content (NOT stored)


def _to_trade(row: asyncpg.Record) -> Trade:
    return Trade(**dict(row))


class TradeRepository:
    """Saves and reads trades. The only code that touches the trades table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save_trades(self, trades: Sequence[Trade]) -> SaveTradesResult:
        """Store new trades. Never overwrites; reports repeats and conflicts."""
        # Step 1: sort out repeats inside the batch itself.
        first_seen: dict[tuple[str, str], Trade] = {}
        duplicates = 0
        conflicts: list[TradeConflict] = []
        for trade in trades:
            earlier = first_seen.get(trade.dedupe_key)
            if earlier is None:
                first_seen[trade.dedupe_key] = trade
            elif earlier == trade:
                duplicates += 1
            else:
                conflicts.append(TradeConflict(existing=earlier, incoming=trade))

        unique = list(first_seen.values())
        if not unique:
            return SaveTradesResult(0, 0, ())

        # Step 2: store what is new, then compare the rest with what we already hold.
        async with self._pool.acquire() as conn, conn.transaction():
            inserted_rows = await conn.fetch(
                _INSERT,
                [t.exchange.value for t in unique],
                [t.trade_id for t in unique],
                [t.symbol for t in unique],
                [t.side.value for t in unique],
                [t.quantity for t in unique],
                [t.price for t in unique],
                [t.fee for t in unique],
                [t.fee_asset for t in unique],
                [t.executed_at for t in unique],
            )
            inserted_keys = {(row["exchange"], row["trade_id"]) for row in inserted_rows}

            skipped = [t for t in unique if t.dedupe_key not in inserted_keys]
            if skipped:
                known_rows = await conn.fetch(
                    _SELECT_KNOWN,
                    [t.exchange.value for t in skipped],
                    [t.trade_id for t in skipped],
                )
                stored = {(row["exchange"], row["trade_id"]): _to_trade(row) for row in known_rows}
                for trade in skipped:
                    existing = stored[trade.dedupe_key]
                    if existing == trade:
                        duplicates += 1
                    else:
                        conflicts.append(TradeConflict(existing=existing, incoming=trade))

        for conflict in conflicts:
            logger.warning(
                "trade conflict on %s/%s: %s differ; kept the stored version",
                conflict.existing.exchange.value,
                conflict.existing.trade_id,
                ", ".join(conflict.differing_fields),
            )
        return SaveTradesResult(
            inserted=len(inserted_keys), duplicates=duplicates, conflicts=tuple(conflicts)
        )

    async def get(self, exchange: Exchange, trade_id: str) -> Trade | None:
        row = await self._pool.fetchrow(
            f"SELECT {_COLUMNS} FROM trades WHERE exchange = $1 AND trade_id = $2",
            exchange.value,
            trade_id,
        )
        return _to_trade(row) if row else None

    async def list_trades(
        self, *, exchange: Exchange | None = None, symbol: str | None = None
    ) -> list[Trade]:
        """All trades, oldest first, optionally for one exchange and/or one symbol."""
        rows = await self._pool.fetch(_LIST, exchange.value if exchange else None, symbol)
        return [_to_trade(row) for row in rows]
