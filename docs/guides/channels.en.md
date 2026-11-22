# Generic message channels

[简体中文](channels.md) | **English**

aiverywhere never logs in to an IM platform itself. WeChat, Feishu, iMessage, and custom bridges use one small **webhook channel envelope**. The bridge owns platform login, signature verification, and delivery; aiverywhere owns the task, model execution, persistence, and reply routing.

## Configuration

In the instance `config.json`:

```json
{
  "channels": {
    "wechat": {
      "url": "http://127.0.0.1:8787",
      "auth_token_env": "AIVERYWHERE_WECHAT_TOKEN"
    },
    "feishu": {
      "url": "http://127.0.0.1:8788",
      "auth_token_env": "AIVERYWHERE_FEISHU_TOKEN",
      "idempotent_send": true,
      "receipt_lookup": true
    },
    "imessage": {
      "url": "http://127.0.0.1:8789"
    }
  }
}
```

| Field | Meaning |
| --- | --- |
| `url` | Required bridge URL; aiverywhere POSTs to `url + send_path`. |
| `send_path` | Default `/messages`. |
| `auth_token` / `auth_token_env` | Optional Bearer token; environment references are preferred. |
| `account` / `conversation` | Optional filters; normally supplied by inbound messages. |
| `idempotent_send` | Whether the bridge deduplicates the same Idempotency-Key. |
| `receipt_lookup` | Whether the bridge can look up a delivery receipt by ID. |
| `timeout` / `max_turns` | Override instance defaults. |

`type` currently supports `webhook`. This is not a platform limit: the bridge translates the native platform protocol. New native adapters can be added without changing the agent core.

The legacy `wechat` section is mapped to a `wechat` webhook channel when `channels` is absent.

## Inbound

The resident supervisor exposes the loopback Web API. A bridge submits verified messages to:

```http
POST /api/channels/<channel>/messages
X-Aiverywhere-Token: <daemon token>
Content-Type: application/json

{
  "account": "account-id",
  "conversation": "conversation-id",
  "message_id": "stable-inbound-id",
  "text": "user message"
}
```

`message_id` must be stable. Repeating the same channel/account/conversation/message_id returns the original task. The channel is selected by the path.

The task persists the complete route:

```text
channel + account + conversation + message_id
```

The answer is sent only to that originating channel; it never guesses or switches channels.

Query:

```http
GET /api/channels/<channel>/status?task_id=<task_id>
```

Legacy `POST /api/wechat` remains a compatibility entry for the `wechat` channel.

## Outbound

aiverywhere calls:

```http
POST <url><send_path>
Authorization: Bearer <token>
Idempotency-Key: <task_id>

{
  "id": "<task_id>",
  "channel": "feishu",
  "account": "account-id",
  "conversation": "conversation-id",
  "reply_to": "stable-inbound-id",
  "text": "answer"
}
```

The bridge must echo `channel`, `account`, `conversation`, and `reply_to`, then return:

```json
{"state": "accepted", "receipt": "receipt-id"}
```

`accepted` means the gateway received the message; `delivered` means confirmed delivery. Missing receipts remain `unknown` or `verify`; aiverywhere never claims success.

## Resident supervisor

```sh
aiverywhere start
aiverywhere status
aiverywhere stop
aiverywhere             # ensure supervisor and enter CLI
aiverywhere web         # ensure supervisor, print/open Web, and return
```

The supervisor is single-instance and uses:

```text
data/daemon.json
data/daemon.lock
data/daemon.startup
data/logs/daemon.log
```

No system service is registered; start it again after a reboot.

## Platform bridges

| Platform | Bridge responsibility |
| --- | --- |
| WeChat | login/pairing, inbound verification, account/conversation mapping, send and receipt |
| Feishu | app/event subscription, signature verification, chat_id mapping, send |
| iMessage | local Messages database or AppleScript bridge, send receipt |

Native platform login, QR pairing, rate limits, and delivery confirmation stay outside the core skill. aiverywhere owns task execution and reply routing.
