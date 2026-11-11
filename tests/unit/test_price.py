from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from deskpilot.models import Exchange, PriceTick

BD_TIME = timezone(timedelta(hours=6))


def make_tick(**overrides):
    data = {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "price": "60000.10",
        "exchange_time": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }
    data.update(overrides)
    return PriceTick(**data)


def test_valid_tick():
    tick = make_tick()
    assert tick.exchange is Exchange.BINANCE
    assert tick.price == Decimal("60000.10")


def test_time_is_converted_to_utc():
    tick = make_tick(exchange_time=datetime(2026, 1, 1, 12, 0, tzinfo=BD_TIME))
    assert tick.exchange_time == datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
    assert tick.exchange_time.utcoffset() == timedelta(0)


def test_naive_time_is_rejected():
    with pytest.raises(ValidationError):
        make_tick(exchange_time=datetime(2026, 1, 1, 12, 0))


def test_received_time_defaults_to_now_in_utc():
    before = datetime.now(UTC)
    tick = make_tick()
    assert before <= tick.received_time <= datetime.now(UTC)


@pytest.mark.parametrize("bad", ["BTCUSDT", "btc/usdt", "BTC-USDT", "XBT/"])
def test_bad_symbol_is_rejected(bad):
    with pytest.raises(ValidationError):
        make_tick(symbol=bad)


@pytest.mark.parametrize("bad", ["0", "-5", 60000.1])
def test_bad_price_is_rejected(bad):
    with pytest.raises(ValidationError):
        make_tick(price=bad)


def test_unknown_exchange_is_rejected():
    with pytest.raises(ValidationError):
        make_tick(exchange="some-random-exchange")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        make_tick(colour="red")


def test_tick_cannot_be_modified():
    tick = make_tick()
    with pytest.raises(ValidationError):
        tick.price = Decimal("1")
