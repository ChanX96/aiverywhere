# aiverywhere 用户手册

本手册面向安装和使用 aiverywhere 的用户。只想让宿主 agent 使用 skill 时，从安装开始即可；CLI、Web、消息通道和迁移都是可选项。

## 当前入口状态

| 入口 | 状态 | 已验证范围 |
| --- | --- | --- |
| 仅宿主 skill | 稳定基线 | 安装、链接、Shell 记忆互读、workflow 覆盖 |
| CLI | alpha | 会话、记忆、权限、worker、Web、迁移 |
| Web | alpha | 本机对话、审批/决策、过程面板、todo、运行记录 |
| 微信 / 飞书 / iMessage | alpha | 通用 envelope、bridge 发现、单元/模拟回执；真实账号需单独接入验证 |

当前发布为 **v0.5.0**。真实宿主、浏览器、微信账号和不同 Linux 发行版仍需按对应验收复核。

## 推荐阅读顺序

1. [安装 aiverywhere](install.md)：选择仅宿主、CLI 或手动安装。
2. [第一次任务](#第一次任务)：确认实例、模型和权限。
3. [使用手册](usage.md)：CLI、会话、Web、记忆、工作流和人工介入。
4. 需要渠道时读[通用消息通道](channels.md)或[微信接入](wechat.md)。
5. 换机器或项目时读[宿主接入与迁移](usage.md#宿主接入与迁移)。

## 第一次任务

### 仅宿主

安装后让宿主读取：

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

然后用一个可核对的任务开始，例如：

```text
读取本项目 README，告诉我如何启动项目，并指出依据。
```

宿主用自己的模型、文件工具和权限；aiverywhere 不要求它安装 CLI。

### CLI

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
aiverywhere
```

在 TTY 中输入 `/` 查看命令。`aiverywhere` 默认进入当前项目实例；使用 `--project` 和 `--home` 可以显式绑定。

### Web

```sh
aiverywhere web
# 或
aiverywhere start
```

Web 默认只绑定 `127.0.0.1`，默认只读；读写权限、命令执行和联网分别授权。

## 常用主题

| 主题 | 文档 |
| --- | --- |
| 安装、升级、卸载、安装故障 | [安装指南](install.md) |
| 模型配置、会话、CLI、Web、记忆、工作流 | [使用手册](usage.md) |
| 微信、飞书、iMessage 和通用 envelope | [通用消息通道](channels.md) |
| 微信旧版网关配置、账号绑定和出入站协议 | [微信接入：配置](wechat.md#2-配置) |
| 宿主免点名接入、运行中输入、迁移包 | [使用手册：宿主接入与迁移](usage.md#宿主接入与迁移) |
| 安全模型和凭据边界 | [安全策略](../SECURITY.md) |
| 开发、架构和验收 | [开发手册](../development/README.md) |

## 重要边界

- 宿主安装不需要 Python；可选 CLI 需要 Python 3.11+。
- 记忆、会话、日志和产物默认位于项目实例内。
- 模型凭据可以只保存环境变量名，不要求写进实例。
- 微信、飞书等平台由可信 bridge 接入；aiverywhere 不直接登录账号。
- 真实宿主、浏览器、微信账号和调度环境的验收以[开发规范](../development/development.md#选择与改动相称的验收)为准。
