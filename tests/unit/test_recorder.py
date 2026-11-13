import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from deskpilot.ingestion import BackoffPolicy
from deskpilot.models import Exchange, PriceTick
from deskpilot.storage import Recorder

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)


def tick(n: int) -> PriceTick:
    """Tick number n: price 100 + n, n seconds after T0."""
    return PriceTick(
        exchange=Exchange.BINANCE,
        symbol="BTC/USDT",
        price=str(100 + n),
        exchange_time=T0 + timedelta(seconds=n),
    )


def numbers(ticks) -> list[int]:
    """Turn ticks back into their numbers, to make comparisons easy to read."""
    return [int(t.price) - 100 for t in ticks]


class FakeRepo:
    """A pretend database.

    - fail: errors to raise, one per call, before it starts working
    - hang_first: the first call never finishes (like a database that froze)
    - duplicates: how many ticks per batch it claims to already have
    """

    def __init__(self, *, fail=(), hang_first=False, duplicates=0):
        self.batches = []
        self.calls = 0
        self._errors = list(fail)
        self._hang_first = hang_first
        self._duplicates = duplicates

    async def save_ticks(self, ticks):
        self.calls += 1
        if self._hang_first and self.calls == 1:
            await asyncio.Event().wait()
        if self._errors:
            raise self._errors.pop(0)
        self.batches.append(list(ticks))
        return len(ticks) - self._duplicates


@asynccontextmanager
async def running(recorder):
    task = asyncio.create_task(recorder.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_until(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):  # a bug fails the test instead of hanging it
        while not predicate():
            await asyncio.sleep(0.001)

class CustomError(Exception):
    pass


async def test_the_errors_to_retry_can_be_chosen_per_recorder():
    repo = FakeRepo(fail=[CustomError(), CustomError()])
    recorder = Recorder(repo, flush_interval=0.01, backoff=FAST, retry_on=(CustomError,))
    async with running(recorder):
        await recorder.on_tick(tick(0))
        await wait_until(lambda: len(repo.batches) == 1)
    assert recorder.retry_count == 2


async def test_errors_outside_a_custom_list_are_still_not_swallowed():
    repo = FakeRepo(fail=[ConnectionRefusedError()])  # an OSError, but not in this list
    recorder = Recorder(repo, flush_interval=0.01, backoff=FAST, retry_on=(CustomError,))
    await recorder.on_tick(tick(0))
    with pytest.raises(ConnectionRefusedError):
        await asyncio.wait_for(recorder.run(), timeout=2)

async def test_a_full_batch_is_saved_without_waiting_for_the_interval():
    repo = FakeRepo()
    recorder = Recorder(repo, batch_size=3, flush_interval=60)
    async with running(recorder):
        for n in range(3):
            await recorder.on_tick(tick(n))
        await wait_until(lambda: len(repo.batches) == 1)  # would time out if it waited 60s
    assert numbers(repo.batches[0]) == [0, 1, 2]


async def test_a_partial_batch_is_saved_once_the_interval_has_passed():
    repo = FakeRepo()
    recorder = Recorder(repo, batch_size=100, flush_interval=0.05)
    async with running(recorder):
        for n in range(2):
            await recorder.on_tick(tick(n))
        await wait_until(lambda: len(repo.batches) == 1)
    assert numbers(repo.batches[0]) == [0, 1]


async def test_order_is_kept_across_several_batches():
    repo = FakeRepo()
    recorder = Recorder(repo, batch_size=3, flush_interval=0.01)
    async with running(recorder):
        for n in range(7):
            await recorder.on_tick(tick(n))
        await wait_until(lambda: sum(len(b) for b in repo.batches) == 7)
    assert numbers(t for batch in repo.batches for t in batch) == list(range(7))
    assert all(len(batch) <= 3 for batch in repo.batches)


async def test_new_and_duplicate_ticks_are_counted_separately():
    repo = FakeRepo(duplicates=1)
    recorder = Recorder(repo, batch_size=5, flush_interval=60)
    async with running(recorder):
        for n in range(5):
            await recorder.on_tick(tick(n))
        await wait_until(lambda: len(repo.batches) == 1)
    assert recorder.saved_count == 4
    assert recorder.duplicate_count == 1


@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(), asyncpg.ConnectionDoesNotExistError("gone")],
    ids=["os-error", "lost-connection"],
)
async def test_database_trouble_is_retried_without_losing_ticks(error):
    repo = FakeRepo(fail=[error, error])
    recorder = Recorder(repo, batch_size=10, flush_interval=0.01, backoff=FAST)
    async with running(recorder):
        for n in range(3):
            await recorder.on_tick(tick(n))
        await wait_until(lambda: len(repo.batches) == 1)
    assert numbers(repo.batches[0]) == [0, 1, 2]
    assert recorder.retry_count == 2
    assert repo.calls == 3


async def test_a_real_bug_is_not_swallowed():
    repo = FakeRepo(fail=[RuntimeError("a real bug")])
    recorder = Recorder(repo, flush_interval=0.01)
    await recorder.on_tick(tick(0))
    with pytest.raises(RuntimeError, match="a real bug"):
        await asyncio.wait_for(recorder.run(), timeout=2)


async def test_a_full_buffer_drops_the_newest_ticks_and_counts_them():
    repo = FakeRepo()
    recorder = Recorder(repo, max_buffer=2)
    for n in range(5):
        await recorder.on_tick(tick(n))  # never waits, even though the buffer is full
    assert recorder.dropped_count == 3
    await recorder.drain()
    assert numbers(repo.batches[0]) == [0, 1]


async def test_drain_saves_everything_left_in_batches():
    repo = FakeRepo()
    recorder = Recorder(repo, batch_size=3)
    for n in range(7):
        await recorder.on_tick(tick(n))
    assert recorder.pending == 7

    await recorder.drain()

    assert [numbers(batch) for batch in repo.batches] == [[0, 1, 2], [3, 4, 5], [6]]
    assert recorder.saved_count == 7
    assert recorder.pending == 0


async def test_drain_with_nothing_waiting_does_nothing():
    repo = FakeRepo()
    await Recorder(repo).drain()
    assert repo.calls == 0


async def test_a_batch_interrupted_by_shutdown_is_saved_again_by_drain():
    repo = FakeRepo(hang_first=True)  # the first save never finishes
    recorder = Recorder(repo, batch_size=10, flush_interval=0.01)
    task = asyncio.create_task(recorder.run())
    for n in range(2):
        await recorder.on_tick(tick(n))
    await wait_until(lambda: repo.calls == 1)  # the recorder is stuck inside the save

    task.cancel()  # shutdown
    with suppress(asyncio.CancelledError):
        await task
    assert repo.batches == []  # as far as we know, nothing was saved

    await recorder.drain()
    assert [numbers(batch) for batch in repo.batches] == [[0, 1]]


@pytest.mark.parametrize("kwargs", [{"batch_size": 0}, {"flush_interval": 0}, {"max_buffer": 0}])
def test_invalid_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Recorder(FakeRepo(), **kwargs)
