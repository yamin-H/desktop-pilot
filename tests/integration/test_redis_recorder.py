import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from deskpilot.bus.consumer import StreamRecorder
from deskpilot.bus.publisher import StreamTickSaver
from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.models import PriceTick
from deskpilot.storage import PriceRepository

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)
GROUP = "recorder"


def tick(n):
    return PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price=str(100 + n),
        exchange_time=T0 + timedelta(seconds=n),
        received_time=T0 + timedelta(seconds=n),
    )


async def publish(env, count):
    await StreamTickSaver(env.redis, env.stream).save_ticks([tick(n) for n in range(count)])


def make_worker(env, saver, *, consumer="w1", **settings):
    defaults = {"block_ms": 50, "claim_idle_ms": 60_000, "claim_every": 0.05, "backoff": FAST}
    return StreamRecorder(
        env.redis,
        saver,
        stream=env.stream,
        group=GROUP,
        consumer=consumer,
        **{**defaults, **settings},
    )


async def db_count(pool):
    return await pool.fetchval("SELECT count(*) FROM prices")


async def pending(env):
    return (await env.redis.xpending(env.stream, GROUP))["pending"]


async def until(check, timeout=5.0):
    async with asyncio.timeout(timeout):  # a bug fails the test instead of hanging it
        while not await check():
            await asyncio.sleep(0.02)


@asynccontextmanager
async def running(worker):
    task = asyncio.create_task(worker.run())
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class Hang:
    """A saver that never finishes: a worker killed in the middle of a save."""

    def __init__(self):
        self.entered = asyncio.Event()

    async def save_ticks(self, ticks):
        self.entered.set()
        await asyncio.Event().wait()


class SaveThenHang:
    """Saves, then never finishes: a worker killed after the save but before the acknowledgement."""

    def __init__(self, repo):
        self._repo, self.entered = repo, asyncio.Event()

    async def save_ticks(self, ticks):
        await self._repo.save_ticks(ticks)
        self.entered.set()
        await asyncio.Event().wait()


class Flaky:
    def __init__(self, repo, failures):
        self._repo, self._failures, self.calls = repo, failures, 0

    async def save_ticks(self, ticks):
        self.calls += 1
        if self.calls <= self._failures:
            raise ConnectionRefusedError("database down")
        return await self._repo.save_ticks(ticks)


async def test_every_published_tick_is_stored_and_acknowledged(pool, stream_env):
    await publish(stream_env, 25)
    worker = make_worker(stream_env, PriceRepository(pool))
    async with running(worker):

        async def done():
            return await db_count(pool) == 25 and await pending(stream_env) == 0

        await until(done)
    assert (worker.saved_count, worker.duplicate_count, worker.acked_count) == (25, 0, 25)


async def test_ticks_published_while_the_worker_runs_are_picked_up(pool, stream_env):
    worker = make_worker(stream_env, PriceRepository(pool))
    async with running(worker):
        await publish(stream_env, 5)
        await until(lambda: _count_is(pool, 5))
    assert await db_count(pool) == 5


async def _count_is(pool, expected):
    return await db_count(pool) == expected


async def test_a_worker_killed_before_saving_loses_nothing_after_a_restart(pool, stream_env):
    await publish(stream_env, 10)
    hang = Hang()
    async with running(make_worker(stream_env, hang)):
        await asyncio.wait_for(hang.entered.wait(), 5)
        assert await pending(stream_env) == 10  # delivered, not acknowledged
    assert await db_count(pool) == 0  # killed: nothing was saved

    async with running(make_worker(stream_env, PriceRepository(pool))):  # same name: restart

        async def done():
            return await db_count(pool) == 10 and await pending(stream_env) == 0

        await until(done)


