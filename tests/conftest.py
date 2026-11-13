import asyncio
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from redis import exceptions as redis_errors

from deskpilot.bus.client import make_redis
from deskpilot.config import get_settings
from deskpilot.storage.db import create_pool
from deskpilot.storage.migrate import migrate

TEST_DB_NAME = "deskpilot_test"


def _with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest.fixture
async def stream_env():
    """A Redis connection plus stream names that belong to this test only (deleted afterwards)."""
    client = make_redis(get_settings().redis_url)
    try:
        await client.ping()
    except (OSError, redis_errors.RedisError) as exc:
        await client.aclose()
        pytest.skip(f"Redis is not reachable ({exc!r}). Start it with: make db-up")
    prefix = f"test:{uuid.uuid4().hex[:8]}"
    try:
        yield SimpleNamespace(redis=client, stream=f"{prefix}:ticks", dead=f"{prefix}:ticks:dead")
    finally:
        keys = [key async for key in client.scan_iter(match=f"{prefix}:*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def _recreate_test_database(admin_url: str) -> None:
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _migrate_test_database(test_url: str) -> None:
    conn = await asyncpg.connect(test_url)
    try:
        await migrate(conn)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """A brand-new, fully migrated test database. Skips if PostgreSQL is not running."""
    admin_url = get_settings().database_url
    test_url = _with_database(admin_url, TEST_DB_NAME)
    try:
        asyncio.run(_recreate_test_database(admin_url))
    except OSError as exc:  # connection refused, timeout, ...
        pytest.skip(f"PostgreSQL is not reachable ({exc!r}). Start it with: make db-up")
    asyncio.run(_migrate_test_database(test_url))
    return test_url


@pytest.fixture
async def pool(test_database_url):
    """A connection pool to the test database, with the prices table emptied first."""
    pool = await create_pool(test_database_url, min_size=1, max_size=4)
    await pool.execute("TRUNCATE prices, trades, documents, announcements CASCADE")
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def scratch(test_database_url):
    """A connection that works inside a throwaway schema.

    Migration-runner tests create their own little tables here, so they can never
    touch the real ones.
    """
    conn = await asyncpg.connect(test_database_url)
    await conn.execute("DROP SCHEMA IF EXISTS scratch CASCADE")
    await conn.execute("CREATE SCHEMA scratch")
    await conn.execute("SET search_path TO scratch")
    try:
        yield conn
    finally:
        await conn.execute("DROP SCHEMA IF EXISTS scratch CASCADE")
        await conn.close()
