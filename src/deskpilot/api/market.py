import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any, Protocol

import asyncpg

from deskpilot.agent.tools.common import amount, iso
from deskpilot.analytics import PriceBoard
from deskpilot.models import PriceTick
from deskpilot.storage import PriceRepository

logger = logging.getLogger(__name__)


class MarketSource(Protocol):
    async def latest_ticks(self, within: timedelta) -> list[PriceTick]: ...


class DatabaseMarketSource:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._prices = PriceRepository(pool)

    async def latest_ticks(self, within: timedelta) -> list[PriceTick]:
        return await self._prices.latest_all(within)


def market_snapshot(board: PriceBoard) -> dict[str, Any]:
    """Everything the dashboard shows about prices. Numbers are exact text, never floats."""
    now = board.now()
    prices = []
    for tick in sorted(board.ticks(), key=lambda t: (t.symbol, t.exchange.value)):
        age = (now - tick.received_time).total_seconds()
        prices.append(
            {
                "exchange": tick.exchange.value,
                "symbol": tick.symbol,
                "price": amount(tick.price),
                "time": iso(tick.exchange_time),
                "age_seconds": int(max(0, age)),
                "fresh": age <= board.max_age,
            }
        )
    spreads = [
        {
            "symbol": spread.symbol,
            "high": {"exchange": spread.high.exchange.value, "price": amount(spread.high.price)},
            "low": {"exchange": spread.low.exchange.value, "price": amount(spread.low.price)},
            "amount": amount(spread.amount),
            "percent": format(spread.percent.quantize(Decimal("0.0001")), "f"),
        }
        for spread in board.spreads()
    ]
    return {
        "time": iso(now),
        "max_age_seconds": board.max_age,
        "prices": prices,
        "spreads": spreads,
    }


async def run_market_poller(
    source: MarketSource,
    board: PriceBoard,
    *,
    interval: float = 1.0,
    within: timedelta = timedelta(minutes=5),
    max_cycles: int | None = None,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> None:
    """Copy the newest prices from the database into the board, again and again.

    Database trouble is logged and retried. Anything else is a bug and stops the poller
    (the health endpoint reports that).
    """
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        try:
            for tick in await source.latest_ticks(within):
                await board.on_tick(tick)
        except (OSError, asyncpg.PostgresConnectionError, asyncpg.CannotConnectNowError) as error:
            logger.warning("market poll failed (%s: %s)", type(error).__name__, error)
        if max_cycles is not None and cycle >= max_cycles:
            break
        await sleep(interval)


async def market_events(
    board: PriceBoard, *, interval: float, limit: int | None = None
) -> AsyncIterator[str]:
    """Server-Sent Events: a retry hint, then a market snapshot every `interval` seconds."""
    yield "retry: 3000\n\n"
    sent = 0
    while limit is None or sent < limit:
        yield f"event: market\ndata: {json.dumps(market_snapshot(board))}\n\n"
        sent += 1
        if limit is not None and sent >= limit:
            break
        await asyncio.sleep(interval)
