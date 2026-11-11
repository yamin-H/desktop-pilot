from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from deskpilot.models.money import Money, NonNegativeMoney, PositiveMoney


class AnyBox(BaseModel):
    amount: Money


class PositiveBox(BaseModel):
    amount: PositiveMoney


class NonNegativeBox(BaseModel):
    amount: NonNegativeMoney


def test_accepts_string_without_losing_digits():
    assert AnyBox(amount="60000.12345678").amount == Decimal("60000.12345678")


def test_accepts_int_and_decimal():
    assert AnyBox(amount=5).amount == Decimal("5")
    assert AnyBox(amount=Decimal("1.5")).amount == Decimal("1.5")


def test_rejects_float():
    with pytest.raises(ValidationError):
        AnyBox(amount=0.1)


def test_rejects_bool():
    with pytest.raises(ValidationError):
        AnyBox(amount=True)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "abc", "", None])
def test_rejects_non_numbers(bad):
    with pytest.raises(ValidationError):
        AnyBox(amount=bad)


def test_arithmetic_is_exact():
    total = AnyBox(amount="0.1").amount + AnyBox(amount="0.2").amount
    assert total == Decimal("0.3")


def test_negative_is_allowed_for_plain_money():
    assert AnyBox(amount="-25.5").amount == Decimal("-25.5")


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_positive_rejects_zero_and_negative(bad):
    with pytest.raises(ValidationError):
        PositiveBox(amount=bad)


def test_non_negative_allows_zero_but_not_negative():
    assert NonNegativeBox(amount="0").amount == Decimal("0")
    with pytest.raises(ValidationError):
        NonNegativeBox(amount="-0.01")
