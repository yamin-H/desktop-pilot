import asyncio
import json
from contextlib import suppress
from decimal import Decimal

from websockets.asyncio.server import serve

from deskpilot.ingestion import BackoffPolicy, BinanceFeed

FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)


def trade(price):
    event = {"e": "trade", "s": "BTCUSDT", "p": price, "T": 1767268800123}
    return json.dumps({"stream": "btcusdt@trade", "data": event})


async def test_receives_ticks_and_reconnects_over_a_real_websocket():
    connections = 0

    async def handler(connection):
        nonlocal connections
        connections += 1
        await connection.send(trade(str(100 + connections)))
        if connections == 1:
            await connection.close(code=1011)  # an unclean close, like a server crash
        else:
            await connection.wait_closed()

    queue = asyncio.Queue()
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        feed = BinanceFeed(["BTC/USDT"], queue.put, base_url=f"ws://127.0.0.1:{port}", backoff=FAST)
        task = asyncio.create_task(feed.run())
        try:
            async with asyncio.timeout(5):
                first = await queue.get()
                second = await queue.get()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    assert [first.price, second.price] == [Decimal("101"), Decimal("102")]
    assert feed.reconnect_count >= 1
