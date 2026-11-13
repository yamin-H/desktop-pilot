import json
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from deskpilot.analytics import PriceBoard
from deskpilot.api.limits import RateLimiter
from deskpilot.api.market import market_events, market_snapshot, run_market_poller
from deskpilot.models import PriceTick

NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)


def tick(exchange, price, *, symbol="BTC/USDT", age=1):
    when = NOW - timedelta(seconds=age)
    return PriceTick(
        exchange=exchange, symbol=symbol, price=price, exchange_time=when, received_time=when
    )


def make_board():
    return PriceBoard(max_age=30, clock=lambda: NOW)


async def test_the_snapshot_lists_prices_and_the_gap_as_exact_text():
    board = make_board()
    await board.on_tick(tick("binance", "100.50", age=2))
    await board.on_tick(tick("kraken", "100.00", age=5))
    snapshot = market_snapshot(board)
    assert snapshot["time"] == "2026-11-12T10:15:00Z"
    assert snapshot["max_age_seconds"] == 30
    assert snapshot["prices"] == [
        {
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "price": "100.5",
            "time": "2026-11-12T10:14:58Z",
            "age_seconds": 2,
            "fresh": True,
        },
        {
            "exchange": "kraken",
            "symbol": "BTC/USDT",
            "price": "100",
            "time": "2026-11-12T10:14:55Z",
            "age_seconds": 5,
            "fresh": True,
        },
    ]
    assert snapshot["spreads"] == [
        {
            "symbol": "BTC/USDT",
            "high": {"exchange": "binance", "price": "100.5"},
            "low": {"exchange": "kraken", "price": "100"},
            "amount": "0.5",
            "percent": "0.5000",
        }
    ]


async def test_a_stale_price_is_shown_as_stale_and_left_out_of_the_gap():
    board = make_board()
    await board.on_tick(tick("binance", "100"))
    await board.on_tick(tick("kraken", "99", age=31))
    snapshot = market_snapshot(board)
    assert [p["fresh"] for p in snapshot["prices"]] == [True, False]
    assert snapshot["spreads"] == []


def test_an_empty_board_gives_empty_lists():
    snapshot = market_snapshot(make_board())
    assert (snapshot["prices"], snapshot["spreads"]) == ([], [])


class FakeSource:
    def __init__(self, *replies):
        self._replies, self.calls = list(replies), 0

    async def latest_ticks(self, within):
        self.calls += 1
        reply = self._replies[min(self.calls - 1, len(self._replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


async def no_sleep(seconds):
    pass


async def test_the_poller_copies_ticks_into_the_board():
    board = make_board()
    source = FakeSource([tick("binance", "100"), tick("kraken", "99")])
    await run_market_poller(source, board, max_cycles=2, sleep=no_sleep)
    assert len(board.ticks()) == 2
    assert source.calls == 2


async def test_the_poller_survives_database_trouble_and_recovers():
    board = make_board()
    source = FakeSource(
        ConnectionRefusedError(),
        asyncpg.ConnectionDoesNotExistError("gone"),
        [tick("binance", "100")],
    )
    await run_market_poller(source, board, max_cycles=3, sleep=no_sleep)
    assert len(board.ticks()) == 1


async def test_a_bug_in_the_poller_is_not_swallowed():
    with pytest.raises(RuntimeError, match="bug"):
        await run_market_poller(
            FakeSource(RuntimeError("bug")), make_board(), max_cycles=1, sleep=no_sleep
        )


async def test_the_poller_waits_between_cycles_but_not_after_the_last():
    pauses = []

    async def record(seconds):
        pauses.append(seconds)

    await run_market_poller(FakeSource([]), make_board(), interval=2.5, max_cycles=3, sleep=record)
    assert pauses == [2.5, 2.5]


async def test_the_stream_sends_a_retry_hint_and_then_snapshots():
    board = make_board()
    await board.on_tick(tick("binance", "100"))
    chunks = [chunk async for chunk in market_events(board, interval=0, limit=2)]
    assert chunks[0] == "retry: 3000\n\n"
    assert len(chunks) == 3
    for chunk in chunks[1:]:
        assert chunk.startswith("event: market\ndata: ")
        assert chunk.endswith("\n\n")
        assert json.loads(chunk.split("data: ", 1)[1])["prices"][0]["price"] == "100"


def test_the_rate_limiter_allows_a_burst_then_says_how_long_to_wait():
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.try_acquire() is None
    now[0] = 10
    assert limiter.try_acquire() is None
    assert limiter.try_acquire() == pytest.approx(50)  # the first call frees up at 60s
    now[0] = 60
    assert limiter.try_acquire() is None  # the window has slid


@pytest.mark.parametrize(("calls", "seconds"), [(0, 60), (1, 0), (1, -1)])
def test_a_rate_limiter_needs_sensible_settings(calls, seconds):
    with pytest.raises(ValueError):
        RateLimiter(calls, seconds)
