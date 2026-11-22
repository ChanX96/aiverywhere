# aiverywhere Development Guide

[简体中文](development.md) | **English**

**Do not add an entity unless it is necessary.** Before adding a module, class, dependency, process, or persistent file, explain which concrete scenario the current structure cannot handle. Reuse an existing function or tool when it completes the task clearly.

This guide applies to people and coding agents changing aiverywhere. The root `AGENTS.md`, README, and contribution guide all point here. Product behavior follows the confirmed requirements in the [design notes](design.md) (currently maintained in Chinese); the single [working agreement](../../skills/aiverywhere/SKILL.md) ships with the package. The user-facing README, installation guide, and usage manual are available in Chinese and English.

## Where a change starts

1. **Write the completion condition first.** In one sentence, state the entry point, the input, and the observable result, and name the relevant design section. For example: "When the machine misses a weekly report, the first conversation sees one reminder, and that period executes zero times."
2. **Choose the owner.** Conversation strategy, exploration, and when to recall belong to the model following the working agreement or a skill. Operating software, fetching pages, and producing reports should reuse tools or MCP first. Model-protocol and channel differences stay in their own integration code. The Python core owns context scope, execution, permissions and confirmation, task state, scheduling, and recovery.
3. **Keep design and implementation aligned.** For user-visible semantics, such as what is shared across projects by default or whether a missed run is caught up, confirm the behavior with the user before changing the design. Internal organization can follow this guide directly. Runtime guidance changes update the single skill source.
4. **Extend behavior with skills.** When existing tools can obtain material, execute, and verify a new task, describe the conditions and method in a skill. Extend the Python core only when real read/write, protocol, or consistency guarantees are missing. Hosts and the CLI accept the same version of the working agreement and verifiable results.
5. **Minimize changes to the user's environment.** Smoke-test a new capability end to end with the same skill and an existing host first. Reuse the native path when it returns verifiable results. Default writes stay inside the selected instance and artifacts the user explicitly requested; do not register a system service. Use temporary instances to verify disable, cleanup, and preservation of existing user configuration.
6. **One agent loop per task.** Delegate to a native loop when one exists; a raw model uses the smallest local protocol loop. The same model decides whether to recall, which skill to use, and when to change approach. The scheduler wakes or reminds based on time and recorded state.

## Python package and layout

