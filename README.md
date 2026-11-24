<div align="center">

# aiverywhere

**一个可被任意宿主读取的 shell-first agent skill。需要时再加 CLI、Web 和消息通道。**

同一套工作约定、项目记忆和任务回执，在宿主 agent、终端、本地 Web 和消息渠道之间复用。

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host: sh + jq](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#快速开始)
[![CLI: Python 3.11+](https://img.shields.io/badge/cli-python%203.11%2B-blue.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#项目状态)

[简体中文](README.md) | [English](README.en.md)

</div>

## 这是什么

`aiverywhere` 是一个 **agent skill 产品**，不是一个必须先安装的命令行工具。

它把“怎么理解任务、什么时候查项目记忆、怎么执行和验证、什么值得长期保存”写成一份可读的 `SKILL.md`。任何能读文件、能执行命令的宿主 agent 都能使用；CLI、Web 和消息通道只是可选的运行方式。

它主要解决三个问题：

- **换宿主就丢工作约定**：同一份 skill 可以给 Claude Code、Codex、Cursor、其他编码 agent 或终端使用。
- **项目记忆散落**：事实、技能和线索以普通 JSON 文件保存在项目实例中，宿主和可选 CLI 共用。
- **简单任务被流程拖重**：普通问答可以直接回答；需要时再加载规划、回忆、执行、提取和收尾模块。

### 项目目标

- **Skill 是产品**：宿主只读一个入口，就能获得稳定的工作约定；不安装 CLI 也能完成日常任务。
- **可迁移**：宿主、CLI、Web 和消息通道共用同一个项目实例和 memory-v1，不按入口分裂数据。
- **本地优先**：默认只写项目实例；模型、权限和网络由调用方控制；不注册系统服务。
- **内核轻量**：对话策略尽量留在 skill；只有执行、权限、锁、revision、恢复和回执需要内核。

### 不是这些

- 不是托管的 SaaS，也不提供模型订阅；
- 不是微信/飞书的账号机器人，平台接入由可信 bridge 完成；
- 不要求所有任务都走多步骤流程；普通问答可以直接回答；
- 不保证不同机器、宿主和模型上的效果完全一致。

## 快速开始

### 只安装宿主 skill（推荐）

要求：macOS、Linux、POSIX `sh`；`jq` 可选。

在项目根目录运行：

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

会创建：

```text
<project>/.agents/skills/aiverywhere/   # 宿主读取入口
<project>/.aiverywhere/                 # 项目实例：配置、记忆、日志
```

不需要 Python、venv 或模型 Key。之后让宿主读取 `.agents/skills/aiverywhere/SKILL.md` 即可。

### 安装 CLI 和本地 Web（可选）

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
aiverywhere setup
aiverywhere
```

CLI 需要 Python 3.11+。`aiverywhere` 会显示当前项目和实例；输入 `/` 查看命令。

启动本地 Web：

```sh
aiverywhere web
# 或长期运行
aiverywhere start
```

### 验证

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

没有安装 CLI 时，用宿主读取 `.agents/skills/aiverywhere/SKILL.md`，或运行：

```sh
sh .agents/skills/aiverywhere/scripts/init-instance.sh
```

## 三个入口

| 入口 | 适合什么 | 需要什么 |
| --- | --- | --- |
| 宿主 agent | 日常编码、文档、分析；使用宿主自己的模型和工具 | 能读文件、执行命令；可选 `jq` |
| CLI | 独立终端、持久 session、worker、调度、Web | Python 3.11+ |
| Web / 消息通道 | 本机工作台、审批、运行记录、微信/飞书/iMessage 等 | 可选 CLI + 对应 bridge |

三种入口共用同一个 `.aiverywhere/` 实例和 memory-v1 格式，不另建记忆库。

## 常见操作

```sh
# 新建实例或补齐配置
aiverywhere init
aiverywhere setup

# 查看项目状态、记忆和运行记录
aiverywhere env
aiverywhere memory search '项目'
aiverywhere status

# 一次任务
aiverywhere run '读取 README，说明项目如何启动，并指出依据'

# 长期使用
aiverywhere chat
aiverywhere chat --resume
```

常用记忆命令：

```sh
aiverywhere memory put '月报单位' '默认用万元。'
aiverywhere memory search '月报'
aiverywhere memory search --kind clue
```

## 目录

项目本地实例：

```text
.aiverywhere/
├── config.json                 # 模型、运行预算、MCP、通道配置
├── instance.json               # 项目标识和实例根
├── skills/aiverywhere/         # 活动 skill bundle
├── overrides/                  # 项目级 workflow 覆盖
└── data/
    ├── memory/<project_key>/   # fact / skill / clue
    ├── sessions/               # CLI 持久会话
    ├── runs/                   # 运行详情
    ├── logs/                   # 摘要日志
    ├── artifacts/              # worker 产物
    └── project-settings/       # 宿主接入等非记忆设置
```

记忆一条一个 JSON 文件，带稳定 ID 和递增 revision；`state.json` 只保存调度、任务认领和渠道回执。

## 文档

### 用户手册

完整入口：[docs/guides/README.md](docs/guides/README.md)。

| 我想…… | 阅读 |
| --- | --- |
| 安装、升级、卸载、排查安装 | [安装指南](docs/guides/install.md) |
| 学会 CLI、会话、Web、记忆和工作流 | [使用手册](docs/guides/usage.md) |
| 接入微信、飞书、iMessage | [通用消息通道](docs/guides/channels.md) · [微信接入](docs/guides/wechat.md) |
| 把项目迁移到另一台机器 | [使用手册：宿主接入与迁移](docs/guides/usage.md#宿主接入与迁移) |
| 了解架构和完整能力 | [设计方案](docs/development/design.md) |

### 开发手册

完整入口：[docs/development/README.md](docs/development/README.md)。

| 我想…… | 阅读 |
| --- | --- |
| 搭建开发环境、提交改动 | [开发规范](docs/development/development.md) |
| 理解任务循环、存储、宿主和渠道边界 | [设计方案](docs/development/design.md) |
| 跑验收、看测试范围 | [十个典型验收场景](docs/development/acceptance.md) |
| 贡献代码、报告安全问题 | [贡献指南](docs/CONTRIBUTING.md) · [安全策略](docs/SECURITY.md) |

## 项目状态

当前版本：**[v0.5.0](https://github.com/ChanX96/aiverywhere/releases/tag/v0.5.0)**（alpha）。

已在 macOS arm64、Python 3.14 上验证，CI 覆盖 Python 3.11 和 3.14；Linux 以 CI 验证为准。

- 最低 Python：3.11；
- 宿主安装：macOS / Linux，POSIX `sh`；
- 默认只写项目实例和用户明确指定的产物；
- Web 只绑定 `127.0.0.1`；
- 不注册系统服务，不修改 shell 启动文件。

真实个人微信、部分第三方渠道、完整浏览器交互和部分宿主环境仍需按[开发规范](docs/development/development.md#选择与改动相称的验收)单独验收。

## 非关联声明

aiverywhere 是独立项目，不隶属于 Anthropic、OpenAI、DeepSeek、腾讯、飞书、Apple 或其他模型/渠道厂商。接入第三方服务时，请遵守对应服务条款。

## License

[MIT](LICENSE)
