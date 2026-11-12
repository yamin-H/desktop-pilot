import json
from datetime import UTC, datetime, timedelta

import pytest

from deskpilot.agent.data import StaticData
from deskpilot.agent.tools import ToolContext, build_default_registry
from deskpilot.models import PriceTick, Trade

NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)
DAY = datetime(2026, 11, 10, tzinfo=UTC)


def _at(hour: int, minute: int) -> datetime:
    return DAY.replace(hour=hour, minute=minute)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def paper_trades() -> list[Trade]:
    """The five trades from scripts/seed_trades.py."""
    return [
        Trade(
            exchange="binance",
            trade_id="PAPER-0001",
            symbol="BTC/USDT",
            side="buy",
            quantity="0.50",
            price="60000",
            fee="0.0005",
            fee_asset="BTC",
            executed_at=_at(10, 0),
        ),
        Trade(
            exchange="binance",
            trade_id="PAPER-0002",
            symbol="BTC/USDT",
            side="buy",
            quantity="0.25",
            price="61000",
            fee="15.25",
            fee_asset="USDT",
            executed_at=_at(11, 30),
        ),
        Trade(
            exchange="binance",
            trade_id="PAPER-0003",
            symbol="BTC/USDT",
            side="sell",
            quantity="0.40",
            price="62500",
            fee="25.00",
            fee_asset="USDT",
            executed_at=_at(14, 15),
        ),
        Trade(
            exchange="kraken",
            trade_id="PAPER-0004",
            symbol="ETH/USDT",
            side="buy",
            quantity="5",
            price="3000",
            fee="15.00",
            fee_asset="USDT",
            executed_at=_at(10, 20),
        ),
        Trade(
            exchange="kraken",
            trade_id="PAPER-0005",
            symbol="ETH/USDT",
            side="sell",
            quantity="2",
            price="3100",
            fee="6.20",
            fee_asset="USDT",
            executed_at=_at(16, 45),
        ),
    ]


@pytest.fixture
def paper_prices(now) -> list[PriceTick]:
    """Fresh recorded prices (one minute old)."""
    seen = now - timedelta(minutes=1)
    return [
        PriceTick(exchange="binance", symbol="BTC/USDT", price="63000", exchange_time=seen),
        PriceTick(exchange="binance", symbol="ETH/USDT", price="3050", exchange_time=seen),
    ]


@pytest.fixture
def agent_context(paper_trades, paper_prices, now, tmp_path) -> ToolContext:
    return ToolContext(
        data=StaticData(paper_trades, paper_prices),
        statements_dir=tmp_path / "statements",
        clock=lambda: now,
    )


@pytest.fixture
def run_tool(agent_context, now, tmp_path):
    """Run a tool by name. Pass `data` to use different data instead of the paper trades."""
    registry = build_default_registry()

    async def run(name, arguments=None, *, data=None):
        raw = json.dumps(arguments) if isinstance(arguments, dict) else arguments
        context = (
            agent_context
            if data is None
            else ToolContext(data=data, statements_dir=tmp_path / "statements", clock=lambda: now)
        )
        result = await registry.call(name, raw, context)
        json.dumps(result)  # every result must be plain JSON, or the model could not receive it
        return result

    return run
