# 使用 aiverywhere

**简体中文** | [English](usage.en.md)

只使用宿主入口时不需要执行 CLI 命令，直接读取 `.agents/skills/aiverywhere/SKILL.md` 并使用同目录 `scripts/`。`aiverywhere` 仅指可选 CLI；未加入 PATH 时使用其安装实例的 `venv/bin/aiverywhere`。宿主和 CLI 共享同一个 `.aiverywhere/` 实例。

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

## 统一配置

`init` 在安装根创建唯一配置 `config.json`。`setup` 写入模型与运行参数，保留 `mcpServers` 和 `wechat`；未知分区一律报错。

```sh
aiverywhere setup
export ANTHROPIC_API_KEY="..."
aiverywhere setup --no-input --model "实际模型名" --api-key-env ANTHROPIC_API_KEY
```

交互向导会询问：模型服务（官方或自定义兼容端点）、凭据方式、模型名、单次输出 token、是否调整运行参数，以及工具回合、超时和端口。除模型名和凭据外均可直接回车使用默认值。

```json
{
  "model": {
    "model": "实际模型名",
    "base_url": "https://api.anthropic.com",
    "max_tokens": 4096
  },
  "defaults": {
    "max_turns": 12,
    "timeout": 180,
    "port": 8765
  },
  "mcpServers": {},
  "wechat": {}
}
```

### 模型

空 `model` 分区会读取进程环境中的 `AIVERYWHERE_MODEL`（或 `ANTHROPIC_MODEL`）、`ANTHROPIC_BASE_URL`、`ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`。非空分区以自己的字段为准；缺失的凭据不会自动混用环境变量，除非显式使用 `api_key_env` 或 `auth_token_env`。每次调用仍可用 `--model` 指定模型名。

| 字段 | 约定 |
| --- | --- |
| `model` | 必填。实际模型名。 |
| `base_url` | Messages 兼容端点，默认 `https://api.anthropic.com`。 |
| `max_tokens` | 单次模型请求的最大输出 token，默认 `4096`。 |
| `api_key` | 作为 `x-api-key` 发送。 |
| `auth_token` | 作为 `Authorization: Bearer` 发送。 |
| `api_key_env` | 运行时从该环境变量读取 `x-api-key`；不把密钥写入配置文件。 |
| `auth_token_env` | 运行时从该环境变量读取 Bearer 凭据。 |

`api_key`、`auth_token`、`api_key_env`、`auth_token_env` 只能选择一种。官方端点没有可用凭据时会在发起请求前明确报错。`config.json` 以 `0600` 写入，仍建议不要提交、截图或转发 `config.json` 或整个 `data/`。

**原生执行器。** 已有可独立运行的宿主命令时，可将 `model` 换成分区：

```json
{
  "model": {
    "project": "/绝对路径/任务项目",
    "command": ["/绝对路径/宿主命令", "实际的非交互参数"],
    "pass_env": ["需要的环境变量"]
  }
}
```

命令在指定项目运行，从标准输入接收 JSON（`instructions`、`messages` 等），成功时把最终正文写到标准输出。它绑定当前 `project`，模型由该命令选择；本次带有本地工具授权时，应使用 Messages 模式或在原生宿主中授予权限。

### 运行参数

`defaults` 为空时使用内置值；只写要覆盖的键即可。CLI 的单次参数优先于配置。

| 键 | 默认 | 作用 | 单次覆盖 |
| --- | --- | --- | --- |
| `max_turns` | 12 | 裸 Messages 的工具回合上限 | `--max-turns` |
| `timeout` | 180 | 每个任务的总秒数 | `--timeout` |
| `port` | 8765 | 本地工作台端口，`0` 表示自动分配 | `web --port` |

定时任务和微信任务未单独写 `timeout`、`max_turns` 时沿用这些默认值。修改配置后，正在执行的调用维持原绑定；新任务、计划和 Dream 重新读取。

### MCP

裸模型需要使用本地 stdio 服务时，在 Python 3.10+ 的虚拟环境安装可选依赖。源码环境可安装 `.[mcp]` 额外依赖；已经安装的实例直接补齐依赖：

```sh
~/.aiverywhere/venv/bin/python -m pip install 'mcp>=1.20,<2'
```

例如已有 `office-tools` 命令：

```json
{
  "mcpServers": {
    "office": {"command": "office-tools", "args": [], "allowedTools": ["lookup"]}
  }
}
```

再用 `aiverywhere run --mcp office '用 office 查询资料'` 单次授权。服务在发现工具时启动，任务结束后关闭。

### 个人微信网关

由可信网关完成账号配对并验证来信。在 `wechat` 分区绑定一个项目、账号与会话；回执查询和幂等发送按网关实际能力填写。`timeout`、`max_turns` 可覆盖实例默认值。

