from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from deskpilot.models.common import Exchange, Symbol, UtcDatetime
from deskpilot.models.money import PositiveMoney


class PriceTick(BaseModel):
    """One price update from one exchange, in the common format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange: Exchange
    symbol: Symbol
    price: PositiveMoney
    exchange_time: UtcDatetime  # when the exchange says it happened
    received_time: UtcDatetime = Field(default_factory=lambda: datetime.now(UTC))
