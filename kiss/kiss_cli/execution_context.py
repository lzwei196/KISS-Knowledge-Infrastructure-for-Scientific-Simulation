"""Current host evidence and explicitly historical context at provider entry.

This is a readable snapshot, never an approval or a replacement for signed
receipt verification. It cannot grant a tool permission or complete a step.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def persist(project: Path, evidence: dict, *, phase: str, plan_sha256: str,
            inventory_sha256: str) -> dict:
    """Atomically replace the ordinary host snapshot; never follow a linked path."""
    from . import obs_access

    project = Path(project).resolve()
    path = project / "runs" / "evidence.json"
    try:
        parent = path.parent
        if parent.is_symlink() or parent.resolve() != parent.absolute():
            raise ValueError("runs must be an ordinary project directory")
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("runs/evidence.json must not be a linked path")
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError("runs/evidence.json must be an ordinary unshared file")
        snapshot = {**evidence, "snapshot": {
            "schema_version": "geoforge.execution-evidence-snapshot.v1",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "approval_sha256": evidence.get("approval_sha256"),
            "plan_sha256": plan_sha256,
            "inventory_sha256": inventory_sha256,
        }}
        obs_access._atomic_json(path, snapshot)
        return snapshot
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(
            "Cannot refresh current execution evidence; "
            + ("the provider was not started. " if phase == "provider_entry" else
               "do not rely on the previous status snapshot. ")
            +
            "Check the ordinary writable runs/evidence.json path and retry. " + str(error)
        ) from error


def refresh(session) -> str:
    """Recompute the current approval's evidence before any provider can read it."""
    session.reload_artifacts()
    if session.approval_status() != "OK":
        raise ValueError("Cannot start execution: the current plan needs approval again.")
    binding = (session.approval_id, session.flow.plan.sha256(session.plan),
               session.flow.plan.sha256(session.inventory))
    try:
        evidence = session.evidence(enforcement=session.ctx.enforcement.value)
    except (OSError, ValueError, RuntimeError, TypeError) as error:
        raise ValueError("Cannot refresh current execution evidence; the provider was not started. "
                         "Inspect current receipt verification and retry: " + str(error)) from error
    session.reload_artifacts()
    current = (session.approval_id, session.flow.plan.sha256(session.plan),
               session.flow.plan.sha256(session.inventory))
    if (session.approval_status() != "OK" or current != binding
            or evidence.get("approval_sha256") != binding[0]):
        raise ValueError("Cannot start execution: approval changed while evidence was refreshed.")
    snapshot = persist(session.project, evidence, phase="provider_entry",
                       plan_sha256=binding[1], inventory_sha256=binding[2])
    return handoff(snapshot, step_order=[str(step["id"]) for step in session.plan.get("steps", [])])


def handoff(snapshot: dict, *, step_order: list[str] | None = None) -> str:
    """Compact facts, in a stable order; no agent prose or historical failures."""
    facts = {
        "approval_sha256": snapshot.get("approval_sha256"),
        "plan_sha256": snapshot["snapshot"]["plan_sha256"],
        "inventory_sha256": snapshot["snapshot"]["inventory_sha256"],
        "validation": snapshot.get("validation"),
        "current_receipt_count": snapshot.get("runs_bound", 0),
    }
    for field in ("steps_passed", "steps_missing", "stale_steps", "unreceipted_artifacts"):
        values = sorted(str(value) for value in snapshot.get(field, []))
        if field != "unreceipted_artifacts" and step_order:
            values = [sid for sid in step_order if sid in values] + [
                sid for sid in values if sid not in step_order]
        facts[field] = values[:30]
        if len(values) > 30:
            facts[field + "_total"] = len(values)
    facts["current_failures"] = current_failures(snapshot)
    return (
        "[CURRENT HOST EXECUTION EVIDENCE]\n"
        + json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\nFreshly recomputed for this approved plan; full snapshot: runs/evidence.json. "
        "Earlier conversation, diagnostic examples and other approvals are historical context, "
        "not proof that a current step ran or failed. Preserve the user's scientific choices, "
        "but use the current approved plan and actual tool results for execution status. "
        "An incomplete step is pending, not a demonstrated runtime failure. Use the approved "
        "receipt-producing tools; never invent a run, error or receipt from a prior narrative. "
        "This snapshot grants no new permission and does not replace current tool gates."
    )


