# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0] - 2026-11-22

### Added

- 面向任意宿主 agent 的一句话安装脚本 `install.sh`，可选安装 CLI；宿主接入不再区分具体产品。
- `aiverywhere setup`：交互式模型与运行参数配置，除模型名和凭据外均有默认值；支持非交互和环境变量凭据。
- `aiverywhere link`：把活动 agent 链接到通用技能目录 `.agents/skills/aiverywhere`。
- `defaults` 配置分区：`max_turns`、`timeout`、`port` 可由实例配置覆盖。
- 模型配置支持 `max_tokens`、`api_key_env` 与 `auth_token_env`。
- 标准开源仓库文件：更新日志、安全策略、行为准则、Issue/PR 模板、Dependabot、Makefile、CI 与发布工作流。
- 面向使用者的 README、安装指南、使用手册、微信接入指南、开发规范与社区文档同时提供中文和英文版本。
- `memory kind=clue`：线索复用记忆存储、锁和修订号，`memory search --kind clue` 只读列出，`memory forget` 标记已处理。
- `aiverywhere dream` 改为普通任务；宿主可在空闲检查点用自己的模型完成同样的 Dream，CLI/`wake --dream` 使用同一提示词。
- CLI `chat` 改为顺序执行，移除并行队列、取消和 `jobs` 预算；核心壳与 web/微信/调度/MCP/原生执行器等可选适配器边界写入 README 和设计说明。
- 新增 `aiverywhere welcome` 和直接运行 `aiverywhere` 的欢迎终端；显示项目、实例、模型、Agent 修订与记忆状态，TTY 下进入交互。
- 本地工作台新增“对话与工作”：进程内会话、后台任务、状态轮询和工具回执；默认只读，显式开启工作模式后允许写项目文件；界面改为深色科技风对话工作区。
- 增加 `search_files`、`edit_file`、`run_command`、`web_search`、`web_fetch`；新增 `--allow-exec`，网页工具默认可用，命令取消时终止进程组。
- 增加深度 1、最多 2 个的 `delegate` worker；私有工作区、artifact 交接、`accept_artifact`、Seatbelt/bubblewrap 隔离探测和 `/cancel <worker-id>`。
- Messages 适配器支持 SSE 文本流；非 JSON 的 `run`/`chat` 流式显示，Ctrl+C 或 `/cancel` 取消当前任务，JSON 回执保持单份。
- 配置迁到实例根 `config.json`，`data/` 保留活动 skill、状态、日志和 artifacts；`init` 迁移旧配置并报告冲突。
- 文档迁到 `docs/guides/` 和 `docs/development/`；root config 加入忽略规则。
- Skill bundle 增加 memory-v1 schema 和纯 POSIX Shell 的 init/validate/write/list/read；仅宿主安装不需要 Python、venv 或 CLI。
- 记忆迁到项目 `.aiverywhere/data/memory/<project_key>/<id>.json`；Python Store 复用 Shell 校验并迁移旧 `state.json` 记忆；`state.json` 只保存计划、任务和渠道回执。
- `install.sh` 默认仅宿主为纯 Shell；`--cli` 才是可选 Python 安装。
- 源码按 `cli/core/integrations/platform/ui` 目录重构，保留 `aiverywhere.cli:main`。
- 修复流式响应中的 provider thinking 块导致下一轮工具请求 HTTP 422：工具循环只保留 text/tool_use 块。
- CLI 交互改为单会话多轮：连续输入共享同一个 Task 历史和 task_id，`/new` 才显式切换会话；修复退出时 `reader` 为 `None` 的回溯。
- CLI 增加 `/permissions`、`/grant`、`/revoke`、`/approve`、`/deny`，写文件/命令/联网可在 session 内授权或逐次审批；Web 工作台复用对应权限字段。
- CLI 增加 JSONL 持久 session、默认恢复最近会话、`/resume`/`/sessions`/`/status`/`/compact`；自动 compaction 支持模型摘要、确定性回退和硬上限错误。
- CLI 交互输入使用 prompt-toolkit；输入 `/` 显示 `/help`、`/jobs`、`/cancel`、`/ask`、`/quit` 菜单。
- README 重写为 GitHub 项目首页结构，补充亮点、架构、快速开始、状态和开发说明。
- 网页搜索从 Tavily 切换为免 Key 的 Bing RSS，失败时回退 DuckDuckGo HTML。
- 欢迎屏改为从 `AIVERYWHERE` 字模生成的可读大字标；CLI 提示改为 `aiverywhere ›` 并支持 `/help`。
- `aiverywhere web` 在 TTY 桌面环境默认打开浏览器；`--no-open` 关闭。
- `aiverywhere --version` 与动态版本元数据。

### Changed

- `init` 创建的统一配置增加空的 `defaults` 分区；旧配置继续有效。
- 新安装默认使用 `~/.aiverywhere` 作为用户级安装根；项目内联链接可反向定位自定义安装根。
- 微信任务和定时任务未单独配置时，沿用实例的运行参数默认值。
- 记忆写入不再自动生成反思线索；线索改由模型显式用 `kind=clue` 记录，Dream 自己的写入不会触发下一轮。

### Removed

- 常驻 `wake --watch`、内置系统服务登记和 `jobs` 并发预算；定时与微信 worker 改由外部 cron/launchd/systemd timer 调用一次性 `wake`。
- Dream 专用循环、JSON lesson 契约、`dream` 认领/租约、`clue` 独立状态和 `dream_pending` 字段。
- `observe` 工具/命令；Dream 与普通任务共用 `remember`、`recall`、`clue_done` 和只读文件工具。

### Security

- `data/config.json` 原子写入并保持 `0600`；安装摘要和 `setup` 输出不回显密钥。
- 可选用环境变量引用凭据，避免把密钥写入配置文件。
- 安装器不修改 shell 启动文件，不注册系统服务，仅在用户明确选择时创建命令链接。

[Unreleased]: https://github.com/ChanX96/aiverywhere/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ChanX96/aiverywhere/releases/tag/v0.1.0
