import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from enum import StrEnum

from deskpilot.ingestion.backoff import BackoffPolicy
from deskpilot.models import Exchange, PriceTick

logger = logging.getLogger(__name__)

RawMessage = str | bytes
TickHandler = Callable[[PriceTick], Awaitable[None]]


class FeedDisconnected(Exception):
    """The connection ended. It is safe to reconnect."""


class FeedStale(FeedDisconnected):
    """The connection is open but has gone silent for too long."""


class FeedStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"


class BaseFeed(ABC):
    """Keeps one exchange connection alive and turns its messages into PriceTicks.

    A subclass only has to say HOW to connect and HOW to read one message.
    Reconnecting, waiting, and silence detection live here, once, for everyone.
    """

    exchange: Exchange

    # Errors that mean "connection problem, try again". Anything else is a bug in
    # our code and is allowed to crash loudly instead of being retried forever.
    # Subclasses can add their library's own errors here.
    retry_on: tuple[type[BaseException], ...] = (OSError, TimeoutError, FeedDisconnected)

    def __init__(
        self,
        on_tick: TickHandler,
        *,
        backoff: BackoffPolicy | None = None,
        stale_after: float = 30.0,
    ) -> None:
        self._on_tick = on_tick
        self._backoff = backoff or BackoffPolicy()
        self._stale_after = stale_after
        self._failures = 0  # failures in a row, used to size the next wait

        self.status = FeedStatus.DISCONNECTED
        self.reconnect_count = 0
        self.parse_error_count = 0

    @abstractmethod
    def connect(self) -> AbstractAsyncContextManager[AsyncIterator[RawMessage]]:
        """Open a connection (and subscribe). Use as: `async with feed.connect() as stream`."""

    @abstractmethod
    def parse(self, raw: RawMessage) -> list[PriceTick]:
        """Turn one raw message into zero or more PriceTicks.

        Return [] for messages that are not prices (heartbeats, confirmations).
        Raise ValueError for messages that cannot be read.
        """

    async def run(self) -> None:
        """Stay connected and deliver ticks. Runs until the task is cancelled."""
        while True:
            try:
                await self._session()
            except self.retry_on as exc:
                delay = self._backoff.delay(self._failures)
                self._failures += 1
                self.reconnect_count += 1
                logger.warning(
                    "%s feed lost (%s: %s); reconnecting in %.1fs",
                    self.exchange,
                    type(exc).__name__,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _session(self) -> None:
        """One connection, from opening until it ends (always by raising)."""
        async with self.connect() as stream:
            self.status = FeedStatus.CONNECTED
            logger.info("%s feed connected", self.exchange)
            try:
                await self._read_forever(stream)
            finally:
                self.status = FeedStatus.DISCONNECTED

    async def _read_forever(self, stream: AsyncIterator[RawMessage]) -> None:
        iterator = aiter(stream)
        while True:
            try:
                async with asyncio.timeout(self._stale_after):
                    raw = await anext(iterator)
            except StopAsyncIteration:
                raise FeedDisconnected("server closed the connection") from None
            except TimeoutError:
                raise FeedStale(f"no message for {self._stale_after}s") from None

            self._failures = 0  # a message arrived, so this connection is healthy
            await self._handle(raw)

    async def _handle(self, raw: RawMessage) -> None:
        try:
            ticks = self.parse(raw)
        except ValueError as exc:
            self.parse_error_count += 1
            logger.warning("%s: skipped unreadable message (%s)", self.exchange, exc)
            return
        for tick in ticks:
            await self._on_tick(tick)
