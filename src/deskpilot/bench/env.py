import os
import platform
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from redis.asyncio import Redis

from deskpilot.storage import create_pool
from deskpilot.storage.migrate import migrate


def _with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@asynccontextmanager
async def temporary_database(
    admin_url: str, name: str = "deskpilot_bench"
) -> AsyncIterator[asyncpg.Pool]:
    """A fresh, fully migrated database that is dropped afterwards. Dev data is never touched."""
    quoted = '"' + name.replace('"', '""') + '"'

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_url)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    await admin(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)")
    await admin(f"CREATE DATABASE {quoted}")
    url = _with_database(admin_url, name)
    conn = await asyncpg.connect(url)
    try:
        await migrate(conn)
    finally:
        await conn.close()
    pool = await create_pool(url, min_size=2, max_size=8)
    try:
        yield pool
    finally:
        await pool.close()
        await admin(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)")


@asynccontextmanager
async def temporary_stream(redis: Redis) -> AsyncIterator[str]:
    """A uniquely named stream. Every key under its prefix is deleted afterwards."""
    prefix = f"bench:{uuid.uuid4().hex[:8]}"
    try:
        yield f"{prefix}:ticks"
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
        if keys:
            await redis.delete(*keys)


async def describe_environment(redis: Redis, pool: asyncpg.Pool) -> dict[str, str]:
    """Where the numbers were measured. Without this, a benchmark means nothing."""
    redis_info = await redis.info("server")
    return {
        "python": platform.python_version(),
        "system": f"{platform.system()} {platform.release()}",
        "cpu": f"{os.cpu_count()} logical cores",
        "postgresql": await pool.fetchval("SHOW server_version"),
        "redis": str(redis_info.get("redis_version", "?")),
    }
