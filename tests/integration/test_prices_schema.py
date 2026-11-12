import asyncpg
import pytest


async def test_all_migrations_are_applied(pool):
    rows = await pool.fetch("SELECT name FROM schema_migrations ORDER BY name")
    assert [row["name"] for row in rows] == [
        "001_extensions.sql",
        "002_prices.sql",
        "003_trades.sql",
        "004_documents.sql",
    ]


async def test_prices_is_a_timescale_hypertable(pool):
    name = await pool.fetchval(
        "SELECT hypertable_name FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'prices'"
    )
    assert name == "prices"


@pytest.mark.parametrize("bad_price", [0, -1])
async def test_database_itself_rejects_non_positive_prices(pool, bad_price):
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(
            "INSERT INTO prices VALUES ('binance', 'BTC/USDT', $1, now(), now())", bad_price
        )
