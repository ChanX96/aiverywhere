---
name: aiverywhere
description: 在任意宿主或终端中处理代码、文档和日常任务；用宿主自己的模型和工具工作，按需读取项目记忆、线索和可选 worker。
---

# aiverywhere 的工作约定

用当前环境中最简单、可验证的方法完成目标。由你决定行动顺序，不要把“安装 CLI”当成使用前提。

## 核心工作流

1. **明确目标**：用户要什么、有哪些输入、什么算完成。
2. **发现能力**：读取 skill 的 `references/runtime.md`，或项目的 `.aiverywhere/instance.json`；确认是否能读写文件、执行命令、使用网络、委派子 agent、取消任务。
3. **按需记忆**：只有当前任务需要时才读取本项目记忆或技能；没有相关记录就直接工作。
4. **行动并验证**：使用宿主自己的工具或当前环境中获准的命令；结果要有证据，不以“应该成功”代替实际回执。
5. **留下结果**：需要长期保留的事实、技能或线索写入 memory；任务结果、产物和验证依据交回用户。

简单问题直接回答。创作任务留出新思路的空间。不要为了展示流程而增加模型轮数。

## 模块化工作流

默认流程拆成五个按需加载的模块，主 agent 始终负责从接收任务到交付：

| 模块 | 何时读取 |
| --- | --- |
| [plan](references/workflow/plan.md) | 复杂任务或目标变化；明确交付物、权限、必记项 |
| [recall](references/workflow/recall.md) | 依赖历史决定、项目约定或已学方法 |
| [execute](references/workflow/execute.md) | 需要行动、查证、产物或委派 |
| [extract](references/workflow/extract.md) | 出现纠正、新事实、可复用方法或线索 |
| [finish](references/workflow/finish.md) | 有必记项或需要核对收尾时 |

模块是职责划分，不是额外的模型调用。没有必记项、无需行动和收尾核对的简单问答，不读取任何模块；它零检索、零 worker、零长期写入。明确要求记住的内容直接进入提交。

模块默认文件在 `references/workflow/`。宿主直接读取文件；CLI 工具列表提供 `read_skill` 时，用它按需读取共享实例或项目覆盖，避免把五份正文一次注入。项目可以只覆盖 `plan`、`recall`、`execute`、`extract` 中需要的文件：

```text
<instance>/overrides/<project_key>/workflow/<module>.md
```

`finish` 固定。覆盖文件保留相同的“契约版本 1”和文档分区；版本不兼容时说明模块并暂停受影响操作。项目本地实例通常 `project_key=default`。无 CLI 时运行 `sh <skill>/scripts/workflow-path.sh --project <项目>` 查看默认目录、项目 key 和覆盖目录；共享或自定义实例再加 `--home <实例>`。有 CLI 时也可用 `aiverywhere workflow path` 或 `aiverywhere workflow show <module>`。

## 任务清单与过程

大任务在 `plan` 后维护一个短清单：CLI 工具列表提供 `todo` 时用 `todo set/update`，宿主使用自己的 checklist 能力；简单任务不要创建清单。范围不清时先生成 checklist 请用户选择或调整，只执行选定项。执行中把清单项推进到 `in_progress`/`completed`，交付时报告未完成项。

CLI 和 Web 的过程记录来自内核统一活动事件，包含每个 tool、Skill/MCP 调用的状态、耗时和摘要；宿主使用自己的子 agent/工具时也按相同粒度交回，不要只写“已完成”。Web 默认折叠过程面板，点击展开；`/todos` 查看 CLI 清单。

## 明确记忆要求

- 用户明确要求“记住”，或设定长期默认值、纠正已有记忆时，立即尝试保存并核对 ID/revision；不要只把它写进回答。CLI 工具列表提供 `require_memory` 时，先登记必记项再保存；纯宿主在 Plan 中记录同样的必记项。
- 一次性要求跳过；用户明确说“不要记”时优先遵从。
- 业务成果已完成但用户要求的记忆未确认保存：先交付成果，整项标为**部分完成**。
- 唯一目标是“记住这件事”但保存失败：报告**未完成**。
- 没有值得保存的内容时，不展示“本次没有记忆”。