```json
{
  "project": "/绝对路径/任务项目",
  "account": "demo",
  "conversation": "chat-1",
  "url": "http://127.0.0.1:8787",
  "idempotent_send": true,
  "receipt_lookup": true
}
```

实例配置可能含有密钥，由安装者在本机编辑。旧版的 `data/config.json`、`data/model.json`、`data/mcp.json` 与 `data/wechat.json` 在首次初始化时导入或迁移，后续统一配置位于实例根 `config.json`。旧 wheel 曾把资料保存在独立虚拟环境的用户，可先停止旧实例写入，核对目标目录，将原有 `data/` 复制到新安装根，有自定义 agent 时将其保存为新项目的 `data/SKILL.md`，再运行 `init`。保留旧实例直至核对完成。

## 环境、对话和委派

```sh
aiverywhere env
AIVERYWHERE_HOST=my-host aiverywhere env
aiverywhere --project . run --json '读 README，告诉我这个项目怎样运行。'
aiverywhere
aiverywhere chat
```

直接运行 `aiverywhere` 会显示项目、实例、模型、Agent 修订和记忆状态；在 TTY 中随后进入交互，非 TTY 只打印欢迎屏后退出。`env` 显示平台、解释器、任务目录、已确认的授权和仍待验证的能力。宿主可设置 `AIVERYWHERE_HOST` 或传 `--host`；两者都省略时只记录已知标记，不推断身份。`--home` 绑定数据所在的安装根，`--project` 绑定任务目录，两个全局参数均放在子命令前。

安装器默认使用 `~/.aiverywhere`。在已创建技能链接的项目中，命令会通过链接定位自定义安装根；其他目录用 `--home` 或 `AIVERYWHERE_HOME` 指定。希望某个项目使用独立实例时，执行 `aiverywhere --home <项目> init`，再用同一 `--home` 运行 `link`，避免与用户级实例混用。

每项任务只有一个 agentloop。宿主运行自己的循环，可把目标委派给原生子 agent。独立 CLI 可调已配置的原生命令，只有直接连接 Messages 端点时才运行本项目的最小工具循环。交互模式一次推进一个前台任务；运行中输入 `/cancel` 取消当前任务，`/cancel <worker-id>` 只取消指定 worker，`/jobs` 查看状态，`/ask ID 内容` 追问。

```sh
printf '%s\n' '读 README，返回启动命令和依据。' |
  aiverywhere --project . run --json --task-id readme-1 -
```

同一项目内重试同一请求 ID 可取回原任务回执。裸模型的文件工具默认只读，`--allow-write` 允许写任务文件，`--allow-exec` 允许在项目内执行命令，修订 agent 则需单独授权 `--allow-agent-edit <旧修订号>`。

### 工具、worker 与取消

文件工具包括 `list_files`、`read_file`、`search_files`、`write_file` 和 `edit_file`。`write_file`/`edit_file` 需要 `--allow-write`；`edit_file` 用读取到的 SHA-256 和唯一匹配片段，冲突时拒绝覆盖。`run_command(argv, cwd, timeout)` 需要 `--allow-exec`，返回退出码、限长输出和超时标记；取消时会终止进程组。`web_search` 使用免 Key 的 Bing RSS，失败时回退 DuckDuckGo HTML，`web_fetch` 只读取公开文本页面，拒绝内网和保留地址。

`run`/`chat` 的主任务可以调用 `delegate(tasks)`，默认最多 2 个、深度 1 层的 worker。每个 worker 在安装根的 `work/<主任务>/<worker>/` 私有副本中运行，使用同一个 `Task.run()`、`SKILL.md` 和记忆项目；它不能改真实项目。worker 交回摘要和 artifact（路径、大小、SHA-256），主任务核验后调用 `accept_artifact` 写入授权目标。命令隔离通过实际探测 Seatbelt 或 bubblewrap 决定；不可用时 worker 只能使用受限文件工具。

交互式 TTY 中输入 `/` 会显示命令补全菜单：`/help`、`/jobs`、`/cancel`、`/ask`、`/quit`。

非 JSON 的交互和一次性运行会流式显示正文；`--json` 保持一份最终回执。Ctrl+C 取消当前主任务，`/cancel` 取消当前任务，`/cancel <worker-id>` 只取消指定 worker。已完成产物仍可查；外部操作结果未知时保留待核对状态。

## 记忆、技能和本地工作台

宿主不安装 CLI 时，使用 skill bundle 自带的 Shell：

```sh
sh <skill>/scripts/init-instance.sh
sh <skill>/scripts/write-memory.sh --kind fact --title '月报' --text '在副本中编辑。' --source task-1
sh <skill>/scripts/list-memory.sh --kind clue
sh <skill>/scripts/read-memory.sh <id>
sh <skill>/scripts/validate-memory.sh < record.json
```

