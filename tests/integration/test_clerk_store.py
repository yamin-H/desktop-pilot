from datetime import UTC, datetime

from deskpilot.clerk.models import Announcement, Category, Classified
from deskpilot.clerk.store import AnnouncementStore

T0 = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


def item(n, *, important=True, source="demo", category=Category.MAINTENANCE, assets=()):
    url = f"https://x.test/{n}"
    return Classified(
        Announcement(source, url, f"Title {n}", url, T0), category, tuple(assets), important
    )


async def test_only_new_announcements_are_returned_and_repeats_change_nothing(pool):
    store = AnnouncementStore(pool)
    assert await store.save_new([item(1), item(2)]) == [item(1), item(2)]
    assert await store.save_new([item(2), item(3)]) == [item(3)]
    assert await store.count("demo") == 3
    assert await store.count("other") == 0


async def test_the_same_url_from_another_source_is_a_different_announcement(pool):
    store = AnnouncementStore(pool)
    await store.save_new([item(1)])
    assert len(await store.save_new([item(1, source="other")])) == 1


async def test_important_unalerted_items_are_pending_in_arrival_order(pool):
    store = AnnouncementStore(pool)
    await store.save_new([item(3), item(1, important=False), item(2)])
    assert [p.announcement.external_id for p in await store.pending_alerts("demo")] == [
        "https://x.test/3",
        "https://x.test/2",
    ]


async def test_a_baseline_save_marks_everything_as_alerted(pool):
    store = AnnouncementStore(pool)
    await store.save_new([item(1), item(2)], baseline=True)
    assert await store.pending_alerts("demo") == []
    assert await store.count("demo") == 2


async def test_a_marked_item_is_no_longer_pending(pool):
    store = AnnouncementStore(pool)
    await store.save_new([item(1), item(2)])
    await store.mark_alerted(item(1))
    assert [p.announcement.external_id for p in await store.pending_alerts("demo")] == [
        "https://x.test/2"
    ]


async def test_everything_survives_a_round_trip(pool):
    store = AnnouncementStore(pool)
    original = item(1, category=Category.DELISTING, assets=("BTC", "ETH"))
    await store.save_new([original])
    assert await store.pending_alerts("demo") == [original]


async def test_recent_items_come_newest_first_and_can_be_filtered(pool):
    store = AnnouncementStore(pool)
    await store.save_new([item(1), item(2, important=False)])
    await store.save_new([item(3)])
    assert [i.announcement.title for i in await store.list_recent()] == [
        "Title 3",
        "Title 2",
        "Title 1",
    ]
    assert [i.announcement.title for i in await store.list_recent(important_only=True)] == [
        "Title 3",
        "Title 1",
    ]
    assert len(await store.list_recent(limit=1)) == 1
