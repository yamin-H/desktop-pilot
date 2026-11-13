from collections.abc import Sequence

import asyncpg

from deskpilot.clerk.models import Announcement, Category, Classified

_INSERT = """
INSERT INTO announcements
    (source, external_id, title, url, published_at, category, assets, important, alerted_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CASE WHEN $9 THEN now() END)
ON CONFLICT (source, external_id) DO NOTHING
RETURNING 1
"""

_COLUMNS = "source, external_id, title, url, published_at, category, assets, important"


def _to_classified(row: asyncpg.Record) -> Classified:
    return Classified(
        announcement=Announcement(
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
        ),
        category=Category(row["category"]),
        assets=tuple(row["assets"]),
        important=row["important"],
    )


class AnnouncementStore:
    """Saves announcements and remembers which ones were already alerted."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def count(self, source: str) -> int:
        return await self._pool.fetchval(
            "SELECT count(*) FROM announcements WHERE source = $1", source
        )

    async def save_new(
        self, items: Sequence[Classified], *, baseline: bool = False
    ) -> list[Classified]:
        """Store announcements we have not seen. Returns the new ones.

        With `baseline`, the new ones are marked as already alerted (used on a source's first
        fetch, so the existing backlog does not trigger a flood of alerts).
        """
        new: list[Classified] = []
        async with self._pool.acquire() as conn, conn.transaction():
            for item in items:
                a = item.announcement
                inserted = await conn.fetchval(
                    _INSERT,
                    a.source,
                    a.external_id,
                    a.title,
                    a.url,
                    a.published_at,
                    item.category.value,
                    list(item.assets),
                    item.important,
                    baseline,
                )
                if inserted:
                    new.append(item)
        return new

    async def pending_alerts(self, source: str) -> list[Classified]:
        """Important announcements that were stored but not alerted yet, oldest first."""
        rows = await self._pool.fetch(
            f"SELECT {_COLUMNS} FROM announcements "
            "WHERE source = $1 AND important AND alerted_at IS NULL "
            "ORDER BY first_seen_at, external_id",
            source,
        )
        return [_to_classified(row) for row in rows]

    async def mark_alerted(self, item: Classified) -> None:
        await self._pool.execute(
            "UPDATE announcements SET alerted_at = now() WHERE source = $1 AND external_id = $2",
            item.announcement.source,
            item.announcement.external_id,
        )

    async def list_recent(
        self, limit: int = 20, *, important_only: bool = False
    ) -> list[Classified]:
        rows = await self._pool.fetch(
            f"SELECT {_COLUMNS} FROM announcements "
            "WHERE ($1 = false OR important) ORDER BY first_seen_at DESC, external_id LIMIT $2",
            important_only,
            limit,
        )
        return [_to_classified(row) for row in rows]
