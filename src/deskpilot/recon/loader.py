import csv
import io
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from deskpilot.models import Exchange, Trade

REQUIRED_COLUMNS = ("trade_id", "symbol", "side", "quantity", "price", "fee", "executed_at")


class StatementError(ValueError):
    """The statement cannot be read completely. `problems` lists every bad spot."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _explain(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
    return str(error)


def _parse_row(row: dict, exchange: Exchange) -> Trade:
    if None in row:  # the csv module files surplus values under the key None
        raise ValueError("too many columns in this row")
    values = {name: (value or "").strip() for name, value in row.items()}
    return Trade(
        exchange=exchange,
        trade_id=values["trade_id"],
        symbol=values["symbol"].upper(),
        side=values["side"].lower(),
        quantity=values["quantity"],
        price=values["price"],
        fee=values["fee"] or "0",  # a blank fee means no fee
        fee_asset=values.get("fee_asset") or None,
        executed_at=datetime.fromisoformat(values["executed_at"]),  # needs a timezone
    )


def parse_statement(text: str, exchange: Exchange) -> list[Trade]:
    """Read a statement in our CSV format. Refuses the whole file if any row is bad."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise StatementError(["the file is empty (there is no header row)"])
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]

    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise StatementError(
            [
                f"missing column(s): {', '.join(missing)} "
                f"(found: {', '.join(reader.fieldnames) or 'none'})"
            ]
        )

    trades: list[Trade] = []
    problems: list[str] = []
    for row in reader:
        line = reader.line_num
        try:
            trades.append(_parse_row(row, exchange))
        except ValueError as error:  # pydantic's ValidationError is a ValueError too
            problems.append(f"line {line}: {_explain(error)}")
    if problems:
        raise StatementError(problems)
    return trades


def read_statement(path: str | Path, exchange: Exchange) -> list[Trade]:
    # utf-8-sig quietly removes the invisible marker Excel puts at the start of CSV files
    return parse_statement(Path(path).read_text(encoding="utf-8-sig"), exchange)
