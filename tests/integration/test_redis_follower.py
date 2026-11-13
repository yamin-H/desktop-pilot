import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from deskpilot.analytics import PriceBoard
from deskpilot.bus.follower import MarketFollower
from deskpilot.bus.publisher import StreamTickSaver
from deskpilot.models import Exchange, PriceTick

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def tick(exchange, price, seconds):
    when = T0 + timedelta(seconds=seconds)
    return PriceTick(
        exchange=exchange, symbol="BTC/USDT", price=price, exchange_time=when, received_time=when
    )


async def until(check, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.02)


async def test_the_follower_starts_from_history_and_then_follows_new_ticks(stream_env):
    saver = StreamTickSaver(stream_env.redis, stream_env.stream)
    await saver.save_ticks([tick("binance", "100", 1), tick("kraken", "99", 2)])

    board = PriceBoard()
    follower = MarketFollower(stream_env.redis, board, stream=stream_env.stream, block_ms=50)
    task = asyncio.create_task(follower.run())
    try:
        await until(lambda: len(board.ticks()) == 2)  # filled from history
        assert str(board.latest(Exchange.BINANCE, "BTC/USDT").price) == "100"

        await saver.save_ticks([tick("binance", "101", 3)])
        await until(lambda: str(board.latest(Exchange.BINANCE, "BTC/USDT").price) == "101")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
