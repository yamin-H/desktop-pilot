import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from deskpilot.agent import ToolCallRecord
from deskpilot.evals.golden import CallSpec, GoldenQuestion
from deskpilot.evals.scoring import (
    FoundNumber,
    call_matches,
    clock_numbers,
    find_numbers,
    numbers_in_value,
    score_answer,
)

NOW = datetime(2026, 11, 12, 10, 15, tzinfo=UTC)


def record(name, args=None, result=None):
    return ToolCallRecord(name, json.dumps(args or {}), result if result is not None else {})


def make_question(**fields):
    return GoldenQuestion(**{"id": "q", "question": "What?", **fields})


def checks_of(question, answer, records=(), extra=()):
    return {c.name: c for c in score_answer(question, answer, list(records), extra_numbers=extra)}


def values(text):
    return [number.value for number in find_numbers(text)]


# --- finding numbers -------------------------------------------------------------------------


def test_numbers_are_found_with_thousands_separators():
    assert values("Total 1,005.23 USDT, price 63000, qty 0.3495") == [
        Decimal("1005.23"),
        Decimal("63000"),
        Decimal("0.3495"),
    ]


def test_dates_times_ids_files_and_list_numbers_are_not_numbers():
    text = (
        "On 2026-11-10T14:15:00Z at 14:15, PAPER-0003 made 817.43.\n"
        "See binance_2026-11-10.csv\n1. one\n2. two"
    )
    assert values(text) == [Decimal("817.43")]


def test_a_minus_sign_is_ignored():
    assert values("a loss of -6.30 USDT") == [Decimal("6.30")]


def test_a_comma_between_short_numbers_is_a_list_not_one_number():
    assert values("1, 2, 3") == [Decimal(1), Decimal(2), Decimal(3)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0.3495", True), ("63000", True), ("63,000", True), ("2026", True)]
    + [("15", False), ("7", False), ("99", False)],
)
def test_what_counts_as_a_figure(text, expected):
    assert FoundNumber(text, Decimal(text.replace(",", ""))).is_figure is expected


def test_numbers_are_collected_from_nested_tool_results():
    result = {
        "count": 2,
        "ok": True,
        "missing": None,
        "rows": [{"qty": "0.3495", "detail": "ledger 0.50, statement 0.51"}],
        "note": "no digits here",
    }
    assert numbers_in_value(result) == {
        Decimal(2),
        Decimal("0.3495"),
        Decimal("0.50"),
        Decimal("0.51"),
    }


def test_the_parts_of_the_clock_are_known():
    assert clock_numbers(NOW) == {Decimal(2026), Decimal(11), Decimal(12), Decimal(10), Decimal(15)}


# --- matching tool calls ---------------------------------------------------------------------


def test_a_call_matches_by_tool_name_or_any_of_a_list():
    assert call_matches(CallSpec(tool="get_pnl"), record("get_pnl"))
    assert call_matches(CallSpec(tool=["get_pnl", "get_positions"]), record("get_positions"))
    assert not call_matches(CallSpec(tool="get_pnl"), record("get_positions"))


def test_arguments_must_match_but_extra_ones_are_fine_and_case_is_ignored():
    spec = CallSpec(tool="get_latest_price", args={"exchange": "binance", "symbol": "BTC/USDT"})
    sent = {"exchange": "Binance", "symbol": "btc/usdt", "extra": 1}
    assert call_matches(spec, record("get_latest_price", sent))
    assert not call_matches(spec, record("get_latest_price", {"exchange": "kraken", "symbol": "BTC/USDT"}))
    assert not call_matches(spec, record("get_latest_price", {"exchange": "binance"}))


def test_unreadable_arguments_only_matter_when_arguments_are_expected():
    broken = ToolCallRecord("get_pnl", "{oops", {})
    assert call_matches(CallSpec(tool="get_pnl"), broken)
    assert not call_matches(CallSpec(tool="get_pnl", args={"exchange": "kraken"}), broken)


def test_a_failed_call_only_matches_when_an_error_is_expected():
    failed = record("run_reconciliation", result={"error": "no such file"})
    assert not call_matches(CallSpec(tool="run_reconciliation"), failed)
    assert call_matches(CallSpec(tool="run_reconciliation", error=True), failed)
    assert not call_matches(CallSpec(tool="run_reconciliation", error=True), record("run_reconciliation"))


