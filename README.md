# aiverywhere

**简体中文** | [English](README.en.md)

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host shell](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#安装)
[![CLI Python 3.9+](https://img.shields.io/badge/cli-python%203.9%2B-blue.svg)](pyproject.toml)

**让同一个 agent 在任意宿主和终端里工作。** aiverywhere 把目标、必要的上下文和可用工具交给模型。模型选择怎样行动、是否回忆，以及哪些经验值得保存。宿主只安装 skill 时，记忆由 POSIX Shell 和普通 JSON 文件管理；Python/CLI 只在需要本地模型、Web 或 worker 时选装。

## 核心壳

核心只保留四类东西：一份 `SKILL.md`、一个最小模型/工具循环、一个记忆与线索存储、一个宿主/CLI 入口。`init`、`setup`、`link`、`run`、`chat`、`memory`、`dream` 属于核心；`chat` 每行顺序执行，不维护后台队列。

`web` 工作台、微信网关、`schedule`/`wake` 调度、MCP 和原生执行器都是可选适配器。`wake` 由外部 cron/launchd/systemd timer 调用一次，不常驻，也不注册系统服务；Dream 由宿主在空闲时用自己的模型完成，或由 CLI 执行一次普通任务。

## 一句话安装

仅宿主：macOS 或 Linux、POSIX `sh`；`jq` 可选。可选 CLI：Python 3.9+。在要使用的项目根目录执行：

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

安装了源码时，也可以直接在仓库根目录运行 `./install.sh`。默认只安装宿主 bundle：把 skill 复制到项目内 `.aiverywhere/skills/aiverywhere`，创建 `.aiverywhere/data/memory/`，并把 `.agents/skills/aiverywhere` 链接到标准 skill 目录。这条路径不需要 Python、pip 或 venv。需要命令行时再加 `--cli`。

对任意宿主 agent 说一句话即可：

```text
安装 aiverywhere：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

### 可选：安装 CLI 并配置模型

交互运行会在安装后询问模型端点、凭据、模型名和运行参数：

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
```

无人值守时用环境变量提供模型与凭据，其余参数使用默认值：

```sh
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="你的模型名"
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

也可以安装完成后运行 `aiverywhere setup` 随时修改。完整选项、升级与卸载见[安装指南](docs/guides/install.md)。

## 先验证

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

未把可选 CLI 加入 PATH 时，使用它的安装实例 `venv/bin/aiverywhere`。在宿主会话里给一个可核对的小任务，例如“读取本项目 README，告诉我如何启动工作台，并指出依据”，确认宿主读取的是 `.agents/skills/aiverywhere/SKILL.md` 中的同一份工作约定。

本地工作台：

```sh
aiverywhere web
```

打开终端显示的地址（默认 `http://127.0.0.1:8765/`；TTY 下默认尝试自动打开浏览器，`--no-open` 只打印地址）。“对话与工作”可直接提交任务：默认只读；开启“允许修改项目文件”后，模型才能写入当前项目。会话上下文保留在当前 web 进程内，右侧显示工具回执；重启进程或切换模式会重置上下文。其余页面可查看、创建、编辑和删除项目记忆与技能，修订 agent 文件，按时间浏览只读日志。页面和字体均在本机加载，按 Ctrl+C 关闭。

## 入口和能力

| 入口 | 怎样开始 |
| --- | --- |
| 任意宿主对话或原生子 agent | 读取项目中的 `.agents/skills/aiverywhere/SKILL.md`；需要本地记忆时使用 `.aiverywhere/skills/aiverywhere/scripts/`。沿用宿主的模型、工具和权限。 |
| 独立 CLI | `aiverywhere setup` 后直接运行 `aiverywhere` 显示欢迎屏并进入交互，或用 `aiverywhere run '目标'` / `aiverywhere chat`；写文件加 `--allow-write`，执行命令加 `--allow-exec`。 |
| 定时任务和 Dream | Dream 可由宿主在自己的空闲检查点用当前模型执行；CLI 用 `aiverywhere dream`，定时任务由外部 cron、launchd 或 systemd timer 周期调用 `wake --dream`。 |
| 个人微信 | 由可信网关接入，aiverywhere 负责持久任务、模型答复和回执；见[微信接入指南](docs/guides/wechat.md)。 |
| 本地工作台 | `aiverywhere web`，在浏览器中对话、执行只读或显式授权写文件的任务，并管理记忆、技能与日志；只绑定回环地址。 |

## 工具、worker 与取消

独立 CLI 的裸 Messages 工具包括文件查找、局部编辑、命令执行和网页搜索/读取。`list_files`、`read_file`、`search_files`、`web_search`、`web_fetch` 默认可用；`write_file`、`edit_file` 需要 `--allow-write`，`run_command` 需要 `--allow-exec`。写入和命令都只应作用于当前任务范围，命令进程在取消时会终止整个进程组。

`aiverywhere run` 和 `aiverywhere chat` 默认允许主模型委派最多 2 个、深度 1 层的 worker。worker 使用同一 `Task.run()` 和 `SKILL.md`，但文件工具运行在 `work/<主任务>/<worker>/` 私有副本中；模型只拿到摘要和 artifact，需要写回时调用 `accept_artifact`。命令是否可用取决于系统隔离探测：本机提供 Seatbelt/bubblewrap 且实际可用时才启用，否则 worker 仍能用受限文件工具，但不能执行命令。

非 `--json` 的 `run` 和 `chat` 会流式显示正文；`--json` 仍只输出一份最终回执。交互中 Ctrl+C 取消当前主任务，`/cancel` 取消当前任务，`/cancel <worker-id>` 只取消指定 worker。切换或重开任务不会把旧回答当作新会话依据。

## 宿主记忆（不安装 CLI）

Skill bundle 自带 POSIX Shell：

```sh
sh <skill>/scripts/init-instance.sh
sh <skill>/scripts/write-memory.sh --kind fact --title '标题' --text '正文' --source task-1
sh <skill>/scripts/list-memory.sh --kind clue
sh <skill>/scripts/read-memory.sh <id>
sh <skill>/scripts/validate-memory.sh < record.json
```

记忆是 `data/memory/<project_key>/<id>.json`，格式由 references/memory-v1.schema.json 统一。没有 `jq` 时，宿主可用原生结构化校验；没有 Python 也能使用。CLI 可选安装，但读写同一批文件和同一个 schema。

## 配置

安装 CLI 后，`aiverywhere setup` 写入 `config.json`。空分区表示使用内置默认值。除模型名和凭据外，其余配置都有默认值：

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

凭据可写入 0600 的 `config.json`，也可只保存环境变量名（`api_key_env`、`auth_token_env`），避免密钥落盘。字段、非交互示例、MCP 与微信网关配置见[使用手册](docs/guides/usage.md#统一配置)。

## 文件放在哪里

| 路径 | 用途 |
| --- | --- |
| `<项目>/.aiverywhere/` | 默认项目实例；不需要 Python。 |
| `<项目>/.aiverywhere/skills/aiverywhere/` | 标准 skill bundle：`SKILL.md`、references、Shell 脚本。 |
| `<项目>/.aiverywhere/data/memory/<project_key>/` | 一条记忆一个 JSON 文件。 |
| `<项目>/.aiverywhere/data/logs/` | 按任务保存的日志。 |
| `<项目>/.aiverywhere/data/artifacts/` | worker 或任务产物。 |
| `<项目>/.aiverywhere/state.json` | 计划、任务认领和渠道回执；不保存记忆。 |
| `<项目>/.aiverywhere/config.json` | 可选 CLI 的模型与运行参数。 |
| `<项目>/.aiverywhere/work/` | 可回收的 worker 私有工作区。 |
| `<项目>/.agents/skills/aiverywhere` | 指向标准 skill bundle 的项目链接。 |

用户级共享实例可用 `--home ~/.aiverywhere` 或 `AIVERYWHERE_HOME`。备份整个 `.aiverywhere/` 即可带走记忆、配置和产物。

## 项目结构

```text
.github/                     CI、发布、Issue/PR 模板、Dependabot
docs/guides/                 中英文安装、使用与微信接入指南
docs/development/            设计方案与开发规范
docs/CONTRIBUTING.md         参与方式与验收要求
docs/SECURITY.md             私下报告安全问题的边界
docs/CODE_OF_CONDUCT.md      行为准则
skills/aiverywhere/SKILL.md  随包分发的唯一行为模板
src/aiverywhere/
  cli/                       CLI 组合根与命令入口
  core/                      agent、store、tools、memory、worker
  integrations/              web、wechat、MCP 适配器
  platform/                  environment、sandbox
  ui/                        welcome 与终端展示
tests/                       标准库 unittest 冒烟与配置测试
install.sh                   面向任意宿主的一句话安装器
README.md / README.en.md     中英文项目说明
AGENTS.md                    编码 agent 的开发入口
CHANGELOG.md                 版本变更
Makefile                     安装、测试、检查与构建入口
pyproject.toml               包元数据、依赖、工具配置和 CLI 入口
```

## 开发

```sh
make install
make check
make build
```

也可手动执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

提交前阅读[开发规范](docs/development/development.md)，并按规范附上验收场景、实际结果和待验证项。

## 文档

- [安装指南](docs/guides/install.md)：一句话安装、可选 CLI、升级与卸载。
- [使用手册](docs/guides/usage.md)：配置、入口、记忆、工作台和计划。
- [微信接入](docs/guides/wechat.md)：网关协议、worker、回执、验收与故障排查。
- [设计方案](docs/development/design.md)：架构、同类项目调研与已验证的边界。
- [开发规范](docs/development/development.md)：目录约定、改动归属与验收要求。
- [参与贡献](docs/CONTRIBUTING.md) · [安全策略](docs/SECURITY.md) · [行为准则](docs/CODE_OF_CONDUCT.md) · [更新日志](CHANGELOG.md)
- English: [README](README.en.md) · [Installation](docs/guides/install.en.md) · [Usage](docs/guides/usage.en.md) · [Development](docs/development/development.en.md) · [Contributing](docs/CONTRIBUTING.en.md) · [Security](docs/SECURITY.en.md) · [Code of Conduct](docs/CODE_OF_CONDUCT.en.md)

由 [ChanX96](https://github.com/ChanX96) 发起，按 [MIT 许可证](LICENSE)分发。
