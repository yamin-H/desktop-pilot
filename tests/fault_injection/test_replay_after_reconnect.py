import asyncio
import json
from contextlib import suppress
from decimal import Decimal

from websockets.asyncio.server import serve

from deskpilot.ingestion import BackoffPolicy, BinanceFeed
from deskpilot.storage import PriceRepository, Recorder

FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)
BASE_MS = 1767268800123


def trade(price: str, offset_ms: int) -> str:
    event = {"e": "trade", "s": "BTCUSDT", "p": price, "T": BASE_MS + offset_ms}
    return json.dumps({"stream": "btcusdt@trade", "data": event})


# The same history on every connection, with two kinds of damage:
HISTORY = [
    trade("100", 0),
    trade("102", 2),
    trade("101", 1),  # arrives late: out of order
    trade("102", 2),  # arrives twice
]
# 3 distinct prices per connection, 4 messages, 3 connections = 12 ticks in total.


async def test_dropped_connections_replays_duplicates_and_disorder_leave_the_database_correct(
    pool,
):
    connections = 0

    async def handler(connection):
        nonlocal connections
        connections += 1
        for message in HISTORY:
            await connection.send(message)
        if connections < 3:
            await connection.close(code=1011)  # drop the connection, like a server crash
        else:
            await connection.wait_closed()

    recorder = Recorder(PriceRepository(pool), batch_size=50, flush_interval=0.02)
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        feed = BinanceFeed(
            ["BTC/USDT"], recorder.on_tick, base_url=f"ws://127.0.0.1:{port}", backoff=FAST
        )
        tasks = [asyncio.create_task(feed.run()), asyncio.create_task(recorder.run())]
        try:
            async with asyncio.timeout(10):
                while recorder.saved_count + recorder.duplicate_count < 12:
                    await asyncio.sleep(0.01)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await recorder.drain()

    assert feed.reconnect_count >= 2
    rows = await pool.fetch("SELECT price FROM prices ORDER BY exchange_time")
    assert [row["price"] for row in rows] == [Decimal("100"), Decimal("101"), Decimal("102")]
    assert recorder.saved_count == 3
    assert recorder.duplicate_count == 9
