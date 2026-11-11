import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from deskpilot.config import get_settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
LOCK_ID = 7_201_001  # any fixed number: "only one migration runner at a time"

_NAME = re.compile(r"(\d{3})_[a-z0-9_]+\.sql")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       text        PRIMARY KEY,
    checksum   text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    """Something is wrong with the migration files or their history."""


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read migration files, in order. File names look like 001_something.sql."""
    migrations: list[Migration] = []
    numbers: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"bad migration file name {path.name!r} (use 001_name.sql)")
        number = match.group(1)
        if number in numbers:
            raise MigrationError(
                f"two migrations share number {number}: {numbers[number]} and {path.name}"
            )
        numbers[number] = path.name
        # Normalise line endings, so Windows and Linux compute the same checksum.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        migrations.append(Migration(path.name, text))
    return migrations


async def migrate(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration not yet applied, in order. Returns the names applied."""
    migrations = load_migrations(directory)

    await conn.execute("SELECT pg_advisory_lock($1)", LOCK_ID)
    try:
        await conn.execute(_CREATE_TABLE)
        rows = await conn.fetch("SELECT name, checksum FROM schema_migrations")
        applied = {row["name"]: row["checksum"] for row in rows}

        newly_applied: list[str] = []
        for migration in migrations:
            recorded = applied.get(migration.name)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationError(
                        f"{migration.name} was changed after it was applied. "
                        "Never edit an applied migration; add a new one instead."
                    )
                continue

            # All of the migration or none of it: a failure leaves no half-built tables.
            async with conn.transaction():
                await conn.execute(migration.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (name, checksum) VALUES ($1, $2)",
                    migration.name,
                    migration.checksum,
                )
            logger.info("applied migration %s", migration.name)
            newly_applied.append(migration.name)
        return newly_applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_ID)


async def _main() -> None:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        applied = await migrate(conn)
    finally:
        await conn.close()
    print(f"applied: {', '.join(applied)}" if applied else "database is already up to date")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(_main())