async def test_another_worker_takes_over_after_the_dead_one_has_been_idle_long_enough(
    pool, stream_env
):
    await publish(stream_env, 10)
    hang = Hang()
    async with running(make_worker(stream_env, hang, consumer="dead")):
        await asyncio.wait_for(hang.entered.wait(), 5)

    rescuer = make_worker(stream_env, PriceRepository(pool), consumer="alive", claim_idle_ms=100)
    async with running(rescuer):

        async def done():
            return await db_count(pool) == 10 and await pending(stream_env) == 0

        await until(done)
    assert rescuer.claimed_count == 10


async def test_a_live_workers_fresh_messages_are_not_stolen(pool, stream_env):
    await publish(stream_env, 5)
    hang = Hang()
    async with running(make_worker(stream_env, hang, consumer="busy")):
        await asyncio.wait_for(hang.entered.wait(), 5)
        other = make_worker(
            stream_env, PriceRepository(pool), consumer="other", claim_idle_ms=60_000
        )
        async with running(other):
            await asyncio.sleep(0.4)
        assert other.claimed_count == 0
        assert await db_count(pool) == 0
        assert await pending(stream_env) == 5  # still owned by the busy worker


async def test_a_worker_killed_after_saving_but_before_acknowledging_causes_no_duplicates(
    pool, stream_env
):
    await publish(stream_env, 10)
    saver = SaveThenHang(PriceRepository(pool))
    async with running(make_worker(stream_env, saver)):
        await asyncio.wait_for(saver.entered.wait(), 5)
        assert await db_count(pool) == 10
        assert await pending(stream_env) == 10  # saved, but never acknowledged

    second = make_worker(stream_env, PriceRepository(pool))
    async with running(second):
        await until(lambda: _pending_is(stream_env, 0))
    assert await db_count(pool) == 10  # the redelivery changed nothing
    assert (second.saved_count, second.duplicate_count) == (0, 10)


async def _pending_is(env, expected):
    return await pending(env) == expected


async def test_an_unreadable_entry_goes_to_the_dead_letter_stream_and_does_not_block_the_rest(
    pool, stream_env
):
    saver = StreamTickSaver(stream_env.redis, stream_env.stream)
    await saver.save_ticks([tick(0), tick(1)])
    await stream_env.redis.xadd(stream_env.stream, {"junk": "yes"})
    await saver.save_ticks([tick(2)])

    worker = make_worker(stream_env, PriceRepository(pool))
    async with running(worker):

        async def done():
            return await db_count(pool) == 3 and await pending(stream_env) == 0

        await until(done)

    assert worker.dead_count == 1
    [(_, record)] = await stream_env.redis.xrange(stream_env.dead)
    assert "field_junk" in record
    assert record["field_junk"] == "yes"
    assert record["original_id"]
    assert record["error"]


async def test_a_database_outage_keeps_entries_unacknowledged_until_the_save_works(
    pool, stream_env
):
    await publish(stream_env, 5)
    flaky = Flaky(PriceRepository(pool), failures=3)
    worker = make_worker(stream_env, flaky)
    async with running(worker):
        await until(lambda: _flaky_called(flaky, 2))
        assert await pending(stream_env) == 5  # not lost, not acknowledged

        async def done():
            return await db_count(pool) == 5 and await pending(stream_env) == 0

        await until(done)
    assert worker.retry_count >= 3


async def _flaky_called(flaky, times):
    return flaky.calls >= times


async def test_an_entry_trimmed_away_while_pending_is_counted_as_lost(pool, stream_env):
    await publish(stream_env, 3)
    await stream_env.redis.xgroup_create(stream_env.stream, GROUP, id="0")
    delivered = await stream_env.redis.xreadgroup(GROUP, "w1", {stream_env.stream: ">"}, count=3)
    first_id = delivered[0][1][0][0]
    await stream_env.redis.xdel(stream_env.stream, first_id)  # as if trimmed

    worker = make_worker(stream_env, PriceRepository(pool))
    async with running(worker):

        async def done():
            return await db_count(pool) == 2 and await pending(stream_env) == 0

        await until(done)
    assert worker.lost_count == 1
