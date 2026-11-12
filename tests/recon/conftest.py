from datetime import UTC, datetime

import pytest

from deskpilot.models import Trade

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def make_trade():
    def make(**overrides) -> Trade:
        data = {
            "exchange": "binance",
            "trade_id": "T-1",
            "symbol": "BTC/USDT",
            "side": "buy",
            "quantity": "2",
            "price": "60000",
            "fee": "0.002",
            "fee_asset": "BTC",
            "executed_at": T0,
        }
        data.update(overrides)
        return Trade(**data)

    return make
