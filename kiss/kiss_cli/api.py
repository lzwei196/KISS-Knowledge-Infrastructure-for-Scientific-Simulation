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

import json
import os
import re
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
                "name": "create_project_plot",
                "description": (
                    "Create a safe line, scatter, or bar plot in this chat's "
                    "artifacts folder. Use a relevant plotting/visualization skill "
                    "to choose an honest chart, then call this tool when the direct "
                    "API has no plotting runtime. GeoForge displays the SVG inline."
                ),
                "input_schema": {"type": "object", "properties": {
                    "output_path": {"type": "string",
                                    "description": "relative .svg path below artifacts/"},
                    "kind": {"type": "string", "enum": ["line", "scatter", "bar"]},
                    "title": {"type": "string"},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "series": {"type": "array", "items": {"type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "x": {"type": "array", "items": {}},
                            "y": {"type": "array", "items": {"type": "number"}},
                        }, "required": ["y"]}},
                }, "required": ["output_path", "series"]},
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
                    "url": {"type": "string"},
                    "expected_path": {"type": "string"},
                    "command": {"type": "string"},
                    "resume_hint": {"type": "string"},
                }, "required": ["kind", "title", "message"]},
            },
        ]
    return tools


class ToolError(Exception):
    pass


def execute_tool(name: str, args: dict, ki, cfg, *, setup_mode: bool = False,
                 setup_context: dict | None = None,
                 project_mode: bool = False) -> str:
    """Run one tool. Every path argument is confined to the KI package."""
    root = Path(ki.root).resolve()
    workroot = Path(cfg.root).resolve()
    progress_root = Path((setup_context or {}).get("project_root") or workroot).resolve()

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
        base = _inside_work(args.get("subdir") or ".")
        if not base.is_dir():
            raise ToolError(f"no such project directory: {args.get('subdir')}")
        names = []
        for f in sorted(base.rglob("*")):
            if not f.is_file() or "memory" in f.relative_to(workroot).parts:
                continue
            try:
                names.append(f"{f.relative_to(workroot)} ({f.stat().st_size} bytes)")
            except OSError:
                continue
        return "\n".join(names[:1000]) or "(no project files yet)"

    if project_mode and name == "read_project_file":
        p = _inside_work(args.get("path") or "")
        if not p.is_file():
            raise ToolError(f"no such project file: {args.get('path')}")
        if p.stat().st_size > 5_000_000:
            raise ToolError("project file is too large for the text reader; use a KI tool")
        return p.read_text(encoding="utf-8", errors="replace")[:120000]

    if project_mode and name == "write_project_file":
        p = _inside_work(args.get("path") or "")
        content = args.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be text")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ToolError("write_project_file is limited to 1 MB; use a KI tool")
        rel = p.relative_to(workroot)
        writable = {"inputs", "runs", "outputs", "artifacts", "references"}
        if not rel.parts or rel.parts[0] not in writable:
            raise ToolError("project writes must stay under inputs, runs, outputs, artifacts, or references")
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
        cwd = _inside_work(args.get("cwd") or ".")
        if not cwd.is_dir():
            raise ToolError(f"project directory does not exist: {args.get('cwd')}")
        for token in arguments:
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            if not (value.startswith(("/", "./", "../")) or "/" in value):
                continue
            candidate = Path(value)
            resolved = candidate.resolve() if candidate.is_absolute() else (cwd / candidate).resolve()
            if not any(resolved == base or base in resolved.parents for base in (workroot, root)):
                raise ToolError(f"tool argument path escapes the project and KI: {value}")
        timeout = max(1, min(int(args.get("timeout_seconds") or 600), 3600))
        child_env = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        child_env["KISS_ROOT"] = str(workroot)
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

    if project_mode and name == "create_project_plot":
        from .plotting import PlotError, render_svg
        p = _inside_work(args.get("output_path") or "")
        rel = p.relative_to(workroot)
        if not rel.parts or rel.parts[0] != "artifacts" or p.suffix.lower() != ".svg":
            raise ToolError("plot output_path must be a .svg file below artifacts/")
        try:
            summary = render_svg(args, p)
        except (OSError, PlotError) as e:
            raise ToolError(str(e)) from None
        return (f"{summary}\nInclude it in the reply as: "
                f"![{args.get('title') or p.stem}]({rel.as_posix()})")

    if project_mode and name == "request_user_action":
        from . import projectrun as _projectrun, setup as _setup
        doc = _setup.request_user(workroot, args)
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
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), env={**child_env, **safe_env},
                capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            tail = ((e.stdout or "") + (e.stderr or ""))[-12000:]
            return f"TIMEOUT after {timeout}s\n{tail}"
        output = (proc.stdout + proc.stderr)[-50000:]
        return f"exit_code={proc.returncode}\n{output}"

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

def _post(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=tls.context()) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        raise ToolError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise ToolError(f"cannot reach {url}: {e.reason}") from None


def _anthropic_turn(prov, model, system, messages, tools, key):
    data = _post(prov.base_url,
                 {"x-api-key": key, "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 4096, "system": system,
                  "messages": messages, "tools": tools})
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
                 {"model": model, "messages": msgs, "tools": oai_tools})
    choice = (data.get("choices") or [{}])[0].get("message", {})
    text = choice.get("content") or ""
    calls = []
    for c in (choice.get("tool_calls") or []):
        # A malformed tool call from the vendor must degrade into a visible
        # error, not an uncaught exception that drops the whole stream.
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
            calls.append((c["id"], c["function"]["name"], args))
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            raise ToolError(f"vendor returned a malformed tool call: {e}") from None
    return text, calls, choice


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

    for step in range(max_steps):
        try:
            if prov.wire == "anthropic":
                text, calls, raw = _anthropic_turn(prov, model_id, system, messages, tools, key)
            else:
                text, calls, raw = _openai_turn(prov, model_id, system, messages, tools, key)
        except ToolError as e:
            yield f"\n[{prov.label} failed: {e}]"
            return

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
