"""Simple OpenAI-compatible and Ollama adapters.

The agent loop and tool protocol stay Anthropic-shaped internally.  This
module only translates requests and responses at the model boundary.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from .agent import Messages


DEFAULT_BASES = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


class ChatCompletions(Messages):
    """OpenAI Chat Completions protocol, used by OpenAI, Ollama and custom gateways."""

    def __init__(self, client, model: str | None, *, settings=None):
        self.client = client
        settings = settings or {}
        self.protocol = settings.get("protocol", "openai")
        self.model = model or settings.get("model")
        self.max_tokens = settings.get("max_tokens", 4096)
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ValueError("max_tokens 需要正整数")
        self.base = (settings.get("base_url") or DEFAULT_BASES.get(self.protocol) or "").rstrip("/")
        if not self.base:
            raise ValueError("OpenAI/Ollama/custom 协议需要 base_url")
        url = urlsplit(self.base)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.query or url.fragment:
            raise ValueError("模型服务地址应为 HTTP(S) 地址")
        path = settings.get("chat_path")
        if path:
            if not isinstance(path, str) or not path.startswith("/"):
                raise ValueError("model.chat_path 需要以 / 开头")
            if self.base.endswith("/v1") and path.startswith("/v1/"):
                path = path[3:]
            self.endpoint = self.base + path
        elif self.base.endswith("/chat/completions"):
            self.endpoint = self.base
        elif self.base.endswith("/v1"):
            self.endpoint = self.base + "/chat/completions"
        else:
            self.endpoint = self.base + "/v1/chat/completions"
        self.headers = {"content-type": "application/json"}
        token = settings.get("auth_token") or self._env(settings.get("auth_token_env"))
        key = settings.get("api_key") or self._env(settings.get("api_key_env"))
        if token or key:
            self.headers["Authorization"] = f"Bearer {token or key}"
        extra = settings.get("headers") or {}
        if not isinstance(extra, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in extra.items()):
            raise ValueError("model.headers 需要字符串键值对象")
        self.headers.update(extra)

    @staticmethod
    def _openai_content(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(ChatCompletions._openai_content(item) for item in value)
        if isinstance(value, dict):
            return ChatCompletions._openai_content(value.get("text", value.get("content", "")))
        return json.dumps(value, ensure_ascii=False)

    def _messages(self, system: str, messages: list) -> list[dict]:
        result = [{"role": "system", "content": system}]
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "assistant" and isinstance(content, list):
                text = []
                calls = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text.append(self._openai_content(block.get("text", "")))
                    elif block.get("type") == "tool_use":
                        calls.append({"id": block.get("id", ""), "type": "function",
                                      "function": {"name": block.get("name", ""),
                                                   "arguments": json.dumps(block.get("input", {}),
                                                                           ensure_ascii=False)}})
                item = {"role": "assistant", "content": "\n".join(text) if text else None}
                if calls:
                    item["tool_calls"] = calls
                result.append(item)
            elif role == "user" and isinstance(content, list):
                tool_results = []
                ordinary = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_results.append({"role": "tool", "tool_call_id": block.get("tool_use_id", ""),
                                             "content": self._openai_content(block.get("content", ""))})
                    elif block.get("type") == "text":
                        ordinary.append(self._openai_content(block.get("text", "")))
                result.extend(tool_results)
                if ordinary:
                    result.append({"role": "user", "content": "\n".join(ordinary)})
            else:
                result.append({"role": role, "content": self._openai_content(content)})
        return result

    @staticmethod
    def _tools(tools: list) -> list[dict]:
        return [{"type": "function", "function": {
            "name": item.get("name", ""), "description": item.get("description", ""),
            "parameters": item.get("input_schema", {"type": "object", "properties": {}}),
        }} for item in tools]

    @staticmethod
    def _stop(reason) -> str:
        if reason in {"tool_calls", "function_call"}:
            return "tool_use"
        if reason == "length":
            return "max_tokens"
        return "end_turn" if reason in {None, "stop", "end_turn"} else str(reason)

    @staticmethod
    def _arguments(value) -> dict:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI 工具参数不是 JSON 对象")
        return parsed

    def _response(self, data: dict) -> dict:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI 兼容端点没有返回 choices")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        blocks = []
        content = message.get("content")
        if content:
            blocks.append({"type": "text", "text": self._openai_content(content)})
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            blocks.append({"type": "tool_use", "id": call.get("id", ""),
                           "name": function.get("name", ""),
                           "input": self._arguments(function.get("arguments", ""))})
        if not blocks:
            raise ValueError("OpenAI 兼容端点返回空内容")
        return {"content": blocks, "stop_reason": self._stop(choice.get("finish_reason"))}

    async def send(self, system: str, messages: list, tools: list, on_thinking=None) -> dict:
        import httpx

        if not self.model:
            raise ValueError("请用 --model 或 AIVERYWHERE_MODEL 指定模型")
        payload = {"model": self.model, "messages": self._messages(system, messages),
                   "max_tokens": self.max_tokens}
        if tools:
            payload["tools"] = self._tools(tools)
        try:
            response = await self.client.post(self.endpoint, headers=self.headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(self._http_error(exc)) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"模型请求未完成（{type(exc).__name__}）") from exc
        data = response.json()
        choice = (data.get("choices") or [{}])[0] if isinstance(data, dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
        if reasoning and on_thinking:
            on_thinking(str(reasoning))
        return self._response(data)

    async def stream_send(self, system: str, messages: list, tools: list, on_text=None,
                          on_thinking=None) -> dict:
        import httpx

        if not self.model:
            raise ValueError("请用 --model 或 AIVERYWHERE_MODEL 指定模型")
        payload = {"model": self.model, "messages": self._messages(system, messages),
                   "max_tokens": self.max_tokens, "stream": True}
        if tools:
            payload["tools"] = self._tools(tools)
        text = []
        calls: dict[int, dict] = {}
        finish = None
        try:
            async with self.client.stream("POST", self.endpoint, headers=self.headers, json=payload) as response:
                response.raise_for_status()
                async for raw in response.aiter_lines():
                    if not raw.startswith("data:"):
                        continue
                    payload_text = raw[5:].strip()
                    if payload_text in {"", "[DONE]"}:
                        continue
                    event = json.loads(payload_text)
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content") and on_thinking:
                            on_thinking(str(delta["reasoning_content"]))
                        if delta.get("content"):
                            piece = self._openai_content(delta["content"])
                            text.append(piece)
                            if on_text:
                                on_text(piece)
                        for call in delta.get("tool_calls") or []:
                            index = int(call.get("index", 0))
                            target = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if call.get("id"):
                                target["id"] = call["id"]
                            function = call.get("function") or {}
                            if function.get("name"):
                                target["name"] = function["name"]
                            if function.get("arguments"):
                                target["arguments"] += function["arguments"]
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
        except httpx.HTTPStatusError as exc:
            raise ValueError(self._http_error(exc)) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"模型请求未完成（{type(exc).__name__}）") from exc
        blocks = []
        answer = "".join(text)
        if answer:
            blocks.append({"type": "text", "text": answer})
        for index in sorted(calls):
            target = calls[index]
            blocks.append({"type": "tool_use", "id": target["id"],
                           "name": target["name"], "input": self._arguments(target["arguments"])})
        if not blocks:
            raise ValueError("OpenAI 兼容端点返回空流")
        return {"content": blocks, "stop_reason": self._stop(finish)}
