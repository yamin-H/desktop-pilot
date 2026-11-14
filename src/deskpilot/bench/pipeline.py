import asyncio
import random
import time
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
from redis.asyncio import Redis

from deskpilot.analytics import PriceBoard
from deskpilot.bench.data import binance_message, kraken_message, make_tick
from deskpilot.bench.stats import LatencySummary, per_second, summarize
from deskpilot.bus import REDIS_RETRYABLE, MarketFollower, StreamRecorder, StreamTickSaver
from deskpilot.ingestion import BinanceFeed, KrakenFeed
from deskpilot.models import PriceTick
from deskpilot.recon.injection import build_scenario
from deskpilot.recon.matcher import reconcile
from deskpilot.storage import PriceRepository, Recorder


class BenchmarkError(Exception):
    """A benchmark stage produced wrong results, so its speed is meaningless."""


@dataclass(frozen=True)
class StageResult:
    name: str
    count: int  # items processed
    seconds: float

    @property
    def rate(self) -> float:
        return per_second(self.count, self.seconds)


@dataclass(frozen=True)
class LatencyResult:
    rate: int  # ticks per second offered
    duration: float
    flush_interval: float
    published: int  # ticks offered to the pipeline
    dropped: int  # ticks the publisher buffer dropped
    delivered: int  # ticks that reached the database
    to_database: LatencySummary  # tick created -> committed in PostgreSQL (after warm-up)
    to_board: LatencySummary  # tick created -> applied to the API's price board (after warm-up)
    keeping_up: bool  # the producer managed to offer ticks at the requested rate


async def _ignore(tick: PriceTick) -> None:
    pass


def bench_parse(count: int, seed: int = 1) -> list[StageResult]:
    """How fast the real feed code turns raw exchange messages into ticks (CPU only)."""
    rng = random.Random(seed)
    symbols = ["BTC/USDT", "ETH/USDT"]
    cases = (
        (
            "parse binance messages",
            BinanceFeed(symbols, _ignore),
            [binance_message(i, rng) for i in range(count)],
        ),
        (
            "parse kraken messages",
            KrakenFeed(symbols, _ignore),
            [kraken_message(i, rng) for i in range(count)],
        ),
    )
    results = []
    for name, feed, messages in cases:
        parsed = 0
        started = time.perf_counter()
        for raw in messages:
            parsed += len(feed.parse(raw))
        seconds = time.perf_counter() - started
        if parsed != count:
            raise BenchmarkError(f"{name}: parsed {parsed} ticks from {count} messages")
        results.append(StageResult(name, count, seconds))
    return results


async def bench_publish(
    redis: Redis, stream: str, ticks: list[PriceTick], *, batch_size: int = 500
) -> StageResult:
    """Ticks per second into a Redis stream, in batches like the real publisher sends."""
    saver = StreamTickSaver(redis, stream, maxlen=max(200_000, len(ticks) * 2))
    started = time.perf_counter()
    for start in range(0, len(ticks), batch_size):
        await saver.save_ticks(ticks[start : start + batch_size])
    seconds = time.perf_counter() - started
    length = await redis.xlen(stream)
    if length != len(ticks):
        raise BenchmarkError(f"published {len(ticks)} ticks but the stream holds {length}")
    return StageResult("publish to Redis", len(ticks), seconds)


async def bench_consume(
    redis: Redis,
    pool: asyncpg.Pool,
    stream: str,
    count: int,
    *,
    batch_size: int = 500,
    timeout: float = 300.0,
) -> StageResult:
    """Ticks per second from a pre-filled stream into PostgreSQL, through the real worker."""
    await pool.execute("TRUNCATE prices")
    worker = StreamRecorder(
        redis,
        PriceRepository(pool),
        stream=stream,
        group="bench",
        consumer="bench-1",
        batch_size=batch_size,
        block_ms=50,
        claim_every=3600.0,
    )
    started = time.perf_counter()
    task = asyncio.create_task(worker.run())
    try:
        async with asyncio.timeout(timeout):
            while worker.acked_count < count:
                if task.done():
                    task.result()  # shows a crash instead of waiting forever
                await asyncio.sleep(0.005)
        seconds = time.perf_counter() - started
    except TimeoutError:
        raise BenchmarkError(f"only {worker.acked_count} of {count} ticks were processed") from None
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    stored = await pool.fetchval("SELECT count(*) FROM prices")
    if stored != count or worker.saved_count != count:
        raise BenchmarkError(
            f"expected {count} stored rows, found {stored} (worker saved {worker.saved_count}, "
            f"duplicates {worker.duplicate_count})"
        )
    return StageResult("Redis to PostgreSQL", count, seconds)


