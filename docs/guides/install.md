# 安装 aiverywhere

**简体中文** | [English](install.en.md)

仅宿主安装适用于 macOS 或 Linux、POSIX `sh`；`jq` 可选。可选 CLI 需要 Python 3.9+。安装不区分宿主产品：任意能读文件、能执行命令的 agent 使用同一份指南。用户给出下面一句话即可：

```text
安装 aiverywhere：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

## 选择安装方式

### A. 让 agent 只安装 skill（推荐给宿主）

把下面一句话交给 agent：

```text
安装 aiverywhere skill：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

它只需要 POSIX `sh`，不需要 Python 或 CLI。

### B. 让 agent 安装 skill + CLI

```text
安装 aiverywhere CLI：curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

需要 Python 3.9+；模型配置可通过环境变量传入。

### C. 手动安装 skill

```sh
cp -R skills/aiverywhere <项目>/.aiverywhere/skills/aiverywhere
sh <项目>/.aiverywhere/skills/aiverywhere/scripts/init-instance.sh <项目>
ln -s <项目>/.aiverywhere/skills/aiverywhere <项目>/.agents/skills/aiverywhere
```

### D. 手动安装 CLI

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/aiverywhere init
.venv/bin/aiverywhere setup
.venv/bin/aiverywhere link
```

### E. Bridge 插件

项目或实例的 `bridges/` 目录用于可选常驻 bridge：

```text
<项目>/bridges/<bridge-id>/bridge.json
<实例>/bridges/<bridge-id>/bridge.json
```

模板和抽象类见 [bridges/README.md](../../bridges/README.md)。CLI 和 Web 只读取 manifest 和健康状态，不导入或执行 bridge 代码。

## 1. 一句话安装

在要使用的**项目根目录**执行：

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

已有源码检出时，直接在仓库根目录运行 `./install.sh`，安装器会自动使用本地源码，不需要先推送 GitHub。
以下命令按 `ChanX96/aiverywhere` 的 `main` 分支编写。fork 或镜像需要替换脚本 URL，并可用 `AIVERYWHERE_REPO`、`AIVERYWHERE_REF` 指定安装器内部获取源码的位置。

默认安装器只做宿主 bundle：

1. 把 `skills/aiverywhere/` 复制到 `<项目>/.aiverywhere/skills/aiverywhere/`。
2. 创建 `.aiverywhere/data/memory/`、`instance.json` 和项目 skill 链接。
3. 不调用 Python、不创建 venv、不要求模型 Key。
4. `--cli` 才额外安装 Python 环境、命令和模型配置。

安装完成后，宿主 agent 读取：

```text
<项目>/.agents/skills/aiverywhere/SKILL.md
```

需要记忆时使用同一目录下的 `scripts/`；不需要 Python。用户级共享实例可用 `--home ~/.aiverywhere`。

### 常用选项

```sh
# 可选 CLI 和交互式模型配置
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli

# 无交互：只安装宿主运行时
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --yes

# 无交互：安装 CLI，模型和凭据来自环境变量
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="你的模型名"
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

| 选项 | 作用 |
| --- | --- |
| `--cli` / `--no-cli` | 是否把命令链接到命令目录并配置模型；默认交互询问，非交互默认不安装 CLI。 |
| `--yes`、`--no-input` | 不提问；宿主安装；需要 CLI 时要求模型环境变量。 |
| `--home DIR` | 实例根，默认 `<项目>/.aiverywhere`。 |
| `--project DIR` | 创建技能链接的项目，默认当前目录。 |
| `--source TARGET` | pip 安装源：本地目录、wheel 或包名，适合离线和已核对的版本。 |
| `--ref REF` | 从 GitHub 获取的分支或标签，默认 `main`。 |
| `--bin-dir DIR` | 命令链接目录，默认 `~/.local/bin`。 |
| `--no-link` | 不创建项目技能链接。 |
| `--dry-run` | 只打印将执行的命令。 |

`PIP_INDEX_URL` 会传给 pip。例如：

```sh
export PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

## 2. 宿主接入

安装器已经把活动文件链接到项目。任何宿主按自己的能力选择一种方式：

- 支持项目级技能目录的宿主，读取 `.agents/skills/aiverywhere/SKILL.md`。
- 只支持显式文件读取的宿主，读取 `<项目>/.agents/skills/aiverywhere/SKILL.md`；安装 CLI 后可用 `aiverywhere skill --info` 核对 `path` 和修订号。
- 在宿主会话里给一个可核对的小任务，例如“读取本项目 README，告诉我如何启动工作台，并指出依据”。