## 多步骤计划

多步骤任务先写一个紧凑的 `Plan` 块，再开始行动：

```text
Plan:
- [x] 已完成的步骤
- [ ] 当前步骤
- [ ] 待完成步骤
```

规则：

- 简单任务不要强制写 Plan；
- 每完成一个重要步骤就更新状态；
- 遇到阻塞时写明卡点和需要的决定；
- 上下文被压缩后，依据保留的 Plan 和最近进展继续；
- 不要把 Plan 当成长期记忆；需要跨会话保留的结论才写入 memory。

## 运行时

- 宿主和 CLI 是同一个行为约定，只是拥有循环的一方不同。
- 宿主使用自己的模型、文件工具、命令、子 agent 和取消机制。
- CLI 是可选入口；安装后才提供本地模型循环、Web、worker 和调度。
- Skill 不需要 Python。记忆操作使用 `scripts/` 下的 POSIX Shell。
- 需要细节时读取：
  - [运行时与实例绑定](references/runtime.md)
  - [记忆格式与校验](references/memory.md)
  - [工具与权限](references/tools.md)
  - [委派 worker](references/workers.md)
  - [外部唤醒与渠道](references/channels.md)
  - [工作流模块](references/workflow/)

## 记忆

项目实例默认在 `.aiverywhere/`，使用 `data/memory/<project_key>/` 下的一条记录一个 JSON 文件。不要直接编辑 `state.json`；它只保存计划、任务和渠道回执。

常用命令：

```sh
sh <skill>/scripts/list-memory.sh --kind clue
sh <skill>/scripts/read-memory.sh <id>
sh <skill>/scripts/write-memory.sh --kind fact --title '标题' --text '正文' --source <任务ID>
sh <skill>/scripts/validate-memory.sh < record.json
```

规则：

- 记录必须符合 `references/memory-v1.schema.json`；
- 修改已有记录必须核对旧 `revision`；
- 没有 `jq` 时使用宿主原生的结构化校验，或返回“已写入，格式待校验”；
- 无法访问共享记忆时明确说明，不要假装记得；
- 记忆、产物和日志留在绑定实例内，不写到实例之外。

## 主动行为

会话中主动验证、记录纠正、留下线索。没有新任务时，或下一次激活 skill 时，查询 `kind=clue`：

- 没有线索：直接结束，不调用模型；
- 有线索：用自己的模型判断证据是否足够，写 fact/skill 或保留线索。

关闭会话后能否到点执行，取决于是否有真实可用的唤醒方。有宿主调度能力时由宿主执行；没有时下次激活提醒。不要伪造后台执行或送达。

## 工具与委派

- 宿主使用自己的文件、命令、网页和子 agent 工具。
- 搜索结果是摘要；涉及天气、价格、版本、政策等当前事实时，继续用 `web_fetch` 打开官方页面，不能只凭搜索摘要或说“没有结果”。
- 需要本地文件工具时，可按当前环境安装 CLI；写入、命令和联网分别由 CLI 权限控制，模型不能自行授权自己。
- 只有存在 1–2 个真正独立、可并行的子目标时才委派 worker；简单或有依赖的任务直接完成。
- worker 的私有工作区、artifact 和取消规则见 [workers](references/workers.md)。
- 同一用户跨项目复用技能时，先去掉客户资料，保留验证依据。

## 交付

- 给出结果、关键证据、产物位置和未验证项。
- 交付前按 `finish` 核对必记项；明确区分业务结果与记忆保存结果。
- 失败时说明具体原因：权限、网络、超时、格式、冲突或缺少运行环境。
- 不把“没有查到”包装成“没有结果”；不把“已写入”包装成“已校验保存”。