class TimingSaver:
    """Wraps the real saver and notes how long each tick took to be committed."""

    def __init__(self, inner: PriceRepository) -> None:
        self._inner = inner
        self.latencies: list[float] = []

    async def save_ticks(self, ticks):
        saved = await self._inner.save_ticks(ticks)
        done = datetime.now(UTC)
        self.latencies.extend((done - tick.received_time).total_seconds() for tick in ticks)
        return saved


class TimingBoard(PriceBoard):
    """A price board that notes how long each tick took to reach it."""

    def __init__(self) -> None:
        super().__init__()
        self.latencies: list[float] = []

    async def on_tick(self, tick: PriceTick) -> None:
        self.latencies.append((datetime.now(UTC) - tick.received_time).total_seconds())
        await super().on_tick(tick)


async def bench_latency(
    redis: Redis,
    pool: asyncpg.Pool,
    stream: str,
    *,
    rate: int,
    duration: float,
    flush_interval: float,
    warmup: float = 0.1,
    seed: int = 1,
    timeout: float = 60.0,
) -> LatencyResult:
    """Offer ticks at a steady rate and time each one from creation to storage and to the board.

    Runs the real publisher (buffer + Redis), the real recorder worker and the real follower.
    The first `warmup` fraction of samples is dropped.
    """
    total = int(rate * duration)
    if rate < 1 or flush_interval <= 0 or not 0 <= warmup < 1 or total < 10:
        raise ValueError(
            "need rate >= 1, flush_interval > 0, 0 <= warmup < 1 and rate x duration >= 10"
        )

    await pool.execute("TRUNCATE prices")
    rng = random.Random(seed)
    publisher = Recorder(
        StreamTickSaver(redis, stream, maxlen=max(200_000, total * 2)),
        flush_interval=flush_interval,
        retry_on=(*Recorder.retry_on, *REDIS_RETRYABLE),
    )
    saver = TimingSaver(PriceRepository(pool))
    worker = StreamRecorder(
        redis,
        saver,
        stream=stream,
        group="bench",
        consumer="bench-1",
        block_ms=50,
        claim_every=3600.0,
    )
    board = TimingBoard()
    follower = MarketFollower(redis, board, stream=stream, block_ms=50)
    tasks = [asyncio.create_task(c.run()) for c in (publisher, worker, follower)]

    try:
        await asyncio.sleep(0.3)  # let the consumers start waiting
        started = time.perf_counter()
        offered = 0
        while offered < total:
            due = min(total, int((time.perf_counter() - started) * rate) + 1)
            while offered < due:
                await publisher.on_tick(make_tick(offered, rng))
                offered += 1
            await asyncio.sleep(0.001)
        keeping_up = time.perf_counter() - started <= duration * 1.2

        expected = total - publisher.dropped_count
        try:
            async with asyncio.timeout(timeout):
                while len(saver.latencies) < expected or len(board.latencies) < expected:
                    for task in tasks:
                        if task.done():
                            task.result()
                    await asyncio.sleep(0.01)
        except TimeoutError:
            raise BenchmarkError(
                f"not everything arrived within {timeout:.0f}s: database "
                f"{len(saver.latencies)}/{expected}, board {len(board.latencies)}/{expected}"
            ) from None

        def trimmed(values: list[float]) -> list[float]:
            return values[int(len(values) * warmup) :]

        return LatencyResult(
            rate=rate,
            duration=duration,
            flush_interval=flush_interval,
            published=total,
            dropped=publisher.dropped_count,
            delivered=len(saver.latencies),
            to_database=summarize(trimmed(saver.latencies)),
            to_board=summarize(trimmed(board.latencies)),
            keeping_up=keeping_up,
        )
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


def bench_checker(trade_count: int, seed: int = 7) -> StageResult:
    """Trades per second through the reconciliation engine. Also proves it still finds all 20 mistakes."""
    scenario = build_scenario(seed=seed, trade_count=trade_count)
    started = time.perf_counter()
    report = reconcile(
        scenario.ledger,
        scenario.statement,
        exchange=scenario.exchange,
        start=scenario.start,
        end=scenario.end,
    )
    seconds = time.perf_counter() - started
    expected = Counter((item.kind, item.trade_id) for item in scenario.injected)
    found = Counter((item.kind, item.trade_id) for item in report.breaks)
    if found != expected:
        raise BenchmarkError("the Checker did not report exactly the injected mistakes")
    return StageResult("reconciliation", len(scenario.statement), seconds)
