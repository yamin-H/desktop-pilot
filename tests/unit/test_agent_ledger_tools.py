from datetime import timedelta

import pytest

from deskpilot.agent.data import StaticData
from deskpilot.agent.tools import build_default_registry
from deskpilot.models import Exchange, PriceTick, Trade


def test_every_tool_and_argument_is_described_for_the_model():
    for schema in build_default_registry().schemas():
        function = schema["function"]
        assert function["description"]
        for name, prop in function["parameters"]["properties"].items():
            assert prop.get("description"), f"{function['name']}.{name} has no description"


def test_exchange_choices_match_the_exchange_enum():
    schemas = {s["function"]["name"]: s["function"] for s in build_default_registry().schemas()}
    for name in ("get_positions", "get_pnl", "get_realized_pnl", "run_reconciliation"):
        choices = schemas[name]["parameters"]["properties"]["exchange"]["enum"]
        assert set(choices) == {exchange.value for exchange in Exchange}


async def test_positions_are_the_hand_calculated_ones(run_tool):
    result = await run_tool("get_positions")
    assert result["count"] == 2
    btc, eth = result["positions"]
    assert btc == {
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "quote_currency": "USDT",
        "quantity": "0.3495",
        "average_cost": "60393.93",
        "cost_basis": "21107.68",
        "realized_pnl": "817.43",
    }
    assert eth == {
        "exchange": "kraken",
        "symbol": "ETH/USDT",
        "quote_currency": "USDT",
        "quantity": "3",
        "average_cost": "3003.00",
        "cost_basis": "9009.00",
        "realized_pnl": "187.80",
    }


async def test_positions_can_be_filtered(run_tool):
    result = await run_tool("get_positions", {"exchange": "kraken"})
    assert [p["symbol"] for p in result["positions"]] == ["ETH/USDT"]
    result = await run_tool("get_positions", {"symbol": "btc/usdt"})  # case does not matter
    assert [p["exchange"] for p in result["positions"]] == ["binance"]


async def test_a_bad_symbol_is_an_error_the_model_can_read(run_tool):
    result = await run_tool("get_positions", {"symbol": "BTCUSDT"})
    assert "BTC/USDT" in result["error"]


async def test_no_trades_means_no_positions(run_tool):
    result = await run_tool("get_positions", data=StaticData())
    assert (result["count"], result["positions"]) == (0, [])


async def test_pnl_is_the_hand_calculated_one(run_tool):
    result = await run_tool("get_pnl")
    btc, eth = result["positions"]

    assert (btc["price"], btc["market_value"]) == ("63000", "22018.50")
    assert (btc["unrealized_pnl"], btc["total_pnl"]) == ("910.82", "1728.25")
    assert (eth["price"], eth["market_value"]) == ("3050", "9150.00")
    assert (eth["unrealized_pnl"], eth["total_pnl"]) == ("141.00", "328.80")

    assert result["totals"] == [
        {
            "quote_currency": "USDT",
            "realized_pnl": "1005.23",
            "unrealized_pnl": "1051.82",
            "total_pnl": "2057.05",
            "missing_prices": [],
        }
    ]


async def test_pnl_says_when_the_price_was_recorded_and_that_it_is_fresh(run_tool):
    btc = (await run_tool("get_pnl"))["positions"][0]
    assert btc["price_time"] == "2026-11-12T10:14:00Z"
    assert btc["price_is_stale"] is False


async def test_an_old_price_is_flagged_as_stale(run_tool, paper_trades, now):
    old = PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price="63000",
        exchange_time=now - timedelta(hours=1),
    )
    btc = (await run_tool("get_pnl", data=StaticData(paper_trades, [old])))["positions"][0]
    assert btc["price_is_stale"] is True


async def test_a_missing_price_makes_unrealized_profit_unknown_not_zero(
    run_tool, paper_trades, now
):
    only_btc = PriceTick(
        exchange="binance",
        symbol="BTC/USDT",
        price="63000",
        exchange_time=now - timedelta(minutes=1),
    )
    result = await run_tool("get_pnl", data=StaticData(paper_trades, [only_btc]))
    eth = result["positions"][1]
    assert eth["price"] is None
    assert eth["unrealized_pnl"] is None
    assert eth["total_pnl"] is None
    assert eth["realized_pnl"] == "187.80"  # still known
    [totals] = result["totals"]
    assert totals["realized_pnl"] == "1005.23"
    assert totals["unrealized_pnl"] is None
    assert totals["total_pnl"] is None
    assert totals["missing_prices"] == ["ETH/USDT"]


async def test_a_closed_position_needs_no_price(run_tool):
    trades = [
        Trade(
            exchange="binance", trade_id="A", symbol="BTC/USDT", side="buy",
            quantity="1", price="100", executed_at="2026-11-10T10:00:00Z",
        ),
        Trade(
            exchange="binance", trade_id="B", symbol="BTC/USDT", side="sell",
            quantity="1", price="110", executed_at="2026-11-10T11:00:00Z",
        ),
    ]
    result = await run_tool("get_pnl", data=StaticData(trades))
    [row] = result["positions"]
    assert (row["quantity"], row["price"], row["unrealized_pnl"]) == ("0", None, "0.00")
    assert result["totals"][0]["total_pnl"] == "10.00"


