import asyncio
import logging
from collections.abc import Callable
from typing import Any

from redis.asyncio import Redis

from deskpilot.analytics import PriceBoard
from deskpilot.bus.client import REDIS_RETRYABLE
from deskpilot.bus.codec import decode_tick
from deskpilot.ingestion.backoff import BackoffPolicy

logger = logging.getLogger(__name__)


class MarketFollower:
    """Keeps a PriceBoard up to date by reading a Redis stream. No consumer group.

    It starts from the stream's recent history (so the board is filled at once), then reads
    new entries. Every follower sees every tick, independently of the recorder workers.
    After a Redis problem it carries on from the last entry it saw.
    """

    def __init__(
        self,
        redis: Redis,
        board: PriceBoard,
        *,
        stream: str = "ticks",
        history: int = 2000,
        block_ms: int = 1000,
        backoff: BackoffPolicy | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._redis = redis
        self._board = board
        self._stream = stream
        self._history = history
        self._block_ms = block_ms
        self._backoff = backoff or BackoffPolicy(base=0.5, factor=2.0, cap=10.0)
        self._sleep = sleep
        self.received_count = 0
        self.skipped_count = 0  # unreadable entries
        self.retry_count = 0

    async def _apply(self, fields: dict[str, str] | None) -> None:
        try:
            tick = decode_tick(fields)
        except ValueError:
            self.skipped_count += 1
            return
        await self._board.on_tick(tick)
        self.received_count += 1

    async def _seed(self) -> str:
        newest_first = await self._redis.xrevrange(self._stream, count=self._history)
        for _, fields in reversed(newest_first):  # oldest first, so the newest tick wins
            await self._apply(fields)
        return newest_first[0][0] if newest_first else "0-0"

    async def run(self, max_cycles: int | None = None) -> None:
        last_id: str | None = None
        failures = 0
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            try:
                if last_id is None:
                    last_id = await self._seed()
                response = await self._redis.xread(
                    {self._stream: last_id}, count=1000, block=self._block_ms
                )
                for _, entries in response or []:
                    for entry_id, fields in entries:
                        last_id = entry_id
                        await self._apply(fields)
                failures = 0
            except REDIS_RETRYABLE as error:
                delay = self._backoff.delay(failures)
                failures += 1
                self.retry_count += 1
                logger.warning(
                    "Redis problem (%s: %s); retrying in %.1fs", type(error).__name__, error, delay
                )
                await self._sleep(delay)
