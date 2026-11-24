# 开发 aiverywhere

修改本项目之前，先读[开发手册入口](docs/development/README.md)、[项目开发规范](docs/development/development.md)，再读[设计方案](docs/development/design.md)中与任务相关的章节。交付时按规范附上验收场景、实际运行结果以及待验证项。

[SKILL.md](skills/aiverywhere/SKILL.md) 是产品的行为模板。请求安装时执行[安装指南](docs/guides/install.md)（[English](docs/guides/install.en.md)）。安装和宿主导入不区分产品：统一使用 `install.sh` 与 `.agents/skills/aiverywhere`，需要独立执行时再选装 CLI。安装或配置改动的验收同时覆盖仅宿主、`--cli`、重复安装和干净 wheel。
