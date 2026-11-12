from collections.abc import Iterable
from datetime import datetime

from deskpilot.models import Exchange, Trade
from deskpilot.recon.report import ReconReport
from deskpilot.recon.rules import (
    Break,
    BreakKind,
    Tolerances,
    compare_trades,
    duplicate_in_statement,
    missing_in_ledger,
    missing_in_statement,
)

_KIND_ORDER = {kind: position for position, kind in enumerate(BreakKind)}


class ReconInputError(ValueError):
    """The inputs themselves are wrong (for example a statement from another exchange)."""


def reconcile(
    ledger: Iterable[Trade],
    statement: Iterable[Trade],
    *,
    exchange: Exchange,
    start: datetime,
    end: datetime,
    tolerances: Tolerances | None = None,
) -> ReconReport:
    """Compare our ledger with one exchange's statement for the period [start, end).

    Trades are paired by trade ID. Our trades on other exchanges are ignored. Our trades
    outside the period that the statement does not list are not blamed (they are counted).
    A trade the statement lists must be in our ledger, whatever its time.
    """
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("start and end must include a timezone")
    if start >= end:
        raise ValueError("start must be before end")

    ledger_by_id: dict[str, Trade] = {}
    for trade in ledger:
        if trade.exchange is not exchange:
            continue
        if trade.trade_id in ledger_by_id:
            raise ReconInputError(
                f"the ledger lists {exchange.value}/{trade.trade_id} more than once"
            )
        ledger_by_id[trade.trade_id] = trade

    breaks: list[Break] = []
    statement_by_id: dict[str, Trade] = {}
    for trade in statement:
        if trade.exchange is not exchange:
            raise ReconInputError(
                f"statement trade {trade.exchange.value}/{trade.trade_id} does not belong "
                f"in a {exchange.value} statement"
            )
        first = statement_by_id.get(trade.trade_id)
        if first is None:
            statement_by_id[trade.trade_id] = trade
        else:
            breaks.append(duplicate_in_statement(first, trade))

    matched = 0
    matched_clean = 0
    for trade_id, theirs in statement_by_id.items():
        ours = ledger_by_id.get(trade_id)
        if ours is None:
            breaks.append(missing_in_ledger(theirs))
            continue
        matched += 1
        differences = compare_trades(ours, theirs, tolerances)
        if not differences:
            matched_clean += 1
        breaks.extend(differences)

    ignored = 0
    for trade_id, ours in ledger_by_id.items():
        if trade_id in statement_by_id:
            continue
        if start <= ours.executed_at < end:
            breaks.append(missing_in_statement(ours))
        else:
            ignored += 1

    breaks.sort(key=lambda item: (item.executed_at, item.trade_id, _KIND_ORDER[item.kind]))
    return ReconReport(
        exchange=exchange,
        start=start,
        end=end,
        statement_trades=len(statement_by_id),
        ledger_trades=len(ledger_by_id),
        matched=matched,
        matched_clean=matched_clean,
        ignored_outside_period=ignored,
        breaks=tuple(breaks),
    )
