"""Declared KI entrypoints, shared by planning and execution checks.

Older KIs use s1_grid/, s2_forcing/, etc. Those scripts are accepted only
when the package's own protocol names them; arbitrary project scripts,
preflights and symlink escapes are never promoted to executable plan tools.
"""
from pathlib import Path
import os
import re


# Never approvable as a step tool: a declared "binary" that is really an interpreter.
_INTERPRETER = re.compile(r"^(python[0-9.]*|python[0-9.]*\.exe|rscript|r|julia[0-9.-]*|octave(-cli)?|"
                          r"bash|sh|zsh|dash|perl[0-9.]*|node|ruby|php|java)$", re.IGNORECASE)


def is_ki_tool(root: Path, tool: Path | str) -> bool:
    try:
        return _is_ki_tool(root, tool)
    except (OSError, ValueError, RuntimeError, TypeError):
        # Malformed paths, unreadable protocols and symlink cycles fail closed.
        return False


def declared_binaries(root: Path) -> set[Path]:
    """Executables the KI declares in knowledge_infrastructure.yaml (``binary.path``
    or ``binaries: [{path}]``).  They live in GeoForge's managed binaries
    directory, outside the KI package, and are the only way to run a compiled
    model such as VIC through a receipted step."""
    doc = Path(root) / "knowledge_infrastructure.yaml"
    if not doc.is_file() or doc.is_symlink():
        return set()
    try:
        import yaml
        data = yaml.safe_load(doc.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return set()
    # Only the model's own declared product counts: `model.binary.path`, `binary.path`,
    # or `binaries: [{path}]`. A bare regex over every `path:` line used to promote the
    # interpreters some KIs list (python, Rscript, octave, julia) into approvable tools —
    # arbitrary code through the tool wall.
    cands: list = []
    # `binary:` sits at the top level or under one top-level section (package:, model:, …)
    holders = [data] + [v for v in data.values() if isinstance(v, dict)]
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        b = holder.get("binary")
        if isinstance(b, dict) and b.get("path"):
            cands.append(b["path"])
        for entry in holder.get("binaries") or []:
            if isinstance(entry, dict) and entry.get("path"):
                cands.append(entry["path"])
    out: set[Path] = set()
    for raw in cands:
        candidate = Path(str(raw).strip("'\""))
        if not (candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        if _INTERPRETER.match(candidate.name):
            continue
        out.add(candidate.resolve())
    return out


def is_declared_binary(root: Path, tool: Path | str) -> bool:
    try:
        p = Path(tool)
        return p.is_absolute() and p.resolve() in declared_binaries(root)
    except (OSError, ValueError, RuntimeError, TypeError):
        return False


def _is_ki_tool(root: Path, tool: Path | str) -> bool:
    root = Path(root).resolve()
    p = Path(tool)
    p = (root / p).resolve() if not p.is_absolute() else p.resolve()
    if p in declared_binaries(root):
        return True
    if root not in p.parents or not p.is_file() or p.name in ("preflight_check.py", "__init__.py"):
        return False
    if not (p.suffix.lower() in (".py", ".sh") or (not p.suffix and os.access(p, os.X_OK))):
        return False
    rel = p.relative_to(root).as_posix()
    if rel.startswith("tools/"):
        return True
    if not re.match(r"s[0-9]+_[A-Za-z0-9_-]+/", rel):
        return False
    for name in ("SKILL.md", "SKILL_en.md", "dag.yaml", "knowledge_infrastructure.yaml"):
        doc = root / name
        if doc.is_file() and not doc.is_symlink():
            text = doc.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?<![A-Za-z0-9_./-])" + re.escape(rel) + r"(?![A-Za-z0-9_./-])", text):
                return True
    return False
