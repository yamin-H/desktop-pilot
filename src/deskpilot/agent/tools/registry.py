import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from deskpilot.agent.data import AgentData
from deskpilot.analytics import LedgerError

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A problem the assistant can understand and explain (bad argument, missing file, ...)."""


class ToolArgs(BaseModel):
    """Base class for tool arguments. Unknown arguments are errors, so invented ones are caught."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    """What a tool is allowed to use."""

    data: AgentData
    statements_dir: Path
    clock: Callable[[], datetime]


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


def _simplify(node: Any) -> Any:
    """Make a Pydantic JSON schema plain: no 'anyOf with null', no titles, no null defaults.

    Simple schemas work with every model provider.
    """
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "anyOf" in node:
        options = [option for option in node["anyOf"] if option.get("type") != "null"]
        if len(options) == 1:
            rest = {key: value for key, value in node.items() if key != "anyOf"}
            simple = _simplify({**rest, **options[0]})
            if len(options) < len(node["anyOf"]):
                # Some models send null for "not given". Say that is allowed.
                simple["type"] = [simple["type"], "null"]
                if "enum" in simple:
                    simple["enum"] = [*simple["enum"], None]
            return simple
    return {key: _simplify(value) for key, value in node.items() if key != "title"}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[ToolArgs]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        """The tool as the model sees it (OpenAI function-calling format)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _simplify(self.args.model_json_schema()),
            },
        }


def _explain(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'arguments'}: {item['msg']}"
        for item in error.errors()
    )


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    async def call(
        self, name: str, raw_arguments: str | None, context: ToolContext
    ) -> dict[str, Any]:
        """Run a tool. Never raises: problems come back as {"error": "..."} for the model."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}. Available tools: {', '.join(self._tools)}"}

        try:
            arguments = json.loads(raw_arguments) if raw_arguments and raw_arguments.strip() else {}
        except json.JSONDecodeError:
            return {"error": "the arguments were not valid JSON"}
        if not isinstance(arguments, dict):
            return {"error": "the arguments must be a JSON object"}

        try:
            args = tool.args.model_validate(arguments)
        except ValidationError as error:
            return {"error": f"invalid arguments: {_explain(error)}"}

        try:
            return await tool.handler(context, args)
        except ToolError as error:
            return {"error": str(error)}
        except LedgerError as error:
            return {"error": f"the ledger cannot be calculated: {error}"}
        except Exception:
            # A bug. Keep the details in our log; the model only gets a safe, generic message.
            logger.exception("tool %s failed unexpectedly", name)
            return {
                "error": f"internal error in tool {name}. Do not guess a result; "
                "tell the user the data could not be retrieved."
            }
