from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.bus.codec import decode_tick, encode_tick
from deskpilot.models import PriceTick

TICK = PriceTick(
    exchange="binance", symbol="BTC/USDT", price="60000.10",
    exchange_time=datetime(2026, 11, 12, 10, 0, 1, 123000, tzinfo=UTC),
    received_time=datetime(2026, 11, 12, 10, 0, 1, 130000, tzinfo=UTC),
)


def test_a_tick_survives_the_trip_unchanged():
    assert decode_tick(encode_tick(TICK)) == TICK


def test_the_fields_are_plain_text_and_prices_keep_every_digit():
    fields = encode_tick(TICK)
    assert all(isinstance(value, str) for value in fields.values())
    assert fields["price"] == "60000.10"
    tiny = PriceTick(exchange="kraken", symbol="ETH/USDT", price="0.00000001",
                     exchange_time=TICK.exchange_time)
    assert encode_tick(tiny)["price"] == "0.00000001"  # not 1E-8
    assert decode_tick(encode_tick(tiny)).price == Decimal("0.00000001")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: None,
        lambda f: {},
        lambda f: {"exchange": "binance"},
        lambda f: {**f, "colour": "red"},
        lambda f: {**f, "price": "abc"},
        lambda f: {**f, "price": "0"},
        lambda f: {**f, "exchange": "ftx"},
        lambda f: {**f, "exchange_time": "2026-11-12T10:00:00"},  # no timezone
        lambda f: {**f, "exchange_time": "yesterday"},
    ],
)
def test_anything_that_is_not_one_valid_tick_is_a_value_error(mutate):
    with pytest.raises(ValueError):
        decode_tick(mutate(encode_tick(TICK)))