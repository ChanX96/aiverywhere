# 通用消息通道

**简体中文** | [English](channels.en.md)

aiverywhere 不直接登录任何 IM 平台。WeChat、飞书、iMessage 或自定义桥接器通过一个很小的 **webhook channel envelope** 接入；aiverywhere 负责任务、模型执行、持久化和回复路由，桥接器负责平台登录、签名验证和实际发送。

## 配置

实例根 `config.json`：

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

字段：

| 字段 | 说明 |
| --- | --- |
| `url` | 必填。桥接器地址；aiverywhere 会 POST 到 `url + send_path`。 |
| `send_path` | 默认 `/messages`。 |
| `auth_token` / `auth_token_env` | 可选 Bearer token；优先使用环境变量引用。 |
| `account` / `conversation` | 可选。配置后只接受该账号/会话；通常留空，由入站消息携带。 |
| `idempotent_send` | 网关是否保证同一 `Idempotency-Key` 不重复发送。 |
| `receipt_lookup` | 网关是否支持按 ID 查询回执。 |
| `timeout` / `max_turns` | 覆盖实例默认值。 |

`type` 目前只支持 `webhook`。这不是限制平台，而是把平台差异留在桥接器：同一套 envelope 可以接 WeChat、飞书和 iMessage。需要原生协议时，再增加适配器，不改变 agent 内核。

旧版 `wechat` 配置会在没有 `channels` 时自动映射为 `wechat` webhook channel。

## 入站

常驻 supervisor 默认在实例配置端口提供本机 Web API。桥接器把已验证消息提交到：

```http
POST /api/channels/<channel>/messages
X-Aiverywhere-Token: <daemon token>
Content-Type: application/json

{
  "account": "account-id",
  "conversation": "conversation-id",
  "message_id": "stable-inbound-id",
  "text": "用户消息"
}
```

`message_id` 必须稳定；同一 channel/account/conversation/message_id 重复投递只返回原任务。`channel` 由路径指定，body 中不需要重复。

任务持久化在实例 `state.json` 的 `jobs` 中，记录：

```text
channel + account + conversation + message_id
```

worker 执行完成后，回复只会回到这个原 channel，不会猜测或切换到其他通道。

查询：

```http
GET /api/channels/<channel>/status?task_id=<task_id>
```

旧的 `POST /api/wechat` 仍作为 `wechat` 通道兼容入口。

## 出站

aiverywhere 调用：

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
  "text": "答复"
}
```

桥接器必须回显 `channel`、`account`、`conversation`、`reply_to`，并返回：

```json
{"state": "accepted", "receipt": "receipt-id"}
```

`accepted` 表示网关已接收，`delivered` 表示已确认送达。缺少回执时 aiverywhere 保留 `unknown` 或 `verify`，不会声称成功。

## 常驻和启动

```sh
aiverywhere start       # 启动 supervisor 和 Web
aiverywhere status
aiverywhere stop
aiverywhere             # 确保 supervisor 已启动，并进入 CLI
aiverywhere web         # 确保 supervisor，打印/打开 Web
```

supervisor 是单实例，使用：

```text
data/daemon.json
data/daemon.lock
data/daemon.startup
data/logs/daemon.log
```

不注册系统服务；机器重启后需要用户再次启动。

## 平台桥接建议

| 平台 | 桥接器职责 |
| --- | --- |
| WeChat | 登录/配对、入站验证、账号与会话映射、发送与回执 |
| 飞书 | 应用/机器人事件订阅、验签、chat_id 映射、发送 |
| iMessage | 本机 Messages 数据库或 AppleScript 桥接、发送回执 |

平台登录、二维码、封控、签名和真实送达不属于核心 skill；桥接器只负责协议，aiverywhere 负责任务和回复路由。
