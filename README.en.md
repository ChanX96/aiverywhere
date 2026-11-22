# aiverywhere

[简体中文](README.md) | **English**

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host shell](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#installation)
[![CLI Python 3.9+](https://img.shields.io/badge/cli-python%203.9%2B-blue.svg)](pyproject.toml)

**Run the same agent in any host and in the terminal.** aiverywhere gives a model the goal, the context it needs, and the tools it may use. The model chooses what to do, decides whether to recall past experience, and decides which lessons are worth keeping. Python is responsible for writing tool results, memory revisions, scheduled work, and delivery receipts back to the project reliably.

## Core shell

The core keeps only four things: one `SKILL.md`, one minimal model/tool loop, one memory and clue store, and a host/CLI entry. `init`, `setup`, `link`, `run`, `chat`, `memory`, and `dream` form the core. `chat` runs one line to completion at a time and keeps no background queue.

The web console, WeChat gateway, `schedule`/`wake` scheduling, MCP, and native executor are optional adapters. `wake` is a one-shot call from an external cron, launchd, or systemd timer; it is not a daemon and registers no system service. Dream runs in the host's own idle loop with the host model, or as one ordinary CLI task.

## One-line installation

Host-only: macOS or Linux with POSIX `sh`; `jq` optional. Optional CLI: Python 3.9+. Run this in the project root:

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

With a source checkout, run `./install.sh` from the repository root. By default it installs only the host bundle into the project at `.aiverywhere/skills/aiverywhere`, creates `.aiverywhere/data/memory/`, and links `.agents/skills/aiverywhere` to the standard skill directory. This path needs no Python, pip, or venv. Add `--cli` only when you want the command-line runtime. Hosts do not need product-specific setup: a host that can read files reads that link or the absolute path printed by the installer. Install the CLI only when you need it.

Any host agent can be asked with one sentence:

```text
Install aiverywhere: curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

### Optional: install the CLI and configure a model

The interactive flow asks for the model endpoint, credential, model name, and runtime parameters after installation:

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
```

For unattended installs, provide the model and credential through the environment; all other values use defaults:

```sh
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="your-model"
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

Run `aiverywhere setup` later to change the configuration. The installer and setup prompts are currently written in Chinese; the [installation guide](docs/guides/install.en.md) and [usage manual](docs/guides/usage.en.md#configuration) document every field, and `--no-input` is fully language-neutral. See the guide for all options, upgrades, and uninstall steps.

## Verify

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

If the optional CLI is not on `PATH`, use its installed `venv/bin/aiverywhere`. In a host session, ask a small verifiable task such as "read this project's README, tell me how to start the console, and cite the evidence". This confirms that the host is using the same working agreement from `.agents/skills/aiverywhere/SKILL.md`.

Local console:

```sh
aiverywhere web
```

Open the address printed in the terminal (default `http://127.0.0.1:8765/`; a TTY tries to open the browser by default, while `--no-open` only prints it). "Chat & work" submits tasks directly: read-only by default; enable "Allow project writes" before the model can modify the current project. Session context lives in the current web process and tool receipts appear on the right; restarting the process or switching modes resets the context. The other pages search, create, edit, and delete project memory and skills, revise the agent definition, and browse a read-only log by time. Pages and fonts are served locally. Press Ctrl+C to stop.

## Entries and capabilities

| Entry | How to start |
| --- | --- |
| Any host conversation or native subagent | Read `.agents/skills/aiverywhere/SKILL.md`; use `.aiverywhere/skills/aiverywhere/scripts/` for local memory. Use the host's own model, tools, and permissions. |
| Standalone CLI | Run `aiverywhere setup`, then run `aiverywhere` for the welcome screen and interactive session, or use `aiverywhere run 'goal'` / `aiverywhere chat`; add `--allow-write` for file writes and `--allow-exec` for commands. |
| Scheduled work and Dream | The host can run Dream with its current model at its own idle checkpoint; the CLI uses `aiverywhere dream`, an external cron, launchd, or systemd timer calls `wake --dream` periodically. |
| Personal WeChat | Integrated through a trusted gateway; aiverywhere owns durable tasks, model answers, and receipts. See the [WeChat guide](docs/guides/wechat.en.md). |
| Local console | `aiverywhere web`; chat and run read-only or explicitly write-enabled tasks in the browser, and manage memory, skills, and logs; binds to loopback only. |

## Tools, workers, and cancellation

The standalone CLI's raw Messages tools include file search, local edits, command execution, and web search/fetch. `list_files`, `read_file`, `search_files`, `web_search`, and `web_fetch` are available by default; `write_file` and `edit_file` require `--allow-write`, and `run_command` requires `--allow-exec`. Writes and commands must stay within the task scope; cancellation terminates the command's process group.

`aiverywhere run` and `aiverywhere chat` let the main model delegate up to two depth-one workers by default. A worker uses the same `Task.run()` and `SKILL.md`, but its file tools operate on a private copy under `work/<main-task>/<worker>/`. The model receives summaries and artifacts and calls `accept_artifact` to copy a verified result into the project. Command availability depends on an actual OS isolation probe: Seatbelt or bubblewrap must be present and usable. Otherwise workers retain restricted file tools but cannot execute commands.

Non-`--json` `run` and `chat` stream the answer; `--json` still emits one final receipt. Ctrl+C cancels the current main task, `/cancel` cancels it, and `/cancel <worker-id>` cancels one worker. Switching tasks never treats an old answer as evidence for a new one.

## Host memory without the CLI

The skill bundle includes POSIX Shell:

```sh
sh <skill>/scripts/init-instance.sh
sh <skill>/scripts/write-memory.sh --kind fact --title 'title' --text 'body' --source task-1
sh <skill>/scripts/list-memory.sh --kind clue
sh <skill>/scripts/read-memory.sh <id>
sh <skill>/scripts/validate-memory.sh < record.json
```

Memory records are `data/memory/<project_key>/<id>.json`, governed by `references/memory-v1.schema.json`. Without `jq`, a host may use native structured validation; Python is not required. The optional CLI reads and writes the same files and schema.

## Configuration

After installing the CLI, `aiverywhere setup` writes `config.json`. Empty sections mean built-in defaults. Everything except the model name and credential has a default value:

```json
{
  "model": {
    "model": "your-model",
    "base_url": "https://api.anthropic.com",
    "max_tokens": 4096
  },
  "defaults": {
    "max_turns": 12,
    "timeout": 180,
    "port": 8765
  },
  "mcpServers": {},
  "wechat": {}
}
```

A credential can be stored in the 0600 `config.json`, or only its environment variable name can be saved (`api_key_env`, `auth_token_env`) to keep the secret off disk. See the [usage manual](docs/guides/usage.en.md#configuration) for fields, non-interactive examples, MCP, and WeChat gateway configuration.

## Where files live

| Path | Purpose |
| --- | --- |
| `<project>/.aiverywhere/` | Default project instance; no Python required. |
| `<project>/.aiverywhere/skills/aiverywhere/` | Standard skill bundle: `SKILL.md`, references, Shell scripts. |
| `<project>/.aiverywhere/data/memory/<project_key>/` | One JSON file per memory record. |
| `<project>/.aiverywhere/data/logs/` | Per-task summaries and receipts. |
| `<project>/.aiverywhere/data/artifacts/` | Worker or task artifacts. |
| `<project>/.aiverywhere/state.json` | Plans, task claims, and channel receipts; no memory bodies. |
| `<project>/.aiverywhere/config.json` | Optional CLI model and runtime parameters. |
| `<project>/.aiverywhere/work/` | Recyclable private worker workspaces. |
| `<project>/.agents/skills/aiverywhere` | Link to the standard skill bundle. |

When running from a source checkout, the install root is the checkout; its configuration is `config.json` and its state/logs live in `data/`. Use `--home` to select an install root and `--project` to select the project for this task. To back up, stop writers and copy `config.json` and `data/`.

## Project layout

```text
.github/                    CI, release, issue/PR templates, Dependabot
docs/guides/                Bilingual install, usage, and WeChat guides
docs/development/           Design notes and development standards
docs/CONTRIBUTING.md        Contribution and acceptance requirements
docs/SECURITY.md            Private vulnerability reporting and security boundaries
docs/CODE_OF_CONDUCT.md     Code of conduct
skills/aiverywhere/SKILL.md  The single distributed working agreement
src/aiverywhere/
  cli/                      CLI composition root and entry points
  core/                     agent, store, tools, memory, worker
  integrations/             web, WeChat, MCP adapters
  platform/                 environment and sandbox
  ui/                       welcome and terminal presentation
tests/                      Standard-library unittest smoke and configuration tests
install.sh                  One-line installer for any host
AGENTS.md                   Entry point for coding agents
CHANGELOG.md                Version history
Makefile                    Install, test, lint, and build entry points
pyproject.toml              Package metadata, dependencies, tool config, CLI entry point
```

## Development

```sh
make install
make check
make build
```

Or manually:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

Read the [development guide](docs/development/development.en.md) before submitting changes and include acceptance evidence, observed results, and open verification items. The architecture notes are currently maintained in Chinese.

## Documentation

- [Installation guide](docs/guides/install.en.md): one-line install, optional CLI, upgrades, and uninstall.
- [Usage manual](docs/guides/usage.en.md): configuration, entries, memory, console, and schedules.
- [WeChat integration](docs/guides/wechat.en.md): gateway contract, worker, receipts, acceptance, and troubleshooting.
- [Design notes](docs/development/design.md) (Chinese): architecture, prior art, and verified boundaries.
- [Development guide](docs/development/development.en.md): layout, change ownership, and acceptance requirements.
- [Contributing](docs/CONTRIBUTING.en.md) · [Security](docs/SECURITY.en.md) · [Code of Conduct](docs/CODE_OF_CONDUCT.en.md) · [Changelog](CHANGELOG.md) (Chinese)
- 中文: [README](README.md) · [安装](docs/guides/install.md) · [使用](docs/guides/usage.md) · [开发](docs/development/development.md) · [贡献](docs/CONTRIBUTING.md) · [安全](docs/SECURITY.md)

Started by [ChanX96](https://github.com/ChanX96), distributed under the [MIT License](LICENSE).
