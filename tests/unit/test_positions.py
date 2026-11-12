from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest

from deskpilot.analytics import (
    DuplicateTradeError,
    OversoldError,
    Position,
    UnsupportedFeeError,
    calculate_positions,
)
from deskpilot.models import Exchange, Trade

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
    """Build a trade. Unless `at` (minutes after T0) is given, every new trade is one
    minute later than the previous one, so trades happen in the order they are written."""
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


def one(trades) -> Position:
    [position] = calculate_positions(trades)
    return position


def test_no_trades_gives_no_positions():
    assert calculate_positions([]) == []


def test_a_single_buy():
    position = one([buy("1", "100")])
    assert position.quantity == Decimal("1")
    assert position.cost == Decimal("100")
    assert position.average_cost == Decimal("100")
    assert position.realized_pnl == 0
    assert position.realized_events == ()


def test_average_cost_is_the_weighted_average_of_the_buys():
    position = one([buy("2", "100"), buy("2", "200")])
    assert position.quantity == Decimal("4")
    assert position.cost == Decimal("600")
    assert position.average_cost == Decimal("150")


def test_a_partial_sale_realizes_profit_at_the_average_cost():
    position = one([buy("2", "100"), buy("2", "200"), sell("1", "180")])
    assert position.realized_pnl == Decimal("30")  # received 180, those coins cost 150
    assert position.quantity == Decimal("3")
    assert position.cost == Decimal("450")
    assert position.average_cost == Decimal("150")  # selling does not change the average


def test_a_loss_is_negative():
    assert one([buy("1", "100"), sell("1", "90")]).realized_pnl == Decimal("-10")


def test_selling_everything_leaves_nothing():
    position = one([buy("2", "100"), sell("2", "110")])
    assert position.quantity == 0
    assert position.cost == 0
    assert position.average_cost is None
    assert position.realized_pnl == Decimal("20")


def test_closing_a_position_in_pieces_leaves_exactly_zero_cost():
    # 3 coins cost 4 in total (3 + a fee of 1), so one third is a repeating decimal
    position = one([buy("3", "1", fee="1", fee_asset="USDT"), sell("1", "1"), sell("2", "1")])
    assert position.quantity == 0
    assert position.cost == 0
    assert position.realized_pnl == Decimal("-1")  # received 3, spent 4: exact, no crumbs


def test_a_fee_in_the_quote_currency_raises_the_cost_of_a_buy():
    position = one([buy("1", "100", fee="1", fee_asset="USDT")])
    assert position.cost == Decimal("101")
    assert position.fees_quote == Decimal("1")


def test_a_fee_in_the_quote_currency_lowers_the_proceeds_of_a_sale():
    position = one([buy("1", "100"), sell("1", "110", fee="2", fee_asset="USDT")])
    assert position.realized_pnl == Decimal("8")  # received 108, cost 100


def test_a_fee_in_coins_on_a_buy_means_fewer_coins_for_the_same_money():
    position = one([buy("1", "100", fee="0.01", fee_asset="BTC")])
    assert position.quantity == Decimal("0.99")
    assert position.cost == Decimal("100")
    assert position.average_cost.quantize(Decimal("0.0001")) == Decimal("101.0101")
    assert position.fees_base == Decimal("0.01")


def test_a_fee_in_coins_on_a_sale_also_leaves_the_position():
    position = one([buy("2", "100"), sell("1", "110", fee="0.01", fee_asset="BTC")])
    # 1.01 coins left: they cost 200 * 1.01 / 2 = 101, and we received 110
    assert position.quantity == Decimal("0.99")
    assert position.cost == Decimal("99")
    assert position.realized_pnl == Decimal("9")


def test_the_fee_currency_is_matched_ignoring_case():
    assert one([buy("1", "100", fee="1", fee_asset="usdt")]).cost == Decimal("101")


def test_a_zero_fee_needs_no_known_currency():
    assert one([buy("1", "100", fee="0", fee_asset="BNB")]).cost == Decimal("100")


@pytest.mark.parametrize("asset", ["BNB", None])
def test_a_fee_in_an_unknown_currency_is_refused(asset):
    with pytest.raises(UnsupportedFeeError):
        calculate_positions([buy("1", "100", fee="0.5", fee_asset=asset)])


def test_a_coin_fee_that_eats_the_whole_purchase_is_refused():
    with pytest.raises(UnsupportedFeeError):
        calculate_positions([buy("1", "100", fee="1", fee_asset="BTC")])


def test_selling_coins_we_never_held_is_refused():
    with pytest.raises(OversoldError, match="binance/T-SELL"):
        calculate_positions([sell("1", "100", trade_id="T-SELL")])


