import re
from pathlib import Path
from typing import Any

from pydantic import Field

from deskpilot.agent.tools.common import ExchangeName, amount, iso, parse_time
from deskpilot.agent.tools.registry import Tool, ToolArgs, ToolContext, ToolError
from deskpilot.models import Exchange
from deskpilot.recon import Break, ReconInputError, StatementError, read_statement, reconcile

MAX_BREAKS = 50

# Plain file names only: no folders, no "..", must end in .csv
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.csv")


class ReconArgs(ToolArgs):
    exchange: ExchangeName = Field(description="The exchange the statement is from.")
    statement_file: str = Field(
        description="File name of the statement CSV, like binance_2026-11-10.csv. "
        "Only files in the statements folder can be used."
    )
    start: str = Field(
        description="Start of the period (included). ISO 8601 date or time, UTC if no timezone."
    )
    end: str = Field(
        description="End of the period (excluded). ISO 8601 date or time, UTC if no timezone. "
        "For one whole day, use the next day's date."
    )


def _statement_path(directory: Path, name: str) -> Path:
    available = sorted(p.name for p in directory.glob("*.csv")) if directory.is_dir() else []
    listing = ", ".join(available) or "none"
    if not _FILE_NAME.fullmatch(name):
        raise ToolError(
            f"{name!r} is not a valid statement file name. Available statements: {listing}"
        )
    path = directory / name
    # Also refuse anything that resolves outside the folder (for example a symlink).
    if not path.is_file() or path.resolve().parent != directory.resolve():
        raise ToolError(
            f"there is no statement file named {name!r}. Available statements: {listing}"
        )
    return path


def _break_row(item: Break) -> dict[str, Any]:
    return {
        "kind": item.kind.value,
        "trade_id": item.trade_id,
        "time": iso(item.executed_at),
        "detail": item.detail,
        "ledger_value": item.ledger_value,
        "statement_value": item.statement_value,
        "difference": amount(item.difference),
    }


async def run_reconciliation(context: ToolContext, args: ReconArgs) -> dict[str, Any]:
    exchange = Exchange(args.exchange)
    start = parse_time(args.start, "start")
    end = parse_time(args.end, "end")
    if start >= end:
        raise ToolError("start must be before end")

    path = _statement_path(context.statements_dir, args.statement_file)
    try:
        statement = read_statement(path, exchange)
    except StatementError as error:
        raise ToolError("the statement cannot be read: " + "; ".join(error.problems[:10])) from None
    except UnicodeDecodeError:
        raise ToolError("the statement is not a readable text file") from None

    ledger = await context.data.trades(exchange=exchange)
    try:
        report = reconcile(ledger, statement, exchange=exchange, start=start, end=end)
    except ReconInputError as error:
        raise ToolError(f"cannot reconcile: {error}") from None

    return {
        "exchange": exchange.value,
        "period": {"start": iso(start), "end": iso(end)},
        "is_clean": report.is_clean,
        "statement_trades": report.statement_trades,
        "ledger_trades": report.ledger_trades,
        "matched": report.matched,
        "matched_without_differences": report.matched_clean,
        "ledger_trades_outside_period_not_checked": report.ignored_outside_period,
        "break_count": len(report.breaks),
        "breaks_by_kind": {kind.value: number for kind, number in report.counts().items()},
        "breaks_shown": min(len(report.breaks), MAX_BREAKS),
        "truncated": len(report.breaks) > MAX_BREAKS,
        "breaks": [_break_row(item) for item in report.breaks[:MAX_BREAKS]],
        "note": "difference = statement minus ledger (for time_drift, in seconds). This tool "
        "only reports; it never changes any record.",
    }


RECON_TOOLS = [
    Tool(
        "run_reconciliation",
        "Compare our recorded trades with an exchange statement file for a time period and "
        "list every mismatch (missing trades, different quantity, price, fee or time). "
        "Read-only: it reports and never fixes.",
        ReconArgs,
        run_reconciliation,
    ),
]