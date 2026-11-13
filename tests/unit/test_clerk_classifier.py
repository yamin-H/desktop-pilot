import pytest

from deskpilot.clerk.classifier import classify
from deskpilot.clerk.models import Announcement, Category


def run(title, **kwargs):
    return classify(Announcement("demo", "https://x.test/1", title, "https://x.test/1"), **kwargs)


@pytest.mark.parametrize(
    ("title", "category", "assets", "important"),
    [
        ("Exchange will list ABC trading pair", Category.LISTING, (), False),
        ("Exchange will list Bitcoin perpetual contracts", Category.LISTING, ("BTC",), True),
        ("Exchange will delist XYZ and ABC", Category.DELISTING, (), False),
        ("Exchange will delist ETH/USDT margin pairs", Category.DELISTING, ("ETH",), True),
        ("bitcoin futures will be delisted", Category.DELISTING, ("BTC",), True),
        ("Scheduled maintenance for wallets on 2026-11-20", Category.MAINTENANCE, (), True),
        ("Deposits of BTC suspended during network upgrade", Category.MAINTENANCE, ("BTC",), True),
        ("Maintenance window: removal of ETH/BTC pair", Category.DELISTING, ("BTC", "ETH"), True),
        ("Weekly market update", Category.OTHER, (), False),
        ("Trading competition: win BTC prizes", Category.OTHER, ("BTC",), False),
        ("Ethereum staking guide", Category.OTHER, ("ETH",), False),
    ],
)
def test_classification(title, category, assets, important):
    result = run(title)
    assert (result.category, result.assets, result.important) == (category, assets, important)


def test_assets_are_matched_as_whole_words_only():
    assert run("Exchange will list ABTCX token").assets == ()


def test_a_custom_watchlist_can_be_used():
    result = run("Exchange will delist SOL pairs", watchlist={"SOL": ("sol", "solana")})
    assert (result.assets, result.important) == (("SOL",), True)


def test_the_original_announcement_is_kept():
    announcement = Announcement("demo", "https://x.test/9", "Hello", "https://x.test/9")
    assert classify(announcement).announcement is announcement
