# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project Overview

**soft-ue-cli** is a Python CLI tool and MCP server for controlling Unreal Engine 5 via the SoftUEBridge plugin. It gives LLM agents 120+ commands to spawn actors, edit Blueprints, inspect materials/MetaSounds, build UMG screens, read/patch UE config files, run PIE sessions, capture screenshots, and parse local Unreal asset files offline.

- **Two connection paths**: a live HTTP/JSON-RPC bridge to the SoftUEBridge plugin inside a running UE editor/PIE/cooked build, and an offline local path that parses `.uasset`, `.uexp`, `.ini`, `.uproject`, `.uplugin`, and `BuildConfiguration.xml` directly.
- **Engine targets**: primary development target is UE 5.8; UE 5.7 compatibility is maintained.
- **Upstream repo**: https://github.com/softdaddy-o/soft-ue-cli

## Tech Stack

- Python >= 3.10 (3.10–3.13 supported)
- Build backend: hatchling
- Runtime dependencies: `httpx`, `Pillow`; optional extra `mcp>=1.2` for MCP server mode
- Tests: pytest (test files in `tests/`, mirroring `soft_ue_cli/` module names)
- No configured linter/formatter (no ruff/black/mypy config) — match existing style

## Setup, Build, and Test

```bash
# Install in editable mode with MCP extra
pip install -e .[mcp]

# Run the CLI
soft-ue-cli --help
soft-ue-cli commands --json        # machine-readable command catalog

# Run tests
python -m pytest                   # full suite (testpaths = ["tests"])
python -m pytest tests/test_client.py   # single file

# Build the wheel
python -m build                    # or: pip wheel .
```

## Repository Structure

```
soft_ue_cli/            # Python package
├── __main__.py         # CLI entry point (argparse-based, console script soft-ue-cli)
├── client.py           # HTTP/JSON-RPC client for the SoftUEBridge server
├── command_catalog.py  # Source of truth for command status/requirements/metadata
├── command_aliases.py  # Alias prefixes and removed-command migrations
├── mcp_server.py       # MCP server mode (soft-ue-cli mcp-serve)
├── mcp_schema.py       # MCP tool schema generation
├── app_harness.py      # Creative-app orchestration harness: manifest config and read-only observability
├── discovery.py        # Bridge server URL/port discovery
├── diagnostics.py      # Handoff reports, build-log/P4 summaries, data-file validation
├── runtime_binary.py   # Packaged-bridge readiness and binary install/update plans
├── startup_recovery.py # Editor startup/crash recovery
├── surface_selector.py # UE 5.8 official MCP vs SoftUEBridge probing
├── config/             # .ini/.xml/.json UE config parsing, diff, merge, discovery
├── uasset/             # Offline .uasset/.uexp parsing (packages, properties, Blueprints)
├── skills/             # Markdown LLM workflow prompts shipped in the wheel
└── plugin_data/SoftUEBridge/  # UE C++ bridge plugin sources
tests/                  # pytest suite, one test_<module>.py per module
docs/                   # Diagrams (architecture.svg)
pyproject.toml          # Build, deps, wheel force-include list, pytest config
CHANGELOG.md            # Keep a Changelog format; "Unreleased" section on top
```

## Conventions and Gotchas

- **Adding a new skill file**: every markdown file in `soft_ue_cli/skills/` must also be listed in `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml` or it will be excluded from the wheel. There is a test (`tests/test_skills.py`) guarding this.
- **Command surface changes**: `commands` (backed by `command_catalog.py`) is the source of truth for command names, families, status, runtime/editor/PIE requirements, optional plugin requirements, and examples. Update it whenever adding, renaming, or removing commands; `tests/test_command_catalog.py` validates consistency.
- **Canonical command families**: new commands belong under the supported families (`umg`, `capture`, `mutable`, `statetree`, `metasound`, `anim`, `asset`, `blueprint`, `cloth`, `session`, `config`, `runtime`) rather than as one-off names.
- **Optional Unreal plugins**: workflows depending on optional UE plugins must compile without them and fail at runtime with structured `plugin_unavailable` errors.
- **Error reporting over MCP**: bridge failures must surface the real error reason in the MCP result, not a bare `exited with code 1`.
- **Session identity** (`client.set_session_label`) is intentionally thread-local — the MCP server is a long-lived process on pooled worker threads; do not convert it to a process global.
- **Versioning**: the version lives in `pyproject.toml` (`project.version`). Add changes under the `## Unreleased` heading in `CHANGELOG.md` (Keep a Changelog style).
- **Code style**: type hints on signatures, `from __future__ import annotations` at the top of modules, docstrings on public functions, no external deps beyond `httpx`/`Pillow` unless strictly necessary.

## Testing Guidelines

- Tests use pytest with `unittest.mock.patch` and httpx mock transports — no real Unreal Engine instance is required.
- Mirror the module under test: `soft_ue_cli/foo.py` → `tests/test_foo.py`.
- When changing bridge client behavior, patch `soft_ue_cli.client.get_server_url` rather than opening sockets.
- Run the full suite (`python -m pytest`) before submitting; keep it passing.

## PR Guidance

- Keep changes minimal and focused; update `CHANGELOG.md` under `Unreleased` for user-visible changes.
- Keep `README.md` command references in sync when the command surface changes.
- Do not commit secrets, engine credentials, or machine-specific paths.
