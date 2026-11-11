import json
import re
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.ingestion.base import BaseFeed, RawMessage, TickHandler
from deskpilot.models import Exchange, PriceTick

BINANCE_WS_URL = "wss://stream.binance.com:9443"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SYMBOL = re.compile(r"[A-Z0-9]+/[A-Z0-9]+")


def _from_millis(value: object) -> datetime:
    """Binance sends times as whole milliseconds since 1970."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"time must be whole milliseconds, got {value!r}")
    try:
        return _EPOCH + timedelta(milliseconds=value)
    except OverflowError:
        raise ValueError(f"time out of range: {value!r}") from None


class BinanceFeed(BaseFeed):
    """Live trade prices from Binance's public WebSocket."""

    exchange = Exchange.BINANCE
    # also retry on the websocket library's own connection errors
    retry_on = (*BaseFeed.retry_on, WebSocketException)

    def __init__(
        self,
        symbols: Sequence[str],
        on_tick: TickHandler,
        *,
        base_url: str = BINANCE_WS_URL,
        backoff: BackoffPolicy | None = None,
        stale_after: float = 30.0,
    ) -> None:
        super().__init__(on_tick, backoff=backoff, stale_after=stale_after)
        if not symbols:
            raise ValueError("at least one symbol is required")
        for symbol in symbols:
            if not _SYMBOL.fullmatch(symbol):
                raise ValueError(f"symbol must look like BTC/USDT, got {symbol!r}")

        # Binance name -> our name, e.g. "BTCUSDT" -> "BTC/USDT"
        self._symbol_map = {symbol.replace("/", ""): symbol for symbol in symbols}
        streams = "/".join(f"{name.lower()}@trade" for name in self._symbol_map)
        self.url = f"{base_url}/stream?streams={streams}"

    @asynccontextmanager
    async def connect(self):
        async with ws_connect(self.url) as connection:
            yield connection

    def parse(self, raw: RawMessage) -> list[PriceTick]:
        message = json.loads(raw, parse_float=Decimal)  # bad JSON raises ValueError
        if not isinstance(message, dict):
            raise ValueError("message is not a JSON object")

        # Several streams arrive wrapped as {"stream": "...", "data": {...}}
        data = message["data"] if "stream" in message and "data" in message else message
        if not isinstance(data, dict):
            raise ValueError("message data is not a JSON object")

        if data.get("e") != "trade":
            return []  # e.g. the "subscribed" confirmation: nothing to do

        native = data.get("s")
        symbol = self._symbol_map.get(native) if isinstance(native, str) else None
        if symbol is None:
            raise ValueError(f"unexpected symbol {native!r}")

        return [
            PriceTick(
                exchange=Exchange.BINANCE,
                symbol=symbol,
                price=data.get("p"),
                exchange_time=_from_millis(data.get("T")),
            )
        ]
