from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from deskpilot.recon.rules import BreakKind, Tolerances, compare_trades

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_identical_trades_have_no_breaks(make_trade):
    assert compare_trades(make_trade(), make_trade()) == []


def test_rahims_case_a_quantity_that_is_off_by_a_fee(make_trade):
    [found] = compare_trades(make_trade(quantity="2"), make_trade(quantity="1.998"))
    assert found.kind is BreakKind.QUANTITY_MISMATCH
    assert (found.ledger_value, found.statement_value) == ("2", "1.998")
    assert found.difference == Decimal("-0.002")
    assert "ledger 2, statement 1.998" in found.detail
    assert "-0.002" in found.detail
    assert (found.exchange.value, found.trade_id, found.executed_at) == ("binance", "T-1", T0)


def test_numbers_equal_in_value_are_not_a_break(make_trade):
    assert compare_trades(make_trade(quantity="2.0"), make_trade(quantity="2.00")) == []


def test_a_different_price(make_trade):
    [found] = compare_trades(make_trade(price="60000"), make_trade(price="60001"))
    assert found.kind is BreakKind.PRICE_MISMATCH
    assert found.difference == Decimal("1")


def test_a_different_coin_pair(make_trade):
    [found] = compare_trades(make_trade(), make_trade(symbol="ETH/USDT"))
    assert found.kind is BreakKind.SYMBOL_MISMATCH
    assert (found.ledger_value, found.statement_value) == ("BTC/USDT", "ETH/USDT")
    assert found.difference is None


def test_a_different_side(make_trade):
    [found] = compare_trades(make_trade(side="buy"), make_trade(side="sell"))
    assert found.kind is BreakKind.SIDE_MISMATCH
    assert (found.ledger_value, found.statement_value) == ("buy", "sell")


def test_a_different_fee_amount(make_trade):
    [found] = compare_trades(make_trade(fee="0.002"), make_trade(fee="0.003"))
    assert found.kind is BreakKind.FEE_MISMATCH
    assert (found.ledger_value, found.statement_value) == ("0.002 BTC", "0.003 BTC")
    assert found.difference == Decimal("0.001")


def test_the_same_fee_in_a_different_currency(make_trade):
    ledger = make_trade(fee="0.002", fee_asset="BTC")
    statement = make_trade(fee="0.002", fee_asset="BNB")
    [found] = compare_trades(ledger, statement)
    assert found.kind is BreakKind.FEE_MISMATCH
    assert found.difference is None  # amounts in different currencies cannot be subtracted


def test_the_fee_currency_is_compared_ignoring_case(make_trade):
    assert compare_trades(make_trade(fee_asset="BTC"), make_trade(fee_asset="btc")) == []


def test_zero_fees_ignore_the_currency(make_trade):
    ledger = make_trade(fee="0", fee_asset=None)
    statement = make_trade(fee="0", fee_asset="BNB")
    assert compare_trades(ledger, statement) == []


def test_a_fee_only_the_statement_knows_about(make_trade):
    ledger = make_trade(fee="0", fee_asset=None)
    statement = make_trade(fee="0.5", fee_asset="USDT")
    [found] = compare_trades(ledger, statement)
    assert found.kind is BreakKind.FEE_MISMATCH
    assert (found.ledger_value, found.statement_value) == ("0", "0.5 USDT")
    assert found.difference == Decimal("0.5")


def test_small_time_differences_are_allowed(make_trade):
    shifted = make_trade(executed_at=T0 + timedelta(seconds=1))  # exactly the tolerance
    assert compare_trades(make_trade(), shifted) == []


def test_a_bigger_time_difference_is_a_break(make_trade):
    [found] = compare_trades(make_trade(), make_trade(executed_at=T0 + timedelta(seconds=2)))
    assert found.kind is BreakKind.TIME_DRIFT
    assert found.difference == Decimal("2")


def test_time_drift_is_reported_in_both_directions(make_trade):
    [found] = compare_trades(make_trade(), make_trade(executed_at=T0 - timedelta(seconds=3)))
    assert found.difference == Decimal("-3")


def test_a_wider_time_tolerance_can_be_given(make_trade):
    late = make_trade(executed_at=T0 + timedelta(seconds=5))
    assert compare_trades(make_trade(), late, Tolerances(timedelta(seconds=10))) == []


def test_several_differences_give_several_breaks_in_a_fixed_order(make_trade):
    statement = make_trade(
        quantity="1.998", fee="0.5", executed_at=T0 + timedelta(seconds=30), price="60001"
    )
    kinds = [found.kind for found in compare_trades(make_trade(), statement)]
    assert kinds == [
        BreakKind.QUANTITY_MISMATCH,
        BreakKind.PRICE_MISMATCH,
        BreakKind.FEE_MISMATCH,
        BreakKind.TIME_DRIFT,
    ]


def test_a_negative_tolerance_is_refused():
    with pytest.raises(ValueError):
        Tolerances(timedelta(seconds=-1))
