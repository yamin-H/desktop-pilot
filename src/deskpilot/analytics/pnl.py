from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from deskpilot.analytics.positions import Position
from deskpilot.models.money import to_decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class PositionValue:
    """A position valued at a current price. None means unknown, never zero."""

    position: Position
    mark_price: Decimal | None  # the current price used (None if none was given)
    market_value: Decimal | None  # coins held x current price
    unrealized_pnl: Decimal | None  # market value minus cost: profit on paper

    @property
    def total_pnl(self) -> Decimal | None:
        """Realized + unrealized, or None if the unrealized part is unknown."""
        if self.unrealized_pnl is None:
            return None
        return self.position.realized_pnl + self.unrealized_pnl


@dataclass(frozen=True)
class Totals:
    """Profit and loss summed for one quote currency. Currencies are never mixed."""

    quote: str
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None  # None if any open position has no price
    missing_marks: tuple[str, ...]  # symbols that had no price

    @property
    def total_pnl(self) -> Decimal | None:
        if self.unrealized_pnl is None:
            return None
        return self.realized_pnl + self.unrealized_pnl


def _check_mark(symbol: str, value: object) -> Decimal:
    price = to_decimal(value)  # refuses floats, NaN and text that is not a number
    if price <= 0:
        raise ValueError(f"the price for {symbol} must be greater than 0")
    return price


def value_positions(
    positions: Iterable[Position], marks: Mapping[str, object]
) -> list[PositionValue]:
    """Value positions at current prices. `marks` maps a symbol to its price.

    Prices may be strings, ints or Decimals, never floats.
    """
    prices = {symbol: _check_mark(symbol, value) for symbol, value in marks.items()}

    result = []
    for position in positions:
        mark = prices.get(position.symbol)
        if position.quantity == 0:
            # Nothing is held, so nothing is at stake and no price is needed.
            result.append(PositionValue(position, mark, ZERO, ZERO))
        elif mark is None:
            result.append(PositionValue(position, None, None, None))
        else:
            market_value = position.quantity * mark
            result.append(PositionValue(position, mark, market_value, market_value - position.cost))
    return result


def totals_by_quote(values: Iterable[PositionValue]) -> list[Totals]:
    """Add up profit and loss per quote currency."""
    realized: dict[str, Decimal] = {}
    unrealized: dict[str, Decimal] = {}
    missing: dict[str, set[str]] = {}

    for value in values:
        quote = value.position.quote
        realized[quote] = realized.get(quote, ZERO) + value.position.realized_pnl
        if value.unrealized_pnl is None:
            missing.setdefault(quote, set()).add(value.position.symbol)
        else:
            unrealized[quote] = unrealized.get(quote, ZERO) + value.unrealized_pnl

    return [
        Totals(
            quote=quote,
            realized_pnl=realized[quote],
            # One missing price makes the whole unrealized total unknown, not "partly known".
            unrealized_pnl=None if quote in missing else unrealized.get(quote, ZERO),
            missing_marks=tuple(sorted(missing.get(quote, ()))),
        )
        for quote in sorted(realized)
    ]
