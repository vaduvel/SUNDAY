"""J.A.R.V.I.S. MCP tool registry with schema-aware validation."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from core.schema_validation import (
    SchemaValidationError,
    ensure_object_schema,
    validate_arguments,
    validate_tool_schema,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Standardized local tool definition."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]


class MCPRegistry:
    """Universal registry for JARVIS tools."""

    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self.tracer: Any | None = None
        logger.info("🔌 [MCP] Agentic OS Tool Registry initialized.")

    def set_tracer(self, tracer: Any) -> None:
        """Attach a lightweight tracer used for MCP tool calls."""
        self.tracer = tracer

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any] | None,
        handler: Callable[..., Any],
    ) -> MCPTool:
        """Standardize a local function into an MCP-compliant tool."""
        if not callable(handler):
            raise TypeError(f"Handler for tool '{name}' must be callable.")

        normalized_schema = validate_tool_schema(parameters)
        tool = MCPTool(
            name=name,
            description=description,
            parameters=normalized_schema,
            handler=handler,
        )
        self.tools[name] = tool
        logger.info("✅ [MCP] Tool registered: %s", name)
        return tool

    def get_tool_listing(self) -> List[Dict[str, Any]]:
        """Return tool definitions for LLM context / MCP discovery."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": ensure_object_schema(tool.parameters),
            }
            for tool in self.tools.values()
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any] | None) -> Any:
        """Unified execution bridge with runtime schema validation."""
        tool = self.tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found."}

        span_id = None
        if self.tracer:
            span_id = self.tracer.start_span(
                "mcp_registry_tool",
                name,
                {"argument_keys": sorted((arguments or {}).keys())},
            )

        try:
            validated_arguments = validate_arguments(arguments, tool.parameters)
        except SchemaValidationError as exc:
            logger.info("⚠️ [MCP] Validation failed for %s: %s", name, exc)
            if span_id:
                self.tracer.end_span(
                    span_id,
                    status="validation_error",
                    error=str(exc),
                )
            return {"error": "Tool input validation failed.", "details": str(exc)}

        logger.info("🚀 [MCP] Executing tool: %s with args: %s", name, validated_arguments)

        try:
            result = tool.handler(**validated_arguments)
            if inspect.isawaitable(result):
                result = await result
            if span_id:
                self.tracer.end_span(
                    span_id,
                    attributes={"result_type": type(result).__name__},
                )
            return result
        except Exception as exc:  # pragma: no cover - defensive runtime wrapper
            logger.error("❌ [MCP] Tool execution error (%s): %s", name, exc)
            if span_id:
                self.tracer.end_span(
                    span_id,
                    status="error",
                    error=str(exc),
                )
            return {"error": "Tool execution failed.", "details": str(exc)}


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════


async def test_tool(msg: str):
    return f"Processed: {msg}"


async def main():
    mcp = MCPRegistry()
    mcp.register_tool(
        name="test_tool",
        description="A simple test tool",
        parameters={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        handler=test_tool,
    )

    result = await mcp.call_tool("test_tool", {"msg": "GALAXY AEON 2026"})
    print(f"📡 [MCP] Test Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
