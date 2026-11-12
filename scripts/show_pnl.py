"""Show positions and profit and loss from the stored trades.

Usage:   uv run python scripts/show_pnl.py [SYMBOL=PRICE ...]
Example: uv run python scripts/show_pnl.py BTC/USDT=63000 ETH/USDT=3050

Prices you give are used as they are. For any symbol without one, the latest
recorded Binance price is used, if there is one.
"""

import asyncio
import sys
from decimal import Decimal

from deskpilot.analytics import (
    LedgerError,
    calculate_positions,
    totals_by_quote,
    value_positions,
)
from deskpilot.config import get_settings
from deskpilot.models import Exchange
from deskpilot.storage import PriceRepository, TradeRepository, create_pool

HEADER = (
    f"{'exchange':<9}{'symbol':<10}{'held':>13}{'avg cost':>14}"
    f"{'price':>14}{'realized':>13}{'unrealized':>13}"
)


def money(value: Decimal | None, places: int = 2) -> str:
    return "n/a" if value is None else f"{value:,.{places}f}"


def parse_prices(args: list[str]) -> dict[str, str]:
    prices = {}
    for arg in args:
        symbol, separator, price = arg.partition("=")
        if not separator or not price:
            raise SystemExit(f"expected SYMBOL=PRICE (like BTC/USDT=63000), got {arg!r}")
        prices[symbol.upper()] = price
    return prices


async def main(args: list[str]) -> int:
    given = parse_prices(args)
    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as exc:
        raise SystemExit(
            f"Cannot reach the database ({exc}). Run: make db-up && make migrate"
        ) from None

    try:
        trades = await TradeRepository(pool).list_trades()
        if not trades:
            print("No trades stored. Run: uv run python scripts/seed_trades.py")
            return 0
        try:
            positions = calculate_positions(trades)
        except LedgerError as exc:
            print(f"Cannot calculate positions: {exc}")
            return 1

        prices = dict(given)
        sources = {symbol: "given by you" for symbol in given}
        recorded = PriceRepository(pool)
        for symbol in sorted({p.symbol for p in positions if p.quantity > 0}):
            if symbol in prices:
                continue
            tick = await recorded.latest(Exchange.BINANCE, symbol)
            if tick is None:
                sources[symbol] = "none available"
            else:
                prices[symbol] = tick.price
                sources[symbol] = f"recorded from binance at {tick.exchange_time:%Y-%m-%d %H:%M} UTC"

        values = value_positions(positions, prices)

        print(HEADER)
        for value in values:
            p = value.position
            print(
                f"{p.exchange.value:<9}{p.symbol:<10}{money(p.quantity, 8):>13}"
                f"{money(p.average_cost):>14}{money(value.mark_price):>14}"
                f"{money(p.realized_pnl):>13}{money(value.unrealized_pnl):>13}"
            )

        print()
        for symbol in sorted({v.position.symbol for v in values if v.position.quantity > 0}):
            print(f"price for {symbol}: {sources[symbol]}")

        print()
        for totals in totals_by_quote(values):
            if totals.unrealized_pnl is None:
                unrealized = f"n/a (no price for {', '.join(totals.missing_marks)})"
            else:
                unrealized = money(totals.unrealized_pnl)
            print(
                f"{totals.quote}: realized {money(totals.realized_pnl)}   "
                f"unrealized {unrealized}   total {money(totals.total_pnl)}"
            )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))