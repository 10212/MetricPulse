"""MCP tools converter - converts MCP tools list to LangChain-compatible tools."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from .client import MCPClient


def _format_params_for_display(schema: dict | None) -> str:
    """Convert JSON Schema properties to human-readable parameter descriptions."""
    if not schema:
        return ""
    props = schema.get("properties", {})
    if not props:
        return ""
    required = set(schema.get("required", []))
    parts = []
    for name, prop in props.items():
        ptype = prop.get("type", "any")
        req = "(required)" if name in required else "(optional)"
        desc = prop.get("description", "")
        parts.append(f"  {name}: {ptype} {req} - {desc}")
    return "\n".join(parts)


def create_mcp_tools(mcp_client: MCPClient, tools_list: list[dict]) -> list:
    """Convert an MCP tools list into LangChain-compatible tool objects.

    Args:
        mcp_client: An initialized MCPClient instance.
        tools_list: List of tools from the MCP server.
            Each item: {"name": ..., "description": ..., "inputSchema": {...}}

    Returns:
        A list of LangChain tool objects ready to bind to an LLM.
    """
    langchain_tools = []

    for tool_info in tools_list:
        tool_name = tool_info["name"]
        tool_desc = tool_info.get("description", "")
        input_schema = tool_info.get("inputSchema", {})
        params_display = _format_params_for_display(input_schema)

        full_description = (
            f"{tool_desc}\n\nParameters:\n{params_display}"
            if params_display
            else tool_desc
        )

        # Capture current loop variables in a factory closure
        def _make_tool(name: str, desc: str) -> Any:
            @tool(name, description=desc)
            async def _fn(arguments: str = "") -> str:
                """Invoke a remote MCP tool.

                Args:
                    arguments: JSON string of the tool arguments.
                """
                try:
                    args_dict = json.loads(arguments) if arguments else {}
                    result = await mcp_client.call_tool(name, args_dict)
                    return json.dumps(result, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    return f"Invalid JSON arguments: {arguments}"
                except Exception as e:
                    return f"MCP tool call failed [{name}]: {e}"
            return _fn

        tool_obj = _make_tool(tool_name, full_description)
        langchain_tools.append(tool_obj)

    return langchain_tools
