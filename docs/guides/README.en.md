# aiverywhere user manual

This manual is for people installing and using aiverywhere. If you only need the host skill, start with installation; the CLI, Web, channels, and migration are optional.

## Entry status

| Entry | Status | Verified scope |
| --- | --- | --- |
| Host-only skill | stable baseline | install, link, Shell memory interop, workflow overrides |
| CLI | alpha | sessions, memory, permissions, workers, Web, migration |
| Web | alpha | local chat, decisions, process panels, todos, run history |
| WeChat / Feishu / iMessage | alpha | generic envelope, bridge discovery, unit/simulated receipts; real accounts need separate verification |

Current release: **v0.5.0**. Real hosts, browsers, WeChat accounts, and Linux distributions still follow their respective acceptance checks.

## Recommended reading order

1. [Install aiverywhere](install.en.md): host-only, CLI, or manual.
2. [First task](#first-task): confirm the instance, model, and permissions.
3. [Usage](usage.en.md): CLI, sessions, Web, memory, workflows, and human decisions.
4. Read [channels](channels.en.md) or [WeChat](wechat.en.md) only when you need them.
5. For another machine or project, read [adoption and migration](usage.en.md#host-adoption-and-migration).

## First task

### Host-only

After installation, point the host at:

```text
<project>/.agents/skills/aiverywhere/SKILL.md
```

Then start with a verifiable task:

```text
Read this project's README, explain how to start it, and cite the evidence.
```

The host uses its own model, file tools, and permissions. aiverywhere does not require a Python CLI.

### CLI

```sh
aiverywhere --version
aiverywhere env
aiverywhere skill --info
aiverywhere
```

Type `/` in a TTY for commands. `aiverywhere` uses the current project instance by default; `--project` and `--home` bind explicitly.

### Web

```sh
aiverywhere web
# or
aiverywhere start
```

The console binds to `127.0.0.1` by default and is read-only; writes, command execution, and network access are separate grants.

## Topics

| Topic | Document |
| --- | --- |
| Install, upgrade, uninstall, troubleshoot | [Installation](install.en.md) |
| Model config, sessions, CLI, Web, memory, workflows | [Usage](usage.en.md) |
| WeChat, Feishu, iMessage, generic envelope | [Channels](channels.en.md) |
| Legacy WeChat gateway, account binding, and protocol | [WeChat: configuration](wechat.en.md#2-configuration) |
| Host adoption, running input, migration | [Usage: adoption and migration](usage.en.md#host-adoption-and-migration) |
| Security and credentials | [Security](../SECURITY.en.md) |
| Development, architecture, acceptance | [Developer manual](../development/README.md) |

## Boundaries

- Host-only installation does not need Python; the optional CLI needs Python 3.11+.
- Memory, sessions, logs, and artifacts stay in the project instance by default.
- Credentials may be stored as environment-variable names only.
- WeChat, Feishu, and other platforms connect through trusted bridges; aiverywhere does not log in directly.
- Real host, browser, WeChat, and scheduling acceptance follows the [development guide](../development/development.en.md#acceptance-proportional-to-the-change).
