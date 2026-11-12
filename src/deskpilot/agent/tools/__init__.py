from deskpilot.agent.tools.ledger import LEDGER_TOOLS
from deskpilot.agent.tools.recon import RECON_TOOLS
from deskpilot.agent.tools.registry import Tool, ToolArgs, ToolContext, ToolError, ToolRegistry


def build_default_registry() -> ToolRegistry:
    """All of the assistant's tools. Every one of them is read-only."""
    return ToolRegistry([*LEDGER_TOOLS, *RECON_TOOLS])


__all__ = [
    "Tool",
    "ToolArgs",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "build_default_registry",
]