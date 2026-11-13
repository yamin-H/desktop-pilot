from collections.abc import Mapping
from typing import Any

from deskpilot.models import PriceTick


def encode_tick(tick: PriceTick) -> dict[str, str]:
    """A tick as the plain text fields of a stream entry. Prices keep every digit."""
    return {
        "exchange": tick.exchange.value,
        "symbol": tick.symbol,
        "price": format(tick.price, "f"),
        "exchange_time": tick.exchange_time.isoformat(),
        "received_time": tick.received_time.isoformat(),
    }


def decode_tick(fields: Mapping[str, Any] | None) -> PriceTick:
    """The reverse. Raises ValueError for anything that is not exactly one valid tick."""
    if not fields:
        raise ValueError("the entry has no fields")
    return PriceTick(**dict(fields))  # a validation error is a ValueError
