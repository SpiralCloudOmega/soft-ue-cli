"""Guards for public package metadata and README freshness."""

from __future__ import annotations

import sys
import tomllib

from tests.repo_paths import cli_root, repo_root


_repo_root = repo_root
_cli_root = cli_root


def test_project_readme_metadata_points_at_public_readme():
    cli_root = _cli_root()
    pyproject = cli_root / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    readme_name = metadata["project"]["readme"]
    readme = cli_root / readme_name

    assert readme_name == "README.md"
    assert readme.exists()

    text = readme.read_text(encoding="utf-8")
    assert text.startswith("# soft-ue-cli")
    assert "Command Discovery And Taxonomy" in text
    assert "UE 5.8 MCP Positioning" in text
    assert "main development target is now **Unreal Engine 5.8**" in text
    assert "UE 5.7 compatibility remains maintained" in text


def test_readme_tool_count_claim_matches_current_mcp_surface():
    cli_root = _cli_root()
    sys.path.insert(0, str(cli_root))

    from soft_ue_cli.mcp_schema import extract_tools  # noqa: PLC0415

    readme = (cli_root / "README.md").read_text(encoding="utf-8")
    tool_count = len(extract_tools())

    assert tool_count >= 120
    assert "60+" not in readme
    assert "tools-60%2B" not in readme
    assert "commands-120%2B" in readme
    assert "120+" in readme