def test_a_period_is_judged_by_the_sales_it_contains():
    result = {"sales": [{"trade_id": "A"}, {"trade_id": "B"}]}
    seen = record("get_realized_pnl", result=result)
    assert call_matches(CallSpec(tool="get_realized_pnl", sales=["B", "A"]), seen)
    assert not call_matches(CallSpec(tool="get_realized_pnl", sales=["A"]), seen)
    empty = record("get_realized_pnl", result={"sales": []})
    assert call_matches(CallSpec(tool="get_realized_pnl", sales=[]), empty)
    assert not call_matches(CallSpec(tool="get_realized_pnl", sales=[]), seen)


# --- the tools check -------------------------------------------------------------------------


def test_a_missing_tool_call_fails_the_tools_check_and_is_named():
    check = checks_of(make_question(calls=[{"tool": "get_pnl"}]), "x")["tools"]
    assert check.passed is False
    assert "get_pnl" in check.detail


def test_no_tools_fails_when_a_tool_was_called():
    question = make_question(no_tools=True)
    assert checks_of(question, "I cannot.", [record("get_pnl")])["tools"].passed is False
    assert checks_of(question, "I cannot.")["tools"].passed is True


def test_a_forbidden_tool_fails_only_when_it_succeeded():
    question = make_question(forbid_tools=["run_reconciliation"])
    worked = record("run_reconciliation", result={"is_clean": True})
    refused = record("run_reconciliation", result={"error": "invalid"})
    assert checks_of(question, "x", [worked])["tools"].passed is False
    assert checks_of(question, "x", [refused])["tools"].passed is True
    assert checks_of(question, "x")["tools"].passed is True


def test_a_question_with_no_tool_expectations_has_no_tools_check():
    assert "tools" not in checks_of(make_question(numbers=["1.5"]), "1.5")


# --- numbers, mentions, phrases --------------------------------------------------------------


def test_expected_numbers_are_found_whatever_the_formatting():
    question = make_question(numbers=["1005.23", "63000", "6.3"])
    answer = "Profit 1,005.23 USDT; price 63000.00; a loss of -6.30"
    assert checks_of(question, answer)["numbers"].passed


def test_a_missing_number_is_named():
    check = checks_of(make_question(numbers=["2138.05"]), "about 2,138")["numbers"]
    assert check.passed is False
    assert "2138.05" in check.detail


def test_mentions_ignore_case():
    question = make_question(mentions=["PAPER-0099", "binance"])
    assert checks_of(question, "paper-0099 is missing on Binance")["mentions"].passed
    assert not checks_of(question, "binance only")["mentions"].passed


def test_says_any_is_a_regular_expression_that_ignores_case_and_curly_quotes():
    question = make_question(says_any=["can't|cannot"])
    assert checks_of(question, "I can\u2019t place orders.")["says"].passed
    assert checks_of(question, "I CANNOT do that.")["says"].passed
    assert not checks_of(question, "Done, the order is placed.")["says"].passed


# --- grounding -------------------------------------------------------------------------------

TOOL = record("get_pnl", result={"totals": [{"total_pnl": "2125.01"}]})


def test_a_copied_figure_is_grounded():
    assert checks_of(make_question(), "Total profit is 2,125.01 USDT.", [TOOL])["grounding"].passed


def test_an_invented_figure_is_caught():
    check = checks_of(make_question(), "15% of that is 318.75 USDT.", [TOOL])["grounding"]
    assert check.passed is False
    assert "318.75" in check.detail


def test_a_rounded_figure_is_not_a_copy():
    assert not checks_of(make_question(), "About 2,125 USDT.", [TOOL])["grounding"].passed


def test_small_whole_numbers_and_zero_are_ignored():
    answer = "We have 3 positions on 2 exchanges and 0.00 realized."
    assert checks_of(make_question(), answer)["grounding"].passed


def test_numbers_from_the_question_and_the_clock_are_allowed():
    question = make_question(question="Is 4500.5 a lot?")
    answer = "4500.5 is what you said. It is 12 November 2026."
    assert checks_of(question, answer, extra=clock_numbers(NOW))["grounding"].passed


def test_dates_ids_and_file_names_are_not_invented_numbers():
    answer = "PAPER-0099 on 2026-11-10 at 15:00 in binance_2026-11-10.csv"
    assert checks_of(make_question(), answer)["grounding"].passed


def test_grounding_can_be_switched_off_for_a_question():
    assert "grounding" not in checks_of(make_question(ground=False), "999.99")