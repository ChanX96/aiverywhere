<div align="center">

# aiverywhere

**The skill is the product, not an accessory to the CLI.**

One agent contract for any host, terminal, local console, or scheduled job.

[![CI](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml/badge.svg)](https://github.com/ChanX96/aiverywhere/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Host: sh + jq](https://img.shields.io/badge/host-sh%20%2B%20jq-brightgreen.svg)](#host-only-install)
[![CLI: Python 3.9+](https://img.shields.io/badge/cli-python%203.9%2B-blue.svg)](pyproject.toml)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

[简体中文](README.md) | [English](README.en.md)

</div>

## What is aiverywhere?

`aiverywhere` is a **shell-first agent skill** with an optional CLI. It gives a model a working contract, a small tool loop, durable project memory, and adapters for a local console, workers, WeChat, and scheduled jobs.

Most agent projects assume you install Python and a command before doing anything. `aiverywhere` does the opposite:

- **`SKILL.md` is the core product.** Any host that can read files and run commands can use it.
- Host-only users manage memory with **POSIX Shell and plain JSON**, without Python, pip, or a venv.
- The CLI is another optional host, not a prerequisite.
- Hosts, the CLI, the console, and scheduled work read and write the **same memory files and schema**.

## Highlights

### Host-only, no forced CLI

The default install copies the skill bundle, creates `<project>/.aiverywhere/`, and links `.agents/skills/aiverywhere`. There is no Python dependency and no model key requirement.

### Memory as ordinary files

```text
.aiverywhere/data/memory/<project_key>/<id>.json
```

Each record has a stable ID, incremented `revision`, one of `fact` / `skill` / `clue`, and a fixed JSON Schema. `state.json` is reserved for plans, task claims, and channel receipts.

### Host and CLI share one memory

Shell records are immediately visible to the CLI, and CLI records are readable from the host scripts. The CLI reuses the same `validate-memory.sh` before writing.

### A proactive skill

`SKILL.md` defines not only how to call tools, but when to recall, when to save a fact or skill, when to leave a clue, when to process old clues, and when to promote a repeated workflow into a skill.

### Tools, workers, and streaming

- File discovery, search, edits, and permission-gated commands.
- Depth-one parallel workers with private workspaces and artifact hand-off.
- SSE text streaming, CLI streaming, Ctrl+C, and `/cancel`.
- Optional local Web console, WeChat gateway, MCP, and schedulers.
- Read-only by default; writes and command execution require explicit grants.

### Keyless web search

`web_search` uses **Bing RSS** as the primary channel and falls back to **DuckDuckGo HTML**. It no longer depends on Tavily. `web_fetch` accepts only public HTTP(S) text pages and rejects private, loopback, and reserved addresses on every redirect.

### Local-first

- Project-local instance by default: `<project>/.aiverywhere/`.
- Credentials can be stored as environment-variable names.
- The Web server binds only to loopback.
- Console assets ship with the package; no CDN.
- No system service and no shell-startup edits.

## Architecture

```text
Host agent / CLI / Web / WeChat / scheduler
                  │
                  ▼
             SKILL.md
                  │
                  ▼
       Task loop + Tools + Workers
                  │
                  ▼
   .aiverywhere/data/memory/<key>/*.json
        (shared by host and CLI)
```

Source layout:

```text
src/aiverywhere/
├── cli/                  CLI commands and composition root
├── core/                 agent, store, memory, tools, workers
├── integrations/web/     Web server, chat sessions, static assets
├── integrations/wechat.py
├── platform/             environment and sandbox
└── ui/                   welcome screen and terminal presentation
```

## Quick start

### Host-only install

Requires macOS / Linux with POSIX `sh`; `jq` is optional.

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

From a source checkout:

```sh
./install.sh
```

The host reads:

```text
<project>/.agents/skills/aiverywhere/SKILL.md
<project>/.aiverywhere/skills/aiverywhere/scripts/
```

No Python is required.

### Optional CLI

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli
```

Or:

```sh
./install.sh --cli
aiverywhere setup
```

Non-interactive:

```sh
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="your-model"
./install.sh --cli --yes
```

### Verify

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

## Usage

### Host agent

Point the host at the project skill:

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

The host uses its own model, tools, and permissions.

### Interactive CLI

```sh
aiverywhere
```

On a real TTY, the welcome screen opens an interactive prompt:

```text
aiverywhere ›
```

Type `/` to open the command menu:

| Command | Purpose |
| --- | --- |
| `/help` | Show help |
| `/new` | Start a new session |
| `/jobs` | Show tasks in this process |
| `/cancel` | Cancel the current task |
| `/ask <id> <question>` | Ask a follow-up against a completed task |
| `/quit` | Exit |

Writes and commands are off by default:

```sh
aiverywhere --allow-write
aiverywhere --allow-exec
```

### Local Web console

```sh
aiverywhere web
```

The default URL is `http://127.0.0.1:8765/`. A desktop TTY tries to open it automatically; `--no-open` only prints the URL.

## Memory

### Shell

```sh
SKILL=.agents/skills/aiverywhere

sh "$SKILL/scripts/init-instance.sh"
sh "$SKILL/scripts/write-memory.sh" \
  --kind fact \
  --title 'Monthly unit' \
  --text 'Monthly reports use ten-thousand yuan.' \
  --source task-001
sh "$SKILL/scripts/list-memory.sh" --kind clue
sh "$SKILL/scripts/read-memory.sh" <id>
```

### CLI

```sh
aiverywhere memory put 'Monthly unit' 'Monthly reports use ten-thousand yuan.'
aiverywhere memory search 'Monthly unit'
aiverywhere memory search --kind clue
aiverywhere memory forget <id>
```

### Record format

```json
{
  "schema_version": 1,
  "id": "0123456789abcdef0123456789abcdef",
  "revision": 1,
  "kind": "fact",
  "title": "Monthly unit",
  "text": "Monthly reports use ten-thousand yuan.",
  "source": "task-001",
  "updated": "2026-11-22T12:00:00Z",
  "shared": false
}
```

See [memory-v1.schema.json](skills/aiverywhere/references/memory-v1.schema.json).

## Status

Alpha. Verified locally:

- host-only, `--cli`, repeat, and clean-wheel installs;
- bidirectional Shell/CLI memory access;
- migration of legacy `state.json` memory;
- base tool, worker, streaming, and Web paths;
- a real Bing RSS search.

Still under verification:

- real personal WeChat and browser channels;
- long-running interactive TTY use;
- host-specific skill discovery;
- deeper source package boundaries and long-term memory indexing.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
make check
```

This runs Python tests, Shell memory tests, and ShellCheck.

## Documentation

- [Install](docs/guides/install.en.md)
- [Usage](docs/guides/usage.en.md)
- [WeChat](docs/guides/wechat.en.md)
- [Design](docs/development/design.md)
- [Development guide](docs/development/development.en.md)
- [Chinese README](README.md)

## License

[MIT](LICENSE)
