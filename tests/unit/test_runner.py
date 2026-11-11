import asyncio
from contextlib import suppress

import pytest

from deskpilot.ingestion import run_feeds


class Waiter:
    """A feed that runs until cancelled, and remembers that it was cancelled."""

    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = False

    async def run(self):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class Crasher:
    async def run(self):
        raise RuntimeError("a real bug")


class Handshake:
    """Finishes only once the other feed has also started. Proves they run together."""

    def __init__(self, mine, theirs):
        self.mine = mine
        self.theirs = theirs

    async def run(self):
        self.mine.set()
        await self.theirs.wait()


async def test_feeds_run_at_the_same_time():
    a, b = asyncio.Event(), asyncio.Event()
    # If they ran one after the other, this would wait forever and time out.
    await asyncio.wait_for(run_feeds([Handshake(a, b), Handshake(b, a)]), timeout=2)


async def test_a_real_bug_in_one_feed_stops_the_others_and_is_raised():
    waiter = Waiter()
    with pytest.raises(ExceptionGroup) as info:
        await asyncio.wait_for(run_feeds([waiter, Crasher()]), timeout=2)
    assert any(isinstance(error, RuntimeError) for error in info.value.exceptions)
    assert waiter.cancelled


async def test_cancelling_the_runner_stops_every_feed():
    first, second = Waiter(), Waiter()
    task = asyncio.create_task(run_feeds([first, second]))
    async with asyncio.timeout(2):
        await first.started.wait()
        await second.started.wait()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert first.cancelled
    assert second.cancelled


async def test_no_feeds_is_an_error():
    with pytest.raises(ValueError):
        await run_feeds([])
