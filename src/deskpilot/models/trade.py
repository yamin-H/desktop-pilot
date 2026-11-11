from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from deskpilot.models.common import Exchange, Side, Symbol, UtcDatetime
from deskpilot.models.money import NonNegativeMoney, PositiveMoney


class Trade(BaseModel):
    """One executed trade (a fill), in the common format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange: Exchange
    trade_id: str = Field(min_length=1)  # the exchange's own ID for this trade
    symbol: Symbol
    side: Side
    quantity: PositiveMoney
    price: PositiveMoney
    fee: NonNegativeMoney = Decimal("0")
    fee_asset: str | None = None  # which coin the fee was paid in
    executed_at: UtcDatetime

    @property
    def notional(self) -> Decimal:
        """Total value of the trade: quantity x price."""
        return self.quantity * self.price

    @property
    def dedupe_key(self) -> tuple[str, str]:
        """Two trades with the same key are the same trade seen twice."""
        return (self.exchange.value, self.trade_id)
