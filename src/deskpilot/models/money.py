from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, Field


def to_decimal(value: Any) -> Decimal:
    """Turn a value into an exact Decimal. Floats are refused on purpose."""
    if isinstance(value, bool):
        raise ValueError("a bool is not a valid money value")
    if isinstance(value, float):
        raise ValueError("floats are not allowed for money; use a string, int or Decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"cannot read {value!r} as a decimal number") from None
    if not number.is_finite():
        raise ValueError("NaN and infinity are not allowed")
    return number


# Any exact number (can be negative, e.g. a loss)
Money = Annotated[Decimal, BeforeValidator(to_decimal)]
# Must be greater than zero (prices, quantities)
PositiveMoney = Annotated[Decimal, BeforeValidator(to_decimal), Field(gt=0)]
# Zero or more (fees)
NonNegativeMoney = Annotated[Decimal, BeforeValidator(to_decimal), Field(ge=0)]
