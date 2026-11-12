from collections.abc import Iterable
from typing import Protocol

import asyncpg

from deskpilot.models import Exchange, PriceTick, Trade
from deskpilot.storage import PriceRepository, TradeRepository


class AgentData(Protocol):
    """Everything the assistant's tools are allowed to read. Read-only by design."""

    async def trades(
        self, *, exchange: Exchange | None = None, symbol: str | None = None
    ) -> list[Trade]:
        """Trades, oldest first, optionally for one exchange and/or one symbol."""
        ...

    async def latest_price(self, exchange: Exchange, symbol: str) -> PriceTick | None:
        """The most recent recorded price, or None if there is none."""
        ...


class DatabaseData:
    """The real thing: reads from PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._trades = TradeRepository(pool)
        self._prices = PriceRepository(pool)

    async def trades(
        self, *, exchange: Exchange | None = None, symbol: str | None = None
    ) -> list[Trade]:
        return await self._trades.list_trades(exchange=exchange, symbol=symbol)

    async def latest_price(self, exchange: Exchange, symbol: str) -> PriceTick | None:
        return await self._prices.latest(exchange, symbol)


class StaticData:
    """Fixed in-memory data, for tests and evaluations. Same behaviour, no database."""

    def __init__(self, trades: Iterable[Trade] = (), prices: Iterable[PriceTick] = ()) -> None:
        self._trades = sorted(trades, key=lambda t: (t.executed_at, t.trade_id))
        self._prices: dict[tuple[Exchange, str], PriceTick] = {}
        for tick in prices:
            key = (tick.exchange, tick.symbol)
            current = self._prices.get(key)
            if current is None or tick.exchange_time >= current.exchange_time:
                self._prices[key] = tick

    async def trades(
        self, *, exchange: Exchange | None = None, symbol: str | None = None
    ) -> list[Trade]:
        return [
            trade
            for trade in self._trades
            if (exchange is None or trade.exchange is exchange)
            and (symbol is None or trade.symbol == symbol)
        ]

    async def latest_price(self, exchange: Exchange, symbol: str) -> PriceTick | None:
        return self._prices.get((exchange, symbol))