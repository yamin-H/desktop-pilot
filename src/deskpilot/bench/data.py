import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from deskpilot.models import PriceTick

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
_PAIRS = (
    ("binance", "BTC/USDT"),
    ("binance", "ETH/USDT"),
    ("kraken", "BTC/USDT"),
    ("kraken", "ETH/USDT"),
)


def _price(rng: random.Random, symbol: str) -> Decimal:
    low, high = (50_000, 70_000) if symbol.startswith("BTC") else (2_000, 4_000)
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def make_tick(index: int, rng: random.Random, *, received_time: datetime | None = None) -> PriceTick:
    """Tick number `index`. Every index gets its own exchange time, so no two ticks collide.

    Unless `received_time` is given, it is "now": the moment of creation, which is where
    latency measurements start.
    """
    exchange, symbol = _PAIRS[index % len(_PAIRS)]
    extra = {} if received_time is None else {"received_time": received_time}
    return PriceTick(
        exchange=exchange,
        symbol=symbol,
        price=_price(rng, symbol),
        exchange_time=BASE_TIME + timedelta(milliseconds=index),
        **extra,
    )


def make_ticks(count: int, seed: int = 1) -> list[PriceTick]:
    rng = random.Random(seed)
    return [make_tick(index, rng) for index in range(count)]


def binance_message(index: int, rng: random.Random) -> str:
    """A raw Binance trade-stream message, as our feed receives it."""
    btc = index % 2 == 0
    symbol = "BTCUSDT" if btc else "ETHUSDT"
    event = {
        "e": "trade",
        "s": symbol,
        "p": str(_price(rng, "BTC/USDT" if btc else "ETH/USDT")),
        "T": 1_767_225_600_000 + index,
    }
    return json.dumps({"stream": f"{symbol.lower()}@trade", "data": event})


def kraken_message(index: int, rng: random.Random) -> str:
    """A raw Kraken v2 trade update with one trade, as our feed receives it."""
    symbol = "BTC/USDT" if index % 2 == 0 else "ETH/USDT"
    stamp = (BASE_TIME + timedelta(milliseconds=index)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    item = {
        "symbol": symbol,
        "side": "buy",
        "price": float(_price(rng, symbol)),  # Kraken sends prices as JSON numbers
        "qty": 0.001,
        "ord_type": "market",
        "trade_id": index,
        "timestamp": stamp,
    }
    return json.dumps({"channel": "trade", "type": "update", "data": [item]})