这个入口只使用宿主自己的模型、工具和授权；Python 只在调用记忆、环境或工作台等本地命令时运行。宿主名称可省略；需要补充本地事实且已安装 CLI 时，可用 `aiverywhere --project <目录> env`，或设置 `AIVERYWHERE_HOST=<宿主名>`。

## 3. 可选 CLI

需要独立终端或计划任务时安装 CLI；宿主也可以在自己的空闲检查点完成 Dream，无需安装 CLI。

```sh
aiverywhere setup
```

交互向导依次询问模型服务、凭据方式、模型名、单次输出 token，以及工具回合、超时和端口。除模型名和凭据外均可直接回车使用默认值。配置写入实例根 `config.json`（默认 `<项目>/.aiverywhere/config.json`），文件权限为 `0600`。

非交互示例：

```sh
export ANTHROPIC_API_KEY="..."
aiverywhere setup --no-input \
  --model "你的模型名" \
  --base-url "https://api.anthropic.com" \
  --max-tokens 4096 \
  --max-turns 12 \
  --timeout 180 \
  --port 8765
```

也可以不把密钥写入配置，只保存环境变量名：

```sh
aiverywhere setup --no-input --model "你的模型名" --api-key-env ANTHROPIC_API_KEY
```

凭据优先级和所有字段见[使用手册](usage.md#统一配置)。运行一次真实任务：

```sh
aiverywhere run --json '读 README，告诉我怎样启动工作台。'
```

核对回执中的 `status` 为 `completed`，`answer` 能回答任务。直接运行 `aiverywhere` 会显示欢迎屏并进入交互；宿主入口和本地工作台不依赖模型配置。

## 4. 打开本地工作台

```sh
aiverywhere web
```

打开打印的地址。`aiverywhere web` 会确保常驻 supervisor 并提供地址，不会阻塞终端；端口占用时会选择空闲端口，也可用 `--port` 指定。停止用 `aiverywhere stop`。工作台无需模型和网络账号。

## 5. 升级、迁移与卸载

**升级**：用相同的 `--home` 和 `--project` 重新运行安装器。它复用现有虚拟环境和 `data/`，`init` 保留已有活动 agent、记忆、技能、计划和日志。升级前可停止写入并备份 `config.json` 和 `data/`。

**迁移**：停止写入，复制整个 `.aiverywhere/` 到目标安装根，再在新位置运行：

```sh
aiverywhere --home <新安装根> --project <项目> init
```

**卸载**：先停止 supervisor，再确认要删除的实例根。`.aiverywhere/` 包含配置、记忆、session、日志和产物，删除后不可恢复。

```sh
aiverywhere stop
# 如果使用项目实例：
rm -f <项目>/.agents/skills/aiverywhere
rm -rf <项目>/.aiverywhere
# 如果使用用户级实例：
rm -f ~/.local/bin/aiverywhere
rm -rf ~/.aiverywhere
```

只卸载 CLI、保留记忆和配置时，不要删除 `~/.aiverywhere/config.json`、`data/` 或 `skills/`。桥接器和平台登录由 bridge 自己管理；卸载 aiverywhere 不会删除 bridge 的账号数据。

## 故障排查

- **找不到 Python 3.9+**：只有安装可选 CLI 时才需要；可安装 `python3`，或设置 `AIVERYWHERE_PYTHON=/path/to/python3`。
- **无法创建虚拟环境**：Debian/Ubuntu 安装 `python3-venv`；或使用已有 Python 的 `-m venv` 能力。
- **pip 下载慢**：设置 `PIP_INDEX_URL` 使用镜像。
- **`aiverywhere: command not found`**：把 `~/.local/bin` 加入 PATH，或使用 CLI 实例的 `venv/bin/aiverywhere`；也可重新运行安装器并加 `--cli`。
- **项目技能链接已存在**：安装器不会覆盖指向其他位置的链接。先核对 `<项目>/.agents/skills/aiverywhere/SKILL.md`，再决定保留或删除。
- **自定义安装根后在别的项目找不到实例**：在已链接的项目中运行可自动定位；其他目录设置 `AIVERYWHERE_HOME=<安装根>`。

安装器不请求 `sudo`、不修改 shell 启动文件、不注册系统服务。安全边界见[安全策略](../SECURITY.md)。
