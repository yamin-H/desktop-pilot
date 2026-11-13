"""Redis stream -> PostgreSQL. Safe to stop, kill or run several copies of.

Usage: uv run python scripts/run_recorder.py [--name NAME]
Give each copy its own --name. A restarted worker with the same name resumes its own
unfinished work at once; other workers take it over after it has been idle for 30 seconds.
"""

import argparse
import asyncio
import logging
import socket
import sys
from contextlib import suppress
from datetime import UTC, datetime

from redis import exceptions as redis_errors

from deskpilot.bus import StreamRecorder, make_redis
from deskpilot.config import get_settings
from deskpilot.storage import PriceRepository, create_pool


def status_line(worker: StreamRecorder) -> str:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    return (
        f"{stamp}  saved {worker.saved_count}  duplicates {worker.duplicate_count}  "
        f"claimed {worker.claimed_count}  dead {worker.dead_count}  lost {worker.lost_count}  "
        f"retries {worker.retry_count}"
    )


async def report(worker: StreamRecorder, every: float = 5.0) -> None:
    while True:
        await asyncio.sleep(every)
        print(status_line(worker), flush=True)


async def main(name: str) -> int:
    settings = get_settings()
    redis = make_redis(settings.redis_url)
    try:
        await redis.ping()
        pool = await create_pool(settings.database_url)
    except (OSError, redis_errors.RedisError) as error:
        print(f"Cannot start ({error}). Run: make db-up && make migrate")
        await redis.aclose()
        return 2

    worker = StreamRecorder(
        redis, PriceRepository(pool), stream=settings.tick_stream, consumer=name
    )
    print(f"recorder worker {name!r} reading {settings.tick_stream!r}")
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(worker.run())
            group.create_task(report(worker))
    finally:
        print("stopped. " + status_line(worker))
        await pool.close()
        await redis.aclose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redis stream to PostgreSQL recorder.")
    parser.add_argument("--name", default=f"recorder-{socket.gethostname()}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main(parser.parse_args().name)))
