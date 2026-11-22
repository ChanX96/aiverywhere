# WeChat integration for aiverywhere

[简体中文](wechat.md) | **English**

aiverywhere **does not log in to personal WeChat directly**. The commands below assume `aiverywhere` is on `PATH`; add `--home` or set `AIVERYWHERE_HOME` for a custom install root. A trusted gateway owns WeChat login, account pairing, inbound verification, and sending. aiverywhere turns verified inbound messages into durable tasks, generates answers with the instance model, and writes answers and delivery receipts back to the gateway. The WeChat channel is an optional adapter; it does not change the core agent loop used by hosts or the CLI.

## 1. Prerequisites

- macOS or Linux with the CLI installed, and a working model or native executor configured for the instance. `wechat` only queues an inbound message; the externally scheduled `wake` generates the answer and needs model access.
- A gateway that receives WeChat messages, performs account pairing and inbound verification, and implements the outbound HTTP contract below.
- One instance currently binds **one account + one conversation**. Use separate instances (different `--home`) or extend the adapter for multiple contacts or groups.
- Run the gateway on loopback or behind TLS. Do not expose `aiverywhere wechat` or the gateway management API to the public internet.

## 2. Configuration

Fill in the `wechat` section of the instance's `config.json`:

```json
{
  "project": "/absolute/path/to/task-project",
  "account": "demo",
  "conversation": "chat-1",
  "url": "http://127.0.0.1:8787",
  "auth_token": "gateway-access-token",
  "idempotent_send": true,
  "receipt_lookup": true,
  "timeout": 600,
  "max_turns": 12,
  "progress_after": 120
}
```

| Field | Contract |
| --- | --- |
| `project` | Required. Absolute path; must equal `--project` used by `wake` and `wechat`. |
| `account` | Required. Gateway's WeChat account identifier. |
| `conversation` | Required. Gateway's conversation identifier. |
| `url` | Required. Gateway HTTP(S) base URL without userinfo, query, or fragment. |
| `auth_token` | Optional. aiverywhere sends `Authorization: Bearer <token>` outbound; inbound authentication belongs to the gateway. |
| `idempotent_send` | Whether the gateway guarantees one delivery per `Idempotency-Key`. |
| `receipt_lookup` | Whether the gateway supports `GET /messages/<id>`. |
| `timeout` | Seconds for one WeChat task; defaults to the instance `defaults.timeout`. |
| `max_turns` | Tool-turn limit for the task; defaults to the instance `defaults.max_turns`. |
| `progress_after` | Seconds without progress before one reminder, default 120; `0` only reports an evidence-based concern. |

`config.json` may contain model keys and gateway tokens. Keep it at `0600` and never commit or share it. New tasks read the latest config; an in-flight send verifies the original binding.

## 3. Inbound: gateway to aiverywhere

After verifying that an inbound message belongs to the paired account and conversation, the gateway normalizes it to one JSON object and passes it on standard input:

```json
{
  "account": "demo",
  "conversation": "chat-1",
  "message_id": "wx-msg-001",
  "text": "Summarize this week's progress."
}
```

```sh
printf '%s\n' "$MESSAGE_JSON" |
  aiverywhere --project /absolute/path/to/task-project wechat
```

Prefer serializing from Python or the gateway's own HTTP client instead of interpolating user text into a shell string:

```python
import json
import subprocess

envelope = {
    "account": "demo",
    "conversation": "chat-1",
    "message_id": inbound.id,
    "text": inbound.text,
}
result = subprocess.run(
    ["aiverywhere", "--project", "/absolute/path/to/task-project", "wechat"],
    input=json.dumps(envelope, ensure_ascii=False),
    text=True,
    capture_output=True,
    check=True,
)
task = json.loads(result.stdout)
```

A successful call prints a receipt like:

```json
{
  "task_id": "wechat:2f0c...",
  "status": "queued",
  "delivery": "queued",
  "receipt": null,
  "detail": null
}
```

`queued` only means the message is persisted; **no model has been called yet**. The gateway should store `message_id → task_id` for later status queries.

Fields and deduplication:

- `account` and `conversation` must match the configuration exactly.
- `message_id` is limited to 256 characters; `text` to 65,536; the envelope is limited to 1 MiB.
- The same project, account, conversation, and `message_id` with the same text returns the original task. Reusing a `message_id` with different text is rejected. The gateway must assign stable, unique IDs.
- The gateway verifies that the message really came from the bound WeChat account. The CLI has no inbound signature verification.

## 4. Start the external scheduler

After messages are queued, they must be generated and delivered. aiverywhere does not run a daemon or register a system service; an external cron, launchd, systemd timer, or process manager calls the one-shot `wake` periodically:

```cron
* * * * * cd /absolute/path/to/task-project && aiverywhere --project /absolute/path/to/task-project wake --dream
```

Each call processes due plans in order, one WeChat job, and one ordinary Dream when `--dream` is set and idle clues exist. More frequent calls reduce WeChat latency; the external scheduler owns process liveness, retries, and logs. Without a scheduler, WeChat tasks remain `queued`.

Cron's PATH is usually narrow; use the absolute command path from the install-root virtual environment, or set PATH explicitly in the crontab.

