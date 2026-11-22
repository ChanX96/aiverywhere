# 微信接入 aiverywhere

**简体中文** | [English](wechat.en.md)

aiverywhere **不直接登录个人微信**。以下命令假设 `aiverywhere` 已在 PATH；自定义安装根时加 `--home` 或设置 `AIVERYWHERE_HOME`。个人微信的登录、账号配对、收信验证和发送由可信网关负责；aiverywhere 只负责把已验证的来信变成持久任务、用实例模型生成答复，并把答复和送达回执写回网关。微信通道是可选适配器，不改变宿主或 CLI 的核心 agent loop。

## 1. 前提

- macOS 或 Linux，已安装 CLI，并且实例已配置可运行的模型或原生执行器。`wechat` 命令只把来信排入队列；真正生成答复的是外部调度器触发的 `wake`，它需要模型访问权。
- 有一个能接收微信消息、完成账号配对和入站验证的网关。网关还需要实现本文的出站 HTTP 契约。
- 当前一个实例只绑定**一个账号 + 一个会话**。多个联系人或群聊要分别使用不同实例（不同 `--home`）或扩展现有适配器。
- 网关应在本机回环地址或 TLS 后运行；不要把 `aiverywhere wechat` 或网关管理接口直接暴露到公网。

## 2. 配置

在实例的 `config.json` 中填写 `wechat` 分区：

```json
{
  "project": "/绝对路径/任务项目",
  "account": "demo",
  "conversation": "chat-1",
  "url": "http://127.0.0.1:8787",
  "auth_token": "网关访问令牌",
  "idempotent_send": true,
  "receipt_lookup": true,
  "timeout": 600,
  "max_turns": 12,
  "progress_after": 120
}
```

| 字段 | 约定 |
| --- | --- |
| `project` | 必填。绝对路径，必须等于调用 `wake` 和 `wechat` 时的 `--project`。 |
| `account` | 必填。网关绑定的微信账号标识。 |
| `conversation` | 必填。网关绑定的会话标识。 |
| `url` | 必填。网关 HTTP(S) 基地址，不含账号、查询参数或片段。 |
| `auth_token` | 可选。aiverywhere 发往网关时发送 `Authorization: Bearer <token>`；入站认证由网关负责。 |
| `idempotent_send` | 网关是否能按 `Idempotency-Key` 保证同一投递只生效一次。 |
| `receipt_lookup` | 网关是否支持 `GET /messages/<id>` 查询回执。 |
| `timeout` | 本次微信任务的秒数；默认沿用实例 `defaults.timeout`。 |
| `max_turns` | 本次微信任务的工具回合上限；默认沿用实例 `defaults.max_turns`。 |
| `progress_after` | 无进展提醒的等待秒数，默认 120；`0` 表示只提醒有证据的偏离。 |

`config.json` 可能包含模型密钥和网关令牌，保持 `0600`，不要提交或分享。修改配置后，新任务使用新配置；已开始的发送继续核对原绑定。

## 3. 入站：网关到 aiverywhere

网关确认来信属于已配对账号和会话后，把消息规范化为一个 JSON 对象，通过标准输入交给 CLI：

```json
{
  "account": "demo",
  "conversation": "chat-1",
  "message_id": "wx-msg-001",
  "text": "整理一下这周的进展。"
}
```

```sh
printf '%s\n' "$MESSAGE_JSON" |
  aiverywhere --project /绝对路径/任务项目 wechat
```

更稳妥的做法是用 Python 或网关自身的 HTTP 客户端序列化后启动子进程，不要把用户正文拼进 shell 字符串：

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
    ["aiverywhere", "--project", "/绝对路径/任务项目", "wechat"],
    input=json.dumps(envelope, ensure_ascii=False),
    text=True,
    capture_output=True,
    check=True,
)
task = json.loads(result.stdout)
```

成功时标准输出返回类似：

```json
{
  "task_id": "wechat:2f0c...",
  "status": "queued",
  "delivery": "queued",
  "receipt": null,
  "detail": null
}
```

`queued` 只表示消息已持久化，**还没有调用模型**。网关应保存 `message_id → task_id` 映射，稍后可用它查询状态。

字段和去重规则：

- `account`、`conversation` 必须与配置完全一致，否则拒绝。
- `message_id` 最多 256 字符，`text` 最多 65,536 字符；输入信封最大 1 MiB。
- 同一项目、账号、会话和 `message_id` 重复提交同一正文会返回原任务；同一 `message_id` 换成不同正文会报错。网关必须为每条来信分配稳定、唯一的 ID。
- 网关负责验证消息确实来自对应微信账号；CLI 不提供入站签名验证。

## 4. 启动外部调度

来信入队后，需要生成并交付答复。aiverywhere 不常驻、不注册系统服务；由外部 cron、launchd、systemd timer 或进程管理器周期调用一次 `wake`：

```cron
* * * * * cd /绝对路径/任务项目 && aiverywhere --project /绝对路径/任务项目 wake --dream
```

每次调用会顺序处理到期计划、一个微信任务，并在 `--dream` 且有空闲线索时执行一次普通 Dream。调用越频繁，微信响应越及时；进程存活、重试和日志由外部调度器负责。没有调度器时，微信任务会一直停留在 `queued`。

cron 的 PATH 通常很窄；请使用安装根虚拟环境的绝对命令路径，或在 crontab 中显式设置 PATH。

`wake` 必须能读取同一实例的 `data/`，并使用已配置的模型或原生执行器。只有宿主模型、没有独立执行器时，不要让 CLI 处理微信；应在宿主侧接入。

## 5. 出站：aiverywhere 到网关

生成完成或任务失败后，aiverywhere 向 `{url}/messages` 发送：

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
  "text": "这是最终答复。"
}
```

