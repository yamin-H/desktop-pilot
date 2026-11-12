from datetime import UTC, datetime, timedelta
from decimal import Decimal

from deskpilot.agent.data import StaticData
from deskpilot.models import Exchange, PriceTick, Trade

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def trade(trade_id, *, minutes=0, exchange="binance", symbol="BTC/USDT"):
    return Trade(
        exchange=exchange,
        trade_id=trade_id,
        symbol=symbol,
        side="buy",
        quantity="1",
        price="100",
        executed_at=T0 + timedelta(minutes=minutes),
    )


def tick(price, *, minutes=0, exchange="binance", symbol="BTC/USDT"):
    return PriceTick(
        exchange=exchange,
        symbol=symbol,
        price=price,
        exchange_time=T0 + timedelta(minutes=minutes),
    )


async def test_trades_come_back_oldest_first():
    data = StaticData([trade("B", minutes=5), trade("A", minutes=1), trade("C", minutes=1)])
    assert [t.trade_id for t in await data.trades()] == ["A", "C", "B"]


async def test_trades_can_be_filtered():
    data = StaticData(
        [
            trade("A"),
            trade("B", exchange="kraken"),
            trade("C", symbol="ETH/USDT"),
        ]
    )
    assert [t.trade_id for t in await data.trades(exchange=Exchange.KRAKEN)] == ["B"]
    assert [t.trade_id for t in await data.trades(symbol="ETH/USDT")] == ["C"]
    assert await data.trades(symbol="XRP/USDT") == []


async def test_the_latest_price_is_the_newest_by_exchange_time():
    data = StaticData(prices=[tick("101", minutes=5), tick("100", minutes=1)])
    found = await data.latest_price(Exchange.BINANCE, "BTC/USDT")
    assert found.price == Decimal("101")


async def test_a_missing_price_is_none():
    data = StaticData(prices=[tick("100")])
    assert await data.latest_price(Exchange.KRAKEN, "BTC/USDT") is None
    assert await data.latest_price(Exchange.BINANCE, "ETH/USDT") is None