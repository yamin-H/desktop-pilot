"""Show the state of the tick stream: size, consumer groups, backlog, dead letters.

Usage: uv run python scripts/stream_status.py
"""

import asyncio
import sys

from redis import exceptions as redis_errors

from deskpilot.bus import make_redis
from deskpilot.config import get_settings


async def main() -> int:
    settings = get_settings()
    redis = make_redis(settings.redis_url)
    stream = settings.tick_stream
    try:
        length = await redis.xlen(stream)
        print(
            f"stream {stream}: {length:,} entries (capped at about {settings.tick_stream_maxlen:,})"
        )
        try:
            groups = await redis.xinfo_groups(stream)
        except redis_errors.ResponseError:
            groups = []
        for group in groups:
            lag = group.get("lag")
            print(
                f"group {group['name']}: consumers {group['consumers']}, "
                f"pending {group['pending']}, lag {'?' if lag is None else lag}"
            )
        if not groups:
            print("no consumer groups yet")
        print(f"dead letters: {await redis.xlen(f'{stream}:dead')}")
        return 0
    except (OSError, redis_errors.RedisError) as error:
        print(f"Cannot reach Redis ({error}). Run: make db-up")
        return 2
    finally:
        await redis.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
