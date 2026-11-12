from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import Field

from deskpilot.agent.tools.common import (
    ExchangeName,
    amount,
    iso,
    money,
    parse_symbol,
    parse_time,
)
from deskpilot.agent.tools.registry import Tool, ToolArgs, ToolContext, ToolError
from deskpilot.analytics import Position, calculate_positions, totals_by_quote, value_positions
from deskpilot.models import Exchange, PriceTick, Trade

ZERO = Decimal(0)
MAX_ROWS = 50
STALE_AFTER = timedelta(minutes=10)
PRICE_SOURCE = Exchange.BINANCE  # one reference price per coin pair

_EXCHANGE_HELP = "Only this exchange. Leave out for all exchanges."
_SYMBOL_HELP = "Only this coin pair, like BTC/USDT. Leave out for all."


class PositionArgs(ToolArgs):
    exchange: ExchangeName | None = Field(None, description=_EXCHANGE_HELP)
    symbol: str | None = Field(None, description=_SYMBOL_HELP)


class RealizedArgs(ToolArgs):
    start: str = Field(
        description="Start of the period (included). ISO 8601 date or time, UTC if no timezone."
    )
    end: str = Field(
        description="End of the period (excluded). ISO 8601 date or time, UTC if no timezone. "
        "For one whole day, use the next day's date."
    )
    exchange: ExchangeName | None = Field(None, description=_EXCHANGE_HELP)
    symbol: str | None = Field(None, description=_SYMBOL_HELP)


class LatestPriceArgs(ToolArgs):
    exchange: ExchangeName = Field(description="Which exchange.")
    symbol: str = Field(description="The coin pair, like BTC/USDT.")


class ListTradesArgs(ToolArgs):
    exchange: ExchangeName | None = Field(None, description=_EXCHANGE_HELP)
    symbol: str | None = Field(None, description=_SYMBOL_HELP)
    limit: int = Field(20, ge=1, le=100, description="How many trades, newest first (1 to 100).")


async def _load_positions(
    context: ToolContext, exchange: str | None, symbol: str | None
) -> list[Position]:
    trades = await context.data.trades(
        exchange=Exchange(exchange) if exchange else None,
        symbol=parse_symbol(symbol),
    )
    return calculate_positions(trades)


def _position_row(position: Position) -> dict[str, Any]:
    return {
        "exchange": position.exchange.value,
        "symbol": position.symbol,
        "quote_currency": position.quote,
        "quantity": amount(position.quantity),
        "average_cost": money(position.average_cost),
        "cost_basis": money(position.cost),
        "realized_pnl": money(position.realized_pnl),
    }


async def get_positions(context: ToolContext, args: PositionArgs) -> dict[str, Any]:
    positions = await _load_positions(context, args.exchange, args.symbol)
    return {
        "count": len(positions),
        "positions": [_position_row(position) for position in positions],
        "note": "Average-cost method. Money is in the quote currency, rounded to cents. "
        "realized_pnl is profit already locked in by sales. A quantity of 0 means closed.",
    }


async def get_pnl(context: ToolContext, args: PositionArgs) -> dict[str, Any]:
    positions = await _load_positions(context, args.exchange, args.symbol)
    now = context.clock()

    ticks: dict[str, PriceTick] = {}
    for symbol in sorted({p.symbol for p in positions if p.quantity > 0}):
        tick = await context.data.latest_price(PRICE_SOURCE, symbol)
        if tick is not None:
            ticks[symbol] = tick

    values = value_positions(positions, {symbol: tick.price for symbol, tick in ticks.items()})

    rows = []
    for value in values:
        position = value.position
        is_open = position.quantity > 0
        tick = ticks.get(position.symbol) if is_open else None
        rows.append(
            {
                **_position_row(position),
                "price": amount(value.mark_price) if is_open else None,
                "price_time": iso(tick.exchange_time) if tick else None,
                "price_is_stale": (now - tick.exchange_time) > STALE_AFTER if tick else None,
                "market_value": money(value.market_value),
                "unrealized_pnl": money(value.unrealized_pnl),
                "total_pnl": money(value.total_pnl),
            }
        )

    totals = [
        {
            "quote_currency": item.quote,
            "realized_pnl": money(item.realized_pnl),
            "unrealized_pnl": money(item.unrealized_pnl),
            "total_pnl": money(item.total_pnl),
            "missing_prices": list(item.missing_marks),
        }
        for item in totals_by_quote(values)
    ]
    return {
        "price_source": f"latest recorded {PRICE_SOURCE.value} price for each coin pair",
        "positions": rows,
        "totals": totals,
        "note": "null means unknown, not zero. Unrealized profit is on paper: value now minus "
        "cost. total = realized + unrealized. price_is_stale is true if the price is more "
        f"than {int(STALE_AFTER.total_seconds() // 60)} minutes old.",
    }


