# 运行时与实例绑定

## 绑定顺序

1. 显式 `--home` 或 `AIVERYWHERE_HOME`；
2. 项目内 `.aiverywhere/instance.json`；
3. 源码 checkout 或 wheel 自带的活动 skill；
4. 用户级 `~/.aiverywhere/`；
5. 首次持久化时创建项目内 `.aiverywhere/`。

项目内实例是默认形态。它不需要 Python，不依赖全局命令，同一项目的不同宿主会看到同一份数据。

## `instance.json`

```json
{
  "schema_version": 1,
  "project_key": "default",
  "project_root": "/absolute/project/path",
  "instance_root": "/absolute/project/path/.aiverywhere"
}
```

项目键由初始化方写入，宿主不要自行用路径哈希猜测。

## 能力发现

先看当前环境：

- 有文件读写：可以读取和写入 memory JSON；
- 有 `sh`：可以运行 `scripts/`；
- 有 `jq`：可以做完整格式校验；
- 有命令执行：可以调用可选 CLI；
- 有网络：可以查公开资料；
- 有子 agent/取消机制：可以委派和停止。

缺少能力时直接说明并选择更小的路径，不要假装拥有。

## 宿主与 CLI

宿主拥有自己的循环时，使用宿主模型和工具；CLI 只是在需要本地模型、Web、worker 或调度时安装的另一个入口。两者读写同一套记忆文件。

CLI 的交互 session 属于可选入口，写在 `data/sessions/<project_key>/`，带锁、事件序号和恢复语义；宿主不需要读取或伪造这些文件。写文件、执行命令和联网由 CLI 的 session 授权控制，退出即失效。
