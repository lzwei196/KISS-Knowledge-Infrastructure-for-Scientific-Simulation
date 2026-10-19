"""Explicit next-phase consent and historical-only snapshots of completed work.

An agent cannot call this route. The GUI passes the user's phase-bound action
to flowrun.pre before a new provider turn. Archived approvals are never restored.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path

POLICY = "geoforge.completed-phase.v1"
ACTION = "plan_next_phase"
FILES = ("plan.json", "data-inventory.json", "approval.json")
MAX_BYTES = 16 * 1024 * 1024


def _ordinary(path: Path, project: Path, *, directory=False, missing=False):
    if not path.is_relative_to(project) or path.resolve() != path:
        raise ValueError("Phase history paths must be ordinary project paths")
    for part in (path, *path.parents):
        if not part.is_relative_to(project):
            break
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise ValueError("Phase history source is missing") from None
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)):
            raise ValueError("Phase history paths must not use links or junctions")
        want_dir = part != path or directory
        if want_dir and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Phase history directory is not ordinary")
        if not want_dir and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("Phase history source must be an ordinary, unlinked file")


def _read(path: Path, project: Path) -> bytes:
    _ordinary(path, project)
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Phase history source exceeds the bounded snapshot limit")
    return data


def _capture(project: Path, flow):
    project = Path(project).resolve()
    ctx = flow.states.FlowContext.load(project)
    if ctx.state.value != "COMPLETED":
        raise ValueError("Only the current completed phase can start a new phase")
    payload = {name: _read(project / "runs" / name, project) for name in FILES}
    docs = {name: json.loads(raw) for name, raw in payload.items()}
    if not all(isinstance(doc, dict) for doc in docs.values()):
        raise ValueError("Completed phase documents must be objects")
    approval = docs["approval.json"]
    if (flow.approval.check(project) != "OK" or not flow.receipts.verify(project, approval)
            or approval != flow.approval.read(project)
            or approval.get("plan_sha256") != flow.plan.sha256(docs["plan.json"])
            or approval.get("data_inventory_sha256") != flow.plan.sha256(docs["data-inventory.json"])):
        raise ValueError("The completed phase approval or plan has changed")
    phase = {"state": "COMPLETED", "approval_id": flow.approval.approval_id(approval),
             "plan_sha256": approval["plan_sha256"],
             "data_inventory_sha256": approval["data_inventory_sha256"]}
    return phase, payload


def action(project: Path, flow) -> dict | None:
    """Read-only GUI capability; a stale click never grants replanning."""
    try:
        phase, _ = _capture(project, flow)
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    return {"kind": ACTION, "phase": phase}


def begin(project: Path, flow, requested: dict, *, reason: str) -> Path:
    """Snapshot exact bytes, recheck the bound click, then revoke and replan.

    A snapshot or stale-action failure happens before approval revocation. If
    the final state save fails, the revoked approval stays revoked; no rollback
    may resurrect execution consent.
    """
    project = Path(project).resolve()
    if set(requested) - {"kind", "phase", "note"} or requested.get("kind") != ACTION:
        raise ValueError("Invalid next-phase action")
    phase, payload = _capture(project, flow)
    if requested.get("phase") != phase:
        raise ValueError("This next-phase choice is stale; refresh Project status")
    history = project / ".geoforge" / "phase-history"
    _ordinary(history, project, directory=True, missing=True)
    history.mkdir(parents=True, exist_ok=True)
    target = history / phase["approval_id"]
    _ordinary(target, project, directory=True, missing=True)
    records = {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
               for name, raw in payload.items()}
    unsigned = {"policy": POLICY, "historical_only": True, "phase": phase, "files": records}
    def require_archive(folder):
        record = json.loads(_read(folder / "record.json", project))
        if (not isinstance(record, dict) or not flow.receipts.verify(project, record)
                or {key: record.get(key) for key in unsigned} != unsigned
                or any(_read(folder / name, project) != raw for name, raw in payload.items())):
            raise ValueError("Completed-phase history is not authentic")
    if target.exists():
        require_archive(target)
    else:
        stage = history / (".pending-" + uuid.uuid4().hex)
        stage.mkdir()
        for name, raw in payload.items():
            (stage / name).write_bytes(raw)
        record = flow.receipts.sign(project, unsigned)
        (stage / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        require_archive(stage)
        os.rename(stage, target)  # unique immutable destination; never overwrite history
        require_archive(target)
    current_phase, current_payload = _capture(project, flow)
    if current_phase != phase or current_payload != payload:
        raise ValueError("The completed phase changed while it was being archived")
    flow.approval.revoke(project, reason or "User selected Plan next phase")
    ctx = flow.states.FlowContext.load(project)
    ctx.move("replan")
    return target
