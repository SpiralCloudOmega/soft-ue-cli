"""Configuration and read-only observability for creative-app orchestration."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import webbrowser
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit


MANIFEST_SCHEMA = "soft-ue.app-harness.manifest.v1"
STATUS_SCHEMA = "soft-ue.app-harness.status.v1"
MCP_CONFIG_SCHEMA = "soft-ue.app-harness.mcp-config.v1"
DASHBOARD_MANIFEST_SCHEMA = "soft-ue.app-harness.dashboard-manifest.v1"
DEFAULT_MANIFEST_PATH = Path(".soft-app-harness") / "harness.json"
MAX_MANIFEST_BYTES = 1_048_576

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CAPABILITY_ACCESS = {"read", "read-write", "orchestrate"}
_ADAPTER_KINDS = {"mcp"}
_LEGACY_CUA_KIND = "computer-use"
_CONFIG_KEYS = {"command", "args", "env", "url", "required_paths"}
_PROVENANCE_KEYS = {"source", "reference_url"}
_CAPABILITY_KEYS = {"id", "description", "access"}
_ADAPTER_KEYS = {"id", "name", "kind", "enabled", "capabilities", "provenance", "config", "health_probe"}
_ORCHESTRATOR_KEYS = {"id", "name", "kind", "enabled", "capabilities", "provenance", "config"}


class ManifestError(ValueError):
    """Raised when a harness manifest is malformed or unsafe to consume."""


def _capability(capability_id: str, description: str, access: str) -> dict[str, str]:
    return {"id": capability_id, "description": description, "access": access}


def default_manifest() -> dict[str, Any]:
    """Return a fresh version-one harness inventory with no credentials."""
    return {
        "schema": MANIFEST_SCHEMA,
        "version": 1,
        "adapters": [
            {
                "id": "unreal-soft-ue",
                "name": "Built-in Unreal MCP",
                "kind": "mcp",
                "enabled": True,
                "capabilities": [
                    _capability(
                        "unreal.structured-control",
                        "Structured Unreal editor, runtime, inspection, capture, and verification tools.",
                        "read-write",
                    )
                ],
                "provenance": {
                    "source": "built-in",
                    "reference_url": "https://github.com/softdaddy-o/soft-ue-cli",
                },
                "config": {
                    "command": sys.executable,
                    "args": ["-m", "soft_ue_cli", "mcp-serve"],
                    "env": {},
                    "required_paths": [],
                },
                "health_probe": "soft-ue-bridge",
            },
            {
                "id": "blender-mcp",
                "name": "Blender MCP",
                "kind": "mcp",
                "enabled": False,
                "capabilities": [
                    _capability(
                        "blender.structured-control",
                        "External structured Blender scene and content operations.",
                        "read-write",
                    )
                ],
                "provenance": {
                    "source": "external",
                    "reference_url": "https://github.com/ahujasid/blender-mcp",
                },
                "config": {},
            },
            {
                "id": "unity-mcp",
                "name": "Unity MCP",
                "kind": "mcp",
                "enabled": False,
                "capabilities": [
                    _capability(
                        "unity.structured-control",
                        "External structured Unity editor operations when a server is configured.",
                        "read-write",
                    )
                ],
                "provenance": {
                    "source": "external",
                    "reference_url": "https://github.com/IvanMurzak/Unity-MCP",
                },
                "config": {},
            },
            {
                "id": "cua-driver",
                "name": "Cua Driver computer use",
                "kind": "mcp",
                "enabled": False,
                "capabilities": [
                    _capability(
                        "desktop.visual-control",
                        "Visual computer-use fallback for unsupported application interactions.",
                        "read-write",
                    )
                ],
                "provenance": {
                    "source": "external",
                    "reference_url": "https://github.com/trycua/cua",
                },
                "config": {
                    "command": "cua-driver",
                    "args": ["mcp"],
                },
            },
        ],
        "orchestration": {
            "strategy": "manager-executor-auditor",
            "orchestrators": [
                {
                    "id": "longhorizon-harness",
                    "name": "LongHorizon Harness",
                    "kind": "orchestrator",
                    "enabled": False,
                    "capabilities": [
                        _capability(
                            "workflow.durable-orchestration",
                            "Durable Manager, Executor, and Auditor workflow coordination.",
                            "orchestrate",
                        )
                    ],
                    "provenance": {
                        "source": "external",
                        "reference_url": "https://github.com/AMAP-ML/LongHorizon-Harness",
                    },
                    "config": {},
                }
            ],
        },
    }


def _expect_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{location} must be an object")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ManifestError(f"{location} contains unknown field(s): {', '.join(unknown)}")


def _expect_string(value: Any, location: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ManifestError(f"{location} must be a non-empty string")
    return value


def _validate_id(value: Any, location: str) -> str:
    identifier = _expect_string(value, location)
    if not _ID_RE.fullmatch(identifier):
        raise ManifestError(f"{location} must use lowercase kebab-case")
    return identifier


def _validate_url(value: Any, location: str) -> str:
    url = _expect_string(value, location)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ManifestError(f"{location} must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ManifestError(f"{location} must not contain credentials")
    return url


def _validate_capabilities(value: Any, location: str) -> None:
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{location} must be a non-empty array")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item_location = f"{location}[{index}]"
        item = _expect_object(raw, item_location)
        _reject_unknown(item, _CAPABILITY_KEYS, item_location)
        if set(item) != _CAPABILITY_KEYS:
            raise ManifestError(f"{item_location} requires id, description, and access")
        capability_id = _expect_string(item["id"], f"{item_location}.id")
        if capability_id in seen:
            raise ManifestError(f"{location} contains duplicate capability id: {capability_id}")
        seen.add(capability_id)
        _expect_string(item["description"], f"{item_location}.description")
        if item["access"] not in _CAPABILITY_ACCESS:
            raise ManifestError(
                f"{item_location}.access must be one of: {', '.join(sorted(_CAPABILITY_ACCESS))}"
            )


def _validate_provenance(value: Any, location: str) -> None:
    provenance = _expect_object(value, location)
    _reject_unknown(provenance, _PROVENANCE_KEYS, location)
    if set(provenance) != _PROVENANCE_KEYS:
        raise ManifestError(f"{location} requires source and reference_url")
    if provenance["source"] not in {"built-in", "external", "custom"}:
        raise ManifestError(f"{location}.source must be built-in, external, or custom")
    _validate_url(provenance["reference_url"], f"{location}.reference_url")


def _validate_string_list(value: Any, location: str) -> None:
    if not isinstance(value, list):
        raise ManifestError(f"{location} must be an array")
    for index, item in enumerate(value):
        _expect_string(item, f"{location}[{index}]")


def _validate_config(value: Any, location: str, *, enabled: bool, kind: str) -> None:
    config = _expect_object(value, location)
    _reject_unknown(config, _CONFIG_KEYS, location)
    has_command = "command" in config
    has_url = "url" in config
    command = _expect_string(config["command"], f"{location}.command") if has_command else None
    url = _validate_url(config["url"], f"{location}.url") if has_url else None
    if has_command and has_url:
        raise ManifestError(f"{location} cannot contain both command and url")
    if "args" in config:
        _validate_string_list(config["args"], f"{location}.args")
        if not has_command:
            raise ManifestError(f"{location}.args requires command")
    if "required_paths" in config:
        _validate_string_list(config["required_paths"], f"{location}.required_paths")
    if "env" in config:
        env = _expect_object(config["env"], f"{location}.env")
        if not has_command:
            raise ManifestError(f"{location}.env requires command")
        for key, env_value in env.items():
            _expect_string(key, f"{location}.env key")
            _expect_string(env_value, f"{location}.env.{key}", allow_empty=True)
    if enabled and kind == "mcp" and command is None and url is None:
        raise ManifestError(f"{location} requires command or url when its MCP adapter is enabled")
    if enabled and kind != "mcp" and command is None:
        raise ManifestError(f"{location} requires command when enabled")


def _validate_inventory_item(
    raw: Any,
    location: str,
    *,
    orchestrator: bool,
) -> str:
    item = _expect_object(raw, location)
    allowed = _ORCHESTRATOR_KEYS if orchestrator else _ADAPTER_KEYS
    _reject_unknown(item, allowed, location)
    required = {"id", "name", "kind", "enabled", "capabilities", "provenance", "config"}
    missing = sorted(required - set(item))
    if missing:
        raise ManifestError(f"{location} missing required field(s): {', '.join(missing)}")
    identifier = _validate_id(item["id"], f"{location}.id")
    _expect_string(item["name"], f"{location}.name")
    if not isinstance(item["enabled"], bool):
        raise ManifestError(f"{location}.enabled must be a boolean")
    kind = _expect_string(item["kind"], f"{location}.kind")
    if orchestrator:
        if kind != "orchestrator":
            raise ManifestError(f"{location}.kind must be orchestrator")
    elif kind == _LEGACY_CUA_KIND:
        if identifier != "cua-driver":
            raise ManifestError(
                f"{location}.kind computer-use is only supported for the legacy cua-driver entry"
            )
        item["kind"] = "mcp"
    elif kind not in _ADAPTER_KINDS:
        raise ManifestError(f"{location}.kind must be mcp")
    _validate_capabilities(item["capabilities"], f"{location}.capabilities")
    _validate_provenance(item["provenance"], f"{location}.provenance")
    _validate_config(
        item["config"],
        f"{location}.config",
        enabled=item["enabled"],
        kind=item["kind"],
    )
    if not orchestrator and "health_probe" in item:
        if item["health_probe"] != "soft-ue-bridge":
            raise ManifestError(f"{location}.health_probe must be soft-ue-bridge")
        if item["kind"] != "mcp":
            raise ManifestError(f"{location}.health_probe is only valid for MCP adapters")
    return identifier


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Strictly validate and return a normalized defensive copy of a manifest."""
    root = _expect_object(manifest, "manifest")
    _reject_unknown(root, {"schema", "version", "adapters", "orchestration"}, "manifest")
    if set(root) != {"schema", "version", "adapters", "orchestration"}:
        raise ManifestError("manifest requires schema, version, adapters, and orchestration")
    if root["schema"] != MANIFEST_SCHEMA or root["version"] != 1:
        raise ManifestError(f"unsupported manifest schema/version; expected {MANIFEST_SCHEMA} version 1")
    if not isinstance(root["adapters"], list):
        raise ManifestError("manifest.adapters must be an array")
    checked = copy.deepcopy(root)
    orchestration = _expect_object(checked["orchestration"], "manifest.orchestration")
    _reject_unknown(orchestration, {"strategy", "orchestrators"}, "manifest.orchestration")
    if set(orchestration) != {"strategy", "orchestrators"}:
        raise ManifestError("manifest.orchestration requires strategy and orchestrators")
    _expect_string(orchestration["strategy"], "manifest.orchestration.strategy")
    if not isinstance(orchestration["orchestrators"], list):
        raise ManifestError("manifest.orchestration.orchestrators must be an array")

    identifiers: set[str] = set()
    for index, adapter in enumerate(checked["adapters"]):
        identifier = _validate_inventory_item(adapter, f"manifest.adapters[{index}]", orchestrator=False)
        if identifier in identifiers:
            raise ManifestError(f"duplicate inventory id: {identifier}")
        identifiers.add(identifier)
    for index, orchestrator in enumerate(orchestration["orchestrators"]):
        identifier = _validate_inventory_item(
            orchestrator,
            f"manifest.orchestration.orchestrators[{index}]",
            orchestrator=True,
        )
        if identifier in identifiers:
            raise ManifestError(f"duplicate inventory id: {identifier}")
        identifiers.add(identifier)
    return checked


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"manifest JSON contains duplicate key: {key}")
        result[key] = value
    return result


