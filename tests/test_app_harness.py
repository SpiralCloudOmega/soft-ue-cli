"""Focused tests for the creative-app harness foundation."""

from __future__ import annotations

import http.client
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
    cua = next(adapter for adapter in manifest["adapters"] if adapter["id"] == "cua-driver")
    assert cua["kind"] == "mcp"
    assert cua["config"] == {"command": "cua-driver", "args": ["mcp"]}
    assert cua["capabilities"][0]["id"] == "desktop.visual-control"
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


@pytest.mark.parametrize(
    "config,error_location",
    [
        ({"command": None}, "config.command"),
        ({"url": None}, "config.url"),
        ({"command": "tool", "args": None}, "config.args"),
        ({"command": "tool", "args": [None]}, r"config.args\[0\]"),
        ({"command": "tool", "env": None}, "config.env"),
        ({"command": "tool", "env": {"TOKEN": None}}, "config.env.TOKEN"),
        ({"command": "tool", "required_paths": None}, "config.required_paths"),
        ({"command": "tool", "required_paths": [None]}, r"config.required_paths\[0\]"),
    ],
)
def test_manifest_validation_rejects_null_config_values(config, error_location):
    manifest = app_harness.default_manifest()
    manifest["adapters"][1]["config"] = config

    with pytest.raises(app_harness.ManifestError, match=error_location):
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
    cua = next(item for item in manifest["adapters"] if item["id"] == "cua-driver")
    orchestrator = manifest["orchestration"]["orchestrators"][0]
    blender["enabled"] = True
    blender["config"] = {
        "command": "blender-mcp",
        "args": ["--stdio"],
        "env": {"BLENDER_PORT": "9876"},
    }
    cua["enabled"] = True
    orchestrator["enabled"] = True
    orchestrator["config"] = {"command": "longhorizon"}

    config = app_harness.generate_mcp_config(manifest)

    assert config["schema"] == app_harness.MCP_CONFIG_SCHEMA
    assert set(config["mcpServers"]) == {"unreal-soft-ue", "blender-mcp", "cua-driver"}
    assert config["mcpServers"]["blender-mcp"] == {
        "command": "blender-mcp",
        "args": ["--stdio"],
        "env": {"BLENDER_PORT": "9876"},
    }
    assert config["mcpServers"]["cua-driver"] == {
        "command": "cua-driver",
        "args": ["mcp"],
    }
    assert "longhorizon-harness" not in config["mcpServers"]


def test_legacy_cua_kind_is_normalized_without_relaxing_other_adapter_kinds():
    manifest = app_harness.default_manifest()
    cua = next(item for item in manifest["adapters"] if item["id"] == "cua-driver")
    cua["kind"] = "computer-use"
    cua["enabled"] = True

    checked = app_harness.validate_manifest(manifest)

    checked_cua = next(item for item in checked["adapters"] if item["id"] == "cua-driver")
    assert checked_cua["kind"] == "mcp"
    assert cua["kind"] == "computer-use"
    assert app_harness.generate_mcp_config(manifest)["mcpServers"]["cua-driver"] == {
        "command": "cua-driver",
        "args": ["mcp"],
    }

    blender = next(item for item in manifest["adapters"] if item["id"] == "blender-mcp")
    blender["kind"] = "computer-use"
    with pytest.raises(app_harness.ManifestError, match="only supported for the legacy cua-driver"):
        app_harness.validate_manifest(manifest)


def test_generate_mcp_config_preserves_remote_url():
    manifest = app_harness.default_manifest()
    unity = next(item for item in manifest["adapters"] if item["id"] == "unity-mcp")
    unity["enabled"] = True
    unity["config"] = {"url": "http://127.0.0.1:8123/mcp"}

    config = app_harness.generate_mcp_config(manifest)

    assert config["mcpServers"]["unity-mcp"] == {
        "url": "http://127.0.0.1:8123/mcp"
    }


def test_generate_mcp_config_rejects_null_command_instead_of_dropping_url():
    manifest = app_harness.default_manifest()
    unity = next(item for item in manifest["adapters"] if item["id"] == "unity-mcp")
    unity["enabled"] = True
    unity["config"] = {
        "command": None,
        "url": "http://127.0.0.1:8123/mcp",
    }

    with pytest.raises(app_harness.ManifestError, match=r"config\.command"):
        app_harness.generate_mcp_config(manifest)


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
    manifest["adapters"][1]["provenance"][
        "reference_url"
    ] = "https://example.test/project?api_key=reference-secret#private"
    manifest["adapters"][1]["config"] = {
        "url": "https://example.test/mcp/path?token=config-secret#session"
    }
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
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]

    with urllib.request.urlopen(f"{dashboard}/api/status", timeout=2) as response:
        status = json.load(response)
        assert status["schema"] == app_harness.STATUS_SCHEMA

    with urllib.request.urlopen(f"{dashboard}/api/manifest", timeout=2) as response:
        payload = json.load(response)
        assert payload["schema"] == app_harness.DASHBOARD_MANIFEST_SCHEMA
        assert payload["manifest"]["adapters"][0]["config"]["env"]["TOKEN"] == "<redacted>"
        assert payload["manifest"]["adapters"][1]["config"]["url"] == (
            "https://example.test/mcp/path"
        )
        assert payload["manifest"]["adapters"][1]["provenance"]["reference_url"] == (
            "https://example.test/project"
        )
        assert "super-secret" not in json.dumps(payload)
        assert "config-secret" not in json.dumps(payload)
        assert "reference-secret" not in json.dumps(payload)

    request = urllib.request.Request(f"{dashboard}/api/status", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 405

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{dashboard}/README.md", timeout=2)
    assert exc.value.code == 404


def test_dashboard_rejects_non_loopback_missing_and_malformed_hosts(dashboard):
    port = int(dashboard.rsplit(":", 1)[1])

    request = urllib.request.Request(
        f"{dashboard}/api/status",
        headers={"Host": "attacker.example"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 403
    assert exc.value.headers["X-Frame-Options"] == "DENY"

    request = urllib.request.Request(
        f"{dashboard}/api/status",
        headers={"Host": f"localhost:{port}"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 200

    request = urllib.request.Request(
        f"{dashboard}/api/status",
        headers={"Host": "localhost"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 403

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    connection.putrequest("GET", "/api/status", skip_host=True)
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 400
    response.read()
    connection.close()

    request = urllib.request.Request(
        f"{dashboard}/api/status",
        headers={"Host": "localhost:not-a-port"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=2)
    assert exc.value.code == 400


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
