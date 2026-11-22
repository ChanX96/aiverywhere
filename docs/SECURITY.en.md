# Security Policy

[简体中文](SECURITY.md) | **English**

## Supported versions

Security fixes target the latest release. The current line is `0.1.x`.

## Private reporting

Report vulnerabilities through [GitHub private security advisories](https://github.com/ChanX96/aiverywhere/security/advisories/new). Do not paste credentials, personal WeChat content, user material under `data/`, or identifiable run logs into a public issue.

Include the affected version and platform, the entry point (installer, CLI, console, MCP, or WeChat gateway), reproduction conditions, actual impact, and what you have already redacted. Maintainers will acknowledge receipt and will try to publish an explanation after a fix ships.

## Security boundaries of this project

- `config.json` may contain model credentials. It is written atomically with mode `0600`. Do not commit, screenshot, or forward `config.json` or `data/`.
- The console binds only to `127.0.0.1`, uses a per-page session token and same-origin checks, and does not provide remote access.
- The installer never requests `sudo`, never edits shell startup files, and never registers a system service. `--cli` only creates a command link at `<bin-dir>/aiverywhere`; an existing file not owned by the installer is not overwritten.
- `install.sh` fetches source from the configured repository and hands it to `pip` for building. If you are unsure about the source, download and review the script first, then point `--source` at a reviewed local checkout or distribution.
- Model endpoints, MCP servers, native executors, and WeChat gateways are configured by the user. Their permissions, logs, and credentials belong to those environments. Confirm the authorization scope before running tasks.
- Do not send real user data to maintainers. Reproduce issues with synthetic material and remove paths, accounts, and credentials from logs.
