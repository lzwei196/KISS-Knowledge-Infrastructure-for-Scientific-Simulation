"""flow.approval — the user's (or the app's) approval of a plan, bound to its hash and SIGNED.

Plan v3 map A4. The file shape is the issue's `runs/approval.json`. The
carry-then-bind idea comes from chat's plan-carry (api/chat.py L941-985): once
approved, the plan is frozen; execution binds to it and never re-derives. Chat's
"plan did not carry → fail loud, do NOT silently re-derive" (L972-985) is kept
as `check() == "MISSING"` blocking execution.

Codex review #6: a hand-written approval.json whose hashes matched the plan files
used to pass `check()`. Now the approval is HMAC-signed with the project key
(same key as receipts, kept outside the project) and `check()` verifies the
signature, the schema, `approved_by in {user, auto}` and the plan hashes. Only app
code holds the key path; the tool policy also denies the agent any write to the
file (flow.policy.protected_paths).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from .plan import HIGH_IMPACT_CHOICES, read_artifacts, sha256
from . import receipts as _r

FILE = "approval.json"
SCHEMA_VERSION = "1.0"
_REQUIRED = ("schema_version", "plan_sha256", "data_inventory_sha256", "approved_by",
             "approved_at", "decisions", "selected_kis", "signature")
# Added by the 2026-09 unification (desktop tool_sha256, web approval_nonce). A signed
# document from before then lacks them: that is a legacy approval, answered as DRIFT
# (re-approve once), never FORGED (which reads as "someone edited approval.json").
_UNIFIED = ("tool_sha256", "approval_nonce")


def _path(project: Path) -> Path:
    return Path(project) / "runs" / FILE


def may_auto_approve(plan: dict, inventory: dict) -> tuple[bool, list[str]]:
    """Issue §A.4 + user decision 3: auto-approve only when nothing needs the user and
    no high-impact scientific choice is open. Returns (ok, reasons_it_is_not_ok)."""
    why: list[str] = []
    for it in (inventory or {}).get("items") or []:
        if isinstance(it, dict) and it.get("needs_user") and not it.get("decision"):
            why.append(f"data item {it.get('id')!r} needs the user")
    for ch in (plan or {}).get("scientific_choices") or []:
        if not isinstance(ch, dict):
            continue
        hi = ch.get("high_impact")
        if hi is None:
            hi = ch.get("kind") in HIGH_IMPACT_CHOICES
        if hi and not ch.get("decision"):
            why.append(f"scientific choice {ch.get('id')!r} is high-impact and undecided")
    for q in (plan or {}).get("unresolved_questions") or []:
        why.append(f"unresolved question: {q}")
    return (not why), why


_HASH_CACHE: dict[tuple[str, int, int], str] = {}


def _cached_sha256(path: Path) -> str:
    """check() runs on every gated command; a declared model binary can be hundreds of MB.
    Re-hash only when size or mtime changed."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    h = _HASH_CACHE.get(key)
    if h is None:
        h = _r.sha256_file(path)
        if len(_HASH_CACHE) > 512:
            _HASH_CACHE.clear()
        _HASH_CACHE[key] = h
    return h


def _tool_hashes(plan: dict) -> dict[str, dict[str, str]]:
    """Hash every executable named by the plan at approval time. Tools must be absolute
    (plan.validate refuses relative ones): the approval is checked from other processes
    whose cwd is not the project."""
    result: dict[str, dict[str, str]] = {}
    for step in (plan or {}).get("steps") or []:
        if not isinstance(step, dict) or not step.get("tool"):
            continue
        step_id = str(step.get("id") or "")
        path = Path(str(step["tool"])).expanduser()
        if not path.is_absolute():
            raise FileNotFoundError(f"cannot approve: step {step_id!r} tool is not an absolute path: {path}")
        path = path.resolve()
        if not step_id or not path.is_file():
            raise FileNotFoundError(f"cannot approve: step {step_id!r} tool does not exist: {path}")
        result[step_id] = {"path": str(path), "sha256": _cached_sha256(path)}
    return result


