import pytest

from deskpilot.clerk.alerts import AlertError
from deskpilot.clerk.fetcher import FetchError
from deskpilot.clerk.runner import check_source, run_clerk
from deskpilot.clerk.sources import SourceConfig
from deskpilot.clerk.store import AnnouncementStore

SOURCE = SourceConfig(name="demo", url="https://x.test/news", item_selector="li.item")
OTHER = SourceConfig(name="other", url="https://y.test/news", item_selector="li.item")


def page(*titles):
    items = "".join(
        f'<li class="item"><a href="https://x.test/{title.lower().replace(" ", "-")}">{title}</a></li>'
        for title in titles
    )
    return f"<ul>{items}</ul>"


MAINTENANCE = "Scheduled maintenance tonight"
LISTING_ABC = "Exchange will list ABC"  # not important: no watched asset
DELIST_ETH = "Exchange will delist ETH pairs"  # important


class FakeFetcher:
    """Plays back one page (or error) per call. The last one repeats."""

    def __init__(self, *pages):
        self._pages = list(pages)
        self.calls = 0

    async def fetch(self, source):
        self.calls += 1
        current = self._pages[min(self.calls - 1, len(self._pages) - 1)]
        if isinstance(current, Exception):
            raise current
        return current


class Recording:
    def __init__(self, failures=0):
        self.sent, self._failures = [], failures

    async def send(self, message):
        if self._failures:
            self._failures -= 1
            raise AlertError("channel down")
        self.sent.append(message)


async def test_the_first_check_is_a_baseline_and_sends_no_alerts(pool):
    store, alerter = AnnouncementStore(pool), Recording()
    result = await check_source(SOURCE, FakeFetcher(page(MAINTENANCE, DELIST_ETH)), store, alerter)
    assert (result.baseline, result.fetched, result.new, result.alerted) == (True, 2, 2, 0)
    assert alerter.sent == []
    assert await store.count("demo") == 2


async def test_later_checks_alert_once_for_new_important_announcements(pool):
    store, alerter = AnnouncementStore(pool), Recording()
    fetcher = FakeFetcher(page(LISTING_ABC), page(LISTING_ABC, MAINTENANCE, DELIST_ETH))
    await check_source(SOURCE, fetcher, store, alerter)

    second = await check_source(SOURCE, fetcher, store, alerter)
    assert (second.baseline, second.new, second.alerted) == (False, 2, 2)
    assert len(alerter.sent) == 2
    assert any(text.startswith("[MAINTENANCE]") for text in alerter.sent)
    assert any(text.startswith("[DELISTING]") and "Mentions: ETH" in text for text in alerter.sent)

    third = await check_source(SOURCE, fetcher, store, alerter)  # the same page again
    assert (third.new, third.alerted) == (0, 0)
    assert len(alerter.sent) == 2


async def test_unimportant_announcements_are_stored_but_never_alerted(pool):
    store, alerter = AnnouncementStore(pool), Recording()
    fetcher = FakeFetcher(page(MAINTENANCE), page(MAINTENANCE, LISTING_ABC))
    await check_source(SOURCE, fetcher, store, alerter)
    result = await check_source(SOURCE, fetcher, store, alerter)
    assert (result.new, result.alerted) == (1, 0)
    assert await store.count("demo") == 2


async def test_a_failed_alert_is_retried_next_time_without_duplicates(pool):
    store, alerter = AnnouncementStore(pool), Recording(failures=1)
    fetcher = FakeFetcher(page(LISTING_ABC), page(LISTING_ABC, DELIST_ETH))
    await check_source(SOURCE, fetcher, store, alerter)

    failed = await check_source(SOURCE, fetcher, store, alerter)
    assert (failed.new, failed.alerted) == (1, 0)
    assert "channel down" in failed.alert_error

    retried = await check_source(SOURCE, fetcher, store, alerter)
    assert (retried.new, retried.alerted, retried.alert_error) == (0, 1, None)
    await check_source(SOURCE, fetcher, store, alerter)
    assert len(alerter.sent) == 1  # delivered exactly once


@pytest.mark.parametrize(
    ("page_or_error", "expected"),
    [(FetchError("demo: HTTP 503"), "503"), ("<html><body>nothing</body></html>", "layout")],
)
async def test_a_source_that_cannot_be_read_is_reported_not_raised(pool, page_or_error, expected):
    result = await check_source(
        SOURCE, FakeFetcher(page_or_error), AnnouncementStore(pool), Recording()
    )
    assert expected in result.source_error
    assert (result.fetched, result.new) == (0, 0)


async def test_a_page_that_failed_to_parse_does_not_count_as_the_baseline(pool):
    store, alerter = AnnouncementStore(pool), Recording()
    fetcher = FakeFetcher("<html></html>", page(DELIST_ETH))
    await check_source(SOURCE, fetcher, store, alerter)
    result = await check_source(SOURCE, fetcher, store, alerter)
    assert result.baseline is True  # still the first successful read: no alert flood
    assert alerter.sent == []


async def no_sleep(seconds):
    pass


async def test_one_failing_source_does_not_stop_the_others(pool):
    store, alerter, results = AnnouncementStore(pool), Recording(), []

    class PerSource:
        async def fetch(self, source):
            if source.name == "demo":
                raise FetchError("demo: down")
            return page(MAINTENANCE)

    await run_clerk(
        [SOURCE, OTHER],
        PerSource(),
        store,
        alerter,
        max_cycles=1,
        on_result=results.append,
        sleep=no_sleep,
    )
    assert [(r.source, r.source_error is not None) for r in results] == [
        ("demo", True),
        ("other", False),
    ]


async def test_repeated_failures_alert_once_and_recovery_alerts_once(pool):
    boom = FetchError("demo: HTTP 500")
    fetcher = FakeFetcher(boom, boom, boom, boom, page(MAINTENANCE))
    alerter = Recording()
    await run_clerk(
        [SOURCE], fetcher, AnnouncementStore(pool), alerter, max_cycles=5, sleep=no_sleep
    )
    assert len(alerter.sent) == 2
    assert "failed 3 times in a row" in alerter.sent[0]
    assert "HTTP 500" in alerter.sent[0]
    assert "recovered" in alerter.sent[1]


async def test_the_loop_waits_between_cycles_but_not_after_the_last(pool):
    pauses = []

    async def record(seconds):
        pauses.append(seconds)

    await run_clerk(
        [SOURCE],
        FakeFetcher(page(MAINTENANCE)),
        AnnouncementStore(pool),
        Recording(),
        interval=100,
        max_cycles=3,
        sleep=record,
    )
    assert len(pauses) == 2
    assert all(90 <= pause <= 110 for pause in pauses)


async def test_a_failing_status_alert_does_not_break_the_loop(pool):
    boom = FetchError("demo: down")
    fetcher = FakeFetcher(boom, boom, boom, boom)
    alerter = Recording(failures=99)
    await run_clerk(
        [SOURCE], fetcher, AnnouncementStore(pool), alerter, max_cycles=4, sleep=no_sleep
    )
    assert fetcher.calls == 4
