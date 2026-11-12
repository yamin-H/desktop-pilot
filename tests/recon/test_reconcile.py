from datetime import UTC, datetime, timedelta

import pytest

from deskpilot.models import Exchange
from deskpilot.recon.matcher import ReconInputError, reconcile
from deskpilot.recon.report import format_report
from deskpilot.recon.rules import BreakKind, Tolerances

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
END = START + timedelta(days=1)
NOON = START + timedelta(hours=12)  # the default time of make_trade()
NAIVE = datetime(2026, 1, 1)


def run(ledger, statement, **kwargs):
    return reconcile(ledger, statement, exchange=Exchange.BINANCE, start=START, end=END, **kwargs)


def kinds(report):
    return [item.kind for item in report.breaks]


def test_two_empty_sides_are_clean():
    report = run([], [])
    assert report.is_clean
    assert (report.statement_trades, report.ledger_trades, report.matched) == (0, 0, 0)


def test_identical_trades_are_clean(make_trade):
    report = run([make_trade()], [make_trade()])
    assert report.is_clean
    assert (report.matched, report.matched_clean) == (1, 1)


def test_a_trade_only_the_exchange_knows_about(make_trade):
    report = run([], [make_trade()])
    assert kinds(report) == [BreakKind.MISSING_IN_LEDGER]
    assert report.matched == 0


def test_a_trade_only_we_know_about(make_trade):
    report = run([make_trade()], [])
    assert kinds(report) == [BreakKind.MISSING_IN_STATEMENT]


def test_our_trades_outside_the_period_are_not_blamed(make_trade):
    older = make_trade(trade_id="OLD", executed_at=START - timedelta(hours=1))
    report = run([older], [])
    assert report.is_clean
    assert report.ledger_trades == 1
    assert report.ignored_outside_period == 1


def test_the_period_includes_its_start_but_not_its_end(make_trade):
    at_start = make_trade(trade_id="A", executed_at=START)
    at_end = make_trade(trade_id="B", executed_at=END)
    report = run([at_start, at_end], [])
    assert [item.trade_id for item in report.breaks] == ["A"]
    assert report.ignored_outside_period == 1


def test_a_statement_trade_outside_the_period_must_still_be_in_the_ledger(make_trade):
    late = make_trade(executed_at=END + timedelta(hours=1))
    assert kinds(run([], [late])) == [BreakKind.MISSING_IN_LEDGER]


def test_a_matched_pair_is_compared_even_across_the_period_boundary(make_trade):
    ours = make_trade(executed_at=END - timedelta(milliseconds=500))
    theirs = make_trade(executed_at=END + timedelta(milliseconds=500))
    assert run([ours], [theirs]).is_clean  # 1 second apart, which is allowed


def test_other_exchanges_in_the_ledger_are_ignored(make_trade):
    report = run([make_trade(exchange="kraken", trade_id="K-1")], [])
    assert report.is_clean
    assert report.ledger_trades == 0


def test_the_same_id_on_another_exchange_is_not_a_match(make_trade):
    report = run([make_trade(exchange="kraken")], [make_trade()])
    assert kinds(report) == [BreakKind.MISSING_IN_LEDGER]


def test_a_statement_from_the_wrong_exchange_is_refused(make_trade):
    with pytest.raises(ReconInputError, match="kraken"):
        run([], [make_trade(exchange="kraken")])


def test_a_ledger_that_lists_a_trade_twice_is_refused(make_trade):
    with pytest.raises(ReconInputError, match="more than once"):
        run([make_trade(), make_trade()], [])


def test_a_trade_listed_twice_on_the_statement_is_a_break_but_the_first_still_matches(
    make_trade,
):
    report = run([make_trade()], [make_trade(), make_trade()])
    assert kinds(report) == [BreakKind.DUPLICATE_IN_STATEMENT]
    assert (report.statement_trades, report.matched, report.matched_clean) == (1, 1, 1)
    assert "identical" in report.breaks[0].detail


def test_a_duplicate_with_different_content_is_described(make_trade):
    report = run([make_trade()], [make_trade(), make_trade(quantity="3")])
    assert "different content" in report.breaks[0].detail


