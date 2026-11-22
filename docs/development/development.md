# aiverywhere 项目开发规范

**简体中文** | [English](development.en.md)

**如无必要，勿增实体。** 新增模块、类、依赖、进程或持久文件前，先说明现有结构在哪个具体场景下已不够用。现有函数或工具能清楚完成任务时，直接复用。

本规范适用于修改 aiverywhere 的人和编码 agent。根目录的 `AGENTS.md`、README 和贡献指南都指向本页。产品行为以[设计方案](design.md)中已确认的需求为依据，唯一的[工作约定模板](../../skills/aiverywhere/SKILL.md)随包交付。

## 一项改动从哪里开始

1. **先写完成条件。** 在当前任务说明或改动描述里，用一句话写出入口、输入和预期可观察结果，并指明对应设计章节。例如“机器错过一期周报，首次打开会话时看见一次提醒，该期实际执行次数为零”。
2. **选择归属。** 对话策略、探索和何时回忆由模型依据工作约定或技能决定。操作软件、取网页、生成报表优先复用工具或 MCP。模型协议和渠道差异留在各自的接入代码。Python 内核负责上下文范围、执行、权限与确认、任务状态、调度和恢复。
3. **保持设计与实现一致。** 涉及用户可感知的语义变化，例如默认跨项目共享的内容或漏跑后是否补做，先与用户确定再更新设计。只影响内部组织的改动可直接按规范完成。运行时指导变动更新唯一的技能源文件。
4. **用技能扩展做法。** 新任务能用现有工具取得资料、执行和核验时，用技能描述适用条件与方法。只有缺少真实的读写、协议或一致性保障时才扩展 Python 内核。宿主与 CLI 用同一版本的工作约定和可核实的结果验收。
5. **减少对用户环境的改动。** 新能力先用同一 skill 和已有宿主做一次端到端冒烟。能交回可核验的结果就复用原生路径。默认写入限定在选定实例和用户明确指定的产物，不登记系统服务。通过临时实例验证停用、清理及已有用户配置的保留。
6. **一个任务由一个 agentloop 执行。** 有原生循环就委派，裸模型使用最小的本地协议循环。是否回忆、使用哪项技能、何时改换方法由同一模型决定。调度器按时间和已记录的状态唤醒或提醒。

## Python 包与目录

