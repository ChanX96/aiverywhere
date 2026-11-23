# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.1] - Unreleased

### Fixed

- Web 旧 supervisor 在新 venv 替换后仍持有失效静态资源，重启后恢复。
- Web 流式文本增加前端字符节流，避免一次跳出整段。
- 思考过程改为浅灰色可读样式，并保留流式期间自动展开。

## [0.3.0] - Unreleased

### Added

- Web 对话支持 Markdown 标题、列表、引用、链接、内联代码和带语言标签/复制按钮的代码块，所有模型文本先转义。
- Web 对话显示模型返回的 thinking/推理文本，可折叠查看，不写回模型上下文。
- Web 对话轮询增量文本，运行时显示流式回答和光标；支持 SSE 的 Messages/OpenAI 适配器均会推送增量。

## [0.2.0] - 2026-11-23

### Added

- 模块化工作流：主 SKILL.md + plan、recall、execute、extract、finish 五个按需模块。
- 项目级 workflow 覆盖目录和 `aiverywhere workflow list/path/show`。
- `require_memory` 必记项登记、写后回读和 `partial` 交付状态。
- worker 记忆写权限在工具层收口，只交回候选。

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
- CLI `chat` 采用单前台回合；TTY 顺序显示 prompt，管道模式保留输入队列；核心壳与 web/微信/调度/MCP/原生执行器等可选适配器边界写入 README 和设计说明。
- 新增 `aiverywhere welcome` 和直接运行 `aiverywhere` 的欢迎终端；显示项目、实例、模型、Agent 修订与记忆状态，TTY 下进入交互。
- 本地工作台新增“对话与工作”：进程内会话、后台任务、状态轮询和工具回执；默认只读，显式开启工作模式后允许写项目文件；界面改为深色科技风对话工作区。
- 增加 `search_files`、`edit_file`、`run_command`、`web_search`、`web_fetch`；新增 `--allow-exec`，网页工具默认可用，命令取消时终止进程组。
- 增加深度 1、最多 2 个的 `delegate` worker；私有工作区、artifact 交接、`accept_artifact`、Seatbelt/bubblewrap 隔离探测和 `/cancel <worker-id>`。
- Messages 适配器支持 SSE 文本流；非 JSON 的 `run`/`chat` 流式显示，Ctrl+C 或 `/cancel` 取消当前任务，JSON 回执保持单份。
- 配置迁到实例根 `config.json`，`skills/` 保留活动 skill，`data/` 保留记忆、session、日志和 artifacts；`init` 迁移旧配置并报告冲突。
- 文档迁到 `docs/guides/` 和 `docs/development/`；root config 加入忽略规则。
- Skill bundle 增加 memory-v1 schema 和纯 POSIX Shell 的 init/validate/write/list/read；仅宿主安装不需要 Python、venv 或 CLI。
- 记忆迁到项目 `.aiverywhere/data/memory/<project_key>/<id>.json`；Python Store 复用 Shell 校验并迁移旧 `state.json` 记忆；`state.json` 只保存计划、任务和渠道回执。
- `install.sh` 默认仅宿主为纯 Shell；`--cli` 才是可选 Python 安装。
- 源码按 `cli/core/integrations/platform/ui` 目录重构，保留 `aiverywhere.cli:main`。
- 修复流式响应中的 provider thinking 块导致下一轮工具请求 HTTP 422：工具循环只保留 text/tool_use 块。
- CLI 交互改为单会话多轮：连续输入共享同一个 Task 历史和 task_id，`/new` 才显式切换会话；修复退出时 `reader` 为 `None` 的回溯。
- `web_search` 对日期/年份重的查询自动补一次短查询并按关键词排序；环境摘要加入 now/timezone/network grant，worker 继承审批。
- 修复 `Tools.execute` 对 `web_search`、`web_fetch`、`run_command` 的分派遗漏；TTY 改为顺序 prompt，任务结束稳定回到 `aiverywhere ›`。
- session 支持持久名称；`aiverywhere chat --resume` 无 ID 时列出最近会话，Web 会话页可重命名。
- 运行日志增加 `data/runs/` 详细 trace（提示词、答复、工具参数/截断结果）和 Web `/` 命令菜单。
- 可靠性修复：旧记忆按项目逐条迁移、共享实例按项目 path key 隔离、完整 skill 随源码/归档/wheel 交付、`jq` 缺失时仍可初始化、默认布局 worker 不递归、Shell/Python 共用校验样本。
- Web 修复导航和运行记录入口，增加 CLI session 历史/恢复展示、Agent bundle 多文件编辑，并明确单项目空间边界。
- 增加 `bridges/` 插件目录、公共 Bridge 抽象类、manifest 自动发现、CLI/Web 状态展示和安装/卸载多种方式。
- 最低 Python 版本提升到 3.11，CI 覆盖 3.11 和 3.14。
- 增加常驻单实例 supervisor、`start/stop/status`、自动 Web、`/api/channels/<id>/messages` 通用入站和回复路由；WeChat/飞书/iMessage 共用 channel envelope。
- 模型协议增加 OpenAI Chat Completions、Ollama 和 custom OpenAI-compatible；setup 支持 protocol/chat_path。
- 环境摘要加入 `now`、`timezone` 和 network grant；worker 继承父任务的逐次审批回调。
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
- 新安装默认使用项目内 `.aiverywhere/`；`~/.aiverywhere` 作为显式共享实例。项目内联链接可反向定位自定义安装根。
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
