import asyncio
import logging
import time
from typing import Any

import asyncpg
from redis import exceptions as redis_errors
from redis.asyncio import Redis

from deskpilot.bus.client import REDIS_RETRYABLE
from deskpilot.bus.codec import decode_tick
from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.models import PriceTick
from deskpilot.storage.recorder import TickSaver

logger = logging.getLogger(__name__)

Entry = tuple[str, dict[str, str] | None]


class StreamRecorder:
    """Reads ticks from a Redis stream (as part of a consumer group) and saves them.

    A message is acknowledged ONLY after it is saved. If this worker dies at any point, the
    message stays pending and is processed again, by this worker after a restart or by another
    worker once it has been idle too long. Saving is duplicate-safe, so reprocessing is harmless.
    """

    # Database trouble worth retrying. Anything else is a bug and stops the worker.
    db_retry_on: tuple[type[BaseException], ...] = (
        OSError,
        asyncpg.PostgresConnectionError,
        asyncpg.CannotConnectNowError,
    )

    def __init__(
        self,
        redis: Redis,
        saver: TickSaver,
        *,
        stream: str = "ticks",
        group: str = "recorder",
        consumer: str = "recorder-1",
        batch_size: int = 500,
        block_ms: int = 1000,
        claim_idle_ms: int = 30_000,
        claim_every: float = 10.0,
        dead_stream: str | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._redis = redis
        self._saver = saver
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._claim_idle_ms = claim_idle_ms
        self._claim_every = claim_every
        self._dead = dead_stream or f"{stream}:dead"
        self._backoff = backoff or BackoffPolicy(base=0.5, factor=2.0, cap=10.0)

        self.saved_count = 0  # ticks stored as new rows
        self.duplicate_count = 0  # ticks the database already had (redeliveries, replays)
        self.acked_count = 0  # stream entries acknowledged
        self.dead_count = 0  # unreadable entries moved to the dead-letter stream
        self.lost_count = 0  # entries trimmed from the stream before we could read them
        self.claimed_count = 0  # entries taken over from idle (dead) workers
        self.retry_count = 0  # failed attempts to reach the database or Redis

    async def setup(self) -> None:
        """Create the consumer group (from the start of the stream) if it does not exist."""
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except redis_errors.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def run(self) -> None:
        """Process until cancelled. Redis trouble is retried; bugs stop the worker."""
        failures = 0
        ready = False
        last_claim = 0.0
        while True:
            try:
                if not ready:
                    await self.setup()
                    await self._recover_own_pending()
                    ready = True
                now = time.monotonic()
                if now - last_claim >= self._claim_every:
                    last_claim = now
                    await self._process(await self._claim_stale())
                await self._process(await self._read(">"))
                failures = 0
            except REDIS_RETRYABLE as error:
                ready = False  # after reconnecting, look at our own unfinished work again
                delay = self._backoff.delay(failures)
                failures += 1
                self.retry_count += 1
                logger.warning(
                    "Redis problem (%s: %s); retrying in %.1fs", type(error).__name__, error, delay
                )
                await asyncio.sleep(delay)

    async def _read(self, start: str) -> list[Entry]:
        """New entries (start='>') or this worker's own unfinished entries (start='0')."""
        response = await self._redis.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: start},
            count=self._batch_size,
            block=self._block_ms if start == ">" else None,
        )
        return list(response[0][1]) if response else []

    async def _recover_own_pending(self) -> None:
        while entries := await self._read("0"):
            await self._process(entries)

    async def _claim_stale(self) -> list[Entry]:
        """Take over entries that another worker received but has been idle on for too long."""
        result: Any = await self._redis.xautoclaim(
            self._stream,
            self._group,
            self._consumer,
            min_idle_time=self._claim_idle_ms,
            start_id="0-0",
            count=self._batch_size,
        )
        entries = list(result[1])
        self.claimed_count += len(entries)
        return entries

    async def _process(self, entries: list[Entry]) -> None:
        entries = [(entry_id, fields) for entry_id, fields in entries if entry_id is not None]
        if not entries:
            return

        ticks: list[PriceTick] = []
        for entry_id, fields in entries:
            if not fields:
                self.lost_count += 1
                logger.warning("stream entry %s was trimmed before it was processed", entry_id)
                continue
            try:
                ticks.append(decode_tick(fields))
            except ValueError as error:
                await self._dead_letter(entry_id, fields, error)

        if ticks:
            new = await self._save(ticks)
            self.saved_count += new
            self.duplicate_count += len(ticks) - new

        # Only now, after the save is confirmed:
        await self._redis.xack(self._stream, self._group, *[entry_id for entry_id, _ in entries])
        self.acked_count += len(entries)

    async def _save(self, ticks: list[PriceTick]) -> int:
        failures = 0
        while True:
            try:
                return await self._saver.save_ticks(ticks)
            except self.db_retry_on as error:
                delay = self._backoff.delay(failures)
                failures += 1
                self.retry_count += 1
                logger.warning(
                    "database write failed (%s: %s); retrying in %.1fs, "
                    "entries stay unacknowledged",
                    type(error).__name__,
                    error,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _dead_letter(self, entry_id: str, fields: dict[str, str], error: ValueError) -> None:
        record = {"original_id": entry_id, "error": str(error)[:200]}
        for key, value in list(fields.items())[:10]:
            record[f"field_{key}"[:50]] = str(value)[:200]
        await self._redis.xadd(self._dead, record, maxlen=10_000, approximate=True)
        self.dead_count += 1
        logger.warning("moved unreadable entry %s to %s", entry_id, self._dead)
