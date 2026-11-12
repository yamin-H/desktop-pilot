from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest

from deskpilot.analytics import calculate_positions, totals_by_quote, value_positions
from deskpilot.models import Trade

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
CENTS = Decimal("0.01")
_numbers = count(1)


def make_trade(
    side,
    quantity,
    price,
    *,
    fee="0",
    fee_asset=None,
    at=None,
    trade_id=None,
    exchange="binance",
    symbol="BTC/USDT",
):
    """Every new trade is one minute later than the previous one, unless `at` is given."""
    number = next(_numbers)
    return Trade(
        exchange=exchange,
        trade_id=trade_id or f"T-{number:06d}",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        fee_asset=fee_asset,
        executed_at=T0 + timedelta(minutes=number if at is None else at),
    )


def buy(quantity, price, **kwargs):
    return make_trade("buy", quantity, price, **kwargs)


def sell(quantity, price, **kwargs):
    return make_trade("sell", quantity, price, **kwargs)


def positions_of(*trades):
    return calculate_positions(trades)


def test_unrealized_pnl_is_value_now_minus_cost():
    [value] = value_positions(positions_of(buy("2", "100")), {"BTC/USDT": "110"})
    assert value.mark_price == Decimal("110")
    assert value.market_value == Decimal("220")
    assert value.unrealized_pnl == Decimal("20")
    assert value.total_pnl == Decimal("20")


def test_the_total_adds_realized_and_unrealized():
    positions = positions_of(buy("2", "100"), sell("1", "120"))
    [value] = value_positions(positions, {"BTC/USDT": "130"})
    assert value.position.realized_pnl == Decimal("20")
    assert value.unrealized_pnl == Decimal("30")  # 1 coin held: worth 130, cost 100
    assert value.total_pnl == Decimal("50")


def test_a_fall_in_price_gives_a_negative_unrealized_pnl():
    [value] = value_positions(positions_of(buy("1", "100")), {"BTC/USDT": "90"})
    assert value.unrealized_pnl == Decimal("-10")


def test_without_a_price_the_unrealized_pnl_is_unknown_not_zero():
    [value] = value_positions(positions_of(buy("1", "100")), {})
    assert value.mark_price is None
    assert value.market_value is None
    assert value.unrealized_pnl is None
    assert value.total_pnl is None


def test_a_closed_position_needs_no_price():
    [value] = value_positions(positions_of(buy("1", "100"), sell("1", "110")), {})
    assert value.market_value == 0
    assert value.unrealized_pnl == 0
    assert value.total_pnl == Decimal("10")


def test_prices_for_other_symbols_are_ignored():
    [value] = value_positions(positions_of(buy("1", "100")), {"ETH/USDT": "3000"})
    assert value.mark_price is None


@pytest.mark.parametrize("price", ["110", 110, Decimal("110")])
def test_prices_can_be_text_ints_or_decimals(price):
    [value] = value_positions(positions_of(buy("1", "100")), {"BTC/USDT": price})
    assert value.unrealized_pnl == Decimal("10")


@pytest.mark.parametrize("bad", [100.5, "0", "-5", "abc"])
def test_bad_prices_are_refused(bad):
    with pytest.raises(ValueError):
        value_positions([], {"BTC/USDT": bad})


def test_totals_for_one_currency():
    positions = positions_of(buy("2", "100"), sell("1", "120"))
    [totals] = totals_by_quote(value_positions(positions, {"BTC/USDT": "130"}))
    assert totals.quote == "USDT"
    assert totals.realized_pnl == Decimal("20")
    assert totals.unrealized_pnl == Decimal("30")
    assert totals.total_pnl == Decimal("50")
    assert totals.missing_marks == ()


def test_different_quote_currencies_are_never_added_together():
    positions = positions_of(
        buy("1", "100"),
        sell("1", "110"),
        buy("1", "200", exchange="kraken", symbol="BTC/USD"),
        sell("1", "230", exchange="kraken", symbol="BTC/USD"),
    )
    totals = totals_by_quote(value_positions(positions, {}))
    assert [(t.quote, t.realized_pnl) for t in totals] == [
        ("USD", Decimal("30")),
        ("USDT", Decimal("10")),
    ]


def test_one_missing_price_makes_the_unrealized_total_unknown():
    positions = positions_of(
        buy("2", "100"),
        sell("1", "120"),
        buy("1", "3000", symbol="ETH/USDT"),
    )
    [totals] = totals_by_quote(value_positions(positions, {"BTC/USDT": "130"}))
    assert totals.realized_pnl == Decimal("20")  # still known
    assert totals.unrealized_pnl is None
    assert totals.total_pnl is None
    assert totals.missing_marks == ("ETH/USDT",)


def test_a_symbol_missing_on_two_exchanges_is_listed_once():
    positions = positions_of(
        buy("1", "100", exchange="binance"), buy("1", "100", exchange="kraken")
    )
    [totals] = totals_by_quote(value_positions(positions, {}))
    assert totals.missing_marks == ("BTC/USDT",)


def test_no_positions_give_no_totals():
    assert totals_by_quote([]) == []


def test_the_paper_trades_give_the_hand_calculated_profit():
    paper = [
        buy("0.50", "60000", fee="0.0005", fee_asset="BTC", trade_id="PAPER-0001", at=0),
        buy("0.25", "61000", fee="15.25", fee_asset="USDT", trade_id="PAPER-0002", at=90),
        sell("0.40", "62500", fee="25.00", fee_asset="USDT", trade_id="PAPER-0003", at=255),
        buy(
            "5",
            "3000",
            fee="15.00",
            fee_asset="USDT",
            trade_id="PAPER-0004",
            at=20,
            exchange="kraken",
            symbol="ETH/USDT",
        ),
        sell(
            "2",
            "3100",
            fee="6.20",
            fee_asset="USDT",
            trade_id="PAPER-0005",
            at=405,
            exchange="kraken",
            symbol="ETH/USDT",
        ),
    ]
    values = value_positions(calculate_positions(paper), {"BTC/USDT": "63000", "ETH/USDT": "3050"})
    btc, eth = values

    # 0.3495 BTC x 63000 = 22018.50, cost 21107.68, so 910.82 on paper
    assert btc.market_value == Decimal("22018.5")
    assert btc.unrealized_pnl.quantize(CENTS) == Decimal("910.82")
    # An independent check: everything received + what we hold - everything spent
    assert btc.total_pnl.quantize(CENTS) == Decimal("1728.25")  # 24975 + 22018.50 - 45265.25

    # 3 ETH x 3050 = 9150, cost 9009, so 141 on paper
    assert eth.market_value == Decimal("9150")
    assert eth.unrealized_pnl == Decimal("141")

    [totals] = totals_by_quote(values)
    assert totals.realized_pnl.quantize(CENTS) == Decimal("1005.23")  # 817.43 + 187.80
    assert totals.unrealized_pnl.quantize(CENTS) == Decimal("1051.82")  # 910.82 + 141.00
    assert totals.total_pnl.quantize(CENTS) == Decimal("2057.05")
