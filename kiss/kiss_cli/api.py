"""The API driver: talk to a model directly instead of spawning an agent CLI.

The CLI driver reuses an agent the user has already installed and signed in, so
it needs no key and inherits that agent's tools. This driver is the other half:
an API key, and KISS owns the loop.

Two things follow from owning the loop, and they are the reason to have it:

* **The tools are typed.** The model asks for ``run_preflight`` or
  ``read_ki_file(path)``; it cannot express an arbitrary shell command. The
  permission question changes from "is this command safe" — undecidable from a
  string — to "is this argument in range", which is checkable.
* **It can stop and ask mid-turn.** A one-shot ``claude -p`` exits when the turn
  ends, so a CLI agent can only ask between turns. Here the loop is ours, so a
  request for approval can suspend it and resume on an answer.

No SDK dependency: both wire formats are a single POST of JSON, and taking a
dependency on two vendor SDKs to send one request each would be a poor trade for
a tool meant to install cleanly anywhere.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from . import skilllib, tls
from .presentation import activity_marker

TIMEOUT = 300


@dataclass
class ApiProvider:
    """One API endpoint and how to authenticate to it."""

    name: str
    label: str
    #: "anthropic" (native messages API) or "openai" (chat/completions shape)
    wire: str
    base_url: str
    env_key: str
    models: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    signup: str = ""

    def key(self) -> str | None:
        return os.environ.get(self.env_key) or None

    def available(self) -> bool:
        return bool(self.key())


#: Mirrors the provider table the HydroCraft backend already serves, so a key
#: that works there works here.
PROVIDERS: dict[str, ApiProvider] = {
    "anthropic": ApiProvider(
        name="anthropic", label="Claude (API)", wire="anthropic",
        base_url="https://api.anthropic.com/v1/messages",
        env_key="ANTHROPIC_API_KEY",
        models={"claude-sonnet-4-5": "claude-sonnet-4-5",
                "claude-opus-4-1": "claude-opus-4-1"},
        default_model="claude-sonnet-4-5",
        signup="https://console.anthropic.com/settings/keys",
    ),
    "deepseek": ApiProvider(
        name="deepseek", label="DeepSeek (API)", wire="openai",
        base_url="https://api.deepseek.com/chat/completions",
        env_key="DEEPSEEK_API_KEY",
        models={"deepseek-chat": "deepseek-chat",
                "deepseek-reasoner": "deepseek-reasoner"},
        default_model="deepseek-chat",
        signup="https://platform.deepseek.com/api_keys",
    ),
    "openai": ApiProvider(
        name="openai", label="OpenAI (API)", wire="openai",
        base_url="https://api.openai.com/v1/chat/completions",
        env_key="OPENAI_API_KEY",
        models={"gpt-4o": "gpt-4o", "gpt-4o-mini": "gpt-4o-mini"},
        default_model="gpt-4o",
        signup="https://platform.openai.com/api-keys",
    ),
    "openrouter": ApiProvider(
        name="openrouter", label="OpenRouter (API)", wire="openai",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        env_key="OPENROUTER_API_KEY",
        models={"claude-sonnet-4-5": "anthropic/claude-sonnet-4.5",
                "deepseek-chat": "deepseek/deepseek-chat"},
        default_model="deepseek-chat",
        signup="https://openrouter.ai/keys",
    ),
}


def available() -> list[ApiProvider]:
    return [p for p in PROVIDERS.values() if p.available()]


# --- the tools the model may call ------------------------------------------
#
# Deliberately typed and narrow. There is no `bash` here: a KI declares what a
# model needs, so the useful operations are enumerable, and enumerating them is
# what lets the permission layer check an argument instead of guessing at a
# command string.

def tool_schemas(ki, *, setup_mode: bool = False,
                 project_mode: bool = False) -> list[dict]:
    tools = [
        {
            "name": "read_ki_file",
            "description": (
                "Read a file from this model's Knowledge Infrastructure package "
                "(SKILL.md, dag.yaml, diagnostics/triplets, docs/, tools/). "
                "Always read SKILL.md before proposing how to run the model."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "path relative to the KI root, e.g. 'SKILL.md'"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_ki_files",
            "description": "List the files in this KI package, optionally under a subdirectory.",
            "input_schema": {
                "type": "object",
                "properties": {"subdir": {"type": "string"}},
            },
        },
        {
            "name": "run_preflight",
            "description": (
                "Run this KI's preflight_check.py and return its output. This is "
                "the authoritative answer to whether the model is ready to run."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_skills",
            "description": (
                "List the agent skills installed on this machine (name + one-line "
                "description). Skills are reusable instruction packages — use one "
                "when a task matches its description (plotting, statistics, "
                "literature review, document formats, ...)."
            ),
            "input_schema": {"type": "object",
                             "properties": {"query": {"type": "string",
                                            "description": "optional substring filter"}}},
        },
        {
            "name": "read_skill",
            "description": (
                "Read one installed skill's SKILL.md instructions by name. Read it "
                "before applying the skill; follow it like a procedure."
            ),
            "input_schema": {"type": "object",
                             "properties": {"name": {"type": "string"}},
                             "required": ["name"]},
        },
        {
            "name": "search_diagnostics",
            "description": (
                "Search this KI's diagnostics/triplets for an error keyword. Use "
                "this before debugging from first principles — the failure is "
                "often already catalogued with a verified remedy."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    ]
    if project_mode:
        tools += [
            {
                "name": "list_project_files",
                "description": (
                    "List files already present in this chat's local project. "
                    "Inspect these before asking the user to supply data."
                ),
                "input_schema": {"type": "object", "properties": {
                    "subdir": {"type": "string",
                               "description": "relative project directory, normally inputs"},
                }},
            },
            {
                "name": "read_project_file",
                "description": "Read a text file from this chat's local project.",
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                }, "required": ["path"]},
            },
            {
                "name": "write_project_file",
                "description": (
                    "Write a small prepared input, run configuration, provenance "
                    "record, or report inside the chat project. Use the KI's tools "
                    "for generated grids and large scientific files."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string",
                             "description": "relative path under inputs, runs, outputs, artifacts, or references"},
                    "content": {"type": "string"},
                }, "required": ["path", "content"]},
            },
            {
                "name": "run_ki_tool",
                "description": (
                    "Run one Python preparation tool shipped inside the selected KI. "
                    "Use this for data conversion, grid/soil/weather preparation, "
                    "configuration generation, validation, and model harness steps. "
                    "Arguments may reference this chat project, this KI package, or "
                    "the current KI's GeoForge-managed shared binaries directory. "
                    "Do not replace a KI tool with improvised calculations."
                ),
                "input_schema": {"type": "object", "properties": {
                    "tool_path": {"type": "string",
                                  "description": "Python file relative to the KI root and below a tools/ directory"},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string",
                            "description": "relative project working directory; defaults to project root"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                }, "required": ["tool_path"]},
            },
            {
                "name": "run_calibration",
                "description": (
                    "Run this KI's project calibration adapter through GeoForge's "
                    "bundled calibration engine. numpy, SPOTPY, and pymoo run "
                    "inside the app, not the user's system Python. Use only after "
                    "the real model, observations, adapter, and holdout definition "
                    "are ready. The full report and engine log are saved in the "
                    "chat project's calibration/runs directory."
                ),
                "input_schema": {"type": "object", "properties": {
                    "obs_shape_by_var": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": (
                            "Map every calibration target variable exactly as named "
                            "in calibration.yaml to its dag observation shape."
                        ),
                    },
                    "algorithm": {"type": "string", "enum": [
                        "dds", "sceua", "dream", "nsga2", "nsga3", "moead"]},
                    "budget": {"type": "integer", "minimum": 1, "maximum": 10000},
                    "seed": {"type": "integer"},
                    "determining_metric": {"type": "string"},
                }, "required": ["obs_shape_by_var"]},
            },
            {
                "name": "create_project_plot",
                "description": (
                    "Create a safe line, scatter, or bar plot in this chat's "
                    "artifacts folder. Use a relevant plotting/visualization skill "
                    "to choose an honest chart, then call this tool when the direct "
                    "API has no plotting runtime. GeoForge displays the SVG inline. "
                    "For a project CSV, prefer source_path plus x_column/y_column "
                    "instead of copying every data point through the model."
                ),
                "input_schema": {"type": "object", "properties": {
                    "output_path": {"type": "string",
                                    "description": "relative .svg path below artifacts/"},
                    "kind": {"type": "string", "enum": ["line", "scatter", "bar"]},
                    "title": {"type": "string"},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "y2_label": {"type": "string",
                                 "description": "optional right-axis label"},
                    "source_path": {"type": "string",
                                    "description": "optional relative .csv file in this chat project"},
                    "x_column": {"type": "string",
                                 "description": "CSV column used for the x axis"},
                    "series": {"type": "array", "items": {"type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "x": {"type": "array", "items": {}},
                            "y": {"type": "array", "items": {"type": "number"}},
                            "y_column": {"type": "string",
                                         "description": "CSV column used for this series"},
                            "axis": {"type": "string", "enum": ["left", "right"],
                                     "description": "use right when units or scale differ from the main series"},
                        }, "required": ["y"]}},
                }, "required": ["output_path", "series"]},
            },
            {
                "name": "publish_project_view",
                "description": (
                    "Publish or update this chat's safe dynamic Project View after "
                    "creating real artifacts. GeoForge renders the declared metrics, "
                    "images, animations, maps, CSV tables, files, and 3D-model "
                    "previews; it never executes model-written HTML or JavaScript. "
                    "Every path must name an existing file below artifacts/."
                ),
                "input_schema": {"type": "object", "properties": {
                    "version": {"type": "integer", "enum": [1]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "layout": {"type": "string", "enum": ["grid", "single"]},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "kis": {"type": "array", "items": {"type": "string"}},
                    "panels": {"type": "array", "maxItems": 24, "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "kind": {"type": "string", "enum": [
                                "metric", "image", "animation", "map", "table",
                                "file", "model3d"]},
                            "title": {"type": "string"},
                            "caption": {"type": "string"},
                            "status": {"type": "string"},
                            "value": {},
                            "unit": {"type": "string"},
                            "path": {"type": "string"},
                            "renderer": {"type": "string"},
                        }, "required": ["kind", "title"]}},
                }, "required": ["title", "panels"]},
            },
            {
                "name": "request_user_action",
                "description": (
                    "Pause project preparation and show one concrete action to the "
                    "user. Use only for a protected download, licence/login, private "
                    "data, system permission, or high-impact scientific choice that "
                    "the KI cannot resolve. Never use it for ordinary KI defaults."
                ),
                "input_schema": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": [
                        "download", "licence", "login", "permission", "choice", "other"]},
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "options": {"type": "array", "maxItems": 8, "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "response": {"type": "string",
                                         "description": "exact answer sent back to the agent when selected"},
                        }, "required": ["label"]}},
                    "allow_note": {"type": "boolean"},
                    "url": {"type": "string"},
                    "expected_path": {"type": "string"},
                    "command": {"type": "string"},
                    "resume_hint": {"type": "string"},
                }, "required": ["kind", "title", "message"]},
            },
        ]
    if project_mode or setup_mode:
        tools.append({
            "name": "report_project_progress",
            "description": (
                "Update GeoForge's small project-status display at a meaningful "
                "transition. Report only work actually reached. This records use "
                "of the general KI; it does not create an adaptive KI harness."
            ),
            "input_schema": {"type": "object", "properties": {
                "stage": {"type": "string", "enum": [
                    "understanding", "choosing_ki", "software", "researching",
                    "preparing", "validating", "running", "results"]},
                "status": {"type": "string", "enum": [
                    "idle", "working", "waiting_for_user", "complete", "failed"]},
                "goal": {"type": "string", "description": (
                    "The current modelling goal. Include this only when the user "
                    "has materially replaced or refined the scientific case; do "
                    "not replace it for a simple continue/retry message."
                )},
                "summary": {"type": "string"},
                "selected_kis": {"type": "array", "items": {"type": "string"}},
            }, "required": ["stage", "status", "summary"]},
        })
    if setup_mode:
        tools += [
            {
                "name": "run_builtin_setup",
                "description": (
                    "Run GeoForge's bundled setup recipe and return its full step "
                    "report. Use it as a fast first attempt, then diagnose and repair "
                    "the first real failure instead of stopping."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_work_files",
                "description": "List files in the writable model setup workspace.",
                "input_schema": {"type": "object", "properties": {
                    "subdir": {"type": "string", "description": "relative workspace path"},
                }},
            },
            {
                "name": "read_work_file",
                "description": "Read a text file from the writable setup workspace.",
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                }, "required": ["path"]},
            },
            {
                "name": "write_work_file",
                "description": (
                    "Write a small text file inside the model setup workspace. "
                    "Use this to repair build files or configuration, not to replace "
                    "the scientific model with a surrogate."
                ),
                "input_schema": {"type": "object", "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                }, "required": ["path", "content"]},
            },
            {
                "name": "run_setup_command",
                "description": (
                    "Run one non-shell command inside the model workspace and return "
                    "stdout, stderr, and its exit code. The executable, working "
                    "directory, and explicit path arguments are checked against a "
                    "build-tool/workspace allowlist; sudo, inline Python, credentials, "
                    "and system package installation are intentionally unavailable."
                ),
                "input_schema": {"type": "object", "properties": {
                    "argv": {"type": "array", "items": {"type": "string"},
                             "description": "argument vector, e.g. [\"cmake\",\"-S\",\".\",\"-B\",\"build\"]"},
                    "cwd": {"type": "string", "description": "relative workspace directory"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                    "env": {"type": "object", "additionalProperties": {"type": "string"}},
                }, "required": ["argv"]},
            },
            *([{
                "name": "publish_setup_output",
                "description": (
                    "Copy a completed generated output or run directory from the "
                    "model setup workspace into this chat project. Use this after "
                    "a successful setup-mode simulation so full binary/text results "
                    "are preserved in the session without rerunning or encoding them "
                    "through chat."
                ),
                "input_schema": {"type": "object", "properties": {
                    "source": {"type": "string",
                               "description": "relative path below outputs/, runs/, or data/ in the setup workspace"},
                    "destination": {"type": "string",
                                    "description": "relative path below inputs/, runs/, outputs/, artifacts/, or references/ in the chat project"},
                }, "required": ["source", "destination"]},
            }] if project_mode else []),
            {
                "name": "request_user_action",
                "description": (
                    "Pause setup and put one concrete human action on GeoForge's "
                    "Setup page. Use only for a licence, protected download, login, "
                    "system privilege, or scientific choice you cannot resolve."
                ),
                "input_schema": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": [
                        "download", "licence", "login", "permission", "choice", "other"]},
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "options": {"type": "array", "maxItems": 8, "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "response": {"type": "string",
                                         "description": "exact answer sent back to the agent when selected"},
                        }, "required": ["label"]}},
                    "allow_note": {"type": "boolean"},
                    "url": {"type": "string"},
                    "expected_path": {"type": "string"},
                    "command": {"type": "string"},
                    "resume_hint": {"type": "string"},
                }, "required": ["kind", "title", "message"]},
            },
        ]
    # Combined installation + project turns intentionally expose both tool
    # families.  A shared operation such as request_user_action must still be
    # declared only once; the later (setup-aware) definition wins.
    return list({tool["name"]: tool for tool in tools}.values())


class ToolError(Exception):
    pass


def execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                 setup_context: dict | None = None,
                 project_mode: bool = False) -> str:
    """Run one tool. Every path argument is confined to the KI package."""
    root = Path(ki.root).resolve()
    workroot = Path(cfg.root).resolve()
    # During a direct-API installation turn the model setup workspace and the
    # chat project are deliberately separate.  Keep both roots explicit so an
    # agent can finish installation and then run/publish into the chat project
    # without weakening the setup command sandbox.
    project_root = Path(
        (setup_context or {}).get("project_root") or workroot
    ).resolve()
    progress_root = project_root

    # A chat owns its scenario files, but the scientific software is installed
    # once in the current KI's managed workspace.  That binary role is a narrow
    # capability granted by GeoForge's config; it is not an arbitrary external
    # filesystem permission.  KI tools may read/execute it directly without
    # making the user copy large model installs into every chat project.
    project_argument_roots = [project_root, workroot, root]
    binary_role = (getattr(cfg, "roles", {}) or {}).get("binaries")
    if binary_role:
        binary_root = Path(binary_role).expanduser().resolve()
        if binary_root not in project_argument_roots:
            project_argument_roots.append(binary_root)

    def _inside(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute paths are not accepted: {rel}")
        # Resolve then verify containment: a bare prefix check is defeated by
        # '..' and by symlinks, and this is the only place model-supplied paths
        # reach the filesystem.
        p = (root / rel).resolve()
        if p != root and root not in p.parents:
            raise ToolError(f"path escapes the KI package: {rel}")
        return p

    def _inside_work(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute workspace paths are not accepted: {rel}")
        p = (workroot / rel).resolve()
        if p != workroot and workroot not in p.parents:
            raise ToolError(f"path escapes the setup workspace: {rel}")
        return p

    def _inside_project(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute project paths are not accepted: {rel}")
        p = (project_root / rel).resolve()
        if p != project_root and project_root not in p.parents:
            raise ToolError(f"path escapes the chat project: {rel}")
        return p

    if name == "read_ki_file":
        p = _inside(args.get("path", ""))
        if not p.is_file():
            raise ToolError(f"no such file in this KI: {args.get('path')}")
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:60000]

    if name == "list_ki_files":
        base = _inside(args.get("subdir") or ".")
        names = sorted(str(f.relative_to(root)) for f in base.rglob("*") if f.is_file())
        return "\n".join(names[:400]) or "(empty)"

    if name == "run_preflight":
        from . import install as _install
        step = _install.run_preflight(ki, cfg.python, cfg)
        return f"{'PASS' if step.ok else 'FAIL'}\n{step.detail}"

    if name == "search_diagnostics":
        kw = (args.get("keyword") or "").lower()
        if not kw:
            raise ToolError("keyword required")
        hits: list[str] = []
        for f in root.rglob("*"):
            if not f.is_file() or "diagnostic" not in str(f.relative_to(root)):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if kw in line.lower():
                    hits.append(f"{f.relative_to(root)}:{i}: {line.strip()[:200]}")
        return "\n".join(hits[:40]) or f"no diagnostics mention {kw!r}"

    if name in ("list_skills", "read_skill"):
        if name == "list_skills":
            q = (args.get("query") or "").lower()
            found = [item for item in skilllib.discover()
                     if not q or q in item["name"].lower()
                     or q in item["description"].lower()]
            return ("\n".join(f"{item['name']} — {item['description']}"
                              for item in found[:200]) or "no skills installed")
        try:
            return skilllib.read(args.get("name", ""))[:60000]
        except FileNotFoundError:
            raise ToolError(f"no skill named {args.get('name')!r}")

    if project_mode and name == "list_project_files":
        base = _inside_project(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such project directory: {args.get('subdir')}")
        names = []
        for f in sorted(base.rglob("*")):
            if not f.is_file() or "memory" in f.relative_to(project_root).parts:
                continue
            try:
                names.append(f"{f.relative_to(project_root)} ({f.stat().st_size} bytes)")
            except OSError:
                continue
        return "\n".join(names[:1000]) or "(no project files yet)"

    if project_mode and name == "read_project_file":
        p = _inside_project(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such project file: {args.get('path')}")
        if p.stat().st_size > 5_000_000:
            raise ToolError("project file is too large for the text reader; use a KI tool")
        return p.read_text(encoding="utf-8", errors="replace")[:120000]

    if project_mode and name == "write_project_file":
        p = _inside_project(args.get("path") or "")
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ToolError("write_project_file is limited to 1 MB; use a KI tool")
        rel = p.relative_to(project_root)
        writable = {"inputs", "runs", "outputs", "artifacts", "references"}
        calibration_write = (len(rel.parts) >= 2 and rel.parts[0] == "calibration"
                             and rel.parts[1] in {"cases", "kis"})
        if not rel.parts or (rel.parts[0] not in writable and not calibration_write):
            raise ToolError(
                "project writes must stay under inputs, runs, outputs, artifacts, "
                "references, calibration/cases, or calibration/kis")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {rel} ({len(content.encode('utf-8'))} bytes)"

    if project_mode and name == "run_ki_tool":
        script = _inside(args.get("tool_path") or "")
        try:
            rel_script = script.relative_to(root)
        except ValueError:
            raise ToolError("tool escapes the selected KI")
        if not script.is_file() or script.suffix.casefold() != ".py" or "tools" not in rel_script.parts:
            raise ToolError("run_ki_tool accepts only shipped Python files below tools/")
        arguments = args.get("arguments") or []
        if (not isinstance(arguments, list) or len(arguments) > 100 or
                not all(isinstance(x, str) and len(x) <= 4000 for x in arguments)):
            raise ToolError("arguments must be a list of short strings")
        cwd = _inside_project(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"project directory does not exist: {args.get('cwd')}")
        for token in arguments:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if not (value.startswith(("/", "./", "../")) or "/" in value):
                continue
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            if not any(
                    resolved == base or base in resolved.parents
                    for base in project_argument_roots):
                raise ToolError(f"tool argument path escapes the project and KI: {value}")
        timeout = max(1, min(int(args.get("timeout_seconds") or 600), 3600))
        child_env = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        child_env["KISS_ROOT"] = str(project_root)
        from .paths import with_ki_tools_common
        child_env = with_ki_tools_common(cfg, child_env)
        from .calibration import with_framework_env
        child_env = with_framework_env(child_env)
        try:
            proc = subprocess.run(
                [str(cfg.python), str(script), *arguments], cwd=str(cwd),
                env=child_env, capture_output=True, text=True, errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            tail = ((e.stdout or "") + (e.stderr or ""))[-12000:]
            return f"TIMEOUT after {timeout}s\n{tail}"
        output = (proc.stdout + proc.stderr)[-80000:]
        return f"exit_code={proc.returncode}\n{output}"

    if project_mode and name == "run_calibration":
        from . import calibration as _calibration
        # Ensure the adapter copy exists before building the generated runtime
        # KI. `ki` is already the session-materialised package in pinned chats.
        _calibration.ensure_project(project_root, [ki])
        try:
            result = _calibration.run_project(
                project=project_root,
                ki_name=ki.name,
                ki_path=root,
                obs_shape_by_var=args.get("obs_shape_by_var") or {},
                algorithm=args.get("algorithm") or None,
                budget=args.get("budget"),
                seed=int(args.get("seed") or 0),
                determining_metric=args.get("determining_metric") or None,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from None
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        summary = {
            "run_id": result.get("run_id"),
            "status": report.get("status"),
            "promotable": report.get("promotable"),
            "backend": report.get("backend"),
            "best_loss": report.get("best_loss"),
            "best_params": report.get("best_params"),
            "reason": report.get("reason"),
            "report_path": result.get("report_path"),
            "log_path": result.get("log_path"),
            "log_tail": result.get("log_tail"),
        }
        return json.dumps(summary, indent=2, ensure_ascii=False, default=str)

    if project_mode and name == "create_project_plot":
        from .plotting import PlotError, render_svg
        p = _inside_project(args.get("output_path") or "")
        rel = p.relative_to(project_root)
        if not rel.parts or rel.parts[0] != "artifacts" or p.suffix.lower() != ".svg":
            raise ToolError("plot output_path must be a .svg file below artifacts/")
        plot_args = dict(args)
        if args.get("source_path"):
            source = _inside_project(args.get("source_path") or "")
            if not source.is_file() or source.suffix.lower() != ".csv":
                raise ToolError("plot source_path must be a project CSV file")
            if source.stat().st_size > 20_000_000:
                raise ToolError("plot CSV is larger than 20 MB")
            x_column = str(args.get("x_column") or "")
            requested = args.get("series") or []
            if not x_column or not requested or not all(
                    isinstance(item, dict) and item.get("y_column")
                    for item in requested):
                raise ToolError("CSV plots require x_column and y_column for every series")
            with source.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                raise ToolError("plot CSV has no data rows")
            columns = set(rows[0])
            y_columns = [str(item["y_column"]) for item in requested]
            missing = [column for column in [x_column, *y_columns]
                       if column not in columns]
            if missing:
                raise ToolError(f"plot CSV is missing columns: {', '.join(missing)}")
            # Keep the request and SVG bounded while preserving both endpoints.
            max_rows = max(2, 5000 // len(requested))
            if len(rows) > max_rows:
                indices = sorted({round(i * (len(rows) - 1) / (max_rows - 1))
                                  for i in range(max_rows)})
                rows = [rows[i] for i in indices]
            built_series = []
            for item, y_column in zip(requested, y_columns):
                built_series.append({
                    "name": item.get("name") or y_column,
                    "axis": item.get("axis") or "left",
                    "x": [row[x_column] for row in rows],
                    "y": [row[y_column] for row in rows],
                })
            plot_args["series"] = built_series
        try:
            summary = render_svg(plot_args, p)
        except (OSError, PlotError) as e:
            raise ToolError(str(e)) from None
        return (f"{summary}\nInclude it in the reply as: "
                f"![{args.get('title') or p.stem}]({rel.as_posix()})")

    if project_mode and name == "publish_project_view":
        from . import projectview as _projectview
        try:
            state = _projectview.publish(project_root, args, source="direct_api")
        except (OSError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from None
        return ("Project View published. GeoForge will render it for this chat.\n" +
                json.dumps({
                    "title": state["title"],
                    "panels": len(state["panels"]),
                    "path": "artifacts/project-view.json",
                }, indent=2, ensure_ascii=False))

    if project_mode and not setup_mode and name == "request_user_action":
        from . import projectrun as _projectrun, setup as _setup
        doc = _setup.request_user(project_root, args)
        _projectrun.report(progress_root, {
            "status": "waiting_for_user", "summary": doc["title"],
            "blocker": doc,
        }, source="api_handoff")
        return "GeoForge will show this one request to the user:\n" + json.dumps(doc, indent=2)

    if (project_mode or setup_mode) and name == "report_project_progress":
        from . import projectrun as _projectrun
        state = _projectrun.report(progress_root, args, source="api")
        return "Project status updated:\n" + json.dumps(state, indent=2)

    if setup_mode and name == "run_builtin_setup":
        callback = (setup_context or {}).get("run_builtin")
        if not callable(callback):
            raise ToolError("the built-in setup runner is unavailable")
        return str(callback())[-60000:]

    if setup_mode and name == "list_work_files":
        base = _inside_work(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such workspace directory: {args.get('subdir')}")
        names = sorted(str(f.relative_to(workroot)) for f in base.rglob("*") if f.is_file())
        return "\n".join(names[:800]) or "(empty)"

    if setup_mode and name == "read_work_file":
        p = _inside_work(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such workspace file: {args.get('path')}")
        return p.read_text(encoding="utf-8", errors="replace")[:60000]

    if setup_mode and name == "write_work_file":
        p = _inside_work(args.get("path") or "")
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if len(content.encode("utf-8")) > 250_000:
            raise ToolError("write_work_file is limited to 250 KB")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {p.relative_to(workroot)} ({len(content.encode('utf-8'))} bytes)"

    if setup_mode and name == "run_setup_command":
        argv = args.get("argv")
        if (not isinstance(argv, list) or not argv or len(argv) > 100 or
                not all(isinstance(x, str) and x and len(x) <= 4000 for x in argv)):
            raise ToolError("argv must be a non-empty list of short strings")
        executable = argv[0]
        allowed = {
            "git", "cmake", "make", "gmake", "ninja", "meson", "pkg-config",
            "python", "python3", "pip", "pip3", "uv", "cargo", "rustc", "go",
            "gcc", "g++", "clang", "clang++", "gfortran", "tar", "unzip",
            "curl", "wget", "patch", "sed", "awk", "find", "ls", "cp", "mv",
            "chmod", "file", "otool", "xcode-select", "brew",
        }
        exe_path = Path(executable)
        if exe_path.is_absolute() or "/" in executable:
            resolved = (workroot / exe_path).resolve() if not exe_path.is_absolute() else exe_path.resolve()
            cfg_python = Path(cfg.python).resolve()
            permitted_roots = [workroot, root, Path(cfg.roles.get("binaries", workroot)).resolve()]
            if resolved != cfg_python and not any(
                    resolved == base or base in resolved.parents for base in permitted_roots):
                raise ToolError(f"executable is outside the setup workspace: {executable}")
            argv[0] = str(resolved)
        elif executable not in allowed:
            raise ToolError(f"command is not in the setup allowlist: {executable}")
        if Path(argv[0]).name == "brew" and len(argv) > 1 and argv[1] not in (
                "--prefix", "--version", "list", "info", "config"):
            raise ToolError("Homebrew changes require the user; create a permission request")

        cwd = _inside_work(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"command directory does not exist: {args.get('cwd')}")
        # Reject path arguments that escape the workspace. This is not a
        # shell, but programs such as cp, curl and git still accept output
        # paths of their own. Compiler/system include flags are allowed only
        # for the conventional read-only roots they genuinely need.
        readable_system_roots = tuple(Path(p) for p in (
            "/usr", "/opt/homebrew", "/Library/Frameworks",
        ))

        def check_path_token(token: str) -> None:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if value.startswith(("http://", "https://", "git@")):
                return
            if not (value.startswith(("/", "./", "../")) or "/" in value):
                return
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            allowed_workspace = any(
                resolved == base or base in resolved.parents
                for base in (workroot, root, Path(cfg.roles.get("binaries", workroot)).resolve())
            )
            allowed_system = any(
                resolved == base or base in resolved.parents for base in readable_system_roots)
            if not allowed_workspace and not allowed_system:
                raise ToolError(f"command path escapes the setup workspace: {value}")

        for token in argv[1:]:
            check_path_token(token)
        if Path(argv[0]).name in ("python", "python3") or Path(argv[0]).resolve() == Path(cfg.python).resolve():
            if "-c" in argv:
                raise ToolError("inline Python is unavailable; write a workspace script and run it")
        timeout = max(1, min(int(args.get("timeout_seconds") or 300), 3600))
        extra_env = args.get("env") or {}
        if not isinstance(extra_env, dict):
            raise ToolError("env must be an object")
        safe_env = {}
        banned = {"HOME", "PATH", "SHELL", "DYLD_INSERT_LIBRARIES", "PYTHONPATH"}
        for key, value in extra_env.items():
            if (not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,63}", str(key)) or
                    key in banned or not isinstance(value, str) or len(value) > 8000):
                raise ToolError(f"unsafe environment override: {key}")
            safe_env[key] = value
        # A tool or build script must never inherit the API key that is driving
        # the agent. Keep the normal build environment, remove credentials.
        child_env = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        from .paths import with_ki_tools_common
        child_env = with_ki_tools_common(cfg, child_env)
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), env={**child_env, **safe_env},
                capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            tail = ((e.stdout or "") + (e.stderr or ""))[-12000:]
            return f"TIMEOUT after {timeout}s\n{tail}"
        except OSError as e:
            # A non-executable script, missing command, or platform launch
            # error is normal repair-loop evidence.  Let the model see it and
            # choose another invocation (usually ``python3 script.py``)
            # instead of aborting the entire API turn.
            return f"FAILED_TO_START: {type(e).__name__}: {e}"
        output = (proc.stdout + proc.stderr)[-50000:]
        return f"exit_code={proc.returncode}\n{output}"

    if setup_mode and project_mode and name == "publish_setup_output":
        source = _inside_work(args.get("source") or "")
        destination = _inside_project(args.get("destination") or "")
        if not source.exists():
            raise ToolError(f"no such generated setup output: {args.get('source')}")
        source_rel = source.relative_to(workroot)
        destination_rel = destination.relative_to(project_root)
        if not source_rel.parts or source_rel.parts[0] not in {"outputs", "runs", "data"}:
            raise ToolError("published setup files must come from outputs, runs, or data")
        writable = {"inputs", "runs", "outputs", "artifacts", "references"}
        if not destination_rel.parts or destination_rel.parts[0] not in writable:
            raise ToolError("published files must stay in a project data folder")

        candidates = [source] if source.is_file() else list(source.rglob("*"))
        # A scientific run directory commonly links its executable and shared
        # model tables back into the same setup workspace.  Those links are
        # safe to publish as normal files when their targets remain inside the
        # workspace.  Keeping the links themselves would make the chat project
        # non-portable, while rejecting them prevented an otherwise successful
        # run from being archived at all.
        files: list[tuple[Path, Path]] = []
        link_count = 0
        for item in candidates:
            if item.is_symlink():
                try:
                    resolved = item.resolve(strict=True)
                except OSError as e:
                    raise ToolError(f"generated output contains a broken symbolic link: {item.name}") from e
                if resolved != workroot and workroot not in resolved.parents:
                    raise ToolError(
                        f"generated output link escapes the setup workspace: {item.name}")
                if not resolved.is_file():
                    raise ToolError(
                        f"generated output contains a symbolic directory: {item.name}")
                files.append((item, resolved))
                link_count += 1
            elif item.is_file():
                files.append((item, item))
        if len(files) > 2000:
            raise ToolError("generated output contains more than 2,000 files")
        total = sum(copy_source.stat().st_size for _, copy_source in files)
        if total > 512 * 1024 * 1024:
            raise ToolError("generated output is larger than the 512 MB publish limit")
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(files[0][1], destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            for item, copy_source in files:
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy_source, target)
        link_note = (f", {link_count} internal links copied as files"
                     if link_count else "")
        return (
            f"published {source_rel} to {destination_rel} "
            f"({len(files)} files, {total} bytes{link_note})"
        )

    if setup_mode and name == "request_user_action":
        from . import projectrun as _projectrun, setup as _setup
        doc = _setup.request_user(workroot, args)
        _projectrun.report(progress_root, {
            "stage": "software", "status": "waiting_for_user",
            "summary": doc["title"], "blocker": doc,
        }, source="api_handoff")
        return "GeoForge is now waiting for the user:\n" + json.dumps(doc, indent=2)

    raise ToolError(f"unknown tool {name}")


# --- wire formats -----------------------------------------------------------

def _post(url: str, headers: dict, payload: dict, *, provider: str) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        from .settings import proxy_url_for
        proxy = proxy_url_for(provider)
        handlers = [
            urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy} if proxy else {}),
            urllib.request.HTTPSHandler(context=tls.context()),
        ]
        with urllib.request.build_opener(*handlers).open(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        raise ToolError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise ToolError(f"cannot reach {url}: {e.reason}") from None


def _cacheable_system(system: str) -> list[dict]:
    """The instruction block as one cacheable prefix.

    Tools and system render ahead of messages, so a single breakpoint here
    covers both. It matters more than one call per turn suggests: the agent
    loop below runs up to ``max_steps`` times for a single user message, and
    without this the same ~20KB KI catalogue was re-sent, and re-billed at full
    price, on every one of them.
    """
    return [{"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}}]


def _cached_messages(messages: list[dict]) -> list[dict]:
    """Messages with a rolling cache breakpoint on the newest turn.

    Each loop step resends the entire conversation. Marking the tail lets the
    next step read everything up to here from cache rather than paying for it
    again. Copied rather than mutated — ``messages`` is reused across steps and
    a breakpoint left behind on an old turn would pin the cache to stale text.
    """
    if not messages:
        return messages
    content = messages[-1].get("content")
    if isinstance(content, str):
        blocks: list = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = [dict(b) if isinstance(b, dict) else b for b in content]
    else:
        return messages
    if not isinstance(blocks[-1], dict):
        return messages
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return [*messages[:-1], {**messages[-1], "content": blocks}]


def _anthropic_turn(prov, model, system, messages, tools, key):
    data = _post(prov.base_url,
                 {"x-api-key": key, "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 4096,
                  "system": _cacheable_system(system),
                  "messages": _cached_messages(messages), "tools": tools},
                 provider=f"api:{getattr(prov, 'name', 'anthropic')}")
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    calls = [(b["id"], b["name"], b.get("input") or {})
             for b in data.get("content", []) if b.get("type") == "tool_use"]
    return text, calls, data.get("content", [])


def _openai_turn(prov, model, system, messages, tools, key):
    oai_tools = [{"type": "function",
                  "function": {"name": t["name"], "description": t["description"],
                               "parameters": t["input_schema"]}} for t in tools]
    msgs = [{"role": "system", "content": system}, *messages]
    data = _post(prov.base_url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": msgs, "tools": oai_tools},
                 provider=f"api:{getattr(prov, 'name', 'openai')}")
    choice = (data.get("choices") or [{}])[0].get("message", {})
    text = choice.get("content") or ""
    calls = []
    for c in (choice.get("tool_calls") or []):
        # Preserve a valid call id/name even when the vendor truncates only
        # the JSON arguments.  Feeding a normal tool error back under that id
        # lets the model retry on the next step instead of dropping the whole
        # turn.  Missing structural fields still fail closed below.
        try:
            call_id = c["id"]
            function = c["function"]
            name = function["name"]
            raw_args = function.get("arguments") or "{}"
        except (KeyError, TypeError) as e:
            raise ToolError(f"vendor returned a malformed tool call: {e}") from None
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError as e:
            args = {
                "_vendor_argument_error": f"invalid JSON arguments: {e}",
                "_raw_arguments": str(raw_args)[:2000],
            }
        calls.append((call_id, name, args))
    return text, calls, choice


_TEXT_TOOL_REQUEST = re.compile(
    r"\[\[GEOF_TOOL:[A-Za-z0-9_.-]+\]\]|"
    r"<invoke\s+name=[\"'][A-Za-z0-9_.-]+[\"'][^>]*>[\s\S]*?<parameter\b",
    re.I,
)


def _looks_like_text_tool_request(text: str) -> bool:
    """Detect providers printing tool syntax instead of making a tool call.

    Some OpenAI-compatible endpoints occasionally return an XML-like tool
    request in ``content`` with an empty structured ``tool_calls`` array. It
    must not be shown as if work happened: no tool was actually run.
    """
    return bool(_TEXT_TOOL_REQUEST.search(str(text or "")))


def run(prov: ApiProvider, ki, cfg, system: str, task: str,
        *, model: str | None = None, max_steps: int = 12,
        history: list[dict] | None = None,
        approve: Callable[[str, dict], bool] | None = None,
        setup_mode: bool = False,
        setup_context: dict | None = None,
        project_mode: bool = False,
        presentation: str = "chat") -> Iterator[str]:
    """Drive one task to completion, yielding text as it is produced.

    ``approve`` is the seam the CLI driver cannot offer: it is called before
    each tool runs and may refuse. Returning False denies that one call and
    tells the model why, rather than aborting the turn.
    """
    key = prov.key()
    if not key:
        yield f"[{prov.label}: set {prov.env_key} — get one at {prov.signup}]"
        return

    want = model or prov.default_model
    if prov.models and want not in prov.models and want not in prov.models.values():
        yield (f"[{prov.label} does not offer {want!r}; choose from "
               f"{list(prov.models)}]")
        return
    model_id = prov.models.get(want, want)
    tools = tool_schemas(ki, setup_mode=setup_mode, project_mode=project_mode)
    # Prior turns travel as REAL messages, not flattened into one user blob
    # with USER:/YOU: markers — the vendor's own multi-turn handling is the
    # thing that makes context work, and counterfeit markers cannot exist in a
    # role field.
    messages: list[dict] = []
    for m in history or []:
        role = "assistant" if m.get("role") == "assistant" else "user"
        body = str(m.get("text", ""))[:8000]
        if body:
            messages.append({"role": role, "content": body})
    messages.append({"role": "user", "content": task})
    text_tool_retries = 0

    for step in range(max_steps):
        try:
            if prov.wire == "anthropic":
                text, calls, raw = _anthropic_turn(prov, model_id, system, messages, tools, key)
            else:
                text, calls, raw = _openai_turn(prov, model_id, system, messages, tools, key)
        except ToolError as e:
            yield f"\n[{prov.label} failed: {e}]"
            return

        if not calls and _looks_like_text_tool_request(text):
            # Do not leak provider-specific pseudo XML into chat, and do not
            # pretend it ran. Give the model one clean chance to use the typed
            # tools that were already sent with the request.
            if text_tool_retries:
                yield (f"\n[{prov.label} returned a tool request as plain text. "
                       "Nothing in that request was run. Retry this message or "
                       "switch the AI connection.]\n")
                return
            text_tool_retries += 1
            if prov.wire == "anthropic":
                messages.append({"role": "assistant", "content": raw})
            else:
                messages.append(raw)
            messages.append({
                "role": "user",
                "content": ("Your previous response printed internal tool-call "
                            "markup as ordinary text, so no action ran. Use the "
                            "provided structured function tools now. Do not print "
                            "XML, <invoke>, or GEOF_TOOL markers."),
            })
            continue

        # A response which also invokes tools is normally scratch narration
        # ("Let me inspect...", "Now I will..."). Keep it in the provider's
        # internal history, but reserve the visible answer for the final
        # no-tool response. Forensic setup pages can still request log mode.
        if text and (not calls or presentation == "log"):
            yield text
        if not calls:
            return

        results = []
        for call_id, name, args in calls:
            if presentation == "log":
                yield f"\n`> {name}({', '.join(f'{k}={v!r}' for k, v in args.items())[:80]})`\n"
            else:
                yield activity_marker(name)
            if approve is not None and not approve(name, args):
                out = "DENIED by the user. Do not retry; explain what you needed it for."
            else:
                try:
                    out = execute_tool(name, args, ki, cfg, setup_mode=setup_mode,
                                       setup_context=setup_context,
                                       project_mode=project_mode)
                except ToolError as e:
                    out = f"ERROR: {e}"
            results.append((call_id, out))

        if prov.wire == "anthropic":
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": out}
                for cid, out in results]})
        else:
            messages.append(raw)
            for cid, out in results:
                messages.append({"role": "tool", "tool_call_id": cid, "content": out})

    yield f"\n[stopped after {max_steps} steps without finishing]"