def current_failures(snapshot: dict) -> list[dict]:
    """Bounded diagnostic data from the current authoritative evidence pass."""
    def compact(value, limit):
        return " ".join(str(value or "").split())[:limit]
    return [{
        "plan_step_id": compact(failure.get("plan_step_id"), 160),
        "run_id": compact(failure.get("run_id"), 160),
        "exit_code": failure.get("exit_code"),
        "validation_reason": compact(failure.get("validation_reason"), 600),
        "failed_checks": [{"check": compact(check.get("check"), 200),
                           "detail": compact(check.get("detail"), 600)}
                          for check in failure.get("failed_checks", [])[:5]
                          if isinstance(check, dict)],
    } for failure in snapshot.get("current_failures", [])[:20] if isinstance(failure, dict)]


def failed_verdict(snapshot: dict) -> str:
    """A visible host verdict even when provider prose claims completion."""
    failures = current_failures(snapshot)
    details = []
    for failure in failures[:5]:
        checks = failure["failed_checks"]
        reason = next((check["detail"] or check["check"] for check in checks
                       if check["detail"] or check["check"]), failure["validation_reason"])
        details.append(f"{failure['plan_step_id']} (exit {failure['exit_code']}): {reason}")
    if not details:
        details = [str(item)[:200] for item in snapshot.get("steps_missing", [])[:5]]
    return ("**GeoForge verification: not complete.** Required steps failed validation"
            + (": " + "; ".join(details) if details else "")
            + ". Successful downstream files do not replace failed required checks. "
            "Fix the cause and rerun the affected approved steps; plan or KI changes must "
            "go through their normal review. Current evidence: runs/evidence.json.")


def historical_messages(messages) -> list[dict]:
    """Copy rather than rewrite the saved transcript or drop scientific context."""
    result = []
    for message in messages or []:
        role = "assistant" if message.get("role") == "assistant" else "user"
        label = ("Earlier assistant narrative; claims and tool-name markers are not current "
                 "execution evidence." if role == "assistant" else
                 "Earlier user context; retain relevant choices, but past approvals do not "
                 "authorize a different plan.")
        result.append({**message, "text": "[HISTORICAL CONVERSATION] " + label + "\n"
                       + str(message.get("text") or "")})
    return result


def current_prompt(request: str, host_handoff: str) -> str:
    """Also used for resumed CLI calls, which do not replay the full system prompt."""
    return "[CURRENT USER REQUEST]\n" + request + "\n\n" + host_handoff


