import random

from deskpilot.bench.data import binance_message, kraken_message, make_tick, make_ticks
from deskpilot.ingestion import BinanceFeed, KrakenFeed
from deskpilot.models import PriceTick


async def ignore(tick):
    pass


def test_generated_ticks_are_deterministic_and_all_different():
    first, second = make_ticks(200, seed=3), make_ticks(200, seed=3)
    assert first == second
    assert make_ticks(200, seed=4) != first
    assert len({(t.exchange, t.symbol, t.exchange_time, t.price) for t in first}) == 200


def test_ticks_cover_both_exchanges_and_both_pairs():
    ticks = make_ticks(8)
    assert {(t.exchange.value, t.symbol) for t in ticks} == {
        ("binance", "BTC/USDT"),
        ("binance", "ETH/USDT"),
        ("kraken", "BTC/USDT"),
        ("kraken", "ETH/USDT"),
    }


def test_a_tick_is_created_now_unless_told_otherwise():
    tick = make_tick(0, random.Random(1))
    assert isinstance(tick, PriceTick)
    assert tick.received_time is not None


def test_generated_binance_messages_are_readable_by_the_real_feed():
    rng = random.Random(1)
    feed = BinanceFeed(["BTC/USDT", "ETH/USDT"], ignore)
    ticks = [tick for i in range(10) for tick in feed.parse(binance_message(i, rng))]
    assert len(ticks) == 10
    assert {t.symbol for t in ticks} == {"BTC/USDT", "ETH/USDT"}


def test_generated_kraken_messages_are_readable_by_the_real_feed():
    rng = random.Random(1)
    feed = KrakenFeed(["BTC/USDT", "ETH/USDT"], ignore)
    ticks = [tick for i in range(10) for tick in feed.parse(kraken_message(i, rng))]
    assert len(ticks) == 10
    assert {t.symbol for t in ticks} == {"BTC/USDT", "ETH/USDT"}
