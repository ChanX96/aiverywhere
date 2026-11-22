# Using aiverywhere

[简体中文](usage.md) | **English**

A host-only install does not need the CLI commands below; point the host at `.agents/skills/aiverywhere/SKILL.md` and use its sibling `scripts/`. `aiverywhere` is only the optional CLI; if it is not on `PATH`, use its installed `venv/bin/aiverywhere`. Hosts and the CLI share the same `.aiverywhere/` instance.

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
```

## Model protocols

`model.protocol` can be:

- `anthropic`: Anthropic Messages, the default;
- `openai`: OpenAI Chat Completions;
- `ollama`: Ollama's OpenAI-compatible API, default `http://127.0.0.1:11434/v1`;
- `custom`: custom OpenAI-compatible gateway, requiring `base_url` and optionally `chat_path` and `headers`.

```sh
aiverywhere setup --protocol openai --model gpt-4.1 --api-key "$OPENAI_API_KEY"
aiverywhere setup --no-input --protocol ollama --model llama3.2
aiverywhere setup --protocol custom --model local \
  --base-url http://127.0.0.1:8000/v1 --chat-path /v1/chat/completions
```

`custom.headers` should contain only non-sensitive or necessary custom headers; credentials still use `api_key` / `auth_token` or environment references, with `config.json` mode `0600`.

## Configuration

`init` creates the single instance configuration at `<install-root>/config.json`. `setup` writes the model and runtime parameters while preserving `mcpServers` and `wechat`; unknown sections are rejected.

```sh
aiverywhere setup
export ANTHROPIC_API_KEY="..."
aiverywhere setup --no-input --model "your-model" --api-key-env ANTHROPIC_API_KEY
```

The interactive wizard asks for the model service (official or a compatible custom endpoint), credential method, model name, maximum output tokens, whether to adjust runtime parameters, and the tool-turn, timeout, and port budgets. Everything except the model name and credential accepts the default by pressing Enter. The prompts are currently in Chinese; every field is documented below.

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

### Model

An empty `model` section reads `AIVERYWHERE_MODEL` (or `ANTHROPIC_MODEL`), `ANTHROPIC_BASE_URL`, and `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` from the process environment. A non-empty section uses its own fields; missing credentials are not silently mixed in from the environment unless `api_key_env` or `auth_token_env` is used explicitly. `--model` can still override the model name for one call.

| Field | Meaning |
| --- | --- |
| `model` | Required. The actual model name. |
| `base_url` | Messages-compatible endpoint, default `https://api.anthropic.com`. |
| `max_tokens` | Maximum output tokens per model request, default `4096`. |
| `api_key` | Sent as `x-api-key`. |
| `auth_token` | Sent as `Authorization: Bearer`. |
| `api_key_env` | Read `x-api-key` from this environment variable at runtime; keeps the secret out of the file. |
| `auth_token_env` | Read the Bearer credential from this environment variable. |

Choose only one of `api_key`, `auth_token`, `api_key_env`, and `auth_token_env`. The official endpoint reports a clear error before the request when no credential is available. `config.json` is written with mode `0600`; still do not commit, screenshot, or share `config.json` or the whole `data/` directory.

**Native executor.** If you already have a standalone host command, replace `model` with:

```json
{
  "model": {
    "project": "/absolute/path/to/task-project",
    "command": ["/absolute/path/to/host-command", "non-interactive-arguments"],
    "pass_env": ["ENV_VAR_NEEDED_BY_THE_COMMAND"]
  }
}
```

The command runs in the selected project, receives a JSON object on standard input (`instructions`, `messages`, and related fields), and writes the final text to standard output on success. It is bound to the current `project`; the command chooses the model. If the task carries local tool grants, use Messages mode or grant the needed permissions inside the native host.

### Runtime parameters

An empty `defaults` section uses the built-in values; only override the keys you need. A one-call CLI option takes precedence over configuration.

| Key | Default | Purpose | One-call override |
| --- | --- | --- | --- |
| `max_turns` | 12 | Tool-turn limit for raw Messages tasks | `--max-turns` |
| `timeout` | 180 | Total seconds per task | `--timeout` |
| `port` | 8765 | Local console port; `0` picks a free port | `web --port` |

Scheduled and WeChat tasks use these defaults when they do not specify `timeout` or `max_turns` themselves. A running call keeps its original binding after a configuration change; new tasks, schedules, and Dream reread the configuration.

