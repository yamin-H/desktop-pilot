from collections.abc import Sequence
from redis.asyncio import Redis
from deskpilot.bus.codec import encode_tick
from deskpilot.models import PriceTick


class StreamTickSaver:
    """Publishes ticks to a Redis stream. Plugs into Recorder, which adds buffering and retry.

    Publishing is at-least-once: if a batch fails halfway it is sent again, so a tick can
    appear twice in the stream. Consumers must (and do) tolerate that.
    """

    def __init__(self, redis: Redis, stream: str = "ticks", maxlen: int = 200_000) -> None:
        if maxlen < 1:
            raise ValueError("maxlen must be at least 1")
        self._redis = redis
        self._stream = stream
        self._maxlen = maxlen

    async def save_ticks(self, ticks: Sequence[PriceTick]) -> int:
        if not ticks:
            return 0
        async with self._redis.pipeline(transaction=False) as pipe:  # one round trip
            for tick in ticks:
                pipe.xadd(self._stream, encode_tick(tick), maxlen=self._maxlen, approximate=True)
            await pipe.execute()
        return len(ticks)