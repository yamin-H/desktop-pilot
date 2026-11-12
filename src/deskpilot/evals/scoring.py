import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from deskpilot.agent import ToolCallRecord
from deskpilot.evals.golden import CallSpec, GoldenQuestion

_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# Things that contain digits but are not money. Removed before looking for numbers.
_NOT_NUMBERS = (
    re.compile(r"\S+\.csv\b"),  # file names
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?"),  # dates and times
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),  # clock times like 14:15
    re.compile(r"\b[A-Za-z][A-Za-z0-9_]*-\d+\b"),  # identifiers like PAPER-0001
    re.compile(r"(?m)^\s*\d+[.)]\s+"),  # list numbering
)


@dataclass(frozen=True)
class FoundNumber:
    text: str  # as written, e.g. "1,005.23"
    value: Decimal

    @property
    def is_figure(self) -> bool:
        """Looks like an amount, price or quantity, rather than a count or a day number."""
        whole = self.text.replace(",", "").split(".")[0]
        return "." in self.text or len(whole) >= 3


def find_numbers(text: str) -> list[FoundNumber]:
    """Numbers in free text. Signs are ignored; dates, times, IDs and file names are skipped."""
    for pattern in _NOT_NUMBERS:
        text = pattern.sub(" ", text)
    return [FoundNumber(token, Decimal(token.replace(",", ""))) for token in _NUMBER.findall(text)]


def numbers_in_value(value: Any) -> set[Decimal]:
    """Every number inside a tool result (nested dicts, lists, strings and numbers)."""
    if value is None or isinstance(value, bool):
        return set()
    if isinstance(value, int | float):
        return {Decimal(str(value))}
    if isinstance(value, str):
        return {number.value for number in find_numbers(value)}
    if isinstance(value, dict):
        return set().union(*(numbers_in_value(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(numbers_in_value(item) for item in value))
    return set()


def clock_numbers(now: datetime) -> set[Decimal]:
    """The parts of the current time, which the model may legitimately mention (like the year)."""
    return {Decimal(part) for part in (now.year, now.month, now.day, now.hour, now.minute)}


def _normal(key: str, value: Any) -> str:
    text = str(value).strip()
    if key == "symbol":
        return text.upper()
    if key == "exchange":
        return text.lower()
    return text


def _arguments(record: ToolCallRecord) -> dict[str, Any]:
    try:
        data = json.loads(record.arguments) if (record.arguments or "").strip() else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def call_matches(spec: CallSpec, record: ToolCallRecord) -> bool:
    """Did this tool call do what the question needs? Extra arguments are fine."""
    if record.name not in spec.tools or record.failed != spec.error:
        return False
    actual = _arguments(record)
    for key, expected in spec.args.items():
        if key not in actual or _normal(key, actual[key]) != _normal(key, expected):
            return False
    if spec.sales is not None:
        sales = record.result.get("sales", [])
        sold = {sale.get("trade_id") for sale in sales if isinstance(sale, dict)}
        if sold != set(spec.sales):
            return False
    return True


@dataclass(frozen=True)
class Check:
    name: str  # tools, numbers, mentions, says, grounding
    passed: bool
    detail: str = ""


def _describe(spec: CallSpec) -> str:
    extras = []
    if spec.args:
        extras.append(f"arguments {spec.args}")
    if spec.sales is not None:
        extras.append(f"a period containing exactly the sales {spec.sales}")
    if spec.error:
        extras.append("returning an error")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return " or ".join(spec.tools) + suffix


def _check_tools(question: GoldenQuestion, records: Sequence[ToolCallRecord]) -> Check | None:
    if not (question.calls or question.no_tools or question.forbid_tools):
        return None
    problems: list[str] = []
    if question.no_tools and records:
        called = ", ".join(sorted({record.name for record in records}))
        problems.append(f"called {called}, but should not call any tool")
    for spec in question.calls:
        if not any(call_matches(spec, record) for record in records):
            problems.append(f"no matching call to {_describe(spec)}")
    for name in question.forbid_tools:
        if any(record.name == name and not record.failed for record in records):
            problems.append(f"{name} succeeded, but must not")
    return Check("tools", not problems, "; ".join(problems))


def _plain(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'").lower()


def score_answer(
    question: GoldenQuestion,
    answer: str,
    records: Sequence[ToolCallRecord],
    *,
    extra_numbers: Iterable[Decimal] = (),
) -> list[Check]:
    """Score one answer. Returns one Check per thing the question asks about."""
    checks: list[Check] = []

    tools = _check_tools(question, records)
    if tools is not None:
        checks.append(tools)

    if question.numbers:
        found = {number.value for number in find_numbers(answer)}
        missing = [number for number in question.numbers if Decimal(number) not in found]
        detail = f"missing: {', '.join(missing)}" if missing else ""
        checks.append(Check("numbers", not missing, detail))

    if question.mentions:
        lowered = answer.lower()
        missing = [word for word in question.mentions if word.lower() not in lowered]
        detail = f"missing: {', '.join(missing)}" if missing else ""
        checks.append(Check("mentions", not missing, detail))

    if question.says_any:
        plain = _plain(answer)
        matched = any(re.search(pattern, plain, re.IGNORECASE) for pattern in question.says_any)
        checks.append(Check("says", matched, "" if matched else "none of the expected phrases"))

    if question.ground:
        allowed = {Decimal(0), *extra_numbers}
        allowed |= numbers_in_value(question.question)
        for record in records:
            allowed |= numbers_in_value(record.result)
        invented = list(
            dict.fromkeys(
                number.text
                for number in find_numbers(answer)
                if number.is_figure and number.value not in allowed
            )
        )
        detail = f"not in any tool result: {', '.join(invented)}" if invented else ""
        checks.append(Check("grounding", not invented, detail))

    return checks