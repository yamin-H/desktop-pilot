import pytest

from deskpilot.evals.golden import GoldenError, load_golden_questions

VALID = """
- id: a
  question: "Q?"
  numbers: ["1.5"]
"""


def load(tmp_path, text):
    path = tmp_path / "questions.yaml"
    path.write_text(text, encoding="utf-8")
    return load_golden_questions(path)


def test_a_valid_file_loads(tmp_path):
    [question] = load(tmp_path, VALID)
    assert (question.id, question.numbers, question.ground) == ("a", ["1.5"], True)


def test_a_misspelled_field_is_refused_instead_of_ignored(tmp_path):
    with pytest.raises(GoldenError, match="number"):
        load(tmp_path, '- id: a\n  question: "Q?"\n  number: ["1.5"]\n')


def test_numbers_must_be_quoted_so_they_never_become_floats(tmp_path):
    with pytest.raises(GoldenError, match="numbers"):
        load(tmp_path, '- id: a\n  question: "Q?"\n  numbers: [1.5]\n')


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity"])
def test_numbers_must_be_finite_numbers(tmp_path, bad):
    with pytest.raises(GoldenError, match="numbers"):
        load(tmp_path, f'- id: a\n  question: "Q?"\n  numbers: ["{bad}"]\n')


def test_a_broken_regular_expression_is_refused(tmp_path):
    with pytest.raises(GoldenError, match="regular expression"):
        load(tmp_path, '- id: a\n  question: "Q?"\n  says_any: ["(unclosed"]\n')


def test_duplicate_ids_are_refused(tmp_path):
    text = '- id: a\n  question: "Q?"\n- id: a\n  question: "R?"\n'
    with pytest.raises(GoldenError, match="duplicate"):
        load(tmp_path, text)


def test_no_tools_cannot_be_combined_with_calls(tmp_path):
    text = '- id: a\n  question: "Q?"\n  no_tools: true\n  calls: [{tool: get_pnl}]\n'
    with pytest.raises(GoldenError, match="no_tools"):
        load(tmp_path, text)


def test_the_error_names_the_question(tmp_path):
    with pytest.raises(GoldenError, match=r"question #2 \(second\)"):
        load(tmp_path, '- id: first\n  question: "Q?"\n- id: second\n  colour: red\n')


@pytest.mark.parametrize("text", ["", "id: a", "[]", "- just text", ": : :"])
def test_a_file_that_is_not_a_list_of_questions_is_refused(tmp_path, text):
    with pytest.raises(GoldenError):
        load(tmp_path, text)


def test_a_call_can_name_one_tool_or_several(tmp_path):
    text = (
        '- id: a\n  question: "Q?"\n'
        "  calls:\n    - tool: get_pnl\n    - tool: [get_pnl, get_positions]\n"
    )
    [question] = load(tmp_path, text)
    assert [spec.tools for spec in question.calls] == [
        ("get_pnl",),
        ("get_pnl", "get_positions"),
    ]
