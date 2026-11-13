"""Fixed data for the evaluation: made-up paper trades, prices and a fixed clock."""

from datetime import UTC, datetime, timedelta

from deskpilot.models import PriceTick, Trade

# "Now" for every evaluation run, so "today" and "yesterday" always mean the same days.
EVAL_NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)


def _at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


PAPER_TRADES: tuple[Trade, ...] = (
    Trade(
        exchange="binance",
        trade_id="PAPER-0001",
        symbol="BTC/USDT",
        side="buy",
        quantity="0.50",
        price="60000",
        fee="0.0005",
        fee_asset="BTC",
        executed_at=_at(10, 10, 0),
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
        executed_at=_at(10, 11, 30),
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
        executed_at=_at(10, 14, 15),
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
        executed_at=_at(10, 10, 20),
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
        executed_at=_at(10, 16, 45),
    ),
    Trade(
        exchange="bybit",
        trade_id="PAPER-0006",
        symbol="BTC/USDT",
        side="buy",
        quantity="0.20",
        price="63000",
        fee="12.60",
        fee_asset="USDT",
        executed_at=_at(11, 9, 0),
    ),
    Trade(
        exchange="bybit",
        trade_id="PAPER-0007",
        symbol="BTC/USDT",
        side="sell",
        quantity="0.10",
        price="64000",
        fee="6.40",
        fee_asset="USDT",
        executed_at=_at(11, 15, 30),
    ),
    Trade(
        exchange="kraken",
        trade_id="PAPER-0008",
        symbol="ETH/USDT",
        side="sell",
        quantity="1",
        price="3040",
        fee="3.04",
        fee_asset="USDT",
        executed_at=_at(12, 8, 30),
    ),
)

# Fresh recorded prices (one minute old at EVAL_NOW).
EVAL_PRICES: tuple[PriceTick, ...] = (
    PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price="63000",
        exchange_time=EVAL_NOW - timedelta(minutes=1),
    ),
    PriceTick(
        exchange="binance",
        symbol="ETH/USDT",
        price="3050",
        exchange_time=EVAL_NOW - timedelta(minutes=1),
    ),
)
