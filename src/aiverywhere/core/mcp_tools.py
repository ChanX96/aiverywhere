"""Optional stdio MCP connections, scoped to one task and opened on discovery."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import AsyncExitStack
from datetime import timedelta

from .store import Store, normalized


class RemoteTools:
    def __init__(self, store: Store, names: tuple[str, ...], resources: AsyncExitStack):
        self.store, self.names, self.resources = store, names, resources
        self.sessions = {}
        self.allowed = {}
        self.selected = {}

    async def _session(self, server: str):
        if server not in self.names:
            raise PermissionError("本次任务未授权该 MCP 服务")
        if server in self.sessions:
            return self.sessions[server]
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise ValueError("MCP 需要 Python 3.10+ 和 python -m pip install '.[mcp]'") from exc
        config = self.store.configuration().get("mcpServers", {})[server]
        if "allowedTools" in config:
            allowed = config["allowedTools"]
            if not isinstance(allowed, list) or not all(isinstance(n, str) for n in allowed):
                raise ValueError("allowedTools 必须是工具名称列表")
            self.allowed[server] = set(allowed)
        params = StdioServerParameters(command=config["command"], args=config.get("args", []),
                                       env=config.get("env"), cwd=self.store.project)
        reader, writer = await self.resources.enter_async_context(stdio_client(params))
        session = await self.resources.enter_async_context(
            ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)))
        await session.initialize()
        self.sessions[server] = session
        return session

    async def _list(self, server: str):
        from mcp.types import PaginatedRequestParams

        session = await self._session(server)
        page = await session.list_tools()
        seen = set()
        while True:
            for item in page.tools:
                if server not in self.allowed or item.name in self.allowed[server]:
                    yield item
            if not page.nextCursor:
                break
            if page.nextCursor in seen:
                raise ValueError("MCP 服务重复返回同一分页游标")
            seen.add(page.nextCursor)
            page = await session.list_tools(params=PaginatedRequestParams(cursor=page.nextCursor))

    async def discover(self, server: str, query: str, active: dict) -> list:
        await self._session(server)
        matches = []
        async for item in self._list(server):
            description = (item.description or item.name)[:800]
            if not all(w in normalized(item.name + " " + description) for w in normalized(query).split()):
                continue
            key = hashlib.sha256((server + "/" + item.name).encode()).hexdigest()[:12]
            alias = "mcp_" + key + "_" + re.sub(r"[^a-zA-Z0-9_-]", "_", item.name)[:40]
            if len(json.dumps(item.inputSchema)) > 24000:
                continue
            self.selected[alias] = (server, item.name, item.inputSchema)
            active[alias] = {"name": alias, "description": description, "input_schema": item.inputSchema}
            matches.append({"name": alias, "tool": item.name, "description": description})
            if len(matches) == 5:
                break
        return matches

    async def call(self, alias: str, arguments: dict) -> str:
        server, name, schema = self.selected[alias]
        async for current in self._list(server):
            if current.name == name and current.inputSchema == schema:
                result = await self.sessions[server].call_tool(name, arguments=arguments)
                parts = [b.text for b in result.content if b.type == "text"]
                if not parts and result.structuredContent is not None:
                    parts.append(json.dumps(result.structuredContent, ensure_ascii=False))
                text = "\n".join(parts) or "(无文本结果)"
                if result.isError:
                    raise ValueError(text[:500])
                return text[:16000]
        raise ValueError("MCP 工具已变更，请重新发现")
