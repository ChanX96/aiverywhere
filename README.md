<div align="center">

# aiverywhere

**把 skill 当作产品，而不是 CLI 的附属。**

同一份 agent 约定，运行在任意宿主、终端和本地工作台。

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host: sh + jq](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#仅宿主安装)
[![CLI: Python 3.11+](https://img.shields.io/badge/cli-python%203.11%2B-blue.svg)](pyproject.toml)
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
- SSE 流式正文、CLI 流式输出、Ctrl+C；TTY 任务结束回到提示符，管道输入仍可 `/cancel`；
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
bridges/                   可发现的常驻 bridge 插件目录和模板
src/aiverywhere/
├── cli/                  CLI 命令与组合根
├── core/                 agent、store、memory、tools、worker
├── integrations/web/     Web 服务、会话和静态资源
├── integrations/bridges/ bridge 抽象类、模板发现和健康检查
├── integrations/wechat.py
├── platform/             环境探测和命令隔离
└── ui/                   欢迎屏与终端展示
```

## 快速开始

### 交给 agent 的一句话

只装 skill，不装 CLI：

```text
安装 aiverywhere skill：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

安装 skill + 可选 CLI：

```text
安装 aiverywhere CLI：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

手动安装、bridge 插件和卸载见[安装指南](docs/guides/install.md#选择安装方式)。

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

### 工作流模块

主 skill 从 `references/workflow/` 按需读取 `plan`、`recall`、`execute`、`extract`、`finish`，不是每个任务都加载五份文档。项目可用 `overrides/<project_key>/workflow/<module>.md` 覆盖前四个模块；`finish` 固定。CLI 的 `aiverywhere workflow list/path/show` 可查看实际生效文件。

用户明确要求记住、设定默认值或纠正记忆时，CLI 模型可先登记 `require_memory`，保存后回读；业务完成但必记项未确认时任务标为 `partial`。

### 宿主 agent

直接把项目交给宿主，或让它读取：

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

宿主使用自己的模型、工具和权限；`aiverywhere` 只提供行为约定和记忆协议。

### 常驻进程与 Web

交互式 CLI 默认会确保一个**单实例常驻 supervisor**运行，并打开本地 Web。历史 session 可直接恢复：

```sh
aiverywhere chat --resume <session-id>
```

会话是持久对话，任务是一次执行；Web 的“会话与任务”页列出 CLI session 和恢复命令，Web 对话本身是当前 supervisor 进程内的临时上下文。



```sh
aiverywhere
aiverywhere start
aiverywhere status
aiverywhere stop
```

- Web 只绑定 `127.0.0.1`；
- 退出 CLI 后，Web、Web 对话任务和 channel worker 继续运行；
- 不注册 launchd、systemd 或 cron，需由用户显式启动/停止；
- 实例内保存 PID、端口、token 和日志，文件权限 `0600`。

`aiverywhere web` 现在只确保 supervisor 运行并打印/打开地址，不再阻塞终端。

### 模型协议

CLI 支持四种协议：

| 协议 | 用法 | 默认地址 |
| --- | --- | --- |
| `anthropic` | Anthropic Messages，默认 | `https://api.anthropic.com` |
| `openai` | OpenAI Chat Completions | `https://api.openai.com/v1` |
| `ollama` | 本地 Ollama 的 OpenAI 兼容接口 | `http://127.0.0.1:11434/v1` |
| `custom` | 自定义 OpenAI 兼容网关 | 需提供 `base_url` |

示例：

```sh
aiverywhere setup --protocol openai --model gpt-4.1 --api-key "$OPENAI_API_KEY"
aiverywhere setup --no-input --protocol ollama --model llama3.2
aiverywhere setup --protocol custom --model local-model \
  --base-url http://127.0.0.1:8000/v1 --chat-path /v1/chat/completions
```

自定义请求头可直接写入实例 `config.json`：

```json
{
  "model": {
    "protocol": "custom",
    "model": "local-model",
    "base_url": "http://127.0.0.1:8000/v1",
    "chat_path": "/v1/chat/completions",
    "headers": {"X-Provider": "local"}
  }
}
```

`custom` 走 OpenAI Chat Completions 形状；工具调用、流式输出和错误处理与 OpenAI 相同。

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
| `/resume <id>` | 恢复指定 session；`aiverywhere chat --resume` 列出最近会话 |
| `/rename <name>` | 重命名当前 session |
| `/sessions` | 列出当前项目的 session |
| `/status` | 当前 session、turn 数、token 估算 |
| `/compact` | 手动压实当前上下文 |
| `/permissions` | 查看当前 session 授权 |
| `/grant write\|exec\|network` | 授予本 session 能力 |
| `/revoke write\|exec\|network` | 撤销本 session 能力 |
| `/approve` / `/deny` | 允许或拒绝待确认的工具操作 |
| `/jobs` | 查看当前进程内的任务 |
| `/cancel` | 取消当前任务（TTY 任务运行中按 Ctrl+C） |
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

CLI/Web 支持运行中补充输入、人工决定和可撤销的宿主规则引导；可用 `aiverywhere migrate` 在机器间迁移 skill、workflow 覆盖和记忆。Web 可以对话；回答按 Markdown 渲染标题、列表、引用、链接、内联代码和带语言标签/复制按钮的代码块，模型返回的思考过程、工具/Skill/MCP 调用和 todo 完成情况以可折叠过程面板显示，文本随 SSE/轮询增量显示，并可在右侧选择慢/标准/快显示速度。用 `/` 命令菜单管理记忆和 skill、编辑完整 Agent bundle、查看历史 CLI session 与带工具参数/结果的运行详情，并按需分别授权写文件、执行命令和联网。一个 Web 绑定一个项目实例；切换项目需在目标项目目录启动 `aiverywhere`。Web 和常驻 worker 由 supervisor 托管；CLI 退出后仍继续运行，直到 `aiverywhere stop`。

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
- [通用消息通道](docs/guides/channels.md)
- [微信旧版接入](docs/guides/wechat.md)
- [设计方案](docs/development/design.md)
- [开发规范](docs/development/development.md)
- [English README](README.en.md)

## 贡献

欢迎提交 Issue 和 PR。涉及行为约定的改动请先阅读 [开发规范](docs/development/development.md)，并同步更新 `skills/aiverywhere/SKILL.md` 和相关验收。

## 非关联声明

aiverywhere 是独立开源项目，不隶属于 Anthropic、OpenAI、腾讯、飞书、Apple 或文中提及的其他产品/服务，也未获得其官方背书。产品名称仅用于说明协议兼容性和接入对象；真实平台接入、账号、数据和条款由使用者及其 bridge 负责。

## License

[MIT](LICENSE)
