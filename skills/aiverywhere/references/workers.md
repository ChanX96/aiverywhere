# 委派 worker

只有 1–2 个真正独立、可并行的子目标时才委派。

- 每个 worker 使用私有工作区；
- worker 不能修改真实项目；
- worker 交回状态、摘要、证据和 artifact（路径、大小、SHA-256）；
- 主任务核验后写入项目；
- 父任务取消应级联取消 worker，单 worker 取消不影响兄弟任务；
- 没有操作系统隔离时，worker 只能使用受限文件工具，不能执行命令；
- 父任务使用 `--ask-permissions` 时，worker 的写入/命令同样走父任务审批，不能绕过。

宿主有自己的子 agent 时，优先使用宿主的机制；CLI 的 `delegate` 只是可选实现。
