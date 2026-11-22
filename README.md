<div align="center">

# aiverywhere

**把 skill 当作产品，而不是 CLI 的附属。**

同一份 agent 约定，运行在任意宿主、终端和本地工作台。

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host: sh + jq](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#仅宿主安装)
[![CLI: Python 3.9+](https://img.shields.io/badge/cli-python%203.9%2B-blue.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#项目状态)

[简体中文](README.md) | [English](README.en.md)

</div>

## 项目说明

`aiverywhere` 是一个 **shell-first 的通用 agent skill**，也可以按需安装成一个独立 CLI。

传统 agent 项目通常先要求安装 Python、创建 venv、配置命令，再把 skill 作为附属文件塞进去。`aiverywhere` 反过来：

- **`SKILL.md` 是核心产品**，任何能读文件、执行命令的宿主都能使用；
- 宿主只安装 skill 时，记忆、线索和实例初始化全部由 **POSIX Shell + JSON 文件**完成；
- CLI 是可选宿主，不是使用前提；
- CLI、宿主、Web、定时任务读写**同一套记忆文件和 schema**。

它适合希望把一套工作约定同时用于 Claude Code、Codex、Cursor、终端脚本、本地 Web 和定时任务的用户。

## 亮点

### 1. 不强制安装 CLI

默认安装只做三件事：

```text
复制 skill bundle
创建 .aiverywhere/ 实例
链接 .agents/skills/aiverywhere
```

不需要 Python、pip、venv 或模型 Key。没有 CLI，也可以创建、检索、读取和校验记忆。

### 2. 记忆是普通文件

一条记录一个 JSON 文件：

```text
.aiverywhere/data/memory/<project_key>/<id>.json
```

- `kind` 支持 `fact`、`skill`、`clue`；
- 稳定 ID、递增 `revision`、原子写入；
- JSON Schema 固定格式；
- `state.json` 只保存计划、任务和渠道回执，不再混入记忆正文。

CLI 的持久会话在：

```text
.aiverywhere/data/sessions/<project_key>/<session_id>.jsonl
```

一条 session 一个追加式文件，带锁、序号和崩溃恢复；`state.json` 不保存会话正文。

### 3. 宿主和 CLI 共用记忆

Shell 写下的记录，CLI 可以立即检索；CLI 写入的记录，宿主也能读取。

CLI 写前复用同一份 `validate-memory.sh`；没有 `jq` 时，宿主可以按 schema 做原生校验，或明确标记为“格式待校验”。

### 4. 主动式 skill

`SKILL.md` 不只回答“怎么调工具”，还规定：

- 什么时候应该回忆；
- 什么值得写成 fact / skill；
- 什么异常要留下 clue；
- 什么时候处理旧线索；
- 什么时候把重复流程沉淀为技能。

Dream、计划、任务回执和 worker 都围绕这套约定工作。

### 5. 工具、worker 和流式输出

- 文件读取、搜索、局部编辑和受控命令执行；
- 深度 1 的并行 worker、私有工作区和 artifact 交接；
- SSE 流式正文、CLI 流式输出、Ctrl+C 和 `/cancel`；
- 本地 Web 工作台、微信网关、MCP 和定时任务等可选适配器；
- 默认只读，写入和命令执行需要显式授权。

### 6. 免 Key 网页搜索

`web_search` 使用 **Bing RSS** 作为主通道，失败时回退到 **DuckDuckGo HTML**，不再依赖 Tavily Key。

`web_fetch` 只读取公开 HTTP(S) 文本页面，并在每次重定向时拒绝内网、回环和保留地址。

### 7. 本地优先

- 默认实例在项目内：`<project>/.aiverywhere/`；
- 模型凭据可只保存环境变量名；
- Web 只绑定回环地址；
- 页面资源随包分发，不依赖 CDN；
- 不注册系统服务，不修改 shell 启动文件。

### 8. 持久会话与自动 compaction

CLI 默认恢复当前项目最近的 session；会话写入追加式 JSONL，崩溃后只恢复到完整记录。上下文接近预算时自动摘要旧回合，原始记录不删除；摘要失败则使用确定性回退，仍超限时明确失败而不是静默丢上下文。

```sh
aiverywhere
# 输入 / 查看命令菜单
```

## 架构

```text
宿主 agent / CLI / Web / 微信 / 定时任务
                  │
                  ▼
             SKILL.md
                  │
                  ▼
       Task 循环 + Tools + Worker
                  │
                  ▼
   .aiverywhere/data/memory/<key>/*.json
        （宿主与 CLI 共用）
```

源码按职责分层：

```text
src/aiverywhere/
├── cli/                  CLI 命令与组合根
├── core/                 agent、store、memory、tools、worker
├── integrations/web/     Web 服务、会话和静态资源
├── integrations/wechat.py
├── platform/             环境探测和命令隔离
└── ui/                   欢迎屏与终端展示
```

## 快速开始

### 仅宿主安装

要求：macOS / Linux、POSIX `sh`；`jq` 可选。

在项目根目录执行：

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

使用源码检出：

```sh
./install.sh
```

安装后：

```text
<project>/.agents/skills/aiverywhere/SKILL.md
<project>/.aiverywhere/skills/aiverywhere/scripts/
```

宿主读取 `SKILL.md`；需要记忆时调用同目录 `scripts/`。不需要 Python。

### 可选 CLI

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
```

或从源码：

```sh
./install.sh --cli
```

配置模型：

```sh
aiverywhere setup
```

无人值守安装：

```sh
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="your-model"
./install.sh --cli --yes
```

### 验证安装

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

当前项目实例应指向：

```text
<project>/.aiverywhere/
<project>/.agents/skills/aiverywhere
```

## 使用

### 宿主 agent

直接把项目交给宿主，或让它读取：

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

宿主使用自己的模型、工具和权限；`aiverywhere` 只提供行为约定和记忆协议。

### 交互式 CLI

```sh
aiverywhere
```

在真实 TTY 中会显示欢迎屏并进入交互：

```text
aiverywhere ›
```

输入 `/` 会显示命令补全菜单：

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示帮助 |
| `/new` | 开始一个新的会话 |
| `/resume <id>` | 恢复指定 session |
| `/sessions` | 列出当前项目的 session |
| `/status` | 当前 session、turn 数、token 估算 |
| `/compact` | 手动压实当前上下文 |
| `/permissions` | 查看当前 session 授权 |
| `/grant write\|exec\|network` | 授予本 session 能力 |
| `/revoke write\|exec\|network` | 撤销本 session 能力 |
| `/approve` / `/deny` | 允许或拒绝待确认的工具操作 |
| `/jobs` | 查看当前进程内的任务 |
| `/cancel` | 取消当前任务 |
| `/ask <id> <问题>` | 向已完成任务追加问题 |
| `/quit` | 退出交互 |

写入和命令执行默认关闭：

```sh
aiverywhere --allow-write
aiverywhere --allow-exec
```

一次性任务：

```sh
aiverywhere run '读取 README，告诉我如何启动 Web，并指出依据'
```

### 本地 Web

```sh
aiverywhere web
```

默认尝试打开 `http://127.0.0.1:8765/`；无桌面环境时只打印地址：

```sh
aiverywhere web --no-open
```

Web 可以对话、管理记忆和 skill、查看日志，并按需分别授权写文件、执行命令和联网。

## 记忆

### Shell 用法

```sh
SKILL=.agents/skills/aiverywhere

sh "$SKILL/scripts/init-instance.sh"
sh "$SKILL/scripts/write-memory.sh" \
  --kind fact \
  --title '月报单位' \
  --text '月报统一使用万元。' \
  --source task-001
sh "$SKILL/scripts/list-memory.sh" --kind clue
sh "$SKILL/scripts/read-memory.sh" <id>
```

### CLI 用法

```sh
aiverywhere memory put '月报单位' '月报统一使用万元。'
aiverywhere memory search '月报'
aiverywhere memory search --kind clue
aiverywhere memory forget <id>
```

### 文件格式

```json
{
  "schema_version": 1,
  "id": "0123456789abcdef0123456789abcdef",
  "revision": 1,
  "kind": "fact",
  "title": "月报单位",
  "text": "月报统一使用万元。",
  "source": "task-001",
  "updated": "2026-11-22T12:00:00Z",
  "shared": false
}
```

字段约束见 [memory-v1.schema.json](skills/aiverywhere/references/memory-v1.schema.json)。

## 项目状态

当前为 alpha 阶段，已在本机验证：

- 仅宿主安装、`--cli` 安装、重复安装和干净 wheel 安装；
- Shell 与 CLI 双向读写同一记忆；
- 旧 `state.json` 记忆迁移；
- 工具、worker、流式输出和 Web 基础路径；
- Bing RSS 真实搜索；
- session 恢复、锁、部分写入修复和自动 compaction 单元测试。

仍待验证或完善：

- 真实个人微信、浏览器渠道和 Linux 外部调度；
- 真实交互 TTY 的长期使用体验；
- 不同宿主对 skill 的自动发现差异；
- 更细的源码子包拆分和长期记忆索引。

## 开发

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
make check
```

`make check` 包含 Python 测试、Shell memory 测试和 ShellCheck。

单独运行：

```sh
.venv/bin/python -m unittest discover -s tests -v
sh tests/shell/memory.sh
```

## 文档

- [安装指南](docs/guides/install.md)
- [使用手册](docs/guides/usage.md)
- [微信接入](docs/guides/wechat.md)
- [设计方案](docs/development/design.md)
- [开发规范](docs/development/development.md)
- [English README](README.en.md)

## 贡献

欢迎提交 Issue 和 PR。涉及行为约定的改动请先阅读 [开发规范](docs/development/development.md)，并同步更新 `skills/aiverywhere/SKILL.md` 和相关验收。

## License

[MIT](LICENSE)
