# aiverywhere developer manual

This manual is for developers, reviewers, and coding agents changing aiverywhere. Users should start at the [user manual](../guides/README.en.md).

## Current baseline

- Release: v0.5.0 (alpha).
- Verified: macOS arm64, Python 3.14; CI covers Python 3.11/3.14.
- Automation: 123 Python tests, 10 CLI/host acceptance scenarios, Shell memory interop/conformance.
- Unverified: real desktop/mobile browsers, real TTY IME, real WeChat accounts, all Linux distributions.

Treat the current `make check` output as authoritative; do not estimate counts in prose.

## Read first

1. [Development guide](development.en.md): change boundaries, layout, comments, tests, and delivery.
2. [Design notes](design.md): product behavior, task lifecycle, storage, channels, and acceptance.
3. [Ten acceptance scenarios](acceptance.md): the fixed CLI/host regression matrix.
4. [Working agreement](../../skills/aiverywhere/SKILL.md): the shared behavior source.

## Architecture at a glance

```text
host agent / CLI / Web / channels / scheduler
                      │
                      ▼
             SKILL.md + workflow
                      │
                      ▼
        Task loop + Tools + Worker + Store
                      │
                      ▼
     instance: config / memory / sessions / runs
```

- `skills/aiverywhere/`: main skill, five on-demand workflow modules, Shell memory scripts.
- `src/aiverywhere/cli/`: argparse, command composition, terminal UI.
- `src/aiverywhere/core/`: Task, Store, memory, tools, workers, migration, adoption.
- `src/aiverywhere/integrations/`: Web, bridges, WeChat.
- `src/aiverywhere/platform/`: environment and sandbox.
- `tests/`: standard-library unittest and acceptance; `tests/shell/` covers Shell interop.

## Development environment

```sh
make install
make check
make acceptance
make build
```

Python 3.11+ is required for development. Host-only paths use POSIX `sh` and do not require Python.

For installer or packaging changes, also test outside the source tree: clean wheel, host-only, `--cli`, repeat install, and migration import. See [the development guide](development.en.md#acceptance-proportional-to-the-change).

## Code standards

- Write the observable completion condition before code.
- Reuse existing functions, scripts, and fields; explain why a new abstraction is necessary.
- Keep the kernel small: put conversation strategy in the skill and only real constraints in Python.
- Use comments for reasons: receipts, locks, revisions, atomic writes, cancellation, recovery, and path boundaries.
- Preserve task/call identity and failure context; distinguish permissions, network, format, conflicts, and unknown results.
- Never commit credentials, instance data, logs, or generated artifacts.
- Update the user manual for commands and the design notes for observable behavior.

## Tests

- Add a repeatable regression or boundary test for bug fixes.
- Cover the real entry, a failure path, cancellation/retry, or a permission boundary.
- Use temporary instances and synthetic data for memory, workflow, migration, and adoption tests.
- A real host, browser, WeChat account, or external endpoint claim needs one real round trip; otherwise mark it unverified.

## Before committing

```sh
make check
make acceptance
make build          # packaging/release changes
git diff --check
```

Also verify links and commands, `--help` for new commands, host-only and `--cli` installs, no secrets or generated files, and the delivery note with design behavior, commands/results, and unverified items.

## Release

Follow the [development guide](development.en.md) and [CHANGELOG](../../CHANGELOG.md). Tag only merged main; the Release workflow builds and uploads wheel/sdist from the tag. Main CI, `make check`, acceptance, and clean-wheel checks must pass first.

## Contributing and security

- [Contributing](../CONTRIBUTING.en.md)
- [Security](../SECURITY.en.md)
- [Code of Conduct](../CODE_OF_CONDUCT.en.md)