async def get_realized_pnl(context: ToolContext, args: RealizedArgs) -> dict[str, Any]:
    start = parse_time(args.start, "start")
    end = parse_time(args.end, "end")
    if start >= end:
        raise ToolError("start must be before end")

    positions = await _load_positions(context, args.exchange, args.symbol)
    events = sorted(
        (
            event
            for position in positions
            for event in position.realized_events
            if start <= event.executed_at < end
        ),
        key=lambda event: (event.executed_at, event.trade_id),
    )

    totals: dict[str, tuple[Decimal, int]] = {}
    for event in events:
        quote = event.symbol.split("/")[1]
        pnl, sales = totals.get(quote, (ZERO, 0))
        totals[quote] = (pnl + event.pnl, sales + 1)

    return {
        "period": {"start": iso(start), "end": iso(end)},
        "sales_in_period": len(events),
        "totals": [
            {"quote_currency": quote, "realized_pnl": money(pnl), "sales": sales}
            for quote, (pnl, sales) in sorted(totals.items())
        ],
        "sales_shown": min(len(events), MAX_ROWS),
        "truncated": len(events) > MAX_ROWS,
        "sales": [
            {
                "exchange": event.exchange.value,
                "trade_id": event.trade_id,
                "symbol": event.symbol,
                "time": iso(event.executed_at),
                "proceeds": money(event.proceeds),
                "cost": money(event.cost),
                "pnl": money(event.pnl),
            }
            for event in events[:MAX_ROWS]
        ],
        "note": "Counts only sales executed inside the period; their cost comes from the full "
        "trade history (average cost). No sales means no realized profit in the period.",
    }


async def get_latest_price(context: ToolContext, args: LatestPriceArgs) -> dict[str, Any]:
    symbol = parse_symbol(args.symbol)
    tick = await context.data.latest_price(Exchange(args.exchange), symbol)
    if tick is None:
        return {
            "found": False,
            "exchange": args.exchange,
            "symbol": symbol,
            "note": "no price has been recorded for this exchange and coin pair",
        }
    age = context.clock() - tick.exchange_time
    return {
        "found": True,
        "exchange": tick.exchange.value,
        "symbol": tick.symbol,
        "price": amount(tick.price),
        "price_time": iso(tick.exchange_time),
        "age_seconds": max(0, int(age.total_seconds())),
        "is_stale": age > STALE_AFTER,
    }


def _trade_row(trade: Trade) -> dict[str, Any]:
    return {
        "exchange": trade.exchange.value,
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "side": trade.side.value,
        "quantity": amount(trade.quantity),
        "price": amount(trade.price),
        "fee": amount(trade.fee),
        "fee_asset": trade.fee_asset,
        "time": iso(trade.executed_at),
    }


async def list_trades(context: ToolContext, args: ListTradesArgs) -> dict[str, Any]:
    trades = await context.data.trades(
        exchange=Exchange(args.exchange) if args.exchange else None,
        symbol=parse_symbol(args.symbol),
    )
    shown = list(reversed(trades))[: args.limit]  # newest first
    return {
        "total_matching": len(trades),
        "shown": len(shown),
        "trades": [_trade_row(trade) for trade in shown],
    }


LEDGER_TOOLS = [
    Tool(
        "get_positions",
        "What we hold right now, per exchange and coin pair: quantity, average cost, cost "
        "basis and realized profit so far. Use for questions about holdings, balances, "
        "exposure or average buy price.",
        PositionArgs,
        get_positions,
    ),
    Tool(
        "get_pnl",
        "Overall profit and loss: realized (locked in by sales, all time) plus unrealized "
        "(on paper, valued at the latest recorded price), per position and totalled per "
        "currency. Use for 'how are we doing', total profit, unrealized profit or the "
        "market value of a position.",
        PositionArgs,
        get_pnl,
    ),
    Tool(
        "get_realized_pnl",
        "Profit locked in by sales within a time period. Use for 'profit today', 'profit on "
        "a given date', 'last week' and similar. Needs a start and an end.",
        RealizedArgs,
        get_realized_pnl,
    ),
    Tool(
        "get_latest_price",
        "The most recent recorded price for a coin pair on one exchange, and how old it is.",
        LatestPriceArgs,
        get_latest_price,
    ),
    Tool(
        "list_trades",
        "The most recent trades in our ledger (newest first), optionally for one exchange "
        "and/or coin pair."
        " Also gives the total number of matching trades, so use it for 'how many trades'.",
        ListTradesArgs,
        list_trades,
    ),
]
