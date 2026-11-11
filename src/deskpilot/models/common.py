from datetime import UTC
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, StringConstraints


class Exchange(StrEnum):
    BINANCE = "binance"
    KRAKEN = "kraken"
    BYBIT = "bybit"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


# One naming style for every coin pair: BASE/QUOTE, upper case. Example: BTC/USDT
Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]+/[A-Z0-9]+$")]


def _to_utc(value):
    return value.astimezone(UTC)


# A time that MUST carry a timezone, and is always stored as UTC
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
