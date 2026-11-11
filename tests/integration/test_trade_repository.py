from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
import pytest

from deskpilot.models import Exchange, Trade
from deskpilot.storage import TradeRepository

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def trade(**overrides):
    data = {
        "exchange": "binance",
        "trade_id": "T-1",
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": "0.002",
        "price": "60000.10",
        "fee": "0.12",
        "fee_asset": "USDT",
        "executed_at": T0,
    }
    data.update(overrides)
    return Trade(**data)


async def count(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM trades")


def ids(trades) -> list[str]:
    return [t.trade_id for t in trades]


async def test_saved_trade_can_be_read_back_exactly(pool):
    repo = TradeRepository(pool)
    original = trade()
    result = await repo.save_trades([original])
    assert (result.inserted, result.duplicates, result.conflicts) == (1, 0, ())
    assert await repo.get(Exchange.BINANCE, "T-1") == original


async def test_saving_the_same_trade_twice_changes_nothing(pool):
    repo = TradeRepository(pool)
    await repo.save_trades([trade()])
    result = await repo.save_trades([trade()])
    assert (result.inserted, result.duplicates, result.conflicts) == (0, 1, ())
    assert await count(pool) == 1


async def test_a_batch_of_new_and_known_trades_is_counted_correctly(pool):
    repo = TradeRepository(pool)
    await repo.save_trades([trade(trade_id="T-1")])
    result = await repo.save_trades([trade(trade_id="T-1"), trade(trade_id="T-2")])
    assert (result.inserted, result.duplicates) == (1, 1)
    assert await count(pool) == 2


async def test_an_identical_repeat_inside_one_batch_is_a_duplicate(pool):
    repo = TradeRepository(pool)
    result = await repo.save_trades([trade(), trade()])
    assert (result.inserted, result.duplicates, result.conflicts) == (1, 1, ())


async def test_the_same_id_on_another_exchange_is_a_different_trade(pool):
    repo = TradeRepository(pool)
    result = await repo.save_trades([trade(), trade(exchange="kraken")])
    assert result.inserted == 2


async def test_same_numbers_written_differently_are_not_a_conflict(pool):
    repo = TradeRepository(pool)
    await repo.save_trades([trade(quantity="0.002")])
    result = await repo.save_trades([trade(quantity="0.00200")])
    assert (result.duplicates, result.conflicts) == (1, ())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "ETH/USDT"),
        ("side", "sell"),
        ("quantity", "0.003"),
        ("price", "60001"),
        ("fee", "0.5"),
        ("fee_asset", "BTC"),
        ("executed_at", T0 + timedelta(seconds=1)),
    ],
)
async def test_same_id_with_different_content_is_a_conflict_and_never_overwrites(
    pool, field, value
):
    repo = TradeRepository(pool)
    original = trade()
    await repo.save_trades([original])

    changed = trade(**{field: value})
    result = await repo.save_trades([changed])

    assert (result.inserted, result.duplicates) == (0, 0)
    [conflict] = result.conflicts
    assert conflict.existing == original
    assert conflict.incoming == changed
    assert conflict.differing_fields == (field,)
    assert await repo.get(Exchange.BINANCE, "T-1") == original


async def test_two_versions_of_a_trade_in_one_batch_is_a_conflict(pool):
    repo = TradeRepository(pool)
    first, second = trade(), trade(quantity="0.003")
    result = await repo.save_trades([first, second])
    assert (result.inserted, result.duplicates) == (1, 0)
    [conflict] = result.conflicts
    assert (conflict.existing, conflict.incoming) == (first, second)
    assert await repo.get(Exchange.BINANCE, "T-1") == first


async def test_a_conflict_is_logged(pool, caplog):
    repo = TradeRepository(pool)
    await repo.save_trades([trade()])
    await repo.save_trades([trade(quantity="0.003")])
    assert "trade conflict on binance/T-1" in caplog.text
    assert "quantity" in caplog.text


async def test_saving_nothing_is_fine(pool):
    result = await TradeRepository(pool).save_trades([])
    assert (result.inserted, result.duplicates, result.conflicts) == (0, 0, ())


async def test_a_missing_trade_is_none(pool):
    assert await TradeRepository(pool).get(Exchange.BINANCE, "nope") is None


async def test_list_is_ordered_by_time_then_id(pool):
    repo = TradeRepository(pool)
    await repo.save_trades(
        [
            trade(trade_id="B", executed_at=T0 + timedelta(seconds=5)),
            trade(trade_id="C", executed_at=T0),
            trade(trade_id="A", executed_at=T0),
        ]
    )
    assert ids(await repo.list_trades()) == ["A", "C", "B"]


async def test_list_can_be_filtered(pool):
    repo = TradeRepository(pool)
    await repo.save_trades(
        [
            trade(trade_id="T-1"),
            trade(trade_id="T-2", symbol="ETH/USDT"),
            trade(trade_id="T-3", exchange="kraken"),
        ]
    )
    assert ids(await repo.list_trades(exchange=Exchange.KRAKEN)) == ["T-3"]
    assert ids(await repo.list_trades(symbol="ETH/USDT")) == ["T-2"]
    assert ids(await repo.list_trades(exchange=Exchange.BINANCE, symbol="BTC/USDT")) == ["T-1"]
    assert await repo.list_trades(symbol="XRP/USDT") == []


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("quantity", Decimal("0")),
        ("price", Decimal("-1")),
        ("fee", Decimal("-1")),
        ("side", "hold"),
        ("trade_id", ""),
    ],
)
async def test_database_itself_refuses_nonsense(pool, column, value):
    values = {
        "exchange": "binance",
        "trade_id": "X",
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": Decimal("1"),
        "price": Decimal("1"),
        "fee": Decimal("0"),
    }
    values[column] = value
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            "INSERT INTO trades (exchange, trade_id, symbol, side, quantity, price, fee, "
            "executed_at) VALUES ($1, $2, $3, $4, $5, $6, $7, now())",
            *values.values(),
        )