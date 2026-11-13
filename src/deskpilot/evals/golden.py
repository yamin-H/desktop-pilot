import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class GoldenError(ValueError):
    """The golden questions file is not valid."""


class OracleCall(BaseModel):
    """A tool call that produces the right answer. A test uses these to PROVE the golden numbers."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    args: dict[str, str | int] = Field(default_factory=dict)
    error: bool = False  # true if this call is supposed to come back as an error


class CallSpec(BaseModel):
    """A tool call the model must make."""

    model_config = ConfigDict(extra="forbid")

    tool: str | list[str]  # a name, or a list meaning "any of these"
    args: dict[str, str] = Field(default_factory=dict)  # must match (exchange/symbol ignore case)
    sales: list[str] | None = None  # get_realized_pnl: the exact trade IDs the period must contain
    error: bool = False  # true if the call is expected to come back as an error

    @property
    def tools(self) -> tuple[str, ...]:
        return (self.tool,) if isinstance(self.tool, str) else tuple(self.tool)


class GoldenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    why: str = ""
    oracle: list[OracleCall] = Field(default_factory=list)
    calls: list[CallSpec] = Field(default_factory=list)
    no_tools: bool = False  # the model must not call any tool
    forbid_tools: list[str] = Field(default_factory=list)  # must not be called successfully
    numbers: list[str] = Field(default_factory=list)  # the answer must contain these
    mentions: list[str] = Field(default_factory=list)  # the answer must contain these words
    says_any: list[str] = Field(default_factory=list)  # regexes; at least one must match
    ground: bool = True  # every figure in the answer must appear in a tool result

    @field_validator("numbers")
    @classmethod
    def _numbers_must_be_numbers(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise ValueError(f"{value!r} is not a number") from None
            if not number.is_finite():
                raise ValueError(f"{value!r} is not a finite number")
        return values

    @field_validator("says_any")
    @classmethod
    def _patterns_must_compile(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                re.compile(value)
            except re.error as error:
                raise ValueError(f"{value!r} is not a valid regular expression: {error}") from None
        return values

    @model_validator(mode="after")
    def _no_tools_means_no_calls(self) -> "GoldenQuestion":
        if self.no_tools and self.calls:
            raise ValueError("no_tools cannot be combined with calls")
        return self


def load_golden_questions(path: Path) -> list[GoldenQuestion]:
    try:
        data: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise GoldenError(f"{path}: not valid YAML: {error}") from None
    if not isinstance(data, list) or not data:
        raise GoldenError(f"{path}: expected a non-empty list of questions")

    questions: list[GoldenQuestion] = []
    seen: set[str] = set()
    for index, item in enumerate(data, start=1):
        label = item.get("id", "?") if isinstance(item, dict) else "?"
        try:
            question = GoldenQuestion.model_validate(item)
        except ValidationError as error:
            raise GoldenError(f"question #{index} ({label}): {error}") from None
        if question.id in seen:
            raise GoldenError(f"duplicate question id {question.id!r}")
        seen.add(question.id)
        questions.append(question)
    return questions
