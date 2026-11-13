import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deskpilot.agent import Agent, StaticData, ToolContext, build_default_registry
from deskpilot.evals.dataset import EVAL_NOW, EVAL_PRICES, PAPER_TRADES
from deskpilot.evals.golden import load_golden_questions
from deskpilot.evals.runner import (
    Ratio,
    format_markdown,
    format_report,
    run_evaluation,
    summarize,
    write_transcript,
)
from deskpilot.evals.scoring import clock_numbers

TESTS = Path(__file__).resolve().parents[1]
Q = {q.id: q for q in load_golden_questions(TESTS / "agent_evals" / "golden_questions.yaml")}
STATEMENTS = TESTS.parent / "data" / "statements"
REFUSAL = "I can't place orders. I'm read-only."


class FakeProviderError(Exception):
    pass


class FakeClient:
    """Looks like the OpenAI async client and plays back scripted replies."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def say(text):
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def use_tool(call_id, name, arguments="{}"):
    function = SimpleNamespace(name=name, arguments=arguments)
    call = SimpleNamespace(id=call_id, type="function", function=function)
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_agent(replies):
    context = ToolContext(
        data=StaticData(PAPER_TRADES, EVAL_PRICES),
        statements_dir=STATEMENTS,
        clock=lambda: EVAL_NOW,
    )
    return Agent(FakeClient(replies), "test-model", build_default_registry(), context)


async def evaluate(replies, questions, **kwargs):
    kwargs.setdefault("extra_numbers", clock_numbers(EVAL_NOW))
    return await run_evaluation(make_agent(replies), questions, **kwargs)


async def test_a_faithful_model_passes():
    replies = [use_tool("1", "get_pnl"), say("Total profit is 2125.01 USDT."), say(REFUSAL)]
    results = await evaluate(replies, [Q["pnl-total"], Q["refuse-trade"]])
    assert [r.passed for r in results] == [True, True]
    assert [r.steps for r in results] == [2, 1]
    assert results[0].records[0].name == "get_pnl"


async def test_a_model_that_rounds_and_invents_numbers_is_caught():
    cheat = say("Total profit is about 2,125 USDT, and 15% of it is 318.75 USDT.")
    [result] = await evaluate([use_tool("1", "get_pnl"), cheat], [Q["pnl-total"]])

    assert result.passed is False
    failed = {check.name: check for check in result.checks if not check.passed}
    assert set(failed) == {"numbers", "grounding"}  # it did call the right tool
    assert "2125.01" in failed["numbers"].detail
    assert "318.75" in failed["grounding"].detail


async def test_a_model_that_pretends_to_place_the_order_is_caught():
    [result] = await evaluate(
        [use_tool("1", "get_positions"), say("Done, order placed.")], [Q["refuse-trade"]]
    )
    failed = {check.name for check in result.checks if not check.passed}
    assert failed == {"tools", "says"}


async def test_the_wrong_period_is_caught_even_when_the_answer_looks_plausible():
    wrong_period = use_tool("1", "get_realized_pnl", '{"start": "2026-11-10", "end": "2026-11-11"}')
    [result] = await evaluate(
        [wrong_period, say("We made 1005.23 USDT yesterday.")], [Q["real-yesterday"]]
    )
    failed = {check.name for check in result.checks if not check.passed}
    assert "tools" in failed  # that period holds the wrong sales
    assert "numbers" in failed  # 87.3 is missing


async def test_any_sensible_phrasing_of_the_period_passes():
    call = use_tool(
        "1", "get_realized_pnl", '{"start": "2026-11-11T00:00:00Z", "end": "2026-11-11T23:59:59Z"}'
    )
    [result] = await evaluate([call, say("Yesterday we made 87.30 USDT.")], [Q["real-yesterday"]])
    assert result.passed


async def test_provider_errors_are_recorded_and_the_run_continues():
    replies = [FakeProviderError("rate limited"), say(REFUSAL)]
    results = await evaluate(
        replies, [Q["pnl-total"], Q["refuse-trade"]], provider_errors=(FakeProviderError,)
    )
    assert results[0].error == "FakeProviderError: rate limited"
    assert results[0].answer is None
    assert results[0].passed is False
    assert results[1].passed is True


async def test_an_unexpected_exception_is_a_bug_and_is_not_swallowed():
    with pytest.raises(FakeProviderError):
        await evaluate([FakeProviderError("surprise")], [Q["pnl-total"]])


async def test_an_empty_answer_is_recorded_as_an_error():
    [result] = await evaluate([say("")], [Q["refuse-trade"]])
    assert "empty" in result.error
    assert result.passed is False


async def test_each_question_can_be_repeated():
    results = await evaluate([say(REFUSAL)] * 3, [Q["refuse-trade"]], repeat=3)
    assert [r.attempt for r in results] == [1, 2, 3]


async def test_there_is_a_pause_between_runs_but_not_before_the_first(monkeypatch):
    pauses = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await evaluate([say(REFUSAL)] * 3, [Q["refuse-trade"]], repeat=3, delay=2.0)
    assert pauses == [2.0, 2.0]


async def test_a_callback_is_told_about_every_run():
    seen = []
    await evaluate([say(REFUSAL)] * 2, [Q["refuse-trade"]], repeat=2, on_result=seen.append)
    assert [r.attempt for r in seen] == [1, 2]


async def test_repeat_must_be_positive():
    with pytest.raises(ValueError):
        await evaluate([], [Q["refuse-trade"]], repeat=0)


async def _mixed_results():
    replies = [
        use_tool("1", "get_pnl"),
        say("Total profit is about 2,125 USDT."),  # fails numbers and grounding
        say(REFUSAL),  # passes
        FakeProviderError("down"),  # no answer
    ]
    return await evaluate(
        replies,
        [Q["pnl-total"], Q["refuse-trade"], Q["refuse-trade"]],
        provider_errors=(FakeProviderError,),
    )


async def test_the_summary_counts_each_check_over_answered_runs_only():
    summary = summarize(await _mixed_results())
    assert (summary.runs, summary.passed, summary.errors) == (3, 1, 1)
    assert summary.checks["tools"] == Ratio(2, 2)
    assert summary.checks["numbers"] == Ratio(0, 1)
    assert summary.checks["grounding"] == Ratio(1, 2)
    assert summary.checks["says"] == Ratio(1, 1)
    assert "mentions" not in summary.checks


def test_a_ratio_prints_as_a_count_and_a_percentage():
    assert str(Ratio(29, 30)) == "29/30 (96.7%)"
    assert str(Ratio(0, 0)) == "0/0 (0.0%)"


async def test_the_text_report_names_failures_and_gives_the_summary():
    text = format_report(await _mixed_results(), model="test-model")
    assert "pnl-total" in text and "FAIL" in text
    assert "numbers: missing: 2125.01" in text
    assert "FakeProviderError: down" in text
    assert "SUMMARY (test-model)" in text
    assert "Numeric correctness" in text
    assert "0/1 (0.0%)" in text


async def test_a_repeated_question_shows_how_many_attempts_passed():
    results = await evaluate([say(REFUSAL), say("Order placed!")], [Q["refuse-trade"]], repeat=2)
    assert "1/2" in format_report(results)


async def test_the_markdown_table_is_ready_for_a_readme():
    text = format_markdown(await _mixed_results(), model="test-model")
    assert "`test-model`" in text
    assert "| Check | Result |" in text
    assert "| Numeric correctness | 0/1 (0.0%) |" in text
    assert "Failed: pnl-total, refuse-trade" in text


async def test_the_transcript_keeps_answers_tool_calls_and_scores(tmp_path):
    results = await evaluate(
        [use_tool("1", "get_pnl"), say("Total profit is 2125.01 USDT.")], [Q["pnl-total"]]
    )
    path = tmp_path / "nested" / "run.jsonl"
    write_transcript(results, path)

    [line] = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(line)
    assert row["id"] == "pnl-total"
    assert row["passed"] is True
    assert row["answer"] == "Total profit is 2125.01 USDT."
    assert row["tool_calls"][0]["name"] == "get_pnl"
    assert row["tool_calls"][0]["result"]["totals"][0]["total_pnl"] == "2125.01"
    assert {check["name"] for check in row["checks"]} == {"tools", "numbers", "grounding"}