### MCP

For raw-model tasks that need a local stdio server, install the optional dependency in a Python 3.11+ environment. A source checkout can install the `.[mcp]` extra; an installed instance can add the dependency directly:

```sh
~/.aiverywhere/venv/bin/python -m pip install 'mcp>=1.20,<2'
```

For example, given an `office-tools` command:

```json
{
  "mcpServers": {
    "office": {"command": "office-tools", "args": [], "allowedTools": ["lookup"]}
  }
}
```

Grant it for one call with `aiverywhere run --mcp office 'look up the material with office'`. The server starts when tools are discovered and closes when the task ends.

### Personal WeChat gateway

A trusted gateway owns account pairing and inbound verification. Bind one project, account, and conversation in the `wechat` section; fill in receipt lookup and idempotent send according to the gateway's actual capabilities. `timeout` and `max_turns` can override the instance defaults.

```json
{
  "project": "/absolute/path/to/task-project",
  "account": "demo",
  "conversation": "chat-1",
  "url": "http://127.0.0.1:8787",
  "idempotent_send": true,
  "receipt_lookup": true
}
```

The configuration may contain secrets and is edited locally by the installer. A legacy `data/config.json`, `data/model.json`, `data/mcp.json`, or `data/wechat.json` is imported or migrated during the first initialization; later edits use the instance-root `config.json`. If an older wheel kept data in a separate virtual environment, stop writers, verify the target directory, copy the old `data/` into the new install root, preserve a customized agent as the new project's `data/SKILL.md`, and run `init`. Keep the old instance until the migration is verified.

## Environment, conversations, and delegation

```sh
aiverywhere env
AIVERYWHERE_HOST=my-host aiverywhere env
aiverywhere --project . run --json 'Read the README and tell me how this project runs.'
aiverywhere
aiverywhere chat
```

Running `aiverywhere` prints the project, instance, model, agent revision, and memory state; on a TTY it then enters the interactive session, while a non-TTY run only prints the welcome screen. `env` reports the platform, interpreter, task directory, confirmed grants, and capabilities that are still unverified. A host can set `AIVERYWHERE_HOST` or pass `--host`; when both are omitted, only known markers are recorded and no identity is inferred. `--home` binds the data install root and `--project` binds the task directory; both global options come before the subcommand.

The installer uses `~/.aiverywhere` by default. In a project that has the skill link, commands can locate a custom install root through the link; from other directories use `--home` or `AIVERYWHERE_HOME`. For a project-local instance, run `aiverywhere --home <project> init` and then `link` with the same `--home` so it does not mix with the user-level instance.

Each task has exactly one agent loop. A host runs its own loop and may delegate to a native subagent. The standalone CLI can call a configured native command; only a direct Messages endpoint runs this project's minimal local tool loop. Chat mode keeps one conversation history and each line continues the current session; a TTY returns to the prompt after each turn; press Ctrl+C to cancel a running turn. `/cancel` at the prompt reports that no task is running; piped/non-TTY input can still send `/cancel`. `/jobs` shows status, `/new` starts a new session, and `/ask ID text` follows up.

```sh
printf '%s\n' 'Read the README, return the startup command and the evidence.' |
  aiverywhere --project . run --json --task-id readme-1 -
```

Retrying the same request ID in the same project returns the original task receipt. Raw-model file tools are read-only by default; `--allow-write` permits writing task files, `--allow-exec` permits commands inside the project, and revising the agent requires separate authorization with `--allow-agent-edit <old-revision>`.

### CLI sessions and automatic compaction

The interactive CLI resumes the latest session for the project by default. Resume a specific session, or list recent sessions first, with:

```sh
aiverywhere chat --resume            # list the 10 most recent sessions and choose
aiverywhere chat --resume <session-id>
```

Each session is an append-only JSONL file:

```text
<instance>/data/sessions/<project_key>/<session_id>.jsonl
```

Commands:

```text
/new                 start a new session
/rename <name>       rename the current session
/resume <session-id> resume a specific session
/sessions            list project sessions with names and update times
/status              show session, turns, token estimate, and summary state
/compact             manually compact the current context
```

When the context approaches its budget, the kernel summarizes old turns; raw session records are retained. If summarization fails, a deterministic fallback is used. If the compacted request still exceeds the hard limit, the request fails explicitly instead of silently dropping context.

