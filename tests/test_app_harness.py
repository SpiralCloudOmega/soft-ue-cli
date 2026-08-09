"""Focused tests for the creative-app harness foundation."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from soft_ue_cli import app_harness
from soft_ue_cli.__main__ import (
    build_parser,
    cmd_harness_init,
    cmd_harness_mcp_config,
    cmd_harness_status,
)
from soft_ue_cli.mcp_schema import extract_tools


def test_default_manifest_inventory_is_versioned_and_credential_free():
    manifest = app_harness.validate_manifest(app_harness.default_manifest())
    adapter_ids = {adapter["id"] for adapter in manifest["adapters"]}
    orchestrator_ids = {
        item["id"] for item in manifest["orchestration"]["orchestrators"]
    }

    assert manifest["schema"] == app_harness.MANIFEST_SCHEMA
    assert manifest["version"] == 1
    assert adapter_ids == {
        "unreal-soft-ue",
        "blender-mcp",
        "unity-mcp",
        "cua-driver",
    }
    assert orchestrator_ids == {"longhorizon-harness"}
    assert all(
        not adapter["config"].get("env")
        for adapter in manifest["adapters"]
    )


def test_manifest_validation_is_strict_and_requires_enabled_mcp_configuration():
    manifest = app_harness.default_manifest()
    manifest["unexpected"] = True
    with pytest.raises(app_harness.ManifestError, match="unknown field"):
        app_harness.validate_manifest(manifest)

    manifest = app_harness.default_manifest()
    unity = next(item for item in manifest["adapters"] if item["id"] == "unity-mcp")
    unity["enabled"] = True
    with pytest.raises(app_harness.ManifestError, match="requires command or url"):
        app_harness.validate_manifest(manifest)


def test_load_manifest_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "harness.json"
    path.write_text(
        '{"schema":"soft-ue.app-harness.manifest.v1","schema":"duplicate"}',
        encoding="utf-8",
    )

    with pytest.raises(app_harness.ManifestError, match="duplicate key"):
        app_harness.load_manifest(path)


def test_initialize_manifest_does_not_overwrite_without_force(tmp_path):
    path = tmp_path / "config" / "harness.json"
    result = app_harness.initialize_manifest(path)
    original = path.read_text(encoding="utf-8")

    assert result["schema"] == "soft-ue.app-harness.init.v1"
    assert app_harness.load_manifest(path)["schema"] == app_harness.MANIFEST_SCHEMA
    with pytest.raises(app_harness.ManifestError, match="already exists"):
        app_harness.initialize_manifest(path)
    assert path.read_text(encoding="utf-8") == original

    forced = app_harness.initialize_manifest(path, force=True)
    assert forced["forced"] is True


def test_generate_mcp_config_includes_only_enabled_mcp_adapters():
    manifest = app_harness.default_manifest()
    blender = next(item for item in manifest["adapters"] if item["id"] == "blender-mcp")
    blender["enabled"] = True
    blender["config"] = {
        "command": "blender-mcp",
        "args": ["--stdio"],
        "env": {"BLENDER_PORT": "9876"},
    }

    config = app_harness.generate_mcp_config(manifest)

    assert config["schema"] == app_harness.MCP_CONFIG_SCHEMA
    assert set(config["mcpServers"]) == {"unreal-soft-ue", "blender-mcp"}
    assert config["mcpServers"]["blender-mcp"] == {
        "command": "blender-mcp",
        "args": ["--stdio"],
        "env": {"BLENDER_PORT": "9876"},
    }
    assert "longhorizon-harness" not in config["mcpServers"]
    assert "cua-driver" not in config["mcpServers"]


def test_generate_mcp_config_preserves_remote_url():
    manifest = app_harness.default_manifest()
    unity = next(item for item in manifest["adapters"] if item["id"] == "unity-mcp")
    unity["enabled"] = True
    unity["config"] = {"url": "http://127.0.0.1:8123/mcp"}

    config = app_harness.generate_mcp_config(manifest)

    assert config["mcpServers"]["unity-mcp"] == {
        "url": "http://127.0.0.1:8123/mcp"
    }


def test_status_checks_executable_paths_and_injected_unreal_health(tmp_path):
    manifest = app_harness.default_manifest()
    unreal = next(item for item in manifest["adapters"] if item["id"] == "unreal-soft-ue")
    unreal["config"]["required_paths"] = ["project"]
    (tmp_path / "project").mkdir()
    calls = []

    status = app_harness.build_status(
        manifest,
        base_dir=tmp_path,
        health_probe=lambda: calls.append("probe") or {"status": "ok"},
    )

    unreal_status = next(item for item in status["adapters"] if item["id"] == "unreal-soft-ue")
    assert status["schema"] == app_harness.STATUS_SCHEMA
    assert status["ready"] is True
    assert unreal_status["ready"] is True
    assert {check["type"] for check in unreal_status["checks"]} == {
        "executable",
        "path",
        "health",
    }
    assert calls == ["probe"]


def test_status_reports_probe_failure_without_exposing_probe_payload():
    status = app_harness.build_status(
        app_harness.default_manifest(),
        health_probe=lambda: {"error": "secret server detail"},
    )

    unreal = next(item for item in status["adapters"] if item["id"] == "unreal-soft-ue")
    health = next(check for check in unreal["checks"] if check["type"] == "health")
    assert unreal["ready"] is False
    assert health["detail"] == "health check failed"
    assert "secret" not in json.dumps(status)


@pytest.fixture
def dashboard(tmp_path):
    path = tmp_path / "harness.json"
    manifest = app_harness.default_manifest()
    manifest["adapters"][0]["config"]["env"] = {"TOKEN": "super-secret"}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    server = app_harness.create_dashboard_server(
        path,
        port=0,
        health_probe=lambda: {"status": "ok"},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_factory_binds_loopback_and_serves_read_only_endpoints(dashboard):
    with urllib.request.urlopen(f"{dashboard}/", timeout=2) as response:
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert "Creative App Harness" in page
        assert "https://" not in page

    with urllib.request.urlopen(f"{dashboard}/api/status", timeout=2) as response:
        status = json.load(response)
        assert status["schema"] == app_harness.STATUS_SCHEMA

    with urllib.request.urlopen(f"{dashboard}/api/manifest", timeout=2) as response:
        payload = json.load(response)
        assert payload["schema"] == app_harness.DASHBOARD_MANIFEST_SCHEMA
        assert payload["manifest"]["adapters"][0]["config"]["env"]["TOKEN"] == "<redacted>"
        assert "super-secret" not in json.dumps(payload)

    request = urllib.request.Request(f"{dashboard}/api/status", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 405

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{dashboard}/README.md", timeout=2)
    assert exc.value.code == 404


def test_harness_cli_parser_and_json_handlers(tmp_path, capsys, monkeypatch):
    path = tmp_path / "harness.json"
    init_args = build_parser().parse_args(
        ["harness", "init", "--manifest", str(path)]
    )
    assert init_args.harness_action == "init"
    cmd_harness_init(init_args)
    assert json.loads(capsys.readouterr().out)["schema"] == "soft-ue.app-harness.init.v1"

    monkeypatch.setattr(
        "soft_ue_cli.__main__.health_check",
        lambda timeout: {"status": "ok"},
    )
    status_args = build_parser().parse_args(
        ["harness", "status", "--manifest", str(path)]
    )
    cmd_harness_status(status_args)
    assert json.loads(capsys.readouterr().out)["schema"] == app_harness.STATUS_SCHEMA

    config_args = build_parser().parse_args(
        ["harness", "mcp-config", "--manifest", str(path)]
    )
    cmd_harness_mcp_config(config_args)
    assert json.loads(capsys.readouterr().out)["schema"] == app_harness.MCP_CONFIG_SCHEMA


def test_harness_safe_leaves_are_mcp_tools_but_serve_is_cli_only():
    tools = {tool["name"]: tool for tool in extract_tools()}

    assert {"harness init", "harness status", "harness mcp-config"} <= set(tools)
    assert "harness serve" not in tools
    assert tools["harness init"]["func"] is cmd_harness_init


def test_manifest_validation_returns_defensive_copy():
    source = app_harness.default_manifest()
    checked = app_harness.validate_manifest(source)
    checked["adapters"][0]["name"] = "Changed"

    assert source["adapters"][0]["name"] == "Built-in Unreal MCP"
