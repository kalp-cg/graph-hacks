"""The agent reaches the graph only through MCP: it discovers tools with list_tools and calls them."""
import inspect
import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Filled in by the agent loop, never by the model.
HIDDEN_PARAMS = {"run_id", "steps_taken"}


class GraphToolbox:
    """A long-lived MCP session to `python -m sentinel.mcp_server` over stdio."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        self.tools: list[dict] = []          # OpenAI-style function schemas, hidden params removed
        self.hidden: dict[str, set[str]] = {}  # tool name -> hidden params it accepts

    async def start(self) -> "GraphToolbox":
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sentinel.mcp_server"],
            env=dict(os.environ),  # the server needs FALKORDB_* / GRAPH_NAME
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listed = await self.session.list_tools()
        self.tools, self.hidden = [], {}
        for t in listed.tools:
            schema = json.loads(json.dumps(t.input_schema or {"type": "object", "properties": {}}))
            props = schema.get("properties", {})
            hidden = HIDDEN_PARAMS & props.keys()
            for h in hidden:
                props.pop(h)
            if "required" in schema:
                schema["required"] = [r for r in schema["required"] if r not in hidden]
            schema.pop("title", None)
            for p in props.values():
                p.pop("title", None)
            self.hidden[t.name] = hidden
            self.tools.append({"type": "function",
                               "function": {"name": t.name, "description": inspect.cleandoc(t.description or ""),
                                            "parameters": schema}})
        return self

    async def close(self) -> None:
        if self._stack:
            await self._stack.aclose()
            self._stack = None

    async def __aenter__(self) -> "GraphToolbox":
        return await self.start()

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    @property
    def names(self) -> list[str]:
        return [t["function"]["name"] for t in self.tools]

    async def call(self, name: str, args: dict, hidden: dict | None = None) -> dict:
        """Call a tool. Unknown tools and bad arguments come back as error dicts, never exceptions."""
        if name not in self.hidden:
            return {"error": "unknown_tool", "message": f"no tool named {name!r}; available: {self.names}"}
        clean = {k: v for k, v in (args or {}).items() if k not in HIDDEN_PARAMS}
        for k, v in (hidden or {}).items():
            if k in self.hidden[name]:
                clean[k] = v
        assert self.session is not None
        res = await self.session.call_tool(name, clean)
        text = "".join(getattr(c, "text", "") for c in res.content)
        if res.is_error:
            return {"error": "tool_failed", "message": text[:500]}
        if isinstance(res.structured_content, dict) and res.structured_content:
            return res.structured_content
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"result": text}
