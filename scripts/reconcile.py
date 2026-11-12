"""Compare an exchange statement (CSV) with the trades stored in our ledger.

Usage:
  uv run python scripts/reconcile.py STATEMENT.csv --exchange binance \\
      --start 2026-11-10 --end 2026-11-11

Times are UTC unless you add a timezone. The period includes --start, excludes --end.
Exit code: 0 = no breaks, 1 = breaks found, 2 = the input could not be used.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from deskpilot.config import get_settings
from deskpilot.models import Exchange
from deskpilot.recon.loader import StatementError, read_statement
from deskpilot.recon.matcher import reconcile
from deskpilot.recon.report import format_report
from deskpilot.storage import TradeRepository, create_pool


def utc_time(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a valid date or time: {text!r}") from None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def main(args: argparse.Namespace) -> int:
    exchange = Exchange(args.exchange)

    try:
        statement = read_statement(args.statement, exchange)
    except StatementError as error:
        print("The statement cannot be read:")
        for problem in error.problems:
            print(f"  {problem}")
        return 2
    except OSError as error:
        print(f"Cannot open the statement: {error}")
        return 2

    try:
        pool = await create_pool(get_settings().database_url)
    except OSError as error:
        print(f"Cannot reach the database ({error}). Run: make db-up && make migrate")
        return 2
    try:
        ledger = await TradeRepository(pool).list_trades(exchange=exchange)
    finally:
        await pool.close()

    try:
        report = reconcile(ledger, statement, exchange=exchange, start=args.start, end=args.end)
    except ValueError as error:
        print(f"Cannot reconcile: {error}")
        return 2

    print(format_report(report))
    return 0 if report.is_clean else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconcile a statement against the ledger.")
    parser.add_argument("statement", help="path to the statement CSV")
    parser.add_argument("--exchange", required=True, choices=[e.value for e in Exchange])
    parser.add_argument("--start", required=True, type=utc_time)
    parser.add_argument("--end", required=True, type=utc_time)
    sys.exit(asyncio.run(main(parser.parse_args())))