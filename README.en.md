<div align="center">

# aiverywhere

**A shell-first agent skill for any host. Add the CLI, Web, or channels only when you need them.**

The same working agreement, project memory, and task receipts across host agents, terminals, local Web, and message channels.

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host: sh + jq](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#quick-start)
[![CLI: Python 3.11+](https://img.shields.io/badge/cli-python%203.11%2B-blue.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

[简体中文](README.md) | [English](README.en.md)

</div>

## What is it

`aiverywhere` is an **agent skill product**, not a CLI that must be installed first.

It packages the working agreement — how to understand a task, when to consult project memory, how to execute and verify, and what deserves long-term storage — into a readable `SKILL.md`. Any host agent that can read files and run commands can use it. The CLI, local Web console, and message channels are optional entry points.

It solves three practical problems:

- **Working rules are lost when the host changes.** The same skill works with Claude Code, Codex, Cursor, other coding agents, or a terminal.
- **Project memory is scattered.** Facts, skills, and clues live as ordinary JSON files in the project instance, shared by the host and the optional CLI.
- **Simple tasks are buried in process.** Ordinary questions can be answered directly; planning, recall, execution, extraction, and finishing modules load only when useful.

### Goals

- **The skill is the product.** A host needs one readable entry point; no CLI is required for everyday work.
- **Portable state.** Host, CLI, Web, and channels share one project instance and memory-v1 format.
- **Local-first.** Default writes stay in the project instance; the caller controls model, permissions, and network. No system service.
- **Small kernel.** Conversation strategy stays in the skill; only execution, permissions, locks, revisions, recovery, and receipts belong in Python.

### Not goals

- Not a hosted SaaS or model subscription.
- Not a WeChat/Feishu account bot; platform access goes through trusted bridges.
- Not a mandate to run every task through a multi-step workflow; simple questions can be answered directly.
- Not a guarantee of identical behavior across machines, hosts, and models.

## Quick start

### Host-only skill (recommended)

Requirements: macOS or Linux, POSIX `sh`; `jq` is optional.

From the project root:

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

This creates:

```text
<project>/.agents/skills/aiverywhere/   # host entry point
<project>/.aiverywhere/                 # project instance: config, memory, logs
```

No Python, venv, or model key is required. Point the host at `.agents/skills/aiverywhere/SKILL.md`.

### CLI and local Web (optional)

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
aiverywhere setup
aiverywhere
```

The CLI requires Python 3.11+. Type `/` for commands. Start the local Web console with:

```sh
aiverywhere web
# or keep the supervisor running
aiverywhere start
```

### Verify

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

Without the CLI, read `.agents/skills/aiverywhere/SKILL.md`, or run:

```sh
sh .agents/skills/aiverywhere/scripts/init-instance.sh
```

## Three entry points

| Entry | Best for | Requirements |
| --- | --- | --- |
| Host agent | Daily coding, documents, analysis; uses the host's model and tools | File/command access; optional `jq` |
| CLI | Standalone terminal, durable sessions, workers, scheduling, Web | Python 3.11+ |
| Web / channels | Local console, approvals, run history, WeChat/Feishu/iMessage | Optional CLI + the matching bridge |

All entries share one `.aiverywhere/` instance and the memory-v1 format.

## Common commands

```sh
# Create or complete an instance
aiverywhere init
aiverywhere setup

# Inspect state, memory, and runs
aiverywhere env
aiverywhere memory search 'project'
aiverywhere status

# Run one task
aiverywhere run 'Read the README, explain how to start the project, and cite evidence'

# Long-lived use
aiverywhere chat
aiverywhere chat --resume
```

Memory examples:

```sh
aiverywhere memory put 'Report unit' 'Use ten-thousand yuan by default.'
aiverywhere memory search 'report'
aiverywhere memory search --kind clue
```

## Layout

```text
.aiverywhere/
├── config.json                 # model, budgets, MCP, channels
├── instance.json               # project identity and instance root
├── skills/aiverywhere/         # active skill bundle
├── overrides/                  # project workflow overrides
└── data/
    ├── memory/<project_key>/   # fact / skill / clue
    ├── sessions/               # durable CLI sessions
    ├── runs/                   # detailed run records
    ├── logs/                   # summary logs
    ├── artifacts/              # worker artifacts
    └── project-settings/       # adoption and non-memory settings
```

Each memory entry is one JSON file with a stable ID and increasing revision. `state.json` holds schedules, task claims, and channel receipts only.

## Documentation

### User manual

Start at [docs/guides/README.en.md](docs/guides/README.en.md).

| I want to… | Read |
| --- | --- |
| Install, upgrade, uninstall, troubleshoot | [Installation](docs/guides/install.en.md) |
| Learn the CLI, sessions, Web, memory, and workflows | [Usage](docs/guides/usage.en.md) |
| Connect WeChat, Feishu, or iMessage | [Channels](docs/guides/channels.en.md) · [WeChat](docs/guides/wechat.en.md) |
| Move a project to another machine | [Usage: adoption and migration](docs/guides/usage.en.md#host-adoption-and-migration) |
| Understand the architecture | [Design notes](docs/development/design.md) |

### Developer manual

Start at [docs/development/README.md](docs/development/README.md).

| I want to… | Read |
| --- | --- |
| Set up and submit changes | [Development guide](docs/development/development.en.md) |
| Understand the task loop and boundaries | [Design notes](docs/development/design.md) |
| Run acceptance checks | [Ten acceptance scenarios](docs/development/acceptance.md) |
| Contribute or report security issues | [Contributing](docs/CONTRIBUTING.en.md) · [Security](docs/SECURITY.en.md) |

## Status

Current release: **[v0.5.0](https://github.com/ChanX96/aiverywhere/releases/tag/v0.5.0)** (alpha).

Verified on macOS arm64 with Python 3.14; CI covers Python 3.11 and 3.14. Linux results follow CI.

- Minimum Python: 3.11.
- Host install: macOS / Linux with POSIX `sh`.
- Writes are limited to the project instance and explicitly requested artifacts.
- Web binds to `127.0.0.1` only.
- No system service or shell startup-file modification.

Real WeChat accounts, some third-party channels, full browser interaction, and some host environments still need the acceptance described in the [development guide](docs/development/development.en.md#acceptance-proportional-to-the-change).

## Not affiliated

aiverywhere is an independent project and is not affiliated with Anthropic, OpenAI, DeepSeek, Tencent, Feishu, Apple, or other model/channel vendors. Follow each third-party service's terms.

## License

[MIT](LICENSE)
