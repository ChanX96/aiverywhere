# Bridge plugins

A bridge is a separate long-running process that owns one native platform
(WeChat, Feishu, iMessage, Slack, …). It converts native events into the generic
channel envelope and sends replies back to the platform.

This directory is discovered by the CLI and Web console. The core only reads
`bridge.json` and an optional loopback health URL; it never imports or executes
bridge code.

## Layout

```text
bridges/<bridge-id>/
├── bridge.json
├── bridge.py          # or any language/service
└── README.md
```

`bridge.json`:

```json
{
  "schema": 1,
  "id": "wechat",
  "name": "WeChat bridge",
  "channel": "wechat",
  "description": "Local WeChat gateway",
  "enabled": false,
  "command": ["python3", "bridge.py"],
  "health_url": "http://127.0.0.1:8787/health",
  "version": "0.1.0",
  "homepage": ""
}
```

- `id` and `channel`: 1–64 letters, digits, `_` or `-`.
- `enabled` is informational; the supervisor does not execute arbitrary commands.
- `health_url`, when present, must be loopback HTTP.
- `command` is displayed to operators; bridge lifecycle is owned by the user's
  process manager or terminal.

Copy `_template/` to a new directory and implement the bridge.

## Contract

Use the public base class from the installed package:

```python
from aiverywhere.integrations.bridges.base import Bridge
```

Implement:

- `verify(native_event) -> bool`
- `normalize(native_event) -> {account, conversation, message_id, text}`
- `send(route, text) -> {"state": "accepted"|"delivered", "receipt": "..."}`

Submit inbound messages to the local supervisor:

```python
await bridge.submit(message, base_url=..., token=...)
```

or HTTP:

```http
POST /api/channels/<channel>/messages
X-Aiverywhere-Token: <token from data/daemon.json>
```

The bridge must echo the original `channel`, `account`, `conversation`, and
`reply_to` in its send acknowledgement.

## Discover

```sh
aiverywhere bridges
```

The Web overview lists discovered bridges, their channel configuration, and
health. `channel_configured` is true when `channels.<channel>` exists in the
instance config.
