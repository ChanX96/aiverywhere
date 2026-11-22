"""Discover bridge manifests without importing or executing bridge code."""

from __future__ import annotations

import http.client
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from ...core import channels


BRIDGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FIELDS = {"schema", "id", "name", "channel", "description", "command", "health_url",
          "enabled", "version", "homepage"}


def _roots(store) -> list[Path]:
    roots = [store.project / "bridges", store.home / "bridges"]
    result = []
    for root in roots:
        if root.is_dir() and root not in result:
            result.append(root)
    return result


def _health(url: str) -> dict:
    try:
        parts = urlsplit(url)
        if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"}:
            return {"ok": False, "detail": "health_url 只允许本机 HTTP"}
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=1)
        try:
            connection.request("GET", parts.path or "/")
            response = connection.getresponse()
            response.read(2048)
            return {"ok": 200 <= response.status < 300, "status": response.status}
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return {"ok": False, "detail": "unreachable"}


def discover(store, *, check_health: bool = False) -> list[dict]:
    found = {}
    configured = set()
    try:
        configured = set(channels.configs(store))
    except (OSError, ValueError):
        configured = set()
    for root in _roots(store):
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("_"):
                continue
            manifest_path = child / "bridge.json"
            try:
                raw = manifest_path.read_bytes()
                if len(raw) > 32768:
                    continue
                manifest = json.loads(raw)
            except (OSError, ValueError):
                continue
            if not isinstance(manifest, dict) or manifest.keys() - FIELDS:
                continue
            ident = manifest.get("id")
            channel = manifest.get("channel")
            if (manifest.get("schema") != 1 or not isinstance(ident, str)
                    or not BRIDGE_ID.fullmatch(ident) or ident in found
                    or not isinstance(channel, str) or not BRIDGE_ID.fullmatch(channel)
                    or not isinstance(manifest.get("name"), str)):
                continue
            command = manifest.get("command", [])
            if command and (not isinstance(command, list)
                            or not all(isinstance(item, str) and item for item in command)):
                continue
            entry = {
                "id": ident, "name": manifest["name"][:160], "channel": channel,
                "description": str(manifest.get("description", ""))[:1000],
                "enabled": bool(manifest.get("enabled", False)),
                "command": command, "path": str(child),
                "channel_configured": channel in configured,
                "manifest": {k: manifest.get(k) for k in
                             ("schema", "version", "homepage", "health_url", "enabled")},
            }
            if check_health and isinstance(manifest.get("health_url"), str):
                entry["health"] = _health(manifest["health_url"])
            found[ident] = entry
    return sorted(found.values(), key=lambda item: item["id"])
