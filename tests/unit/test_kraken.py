import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.ingestion import KrakenFeed
from deskpilot.models import Exchange

TRADE_TIME = "2026-01-01T12:00:00.123456Z"


async def ignore(tick):
    pass


def make_feed():
    return KrakenFeed(["BTC/USDT", "ETH/USDT"], ignore)


def trade(**overrides):
    item = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "price": 60000.1,
        "qty": 0.002,
        "ord_type": "market",
        "trade_id": 4665846,
        "timestamp": TRADE_TIME,
    }
    item.update(overrides)
    return item


def update(*items):
    return json.dumps({"channel": "trade", "type": "update", "data": list(items)})


def test_parses_a_trade_update():
    [tick] = make_feed().parse(update(trade()))
    assert tick.exchange is Exchange.KRAKEN
    assert tick.symbol == "BTC/USDT"
    assert tick.price == Decimal("60000.1")
    assert tick.exchange_time == datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)


def test_parses_bytes():
    [tick] = make_feed().parse(update(trade(symbol="ETH/USDT", price=3000.5)).encode())
    assert tick.symbol == "ETH/USDT"
    assert tick.price == Decimal("3000.5")


def test_json_number_keeps_every_digit():
    raw = (
        '{"channel":"trade","type":"update","data":[{"symbol":"BTC/USDT",'
        f'"price":0.12345678901234567890,"timestamp":"{TRADE_TIME}"}}]}}'
    )
    [tick] = make_feed().parse(raw)
    assert tick.price == Decimal("0.12345678901234567890")


def test_a_batch_of_trades_becomes_several_ticks_in_order():
    ticks = make_feed().parse(update(trade(price=100.5), trade(symbol="ETH/USDT", price=200.25)))
    assert [(t.symbol, t.price) for t in ticks] == [
        ("BTC/USDT", Decimal("100.5")),
        ("ETH/USDT", Decimal("200.25")),
    ]


@pytest.mark.parametrize(
    "message",
    [
        {"channel": "heartbeat"},
        {"channel": "status", "type": "update", "data": [{"system": "online"}]},
        {"method": "pong", "req_id": 1},
        {
            "method": "subscribe",
            "result": {"channel": "trade", "symbol": "BTC/USDT", "snapshot": False},
            "success": True,
        },
        {"channel": "trade", "type": "snapshot", "data": [trade()]},
        {"channel": "ticker", "type": "update", "data": []},
    ],
)
def test_messages_that_are_not_live_trades_are_ignored(message):
    assert make_feed().parse(json.dumps(message)) == []


def test_a_refused_subscription_is_reported():
    refused = {
        "method": "subscribe",
        "error": "Currency pair not supported BTC/FOO",
        "success": False,
    }
    with pytest.raises(ValueError, match="subscription failed"):
        make_feed().parse(json.dumps(refused))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        '"text"',
        json.dumps({"channel": "trade", "type": "update", "data": "oops"}),
        json.dumps({"channel": "trade", "type": "update", "data": ["oops"]}),
        update(trade(symbol="DOGE/USDT")),
        update(trade(symbol=["BTC/USDT"])),
        update(trade(symbol=None)),
        update(trade(price="abc")),
        update(trade(price="NaN")),
        update(trade(price=0)),
        update(trade(price=None)),
        update(trade(timestamp="yesterday")),
        update(trade(timestamp=12345)),
        update(trade(timestamp=None)),
        update(trade(timestamp="2026-01-01T12:00:00")),  # no timezone
    ],
)
def test_unreadable_messages_raise_value_error(raw):
    with pytest.raises(ValueError):
        make_feed().parse(raw)


def test_one_bad_trade_rejects_the_whole_batch():
    with pytest.raises(ValueError):
        make_feed().parse(update(trade(), trade(price=0)))


def test_subscribe_message_asks_for_live_trades_only():
    assert json.loads(make_feed().subscribe_message) == {
        "method": "subscribe",
        "params": {
            "channel": "trade",
            "symbol": ["BTC/USDT", "ETH/USDT"],
            "snapshot": False,
        },
    }


def test_duplicate_symbols_are_subscribed_once():
    feed = KrakenFeed(["BTC/USDT", "BTC/USDT"], ignore)
    assert json.loads(feed.subscribe_message)["params"]["symbol"] == ["BTC/USDT"]


@pytest.mark.parametrize("symbols", [[], ["BTCUSDT"], ["btc/usdt"]])
def test_bad_symbol_list_is_rejected(symbols):
    with pytest.raises(ValueError):
        KrakenFeed(symbols, ignore)
