# 记忆格式与操作

## 目录

```text
<instance>/data/memory/<project_key>/<id>.json
```

一条记录一个文件。`state.json` 不保存记忆，只保存计划、任务和渠道回执。

项目本地实例使用 `<project_key>=default`；共享实例按规范化的项目路径派生稳定 key（`p-` + SHA-256 前 16 位），Shell 和 CLI 必须得到同一个 key。只有显式 `shared` 的通用技能才跨项目可见。

## Schema

唯一规范是 [memory-v1.schema.json](memory-v1.schema.json)。必填字段：

`schema_version`、`id`、`revision`、`kind`、`title`、`text`、`source`、`updated`。

`kind` 为 `fact`、`skill` 或 `clue`。`shared` 可选；一旦出现必须是布尔值，不能为 `null`。共享样本位于 `tests/fixtures/memory-v1-vectors.json`，Shell 和 Python 同跑。

## 写入与更新

```sh
sh scripts/write-memory.sh --kind fact --title '标题' --text '正文' --source task-1
sh scripts/write-memory.sh --id <id> --revision <旧revision> \
  --kind fact --title '标题' --text '新正文' --source task-2
```

新建记录生成稳定 ID。修改已有记录必须核对旧 `revision`；不匹配返回冲突，不覆盖。

## 校验与回执

```sh
sh scripts/validate-memory.sh < record.json
```

| 能力 | 回执 |
| --- | --- |
| `sh` + `jq` | 写前校验，写后重读：已校验保存 |
| 无 `jq`，有原生结构化校验 | 用同一 Schema：已校验保存 |
| 只有普通文件工具 | 写后回读：已写入，格式待校验 |
| 格式错误/写入失败 | 具体原因，保留旧记录 |

Shell 校验只证明格式，不证明并发安全。没有锁或条件写入能力时，只提交修改建议。

## 搜索

```sh
sh scripts/list-memory.sh --kind clue
sh scripts/list-memory.sh --query 月报 --limit 20
sh scripts/read-memory.sh <id>
```

没有向量索引；由模型决定查什么、是否展开正文。
