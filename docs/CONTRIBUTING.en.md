# Contributing to aiverywhere

[简体中文](CONTRIBUTING.md) | **English**

Read the [development guide](development/development.en.md) and the [design notes](development/design.md) (Chinese) for the area you want to change first. Describe the entry point, the task the user brings, and how completion can be observed. Prefer existing models, tools, and skills. New code needs a verifiable runtime responsibility.

## Development environment

From the project root on macOS or Linux:

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
ruff check .
```

Tests use temporary directories, synthetic material, and mock endpoints. When changing storage or the console, verify editing, stale-revision conflicts, deletion, and the read-only log from the real entry point. When changing installation, configuration, or packaging, also verify:

- Running `install.sh` in a temporary `HOME` for both the host-only and `--cli` paths.
- Reinstallation keeps existing `data/`; the project skill link is idempotent; a custom install root can be located through the project link.
- Installing the built wheel outside the source tree, checking `SKILL.md`, static assets, and both the `aiverywhere` and `python -m aiverywhere` entries.
- The configuration wizard never prints secrets, and `config.json` stays at mode `0600`.

```sh
make build
python -m pip install build twine
twine check dist/*
```

## Pull requests

Use the [PR template](../.github/PULL_REQUEST_TEMPLATE.md) and include acceptance scenarios, actual results, and open verification items. Persistent data and local credentials stay in `data/` and must not be committed. When a user-visible behavior changes, update the design notes and the installation or usage documentation together.

Read the [Code of Conduct](CODE_OF_CONDUCT.en.md) before joining discussions. Report security issues privately as described in the [security policy](SECURITY.en.md). [MIT License](../LICENSE)
