from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Category(StrEnum):
    LISTING = "listing"
    DELISTING = "delisting"
    MAINTENANCE = "maintenance"
    OTHER = "other"


@dataclass(frozen=True)
class Announcement:
    source: str  # which configured source it came from
    external_id: str  # stable identity: the absolute URL
    title: str
    url: str
    published_at: datetime | None = None


@dataclass(frozen=True)
class Classified:
    announcement: Announcement
    category: Category
    assets: tuple[str, ...]  # watched assets the title mentions
    important: bool  # worth an alert
