import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from deskpilot.agent.tools.registry import ToolError

# Must list the same exchanges as the Exchange enum (a test checks this).
ExchangeName = Literal["binance", "kraken", "bybit"]

_CENTS = Decimal("0.01")
_SYMBOL = re.compile(r"[A-Z0-9]+/[A-Z0-9]+")


def money(value: Decimal | None) -> str | None:
    """Money rounded to cents, as plain text: '817.43'. None stays None (unknown)."""
    if value is None:
        return None
    rounded = value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return format(rounded if rounded != 0 else Decimal("0.00"), "f")  # never '-0.00'


def amount(value: Decimal | None) -> str | None:
    """An exact quantity or price as plain text without trailing zeros: '0.3495'."""
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")  # 'f' avoids scientific notation like 1E+2


def iso(value: datetime) -> str:
    """A UTC time like 2026-11-10T14:15:00Z."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_symbol(value: str | None) -> str | None:
    """Clean up a coin pair given by the model: ' btc/usdt ' becomes 'BTC/USDT'."""
    if value is None:
        return None
    symbol = value.strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ToolError(f"symbol must look like BTC/USDT, got {value!r}")
    return symbol


def parse_time(value: str, field: str) -> datetime:
    """Read an ISO 8601 date or time. Without a timezone it is taken as UTC."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(
            f"{field} must be an ISO 8601 date or time such as 2026-11-10 or "
            f"2026-11-10T14:30:00Z, got {value!r}"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)