def test_selling_more_than_we_hold_is_refused():
    with pytest.raises(OversoldError):
        calculate_positions([buy("1", "100"), sell("2", "100")])


def test_a_coin_fee_can_push_a_sale_over_what_we_hold():
    with pytest.raises(OversoldError):
        calculate_positions([buy("1", "100"), sell("1", "110", fee="0.01", fee_asset="BTC")])


def test_each_exchange_is_its_own_position():
    positions = calculate_positions(
        [buy("1", "100", exchange="kraken"), buy("2", "100", exchange="binance")]
    )
    assert [(p.exchange, p.quantity) for p in positions] == [
        (Exchange.BINANCE, Decimal("2")),
        (Exchange.KRAKEN, Decimal("1")),
    ]


def test_coins_held_on_one_exchange_cannot_be_sold_on_another():
    with pytest.raises(OversoldError):
        calculate_positions(
            [buy("1", "100", exchange="binance"), sell("1", "100", exchange="kraken")]
        )


def test_each_coin_pair_is_its_own_position_sorted_by_name():
    positions = calculate_positions([buy("1", "3000", symbol="ETH/USDT"), buy("1", "100")])
    assert [p.symbol for p in positions] == ["BTC/USDT", "ETH/USDT"]


def test_base_and_quote_come_from_the_symbol():
    position = one([buy("1", "100")])
    assert (position.base, position.quote) == ("BTC", "USDT")


def test_the_order_of_the_input_does_not_matter():
    trades = [buy("2", "100"), buy("2", "200"), sell("1", "180")]
    assert calculate_positions(list(reversed(trades))) == calculate_positions(trades)


def test_trades_at_the_same_instant_are_ordered_by_trade_id():
    trades = [sell("1", "110", trade_id="B", at=5), buy("1", "100", trade_id="A", at=5)]
    assert one(trades).realized_pnl == Decimal("10")


def test_a_sale_ordered_before_its_own_purchase_is_refused():
    trades = [buy("1", "100", trade_id="B", at=5), sell("1", "110", trade_id="A", at=5)]
    with pytest.raises(OversoldError):
        calculate_positions(trades)


def test_the_same_trade_given_twice_is_refused():
    trade = buy("1", "100")
    with pytest.raises(DuplicateTradeError):
        calculate_positions([trade, trade])


def test_every_sale_records_a_realized_event():
    sale = sell("1", "180", trade_id="S-1", at=50)
    position = one([buy("2", "100", at=10), buy("2", "200", at=20), sale])

    [event] = position.realized_events
    assert (event.exchange, event.trade_id, event.symbol) == (
        Exchange.BINANCE,
        "S-1",
        "BTC/USDT",
    )
    assert event.executed_at == sale.executed_at
    assert event.quantity == Decimal("1")
    assert event.proceeds == Decimal("180")
    assert event.cost == Decimal("150")
    assert event.pnl == Decimal("30")
    assert position.realized_pnl == sum(e.pnl for e in position.realized_events)


# Your five paper trades. Expected results, worked out by hand:
#
# Binance BTC/USDT
#   buy 0.50 @ 60000, fee 0.0005 BTC -> holds 0.4995, cost 30000
#   buy 0.25 @ 61000, fee 15.25 USDT -> holds 0.7495, cost 30000 + 15250 + 15.25 = 45265.25
#   sell 0.40 @ 62500, fee 25 USDT   -> those coins cost 45265.25 * 0.40 / 0.7495 = 24157.57
#                                       received 25000 - 25 = 24975, profit 817.43
#   left: 0.3495 BTC with cost 45265.25 - 24157.57 = 21107.68
# Kraken ETH/USDT
#   buy 5 @ 3000, fee 15 USDT        -> cost 15015
#   sell 2 @ 3100, fee 6.20 USDT     -> those coins cost 15015 * 2 / 5 = 6006
#                                       received 6200 - 6.20 = 6193.80, profit 187.80
#   left: 3 ETH with cost 9009
PAPER = [
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


def test_the_paper_trades_give_the_hand_calculated_positions():
    btc, eth = calculate_positions(PAPER)

    assert (btc.exchange, btc.symbol) == (Exchange.BINANCE, "BTC/USDT")
    assert btc.quantity == Decimal("0.3495")
    assert btc.cost.quantize(CENTS) == Decimal("21107.68")
    assert btc.realized_pnl.quantize(CENTS) == Decimal("817.43")

    assert (eth.exchange, eth.symbol) == (Exchange.KRAKEN, "ETH/USDT")
    assert eth.quantity == Decimal("3")
    assert eth.cost == Decimal("9009")
    assert eth.realized_pnl == Decimal("187.8")
