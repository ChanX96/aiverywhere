# Install aiverywhere

[简体中文](install.md) | **English**

Host-only installation needs macOS or Linux with POSIX `sh`; `jq` is optional. The optional CLI needs Python 3.9+. Installation is host-neutral: any agent that can read files and run commands follows the same guide. The user only needs one sentence:

```text
Install aiverywhere: curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

## 1. One-line installation

Run this in the **project root** you want to use:

```sh
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

With a source checkout, run `./install.sh` from the repository root; the installer uses the local source and does not require the GitHub copy to be published first.
The commands below assume `ChanX96/aiverywhere` and its `main` branch. For a fork or mirror, replace the script URL and pass `AIVERYWHERE_REPO` / `AIVERYWHERE_REF` to change where the installer fetches source code.

The default installer only prepares the host bundle:

1. Copies `skills/aiverywhere/` to `<project>/.aiverywhere/skills/aiverywhere/`.
2. Creates `.aiverywhere/data/memory/`, `instance.json`, and the project skill link.
3. Calls no Python and creates no venv.
4. Requires model configuration only when `--cli` is added.

After installation, a host reads:

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

Use the sibling `scripts/` for memory; Python is not required. A user-level shared instance is available with `--home ~/.aiverywhere`.

### Common options

```sh
# Optional CLI and interactive model configuration
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli

# Non-interactive: host runtime only
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --yes

# Non-interactive: install the CLI; model and credential come from the environment
export ANTHROPIC_API_KEY="..."
export AIVERYWHERE_MODEL="your-model"
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh -s -- --cli --yes
```

| Option | Effect |
| --- | --- |
| `--cli` / `--no-cli` | Link the command into the command directory and configure a model. Interactive by default; non-interactive installs do not install the CLI. |
| `--yes`, `--no-input` | Do not prompt. Host-only install; `--cli` then requires model environment variables. |
| `--home DIR` | Instance root, default `<project>/.aiverywhere`. |
| `--project DIR` | Project that receives the skill link, default the current directory. |
| `--source TARGET` | pip source: a local directory, wheel, or package name; useful offline or for a reviewed version. |
| `--ref REF` | GitHub branch or tag, default `main`. |
| `--bin-dir DIR` | Command link directory, default `~/.local/bin`. |
| `--no-link` | Do not create the project skill link. |
| `--dry-run` | Print the commands that would run. |

`PIP_INDEX_URL` is passed through to pip:

```sh
export PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
curl -fsSL https://raw.githubusercontent.com/ChanX96/aiverywhere/main/install.sh | sh
```

## 2. Host integration

The installer has already linked the live file into the project. A host can use whichever path fits it:

- Hosts that support a project-level skill directory read `.agents/skills/aiverywhere/SKILL.md`.
- Hosts that only support explicit file reads use `<project>/.agents/skills/aiverywhere/SKILL.md`; with the CLI installed, `aiverywhere skill --info` reports the path and revision.
- Give the host a small verifiable task, such as "read this project's README, tell me how to start the console, and cite the evidence".

This entry uses only the host's own model, tools, and permissions; Python runs only for local commands such as memory, environment inspection, or the console. The host name is optional; when a host can run commands and local facts are needed, use `aiverywhere --project <dir> env` or set `AIVERYWHERE_HOST=<name>`.

## 3. Optional CLI

Use the CLI for a standalone terminal or schedules. A host can also run Dream at its own idle checkpoint without installing the CLI.

```sh
aiverywhere setup
```

The wizard asks for the model service, credential method, model name, maximum output tokens, and then the tool-turn, timeout, and port budgets. Everything except the model name and credential accepts the default by pressing Enter. The configuration is written to the instance-root `config.json` with mode `0600`.

The installer and setup prompts are currently written in Chinese. Every option is documented above, every field is documented in the [usage manual](usage.en.md#configuration), and `--no-input` is language-neutral for automation.

Non-interactive example:

```sh
export ANTHROPIC_API_KEY="..."
aiverywhere setup --no-input \
  --model "your-model" \
  --base-url "https://api.anthropic.com" \
  --max-tokens 4096 \
  --max-turns 12 \
  --timeout 180 \
  --port 8765
```

To keep the secret out of the configuration file, save only the environment variable name:

```sh
aiverywhere setup --no-input --model "your-model" --api-key-env ANTHROPIC_API_KEY
```

See the [usage manual](usage.en.md#configuration) for credential precedence and every field. Run a real task:

```sh
aiverywhere run --json 'Read the README and tell me how to start the console.'
```

Check that the receipt has `status` `completed` and an `answer` that addresses the task. Running `aiverywhere` shows the welcome screen and starts the interactive session; the host entry and local console do not require a model configuration.

## 4. Open the local console

```sh
aiverywhere web
```

Open the printed address. If the port is in use, add `--port 0` to choose a free port. Press Ctrl+C to stop. The console needs no model or network account.

## 5. Upgrade, migration, and uninstall

**Upgrade**: rerun the installer with the same `--home` and `--project`. It reuses the existing virtual environment and `data/`; `init` preserves the live agent, memory, skills, plans, and logs. Consider stopping writers and backing up `config.json` and `data/` first.

**Migration**: stop writers, copy `~/.aiverywhere/config.json` and `~/.aiverywhere/data/` to the new install root, then run:

```sh
aiverywhere --home <new-install-root> --project <project> init
aiverywhere --home <new-install-root> --project <project> link
```

**Uninstall**: confirm the install root first, then remove the command link and project link. `config.json` and `data/` contain credentials, memory, and logs and cannot be recovered after deletion.

Stop any cron, launchd, or systemd timer you added first (the current version has no built-in service), then back up and remove:

```sh
cp -a ~/.aiverywhere/data ~/aiverywhere-data-backup
rm -f ~/.local/bin/aiverywhere
rm -f <project>/.agents/skills/aiverywhere/SKILL.md
rmdir <project>/.agents/skills/aiverywhere 2>/dev/null || true
rm -rf ~/.aiverywhere
```

To remove only the CLI and keep memory/configuration, do not delete `~/.aiverywhere/config.json` or `~/.aiverywhere/data/`.

## Troubleshooting

- **Python 3.9+ not found**: only the optional CLI needs it; install `python3`, or set `AIVERYWHERE_PYTHON=/path/to/python3`.
- **Cannot create a virtual environment**: on Debian/Ubuntu install `python3-venv`, or use a Python with `-m venv` support.
- **Slow pip downloads**: set `PIP_INDEX_URL` to a mirror.
- **`aiverywhere: command not found`**: add `~/.local/bin` to `PATH`, use the CLI instance's `venv/bin/aiverywhere`, or rerun the installer with `--cli`.
- **Project skill link already exists**: the installer never overwrites a link that points somewhere else. Inspect `<project>/.agents/skills/aiverywhere/SKILL.md` and decide whether to keep or remove it.
- **A custom install root is not found from another project**: commands run in a linked project can locate it automatically; from other directories set `AIVERYWHERE_HOME=<install-root>`.

The installer never requests `sudo`, edits shell startup files, or registers a system service. See the [security policy](../SECURITY.en.md) for the security boundaries.