def load_manifest(path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load UTF-8 JSON from *path* and strictly validate it."""
    manifest_path = Path(path)
    try:
        size = manifest_path.stat().st_size
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {manifest_path}: {exc}") from exc
    if size > MAX_MANIFEST_BYTES:
        raise ManifestError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    try:
        text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except ManifestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid manifest {manifest_path}: {exc}") from exc
    return validate_manifest(data)


def initialize_manifest(
    path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Create a default manifest, refusing to overwrite unless explicitly forced."""
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = validate_manifest(default_manifest())
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if force:
        replacement = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.new")
        try:
            with replacement.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(replacement, manifest_path)
        except OSError as exc:
            try:
                replacement.unlink()
            except OSError:
                pass
            raise ManifestError(f"cannot write manifest {manifest_path}: {exc}") from exc
    else:
        try:
            with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except FileExistsError as exc:
            raise ManifestError(
                f"manifest already exists: {manifest_path}; use --force to replace it"
            ) from exc
        except OSError as exc:
            raise ManifestError(f"cannot write manifest {manifest_path}: {exc}") from exc
    return {
        "schema": "soft-ue.app-harness.init.v1",
        "created": True,
        "forced": force,
        "path": str(manifest_path),
        "manifest_schema": MANIFEST_SCHEMA,
    }


def generate_mcp_config(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Generate client-ready ``mcpServers`` entries for enabled MCP adapters."""
    checked = validate_manifest(manifest)
    servers: dict[str, dict[str, Any]] = {}
    for adapter in checked["adapters"]:
        if adapter["kind"] != "mcp" or not adapter["enabled"]:
            continue
        config = adapter["config"]
        server: dict[str, Any] = {}
        command = config.get("command")
        url = config.get("url")
        if isinstance(command, str) and command.strip():
            server["command"] = command
            if "args" in config:
                server["args"] = list(config["args"])
            if "env" in config:
                server["env"] = dict(config["env"])
        elif isinstance(url, str) and url.strip():
            server["url"] = url
        else:
            raise ManifestError(
                f"enabled MCP adapter {adapter['id']} requires a valid command or url"
            )
        servers[adapter["id"]] = server
    return {"schema": MCP_CONFIG_SCHEMA, "mcpServers": servers}


def _is_windows_absolute(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or PureWindowsPath(value).is_absolute()


def _resolve_configured_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and not _is_windows_absolute(value):
        path = base_dir / path
    return path


def _executable_check(command: str, base_dir: Path) -> dict[str, Any]:
    looks_like_path = (
        "/" in command
        or "\\" in command
        or Path(command).is_absolute()
        or _is_windows_absolute(command)
    )
    if looks_like_path:
        path = _resolve_configured_path(command, base_dir)
        exists = path.is_file()
        executable = exists and (os.name == "nt" or os.access(path, os.X_OK))
        return {
            "type": "executable",
            "target": command,
            "ok": executable,
            "detail": "executable file found" if executable else "executable file not found or not executable",
        }
    resolved = shutil.which(command)
    return {
        "type": "executable",
        "target": command,
        "ok": resolved is not None,
        "detail": f"resolved to {resolved}" if resolved else "not found on PATH",
    }


def _item_status(
    item: Mapping[str, Any],
    *,
    base_dir: Path,
    health_probe: Callable[[], Mapping[str, Any]] | None,
) -> dict[str, Any]:
    config = item["config"]
    checks: list[dict[str, Any]] = []
    if "command" in config:
        checks.append(_executable_check(config["command"], base_dir))
    elif "url" in config:
        checks.append(
            {
                "type": "configuration",
                "target": config["url"],
                "ok": True,
                "detail": "remote MCP URL configured; no network probe performed",
            }
        )
    else:
        checks.append(
            {
                "type": "configuration",
                "target": "command-or-url",
                "ok": False,
                "detail": "not configured",
            }
        )
    for configured_path in config.get("required_paths", []):
        resolved = _resolve_configured_path(configured_path, base_dir)
        path_exists = resolved.exists()
        checks.append(
            {
                "type": "path",
                "target": configured_path,
                "ok": path_exists,
                "detail": "path found" if path_exists else "path not found",
            }
        )
    if item.get("health_probe") == "soft-ue-bridge":
        if health_probe is None:
            checks.append(
                {
                    "type": "health",
                    "target": "soft-ue-bridge",
                    "ok": False,
                    "detail": "health probe unavailable",
                }
            )
        else:
            try:
                health = health_probe()
                health_ok = isinstance(health, Mapping) and "error" not in health
                checks.append(
                    {
                        "type": "health",
                        "target": "soft-ue-bridge",
                        "ok": health_ok,
                        "detail": "healthy" if health_ok else "health check failed",
                    }
                )
            except Exception:
                checks.append(
                    {
                        "type": "health",
                        "target": "soft-ue-bridge",
                        "ok": False,
                        "detail": "health check failed",
                    }
                )
    configured = bool(config) and all(check["ok"] for check in checks if check["type"] != "health")
    ready = item["enabled"] and bool(checks) and all(check["ok"] for check in checks)
    return {
        "id": item["id"],
        "name": item["name"],
        "kind": item["kind"],
        "enabled": item["enabled"],
        "configured": configured,
        "ready": ready,
        "state": "ready" if ready else ("disabled" if not item["enabled"] else "not_ready"),
        "checks": checks,
    }


def build_status(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | os.PathLike[str] = ".",
    health_probe: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Inspect configuration and health without starting any configured program."""
    checked = validate_manifest(manifest)
    root = Path(base_dir)
    adapters = [
        _item_status(adapter, base_dir=root, health_probe=health_probe)
        for adapter in checked["adapters"]
    ]
    orchestrators = [
        _item_status(orchestrator, base_dir=root, health_probe=None)
        for orchestrator in checked["orchestration"]["orchestrators"]
    ]
    enabled = [entry for entry in (*adapters, *orchestrators) if entry["enabled"]]
    return {
        "schema": STATUS_SCHEMA,
        "manifest_schema": checked["schema"],
        "ready": bool(enabled) and all(entry["ready"] for entry in enabled),
        "strategy": checked["orchestration"]["strategy"],
        "adapters": adapters,
        "orchestrators": orchestrators,
    }


def _redact_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(manifest)
    inventory = [
        *redacted["adapters"],
        *redacted["orchestration"]["orchestrators"],
    ]
    for item in inventory:
        provenance_url = item["provenance"]["reference_url"]
        item["provenance"]["reference_url"] = _strip_url_secrets(provenance_url)
        config_url = item["config"].get("url")
        if isinstance(config_url, str):
            item["config"]["url"] = _strip_url_secrets(config_url)
        env = item["config"].get("env")
        if isinstance(env, dict):
            item["config"]["env"] = {key: "<redacted>" for key in env}
    return redacted


def _strip_url_secrets(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Creative App Harness</title>
<style>
:root{color-scheme:dark;background:#0b1020;color:#e7ecf5;font:15px system-ui,sans-serif}
body{max-width:1100px;margin:0 auto;padding:2rem}h1{margin-bottom:.3rem}p{color:#aab6cc}
#summary,.card{background:#151d30;border:1px solid #2b3853;border-radius:10px;padding:1rem}
#grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem;margin-top:1rem}
.row{display:flex;justify-content:space-between;gap:1rem}.ready{color:#61d095}.not_ready{color:#ff8d85}
.disabled{color:#aab6cc}code{overflow-wrap:anywhere}.check{font-size:.88rem;color:#aab6cc;margin-top:.45rem}
</style>
</head>
<body><h1>Creative App Harness</h1><p>Loopback-only, read-only adapter readiness.</p>
<section id="summary">Loading status…</section><main id="grid"></main>
<script>
"use strict";
const el=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n};
fetch("/api/status",{cache:"no-store"}).then(r=>r.json()).then(data=>{
 const summary=document.getElementById("summary");summary.textContent="";
 summary.append(el("strong",data.ready?"Harness ready":"Harness needs configuration",data.ready?"ready":"not_ready"));
 summary.append(el("div","Strategy: "+data.strategy));
 const grid=document.getElementById("grid");
 for(const item of [...data.adapters,...data.orchestrators]){
  const card=el("article","", "card");const row=el("div","", "row");
  row.append(el("strong",item.name));row.append(el("span",item.state,item.state));card.append(row);
  card.append(el("div",item.kind+" · "+item.id));
  for(const check of item.checks)card.append(el("div",(check.ok?"✓ ":"✗ ")+check.type+": "+check.detail,"check"));
  grid.append(card);
 }
}).catch(()=>{document.getElementById("summary").textContent="Status unavailable";});
</script></body></html>"""


def create_dashboard_server(
    manifest_path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH,
    *,
    port: int = 0,
    health_probe: Callable[[], Mapping[str, Any]] | None = None,
) -> ThreadingHTTPServer:
    """Create a loopback-bound read-only dashboard server without starting it."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer from 0 through 65535")
    path = Path(manifest_path)

    class DashboardHandler(BaseHTTPRequestHandler):
        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            super().end_headers()

        def _send_json(self, payload: Mapping[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _accept_loopback_host(self) -> bool:
            host_headers = self.headers.get_all("Host", [])
            if len(host_headers) != 1 or not host_headers[0]:
                self._send_json(
                    {
                        "schema": "soft-ue.app-harness.error.v1",
                        "error": "invalid_host",
                        "message": "a valid Host header is required",
                    },
                    status=400,
                )
                return False

            match = re.fullmatch(
                r"(?P<hostname>[A-Za-z0-9.-]+)(?::(?P<port>[0-9]{1,5}))?",
                host_headers[0],
            )
            if match is None:
                self._send_json(
                    {
                        "schema": "soft-ue.app-harness.error.v1",
                        "error": "invalid_host",
                        "message": "the Host header is malformed",
                    },
                    status=400,
                )
                return False

            hostname = match.group("hostname").lower()
            port_text = match.group("port")
            if port_text is not None and not 1 <= int(port_text) <= 65535:
                self._send_json(
                    {
                        "schema": "soft-ue.app-harness.error.v1",
                        "error": "invalid_host",
                        "message": "the Host header contains an invalid port",
                    },
                    status=400,
                )
                return False
            if (
                hostname in {"127.0.0.1", "localhost"}
                and port_text is not None
                and int(port_text) == self.server.server_port
            ):
                return True
            self._send_json(
                {
                    "schema": "soft-ue.app-harness.error.v1",
                    "error": "forbidden_host",
                    "message": "dashboard requests must use its loopback host and bound port",
                },
                status=403,
            )
            return False

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if not self._accept_loopback_host():
                return
            route = self.path.partition("?")[0]
            if route == "/":
                body = _DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route in {"/api/manifest", "/api/status"}:
                try:
                    manifest = load_manifest(path)
                    if route == "/api/manifest":
                        self._send_json(
                            {
                                "schema": DASHBOARD_MANIFEST_SCHEMA,
                                "manifest": _redact_manifest(manifest),
                            }
                        )
                    else:
                        self._send_json(
                            build_status(
                                manifest,
                                base_dir=path.parent,
                                health_probe=health_probe,
                            )
                        )
                except ManifestError as exc:
                    self._send_json(
                        {
                            "schema": "soft-ue.app-harness.error.v1",
                            "error": "invalid_manifest",
                            "message": str(exc),
                        },
                        status=500,
                    )
                return
            self._send_json(
                {
                    "schema": "soft-ue.app-harness.error.v1",
                    "error": "not_found",
                    "message": "read-only endpoint not found",
                },
                status=404,
            )

        def _reject_mutation(self) -> None:
            if not self._accept_loopback_host():
                return
            self._send_json(
                {
                    "schema": "soft-ue.app-harness.error.v1",
                    "error": "method_not_allowed",
                    "message": "dashboard is read-only",
                },
                status=405,
            )

        do_POST = _reject_mutation
        do_PUT = _reject_mutation
        do_PATCH = _reject_mutation
        do_DELETE = _reject_mutation

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    server.daemon_threads = True
    return server


def serve_dashboard(
    manifest_path: str | os.PathLike[str] = DEFAULT_MANIFEST_PATH,
    *,
    port: int = 8765,
    open_browser: bool = False,
    health_probe: Callable[[], Mapping[str, Any]] | None = None,
) -> None:
    """Serve the dashboard until interrupted."""
    server = create_dashboard_server(manifest_path, port=port, health_probe=health_probe)
    host, bound_port = server.server_address[:2]
    url = f"http://{host}:{bound_port}/"
    print(
        json.dumps(
            {
                "schema": "soft-ue.app-harness.serve.v1",
                "url": url,
                "manifest_path": str(manifest_path),
                "read_only": True,
            },
            indent=2,
        ),
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
