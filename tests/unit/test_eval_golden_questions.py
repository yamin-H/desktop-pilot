import json
from decimal import Decimal
from pathlib import Path

import pytest

from deskpilot.agent import StaticData, ToolCallRecord, ToolContext, build_default_registry
from deskpilot.evals.dataset import EVAL_NOW, EVAL_PRICES, PAPER_TRADES
from deskpilot.evals.golden import load_golden_questions
from deskpilot.evals.scoring import call_matches, numbers_in_value

TESTS = Path(__file__).resolve().parents[1]
GOLDEN = TESTS / "agent_evals" / "golden_questions.yaml"
STATEMENTS = TESTS.parent / "data" / "statements"

QUESTIONS = load_golden_questions(GOLDEN)


def test_there_are_thirty_questions():
    assert len(QUESTIONS) == 30


def test_every_tool_is_covered_by_at_least_one_question():
    covered = {step.tool for question in QUESTIONS for step in question.oracle}
    assert covered == set(build_default_registry().names)


def test_every_tool_named_in_the_file_exists():
    known = set(build_default_registry().names)
    for question in QUESTIONS:
        used = {step.tool for step in question.oracle}
        used |= set(question.forbid_tools)
        used |= {tool for spec in question.calls for tool in spec.tools}
        assert used <= known, f"{question.id} names an unknown tool: {used - known}"


def test_every_question_checks_something_beyond_grounding():
    for question in QUESTIONS:
        assert (
            question.calls
            or question.no_tools
            or question.forbid_tools
            or question.numbers
            or question.mentions
            or question.says_any
        ), question.id


@pytest.mark.parametrize("question", QUESTIONS, ids=lambda q: q.id)
async def test_the_golden_answers_really_come_out_of_the_tools(question):
    registry = build_default_registry()
    context = ToolContext(
        data=StaticData(PAPER_TRADES, EVAL_PRICES),
        statements_dir=STATEMENTS,
        clock=lambda: EVAL_NOW,
    )

    records = []
    for step in question.oracle:
        arguments = json.dumps(step.args)
        result = await registry.call(step.tool, arguments, context)
        assert ("error" in result) == step.error, f"{step.tool} gave {result}"
        records.append(ToolCallRecord(step.tool, arguments, result))

    # Every call the model is required to make must be satisfied by the oracle's own calls.
    for spec in question.calls:
        assert any(call_matches(spec, record) for record in records), f"nothing matches {spec}"

    available = set()
    text = ""
    for record in records:
        available |= numbers_in_value(record.result)
        text += json.dumps(record.result).lower()

    for number in question.numbers:
        assert Decimal(number) in available, f"{number} is not in any tool result"
    for word in question.mentions:
        assert word.lower() in text, f"{word!r} is not in any tool result"