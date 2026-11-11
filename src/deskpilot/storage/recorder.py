import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

import asyncpg

from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.models import PriceTick

logger = logging.getLogger(__name__)


class TickSaver(Protocol):
    """Anything that can save ticks and say how many were new (PriceRepository does)."""

    async def save_ticks(self, ticks: Sequence[PriceTick]) -> int: ...


class Recorder:
    """Collects ticks from the feeds and saves them to the database in small batches.

    Hand `on_tick` to the feeds, run `run()` as a background task, and call
    `drain()` once at shutdown to save whatever is still waiting.
    """

    # Database problems worth retrying. Anything else is a bug and crashes loudly.
    # (TimeoutError and ConnectionRefusedError are OSErrors.)
    retry_on: tuple[type[BaseException], ...] = (
        OSError,
        asyncpg.PostgresConnectionError,
        asyncpg.CannotConnectNowError,
    )

    def __init__(
        self,
        saver: TickSaver,
        *,
        batch_size: int = 500,
        flush_interval: float = 1.0,
        max_buffer: int = 50_000,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if flush_interval <= 0:
            raise ValueError("flush_interval must be greater than 0")
        if max_buffer < 1:
            raise ValueError("max_buffer must be at least 1")

        self._saver = saver
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._backoff = backoff or BackoffPolicy(base=0.5, factor=2.0, cap=10.0)

        self._queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=max_buffer)
        # The stack being carried: collected, but not yet confirmed saved.
        self._batch: list[PriceTick] = []

        self.saved_count = 0  # ticks stored as new rows
        self.duplicate_count = 0  # ticks the database already had
        self.dropped_count = 0  # ticks thrown away because the tray was full
        self.retry_count = 0  # failed attempts to reach the database

    @property
    def pending(self) -> int:
        """How many ticks are waiting to be saved."""
        return len(self._batch) + self._queue.qsize()

    async def on_tick(self, tick: PriceTick) -> None:
        """Hand a tick to the recorder. Never waits, so a slow database cannot stall a feed."""
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            self.dropped_count += 1
            if self.dropped_count % 1000 == 1:  # don't flood the log
                logger.warning(
                    "recorder buffer is full; %d ticks dropped so far", self.dropped_count
                )

    async def run(self) -> None:
        """Save ticks until cancelled."""
        failures = 0
        while True:
            await self._fill_batch()
            while True:  # keep retrying this same stack until it is saved
                try:
                    await self._save_batch()
                    break
                except self.retry_on as exc:
                    delay = self._backoff.delay(failures)
                    failures += 1
                    self.retry_count += 1
                    logger.warning(
                        "database write failed (%s: %s); retrying in %.1fs, %d ticks waiting",
                        type(exc).__name__,
                        exc,
                        delay,
                        self.pending,
                    )
                    await asyncio.sleep(delay)
            failures = 0

    async def drain(self) -> None:
        """Save everything still waiting. Call this after run() has been cancelled."""
        while self._batch or not self._queue.empty():
            while len(self._batch) < self._batch_size and not self._queue.empty():
                self._batch.append(self._queue.get_nowait())
            await self._save_batch()

    async def _fill_batch(self) -> None:
        """Collect a stack: wait for a first tick, then add more until full or time is up."""
        loop = asyncio.get_running_loop()
        if not self._batch:
            self._batch.append(await self._queue.get())
        deadline = loop.time() + self._flush_interval
        while len(self._batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    self._batch.append(await self._queue.get())
            except TimeoutError:
                break

    async def _save_batch(self) -> None:
        # The stack is only cleared AFTER a confirmed save. If we are cancelled or the
        # database fails halfway, it is still here to be retried (or drained).
        new = await self._saver.save_ticks(self._batch)
        self.saved_count += new
        self.duplicate_count += len(self._batch) - new
        self._batch = []
