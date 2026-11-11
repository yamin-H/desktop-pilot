import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.ingestion import BackoffPolicy, BaseFeed, FeedStatus
from deskpilot.models import Exchange, PriceTick

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)
HANG = object()  # inside a script: "go silent, send nothing more"


class FakeFeed(BaseFeed):
    """A pretend exchange. `scripts` holds one entry per connection attempt:
    - an Exception instance: that connection attempt fails
    - a list: messages to send; an Exception in it is raised, HANG goes silent.
    When the list ends, the server closes the connection.
    When the scripts run out, new connection attempts wait forever.
    """

    exchange = Exchange.BINANCE

    def __init__(self, scripts, on_tick, **kwargs):
        super().__init__(on_tick, **kwargs)
        self._scripts = list(scripts)
        self.connect_attempts = 0

    @asynccontextmanager
    async def connect(self):
        self.connect_attempts += 1
        if not self._scripts:
            await asyncio.Event().wait()
        script = self._scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        yield self._play(script)

    async def _play(self, items):
        for item in items:
            if item is HANG:
                await asyncio.Event().wait()
            if isinstance(item, Exception):
                raise item
            yield item

    def parse(self, raw):
        if raw == "ping":
            return []
        return [
            PriceTick(exchange=Exchange.BINANCE, symbol="BTC/USDT", price=raw, exchange_time=NOW)
        ]


class Collector:
    """Stands in for the rest of the system: just remembers every tick it gets."""

    def __init__(self):
        self.ticks = []

    async def __call__(self, tick):
        self.ticks.append(tick)

    @property
    def prices(self):
        return [t.price for t in self.ticks]


class RecordingBackoff:
    """Remembers which failure numbers it was asked about."""

    def __init__(self):
        self.attempts = []

    def delay(self, attempt):
        self.attempts.append(attempt)
        return 0.001


@asynccontextmanager
async def running(feed):
    """Run the feed in the background; always stop it afterwards."""
    task = asyncio.create_task(feed.run())
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_for_ticks(got, count, timeout=2.0):
    async with asyncio.timeout(timeout):  # a bug fails the test instead of hanging it
        while len(got.ticks) < count:
            await asyncio.sleep(0.001)


async def test_delivers_ticks_in_order():
    got = Collector()
    feed = FakeFeed([["100", "101", "102"]], got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 3)
    assert got.prices == [Decimal("100"), Decimal("101"), Decimal("102")]


async def test_messages_that_are_not_prices_are_ignored():
    got = Collector()
    feed = FakeFeed([["ping", "100"]], got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 1)
    assert got.prices == [Decimal("100")]
    assert feed.parse_error_count == 0


async def test_one_bad_message_is_skipped_and_connection_survives():
    got = Collector()
    feed = FakeFeed([["100", "not-a-number", "101", HANG]], got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 2)
    assert got.prices == [Decimal("100"), Decimal("101")]
    assert feed.parse_error_count == 1
    assert feed.reconnect_count == 0


async def test_reconnects_after_server_closes_connection():
    got = Collector()
    feed = FakeFeed([["100"], ["101"]], got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 2)
    assert got.prices == [Decimal("100"), Decimal("101")]
    assert feed.reconnect_count >= 1


async def test_reconnects_after_connection_breaks_mid_stream():
    got = Collector()
    feed = FakeFeed([["100", ConnectionResetError("boom")], ["101"]], got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 2)
    assert got.prices == [Decimal("100"), Decimal("101")]


async def test_keeps_trying_when_connecting_fails():
    got = Collector()
    scripts = [ConnectionRefusedError(), ConnectionRefusedError(), ["100"]]
    feed = FakeFeed(scripts, got, backoff=FAST)
    async with running(feed):
        await wait_for_ticks(got, 1)
    assert feed.reconnect_count >= 2
    assert got.prices == [Decimal("100")]


async def test_silent_connection_is_treated_as_dead_and_replaced():
    got = Collector()
    feed = FakeFeed([["100", HANG], ["101"]], got, backoff=FAST, stale_after=0.05)
    async with running(feed):
        await wait_for_ticks(got, 2)
    assert got.prices == [Decimal("100"), Decimal("101")]
    assert feed.reconnect_count >= 1


async def test_wait_grows_with_failures_and_resets_after_a_message():
    got = Collector()
    backoff = RecordingBackoff()
    boom = ConnectionRefusedError
    feed = FakeFeed([boom(), boom(), ["100"], boom(), ["101"]], got, backoff=backoff)
    async with running(feed):
        await wait_for_ticks(got, 2)
    # fail, fail (growing) -> message arrives (reset) -> fail, fail again
    assert backoff.attempts[:4] == [0, 1, 0, 1]


async def test_unexpected_errors_are_not_swallowed():
    got = Collector()
    feed = FakeFeed([["100", RuntimeError("a real bug")]], got, backoff=FAST)
    with pytest.raises(RuntimeError, match="a real bug"):
        await asyncio.wait_for(feed.run(), timeout=2)


async def test_status_follows_the_connection():
    got = Collector()
    feed = FakeFeed([["100", HANG]], got, backoff=FAST)
    assert feed.status is FeedStatus.DISCONNECTED
    async with running(feed):
        await wait_for_ticks(got, 1)
        assert feed.status is FeedStatus.CONNECTED
    assert feed.status is FeedStatus.DISCONNECTED
