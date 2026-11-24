# aiverywhere 开发手册

本手册面向修改 aiverywhere 的开发者、reviewer 和编码 agent。用户安装与使用请看[用户手册](../guides/README.md)。

## 当前基线

- 发布：v0.5.0（alpha）；
- 已验证：macOS arm64、Python 3.14，CI 覆盖 Python 3.11/3.14；
- 自动化：123 项 Python 测试、10 个 CLI/宿主验收场景、Shell 记忆互读/一致性；
- 未验证：真实浏览器桌面/移动、真实 TTY 输入法、真实微信账号、全部 Linux 发行版。

基线数字以当前 `make check` 输出为准，不在文档中重复估算。

## 先读什么

1. [开发规范](development.md)：改动边界、目录、注释、测试和交付要求。
2. [设计方案](design.md)：产品行为、任务生命周期、存储、渠道和验收依据。
3. [十个典型验收场景](acceptance.md)：CLI 与宿主的固定回归矩阵。
4. [工作约定模板](../../skills/aiverywhere/SKILL.md)：宿主和 CLI 共用的行为来源。

## 架构速览

```text
宿主 agent / CLI / Web / channels / scheduler
                      │
                      ▼
             SKILL.md + workflow
                      │
                      ▼
        Task loop + Tools + Worker + Store
                      │
                      ▼
     instance: config / memory / sessions / runs
```

职责：

- `skills/aiverywhere/`：主 skill、五个按需 workflow 模块、Shell 记忆脚本；产品行为入口。
- `src/aiverywhere/cli/`：argparse、命令组合和终端 UI。
- `src/aiverywhere/core/`：Task、Store、memory、tools、worker、迁移和宿主接入。
- `src/aiverywhere/integrations/`：Web、bridge、微信等外部集成。
- `src/aiverywhere/platform/`：环境探测和命令隔离。
- `tests/`：标准库 unittest 冒烟和验收；`tests/shell/` 是纯 Shell 互读验收。

更细的目录和设计原因见[开发规范](development.md#python-包与目录)与[设计方案](design.md)。

## 开发环境

```sh
make install          # 创建 .venv 并安装开发依赖
make check            # ruff + sh -n + unittest + shell 验收
make acceptance       # 十个固定 CLI/宿主验收场景
make build            # sdist + wheel
```

要求：Python 3.11+；宿主路径只用 POSIX `sh`，不要求 Python。

安装或打包改动还要在源码树外验证 clean wheel、仅宿主安装、`--cli`、重复安装和迁移导入。具体验收问题见[开发规范](development.md#选择与改动相称的验收)。

## 代码规范

- **先写完成条件**：入口、输入、预期可观察结果、对应设计章节。
- **如无必要，勿增实体**：能复用已有函数、脚本或字段时不要新增抽象；新增前说明现有结构为什么不够。
- **内核保持轻量**：对话策略和探索优先放 skill；只有读写、权限、状态、恢复等真实约束才进 Python。
- **注释解释原因**：重点说明协议回执、锁、revision、原子写入、取消、恢复和目录边界；不要用注释复述代码。
- **错误可核对**：保留任务/调用标识、失败原因，区分权限、网络、格式、冲突和结果未知。
- **不把秘密写入仓库**：凭据、`.env`、实例数据、日志和用户产物不得提交。
- **文档同步**：新命令更新用户手册；用户可感知行为更新设计；安装/迁移改动更新用户手册和验收。

## 测试规范

- 修复 bug 先补可重复失败或边界测试；不要只扩大断言掩盖问题。
- 新增功能至少覆盖真实入口、失败路径、取消/重试和权限边界之一。
- 记忆、workflow、迁移、宿主接入改动优先使用临时实例和合成数据。
- 声称支持真实宿主、浏览器、微信账号或外部端点前，需要该环境的一次真实往返；否则明确标为待验证。

## 提交前检查

```sh
make check
make acceptance        # 涉及行为、安装、迁移、Web 或 workflow 时
make build             # 涉及打包或发布时
git diff --check
```

同时确认：

- README/用户手册/开发手册中的链接和命令仍有效；
- 新命令有 `--help` 和使用文档；
- 安装器仍覆盖仅宿主与 `--cli`；
- 没有提交凭据、实例数据、构建产物或无关文件；
- 交付说明包含设计行为、实际命令/结果和未验证项。

## 发布

发布遵循[开发规范](development.md)和 [CHANGELOG](../../CHANGELOG.md)。tag 只在合并后的 main 上创建；Release 工作流从 tag 构建 wheel/sdist 并上传。发布前必须通过 main CI、`make check`、验收和干净 wheel 验证。

## 贡献与安全

- [贡献指南](../CONTRIBUTING.md)
- [安全策略](../SECURITY.md)
- [行为准则](../CODE_OF_CONDUCT.md)
