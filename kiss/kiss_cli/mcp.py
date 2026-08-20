"""Discover and configure MCP connections without exposing their secrets."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

GITHUB_SETUP_URL = "https://github.com/github/github-mcp-server"


def _codex(home: Path) -> list[dict]:
    path = home / ".codex" / "config.toml"
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out = []
    for name, config in (doc.get("mcp_servers") or {}).items():
        if not isinstance(config, dict):
            continue
        out.append({"name": str(name), "client": "codex",
                    "transport": "remote" if config.get("url") else "stdio"})
    return out


def _claude(home: Path) -> list[dict]:
    path = home / ".claude.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for name, config in (doc.get("mcpServers") or {}).items():
        if not isinstance(config, dict):
            continue
        out.append({"name": str(name), "client": "claude",
                    "transport": "remote" if config.get("url") else "stdio"})
    return out


def discover(home: Path | None = None) -> list[dict]:
    """Return connection names and clients, never command args, headers or env."""
    home = Path(home or Path.home())
    merged: dict[str, dict] = {}
    for item in [*_codex(home), *_claude(home)]:
        key = item["name"].lower()
        target = merged.setdefault(key, {
            "name": item["name"], "clients": [], "transports": [],
            "configured": True,
        })
        if item["client"] not in target["clients"]:
            target["clients"].append(item["client"])
        if item["transport"] not in target["transports"]:
            target["transports"].append(item["transport"])
    return sorted(merged.values(), key=lambda item: item["name"].lower())


def status() -> dict:
    connections = discover()
    github = next((item for item in connections
                   if "github" in item["name"].lower()), None)
    codex = shutil.which("codex")
    native = shutil.which("github-mcp-server")
    docker = shutil.which("docker")
    return {
        "connections": connections,
        "github": {
            "configured": bool(github),
            "clients": github["clients"] if github else [],
            "codex_available": bool(codex),
            "runtime": "native" if native else "docker" if docker else None,
            "can_configure_codex": bool(codex and (native or docker)),
            "token_in_environment": bool(os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")),
            "setup_url": GITHUB_SETUP_URL,
        },
        "direct_api_support": False,
        "note": ("Configured MCPs are inherited by new local-agent processes. "
                 "Direct API providers currently use GeoForge's typed tools only."),
    }


def configure_github_for_codex() -> dict:
    """Add GitHub's official local MCP server to Codex after an explicit click."""
    current = status()
    if current["github"]["configured"] and "codex" in current["github"]["clients"]:
        return {"ok": True, "already_configured": True}
    codex = shutil.which("codex")
    if not codex:
        raise OSError("Codex CLI is not installed")
    native = shutil.which("github-mcp-server")
    docker = shutil.which("docker")
    if native:
        server = [native, "stdio"]
    elif docker:
        # Official GitHub image: browser OAuth on first use, loopback-only
        # callback. No token is copied into GeoForge or the Codex config.
        server = [docker, "run", "-i", "--rm", "-p", "127.0.0.1:8085:8085",
                  "-e", "GITHUB_OAUTH_CALLBACK_PORT=8085",
                  "ghcr.io/github/github-mcp-server"]
    else:
        raise OSError("Install the official github-mcp-server binary or Docker first")
    result = subprocess.run(
        [codex, "mcp", "add", "github", "--", *server],
        capture_output=True, text=True, timeout=60, errors="replace",
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise OSError(f"Codex could not add GitHub MCP: {detail}")
    return {"ok": True, "already_configured": False,
            "message": "GitHub MCP is configured. First use will open GitHub login."}


def prompt_block(names: list[str] | None, *, client: str, direct_api: bool) -> str:
    selected = {str(name).lower() for name in (names or [])}
    if not selected:
        return ""
    connections = [item for item in discover() if item["name"].lower() in selected]
    lines = ["[MCP CONNECTIONS SELECTED FOR THIS CHAT]"]
    if direct_api:
        lines.append("Direct API mode cannot call local MCP servers in this beta. Say so plainly if the task needs one; do not pretend to have used it.")
    for item in connections:
        available = client in item["clients"] and not direct_api
        lines.append(f"- {item['name']}: {'available' if available else 'not available'} through {client}; configured clients: {', '.join(item['clients'])}")
    return "\n".join(lines)