网关必须在成功响应中回显同样的地址字段，并给出 `state` 和非空 `receipt`：

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

- `state` 只能是 `accepted` 或 `delivered`。前者表示网关已接收，后者表示网关确认已送达微信侧。
- `id`、`account`、`conversation`、`reply_to` 必须原样回显；缺少或不同会被视为回执不可核实。
- `idempotent_send` 为 `true` 时，网关应以 `Idempotency-Key` 保存第一次结果；同一 key 重试返回同一回执，不重复发送。
- 网关返回 `5xx`、`408` 或 `429` 时，aiverywhere 会在时限内有限重试；其他非 2xx 记为拒绝或结果未知。
- 送达不确定时，如果 `receipt_lookup` 为 `true`，aiverywhere 会先查询 `GET {url}/messages/{id}`；`404` 表示尚未接收。只有 `idempotent_send` 也为 `true` 时才会重发，否则保留待核对。
- 网关不提供幂等或回执查询时，状态会保留为“送达待核对”，不能声称已送达。

进度提醒使用独立的 ID：`<任务ID>.progress`。它同样发往 `/messages`，`reply_to` 仍是原来信 ID。网关应能把它当作普通消息投递；每个任务至多一条进度提醒。

## 6. 查询状态

```sh
aiverywhere --project /绝对路径/任务项目 wechat --status wechat:2f0c...
```

返回内容包括任务状态、答复或错误、`delivery`、网关回执、最近进度和检查点。`status` 是任务是否完成，`delivery` 是消息是否送达，两者不能混为一谈。

## 7. 最小网关实现清单

1. **验证入站**：确认微信账号、会话和消息来源可信，生成稳定 `message_id`；不要转发未验证消息。
2. **入队**：按上一节调用 `aiverywhere wechat`，保存返回的 `task_id`。
3. **实现 POST**：按 `Idempotency-Key` 去重，发往微信侧，回显完整地址并返回 `accepted` 或 `delivered` 加 `receipt`。
4. **实现 GET**：按 `id` 返回和 POST 相同的回执结构；未知 ID 返回 404。需要支持带 `.progress` 的 ID。
5. **启动调度**：用 cron、launchd、systemd timer 或进程管理器周期调用 `wake --dream`。
6. **保留日志**：记录 `message_id → task_id`、投递 key、回执和错误；不要记录令牌或完整私聊正文。
7. **限流与大小限制**：在网关侧限制频率、正文长度和并发；CLI 已限制信封 1 MiB、正文 65,536 字符。

## 8. 验收

在临时实例和本地假网关上至少完成：

1. 发送一条合法来信，收到 `queued` 和稳定 `task_id`。
2. 调用 `wake`，网关收到一次 POST；`id`、`account`、`conversation`、`reply_to` 和 `text` 正确。
3. 网关回 `accepted`/`delivered` 后，`wechat --status` 显示相同回执。
4. 重复提交同一 `message_id`，不产生第二个任务或第二次投递。
5. 模拟 POST 已发送但回执丢失：开启幂等/查询时不重复发送，状态最终可核实；关闭时保留“待核对”。
6. 重启进程/再次调用 `wake`，未完成任务继续或明确中断，不丢失原会话地址。
7. 用不匹配的 `account` 或 `conversation` 提交，确认被拒绝。

真实个人微信账号、扫码登录、平台封控和实际送达仍需在网关侧联调；本项目当前只验证了假网关回执、进程重启和上下文压缩路径。

## 9. 故障排查

| 现象 | 检查 |
| --- | --- |
| 留言返回 403 | `account`/`conversation` 与配置不一致，或 `project` 不是启动实例的绝对路径。 |
| 留言返回 400 | 缺少字段、正文超过 65,536 字符、信封超过 1 MiB，或同一 `message_id` 换了正文。 |
| 一直 `queued` | 没有调度器调用 `wake`，或没有配置模型/原生执行器。运行 `wake` 并查看输出。 |
| `delivery` 长期 `unknown`/`verify` | 网关没有按契约回显地址和 `receipt`，或没有实现 GET；检查 `idempotent_send`/`receipt_lookup`。 |
| 重复回复 | 网关没有按 `Idempotency-Key` 去重，或没有复用同一任务 ID。 |
| 进度消息被当作重复回复 | 网关应识别 `<任务ID>.progress` 为独立投递，并自行决定是否展示。 |
| 微信登录/掉线 | 属于网关的账号连接职责；aiverywhere 不处理扫码和登录。 |

安全边界：网关是唯一可信的微信入口；`auth_token` 只保护 aiverywhere 到网关的发送；不要把 `aiverywhere` CLI 或网关管理接口暴露到公网；用户正文按不可信输入处理，项目文件工具默认只读。
