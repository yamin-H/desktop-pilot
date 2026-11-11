from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from deskpilot.models import Side, Trade


def make_trade(**overrides):
    data = {
        "exchange": "binance",
        "trade_id": "T-1001",
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": "0.002",
        "price": "60000.10",
        "executed_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }
    data.update(overrides)
    return Trade(**data)


def test_valid_trade_with_defaults():
    trade = make_trade()
    assert trade.side is Side.BUY
    assert trade.fee == Decimal("0")
    assert trade.fee_asset is None


def test_notional_is_exact():
    assert make_trade().notional == Decimal("120.0002")


def test_dedupe_key_uses_exchange_and_trade_id():
    assert make_trade().dedupe_key == ("binance", "T-1001")


def test_same_trade_seen_twice_is_equal():
    assert make_trade() == make_trade()


def test_fee_can_be_given():
    trade = make_trade(fee="0.00000200", fee_asset="BTC")
    assert trade.fee == Decimal("0.000002")
    assert trade.fee_asset == "BTC"


@pytest.mark.parametrize("field", ["quantity", "price"])
@pytest.mark.parametrize("bad", ["0", "-1", 1.5])
def test_bad_quantity_or_price_is_rejected(field, bad):
    with pytest.raises(ValidationError):
        make_trade(**{field: bad})


def test_negative_fee_is_rejected():
    with pytest.raises(ValidationError):
        make_trade(fee="-0.1")


def test_bad_side_is_rejected():
    with pytest.raises(ValidationError):
        make_trade(side="hold")


def test_empty_trade_id_is_rejected():
    with pytest.raises(ValidationError):
        make_trade(trade_id="")


def test_trade_cannot_be_modified():
    trade = make_trade()
    with pytest.raises(ValidationError):
        trade.quantity = Decimal("5")
