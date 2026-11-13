from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from deskpilot.models import Exchange, PriceTick
from deskpilot.storage import PriceRepository

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def tick(price="100", *, exchange=Exchange.BINANCE, symbol="BTC/USDT", at=0):
    """`at` = seconds after T0 on the exchange's clock."""
    return PriceTick(
        exchange=exchange,
        symbol=symbol,
        price=price,
        exchange_time=T0 + timedelta(seconds=at),
        received_time=T0 + timedelta(seconds=at, milliseconds=5),
    )


async def test_latest_all_gives_the_newest_tick_per_exchange_and_symbol_within_the_window(pool):
    repo = PriceRepository(pool)
    now = datetime.now(UTC)

    def tk(exchange, symbol, price, seconds_ago):
        when = now - timedelta(seconds=seconds_ago)
        return PriceTick(
            exchange=exchange, symbol=symbol, price=price, exchange_time=when, received_time=when
        )

    await repo.save_ticks(
        [
            tk("binance", "BTC/USDT", "100", 30),
            tk("binance", "BTC/USDT", "101", 10),
            tk("kraken", "BTC/USDT", "99", 20),
            tk("binance", "ETH/USDT", "3000", 3600),  # outside the window
        ]
    )
    found = await repo.latest_all(timedelta(minutes=5))
    assert [(t.exchange.value, t.symbol, t.price) for t in found] == [
        ("binance", "BTC/USDT", Decimal("101")),
        ("kraken", "BTC/USDT", Decimal("99")),
    ]


async def count(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM prices")


async def test_saved_tick_can_be_read_back_exactly(pool):
    repo = PriceRepository(pool)
    original = tick("60000.10")
    assert await repo.save_ticks([original]) == 1
    assert await repo.latest(Exchange.BINANCE, "BTC/USDT") == original


async def test_saving_the_same_tick_twice_changes_nothing(pool):
    repo = PriceRepository(pool)
    assert await repo.save_ticks([tick()]) == 1
    assert await repo.save_ticks([tick()]) == 0
    assert await count(pool) == 1


async def test_a_duplicate_inside_one_batch_is_stored_once(pool):
    repo = PriceRepository(pool)
    assert await repo.save_ticks([tick(), tick()]) == 1
    assert await count(pool) == 1


async def test_a_batch_of_new_and_old_ticks_reports_only_the_new(pool):
    repo = PriceRepository(pool)
    await repo.save_ticks([tick(at=1)])
    assert await repo.save_ticks([tick(at=1), tick(at=2)]) == 1
    assert await count(pool) == 2


async def test_different_price_at_the_same_time_is_kept(pool):
    repo = PriceRepository(pool)
    assert await repo.save_ticks([tick("100"), tick("101")]) == 2


async def test_other_exchange_or_symbol_is_a_separate_record(pool):
    repo = PriceRepository(pool)
    batch = [
        tick(),
        tick(exchange=Exchange.KRAKEN),
        tick(symbol="ETH/USDT"),
    ]
    assert await repo.save_ticks(batch) == 3


async def test_saving_nothing_is_fine(pool):
    assert await PriceRepository(pool).save_ticks([]) == 0


async def test_every_digit_of_a_price_survives(pool):
    repo = PriceRepository(pool)
    await repo.save_ticks([tick("0.12345678901234567890")])
    saved = await repo.latest(Exchange.BINANCE, "BTC/USDT")
    assert saved.price == Decimal("0.12345678901234567890")


async def test_times_come_back_in_utc(pool):
    repo = PriceRepository(pool)
    bangladesh = timezone(timedelta(hours=6))
    original = PriceTick(
        exchange=Exchange.BINANCE,
        symbol="BTC/USDT",
        price="100",
        exchange_time=datetime(2026, 1, 1, 18, 0, tzinfo=bangladesh),  # = 12:00 UTC
        received_time=datetime(2026, 1, 1, 18, 0, 1, tzinfo=bangladesh),
    )
    await repo.save_ticks([original])
    saved = await repo.latest(Exchange.BINANCE, "BTC/USDT")
    assert saved.exchange_time == T0
    assert saved.exchange_time.utcoffset() == timedelta(0)


async def test_latest_is_the_newest_by_exchange_time_not_by_save_order(pool):
    repo = PriceRepository(pool)
    await repo.save_ticks([tick("105", at=5)])
    await repo.save_ticks([tick("101", at=1)])  # an older tick arrives later
    saved = await repo.latest(Exchange.BINANCE, "BTC/USDT")
    assert saved.price == Decimal("105")


async def test_latest_only_looks_at_the_asked_exchange_and_symbol(pool):
    repo = PriceRepository(pool)
    await repo.save_ticks([tick("100"), tick("999", exchange=Exchange.KRAKEN, at=9)])
    saved = await repo.latest(Exchange.BINANCE, "BTC/USDT")
    assert saved.price == Decimal("100")
    assert await repo.latest(Exchange.BINANCE, "ETH/USDT") is None


async def test_latest_is_none_when_nothing_is_stored(pool):
    assert await PriceRepository(pool).latest(Exchange.BINANCE, "BTC/USDT") is None


async def test_a_large_batch_is_saved_in_one_go(pool):
    repo = PriceRepository(pool)
    batch = [tick(str(100 + i), at=i) for i in range(1000)]
    assert await repo.save_ticks(batch) == 1000
    assert await count(pool) == 1000
