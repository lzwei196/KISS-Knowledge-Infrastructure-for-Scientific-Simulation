"""Explicitly reviewed project data tools; never promoted to shipped KI tools."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

PURPOSES = {"reader", "converter", "check"}
FIELDS = {"version", "purpose", "source_sha256", "arguments", "cwd", "timeout_seconds"}


def directory(project: Path, ki: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", ki).strip(".") or "KI"
    # Distinct selected names must not share a writable adapter directory.
    slug += "-" + hashlib.sha256(ki.encode()).hexdigest()[:8]
    return Path(project).resolve() / "project_tools" / slug


def source_path(project: Path, ki: str, tool: str | Path) -> Path:
    project = Path(project).resolve()
    p = Path(tool)
    p = p if p.is_absolute() else project / p
    parent = directory(project, ki)
    if p.parent != parent or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}\.py", p.name):
        raise ValueError("project data tool must be a named Python file in its selected KI's project_tools directory")
    if p.resolve() != p or any(x.is_symlink() for x in (p, parent, parent.parent)):
        raise ValueError("project data tool paths must not contain links or escape the project")
    if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
        raise ValueError("project data tool must be an ordinary unshared file")
    return p


def step_errors(step: dict, project: Path | None) -> list[str]:
    try:
        if project is None:
            raise ValueError("project data tool requires the current project")
        binding = step.get("project_data_tool")
        if not isinstance(binding, dict) or set(binding) != FIELDS:
            raise ValueError("project_data_tool must contain version, purpose, source_sha256, arguments, cwd, timeout_seconds")
        if type(binding["version"]) is not int or binding["version"] != 1 or binding["purpose"] not in PURPOSES:
            raise ValueError("unsupported project data tool version or purpose")
        if step.get("kind") not in {"check", "prepare"} or "calibration" in step:
            raise ValueError("project data tools support only check or prepare steps, never model execution/calibration")
        if not Path(str(step.get("tool") or "")).is_absolute():
            raise ValueError("project data tool must be an absolute path for approval")
        if step.get("env"):
            raise ValueError("project data tools use their guarded runtime environment, not model environment overrides")
        p = source_path(project, str(step.get("ki") or ""), step.get("tool") or "")
        if not p.is_file():
            raise ValueError("project data tool source is missing; write_project_data_tool before submitting the plan")
        if binding["source_sha256"] != hashlib.sha256(p.read_bytes()).hexdigest():
            raise ValueError("project data tool source hash differs from the reviewed binding")
        args = binding["arguments"]
        if not isinstance(args, list) or len(args) > 100 or any(not isinstance(a, str) or len(a) > 4000 for a in args):
            raise ValueError("project data arguments must be a list of short strings")
        cwd = binding["cwd"]
        if not isinstance(cwd, str) or Path(cwd).is_absolute():
            raise ValueError("project data cwd must be project-relative")
        resolved = (Path(project).resolve() / cwd).resolve()
        if not resolved.is_relative_to(Path(project).resolve()) or not resolved.is_dir():
            raise ValueError("project data cwd must exist inside the project")
        if type(binding["timeout_seconds"]) is not int or not 1 <= binding["timeout_seconds"] <= 600:
            raise ValueError("project data timeout must be an integer from 1 to 600 seconds")
        if not step.get("outputs"):
            raise ValueError("project data tool must declare its inspection report or converted outputs")
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        return [str(exc)]
    return []