### CLI permissions and approval

The interactive CLI is read-only by default. Capabilities can be granted at launch or for the current session:

```sh
aiverywhere --allow-write
aiverywhere --allow-exec
aiverywhere --no-network
```

```text
/permissions
/grant write|exec|network
/revoke write|exec|network
```

`/grant` and `/revoke` are user commands, not model tools. They expire when the CLI exits and are recorded as session audit events. With `--ask-permissions`, `write_file`, `edit_file`, `run_command`, and artifact writes wait for:

```text
/approve
/deny
```

The model can request permission but cannot grant it. The Web console uses the same Task permission fields for writes, commands, and network access.

### Tools, workers, and cancellation

File tools are `list_files`, `read_file`, `search_files`, `write_file`, and `edit_file`. Writes and edits require `--allow-write`; `edit_file` uses the SHA-256 from the read and a unique fragment, refusing stale or ambiguous edits. `run_command(argv, cwd, timeout)` requires `--allow-exec`, returns an exit code, bounded output, and a timeout flag, and terminates the process group on cancellation. `web_search` uses keyless Bing RSS and falls back to DuckDuckGo HTML; `web_fetch` reads only public text pages and rejects loopback, private, and reserved addresses.

A main `run`/`chat` task may call `delegate(tasks)` for up to two depth-one workers. Each worker runs in a private copy under `work/<main-task>/<worker>/` with the same `Task.run()`, `SKILL.md`, and memory project, and cannot modify the real project. It returns a summary and artifacts (path, size, SHA-256); the main task verifies them and calls `accept_artifact` to write an authorized target. Command isolation is enabled only after an actual Seatbelt or bubblewrap probe; otherwise a worker keeps restricted file tools but cannot run commands.

On an interactive TTY, type `/` to open the command menu: `/help`, `/new`, `/resume`, `/sessions`, `/status`, `/compact`, `/permissions`, `/grant`, `/revoke`, `/jobs`, `/cancel`, `/ask`, and `/quit`.

Non-JSON interactive and one-shot runs stream text; `--json` keeps one final receipt. Ctrl+C cancels the current main task; a TTY redisplays the prompt after the turn. Non-TTY input can still use `/cancel`; `/cancel <worker-id>` cancels only that worker. Completed artifacts remain inspectable; operations with unknown external results stay pending verification.

## Memory, skills, and the local console

Without the CLI, use the Shell in the skill bundle:

```sh
sh <skill>/scripts/init-instance.sh
sh <skill>/scripts/write-memory.sh --kind fact --title 'title' --text 'body' --source task-1
sh <skill>/scripts/list-memory.sh --kind clue
sh <skill>/scripts/read-memory.sh <id>
sh <skill>/scripts/validate-memory.sh < record.json
```

Memory records live in `<instance>/data/memory/<project_key>/<id>.json`; the default instance is the project `.aiverywhere/` with key `default`. A shared instance derives a stable `p-<sha256 prefix>` key from each canonical project path, so projects A and B do not read or write the same directory. `state.json` keeps only plans, task claims, and channel receipts. The CLI is optional and reads the same files.

Optional CLI:

```sh
aiverywhere memory put 'monthly report' 'Edit a copy and verify formula positions when done.'
aiverywhere memory search 'monthly report'
aiverywhere memory search --kind skill --cold 'formula'
aiverywhere memory put --kind clue 'Clue: formula positions' 'The count is right but the positions are wrong.'
aiverywhere memory search --kind clue
aiverywhere memory forget <clue-id>
aiverywhere skill --info
aiverywhere link --dir .agents/skills/aiverywhere
aiverywhere web
```

`kind=clue` is a pending clue. It uses the same memory store, lock, and revisions as facts and skills; ordinary fact/skill searches do not return it, and the 90-day cold filter does not apply. Remove a processed clue with `memory forget`.

`link` creates only a symbolic link to the live agent and is idempotent; it refuses to overwrite a link that points somewhere else. Hosts that follow the project skill directory convention discover it; other hosts read the absolute path from `skill --info`.

The console's "Chat & work" page submits tasks to the current instance. It is read-only by default; project writes, command execution, and network access can be enabled separately. **A session is a durable conversation; a task is one execution.** CLI sessions live in `data/sessions/` and can be resumed with `aiverywhere chat --resume <id>` or `/resume <id>` inside chat. Web chat context lives in the current supervisor process and resets when switching modes or restarting it. The "Sessions & tasks" page lists durable CLI sessions and resume commands; "Run log" lists tasks. Tool receipts appear on the right. If no model is configured, the page reports the error instead of silently degrading.

