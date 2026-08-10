"""Repository paths shared by tests in monorepo and standalone layouts."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "cli" / "pyproject.toml").exists():
            return parent
        if (parent / "pyproject.toml").exists() and (parent / "soft_ue_cli").is_dir():
            return parent
    raise AssertionError("Could not locate repository root")


def cli_root() -> Path:
    root = repo_root()
    monorepo_cli = root / "cli"
    return monorepo_cli if (monorepo_cli / "pyproject.toml").exists() else root


def plugin_root() -> Path:
    root = repo_root()
    monorepo_plugin = root / "plugin" / "SoftUEBridge"
    if monorepo_plugin.is_dir():
        return monorepo_plugin
    return cli_root() / "soft_ue_cli" / "plugin_data" / "SoftUEBridge"


def skills_root() -> Path:
    return cli_root() / "soft_ue_cli" / "skills"
