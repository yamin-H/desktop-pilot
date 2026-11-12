from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from deskpilot.models import Exchange, Side, Trade

ZERO = Decimal(0)


class LedgerError(Exception):
    """The trades cannot be turned into positions without guessing."""


class DuplicateTradeError(LedgerError):
    """The same trade (exchange + trade ID) was given twice."""


class UnsupportedFeeError(LedgerError):
    """A fee we cannot place: an unknown currency, or one that eats all the coins bought."""


class OversoldError(LedgerError):
    """A sale of more coins than we held. Some trades or deposits must be missing."""


@dataclass(frozen=True)
class RealizedEvent:
    """Profit or loss locked in by one sale."""

    exchange: Exchange
    trade_id: str
    symbol: str
    executed_at: datetime
    quantity: Decimal  # coins that left the position (including any fee paid in coins)
    proceeds: Decimal  # money received, after fees paid in the quote currency
    cost: Decimal  # what those coins originally cost us

    @property
    def pnl(self) -> Decimal:
        return self.proceeds - self.cost


@dataclass(frozen=True)
class Position:
    """What we hold on one exchange for one coin pair, and what it cost."""

    exchange: Exchange
    symbol: str
    quantity: Decimal  # coins held now
    cost: Decimal  # total cost of the coins held now, in the quote currency
    realized_pnl: Decimal  # profit locked in by sales so far
    # Fees are ALREADY inside cost and profit. These totals are for information only.
    fees_quote: Decimal
    fees_base: Decimal
    realized_events: tuple[RealizedEvent, ...]

    @property
    def base(self) -> str:
        return self.symbol.split("/")[0]

    @property
    def quote(self) -> str:
        return self.symbol.split("/")[1]

    @property
    def average_cost(self) -> Decimal | None:
        """Cost per coin held, or None when we hold nothing."""
        return self.cost / self.quantity if self.quantity > 0 else None


@dataclass
class _Book:
    """Running totals for one (exchange, symbol) while we walk through the trades."""

    quantity: Decimal = ZERO
    cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees_quote: Decimal = ZERO
    fees_base: Decimal = ZERO
    events: list[RealizedEvent] = field(default_factory=list)


def _split_fee(trade: Trade) -> tuple[Decimal, Decimal]:
    """Where the fee was paid. Returns (fee in coins, fee in the quote currency)."""
    if trade.fee == 0:
        return ZERO, ZERO
    base, quote = trade.symbol.split("/")
    asset = (trade.fee_asset or "").upper()
    if asset == base:
        return trade.fee, ZERO
    if asset == quote:
        return ZERO, trade.fee
    raise UnsupportedFeeError(
        f"{trade.exchange.value}/{trade.trade_id}: a fee of {trade.fee} in "
        f"{trade.fee_asset!r} cannot be placed (only {base} or {quote} fees are supported)"
    )


def _apply(book: _Book, trade: Trade) -> None:
    label = f"{trade.exchange.value}/{trade.trade_id}"
    fee_coins, fee_quote = _split_fee(trade)
    gross = trade.quantity * trade.price

    if trade.side is Side.BUY:
        received = trade.quantity - fee_coins  # a fee paid in coins means fewer coins arrive
        if received <= 0:
            raise UnsupportedFeeError(f"{label}: the fee takes all the coins bought")
        book.quantity += received
        book.cost += gross + fee_quote
    else:
        leaving = trade.quantity + fee_coins  # a fee paid in coins also leaves the position
        if leaving > book.quantity:
            coin = trade.symbol.split("/")[0]
            raise OversoldError(
                f"{label}: sells {leaving} {coin} but only {book.quantity} is held "
                f"on {trade.exchange.value}"
            )
        # Selling everything removes the exact remaining cost, so no rounding crumbs are left.
        if leaving == book.quantity:
            cost_removed = book.cost
        else:
            cost_removed = book.cost * leaving / book.quantity
        proceeds = gross - fee_quote

        book.quantity -= leaving
        book.cost -= cost_removed
        book.realized_pnl += proceeds - cost_removed
        book.events.append(
            RealizedEvent(
                exchange=trade.exchange,
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                executed_at=trade.executed_at,
                quantity=leaving,
                proceeds=proceeds,
                cost=cost_removed,
            )
        )

    book.fees_quote += fee_quote
    book.fees_base += fee_coins


def calculate_positions(trades: Iterable[Trade]) -> list[Position]:
    """Turn trades into positions using average cost. Refuses to guess (see the errors)."""
    all_trades = list(trades)

    seen: set[tuple[str, str]] = set()
    for trade in all_trades:
        if trade.dedupe_key in seen:
            raise DuplicateTradeError(
                f"trade {trade.exchange.value}/{trade.trade_id} was given more than once"
            )
        seen.add(trade.dedupe_key)

    books: dict[tuple[Exchange, str], _Book] = {}
    for trade in sorted(all_trades, key=lambda t: (t.executed_at, t.trade_id)):
        _apply(books.setdefault((trade.exchange, trade.symbol), _Book()), trade)

    return [
        Position(
            exchange=exchange,
            symbol=symbol,
            quantity=book.quantity,
            cost=book.cost,
            realized_pnl=book.realized_pnl,
            fees_quote=book.fees_quote,
            fees_base=book.fees_base,
            realized_events=tuple(book.events),
        )
        for (exchange, symbol), book in sorted(
            books.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
    ]
