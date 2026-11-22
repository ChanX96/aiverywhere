"""First-run configuration for the installed command line.

Prompts use defaults for everything except the model name and its credential.
Configuration is written atomically with mode 0600 and never echoed back.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .store import Store, atomic_write, checked_defaults

OFFICIAL = "https://api.anthropic.com"
OPENAI = "https://api.openai.com/v1"
OLLAMA = "http://127.0.0.1:11434/v1"
MAX_TOKENS = 4096
PROTOCOLS = {"anthropic", "openai", "ollama", "custom"}
CREDENTIAL_FIELDS = ("api_key", "auth_token", "api_key_env", "auth_token_env")


class Prompter:
    def __init__(self, input_fn=None, secret_fn=None, output_fn=None):
        self.input_fn = input_fn or input
        self.secret_fn = secret_fn or getpass.getpass
        self.output_fn = output_fn or print

    def text(self, label: str, default: str = "", *, secret: bool = False, required: bool = False) -> str:
        prompt = f"{label} [{default}]: " if default else f"{label}: "
        while True:
            value = self.secret_fn(prompt) if secret else self.input_fn(prompt)
            value = (value or "").strip()
            if value:
                return value
            if default:
                return default
            if not required:
                return ""
            self.output_fn("不能为空。")

    def integer(self, label: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
        while True:
            raw = self.input_fn(f"{label} [{default}]: ").strip()
            if not raw:
                return default
            try:
                value = int(raw)
            except ValueError:
                self.output_fn("请输入整数。")
                continue
            if value < minimum or (maximum is not None and value > maximum):
                bound = f"{minimum}–{maximum}" if maximum is not None else f"不小于 {minimum}"
                self.output_fn(f"请输入 {bound} 的整数。")
                continue
            return value

    def confirm(self, label: str, default: bool) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            raw = self.input_fn(f"{label} [{suffix}]: ").strip().lower()
            if not raw:
                return default
            if raw in {"y", "yes", "是"}:
                return True
            if raw in {"n", "no", "否"}:
                return False
            self.output_fn("请输入 y 或 n。")

    def choice(self, label: str, options: list[tuple[str, str]], default: str) -> str:
        keys = [key for key, _ in options]
        default = default if default in keys else keys[0]
        self.output_fn(label + "：")
        for index, (_, description) in enumerate(options, 1):
            self.output_fn(f"  {index}) {description}")
        while True:
            raw = self.input_fn(f"选择 [{keys.index(default) + 1}]: ").strip()
            if not raw:
                return default
            if raw in keys:
                return raw
            if raw.isdigit() and 1 <= int(raw) <= len(keys):
                return keys[int(raw) - 1]
            self.output_fn("请输入序号。")


def environment_model() -> str:
    return os.getenv("AIVERYWHERE_MODEL") or os.getenv("ANTHROPIC_MODEL") or ""


def environment_base() -> str:
    return os.getenv("ANTHROPIC_BASE_URL") or ""


def environment_credential() -> dict:
    if os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return {"auth_token_env": "ANTHROPIC_AUTH_TOKEN"}
    if os.getenv("ANTHROPIC_API_KEY"):
        return {"api_key_env": "ANTHROPIC_API_KEY"}
    return {}


def check_url(value: str) -> str:
    value = value.strip().rstrip("/")
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.query or url.fragment:
        raise ValueError("模型服务地址应为 HTTP(S) 地址，且不能包含账号、查询参数或片段")
    return value


def is_official(base: str) -> bool:
    return base.rstrip("/") in {OFFICIAL, OFFICIAL + "/v1"}


def _flags(*values) -> bool:
    return any(value is not None for value in values)


def _credential_flag(api_key, auth_token, api_key_env, auth_token_env) -> dict:
    selected = [name for name, value in (
        ("api_key", api_key), ("auth_token", auth_token),
        ("api_key_env", api_key_env), ("auth_token_env", auth_token_env)) if value is not None]
    if len(selected) > 1:
        raise ValueError("一次只能提供一种凭据方式")
    if not selected:
        return {}
    name = selected[0]
    value = {"api_key": api_key, "auth_token": auth_token,
             "api_key_env": api_key_env, "auth_token_env": auth_token_env}[name]
    if not value:
        raise ValueError(f"{name} 不能为空")
    if name.endswith("_env") and not value.isidentifier():
        raise ValueError(f"{name} 需要合法的环境变量名")
    return {name: value}


def _ask_credential(prompt: Prompter, existing: dict, official: bool, *, keep_existing: bool) -> dict:
    current = {key: existing[key] for key in CREDENTIAL_FIELDS if existing.get(key)} if keep_existing else {}
    if current.get("auth_token") or current.get("auth_token_env"):
        default = "2" if current.get("auth_token") else "3"
    elif current.get("api_key") or current.get("api_key_env"):
        default = "1" if current.get("api_key") else "3"
    elif os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY"):
        default = "3"
    else:
        default = "1"
    kind = prompt.choice("凭据方式", [
        ("1", "x-api-key（Anthropic 官方及多数兼容服务）"),
        ("2", "Authorization: Bearer（部分网关）"),
        ("3", "环境变量（不把密钥写入 config.json）"),
    ], default)
    if kind == "1":
        previous = current.get("api_key", "")
        value = prompt.text("API Key（回车保留已配置值）" if previous else "API Key", secret=True,
                            required=official and not previous)
        value = value or previous
        if not value and official:
            raise ValueError("Anthropic 官方端点需要 API Key")
        return {"api_key": value} if value else {}
    if kind == "2":
        previous = current.get("auth_token", "")
        value = prompt.text("Bearer Token（回车保留已配置值）" if previous else "Bearer Token", secret=True,
                            required=official and not previous)
        value = value or previous
        if not value and official:
            raise ValueError("Anthropic 官方端点需要凭据")
        return {"auth_token": value} if value else {}
    previous = current.get("api_key_env") or current.get("auth_token_env") or ""
    suggested = previous or ("ANTHROPIC_AUTH_TOKEN" if os.getenv("ANTHROPIC_AUTH_TOKEN") else "ANTHROPIC_API_KEY")
    name = prompt.text("环境变量名", default=suggested, required=True)
    if not name.isidentifier():
        raise ValueError("环境变量名需要是合法的标识符")
    if not os.getenv(name):
        prompt.output_fn(f"注意：当前环境没有 ${name}，运行 CLI 前需要设置它。")
    field = "auth_token_env" if re.search(r"AUTH|TOKEN|BEARER", name, re.IGNORECASE) else "api_key_env"
    return {field: name}


def _ask_model(prompt: Prompter, existing: dict, *, model, base_url, max_tokens,
               api_key, auth_token, api_key_env, auth_token_env, protocol=None,
               chat_path=None) -> dict:
    current_protocol = existing.get("protocol", "anthropic")
    default_protocol = protocol or current_protocol
    choice = prompt.choice("模型协议", [
        ("1", "Anthropic Messages"),
        ("2", "OpenAI Chat Completions"),
        ("3", "Ollama"),
        ("4", "Custom OpenAI-compatible"),
    ], str({"anthropic": 1, "openai": 2, "ollama": 3, "custom": 4}.get(default_protocol, 1)))
    selected_protocol = {"1": "anthropic", "2": "openai", "3": "ollama", "4": "custom"}[choice]
    default_base = {"anthropic": OFFICIAL, "openai": OPENAI, "ollama": OLLAMA,
                    "custom": "http://127.0.0.1:8000/v1"}[selected_protocol]
    existing_base = existing.get("base_url") if current_protocol == selected_protocol else default_base
    proposed_base = check_url(base_url or existing_base or environment_base() or default_base)
    if selected_protocol == "anthropic":
        default_service = "1" if is_official(proposed_base) else "2"
        service = prompt.choice("模型服务", [
            ("1", f"Anthropic 官方（{OFFICIAL}）"),
            ("2", "自定义 Messages 兼容端点"),
        ], default_service)
        if service == "1":
            base = OFFICIAL
        else:
            base = check_url(prompt.text("模型服务地址",
                                         default=proposed_base if not is_official(proposed_base) else "http://127.0.0.1:8000",
                                         required=True))
    else:
        base = check_url(prompt.text("模型服务地址", default=proposed_base,
                                     required=True))
    name = prompt.text("模型名称", default=model or existing.get("model") or environment_model(), required=True)
    changed_endpoint = base.rstrip("/") != (existing.get("base_url") or OFFICIAL).rstrip("/")
    credential = _credential_flag(api_key, auth_token, api_key_env, auth_token_env)
    if not credential:
        credential = _ask_credential(prompt, existing, is_official(base),
                                     keep_existing=not changed_endpoint)
    section = {"model": name}
    if selected_protocol != "anthropic":
        section["protocol"] = selected_protocol
    if not is_official(base) or selected_protocol != "anthropic":
        section["base_url"] = base
    if chat_path:
        if not chat_path.startswith("/"):
            raise ValueError("chat_path 需要以 / 开头")
        section["chat_path"] = chat_path
    section.update(credential)
    suggested_tokens = max_tokens or existing.get("max_tokens") or MAX_TOKENS
    if type(suggested_tokens) is not int or suggested_tokens <= 0:
        suggested_tokens = MAX_TOKENS
    tokens = prompt.integer("单次模型请求的最大输出 token", suggested_tokens)
    if tokens != MAX_TOKENS:
        section["max_tokens"] = tokens
    return section


def _noninteractive_model(existing: dict, *, model, base_url, max_tokens,
                          api_key, auth_token, api_key_env, auth_token_env, protocol=None,
                          chat_path=None) -> dict:
    if "command" in existing and not _flags(model, base_url, api_key, auth_token, api_key_env, auth_token_env,
                                            max_tokens, protocol, chat_path):
        return dict(existing)
    name = model or existing.get("model") or environment_model()
    if not name:
        raise ValueError("请用 --model 或 AIVERYWHERE_MODEL 指定模型；也可交互运行 aiverywhere setup")
    selected_protocol = protocol or existing.get("protocol", "anthropic")
    if selected_protocol not in PROTOCOLS:
        raise ValueError("protocol 支持 anthropic、openai、ollama 或 custom")
    default_base = {"anthropic": OFFICIAL, "openai": OPENAI, "ollama": OLLAMA,
                    "custom": "http://127.0.0.1:8000/v1"}[selected_protocol]
    base = check_url(base_url or existing.get("base_url") or environment_base() or default_base)
    credential = _credential_flag(api_key, auth_token, api_key_env, auth_token_env)
    changed_endpoint = base.rstrip("/") != (existing.get("base_url") or OFFICIAL).rstrip("/")
    if not credential:
        if not changed_endpoint:
            credential = {key: existing[key] for key in CREDENTIAL_FIELDS if existing.get(key)}
        if not credential:
            credential = environment_credential()
    if not credential and is_official(base):
        raise ValueError("Anthropic 官方端点需要 --api-key、--auth-token 或 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN")
    tokens = max_tokens if max_tokens is not None else existing.get("max_tokens", MAX_TOKENS)
    if type(tokens) is not int or tokens <= 0:
        raise ValueError("max_tokens 需要正整数")
    section = {"model": name}
    if selected_protocol != "anthropic":
        section["protocol"] = selected_protocol
    if not is_official(base) or selected_protocol != "anthropic":
        section["base_url"] = base
    if chat_path:
        if not chat_path.startswith("/"):
            raise ValueError("chat_path 需要以 / 开头")
        section["chat_path"] = chat_path
    section.update(credential)
    if tokens != MAX_TOKENS:
        section["max_tokens"] = tokens
    return section


def _runtime_defaults(base: dict, *, max_turns, timeout, port) -> dict:
    raw = dict(base)
    for key, value in (("max_turns", max_turns), ("timeout", timeout), ("port", port)):
        if value is not None:
            raw[key] = value
    return checked_defaults(raw)


def _write_config(store: Store, model: dict, defaults: dict) -> Path:
    path = store.config_path
    with store.locked():
        latest = store.configuration()
        complete = {"model": model, "defaults": defaults,
                    "mcpServers": latest.get("mcpServers", {}), "wechat": latest.get("wechat", {}),
                    "session": latest.get("session", {}),
                    "channels": latest.get("channels", {})}
        atomic_write(path, (json.dumps(complete, ensure_ascii=False, indent=2) + "\n").encode(), mode=0o600)
    return path


def _summary(path: Path, model: dict, defaults: dict) -> dict:
    if "command" in model:
        description = {"executor": "native", "command": model["command"]}
    else:
        protocol = model.get("protocol", "anthropic")
        default_base = {"anthropic": OFFICIAL, "openai": OPENAI, "ollama": OLLAMA,
                        "custom": "http://127.0.0.1:8000/v1"}[protocol]
        description = {"executor": "messages", "protocol": protocol,
                       "name": model.get("model"),
                       "base_url": model.get("base_url", default_base),
                       "credential": next((key for key in CREDENTIAL_FIELDS if model.get(key)), None),
                       "max_tokens": model.get("max_tokens", MAX_TOKENS)}
    return {"config": str(path), "model": description, "defaults": defaults}


def configure(store: Store, *, interactive: bool | None = None, no_input: bool = False,
              model=None, base_url=None, api_key=None, auth_token=None,
              api_key_env=None, auth_token_env=None, max_tokens=None,
              max_turns=None, timeout=None, port=None, protocol=None, chat_path=None) -> dict:
    """Collect configuration and publish it atomically. Secrets are never returned."""
    if no_input:
        interactive = False
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    _credential_flag(api_key, auth_token, api_key_env, auth_token_env)
    if max_tokens is not None and max_tokens <= 0:
        raise ValueError("max_tokens 需要正整数")
    store.initialize()
    current = store.configuration()
    existing = current.get("model", {})
    base_defaults = store.defaults()
    model_flags = _flags(model, base_url, api_key, auth_token, api_key_env, auth_token_env,
                         max_tokens, protocol, chat_path)
    runtime_flags = _flags(max_turns, timeout, port)

    if not interactive:
        selected = _noninteractive_model(
            existing, model=model, base_url=base_url, max_tokens=max_tokens,
            api_key=api_key, auth_token=auth_token, api_key_env=api_key_env, auth_token_env=auth_token_env,
            protocol=protocol, chat_path=chat_path)
        defaults = _runtime_defaults(base_defaults, max_turns=max_turns, timeout=timeout, port=port)
        path = _write_config(store, selected, defaults)
        return _summary(path, selected, defaults)

    prompt = Prompter()
    prompt.output_fn("aiverywhere 配置向导：直接回车使用方括号中的默认值。")
    if "command" in existing and not model_flags:
        keep_native = prompt.confirm("当前使用原生执行器，保留它并只调整运行参数？", True)
        selected = dict(existing) if keep_native else _ask_model(
            prompt, {}, model=model, base_url=base_url, max_tokens=max_tokens,
            api_key=api_key, auth_token=auth_token, api_key_env=api_key_env, auth_token_env=auth_token_env,
            protocol=protocol, chat_path=chat_path)
    else:
        reconfigure = model_flags or not existing.get("model")
        if not reconfigure:
            reconfigure = prompt.confirm(f"已配置模型 {existing.get('model')}，重新配置连接？", False)
        selected = _ask_model(
            prompt, existing, model=model, base_url=base_url, max_tokens=max_tokens,
            api_key=api_key, auth_token=auth_token, api_key_env=api_key_env, auth_token_env=auth_token_env,
            protocol=protocol, chat_path=chat_path
        ) if reconfigure else dict(existing)

    defaults = dict(base_defaults)
    adjust = prompt.confirm("调整运行参数（回合、超时、并发、端口）？", runtime_flags)
    if adjust:
        defaults["max_turns"] = prompt.integer("工具回合上限", max_turns if max_turns is not None else defaults["max_turns"])
        defaults["timeout"] = prompt.integer("单任务超时秒数", timeout if timeout is not None else defaults["timeout"])
        defaults["port"] = prompt.integer("本地工作台端口", port if port is not None else defaults["port"],
                                          minimum=0, maximum=65535)
    defaults = _runtime_defaults(defaults, max_turns=max_turns, timeout=timeout, port=port)
    path = _write_config(store, selected, defaults)
    return _summary(path, selected, defaults)
