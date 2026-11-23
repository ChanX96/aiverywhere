# 工具与权限

宿主使用自己的文件、命令、网页、子 agent 和取消机制。技能不假设宿主一定有某一种工具。

## 本地工具

- 文件读取、搜索、局部编辑；
- 写入和命令执行需要用户显式授权；
- 命令超时、退出码和进程组取消是运行时职责；
- 网页搜索/抓取失败时区分限流、网络错误、空正文和内网拒绝；中文查询可先用短关键词，日期/年份可能导致 RSS 召回下降。
- CLI 的 `/grant` 和 `/revoke` 只由用户输入，模型不能给自己授权；`--ask-permissions` 时写文件和命令等待 `/approve` 或 `/deny`。
- `web_search`/`web_fetch` 不需要命令执行权限；`command_exec=false` 只限制 `run_command`，不要因此放弃网页通道。
- 搜索结果是摘要；需要当前事实时继续用 `web_fetch` 打开官方或权威页面，不能只凭摘要下结论。
- CLI 的 `require_memory` 只登记本次必记项；`remember` 才写入。收尾时按 ID/revision 回读，未确认则任务标为 `partial`。
- worker 的工具列表不暴露 `require_memory`、`remember`、`clue_done`、`share_skill` 和 `used_skill`；它只交回记忆候选，由主任务统一提交。

## CLI 可选

需要本地模型循环、流式输出、Web、worker 或外部调度时，用户可以再安装 CLI。CLI 与宿主使用同一实例和同一 memory 文件，不另建记忆库。