async def test_an_inconsistent_ledger_is_reported_not_guessed(run_tool):
    trades = [
        Trade(
            exchange="binance", trade_id="S", symbol="BTC/USDT", side="sell",
            quantity="1", price="100", executed_at="2026-11-10T10:00:00Z",
        )
    ]
    result = await run_tool("get_pnl", data=StaticData(trades))
    assert "ledger" in result["error"]
    assert "binance/S" in result["error"]


async def test_realized_profit_for_a_whole_day(run_tool):
    result = await run_tool("get_realized_pnl", {"start": "2026-11-10", "end": "2026-11-11"})
    assert result["sales_in_period"] == 2
    assert result["totals"] == [{"quote_currency": "USDT", "realized_pnl": "1005.23", "sales": 2}]
    assert [(s["trade_id"], s["pnl"]) for s in result["sales"]] == [
        ("PAPER-0003", "817.43"),
        ("PAPER-0005", "187.80"),
    ]
    assert result["period"] == {"start": "2026-11-10T00:00:00Z", "end": "2026-11-11T00:00:00Z"}
    assert result["truncated"] is False


async def test_a_period_counts_only_sales_inside_it_but_uses_the_full_history_for_cost(run_tool):
    result = await run_tool(
        "get_realized_pnl",
        {"start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"},
    )
    assert result["totals"] == [{"quote_currency": "USDT", "realized_pnl": "817.43", "sales": 1}]


async def test_a_period_without_sales_has_no_totals(run_tool):
    result = await run_tool("get_realized_pnl", {"start": "2026-11-12", "end": "2026-11-13"})
    assert (result["sales_in_period"], result["totals"], result["sales"]) == (0, [], [])


async def test_realized_profit_can_be_filtered(run_tool):
    result = await run_tool(
        "get_realized_pnl", {"start": "2026-11-10", "end": "2026-11-11", "exchange": "kraken"}
    )
    assert result["totals"] == [{"quote_currency": "USDT", "realized_pnl": "187.80", "sales": 1}]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "2026-11-11", "end": "2026-11-10"}, "before"),
        ({"start": "2026-11-10", "end": "2026-11-10"}, "before"),
        ({"start": "yesterday", "end": "2026-11-11"}, "ISO 8601"),
        ({"start": "2026-11-10"}, "end"),
    ],
)
async def test_bad_periods_are_errors_the_model_can_read(run_tool, arguments, message):
    assert message in (await run_tool("get_realized_pnl", arguments))["error"]


async def test_many_sales_are_cut_off_and_marked_as_cut_off(run_tool):
    trades = [
        Trade(
            exchange="binance", trade_id="BUY", symbol="BTC/USDT", side="buy",
            quantity="100", price="100", executed_at="2026-11-10T00:00:00Z",
        )
    ] + [
        Trade(
            exchange="binance", trade_id=f"S-{i:03d}", symbol="BTC/USDT", side="sell",
            quantity="1", price="101", executed_at=f"2026-11-10T01:{i // 60:02d}:{i % 60:02d}Z",
        )
        for i in range(60)
    ]
    result = await run_tool(
        "get_realized_pnl",
        {"start": "2026-11-10", "end": "2026-11-11"},
        data=StaticData(trades),
    )
    assert result["sales_in_period"] == 60
    assert result["sales_shown"] == 50
    assert len(result["sales"]) == 50
    assert result["truncated"] is True
    assert result["totals"] == [{"quote_currency": "USDT", "realized_pnl": "60.00", "sales": 60}]


async def test_latest_price(run_tool):
    result = await run_tool("get_latest_price", {"exchange": "binance", "symbol": "BTC/USDT"})
    assert result == {
        "found": True,
        "exchange": "binance",
        "symbol": "BTC/USDT",
        "price": "63000",
        "price_time": "2026-11-12T10:14:00Z",
        "age_seconds": 60,
        "is_stale": False,
    }


async def test_a_price_that_was_never_recorded_is_not_found(run_tool):
    result = await run_tool("get_latest_price", {"exchange": "kraken", "symbol": "BTC/USDT"})
    assert result["found"] is False
    assert "price" not in result


async def test_an_unknown_exchange_is_an_error(run_tool):
    result = await run_tool("get_latest_price", {"exchange": "ftx", "symbol": "BTC/USDT"})
    assert "binance" in result["error"]


async def test_trades_are_listed_newest_first(run_tool):
    result = await run_tool("list_trades")
    assert (result["total_matching"], result["shown"]) == (5, 5)
    assert [t["trade_id"] for t in result["trades"]] == [
        "PAPER-0005",
        "PAPER-0003",
        "PAPER-0002",
        "PAPER-0004",
        "PAPER-0001",
    ]
    assert result["trades"][-1] == {
        "exchange": "binance",
        "trade_id": "PAPER-0001",
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": "0.5",
        "price": "60000",
        "fee": "0.0005",
        "fee_asset": "BTC",
        "time": "2026-11-10T10:00:00Z",
    }


async def test_the_trade_list_can_be_limited_and_filtered(run_tool):
    result = await run_tool("list_trades", {"limit": 2})
    assert (result["total_matching"], result["shown"]) == (5, 2)
    assert [t["trade_id"] for t in result["trades"]] == ["PAPER-0005", "PAPER-0003"]

    result = await run_tool("list_trades", {"exchange": "kraken"})
    assert [t["trade_id"] for t in result["trades"]] == ["PAPER-0005", "PAPER-0004"]


@pytest.mark.parametrize("limit", [0, 101])
async def test_a_limit_out_of_range_is_an_error(run_tool, limit):
    assert "limit" in (await run_tool("list_trades", {"limit": limit}))["error"]