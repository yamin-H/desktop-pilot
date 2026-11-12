from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from deskpilot.models import Exchange
from deskpilot.recon.rules import Break, BreakKind


@dataclass(frozen=True)
class ReconReport:
    """The result of comparing one exchange's statement with our ledger."""

    exchange: Exchange
    start: datetime
    end: datetime
    statement_trades: int  # distinct trades on the statement
    ledger_trades: int  # our trades on this exchange (any time)
    matched: int  # trade IDs found on both sides
    matched_clean: int  # matched, and every field agrees
    ignored_outside_period: int  # our trades outside the period the statement does not list
    breaks: tuple[Break, ...]

    @property
    def is_clean(self) -> bool:
        return not self.breaks

    def counts(self) -> dict[BreakKind, int]:
        """How many breaks of each kind (only kinds that occurred, in a fixed order)."""
        found = Counter(item.kind for item in self.breaks)
        return {kind: found[kind] for kind in BreakKind if found[kind]}


def format_report(report: ReconReport) -> str:
    """The report as plain text."""
    start = report.start.astimezone(UTC)
    end = report.end.astimezone(UTC)
    lines = [
        f"Reconciliation: {report.exchange.value}, "
        f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC",
        f"  statement trades: {report.statement_trades}   ledger trades: {report.ledger_trades}"
        f"   matched: {report.matched} ({report.matched_clean} clean)",
    ]
    if report.ignored_outside_period:
        lines.append(
            f"  {report.ignored_outside_period} ledger trade(s) fall outside the period "
            "and were not checked"
        )

    if report.is_clean:
        lines.append("RESULT: clean, no breaks")
        return "\n".join(lines)

    total = len(report.breaks)
    lines.append(f"RESULT: {total} break{'' if total == 1 else 's'}")
    for kind, number in report.counts().items():
        lines.append(f"  {kind.value:<24}{number:>3}")
    lines.append("")
    lines.append("BREAKS")
    for item in report.breaks:
        when = item.executed_at.astimezone(UTC)
        lines.append(f"  {item.trade_id}  {when:%Y-%m-%d %H:%M:%S}  {item.kind.value}")
        lines.append(f"      {item.detail}")
    return "\n".join(lines)