记忆是 `<实例>/data/memory/<project_key>/<id>.json`，默认实例在项目 `.aiverywhere/`。`state.json` 只保留计划、任务认领和渠道回执。CLI 可选安装，但读写同一批文件。

可选 CLI：

```sh
aiverywhere memory put '月报' '在副本中编辑，完成后核对公式位置。'
aiverywhere memory search '月报'
aiverywhere memory search --kind skill --cold '公式'
aiverywhere memory put --kind clue '线索：公式位置' '数量正确，但公式位置错误。'
aiverywhere memory search --kind clue
aiverywhere memory forget <线索ID>
aiverywhere skill --info
aiverywhere link --dir .agents/skills/aiverywhere
aiverywhere web
```

`kind=clue` 是待处理线索，和 fact/skill 使用同一份记忆、锁与修订号；默认的事实/技能检索不会返回它，也不受 90 天冷过滤。处理完用 `memory forget` 删除线索。

`link` 创建指向活动 skill 目录的符号链接，重复运行保持幂等；旧的文件链接可迁移，指向其他位置的外来链接拒绝覆盖。

工作台的“对话与工作”把任务提交给当前实例，默认只读；只有开启“允许修改项目文件”后模型才能写入当前项目。会话保存在当前 web 进程内，切换模式或重启进程会重置上下文，右侧列出本轮工具回执。模型未配置时，页面会报告错误，不会静默降级。

在工作台的“记忆与技能”中按标题查找，点标题查看或修改，删除前可取消。“Agent 定义”修改实例共用的工作约定。停留在工作台时，外部编辑通常在 3 秒内出现。页面保留正在输入的草稿，旧版本保存时会报告冲突。删除本地定义可回到发行模板，`skill --info` 可重新生成供宿主读取的活动文件。

长时间工作的裸模型 CLI 在每次向模型发送请求前读取当前 agent。交互 CLI 的新任务和追问开始时重新读取执行器配置。原生宿主在工作约定指定的检查点重读，单次已发出的命令沿用它收到的输入。记忆和技能按需取当前修订。[运行中如何感知更新](../development/design.md#运行中的文件变更)

“运行日志”按时间从新到旧展示当前项目的任务，可加载更早记录。日志只读。工作台绑定 `127.0.0.1`，只接受本机同源请求并校验页面令牌；前端资源随包分发，全程可离线使用。`--port 0` 可选取空闲端口。`aiverywhere web` 在 TTY 桌面环境默认尝试打开浏览器；`--no-open` 只打印地址。

模型按本次任务需要取回少量记忆。要逐次确认跨项目使用已验证技能，可设 `aiverywhere memory policy ask`，用户同意后用单次全局参数 `--confirm-shared`。普通项目事实留在其来源项目。

## 空闲 Dream

Dream 是普通任务，不是专用循环。没有新的用户任务时，宿主用自己的模型先执行 `aiverywhere memory search --kind clue`；没有线索就直接结束，不调用模型。有线索时按 [工作约定中的空闲 Dream](../../skills/aiverywhere/SKILL.md) 问答清单核实，证据足够才写 fact/skill 并用 `memory forget` 标记，证据不足就保留线索。

独立 CLI 可运行 `aiverywhere dream`，它使用同一执行器和同一提示词；未配置执行器时会失败并保留线索。外部调度器可调用 `wake --dream`。Dream 没有专用 JSON 输出、租约或状态，重复触发可能重复思考，但锁和修订号保证数据一致。`dream --note` 是 `memory put --kind clue` 的兼容别名。

## 定时任务和唤醒

```sh
aiverywhere schedule add '整理本周进展。' --at 2026-12-07T09:00 --timezone Asia/Shanghai --repeat weekly
aiverywhere wake --dream
```

把示例日期替换为期望的首次运行日期。aiverywhere 不登记常驻进程或系统服务；由现有 cron、launchd、systemd timer 或其他进程管理器周期调用一次性 `wake`。每次调用会顺序处理到期计划、一个微信任务，并在 `--dream` 且存在线索时执行一次普通 Dream。调用越频繁，微信响应越及时；调度器本身负责进程存活和重试。

机器关机或休眠错过的任务会在之后的 `run`、`chat` 或 `schedule notices` 提醒一次，是否补做由用户决定。用 `schedule results` 查看执行结果。外部调度器需要能读取安装根的 `data/`，并使用已配置的模型/原生执行器。
## 微信接入和交付

个人微信通过可信网关接入；aiverywhere 不直接登录微信。配置、入站/出站协议、worker、回执、验收和故障排查见[微信接入指南](wechat.md)。
