from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from deskpilot.analytics import PriceBoard
from deskpilot.models import Exchange, PriceTick

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def tick(exchange, price, *, symbol="BTC/USDT", age=0, at=0):
    """`age` = seconds since we received it. `at` = seconds after NOW on the exchange's clock."""
    return PriceTick(
        exchange=exchange,
        symbol=symbol,
        price=price,
        exchange_time=NOW + timedelta(seconds=at),
        received_time=NOW - timedelta(seconds=age),
    )


def make_board(max_age=30):
    return PriceBoard(max_age=max_age, clock=lambda: NOW)


async def test_latest_is_none_before_any_tick():
    assert make_board().latest(Exchange.BINANCE, "BTC/USDT") is None


async def test_latest_returns_the_last_tick():
    board = make_board()
    first = tick(Exchange.BINANCE, "100", at=1)
    second = tick(Exchange.BINANCE, "101", at=2)
    await board.on_tick(first)
    await board.on_tick(second)
    assert board.latest(Exchange.BINANCE, "BTC/USDT") == second


async def test_the_board_exposes_every_stored_tick_even_stale_ones():
    board = make_board(max_age=30)
    await board.on_tick(tick(Exchange.BINANCE, "100"))
    await board.on_tick(tick(Exchange.KRAKEN, "99", age=100))
    assert {t.exchange for t in board.ticks()} == {Exchange.BINANCE, Exchange.KRAKEN}


def test_the_board_exposes_its_settings():
    board = PriceBoard(max_age=12, clock=lambda: NOW)
    assert (board.max_age, board.now()) == (12, NOW)


async def test_an_older_tick_does_not_replace_a_newer_one():
    board = make_board()
    newer = tick(Exchange.BINANCE, "101", at=5)
    await board.on_tick(newer)
    await board.on_tick(tick(Exchange.BINANCE, "100", at=1))
    assert board.latest(Exchange.BINANCE, "BTC/USDT") == newer


async def test_spread_between_two_exchanges():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "100.50"))
    await board.on_tick(tick(Exchange.KRAKEN, "100.00"))
    [spread] = board.spreads()
    assert spread.symbol == "BTC/USDT"
    assert spread.high.exchange is Exchange.BINANCE
    assert spread.low.exchange is Exchange.KRAKEN
    assert spread.amount == Decimal("0.50")
    assert spread.percent == Decimal("0.5")


async def test_spread_does_not_depend_on_arrival_order():
    board = make_board()
    await board.on_tick(tick(Exchange.KRAKEN, "100.00"))
    await board.on_tick(tick(Exchange.BINANCE, "100.50"))
    [spread] = board.spreads()
    assert spread.high.exchange is Exchange.BINANCE


async def test_spread_amount_is_exact():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "60000.3"))
    await board.on_tick(tick(Exchange.KRAKEN, "60000.1"))
    assert board.spreads()[0].amount == Decimal("0.2")


async def test_equal_prices_give_zero_gap_between_two_different_exchanges():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "100"))
    await board.on_tick(tick(Exchange.KRAKEN, "100"))
    [spread] = board.spreads()
    assert spread.amount == 0
    assert spread.percent == 0
    assert spread.high.exchange is not spread.low.exchange


async def test_one_exchange_alone_gives_no_spread():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "100"))
    assert board.spreads() == []


async def test_different_coin_pairs_are_never_compared():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "100", symbol="BTC/USDT"))
    await board.on_tick(tick(Exchange.KRAKEN, "3000", symbol="ETH/USDT"))
    assert board.spreads() == []


async def test_each_coin_pair_gets_its_own_spread_sorted_by_name():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "3001", symbol="ETH/USDT"))
    await board.on_tick(tick(Exchange.KRAKEN, "3000", symbol="ETH/USDT"))
    await board.on_tick(tick(Exchange.BINANCE, "101", symbol="BTC/USDT"))
    await board.on_tick(tick(Exchange.KRAKEN, "100", symbol="BTC/USDT"))
    assert [s.symbol for s in board.spreads()] == ["BTC/USDT", "ETH/USDT"]


async def test_a_stale_price_is_left_out():
    board = make_board(max_age=30)
    await board.on_tick(tick(Exchange.BINANCE, "100"))
    await board.on_tick(tick(Exchange.KRAKEN, "99", age=31))
    assert board.spreads() == []


async def test_a_price_exactly_at_the_age_limit_is_still_used():
    board = make_board(max_age=30)
    await board.on_tick(tick(Exchange.BINANCE, "100"))
    await board.on_tick(tick(Exchange.KRAKEN, "99", age=30))
    assert len(board.spreads()) == 1


async def test_with_three_exchanges_the_widest_gap_is_reported():
    board = make_board()
    await board.on_tick(tick(Exchange.BINANCE, "101"))
    await board.on_tick(tick(Exchange.KRAKEN, "100"))
    await board.on_tick(tick(Exchange.BYBIT, "99"))
    [spread] = board.spreads()
    assert spread.high.exchange is Exchange.BINANCE
    assert spread.low.exchange is Exchange.BYBIT
    assert spread.amount == Decimal("2")


@pytest.mark.parametrize("bad", [0, -1])
def test_max_age_must_be_positive(bad):
    with pytest.raises(ValueError):
        PriceBoard(max_age=bad)