The first release uses PyPA's `src` layout. The root keeps engineering metadata, development entry points, and documentation. Importable implementation lives under `src/aiverywhere/`; tests call the package's public entry points. [PyPA's src layout discussion](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

```text
.github/                     CI, release, issue/PR templates, dependency updates
AGENTS.md                    Entry point for coding agents
CHANGELOG.md                 Version history
LICENSE                      MIT license
Makefile                     Fixed entry points for install, test, lint, build
README.md / README.en.md     Chinese and English project introduction
docs/guides/                 Bilingual install, usage, and WeChat guides
docs/development/            Design notes and development standards
docs/CONTRIBUTING.md / .en.md  Contribution guide
docs/SECURITY.md / .en.md    Security policy
docs/CODE_OF_CONDUCT.md / .en.md  Code of conduct
install.sh                   Bootstrap: venv, install, init, link, optional CLI
skills/aiverywhere/SKILL.md  The single distributed working agreement
config.json                  Instance configuration (not committed)
data/                        Agent, state, logs, and artifacts (not committed)
work/                        Recyclable private worker workspaces
pyproject.toml               Metadata, build backend, dependencies, tools, CLI entry
src/aiverywhere/
    cli/                     argparse, command handlers, composition root
    core/                    agent, store, memory, tools, workers, Dream
    integrations/web/        Loopback console, chat, and static assets
    integrations/wechat.py   WeChat gateway adapter
    platform/                environment and sandbox
    ui/                      welcome screen and terminal theme
    py.typed                 Type marker
tests/test_smoke.py          Standard-library unittest smoke tests
tests/test_configure.py      Configuration, linking, and install-entry tests
tests/test_dream.py          Clue memory, ordinary Dream task, and tool-permission tests
tests/test_tools.py           File search/edit, command, and web-tool tests
tests/test_stream.py          SSE text, CLI streaming, and basic cancellation tests
tests/test_workers.py         Worker private workspaces, artifact hand-off, and permissions
tests/test_session.py         Durable sessions, locking, crash recovery, and compaction
tests/test_permissions.py      Permission filtering, grants, approval, TTY prompt, and network
tests/test_installer.py        Host-only install and project-local instance
tests/shell/memory.sh          Shell-only memory interoperability
```

- Declare the build backend with `[build-system]` in `pyproject.toml` and point `aiverywhere` at `aiverywhere.cli:main` with `[project.scripts]`. Keep the version only in `__init__.py`. The command line, module startup, and host delegation share one task-execution path. [PyPA's pyproject.toml guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- The CLI binds a task and executor, the skill guides model behavior, and the scheduler owns wakeups, state, and receipts. A raw-model client runs the local tool loop according to the protocol. The storage module does not call a model. Express inputs and outputs with clear function names and boundary types; errors should preserve the reason, task, or call identifier. A new abstraction needs a real caller.
- The host-only path targets POSIX `sh`, optional `jq`, and plain JSON files; it needs no Python. The optional CLI targets Python 3.11+, `venv`, and `python -m pip`. The model HTTP client and optional MCP client are declared in `pyproject.toml`. Downloads may use the [Tsinghua PyPI mirror](https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple).
- A host-only install uses the project `.aiverywhere/`; the CLI binds through `.aiverywhere/instance.json`, the project link, or `--home`. Memory files live under `data/memory/<project_key>/`, and `state.json` keeps only plans, task claims, and channel receipts. Secrets and business data stay in the instance; packaging and CI samples use synthetic data only.
- Installation and host integration have one product-neutral path: `install.sh` creates the environment and calls `init` and `link`; `setup` configures the CLI when standalone execution is needed. The project link is fixed at `.agents/skills/aiverywhere/SKILL.md`; do not add host-specific directory branches. Keep the bootstrap POSIX `sh`; business decisions and testable writes stay in Python.
- `config.json` contains `model`, `defaults`, `mcpServers`, `wechat`, `session`, and `channels`. Model connection parameters and runtime budgets stay in their own sections. Interactive configuration must provide defaults for everything except the model name and credential. Credentials must not appear in command output or test logs.
- Comments should explain protocol receipts, locks, revisions, recovery, and directory boundaries. New commands update the installation or usage documentation; user-visible behavior changes update the design notes as well.

## Acceptance proportional to the change

| Changed area | Minimum acceptance questions |
| --- | --- |
| Task loop, model, host, or tools | Can the same goal be completed from the affected real entry point? Check task/tool receipt pairing, permission inheritance, cancellation, and partial failure. Cover exceptions with repeatable mock receipts; claim support for a real host or endpoint only after one real round trip in that environment. |
| Memory, skills, or storage format | With a temporary install directory and synthetic material, verify old data is readable, projects are isolated, short Chinese terms are recalled, unrelated creation performs zero retrieval, and user deletion cannot be recalled. After changing a write path, retest concurrency, retries, and interrupted writes. Performance claims must state data size, cold/warm process, elapsed time, and bytes read/written. |
| Dream, schedules, or channels | Use a controllable clock and a countable executor. With no clues, Dream makes zero model calls; one clue is handled by an ordinary task that writes a fact/skill and removes the clue; an offline missed task only reminds; duplicate wakeups claim one period; a generated report with unknown delivery keeps verifiable progress. Channel connectivity is judged by aiverywhere's artifacts and receipts. |
| Console chat | Submit one task through the loopback HTTP entry and verify session creation, status polling, tool receipts, and error responses. Defaults must be read-only; only explicit work mode may write. A refresh or process restart must clearly reset context rather than treating old answers as current evidence. Check that front-end assets load offline and responses contain no credentials. |
| Tools, streaming, and workers | Local edits verify the old hash and a unique fragment; commands return real exit codes and can terminate their process group; web tools reject private addresses and distinguish rate limits and non-text bodies. SSE text is shown once and tools execute only after complete arguments; Ctrl+C, `/cancel`, and `/cancel <worker-id>` stop the correct scope. Workers write only private workspaces, artifacts require SHA-256 verification before `accept_artifact`, and commands are unavailable without an isolation backend. |
| Package layout, entries, or resources | Install the built wheel in an empty environment, run `aiverywhere --help` and `python -m aiverywhere --help` outside the source tree, and read the working agreement from the installed package. Record the tested platform; verify macOS and Linux scheduling separately. |
| Installer, configuration, or linking | In a temporary `HOME`, complete both host-only and `--cli` installs: the host link points at the live file; the CLI command works; reinstallation preserves memory; a custom install root is recoverable through the project link; output contains no secrets; `config.json` has mode `0600`. Also verify both a no-TTY and an interactive TTY path so `curl \| sh` never reads prompts from the script. |

## When delivery is ready

From the project root run `make check` (equivalent to `ruff check .`, `sh -n install.sh`, and `python -m unittest discover -s tests`). Keep automation as small smoke tests covering the affected real entries. For installation changes, run `install.sh` for the host-only and `--cli` paths in a temporary `HOME` and repeat the install to confirm data preservation. For packaging changes, run `make build`, install the wheel in a clean environment outside the source tree, and check the template, type marker, console assets, and both CLI entries. [Contribution guide](../CONTRIBUTING.en.md)

Authors leave three things in the delivery note: **the intended design behavior, the commands or operations actually run with their observed results, and unverified environments or deviations from the design**. Reviewers recheck key cases through the affected real entry point and rerun after fixing failures. A capability without evidence remains "unverified". Existing test commands can be reused in CI; the current constraints are enforced by repository entry points, change review, and reproducible acceptance evidence.