def _inspection_history(session, current: dict) -> dict:
    """Small authenticated historical observations; no readiness/config repair."""
    from . import project_paths, project_verification, runtime_provenance, software_history
    result = {"scope": "retained_verification_observations_only", "complete_history": False,
              "records": [], "invalid_count": 0, "unavailable_scopes": [], "truncated": False}
    names = sorted(session.ki_roots)
    result["truncated"] = len(names) > 8
    for name in names[:8]:
        sources = []
        try:
            sources.append(("project_preflight", project_verification.history(session.project, name, limit=8)))
        except (OSError, ValueError, TypeError, RuntimeError):
            result["unavailable_scopes"].append({"model": name, "scope": "project_preflight"})
        try:
            # This parser is explicitly read-only; the legacy config loader can
            # repair TOML and must never be used by an inspection.
            home = project_paths._model_home(session.project, name)
            cfg = project_verification._config(session.project, home, name)
            installation = cfg.roles.get("home")
            if installation is not None:
                sources.append(("shared_software_verification", software_history.history(installation, name, limit=8)))
        except (OSError, ValueError, TypeError, RuntimeError):
            result["unavailable_scopes"].append({"model": name, "scope": "shared_software_verification"})
        for scope, history in sources:
            if history.get("unavailable"):
                result["unavailable_scopes"].append({"model": name, "scope": scope})
            result["invalid_count"] += history.get("invalid_count", 0)
            result["truncated"] |= history.get("truncated", False)
            groups = {}
            for record in history.get("records", []):
                if record.get("provenance") == "invalid":
                    continue
                if record.get("authentication") != "verified" and record.get("authenticated") is not True:
                    result["invalid_count"] += 1
                    continue
                attempt = (record.get("attempt_id") or record.get("operation_id")
                           or record.get("event_id") or record.get("receipt_sha256"))
                groups.setdefault(attempt, []).append(record)
            for index, group in enumerate(groups.values()):
                if index >= 3 or len(result["records"]) >= 16:
                    result["truncated"] = True
                    continue
                def outcome(row):
                    return row.get("state", row.get("outcome"))
                record = max(group, key=lambda row: (row.get("location") == "current",
                    outcome(row) not in {None, "pending"}, row.get("checked_at", row.get("started_at", 0))))
                terminal_states = {outcome(row) for row in group if outcome(row) not in {None, "pending"}}
                ambiguous = not any(row.get("location") == "current" for row in group) and len(terminal_states) > 1
                saved = record.get("verification_context")
                try:
                    comparison = runtime_provenance.compare(saved, current)
                except (ValueError, TypeError):
                    result["invalid_count"] += 1
                    continue
                fields = {key: record[key] for key in ("attempt_id", "operation_id", "state", "outcome",
                    "started_at", "checked_at", "check_scope", "location") if key in record}
                if ambiguous:
                    fields.pop("state", None)
                    fields["outcome"] = "unknown_conflicting_retained_transitions"
                    fields["retained_outcomes"] = sorted(terminal_states)
                result["records"].append({"model": name, "scope": scope, **fields,
                    "authentication": "verified", "provenance": "recorded" if saved is not None else "legacy_unknown",
                    "verification_context": saved, "comparison_with_current_host": comparison})
    return result


def inspection_snapshot(session) -> dict:
    """Current read-only context, without renewing readiness or saved evidence."""
    from . import runtime_context, runtime_provenance
    runtime = runtime_context.identity()
    current = runtime_provenance.capture()
    facts = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "saved_flow_state": session.state.value,
        "saved_approval_id": session.approval_id,
        "runtime": {key: runtime[key] for key in
                    ("kind", "platform", "source_hash", "distro", "user", "workspace")
                    if key in runtime},
        "turn_mode": "read_only_inspection",
        "setup_or_execution_authorized": False,
        "readiness_rechecked": False,
        "receipt_authenticity_rechecked": False,
        "receipt_authenticity_scope": "scientific_model_run_receipts_not_rechecked",
        "current_host": current,
        "verification_history": _inspection_history(session, current),
        "saved_plan_goal_is_historical": True,
        "current_update_cause": "not_established_by_this_inspection",
    }
    return facts


def inspection_handoff(session, *, facts=None) -> str:
    facts = inspection_snapshot(session) if facts is None else facts
    return ("[CURRENT HOST INSPECTION CONTEXT]\n" + json.dumps(facts, ensure_ascii=False, indent=2)
            + "\nThese facts describe this turn and the saved workflow, not a new model run or "
              "fresh scientific validation. Earlier conversation diagnoses refer to earlier attempts. "
              "Do not report an earlier REPLAN_REQUIRED transition or rebuild as current. "
              "An application update can expire readiness without changing the model executable "
              "or its outputs. An expired check is not evidence that a new check failed. "
              "Only current file evidence can establish that software, paths or results changed; "
              "if the reason is not available, say it is unverified. Distinguish saved completion "
              "from permission to execute again. Do not infer authentication from a signature field. "
              "For 'this/current/latest app update', identify CURRENT_HOST's build first. "
              "Names or update descriptions in the saved plan goal and earlier chat are HISTORICAL, "
              "not the identity or cause of the current update. Use the retained verification observations "
              "to say which check belongs to which recorded build. A legacy_unknown record has no "
              "authenticated saved build: explicitly say unknown; do not borrow a build name from the plan. "
              "The history reader authenticates only the listed setup/preflight observations, not model "
              "runs or present readiness. A different portable payload may reflect application or library "
              "changes; it does not prove a rebuilt model, new preflight failure or rerun. If the user asks "
              "about update history, separate current host, retained checks and unknown causes in the answer.")