`wake` must be able to read the same instance's `data/` and use a configured model or native executor. A host model alone is not enough for the CLI; integrate the channel into the host instead.

## 5. Outbound: aiverywhere to the gateway

When generation completes or fails, aiverywhere sends:

```http
POST /messages HTTP/1.1
Content-Type: application/json
Authorization: Bearer <auth_token>
Idempotency-Key: wechat:2f0c...

{
  "id": "wechat:2f0c...",
  "account": "demo",
  "conversation": "chat-1",
  "reply_to": "wx-msg-001",
  "text": "This is the final answer."
}
```

The gateway must echo the same address fields and return a `state` and non-empty `receipt`:

```json
{
  "id": "wechat:2f0c...",
  "account": "demo",
  "conversation": "chat-1",
  "reply_to": "wx-msg-001",
  "state": "accepted",
  "receipt": "gateway-receipt-..."
}
```

- `state` must be `accepted` or `delivered`. The former means the gateway accepted it; the latter means the gateway confirms delivery to WeChat.
- `id`, `account`, `conversation`, and `reply_to` must be echoed exactly; missing or different fields leave the delivery unverifiable.
- With `idempotent_send: true`, the gateway should persist the first result under `Idempotency-Key` and return the same receipt on retry without sending twice.
- On `5xx`, `408`, or `429`, aiverywhere retries within a bounded window; other non-2xx responses become rejected or unknown.
- When delivery is uncertain and `receipt_lookup: true`, aiverywhere first queries `GET {url}/messages/{id}`; `404` means the gateway has not received it. It resends only when `idempotent_send` is also true; otherwise the delivery stays pending verification.
- Without idempotency or lookup, the delivery remains "pending verification"; do not claim it was delivered.

A progress reminder uses an independent ID: `<task-id>.progress`. It is also sent to `/messages`, with `reply_to` set to the original inbound message ID. The gateway should treat it as a normal delivery; each task sends at most one progress reminder.

## 6. Query status

```sh
aiverywhere --project /absolute/path/to/task-project wechat --status wechat:2f0c...
```

The result includes task status, answer or error, `delivery`, gateway receipt, the latest progress, and checkpoint. `status` is whether the task completed; `delivery` is whether the message was delivered. They are different events.

## 7. Minimal gateway checklist

1. **Verify inbound**: confirm the WeChat account, conversation, and message source; assign a stable `message_id`; never forward unverified messages.
2. **Enqueue**: call `aiverywhere wechat` as above and store `task_id`.
3. **Implement POST**: deduplicate by `Idempotency-Key`, send to WeChat, echo the full address, and return `accepted` or `delivered` with a `receipt`.
4. **Implement GET**: return the same receipt shape by `id`; return 404 for unknown IDs. Support IDs containing `.progress`.
5. **Run the scheduler**: have cron, launchd, a systemd timer, or a process manager call `wake --dream` periodically.
6. **Keep logs**: record `message_id → task_id`, delivery keys, receipts, and errors; never log tokens or full private messages.
7. **Apply limits**: rate-limit, cap message size and concurrency at the gateway. The CLI already limits envelopes to 1 MiB and text to 65,536 characters.

## 8. Acceptance

With a temporary instance and a local fake gateway, verify at least:

1. A valid inbound message returns `queued` with a stable `task_id`.
2. Calling `wake` produces one POST with the correct `id`, `account`, `conversation`, `reply_to`, and `text`.
3. After the gateway returns `accepted` or `delivered`, `wechat --status` shows the same receipt.
4. Repeating the same `message_id` creates no second task and no second delivery.
5. Simulate a POST whose receipt is lost: with idempotency/lookup, it does not send twice and the state becomes verifiable; without them, it stays pending verification.
6. Restart the process or call `wake` again: unfinished tasks resume or are explicitly interrupted without losing the original conversation address.
7. Submit a mismatched `account` or `conversation` and confirm it is rejected.

Real personal WeChat accounts, QR login, platform restrictions, and actual delivery still require integration testing on the gateway side. This project currently verifies fake-gateway receipts, process restarts, and context compaction paths only.

## 9. Troubleshooting

| Symptom | Check |
| --- | --- |
| 403 on inbound | `account`/`conversation` differ from the config, or `project` is not the instance's absolute project path. |
| 400 on inbound | Missing fields, text over 65,536 characters, envelope over 1 MiB, or the same `message_id` with different text. |
| Stuck at `queued` | No scheduler calls `wake`, or no model/native executor is configured. Run `wake` and inspect its output. |
| `delivery` stays `unknown`/`verify` | The gateway does not echo the address and `receipt`, or lacks GET support; check `idempotent_send`/`receipt_lookup`. |
| Duplicate replies | The gateway does not deduplicate by `Idempotency-Key`, or reuses different task IDs. |
| Progress shown as a duplicate reply | Treat `<task-id>.progress` as a separate delivery and decide whether to display it. |
| WeChat login or disconnect | The gateway owns account connectivity; aiverywhere does not handle QR login. |

Security boundary: the gateway is the only trusted WeChat entry point; `auth_token` only protects aiverywhere-to-gateway sends; never expose the CLI or gateway management API publicly; treat user text as untrusted input, and project file tools are read-only by default.
