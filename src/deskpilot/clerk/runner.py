import asyncio
import logging
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from deskpilot.clerk.alerts import Alerter, AlertError, format_alert
from deskpilot.clerk.classifier import DEFAULT_WATCHLIST, classify
from deskpilot.clerk.fetcher import Fetcher, FetchError
from deskpilot.clerk.parser import ParseError, parse_announcements
from deskpilot.clerk.sources import SourceConfig
from deskpilot.clerk.store import AnnouncementStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceResult:
    source: str
    fetched: int = 0  # announcements read from the page
    new: int = 0  # announcements we had not seen
    alerted: int = 0  # alerts delivered in this check
    baseline: bool = False  # first ever fetch of this source: stored, no alerts
    source_error: str | None = None  # the page could not be fetched or read
    alert_error: str | None = None  # an alert could not be delivered (retried next time)


async def check_source(
    source: SourceConfig,
    fetcher: Fetcher,
    store: AnnouncementStore,
    alerter: Alerter,
    watchlist: Mapping[str, tuple[str, ...]] = DEFAULT_WATCHLIST,
) -> SourceResult:
    """One check of one source. Save first, then alert, so a failed alert is retried."""
    try:
        html = await fetcher.fetch(source)
        parsed = parse_announcements(html, source)
    except (FetchError, ParseError) as error:
        return SourceResult(source.name, source_error=str(error))

    classified = [classify(announcement, watchlist) for announcement in parsed.items]
    baseline = await store.count(source.name) == 0
    new = await store.save_new(classified, baseline=baseline)

    alerted = 0
    alert_error = None
    for item in await store.pending_alerts(source.name):
        try:
            await alerter.send(format_alert(item))
        except AlertError as error:
            alert_error = str(error)
            break  # stop here, the rest stay pending for the next check
        await store.mark_alerted(item)
        alerted += 1
    return SourceResult(
        source.name, len(classified), len(new), alerted, baseline, alert_error=alert_error
    )


async def _notify(alerter: Alerter, message: str) -> None:
    try:
        await alerter.send(message)
    except AlertError as error:
        logger.warning("could not send a status alert: %s", error)


async def run_clerk(
    sources: Sequence[SourceConfig],
    fetcher: Fetcher,
    store: AnnouncementStore,
    alerter: Alerter,
    watchlist: Mapping[str, tuple[str, ...]] = DEFAULT_WATCHLIST,
    *,
    interval: float = 300.0,
    max_cycles: int | None = None,
    failure_alert_after: int = 3,
    on_result: Callable[[SourceResult], None] | None = None,
    sleep: Callable[[float], object] = asyncio.sleep,
) -> None:
    """Check every source, wait, repeat. A failing source never stops the others.

    After `failure_alert_after` failures in a row for one source, one alert says so; one more
    says when it recovers. Runs until cancelled (or `max_cycles`).
    """
    failures = {source.name: 0 for source in sources}
    warned: set[str] = set()
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        for source in sources:
            result = await check_source(source, fetcher, store, alerter, watchlist)
            if on_result is not None:
                on_result(result)

            if result.source_error is None:
                failures[source.name] = 0
                if source.name in warned:
                    warned.discard(source.name)
                    await _notify(alerter, f"Announcement source {source.name} has recovered.")
                continue
            failures[source.name] += 1
            if failures[source.name] == failure_alert_after and source.name not in warned:
                warned.add(source.name)
                await _notify(
                    alerter,
                    f"Announcement source {source.name} has failed {failure_alert_after} times "
                    f"in a row: {result.source_error}",
                )
        if max_cycles is not None and cycle >= max_cycles:
            break
        await sleep(interval * random.uniform(0.9, 1.1))  # a little jitter, like the feeds