def test_differences_between_matched_trades_become_breaks(make_trade):
    report = run([make_trade(quantity="2")], [make_trade(quantity="1.998")])
    assert kinds(report) == [BreakKind.QUANTITY_MISMATCH]
    assert (report.matched, report.matched_clean) == (1, 0)


def test_breaks_are_ordered_by_time_then_trade_id_then_kind(make_trade):
    later = NOON + timedelta(hours=1)
    ledger = [
        make_trade(trade_id="B", executed_at=later),
        make_trade(trade_id="Z", executed_at=NOON),
    ]
    statement = [make_trade(trade_id="B", executed_at=later, quantity="3", fee="0.5")]
    report = run(ledger, statement)
    assert [(item.trade_id, item.kind) for item in report.breaks] == [
        ("Z", BreakKind.MISSING_IN_STATEMENT),
        ("B", BreakKind.QUANTITY_MISMATCH),
        ("B", BreakKind.FEE_MISMATCH),
    ]


def test_every_trade_is_accounted_for(make_trade):
    ledger = [
        make_trade(trade_id="A"),
        make_trade(trade_id="B"),
        make_trade(trade_id="OLD", executed_at=START - timedelta(days=1)),
        make_trade(trade_id="ONLY-US"),
    ]
    statement = [
        make_trade(trade_id="A"),
        make_trade(trade_id="B", quantity="3"),
        make_trade(trade_id="ONLY-THEM"),
    ]
    report = run(ledger, statement)
    counts = report.counts()

    only_them = counts[BreakKind.MISSING_IN_LEDGER]
    only_us = counts[BreakKind.MISSING_IN_STATEMENT]
    assert report.statement_trades == report.matched + only_them == 3
    assert report.ledger_trades == report.matched + only_us + report.ignored_outside_period == 4


def test_counts_lists_only_kinds_that_occurred_in_a_fixed_order(make_trade):
    report = run([make_trade(trade_id="B")], [make_trade(trade_id="A")])
    assert list(report.counts().items()) == [
        (BreakKind.MISSING_IN_LEDGER, 1),
        (BreakKind.MISSING_IN_STATEMENT, 1),
    ]


def test_a_wider_time_tolerance_can_be_given(make_trade):
    late = make_trade(executed_at=NOON + timedelta(seconds=5))
    assert kinds(run([make_trade()], [late])) == [BreakKind.TIME_DRIFT]
    assert run([make_trade()], [late], tolerances=Tolerances(timedelta(seconds=10))).is_clean


def test_generators_are_accepted(make_trade):
    report = run((t for t in [make_trade()]), (t for t in [make_trade()]))
    assert report.is_clean


@pytest.mark.parametrize(
    ("start", "end"), [(NAIVE, END), (START, NAIVE), (END, START), (START, START)]
)
def test_bad_periods_are_refused(start, end):
    with pytest.raises(ValueError):
        reconcile([], [], exchange=Exchange.BINANCE, start=start, end=end)


def test_a_clean_report_says_so(make_trade):
    text = format_report(run([make_trade()], [make_trade()]))
    assert "binance" in text
    assert "RESULT: clean" in text


def test_a_report_with_breaks_lists_each_one(make_trade):
    report = run(
        [make_trade(quantity="2")],
        [make_trade(quantity="1.998"), make_trade(trade_id="T-2")],
    )
    text = format_report(report)
    assert "RESULT: 2 breaks" in text
    assert "quantity_mismatch" in text
    assert "missing_in_ledger" in text
    assert "T-1" in text and "T-2" in text
    assert "ledger 2, statement 1.998" in text


def test_one_break_is_not_pluralised(make_trade):
    text = format_report(run([make_trade()], []))
    assert "RESULT: 1 break\n" in text + "\n"
    assert "1 breaks" not in text


def test_the_report_mentions_ignored_trades(make_trade):
    older = make_trade(executed_at=START - timedelta(hours=1))
    assert "outside the period" in format_report(run([older], []))
