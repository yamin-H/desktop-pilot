from datetime import UTC, datetime, timedelta

import pytest

from deskpilot.bus.publisher import StreamTickSaver
from deskpilot.models import PriceTick

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def tick(n):
    return PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price=str(100 + n),
        exchange_time=T0 + timedelta(seconds=n),
        received_time=T0 + timedelta(seconds=n, milliseconds=5),
    )


async def test_a_published_tick_is_a_stream_entry_with_exact_text_fields(stream_env):
    saved = await StreamTickSaver(stream_env.redis, stream_env.stream).save_ticks([tick(1)])
    assert saved == 1
    [(_, fields)] = await stream_env.redis.xrange(stream_env.stream)
    assert fields == {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "price": "101",
        "exchange_time": "2026-11-12T10:00:01+00:00",
        "received_time": "2026-11-12T10:00:01.005000+00:00",
    }


async def test_entries_keep_the_order_they_were_published_in(stream_env):
    await StreamTickSaver(stream_env.redis, stream_env.stream).save_ticks(
        [tick(n) for n in range(5)]
    )
    entries = await stream_env.redis.xrange(stream_env.stream)
    assert [fields["price"] for _, fields in entries] == ["100", "101", "102", "103", "104"]


async def test_publishing_nothing_is_fine(stream_env):
    assert await StreamTickSaver(stream_env.redis, stream_env.stream).save_ticks([]) == 0
    assert await stream_env.redis.xlen(stream_env.stream) == 0


async def test_the_stream_is_trimmed_to_roughly_its_maximum_length(stream_env):
    saver = StreamTickSaver(stream_env.redis, stream_env.stream, maxlen=10)
    await saver.save_ticks([tick(n) for n in range(500)])
    length = await stream_env.redis.xlen(stream_env.stream)
    assert 10 <= length <= 200  # trimming is approximate: Redis removes whole blocks


def test_a_maximum_length_below_one_is_refused():
    with pytest.raises(ValueError):
        StreamTickSaver(None, maxlen=0)
