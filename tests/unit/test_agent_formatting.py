from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from deskpilot.agent.tools.common import amount, iso, money, parse_symbol, parse_time
from deskpilot.agent.tools.registry import ToolError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("817.4282855", "817.43"),
        ("0.005", "0.01"),
        ("-0.005", "-0.01"),
        ("-0.004", "0.00"),  # never "-0.00"
        ("1234567.891", "1234567.89"),
        ("3003", "3003.00"),
        ("0", "0.00"),
    ],
)
def test_money_is_rounded_to_cents_as_plain_text(value, expected):
    assert money(Decimal(value)) == expected


def test_unknown_money_stays_unknown():
    assert money(None) is None
    assert amount(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.3495", "0.3495"),
        ("5.000", "5"),
        ("100", "100"),
        ("1E+2", "100"),
        ("0.00", "0"),
        ("0.00000001", "0.00000001"),
        ("-0.002", "-0.002"),
    ],
)
def test_amounts_keep_every_digit_without_trailing_zeros(value, expected):
    assert amount(Decimal(value)) == expected


def test_times_are_written_in_utc_with_a_z():
    assert iso(datetime(2026, 11, 10, 14, 15, tzinfo=UTC)) == "2026-11-10T14:15:00Z"
    local = datetime(2026, 11, 10, 20, 15, tzinfo=timezone(timedelta(hours=6)))
    assert iso(local) == "2026-11-10T14:15:00Z"


def test_symbols_are_cleaned_up():
    assert parse_symbol(" btc/usdt ") == "BTC/USDT"
    assert parse_symbol(None) is None


@pytest.mark.parametrize("bad", ["BTCUSDT", "BTC-USDT", "", "BTC/"])
def test_bad_symbols_are_refused(bad):
    with pytest.raises(ToolError, match="BTC/USDT"):
        parse_symbol(bad)


def test_times_are_read_as_utc():
    assert parse_time("2026-11-10", "start") == datetime(2026, 11, 10, tzinfo=UTC)
    assert parse_time("2026-11-10T14:30:00", "start") == datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
    assert parse_time("2026-11-10T14:30:00Z", "start") == datetime(2026, 11, 10, 14, 30, tzinfo=UTC)
    assert parse_time("2026-11-10T20:30:00+06:00", "start") == datetime(
        2026, 11, 10, 14, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("bad", ["yesterday", "", "10/11/2026", "2026-13-40"])
def test_bad_times_are_refused_with_a_helpful_message(bad):
    with pytest.raises(ToolError, match="ISO 8601"):
        parse_time(bad, "start")