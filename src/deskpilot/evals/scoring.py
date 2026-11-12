import json
import re
from dataclasses import dataclass
from decimal import Decimal

from deskpilot.agent import Answer

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
SMALL_COUNT = Decimal(10)  # "3 trades", "5 breaks": counting words are not money


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    expected_tools: tuple[str, ...] = ()  # every one of these must be called
    required: tuple[str, ...] = ()  # every one of these must appear in the answer
    forbidden: tuple[str, ...] = ()  # none of these may appear (lowercase)


@dataclass(frozen=True)
class CaseScore:
    tools_ok: bool
    required_ok: bool
    forbidden_ok: bool
    ungrounded: tuple[str, ...]  # numbers the model produced from nowhere

    @property
    def grounded(self) -> bool:
        return not self.ungrounded

    @property
    def passed(self) -> bool:
        return self.tools_ok and self.required_ok and self.forbidden_ok and self.grounded


def _clean(text: str) -> str:
    """'60,393.93' becomes '60393.93' so commas never hide a match."""
    return _THOUSANDS.sub("", text)


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(raw) for raw in _NUMBER.findall(_clean(text))}


def score(case: EvalCase, answer: Answer) -> CaseScore:
    called = {record.name for record in answer.tool_calls}
    text = _clean(answer.text)

    source = " ".join(
        [case.question]
        + [f"{record.arguments} {json.dumps(record.result)}" for record in answer.tool_calls]
    )
    allowed = _numbers(source)
    ungrounded = tuple(
        sorted(
            format(number.normalize(), "f")
            for number in _numbers(text)
            if number not in allowed
            and not (number == number.to_integral_value() and number <= SMALL_COUNT)
        )
    )

    return CaseScore(
        tools_ok=set(case.expected_tools) <= called,
        required_ok=all(item in text for item in case.required),
        forbidden_ok=not any(item in text.lower() for item in case.forbidden),
        ungrounded=ungrounded,
    )