def approve(project: Path, decisions: dict | None = None, by: str = "user") -> dict:
    """Write a SIGNED runs/approval.json for the CURRENT plan files. Raises if they are
    missing or invalid-shaped."""
    plan, inv = read_artifacts(project)
    if plan is None or inv is None:
        raise FileNotFoundError("cannot approve: runs/plan.json and runs/data-inventory.json "
                                "must both exist")
    if by not in ("user", "auto"):
        raise ValueError("approved_by must be 'user' or 'auto'")
    doc = {
        "schema_version": SCHEMA_VERSION,
        "plan_sha256": sha256(plan),
        "data_inventory_sha256": sha256(inv),
        "tool_sha256": _tool_hashes(plan),
        "approved_by": by,
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # Distinguishes revoke/re-approve cycles even within the same second.  The
        # registry binds to the resulting signature, so an older approval cannot replay.
        "approval_nonce": secrets.token_hex(16),
        "decisions": dict(decisions or {}),
        "selected_kis": list(plan.get("selected_kis") or []),
    }
    doc = _r.sign(project, doc)
    p = _path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(project) / ".geoforge" / "tmp"          # protected tree (kimi R2 #3)
    tmpdir.mkdir(parents=True, exist_ok=True)
    tmp = tmpdir / f"approval.{os.getpid()}.json"
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    _r.publish_current(Path(project), "approval", doc)
    return doc


def read(project: Path) -> dict | None:
    try:
        doc = json.loads(_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def approval_id(doc: dict) -> str:
    """The value receipts bind to: this unique, signed approval issuance."""
    sig = (doc or {}).get("signature") if isinstance(doc, dict) else None
    return str(sig.get("value") or "") if isinstance(sig, dict) else ""


def check(project: Path) -> str:
    """'OK' when a SIGNED, well-formed approval exists and both hashes still match the
    files on disk; 'MISSING' when there is no (valid) approval or no plan; 'FORGED' when
    the file exists but its signature or schema fails; 'DRIFT' when a plan file changed
    after approval — the driver must move the state to REPLAN_REQUIRED."""
    doc = read(project)
    if not doc:
        return "MISSING"
    if any(k not in doc for k in _REQUIRED) or doc.get("schema_version") != SCHEMA_VERSION \
            or doc.get("approved_by") not in ("user", "auto") \
            or not isinstance(doc.get("decisions"), dict) \
            or not isinstance(doc.get("selected_kis"), list) \
            or ("tool_sha256" in doc and not isinstance(doc.get("tool_sha256"), dict)):
        return "FORGED"
    if not _r.verify(project, doc):
        return "FORGED"
    if any(k not in doc for k in _UNIFIED):
        return "DRIFT"                      # genuine signature, pre-unification shape: re-approve
    if not _r.current_matches(project, "approval", doc):
        return "FORGED"
    plan, inv = read_artifacts(project)
    if plan is None or inv is None:
        return "MISSING"
    if doc.get("plan_sha256") != sha256(plan) or doc.get("data_inventory_sha256") != sha256(inv):
        return "DRIFT"
    if list(plan.get("selected_kis") or []) != list(doc.get("selected_kis") or []):
        return "DRIFT"
    try:
        hashes = _tool_hashes(plan)
    except FileNotFoundError:
        return "DRIFT"                      # a tool the plan names is gone (or not absolute)
    except OSError as e:
        # A transient read error (mount hiccup, EIO) must never become a verdict: the web
        # revokes the approval on anything but OK. Fail the call; the caller retries.
        raise RuntimeError(f"approval check could not hash a step tool: {e}") from e
    if doc.get("tool_sha256") != hashes:
        return "DRIFT"
    return "OK"


def revoke(project: Path, reason: str = "") -> None:
    """Used on DRIFT / REPLAN: keep the old approval for the record, renamed."""
    p = _path(project)
    # Revoke at the server authority first.  If archiving the workspace copy then fails,
    # the old signed document is still unusable and cannot be replayed as current.
    if p.exists() or _r.registry_entry(project).exists():
        _r.publish_current(Path(project), "approval", None)
    if p.exists():
        stamp = time.strftime("%Y%m%dT%H%M%S")
        p.replace(p.with_name(f"approval.revoked.{stamp}.json"))
        (p.parent / f"approval.revoked.{stamp}.reason.txt").write_text(reason or "revoked",
                                                                       encoding="utf-8")
