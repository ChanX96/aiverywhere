# 参与 aiverywhere

**简体中文** | [English](CONTRIBUTING.en.md)

先读[开发规范](development/development.md)和改动涉及的[设计章节](development/design.md)。说明用户从哪个入口提出什么任务，以及怎样观察它已经完成。优先通过现有模型、工具和技能完成工作。新增代码应有可验证的运行时职责。

## 开发环境

在 macOS 或 Linux 的项目根目录：

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
ruff check .
```

测试使用临时目录、合成资料与模拟端点。修改存储或管理页时，从实际入口验证编辑、旧修订冲突、删除和只读日志。修改安装、配置或构建时，额外验证：

- 在临时 `HOME` 中运行 `install.sh`，分别覆盖“仅宿主”和 `--cli` 两种路径。
- 重复安装保留已有 `data/`，项目技能链接幂等，自定义安装根可由项目链接定位。
- 在源码树外安装构建出的 wheel，核对 `SKILL.md`、静态资源、`aiverywhere` 和 `python -m aiverywhere` 两个入口。
- 配置向导不把密钥写入输出，`config.json` 权限保持 `0600`。

```sh
make build
python -m pip install build twine
twine check dist/*
```

## 提交 PR

使用 [PR 模板](../.github/PULL_REQUEST_TEMPLATE.md)，附上验收场景、实际结果和待验证项。持久数据与本机凭据留在 `data/`，不要提交。涉及用户可感知语义时同步更新设计说明和安装/使用文档。

参与讨论前阅读[行为准则](CODE_OF_CONDUCT.md)。安全问题按[安全策略](SECURITY.md)私下报告。[MIT 许可证](../LICENSE)
