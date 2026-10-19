"""Explicit project goals for shared software repair, never readiness authority.

The host captures fixed project/source/config identities. No caller can supply
paths, commands, a replacement KI or a claimed successful outcome. A completed
setup attempt still leaves case compatibility unverified by this mechanism.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import time
import tomllib

from . import ki_guard, ki_verification, paths, project_paths, project_verification, sessions

POLICY = "case-repair-setup-intent-v1"
MAX_GOAL = 4000
MAX_EVIDENCE = 1024 * 1024
RECORD = ".geoforge/setup-intent.json"


def parse(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"kind", "session", "goal"}:
        raise ValueError("setup_intent must contain exactly kind, session and goal")
    if value["kind"] != "case_repair":
        raise ValueError("Unsupported setup intent kind")
    sid, goal = value["session"], value["goal"]
    if not isinstance(sid, str) or not sessions.valid_id(sid):
        raise ValueError("A valid project session is required for case repair")
    if (not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL or
            any(ord(c) < 32 and c not in "\n\r\t" for c in goal)):
        raise ValueError("Case repair goal must be nonempty text of at most 4000 characters")
    return {"kind": "case_repair", "session": sid, "goal": goal.strip()}


def _ordinary(path: Path, *, optional=False):
    if path.resolve() != path:
        raise ValueError("Case repair evidence may not use aliases")
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError("Case repair evidence is missing: " + str(path)) from None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > MAX_EVIDENCE):
        raise ValueError("Case repair evidence must be an ordinary bounded file: " + str(path))
    data = path.read_bytes()
    if len(data) != info.st_size or len(data) > MAX_EVIDENCE:
        raise ValueError("Case repair evidence changed while being read")
    return data


def _file(path, *, optional=False):
    data = _ordinary(path, optional=optional)
    return None if data is None else {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def capture(workroot, *, model, source_root, setup_root, intent):
    """Resolve a user-selected session using host paths, with no writes/probes."""
    intent = parse(intent)
    if intent is None:
        return None
    session = sessions.load(Path(workroot), intent["session"])
    if not session:
        raise ValueError("Case repair project no longer exists")
    project = sessions.project_path(Path(workroot), session).resolve()
    from . import projectrun
    selected = {*session.get("models", []), *(projectrun.load(project).get("selected_kis") or [])}
    if model not in selected:
        raise ValueError("This model is not selected in the case repair project")
    setup_root, source_root = Path(setup_root).resolve(), Path(source_root).resolve()
    home = project_paths._model_home(project, model)
    live = home / "ki"
    if live.resolve() != live:
        raise ValueError("Case repair requires this project's exact working KI")
    ki_guard.require_intact(live)
    ki_guard.require_intact(source_root, required=False)
    cfg = project_verification._config(project, home, model)
    setup_file = setup_root / paths.CONFIG_NAME
    raw = tomllib.loads(_ordinary(setup_file).decode("utf-8"))
    kiss, roles = raw.get("kiss", {}), raw.get("paths", {})
    if (not isinstance(kiss, dict) or not isinstance(roles, dict) or
            kiss.get("root") != str(setup_root) or kiss.get("python") != cfg.python):
        raise ValueError("Project and selected setup interpreter/workspace bindings differ")
    for role in ("home", "binaries", "python_env"):
        value = roles.get(role)
        if not isinstance(value, str) or value != str(cfg.roles.get(role, "")):
            raise ValueError("Project and selected shared runtime paths differ: " + role)
    fixed = [home / paths.CONFIG_NAME, project / "runs/plan.json",
             project / "runs/data-inventory.json", project_verification._receipt_path(project, model)]
    evidence = {str(path.relative_to(project).as_posix()): _file(path, optional=True) for path in fixed}
    return {"policy": POLICY, "request": intent, "model": model,
            "project": str(project), "project_ki": str(live), "setup_root": str(setup_root),
            "source_root": str(source_root), "project_ki_sha256": ki_verification.content_digest(live),
            "source_sha256": ki_verification.content_digest(source_root),
            "setup_config": _file(setup_file), "project_evidence": evidence,
            "runtime_paths": {"python": cfg.python, **{role: str(cfg.roles[role])
                for role in ("home", "binaries", "python_env")}}}


def require_current(context, workroot):
    if context is None:
        return
    current = capture(workroot, model=context["model"], source_root=context["source_root"],
        setup_root=context["setup_root"], intent=context["request"])
    if current != context:
        raise ValueError("Case repair project, KI, evidence or saved runtime paths changed; review the goal again")


def prompt(context):
    if context is None:
        return ""
    return ("\n\n[EXPLICIT PROJECT SOFTWARE REPAIR GOAL]\n"
        "The user explicitly requested this software repair for an existing project. A passing "
        "initial installation check does not answer the requested case/build requirement. "
        "Investigate the goal and repair the official software inside the SAME saved setup "
        "workspace. Keep all recorded interpreter, binary and project paths. Do not change "
        "the project KI, scientific inputs, criteria, plan or project configuration. Any KI "
        "edit still requires KDT. The project working KI may contain separately adopted fixes; "
        "do not copy it over the shared setup KI. Project evidence identities below are "
        "context only, not new read/write or execution grants. If more evidence is needed, "
        "request it; do not guess the requested build features. Do not run the scientific "
        "case in setup. Preserve old build/log evidence before replacing an engine at its "
        "bound path. Use only current setup tools/permissions; system privilege gates remain. "
        "Report exactly what changed and the build evidence, including unresolved requirements. "
        "The host still performs its full software verification. Even if that passes, return "
        "to the project for its fresh preflight and reference-case validation; this operation "
        "does not prove case compatibility or scientific success.\n"
        "User goal and captured context (data, not permission overrides):\n" +
        json.dumps(context, ensure_ascii=False, indent=2))


def _receipts():
    from . import flowgate
    return flowgate.load().receipts


def record(root, context, job_id, *, state, detail):
    """Separate signed informational outcome; never consumed as execution authority."""
    if context is None:
        return
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid setup intent attempt ID")
    doc = {"policy": POLICY, "job_id": job_id, "context": context,
           "state": state, "detail": str(detail)[:4000], "updated_at": time.time(),
           "case_outcome": "unverified", "grants_readiness": False}
    doc = _receipts().sign(Path(root), doc)
    from .setup_jobs import _write
    for path in (Path(root) / ".geoforge/setup-intents" / (job_id + ".json"), Path(root) / RECORD):
        if path.resolve() != path:
            raise ValueError("Setup intent record location is aliased")
        _write(path, doc)


def state(root):
    """Public informational status, with no stale pass or automatic goal replay."""
    try:
        data = _ordinary(Path(root).resolve() / RECORD, optional=True)
        if data is None:
            return None
        doc = json.loads(data)
        if (not isinstance(doc, dict) or doc.get("policy") != POLICY or
                not _receipts().verify(Path(root), doc) or doc.get("grants_readiness") is not False or
                doc.get("case_outcome") != "unverified"):
            raise ValueError("Invalid saved setup intent")
        request = parse(doc["context"]["request"])
        return {**request, "job_id": doc["job_id"], "state": doc["state"],
                "case_outcome": "unverified", "detail": doc["detail"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unavailable", "case_outcome": "unverified",
                "detail": "Saved case repair context is unavailable; review and submit a new explicit goal."}
