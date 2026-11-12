from deskpilot.agent import Answer, ToolCallRecord
from deskpilot.evals.scoring import EvalCase, score

POSITIONS = ToolCallRecord(
    "get_positions",
    "{}",
    {"positions": [{"symbol": "BTC/USDT", "quantity": "0.3495", "average_cost": "60393.93"}]},
)


def answer(text, *calls):
    return Answer(text=text, tool_calls=tuple(calls), steps=2)


CASE = EvalCase(
    id="positions",
    category="positions",
    question="What are our positions?",
    expected_tools=("get_positions",),
    required=("0.3495", "60393.93"),
)


def test_a_correct_grounded_answer_passes():
    result = score(
        CASE, answer("We hold 0.3495 BTC at an average cost of 60393.93 USDT.", POSITIONS)
    )
    assert result.passed


def test_commas_and_currency_signs_do_not_matter():
    assert score(CASE, answer("0.3495 BTC at $60,393.93 each.", POSITIONS)).passed


def test_a_missing_tool_call_fails():
    result = score(CASE, answer("We hold 0.3495 BTC at 60393.93."))
    assert not result.tools_ok


def test_a_missing_number_fails():
    result = score(CASE, answer("We hold some BTC.", POSITIONS))
    assert not result.required_ok


def test_a_number_the_model_made_up_is_caught():
    result = score(CASE, answer("0.3495 BTC at 60393.93, worth 21107.40 USDT.", POSITIONS))
    assert not result.grounded
    assert result.ungrounded == ("21107.4",)
    assert not result.passed


def test_numbers_from_the_question_are_allowed():
    case = EvalCase("pct", "refusal", "What is 15% of our profit?")
    assert score(case, answer("I cannot calculate 15% for you.")).grounded


def test_small_counting_numbers_are_ignored():
    assert score(CASE, answer("3 positions: 0.3495 BTC at 60393.93.", POSITIONS)).grounded


def test_forbidden_text_fails():
    case = EvalCase("buy", "refusal", "Buy 1 BTC.", forbidden=("order placed",))
    assert not score(case, answer("Order placed for 1 BTC.")).forbidden_ok
