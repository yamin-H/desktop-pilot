from pathlib import Path

import asyncpg
import pytest

from deskpilot.storage.migrate import LOCK_ID, MigrationError, migrate


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


async def table_exists(conn, name: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1)", name) is not None


async def test_applies_migrations_in_order_and_records_them(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "CREATE TABLE a (id int);")
    write(tmp_path, "002_b.sql", "CREATE TABLE b (id int);")

    assert await migrate(scratch, tmp_path) == ["001_a.sql", "002_b.sql"]

    assert await table_exists(scratch, "a")
    assert await table_exists(scratch, "b")
    recorded = await scratch.fetch("SELECT name FROM schema_migrations ORDER BY name")
    assert [row["name"] for row in recorded] == ["001_a.sql", "002_b.sql"]


async def test_running_twice_applies_nothing_the_second_time(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "CREATE TABLE a (id int);")
    await migrate(scratch, tmp_path)
    assert await migrate(scratch, tmp_path) == []


async def test_only_new_migrations_are_applied_later(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "CREATE TABLE a (id int);")
    await migrate(scratch, tmp_path)
    write(tmp_path, "002_b.sql", "CREATE TABLE b (id int);")
    assert await migrate(scratch, tmp_path) == ["002_b.sql"]


async def test_a_failing_migration_leaves_nothing_behind(scratch, tmp_path):
    write(tmp_path, "001_bad.sql", "CREATE TABLE half_done (id int); SELECT 1/0;")

    with pytest.raises(asyncpg.DivisionByZeroError):
        await migrate(scratch, tmp_path)

    assert not await table_exists(scratch, "half_done")
    assert await scratch.fetchval("SELECT count(*) FROM schema_migrations") == 0


async def test_editing_an_applied_migration_is_refused(scratch, tmp_path):
    write(tmp_path, "001_a.sql", "CREATE TABLE a (id int);")
    await migrate(scratch, tmp_path)
    write(tmp_path, "001_a.sql", "CREATE TABLE a (id int, extra int);")

    with pytest.raises(MigrationError, match="was changed"):
        await migrate(scratch, tmp_path)


async def test_the_lock_is_released_even_when_a_migration_fails(
    scratch, test_database_url, tmp_path
):
    write(tmp_path, "001_bad.sql", "SELECT 1/0;")
    with pytest.raises(asyncpg.DivisionByZeroError):
        await migrate(scratch, tmp_path)

    other = await asyncpg.connect(test_database_url)  # a different connection
    try:
        assert await other.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_ID) is True
    finally:
        await other.close()
