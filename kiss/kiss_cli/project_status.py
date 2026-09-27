"""Read-only project status from existing Flow, acquisition and activity facts.

snapshot() is the common interpretation for the status button, panel and details.
It never advances Flow, adopts agent reports, approves, downloads or writes proof.
The GUI keeps its existing poll-driven acquisition work outside this module.
"""
from __future__ import annotations

import json
import math
import copy
import threading
import time
from pathlib import Path

from . import acquire, flowgate, obs_access, plan_review, projectrun, setup as setup_flow


# Presentation-only cache. Never used by approval, acquisition or tool gates.
# Every status read checks file metadata again; changed files invalidate it.
# This prevents the fast /run poll from repeatedly hashing static GB datasets.
_EVIDENCE_CACHE: dict = {}
_CACHE_LOCK = threading.RLock()


def _file_stamp(path: Path) -> tuple:
    try:
        stat = path.stat()
        link = path.lstat()
        return (str(path), str(path.resolve()), link.st_ino, link.st_mtime_ns, link.st_ctime_ns,
                stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except (OSError, RuntimeError):
        return (str(path), "missing")


def _evidence_stamp(project: Path, flow) -> tuple:
    """Observe receipt files and referenced bytes, plus artifact membership.

    Metadata is an invalidation signal, not a scientific check or new gate.
    A fresh cache entry still comes only from the shared receipt inspector.
    """
    files = {flow.receipts.keys_dir() / f"{flow.receipts.project_id(project)}.key"}
    for name in ("plan.json", "data-inventory.json", "approval.json"):
        files.add(project / "runs" / name)
    base = project / flow.receipts.RECEIPT_DIR
    for path in base.rglob("*.json") if base.is_dir() else []:
        files.add(path)
        doc = _read(path)
        for field in ("raw_files", "processed_files", "outputs", "inputs"):
            for item in doc.get(field) or []:
                if isinstance(item, dict) and item.get("path"):
                    p = Path(item["path"])
                    files.add(p if p.is_absolute() else project / p)
    for sub in ("inputs", "outputs", "artifacts", "calibration"):
        folder = project / sub
        if folder.is_dir():
            files.update(p for p in folder.rglob("*") if p.is_file())
    return tuple(_file_stamp(path) for path in sorted(files))


def _checked_evidence(project: Path, flow, pj: dict, inv: dict, approval: str,
                      enforcement: str, now: float) -> tuple:
    approval_doc = flow.approval.read(project) if approval == "OK" else None
    ident = flow.approval.approval_id(approval_doc or {})
    stamp = (approval, ident, enforcement, flow.plan.sha256(pj), flow.plan.sha256(inv),
             _evidence_stamp(project, flow))
    key = str(project.resolve())
    with _CACHE_LOCK:
        cached = _EVIDENCE_CACHE.get(key)
        if cached and cached[0] == stamp:
            return copy.deepcopy(cached[1])
    downloads = flow.receipts.inspect_downloads(project, inv, approval_sha256=ident)
    proof = (flow.receipts.evidence(project, pj, approval_doc, inventory=inv,
                                   enforcement=enforcement, _download_inspection=downloads)
             if approval == "OK" else {})
    result = (proof, downloads, now)
    # Do not cache a scan whose files changed during inspection. Slow disk reads
    # are outside the map lock so one large project cannot block all others.
    if stamp[-1] != _evidence_stamp(project, flow):
        raise ValueError("Project files changed during evidence inspection; status is unconfirmed. Refresh to inspect again.")
    with _CACHE_LOCK:
        if len(_EVIDENCE_CACHE) >= 32:
            _EVIDENCE_CACHE.pop(next(iter(_EVIDENCE_CACHE)))
        _EVIDENCE_CACHE[key] = (stamp, copy.deepcopy(result))
    return result


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _read(path: Path) -> dict:
    try:
        return _dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _age(timestamp, now: float) -> int | None:
    try:
        stamp = float(timestamp)
        return max(0, int(now - stamp)) if math.isfinite(stamp) and stamp > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _observation(source: str, timestamp, now: float, summary: str) -> dict:
    return {"source": source, "observed_at": timestamp, "age_seconds": _age(timestamp, now),
            "summary": summary}


def _data_summary(pd: dict | None) -> dict:
    rows = (pd or {}).get("items") or []
    counts = (pd or {}).get("counts") or {}
    available = sum(counts.get(s, 0) for s in ("present_unverified", "acquired", "produced"))
    bad = counts.get("failed", 0) or counts.get("missing", 0)
    coverage_gap = any(_dict(r.get("match")).get("status") == "insufficient" for r in rows)
    binding_failed = _dict((pd or {}).get("binding_status")).get("status") == "needs_review"
    if bad or coverage_gap or binding_failed:
        severity, label = "block", "Data needs attention"
    elif counts.get("waiting_for_you"):
        severity, label = "warn", "Waiting for your input"
    elif available:
        severity, label = "warn", "Files available; preparation and scientific checks still required"
    elif rows:
        severity, label = "warn", "Data preparation pending"
    else:
        severity, label = "", "Data readiness unconfirmed"
    return {"severity": severity, "label": label, "available": available, "total": len(rows)}


def _technical(preparation: dict, plans: list, summary: dict) -> dict:
    # A KI lane is a declaration, not a mapping to the approved inventory.
    # Do not infer per-lane validation from the project stage or another lane.
    required = [item for plan in plans for item in _dict(plan).get("datasets", [])
                if isinstance(item, dict) and not item.get("optional")]
    lanes = {}
    for lane in preparation.get("lanes") or []:
        if not isinstance(lane, dict):
            continue
        label, cls, mark = "Readiness unconfirmed", "", "?"
        note = "KI requirements; no individual scientific validation is established by this view."
        if lane.get("id") == "source_data" and required:
            present = sum(bool(i.get("present")) for i in required)
            missing = len(required) - present
            note = f"{present} / {len(required)} required paths contain files; presence is not scientific validation."
            label, cls, mark = (f"{missing} required paths missing", "warn", "!") if missing else (
                "Files present; not validated", "warn", "•")
        elif lane.get("local_file_count"):
            label, cls, mark = "Files present; not validated", "warn", "•"
        lanes[str(lane.get("id"))] = {"label": label, "cls": cls, "mark": mark, "note": note}
    return {"overall": {"label": summary["label"], "cls": summary["severity"], "mark": "?",
                        "note": "Acquisition, preparation and scientific validation are separate."},
            "lanes": lanes}


def _progress(report: dict, *, state: str, stage: str, selected: list, plan: dict,
              request: dict | None, proof: dict, approval: str, acquisition: dict,
              activity: dict, errors: list, observed_at, now: float) -> dict:
    active = activity.get("state") == "running" and activity.get("process_alive") is True
    complete = (state == "COMPLETED" and approval == "OK"
                and proof.get("receipts_verified") is True and proof.get("validation") == "passed")
    needs_approval = state in {"APPROVED", "ACQUIRING", "EXECUTING", "VERIFYING", "COMPLETED",
                               "SETUP_REQUIRED", "SETUP_RUNNING", "SETUP_VERIFIED"}
    if errors:
        status, summary, actor = "failed", "Project evidence is unreadable; inspect status details.", "user"
    elif request:
        status, summary, actor = "waiting_for_user", str(request.get("title") or "One thing needs you"), "user"
    elif needs_approval and approval != "OK":
        status, summary, actor = "waiting_for_user", "The current plan needs approval before work can continue.", "user"
    elif state in {"FAILED", "FAILED_VALIDATION"} or proof.get("validation") == "failed":
        status, summary, actor = "failed", "An execution attempt failed; agent diagnosis is needed.", "agent"
    elif state == "BLOCKED" or acquisition.get("status") == "failed":
        status, summary, actor = "failed", "Project work is blocked; inspect the acquisition or planning details.", "user"
    elif complete:
        status, summary, actor = "complete", "Flow completed with current approved execution evidence.", "none"
    elif state == "COMPLETED":
        status, summary, actor = "failed", "Flow recorded completion, but current evidence does not establish it.", "agent"
    elif state in {"WAITING_FOR_USER", "PLAN_REVIEW"}:
        status, summary, actor = "waiting_for_user", "Review or input is needed; no active request is available.", "user"
    elif state == "ACQUIRING":
        status, summary, actor = "working", "Waiting for approved data acquisition; model execution has not started.", "host"
    elif active:
        status, summary, actor = "working", "Agent turn active; this alone does not prove model progress.", "agent"
    elif report.get("status") == "failed":
        status, summary, actor = "failed", "The agent reported a problem; scientific outcome is unconfirmed.", "agent"
    else:
        status, summary, actor = "idle", "Project unfinished; no active agent turn is observed.", "agent"
        if state in {"", "NEW"} and not report.get("goal") and not plan.get("goal"):
            summary, actor = "Describe the scientific goal in chat to begin.", "user"
    result = {**report, "status": status, "stage": stage or "understanding", "summary": summary,
              "goal": plan.get("goal") or report.get("goal") or "",
              "selected_kis": selected or report.get("selected_kis") or [],
              "flow_state": state or None, "science_complete": complete,
              "next_actor": actor, "source": "Flow and signed evidence" if state else "Unverified project report",
              "observed_at": observed_at, "age_seconds": _age(observed_at, now),
              "reported_status": report.get("status"), "reported_summary": report.get("summary"),
              "errors": errors}
    result.pop("blocker", None)
    if request:
        result["blocker"] = request
    return result


def snapshot(project: Path, *, report: dict | None = None, plans: list | None = None,
             preparation: dict | None = None, activity: dict | None = None,
             now: float | None = None) -> dict:
    """Interpret existing facts without changing them or trusting chat completion.

    Supplied reports/preparation/activity are observations, never approval or
    scientific proof. The canonical waiting request is preserved verbatim so all
    views reopen the same actionable card, including its full reviewed display.
    No report-only historical blocker is promoted to a new pending request.
    """
    project = Path(project)
    now = time.time() if now is None else now
    report = _dict(report) if report is not None else _read(project / "runs" / projectrun.STATE_FILE)
    activity, preparation = _dict(activity), _dict(preparation)
    errors, proof = [], {}
    acquisition_history = _dict(acquire.status(project))
    acquisition = {}
    request = None
    try:
        # setup.request normally performs a legacy migration; status must not.
        request = setup_flow.request(project, archive_obsolete=False)
        request = request if request and request.get("status") == "waiting" else None
        request_path = project / setup_flow.REQUEST_FILE
        if request_path.is_file():
            raw_request = json.loads(request_path.read_text(encoding="utf-8"))
            if not isinstance(raw_request, dict):
                raise ValueError("expected a request object")
    except (OSError, ValueError) as error:
        errors.append(f"Pending request unreadable: {error}")
    downloads, checked_at = [], None
    state, stage, selected, observed_at, approval = "", "", [], None, "MISSING"
    pj, inv, flow = None, None, None
    try:
        flow = flowgate.load()
        ctx = flow.states.FlowContext.load(project)
        state, stage = ctx.state.value, flow.states.DISPLAY_STAGE.get(ctx.state, "understanding")
        selected, observed_at = list(ctx.selected_kis), ctx.updated_at or None
        pj, inv = flow.plan.read_artifacts(project)
        if isinstance(pj, dict) and isinstance(inv, dict):
            approval = flow.approval.check(project)
            ident = flow.approval.approval_id(flow.approval.read(project) or {}) if approval == "OK" else ""
            if ident and acquisition_history.get("approval_sha256") == ident:
                acquisition = acquisition_history
            proof, downloads, checked_at = _checked_evidence(
                project, flow, pj, inv, approval, ctx.enforcement.value, now)
    except Exception as error:  # unreadable/corrupt proof is unknown, never success
        errors.append(f"{type(error).__name__}: {error}")
    pd = None
    if flow and isinstance(pj, dict) and isinstance(inv, dict):
        try:
            pd = _plan_data(project, flow, pj, inv, proof, request, acquisition, downloads)
        except Exception as error:
            errors.append(f"Data status unavailable: {type(error).__name__}: {error}")
    summary = _data_summary(pd)
    if errors:
        summary.update(severity="block", label="Status evidence needs inspection")
    progress = _progress(report, state=state, stage=stage, selected=selected, plan=pj or {},
                         request=request, proof=proof, approval=approval, acquisition=acquisition,
                         activity=activity, errors=errors, observed_at=observed_at, now=now)
    observations = []
    if observed_at:
        observations.append(_observation("Flow state", observed_at, now, state))
    if checked_at:
        observations.append(_observation("Signed evidence inspection", checked_at, now,
                                         "Cached only while receipt and file metadata remain unchanged."))
    if report.get("updated_at"):
        observations.append(_observation("Agent/app report (not scientific proof)", report["updated_at"], now,
                                         str(report.get("summary") or "")))
    if acquisition.get("updated_at"):
        observations.append(_observation("Host acquisition observation", acquisition["updated_at"], now,
                                         str(acquisition.get("status") or "unknown")))
    if activity:
        observations.append({"source": "Provider activity (not model progress)",
                             "age_seconds": activity.get("event_silence_seconds"),
                             "observed_at": None,
                             "summary": str(activity.get("activity_detail") or activity.get("state") or "unknown")})
    return {"progress": progress, "request": request, "plan_data": pd, "data_summary": summary,
            "technical": _technical(preparation, plans or [], summary), "observations": observations,
            "execution": proof, "acquisition": acquisition, "acquisition_history": acquisition_history,
            "evidence_checked_at": checked_at, "errors": errors}


def _plan_data(project: Path, flow, pj: dict, inv: dict, proof: dict,
               request: dict | None, acq: dict, downloads: list) -> dict:
    groups = plan_review.input_groups(pj, inv, project)
    by_id = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    receipted: set[str] = set()
    acquisitions: dict[str, dict] = {}
    for result in downloads:
        if result.reusable:
            receipt = result.receipt
            receipted.add(str(receipt.get("item_id")))
            if receipt.get('acquisition'):
                acquisitions[str(receipt.get('item_id'))] = receipt['acquisition']
    passed = set(proof.get("steps_passed") or [])
    produced_by = {str(o): str(st.get("id")) for st in pj.get("steps") or [] if isinstance(st, dict)
                   for o in st.get("outputs") or []}
    waiting_title = str(request.get("title") or "") if request and request.get("status") == "waiting" else ""
    waiting_items = {str(r.get("item_id")) for r in (request or {}).get("rows") or []} if waiting_title else set()
    acq_items = acq.get("items") or {}

    def _local(item: dict) -> bool:
        for raw in item.get("local_paths") or []:
            path = Path(str(raw).replace("${PROJECT}", str(project)))
            if not path.is_absolute():
                path = project / path
            if setup_flow.data_path_present(path):
                return True
        return False

    rows: list[dict] = []
    consumed = {str(i) for st in pj.get("steps") or [] if isinstance(st, dict) for i in st.get("inputs") or []}
    for group in ("fetch", "you", "run"):
        for row in groups[group]:
            item = by_id.get(str(row.get("id")), {})
            dataset_id = row.get("dataset_id") or ""
            how = row.get("how")
            if str(row.get("id")) not in consumed and how not in ("generated", "on_disk"):
                status = "unused"          # listed by the agent, used by no step: nothing fetches it
            elif how == "generated":
                status = "produced" if produced_by.get(str(row.get("id"))) in passed else "pending"
            elif how in ("prepared", "default"):
                status = "pending"
            elif how == "provide":
                target = project / str(row.get("target_path") or "")
                status = "present_unverified" if any(p.is_file() and not p.name.startswith(".") for p in target.rglob("*")) \
                    else "waiting_for_you"
            elif how == "choose":
                status = "waiting_for_you"
            elif str(row.get('id')) in acquisitions:
                status = 'acquired'
            elif str(row.get("id")) in receipted:
                status = "acquired"
            elif (acq_items.get(str(row.get("id"))) or {}).get("status") == "failed":
                status = "failed"
            elif _local(item):
                status = "present_unverified"
            elif how == "manual" and (str(row.get("id")) in waiting_items
                                      or (waiting_title and waiting_title.endswith(dataset_id or str(row.get("id"))))):
                status = "waiting_for_you"
            elif (acq_items.get(str(row.get("id"))) or {}).get("status") == "failed":
                status = "failed"
            else:
                status = "pending"
            requirements = item.get("requirements") or {}
            try:
                match = obs_access.assess_dataset(item.get("catalogue") or {}, **{
                    k: requirements[k] for k in ("bbox", "start", "end", "variable")
                    if isinstance(requirements, dict) and requirements.get(k)})
            except (TypeError, ValueError):
                match = {"status": "unknown", "checks": {}, "note": "Invalid data requirements"}
            if match["status"] == "insufficient":
                action = "choose_data"
            elif status in {"present_unverified", "acquired", "produced"}:
                action = "agent_validate"
            elif item.get('delivery') == 'subset':
                action = 'acquire_subset'
            elif how in {"generated", "prepared", "default"}:
                action = "agent_prepare"
            elif item.get("delivery") == "manual":
                action = "manual_download"
            elif item.get("delivery") == "served":
                action = "agent_download" if match["status"] == "covered" else "check_coverage"
            else:
                action = "choose_data" if how == "provide" else "check_coverage"
            rows.append({"id": row.get("id"), "group": group, "how": how, "note": row.get("note"),
                         "facts": row.get("facts"), "target_path": row.get("target_path"), "status": status,
                         "action": action, "match": match,
                         "evidence_source": "signed_receipt" if status in {"acquired", "produced"} else
                                            "local_files" if status == "present_unverified" else "project_inventory",
                         "resolution": (item.get("catalogue") or {}).get("resolution"),
                         "size": (item.get("catalogue") or {}).get("size"),
                         'acquisition_id': item.get('acquisition_id'),
                         'scientific_validation': 'pending',
                         "dataset_id": dataset_id or None, "size_label": row.get("size_label") or "",
                         "for": row.get("for") or [], "delivery": item.get("delivery")})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    binding_status = obs_access._read_snapshot(project / '.geoforge/data-binding-status.json') or {}
    return {"items": rows, "counts": counts, "total": len(rows), 'binding_status': binding_status}
