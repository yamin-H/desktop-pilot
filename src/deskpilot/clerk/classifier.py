import re
from collections.abc import Mapping

from deskpilot.clerk.models import Announcement, Category, Classified

# Asset -> names it may appear under in a title. Whole words only.
DEFAULT_WATCHLIST: Mapping[str, tuple[str, ...]] = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum"),
}

_DELISTING = re.compile(
    r"\bdelist|\bremoval of\b|\bwill remove\b|\bcease trading\b|\bdiscontinu", re.IGNORECASE
)
_MAINTENANCE = re.compile(
    r"\bmaintenance\b|\bupgrade\b|\bdowntime\b|\bsuspen|\bhalt", re.IGNORECASE
)
_LISTING = re.compile(
    r"\bwill list\b|\bnew listing\b|\blisting of\b|\bwill add\b|\blists\b|\bnow available\b",
    re.IGNORECASE,
)


def _mentions(title: str, aliases: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(alias)}\b", title, re.IGNORECASE) for alias in aliases)


def classify(
    announcement: Announcement, watchlist: Mapping[str, tuple[str, ...]] = DEFAULT_WATCHLIST
) -> Classified:
    """Decide what an announcement is about and whether it deserves an alert.

    Rules (delisting is checked first, then maintenance, then listing):
    - maintenance is always important (it can affect our feeds and withdrawals)
    - delistings and listings are important only if they mention a watched asset
    """
    title = announcement.title
    if _DELISTING.search(title):
        category = Category.DELISTING
    elif _MAINTENANCE.search(title):
        category = Category.MAINTENANCE
    elif _LISTING.search(title):
        category = Category.LISTING
    else:
        category = Category.OTHER

    assets = tuple(sorted(asset for asset, names in watchlist.items() if _mentions(title, names)))
    important = category is Category.MAINTENANCE or (
        category in (Category.DELISTING, Category.LISTING) and bool(assets)
    )
    return Classified(announcement, category, assets, important)
