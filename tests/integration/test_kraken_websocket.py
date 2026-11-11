import asyncio
import json
from contextlib import suppress
from decimal import Decimal

from websockets.asyncio.server import serve

from deskpilot.ingestion import BackoffPolicy, KrakenFeed

FAST = BackoffPolicy(base=0.001, factor=1.0, cap=0.001, jitter=0.0)


def update(price):
    item = {"symbol": "BTC/USDT", "price": price, "timestamp": "2026-01-01T12:00:00.123456Z"}
    return json.dumps({"channel": "trade", "type": "update", "data": [item]})


async def test_subscribes_and_resubscribes_after_a_reconnect():
    subscriptions = []

    async def handler(connection):
        subscriptions.append(json.loads(await connection.recv()))
        number = len(subscriptions)
        await connection.send(json.dumps({"channel": "heartbeat"}))
        await connection.send(update(100 + number + 0.5))  # 101.5, then 102.5
        if number == 1:
            await connection.close(code=1011)  # an unclean close, like a server crash
        else:
            await connection.wait_closed()

    queue = asyncio.Queue()
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        feed = KrakenFeed(["BTC/USDT"], queue.put, url=f"ws://127.0.0.1:{port}", backoff=FAST)
        task = asyncio.create_task(feed.run())
        try:
            async with asyncio.timeout(5):
                first = await queue.get()
                second = await queue.get()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    assert [first.price, second.price] == [Decimal("101.5"), Decimal("102.5")]
    assert len(subscriptions) >= 2
    expected = json.loads(feed.subscribe_message)
    assert all(subscription == expected for subscription in subscriptions)
