from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from deskpilot.models import Exchange, Trade


class BreakKind(StrEnum):
    """The ways our ledger and an exchange statement can disagree."""

    MISSING_IN_LEDGER = "missing_in_ledger"  # the exchange lists a trade we do not have
    MISSING_IN_STATEMENT = "missing_in_statement"  # we have a trade the exchange does not list
    DUPLICATE_IN_STATEMENT = "duplicate_in_statement"  # the statement lists a trade twice
    SYMBOL_MISMATCH = "symbol_mismatch"
    SIDE_MISMATCH = "side_mismatch"
    QUANTITY_MISMATCH = "quantity_mismatch"
    PRICE_MISMATCH = "price_mismatch"
    FEE_MISMATCH = "fee_mismatch"  # a different amount, or a different currency
    TIME_DRIFT = "time_drift"  # times differ by more than the allowed drift


@dataclass(frozen=True)
class Break:
    """One disagreement between our ledger and the exchange statement."""

    kind: BreakKind
    exchange: Exchange
    trade_id: str
    executed_at: datetime  # when the trade happened (our version, if we have one)
    ledger_value: str | None  # what our ledger says (None if it has no such trade)
    statement_value: str | None  # what the statement says (None if it has no such trade)
    difference: Decimal | None  # statement minus ledger, when both are plain numbers
    detail: str  # one plain-English sentence


@dataclass(frozen=True)
class Tolerances:
    """How much disagreement is still accepted. Amounts must always match exactly."""

    max_time_drift: timedelta = timedelta(seconds=1)

    def __post_init__(self) -> None:
        if self.max_time_drift < timedelta(0):
            raise ValueError("max_time_drift cannot be negative")


def _number(value: Decimal) -> str:
    return format(value, "f")  # plain digits, never scientific notation


def _summary(trade: Trade) -> str:
    return f"{trade.side.value} {_number(trade.quantity)} {trade.symbol} @ {_number(trade.price)}"


def _fee_text(trade: Trade) -> str:
    if trade.fee == 0:
        return "0"
    return f"{_number(trade.fee)} {trade.fee_asset or 'no currency'}"


def missing_in_ledger(statement: Trade) -> Break:
    return Break(
        kind=BreakKind.MISSING_IN_LEDGER,
        exchange=statement.exchange,
        trade_id=statement.trade_id,
        executed_at=statement.executed_at,
        ledger_value=None,
        statement_value=_summary(statement),
        difference=None,
        detail=(
            f"the statement lists this trade ({_summary(statement)}) "
            "but our ledger has no record of it"
        ),
    )


def missing_in_statement(ledger: Trade) -> Break:
    return Break(
        kind=BreakKind.MISSING_IN_STATEMENT,
        exchange=ledger.exchange,
        trade_id=ledger.trade_id,
        executed_at=ledger.executed_at,
        ledger_value=_summary(ledger),
        statement_value=None,
        difference=None,
        detail=(
            f"our ledger has this trade ({_summary(ledger)}) but the statement does not list it"
        ),
    )


def duplicate_in_statement(first: Trade, extra: Trade) -> Break:
    how = "an identical copy" if first == extra else "a copy with different content"
    return Break(
        kind=BreakKind.DUPLICATE_IN_STATEMENT,
        exchange=extra.exchange,
        trade_id=extra.trade_id,
        executed_at=extra.executed_at,
        ledger_value=None,
        statement_value=_summary(extra),
        difference=None,
        detail=f"the statement lists this trade more than once ({how}); only the first was used",
    )


def compare_trades(
    ledger: Trade, statement: Trade, tolerances: Tolerances | None = None
) -> list[Break]:
    """Compare our version of one trade with the statement's. Returns every difference."""
    tolerances = tolerances or Tolerances()
    breaks: list[Break] = []

    def add(
        kind: BreakKind,
        ledger_value: str,
        statement_value: str,
        detail: str,
        difference: Decimal | None = None,
    ) -> None:
        breaks.append(
            Break(
                kind=kind,
                exchange=ledger.exchange,
                trade_id=ledger.trade_id,
                executed_at=ledger.executed_at,
                ledger_value=ledger_value,
                statement_value=statement_value,
                difference=difference,
                detail=detail,
            )
        )

    if ledger.symbol != statement.symbol:
        add(
            BreakKind.SYMBOL_MISMATCH,
            ledger.symbol,
            statement.symbol,
            f"coin pair differs: ledger {ledger.symbol}, statement {statement.symbol}",
        )

    if ledger.side is not statement.side:
        add(
            BreakKind.SIDE_MISMATCH,
            ledger.side.value,
            statement.side.value,
            f"side differs: ledger {ledger.side.value}, statement {statement.side.value}",
        )

    for kind, name, ours, theirs in (
        (BreakKind.QUANTITY_MISMATCH, "quantity", ledger.quantity, statement.quantity),
        (BreakKind.PRICE_MISMATCH, "price", ledger.price, statement.price),
    ):
        if ours != theirs:  # numbers equal in value are equal: 2.0 and 2.00 match
            difference = theirs - ours
            add(
                kind,
                _number(ours),
                _number(theirs),
                f"{name} differs: ledger {_number(ours)}, statement {_number(theirs)} "
                f"(statement - ledger = {difference:+f})",
                difference,
            )

    ledger_asset = (ledger.fee_asset or "").upper()
    statement_asset = (statement.fee_asset or "").upper()
    fee_differs = ledger.fee != statement.fee
    # The currency only matters when there is a real fee on both sides, and the amounts agree.
    asset_differs = not fee_differs and ledger.fee > 0 and ledger_asset != statement_asset
    if fee_differs or asset_differs:
        comparable = ledger_asset == statement_asset or ledger.fee == 0 or statement.fee == 0
        difference = statement.fee - ledger.fee if fee_differs and comparable else None
        detail = f"fee differs: ledger {_fee_text(ledger)}, statement {_fee_text(statement)}"
        if difference is not None:
            detail += f" (statement - ledger = {difference:+f})"
        add(BreakKind.FEE_MISMATCH, _fee_text(ledger), _fee_text(statement), detail, difference)

    drift = statement.executed_at - ledger.executed_at
    if abs(drift) > tolerances.max_time_drift:
        seconds = Decimal(drift // timedelta(microseconds=1)) / 1_000_000
        add(
            BreakKind.TIME_DRIFT,
            ledger.executed_at.isoformat(),
            statement.executed_at.isoformat(),
            f"time differs by {seconds:+f} s: ledger {ledger.executed_at.isoformat()}, "
            f"statement {statement.executed_at.isoformat()}",
            seconds,
        )

    return breaks
