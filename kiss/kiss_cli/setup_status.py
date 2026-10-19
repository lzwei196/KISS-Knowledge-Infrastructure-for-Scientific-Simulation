"""Latest setup diagnostics, with displaced operations retained as history.

These records explain host checks. They never grant readiness or replace the
independent configuration, KI, dependency and preflight verification gates.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import uuid


def read(root) -> dict:
    try:
        value = json.loads((Path(root) / "status.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def begin(root, previous: dict, *, model: str, operation: str) -> dict:
    """Archive the preceding evidence before constructing a non-ready status.

    Caller holds the existing setup lease/verification scope and publishes the
    returned document. Archive failure propagates; no old evidence is erased.
    """
    root = Path(root)
    saved_history = previous.get("history")
    history = [item for item in saved_history if isinstance(item, dict)] if isinstance(saved_history, list) else []
    error = previous.get("primary_error")
    error = error if isinstance(error, dict) else {}
    substantive = (previous.get("steps") or previous.get("checked_at")
                   or previous.get("verified_at") or previous.get("ok") is True
                   or error.get("name") not in {None, "setup-job", "verification-pending"})
    if substantive:
        old = dict(previous)
        old.pop("history", None)
        payload = json.dumps({"scope": "historical_only", "status": old},
                             ensure_ascii=False, indent=2).encode("utf-8")
        relative = Path(".geoforge/setup-status-history") / (uuid.uuid4().hex + ".json")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        history.append({"path": relative.as_posix(), "sha256": hashlib.sha256(payload).hexdigest(),
                        "scope": "historical_only", "outcome": "passed" if old.get("ok") else "not_passed",
                        "checked_at": old.get("checked_at") or old.get("verified_at")})
    return {"model": model, "ok": False, "verified_at": None,
            "verification_identity": None, "runtime_identity": None, "ki_content_digest": None,
            "installation_ready": False, "checked_at": None, "steps": [],
            "current_operation": {"id": uuid.uuid4().hex, "kind": operation, "started_at": time.time()},
            "history": history[-24:]}


def precheck(root, *, model, check) -> None:
    """Publish a real failed initial check before a provider can read status."""
    from . import setup_jobs
    document = begin(root, read(root), model=model, operation="initial_preflight")
    document.update(checked_at=time.time(),
        primary_error={"name": check.name, "detail": str(check.detail)[:4000]},
        steps=[{"name": check.name, "ok": False, "skipped": bool(check.skipped),
                "detail": str(check.detail)[:4000], "commands": list(check.commands)[:20],
                "evidence": dict(getattr(check, "evidence", {}) or {})}])
    setup_jobs._write(Path(root) / "status.json", document)


def guidance(root) -> str:
    """Bounded diagnostics for both API and CLI; historical errors stay out."""
    document = read(root)
    if not document:
        return ""
    error = document.get("primary_error")
    current = {"ok": document.get("ok") is True,
               "checked_at": document.get("checked_at"),
               "operation": document.get("current_operation"),
               "primary_error": error if document.get("ok") is not True else None,
               "history_available": bool(document.get("history"))}
    if isinstance(current["primary_error"], dict):
        current["primary_error"] = {"name": str(error.get("name", ""))[:100],
                                    "detail": str(error.get("detail", ""))[:4000]}
    return ("\n[CURRENT HOST SETUP STATUS]\n" + json.dumps(current, ensure_ascii=False) +
        "\nStart from this latest host diagnostic. status.json steps describe the current operation; "
        "history and setup-agent.log may contain earlier failed builds and earlier PASS results. "
        "Those are historical evidence, not current blockers or current readiness. A source/runtime "
        "currentness failure calls for verifying that binding; it does not by itself prove the "
        "compiled software is broken or justify rebuilding it. Preserve installed artifacts and "
        "diagnose the current primary_error. Only the unchanged host verification gates establish "
        "readiness; do not edit status records or restore an old PASS.\n")