首版实现采用 PyPA 的 `src` 布局。根目录保留工程元数据、开发入口和说明。可导入的实现集中放在 `src/aiverywhere/`，测试从包的公开入口调用。[PyPA 的 src 布局说明](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

```text
.github/                      CI、发布、Issue/PR 模板和依赖更新
AGENTS.md                     编码 agent 的开发入口
CHANGELOG.md                  版本变更
LICENSE                       许可
Makefile                      安装、测试、检查和构建的固定入口
README.md / README.en.md      中英文项目说明
docs/guides/                  中英文安装、使用与微信接入指南
docs/development/             设计方案与开发规范
docs/CONTRIBUTING.md / .en.md 贡献指南
docs/SECURITY.md / .en.md     安全问题报告
docs/CODE_OF_CONDUCT.md / .en.md 行为准则
install.sh                    纯 Shell 宿主安装；--cli 才准备 Python
skills/aiverywhere/           标准 skill bundle + references + Shell 脚本
.aiverywhere/                 项目本地实例：配置、记忆、日志、产物（不提交）
work/                         worker 私有工作区（可回收）
pyproject.toml                包元数据、构建后端、依赖、工具配置和 CLI 入口
src/aiverywhere/
    cli/                       argparse、命令处理与组合根
    core/                      agent、store、memory、tools、worker、dream
    integrations/web/          本地管理服务、对话和 static 资源
    integrations/wechat.py     微信网关适配
    platform/                  environment、sandbox
    ui/                        欢迎屏与终端主题
    py.typed                  类型标记
tests/test_smoke.py           标准库 unittest 冒烟测试
tests/test_configure.py       配置、链接和安装入口测试
tests/test_dream.py           线索记忆、Dream 普通任务和工具权限测试
tests/test_tools.py            文件搜索/编辑、命令和网页工具测试
tests/test_stream.py           SSE 文本、CLI 流式输出和取消基础测试
tests/test_workers.py          worker 私有工作区、产物交接和权限测试
```

- 在 `pyproject.toml` 用 `[build-system]` 声明构建后端，以 `[project.scripts]` 将 `aiverywhere` 指向 `aiverywhere.cli:main`，版本只维护在 `__init__.py`。命令行、模块启动和宿主委派共用一套任务执行逻辑。[PyPA 的 pyproject.toml 指南](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- CLI 绑定任务和执行器，skill 指导模型行动，调度器负责唤醒、状态和回执。裸模型客户端按协议执行本地工具回合。存储模块不调用模型。用清楚的函数名和边界类型表达输入输出，错误应保留原因、任务或调用标识。新增抽象要有实际调用方。
- 仅宿主路径以 POSIX `sh`、`jq`（可选）和普通 JSON 文件为基线，不需要 Python。可选 CLI 以 Python 3.9+、`venv` 和 `python -m pip` 为基线。模型的 HTTP 客户端及可选 MCP 客户端在 `pyproject.toml` 声明。下载可使用[清华 PyPI 镜像](https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple)。
- 宿主只安装 skill 时使用项目 `.aiverywhere/`；CLI 通过 `.aiverywhere/instance.json`、项目链接或 `--home` 绑定。记忆写入 `data/memory/<project_key>/`，`state.json` 只保留计划、任务和渠道回执。wheel 包含模板、类型标记和页面资源。密钥和业务数据留在实例目录，打包与 CI 样例仅使用合成数据。
- 安装和宿主导入只有一条与产品无关的路径：`install.sh` 的仅宿主分支只用 POSIX Shell 复制 bundle、初始化实例并创建 `.agents/skills/aiverywhere` 目录链接；`--cli` 才建 Python 环境并调用 `setup`。旧文件链接可迁移。
- `config.json` 只包含 `model`、`defaults`、`mcpServers`、`wechat`。模型连接参数和运行预算分别归属两个分区；交互配置必须为除模型名和凭据以外的项提供默认值。凭据不得出现在命令输出或测试日志。
- 核心注释优先解释协议回执、锁、修订、故障恢复和目录边界的原因。新命令同步更新安装或使用指南；用户可感知的行为变化同步更新设计说明。

## 选择与改动相称的验收

| 改到了哪里 | 最少要回答的验收问题 |
| --- | --- |
| 任务循环、模型、宿主或工具 | 从受影响的实际入口能完成同一目标吗？检查任务与工具回执配对、权限继承、取消和部分失败。用可重复的模拟回执覆盖异常；声称支持某真实宿主或端点前，需要该环境的一次真实往返。 |
| 记忆、技能或存储格式 | 用临时安装目录与合成资料验证旧数据可读、不同项目隔离、中文短词找回、无关创作零检索、用户删除后无法召回。改写入路径时复测并发、重试和写入中断。性能结论写明数据规模、冷／热进程、耗时及读写字节。 |
| Dream、计划或渠道 | 用可控制的时钟和可计数的执行器验证。空线索时 Dream 的模型调用为零；一条线索由普通任务处理并写回 fact/skill，完成后线索消失；离线错过的任务只提醒；重复唤醒只认领一期；报告已生成而送达未知时保留可核实的进度。渠道接通以 aiverywhere 的产物和回执为准。 |
| 本地工作台对话 | 通过回环 HTTP 入口提交一次任务，验证会话创建、状态轮询、工具回执和错误返回；默认只读，显式工作模式才允许写。刷新页面或重启进程后明确重置上下文，不把旧回答当作新会话依据。检查前端资源可离线加载，响应不包含凭据。 |
| 工具、流式与 worker | 局部编辑校验旧哈希和唯一片段；命令行返回真实退出码并能终止进程组；网页工具拒绝内网地址、限流和二进制正文可辨。SSE 文本只显示一次，工具参数完整后才执行；Ctrl+C、`/cancel` 和 `/cancel <worker-id>` 分别停止正确范围。worker 只能写私有工作区，产物经 SHA-256 核验后才 `accept_artifact`，无隔离后端时命令不可用。 |
| 包布局、入口或资源 | 在空环境安装构建出的 wheel，切到源码树以外运行 `aiverywhere --help` 和 `python -m aiverywhere --help`，从安装包读取工作约定。记录实测平台；macOS 与 Linux 的调度能力分别验收。 |
| 安装器、配置或链接 | 在临时 `HOME` 分别完成仅宿主和 `--cli` 安装：宿主链接指向活动文件；CLI 命令可用；重复安装保留记忆；自定义安装根可由项目链接恢复；输出不含密钥；`config.json` 权限为 `0600`。另在无 TTY 和交互 TTY 下各验证一次，确认 `curl \| sh` 不会把提示读成脚本正文。 |

## 怎样判定可以交付

从项目根目录执行 `make check`（等价于 `ruff check .`、`sh -n install.sh` 和 `python -m unittest discover -s tests`）。自动化保持为小型冒烟测试，覆盖受影响的真实入口。触及安装时，在临时 `HOME` 运行 `install.sh` 的仅宿主与 `--cli` 路径，并重复安装核对数据保留。触及打包时执行 `make build`，在源码树外用干净环境安装并核对模板、类型标记、页面资源和两个 CLI 入口。[贡献说明](../CONTRIBUTING.md)

作者在交付说明中留下三样东西：**对应的设计行为、实际运行的命令或操作及观察结果、未验证的环境或偏离设计之处**。评审者以受影响的真实入口复核关键用例，失败项修复后重跑。缺少证据的能力保持“待验证”。已有测试命令可直接用于后续 CI；当前约束由仓库入口、改动评审和可复现的验收证据落实。
