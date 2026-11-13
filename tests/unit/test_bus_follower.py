from datetime import UTC, datetime, timedelta

from redis import exceptions as redis_errors

from deskpilot.analytics import PriceBoard
from deskpilot.bus.codec import encode_tick
from deskpilot.bus.follower import MarketFollower
from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.models import Exchange, PriceTick

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)


def entry(entry_id, price, *, exchange="binance", seconds=0):
    when = T0 + timedelta(seconds=seconds)
    tick = PriceTick(
        exchange=exchange, symbol="BTC/USDT", price=price, exchange_time=when, received_time=when
    )
    return (entry_id, encode_tick(tick))


class FakeRedis:
    def __init__(self, history=(), reads=()):
        self.history = list(history)  # newest first, like XREVRANGE
        self.reads = list(reads)  # one response (or error) per XREAD call
        self.read_from = []

    async def xrevrange(self, name, count=None):
        return self.history[:count]

    async def xread(self, streams, count=None, block=None):
        self.read_from.append(next(iter(streams.values())))
        item = self.reads.pop(0) if self.reads else []
        if isinstance(item, Exception):
            raise item
        return item


async def no_sleep(seconds):
    pass


def follower(redis, board):
    return MarketFollower(redis, board, backoff=FAST, sleep=no_sleep)


def latest(board, exchange="binance"):
    return board.latest(Exchange(exchange), "BTC/USDT")


async def test_the_board_is_filled_from_history_with_the_newest_tick_winning():
    history = [
        entry("3-0", "103", seconds=3),
        entry("2-0", "102", seconds=2),
        entry("1-0", "101", seconds=1),
    ]
    board = PriceBoard()
    redis = FakeRedis(history)
    await follower(redis, board).run(max_cycles=1)
    assert str(latest(board).price) == "103"
    assert redis.read_from == ["3-0"]  # carries on after the newest entry it saw


async def test_new_entries_update_the_board_and_move_the_read_position():
    board = PriceBoard()
    redis = FakeRedis(
        history=[entry("1-0", "100", seconds=1)],
        reads=[
            [
                [
                    "ticks",
                    [
                        entry("2-0", "105", seconds=2),
                        entry("3-0", "106", exchange="kraken", seconds=3),
                    ],
                ]
            ],
            [],
        ],
    )
    runner = follower(redis, board)
    await runner.run(max_cycles=2)
    assert str(latest(board).price) == "105"
    assert str(latest(board, "kraken").price) == "106"
    assert redis.read_from == ["1-0", "3-0"]
    assert runner.received_count == 3


async def test_an_empty_stream_is_read_from_the_very_start():
    redis = FakeRedis()
    await follower(redis, PriceBoard()).run(max_cycles=1)
    assert redis.read_from == ["0-0"]


async def test_after_a_connection_error_it_carries_on_from_the_same_place():
    redis = FakeRedis(
        history=[entry("1-0", "100", seconds=1)],
        reads=[redis_errors.ConnectionError("down"), [["ticks", [entry("2-0", "105", seconds=2)]]]],
    )
    board = PriceBoard()
    runner = follower(redis, board)
    await runner.run(max_cycles=2)
    assert redis.read_from == ["1-0", "1-0"]
    assert str(latest(board).price) == "105"
    assert runner.retry_count == 1


async def test_unreadable_entries_are_skipped_and_counted_but_the_position_still_moves():
    redis = FakeRedis(
        reads=[[["ticks", [("1-0", {"junk": "x"}), entry("2-0", "105", seconds=2)]]], []]
    )
    board = PriceBoard()
    runner = follower(redis, board)
    await runner.run(max_cycles=2)
    assert (runner.skipped_count, runner.received_count) == (1, 1)
    assert redis.read_from[1] == "2-0"
    assert str(latest(board).price) == "105"
