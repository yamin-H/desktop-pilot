import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from deskpilot.models import Exchange, PriceTick
from deskpilot.storage import PriceRepository, Recorder

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def tick(n: int) -> PriceTick:
    return PriceTick(
        exchange=Exchange.BINANCE,
        symbol="BTC/USDT",
        price=str(100 + n),
        exchange_time=T0 + timedelta(seconds=n),
    )


async def count(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM prices")


async def test_replaying_the_same_ticks_twice_leaves_the_database_unchanged(pool):
    ticks = [tick(n) for n in range(20)]

    first = Recorder(PriceRepository(pool))
    for t in ticks:
        await first.on_tick(t)
    await first.drain()
    assert await count(pool) == 20
    assert (first.saved_count, first.duplicate_count) == (20, 0)

    replay = Recorder(PriceRepository(pool))
    for t in ticks:
        await replay.on_tick(t)
    await replay.drain()
    assert await count(pool) == 20
    assert (replay.saved_count, replay.duplicate_count) == (0, 20)


async def test_the_background_loop_writes_to_the_database(pool):
    recorder = Recorder(PriceRepository(pool), batch_size=10, flush_interval=0.02)
    task = asyncio.create_task(recorder.run())
    try:
        for n in range(25):
            await recorder.on_tick(tick(n))
        async with asyncio.timeout(5):
            while recorder.saved_count < 25:
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert await count(pool) == 25
