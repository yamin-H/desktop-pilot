from datetime import UTC, datetime, timedelta
from pathlib import Path

from deskpilot.agent import DatabaseData, ToolContext, build_default_registry
from deskpilot.models import Exchange, PriceTick, Trade
from deskpilot.storage import PriceRepository, TradeRepository

NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)


async def test_the_tools_give_the_same_answers_from_the_real_database(pool):
    await TradeRepository(pool).save_trades(
        [
            Trade(
                exchange="binance",
                trade_id="X-1",
                symbol="BTC/USDT",
                side="buy",
                quantity="2",
                price="100",
                executed_at="2026-11-10T10:00:00Z",
            ),
            Trade(
                exchange="binance",
                trade_id="X-2",
                symbol="BTC/USDT",
                side="sell",
                quantity="1",
                price="120",
                executed_at="2026-11-10T11:00:00Z",
            ),
        ]
    )
    tick = PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price="130",
        exchange_time=NOW - timedelta(minutes=1),
    )
    await PriceRepository(pool).save_ticks([tick])

    context = ToolContext(data=DatabaseData(pool), statements_dir=Path("."), clock=lambda: NOW)
    result = await build_default_registry().call("get_pnl", "{}", context)

    # bought 2 at 100, sold 1 at 120 (profit 20), 1 left worth 130 against cost 100 (30 on paper)
    assert result["totals"] == [
        {
            "quote_currency": "USDT",
            "realized_pnl": "20.00",
            "unrealized_pnl": "30.00",
            "total_pnl": "50.00",
            "missing_prices": [],
        }
    ]


async def test_database_data_reads_trades_and_prices(pool):
    data = DatabaseData(pool)
    assert await data.trades() == []
    assert await data.latest_price(Exchange.BINANCE, "BTC/USDT") is None
