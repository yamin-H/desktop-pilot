import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.ingestion import BinanceFeed
from deskpilot.models import Exchange

TRADE_TIME_MS = 1767268800123  # 2026-01-01 12:00:00.123 UTC


async def ignore(tick):
    pass


def make_feed():
    return BinanceFeed(["BTC/USDT", "ETH/USDT"], ignore)


def trade_event(**overrides):
    event = {
        "e": "trade",
        "E": TRADE_TIME_MS + 1,
        "s": "BTCUSDT",
        "t": 12345,
        "p": "60000.10000000",
        "q": "0.00200000",
        "T": TRADE_TIME_MS,
        "m": True,
        "M": True,
    }
    event.update(overrides)
    return event


def combined(event):
    return json.dumps({"stream": "btcusdt@trade", "data": event})


def test_parses_a_trade_from_the_combined_stream():
    [tick] = make_feed().parse(combined(trade_event()))
    assert tick.exchange is Exchange.BINANCE
    assert tick.symbol == "BTC/USDT"
    assert tick.price == Decimal("60000.10")
    assert tick.exchange_time == datetime(2026, 1, 1, 12, 0, 0, 123000, tzinfo=UTC)


def test_parses_a_plain_trade_sent_as_bytes():
    raw = json.dumps(trade_event(s="ETHUSDT", p="3000.5")).encode()
    [tick] = make_feed().parse(raw)
    assert tick.symbol == "ETH/USDT"
    assert tick.price == Decimal("3000.5")


def test_messages_that_are_not_trades_are_ignored():
    feed = make_feed()
    assert feed.parse('{"result": null, "id": 1}') == []
    assert feed.parse(json.dumps({"e": "aggTrade"})) == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        '"text"',
        combined("oops"),
        json.dumps({"e": "trade"}),
        json.dumps(trade_event(s="DOGEUSDT")),
        json.dumps(trade_event(s=["BTCUSDT"])),
        json.dumps(trade_event(p="abc")),
        json.dumps(trade_event(p="0")),
        json.dumps(trade_event(p=None)),
        json.dumps(trade_event(T="soon")),
        json.dumps(trade_event(T=10**30)),
    ],
)
def test_unreadable_messages_raise_value_error(raw):
    with pytest.raises(ValueError):
        make_feed().parse(raw)


def test_url_lists_every_stream():
    expected = "wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade"
    assert make_feed().url == expected


@pytest.mark.parametrize("symbols", [[], ["BTCUSDT"], ["btc/usdt"]])
def test_bad_symbol_list_is_rejected(symbols):
    with pytest.raises(ValueError):
        BinanceFeed(symbols, ignore)
