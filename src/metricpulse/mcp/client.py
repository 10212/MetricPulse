"""MCP HTTP client implementation."""

from __future__ import annotations

import json
from typing import Any

import httpx


class MCPError(Exception):
    """MCP client error."""


class MCPClient:
    """MCP client for calling remote MCP services.

    Usage:
        async with MCPClient("http://127.0.0.1:8766/mcp") as client:
            connected = await client.connect()
            tools = await client.get_tools()
            result = await client.call_tool("tool_name", {"arg": "value"})
    """

    def __init__(self, url: str, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.url = url
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=url,
            timeout=httpx.Timeout(timeout),
            headers=headers,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "MCPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def connect(self) -> bool:
        """Check if the MCP server is reachable."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    async def get_tools(self) -> list[dict]:
        """Fetch the tool list from the MCP server.

        Returns a list of tool dicts, each with name, description, inputSchema keys.
        """
        try:
            resp = await self._client.post("/tools/list")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise MCPError(f"Failed to get tools: HTTP {exc.response.status_code}") from exc
        except (httpx.RequestError, json.JSONDecodeError) as exc:
            raise MCPError(str(exc)) from exc

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool on the MCP server."""
        try:
            resp = await self._client.post("/tools/call", json={"name": name, "arguments": arguments})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise MCPError(f"Tool call [{name}] failed: HTTP {exc.response.status_code}") from exc
        except (httpx.RequestError, json.JSONDecodeError) as exc:
            raise MCPError(str(exc)) from exc
