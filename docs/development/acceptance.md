# 十个典型验收场景

> [开发手册](README.md) · 验收


这十个场景是工作流、记忆和宿主/CLI 交接的固定回归基线。自动化入口：

```sh
make acceptance
# 或
.venv/bin/python -m unittest tests.test_acceptance_matrix -v
```

`make check` 也会执行同一组测试。测试中的“宿主模式”使用安装后的 POSIX Shell bundle，不启动 Python 或 CLI；“CLI 模式”使用当前源码的 `python -m aiverywhere` 或同一个核心 `Task`。

| # | 场景 | CLI/核心断言 | 宿主断言 |
| --- | --- | --- | --- |
| 1 | 干净安装与工作流发现 | `workflow list` 返回五模块 | 仅宿主安装、链接、五模块和 `workflow-path.sh` |
| 2 | 显式项目事实 | `memory put/get` 回读 fact | `write-memory/read-memory` 回读同一事实 |
| 3 | 一次性要求或不要记 | 简单任务零新增记忆 | 宿主零新增记忆 |
| 4 | 纠正旧事实与修订冲突 | `--id/--revision` 更新，旧修订拒绝 | Shell 同 ID 更新，旧修订拒绝 |
| 5 | 记忆失败不得报完成 | 必记项未确认 → `partial` | 写入锁/失败后旧记录保留，错误明确 |
| 6 | 项目覆盖与升级保留 | 覆盖生效、版本不兼容拒绝 | 覆盖保留，路径由宿主脚本解析 |
| 7 | 简单任务零额外路径 | 一次模型回合、零 trace/worker/记忆写入 | 安装后零记忆/日志产物 |
| 8 | 新进程与项目隔离 | 新进程读回，其他项目不可见 | 新 Shell 读回，路径按项目 key 隔离 |
| 9 | worker 写权限 | worker 工具不暴露记忆写入，调用被拒绝 | 宿主无 worker 运行时，保持零写基线 |
| 10 | 产物、记忆和回执 | 产物文件 + fact + 回读 + `completed` | 文件 + fact + 回读，失败时明确 partial |

## 不在自动化里伪造的部分

- 宿主模型是否主动读取某个模块、是否在最终答复中如实说明 partial，属于宿主模型行为；由 `host-acceptance` subagent 在真实宿主工作流中验收，不能用文件测试冒充。
- `require_memory` 只能登记模型已经识别出的必记项；自然语言理解不由测试替代。
- `partial` 的 Web 展示和 CLI 结果在现有 Web/session 测试中覆盖，宿主没有可拦截的结束事件，只能按 SKILL 约定交付。
