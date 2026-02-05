"""Tool registry that manages tool declarations and execution."""

from __future__ import annotations

from typing import Any

from aurelia.core.models import ToolRegistration


class ToolRegistry:
    """Manages MCP tool registrations and dispatches execution requests."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}

    async def register_builtin(self) -> None:
        """Register built-in tools from the FastMCP server."""
        from aurelia.tools.builtin import mcp as builtin_mcp

        tools = builtin_mcp._tool_manager.list_tools()
        for tool in tools:
            registration = ToolRegistration(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.parameters,
                requires_sandbox=False,
                handler="builtin",
            )
            self._tools[tool.name] = registration

    def get_declarations(self, tool_names: list[str]) -> list[dict[str, Any]]:
        """Get tool declarations in GenAI FunctionDeclaration format.

        Args:
            tool_names: Names of tools to include. Only registered tools are returned.

        Returns:
            List of dicts with ``name``, ``description``, and ``parameters`` keys.
        """
        declarations: list[dict[str, Any]] = []
        for name in tool_names:
            if name not in self._tools:
                continue
            reg = self._tools[name]
            declarations.append(
                {
                    "name": reg.name,
                    "description": reg.description,
                    "parameters": reg.input_schema,
                }
            )
        return declarations

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with given arguments.

        Args:
            name: The registered tool name.
            args: Keyword arguments to pass to the tool.

        Returns:
            Dict containing the tool execution result.

        Raises:
            KeyError: If the tool name is not registered.
        """
        if name not in self._tools:
            raise KeyError(f"Tool not found: '{name}'. Available tools: {list(self._tools)}")

        from aurelia.tools.builtin import mcp as builtin_mcp

        result = await builtin_mcp._tool_manager.call_tool(name, args)
        return {"content": [block.model_dump() for block in result]}
