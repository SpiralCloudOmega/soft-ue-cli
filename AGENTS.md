# Contributor guide for coding agents

This file applies to the entire repository. Keep changes focused, preserve public
CLI compatibility, and update tests and documentation with behavior changes.

## Project overview

`soft-ue-cli` is a Python 3.10+ CLI and optional MCP server for controlling
Unreal Engine through the bundled SoftUEBridge plugin. Commands either call the
bridge over HTTP/JSON-RPC or operate locally on assets and configuration files.
Automation output is structured JSON unless a command explicitly documents a
human-readable mode.

## Repository map

- `soft_ue_cli/__main__.py`: argument parser, command handlers, and CLI entry point.
- `soft_ue_cli/client.py` and `discovery.py`: bridge transport and endpoint discovery.
- `soft_ue_cli/command_catalog.py`: public command metadata and requirements.
- `soft_ue_cli/command_aliases.py`: canonical command families and removed-command migrations.
- `soft_ue_cli/mcp_schema.py` and `mcp_server.py`: generated MCP schemas and server exposure.
- `soft_ue_cli/config/` and `soft_ue_cli/uasset/`: offline configuration and asset support.
- `soft_ue_cli/plugin_data/SoftUEBridge/`: packaged Unreal Engine C++ plugin.
- `soft_ue_cli/skills/`: Markdown prompts shipped in both source and wheel distributions.
- `tests/`: pytest coverage for Python behavior and packaged plugin source contracts.

## Setup and validation

```bash
python -m pip install -e .
python -m pytest -q
python -m soft_ue_cli --help
python -m soft_ue_cli commands --json
```

There is no configured formatter, linter, or type checker. Run the narrowest
relevant tests while iterating, then the full pytest suite. Tests must not
require a running Unreal Editor, bridge server, network connection, or GitHub
credentials; mock those boundaries.

## Change rules

### CLI and MCP commands

- Add or change arguments in the parser and keep the handler, command catalog,
  canonical aliases, MCP exposure, tests, and README examples synchronized.
- Preserve canonical nested command families. Removed flat commands belong in
  the migration metadata rather than being silently reintroduced.
- Keep successful automation output JSON-serializable and preserve the documented
  exit-code contract: `0` for success and `1` for command errors.
- Check `soft-ue-cli commands --json` after changing command metadata. MCP tools
  are derived from the argparse surface, but exclusions and schema overrides
  still need explicit review.

### SoftUEBridge plugin

- Keep Unreal Engine 5.8 as the main target while preserving maintained 5.7
  compatibility with narrow version guards where APIs differ.
- Do not use REGISTER_BRIDGE_TOOL for a new tool. Register tool classes from
  the owning module with `Registry.RegisterToolClass<UToolClass>()` so startup,
  shutdown, and hot-reload behavior remain explicit.
- Registration for any newly added UCLASS tool must be deferred through
  `OnPostEngineInit`; unregister delegates and tool classes during shutdown.
- Keep editor-only tools and dependencies in the editor module. Runtime code
  must continue to compile without editor-only headers or modules.
- Add source-contract tests for compatibility-sensitive plugin changes when a
  local Unreal build is not available.

### Skills and package data

- Every skill Markdown file needs frontmatter containing `name`, `description`,
  and `version`.
- Add each new skill to Hatch's wheel `force-include` table in `pyproject.toml`;
  source-checkout discovery alone does not prove that the wheel contains it.
- Keep skill examples on canonical commands and ensure destructive workflows
  include verification and cleanup.

## Safety and scope

- Never commit tokens, credentials, project-identifying data, generated Unreal
  build artifacts, or local `.soft-*` state.
- Treat bridge responses and local asset files as untrusted input. Retain
  timeouts, size limits, path validation, and structured error handling.
- Do not broaden a focused change into unrelated cleanup. Document any required
  live-editor verification that cannot run in the Python test environment.
