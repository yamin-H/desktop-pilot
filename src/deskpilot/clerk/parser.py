import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from deskpilot.clerk.models import Announcement
from deskpilot.clerk.sources import SourceConfig

MAX_TITLE = 500


class ParseError(Exception):
    """The page could not be read."""


class LayoutChanged(ParseError):
    """The page loaded but our selector found nothing: the site's layout probably changed."""


@dataclass(frozen=True)
class ParseResult:
    items: tuple[Announcement, ...]
    skipped: int  # elements without a usable title or link, and repeated links


def _text(element: Tag) -> str:
    return " ".join(element.get_text(" ").split())


def _date(item: Tag, source: SourceConfig) -> datetime | None:
    if not source.date_selector:
        return None
    element = item.select_one(source.date_selector)
    if element is None:
        return None
    raw = element.get(source.date_attribute) if source.date_attribute else _text(element)
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None  # an unreadable date is not worth losing the announcement
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def parse_announcements(html: str, source: SourceConfig) -> ParseResult:
    """Read announcements from a page using the source's CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    elements = soup.select(source.item_selector)
    if not elements:
        raise LayoutChanged(
            f"{source.name}: selector {source.item_selector!r} matched nothing; "
            "the page layout may have changed"
        )

    items: dict[str, Announcement] = {}
    skipped = 0
    for element in elements:
        title_element = element.select_one(source.title_selector)
        link_element = element.select_one(source.link_selector)
        href = link_element.get("href") if link_element is not None else None
        title = re.sub(r"\s+", " ", _text(title_element)) if title_element is not None else ""
        if not title or not isinstance(href, str):
            skipped += 1
            continue

        url = urldefrag(urljoin(source.url, href.strip()))[0]
        if urlparse(url).scheme not in ("http", "https") or url in items:
            skipped += 1  # javascript:, mailto: and repeated links
            continue
        items[url] = Announcement(
            source=source.name,
            external_id=url,
            title=title[:MAX_TITLE],
            url=url,
            published_at=_date(element, source),
        )
    return ParseResult(tuple(items.values()), skipped)
