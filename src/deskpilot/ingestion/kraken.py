import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from pydantic import TypeAdapter
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.ingestion.base import BaseFeed, RawMessage, TickHandler
from deskpilot.models import Exchange, PriceTick, Symbol

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"

_check_symbol = TypeAdapter(Symbol)


def _parse_time(value: object) -> datetime:
    """Kraken sends times as text like 2026-01-01T12:00:00.123456Z."""
    if not isinstance(value, str):
        raise ValueError(f"time must be text, got {value!r}")
    return datetime.fromisoformat(value)  # a time without timezone is rejected by PriceTick


class KrakenFeed(BaseFeed):
    """Live trade prices from Kraken's public WebSocket (API v2)."""

    exchange = Exchange.KRAKEN
    retry_on = (*BaseFeed.retry_on, WebSocketException)

    def __init__(
        self,
        symbols: Sequence[str],
        on_tick: TickHandler,
        *,
        url: str = KRAKEN_WS_URL,
        backoff: BackoffPolicy | None = None,
        stale_after: float = 30.0,
    ) -> None:
        super().__init__(on_tick, backoff=backoff, stale_after=stale_after)
        if not symbols:
            raise ValueError("at least one symbol is required")

        # Kraken v2 already writes symbols like BTC/USDT, the same as our format.
        # dict.fromkeys removes duplicates and keeps the order.
        self._symbols = tuple(dict.fromkeys(_check_symbol.validate_python(s) for s in symbols))
        self.url = url
        self.subscribe_message = json.dumps(
            {
                "method": "subscribe",
                "params": {
                    "channel": "trade",
                    "symbol": list(self._symbols),
                    "snapshot": False,  # we only want live trades, not the last 50
                },
            }
        )

    @asynccontextmanager
    async def connect(self):
        async with ws_connect(self.url) as connection:
            # Every new connection must subscribe again, including after a reconnect.
            await connection.send(self.subscribe_message)
            yield connection

    def parse(self, raw: RawMessage) -> list[PriceTick]:
        message = json.loads(raw, parse_float=Decimal)  # bad JSON raises ValueError
        if not isinstance(message, dict):
            raise ValueError("message is not a JSON object")

        # A refused subscription must be visible, otherwise we would wait forever.
        if message.get("method") == "subscribe" and message.get("success") is False:
            raise ValueError(f"subscription failed: {message.get('error')}")

        # Heartbeats, status, pong, successful-subscribe replies and the
        # initial snapshot are all "nothing to do".
        if message.get("channel") != "trade" or message.get("type") != "update":
            return []

        items = message.get("data")
        if not isinstance(items, list):
            raise ValueError("trade data is not a list")

        # All or nothing: one unreadable trade rejects the whole batch.
        ticks = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("trade is not a JSON object")
            symbol = item.get("symbol")
            if symbol not in self._symbols:
                raise ValueError(f"unexpected symbol {symbol!r}")
            ticks.append(
                PriceTick(
                    exchange=Exchange.KRAKEN,
                    symbol=symbol,
                    price=item.get("price"),
                    exchange_time=_parse_time(item.get("timestamp")),
                )
            )
        return ticks