"Agent definition" edits the whole bundle: `SKILL.md`, `references/*.md|json`, and `scripts/*.sh`. Each file has a content-hash revision check; the main file keeps the live-version rules.

Web chat supports a `/` command palette: `/help`, `/new`, `/status`, `/sessions`, `/logs`, `/agent`, `/memory`, `/overview`, `/resume`. Use ↑↓ to select, Tab/Enter to run, Esc to close. It only exposes safe Web actions. Send a literal slash with `//`.

**Project spaces**: one Web server is bound to one project instance and does not switch to arbitrary paths. To switch, launch `aiverywhere` in the target project; it prefers that project's `.aiverywhere/`, with its own port and supervisor. A user-level instance binds one project at a time; run concurrent projects with separate project-local homes. Do not read unregistered project paths from one console.

In the console, use "Memory and skills" to search by title, open a title to view or edit it, and cancel before deleting. "Agent definition" edits the instance-wide working agreement. While the console is open, external edits usually appear within 3 seconds. The page keeps local drafts and reports a conflict when saving an older revision. Deleting the local definition restores the distributed template; `skill --info` recreates the live file for hosts.

A long-running raw Messages CLI rereads the current agent before every model request. New interactive CLI tasks and follow-ups reread the executor configuration when they start. Native hosts reread at the checkpoints described in the working agreement; a command that receives one standard-input payload keeps what it received. Memory and skills use the current revision when recalled. [How running processes see changes](../development/design.md#运行中的文件变更) (Chinese)

"Run log" shows the current project's tasks newest first and can load older entries. Selecting a task id opens its run record; overview statistics and "Run log" link directly to it. `events.jsonl` keeps summaries; each run also writes a `0600` `data/runs/<hash>.json` with prompt, answer, error, and tool arguments/truncated output. Older tasks have no trace and show summary only. Run records are local sensitive data; do not commit `data/`. The console binds to `127.0.0.1`, accepts only same-origin local requests, checks a page token, serves its front-end assets from the package, and works fully offline. `--port 0` picks a free port.

The model recalls only the small amount of memory needed for the current task. To require confirmation before using a verified skill across projects, set `aiverywhere memory policy ask`; after the user agrees, pass the global `--confirm-shared` for that one call. Ordinary project facts stay in their source project.

## Idle Dream

Dream is an ordinary task, not a dedicated loop. When there is no new user task, the host uses its own model and starts with `aiverywhere memory search --kind clue`; with no clues it stops without calling a model. With clues, it follows the self-questioning checklist in the [working agreement](../../skills/aiverywhere/SKILL.md), writes a fact/skill only when the evidence is sufficient, and marks processed clues with `memory forget`; otherwise the clues remain.

A standalone CLI can run `aiverywhere dream`, which uses the same executor and prompt; without a configured executor it fails and keeps the clues. An external scheduler can call `wake --dream`. Dream has no special JSON output, lease, or state; repeated triggers may repeat the thinking, but the lock and revisions keep data consistent. `dream --note` is a compatibility alias for `memory put --kind clue`.

## Schedules and wakeups

```sh
aiverywhere schedule add 'Summarize this week.' --at 2026-12-07T09:00 --timezone Asia/Shanghai --repeat weekly
aiverywhere wake --dream
```

Replace the example date with the desired first run. aiverywhere does not register a daemon or system service; an existing cron, launchd, systemd timer, or other process manager calls the one-shot `wake` periodically. Each call processes due plans in order, one WeChat job, and one ordinary Dream when `--dream` is set and clues exist. More frequent calls reduce WeChat latency; the scheduler owns process liveness and retries.

Tasks missed while the machine was off or asleep are reported once by a later `run`, `chat`, or `schedule notices`; the user decides whether to catch up. Use `schedule results` to inspect execution results. The external scheduler must be able to read the install root's `data/` and use a configured model or native executor.
## WeChat integration and delivery

Personal WeChat is integrated through a trusted gateway; aiverywhere does not log in to WeChat directly. See the [WeChat integration guide](wechat.en.md) for configuration, inbound/outbound contracts, the worker, receipts, acceptance, and troubleshooting.
