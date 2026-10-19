"""Early, read-only diagnostics for output paths already known to be directories.

The shared runtime contract still validates exact ordinary output files. This
host check only rejects contradictions visible before staging creates folders;
it never guesses from extensions or grants directory output validation.
"""
from __future__ import annotations

import os
from pathlib import Path


def _local(project: Path, raw) -> Path | None:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        return None
    try:
        value = Path(raw)
        if value.drive and not value.is_absolute():
            return None
        path = Path(os.path.abspath(value if value.is_absolute() else project / value))
        return path if path.is_relative_to(project) else None
    except (OSError, ValueError, RuntimeError):
        return None


def plan_errors(plan, inventory, project) -> list[str]:
    """Ordinary outputs must name files, including when their folder is future."""
    if not isinstance(plan, dict) or not isinstance(inventory, dict) or project is None:
        return []
    from ki_tools_common.flow.declared_outputs import ordinary
    project = Path(project).resolve()
    steps = [row for row in plan.get("steps") or [] if isinstance(row, dict)]
    items = [row for row in inventory.get("items") or [] if isinstance(row, dict)]
    known = {project / name: "a tracked project directory" for name in ("inputs", "outputs", "artifacts", "runs/logs")}

    def parents(path, reason):
        for parent in path.parents:
            if parent == project or not parent.is_relative_to(project):
                break
            known.setdefault(parent, reason)

    for step in steps:
        typed = step.get("project_data_tool")
        raw = typed.get("cwd") if isinstance(typed, dict) else step.get("cwd")
        cwd = _local(project, raw)
        if cwd is not None:
            reason = f"the working directory of step {str(step.get('id'))[:120]!r}"
            known[cwd] = reason
            parents(cwd, "a parent of a planned working directory")
    for item in items:
        paths = item.get("local_paths")
        if not isinstance(paths, list):
            continue
        for raw in paths:
            path = _local(project, raw)
            if path is None:
                continue
            parents(path, "a parent of another inventoried path")
            if raw.endswith(tuple(separator for separator in (os.sep, os.altsep) if separator)):
                known[path] = "an explicitly directory-shaped inventory path"

    errors = []
    for step in steps:
        if not ordinary(step) or not isinstance(step.get("outputs"), list):
            continue
        for item in items:
            if item.get("id") not in step["outputs"] or not isinstance(item.get("local_paths"), list):
                continue
            for raw in item["local_paths"]:
                path = _local(project, raw)
                if path is None:
                    continue  # The shared path contract owns invalid/outside paths.
                reason = known.get(path)
                try:
                    if reason is None and path.is_dir():
                        reason = "an existing directory"
                except OSError:
                    continue  # Preserve the shared filesystem diagnostic.
                if reason:
                    errors.append(
                        f"step {str(step.get('id'))[:120]!r}, output {str(item.get('id'))[:120]!r}: "
                        f"local_paths entry {str(raw)[:400]!r} is {reason}, not an individual output file. "
                        "List the exact filenames produced by the KI in local_paths (several files may share one "
                        "output item). Keep the run folder in cwd/tool arguments; do not use a directory or "
                        "wildcard as output evidence. Do not invent filenames or change the model's output contract.")
    return errors
