"""ACQUIRING: the host fetches every approved input before any agent step runs.

FLOW-TARGET-2026-09-17 step 3. Plan approval is the user's consent; this module
is its consequence. Served datasets download directly, server clips advance
their approved job, manual (Baidu) datasets are handed to the user in one card
and get a signed placed-file receipt when the files are there. Progress lives
in ``.geoforge/acquisition.json`` (host-owned, never hashed by the approval);
proof lives in the signed data receipts. Nothing here edits the plan files.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path

from . import obs_access, obs_subset, setup as setup_flow

STATUS_FILE = Path(".geoforge/acquisition.json")
REPLAN_FILE = Path(".geoforge/acquisition-replan.json")
MANUAL_DETAILS_FILE = Path(".geoforge/manual-download-details.json")
INTENT_LOCK = threading.RLock()  # only intent publication/admission, never network I/O
ACQUIRABLE = ("served", "subset", "manual")
MANUAL_REQUEST_ID = "flow-manual-download"


def _flow():
    from . import flowgate
    return flowgate.load()


def _local_present(project: Path, item: dict) -> bool:
    for raw in item.get("local_paths") or []:
        path = Path(str(raw).replace("${PROJECT}", str(project)))
        if not path.is_absolute():
            path = Path(project) / path
        if setup_flow.data_path_present(path):
            return True
    return False


def needed(plan: dict | None, inventory: dict | None, project: Path | None = None) -> list[dict]:
    """Inventory items the host must bring in: named delivery, consumed by a step,
    not already on disk under a path the plan names."""
    steps = [s for s in (plan or {}).get("steps") or [] if isinstance(s, dict)]
    out = []
    for item in (inventory or {}).get("items") or []:
        if not isinstance(item, dict) or item.get("delivery") not in ACQUIRABLE:
            continue
        if item.get("status") == "ready" and project is not None and _local_present(project, item):
            continue
        consumers = [str(s.get("id")) for s in steps if str(item.get("id")) in (s.get("inputs") or [])]
        if consumers:
            out.append({**item, "_step": next((s for s in consumers), None)})
    return out


def status(project: Path) -> dict:
    path = Path(project) / STATUS_FILE
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"status": "idle", "items": {}}


def _write(project: Path, doc: dict) -> dict:
    doc["updated_at"] = time.time()
    obs_access._atomic_json(Path(project) / STATUS_FILE, doc)
    return doc


def _current_approval(project: Path, flow, approval: str) -> bool:
    return approval == flow.approval.approval_id(flow.approval.read(project))


def _write_pass(project: Path, flow, approval: str, doc: dict) -> dict:
    # A concurrently issued approval may already have its own status. Never replace
    # it with an old pass; the caller rejects this result's old identity as stale.
    return _write(project, doc) if _current_approval(project, flow, approval) else doc


def replan_intent(project: Path) -> dict:
    """The host's durable user request; not itself authority to mutate Flow."""
    try:
        value = json.loads((Path(project) / REPLAN_FILE).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def replan_requested(project: Path, approval: str) -> bool:
    intent = replan_intent(project)
    return bool(approval and intent.get("status") == "queued"
                and intent.get("approval_sha256") == approval)


class _ReplanQueued(Exception):
    pass


def _admit_request(project: Path, approval: str) -> None:
    """Reserve the current request after preparation, atomically with Modify.

    Once admitted, this one request may finish even if Modify arrives next.
    No later request is admitted, and this short lock is never held on the network.
    """
    with INTENT_LOCK:
        if replan_requested(project, approval):
            raise _ReplanQueued


def _rebind_existing(project: Path, flow, item: dict, approval: str) -> dict | None:
    """Explicit host recovery, only after shared evidence proves the same request."""
    found = flow.receipts.find_download(project, item, approval_sha256=approval, recover=True,
                                        source="GeoForge Database catalogue")
    if found is None:
        return None
    doc = found.receipt
    raws, processed = doc["raw_files"], doc.get("processed_files") or []
    if found.files == "extracted_only":
        raw_paths, proc_paths, tool = processed, [], "rebound_extracted_files"
    else:
        raw_paths, proc_paths, tool = raws, processed, doc.get("transform_tool")
    receipt = flow.receipts.record_download(
        project, item_id=str(item["id"]), source=doc["source"],
        request_url=doc.get("request_url") or "", http_status=doc.get("http_status"),
        raw_files=[project / r["path"] for r in raw_paths],
        processed_files=[project / r["path"] for r in proc_paths],
        transform_tool=tool, approval_sha256=approval,
        plan_step_id=item.get("_step"), inventory_item=item,
        units_before=doc.get("units_before"), units_after=doc.get("units_after"),
        requested_at=doc.get("requested_at"), acquisition=doc.get("acquisition"),
        expected_files={"raw_files": raw_paths, "processed_files": proc_paths},
        recovery={"receipt": str(found.path.relative_to(project)),
                  "receipt_signature": doc["signature"]["value"],
                  "reason": found.reason, "original_raw_files": raws,
                  "previous_receipt": doc})
    return {"status": "done", "receipt": str(receipt), "path": str(Path(raw_paths[0]["path"]).parent)}


def _served(project: Path, flow, item: dict, approval: str, client=None) -> dict:
    dataset_id = str(item.get("dataset_id") or item.get("chosen_source") or "")
    existing = _rebind_existing(project, flow, item, approval)
    if existing:
        return existing
    _admit_request(project, approval)
    result = (client or obs_access.Client()).download(dataset_id, project)
    if not result.get("served"):
        # the catalogue says manual after all: hand it over instead of failing
        return {"status": "waiting", "manual": result}
    raw_file = Path(str(result["raw_file"]))
    processed = [Path(str(p)) for p in result.get("files") or []]
    receipt = flow.receipts.record_download(
        project, item_id=str(item["id"]), source="GeoForge Database catalogue",
        request_url=f"{obs_access.BASE_URL}/{urllib.parse.quote(dataset_id, safe='')}/download",
        http_status=200, raw_files=[raw_file],
        processed_files=[p for p in processed if p != raw_file],
        transform_tool="verified_zip_extract" if raw_file.suffix.lower() == ".zip" else None,
        approval_sha256=approval, plan_step_id=item.get("_step"), inventory_item=item)
    return {"status": "done", "receipt": str(receipt), "path": result.get("destination")}


def _manual_destination(project: Path, item: dict) -> Path:
    return obs_access._below_inputs(Path(project), None, str(item.get("dataset_id") or ""))


def _manual_row(project: Path, item: dict, info: dict) -> dict:
    url = str(info.get("baidu_url") or "")
    if not url.lower().startswith(("http://", "https://")):
        url = ""                       # never render a non-http scheme as a link
    return {"item_id": item.get("id"), "dataset_id": item.get("dataset_id"),
            "name": info.get("name") or item.get("dataset_id"),
            "size": info.get("size") or (item.get("catalogue") or {}).get("size"),
            "url": url, "code": info.get("baidu_pwd"),
            "path_in_share": info.get("path_in_share") or info.get("baidu_remote_path"),
            "expected_path": str(info.get("destination") or _manual_destination(project, item))}


def _manual_details(project: Path, approval: str) -> dict:
    """Private recovery cache; links/codes must never enter the acquisition result."""
    try:
        doc = json.loads((Path(project) / MANUAL_DETAILS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("approval_sha256") != approval:
        return {}
    return doc.get("items") if isinstance(doc.get("items"), dict) else {}


def _save_manual_details(project: Path, approval: str, details: dict, item: dict, row: dict) -> None:
    details[str(item["id"])] = row
    obs_access._atomic_json(Path(project) / MANUAL_DETAILS_FILE,
                            {"approval_sha256": approval, "items": details})


def _saved_manual_row(project: Path, item: dict, entry: dict, details: dict) -> dict:
    """Recover only this approved item's allowlisted display fields, never a fresh link."""
    row = details.get(str(item["id"]))
    if not isinstance(row, dict) or row.get("item_id") != item.get("id") \
            or row.get("dataset_id") != item.get("dataset_id"):
        row = {}
    return _manual_row(project, item, {
        "baidu_url": row.get("url"), "baidu_pwd": row.get("code"),
        "name": row.get("name"), "size": row.get("size"),
        "path_in_share": row.get("path_in_share"),
        "destination": entry.get("expected_path") or row.get("expected_path"),
    })


def _placed_receipt(project: Path, flow, item: dict, row: dict, approval: str) -> dict | None:
    """Sign what the user placed. The link and code never enter the receipt."""
    dest = Path(str(row["expected_path"]))
    if not setup_flow.data_path_present(dest):
        return None
    files = sorted(p for p in dest.rglob("*")
                   if p.is_file() and not p.is_symlink() and not p.name.startswith(".")
                   and not p.name.endswith(setup_flow.PARTIAL_SUFFIXES))
    if not files:
        return None
    receipt = flow.receipts.record_download(
        project, item_id=str(item["id"]), source="manual placement (Baidu Pan)",
        request_url="", http_status=None, raw_files=files,
        approval_sha256=approval, plan_step_id=item.get("_step"), inventory_item=item)
    return {"status": "done", "receipt": str(receipt), "path": str(dest)}


def _manual_card(project: Path, rows: list[dict]) -> bool:
    """One request card with N rows; only the user reads the links and codes.

    Returns False when a different card is waiting (never clobber an open question)."""
    from . import projectrun
    pending = setup_flow.request(project)
    if pending and pending.get("status") == "waiting":
        if pending.get("id") != MANUAL_REQUEST_ID:
            return False
        if pending.get("rows") == rows:
            run = projectrun.load(project)
            if (run.get("blocker") or {}).get("id") != MANUAL_REQUEST_ID:
                projectrun.report(Path(project), {"status": "waiting_for_user", "summary": pending.get("title"),
                                                  "blocker": pending}, source="flow")
            return True
    lines = []
    for r in rows:
        lines.append(f"{r['name']} ({obs_access.size_label(r.get('size')) or 'size not reported'}) -> {r['expected_path']}")
        if not r.get("url"):
            lines.append("  Download link is not saved. Send a chat message to refresh the manual download instructions.")
        if r.get("code"):
            lines.append(f"  extraction code: {r['code']}")
        if r.get("path_in_share"):
            lines.append(f"  inside the share, download only: {r['path_in_share']}")
    doc = setup_flow.request_user(project, {
        "kind": "download",
        "title": f"Download {len(rows)} dataset{'s' if len(rows) > 1 else ''} from Baidu Pan",
        "message": "\n".join(lines) + "\n\nPlace each dataset exactly at its path, then click "
                   "\"Files are in place, continue\". GeoForge hashes what you placed and signs a receipt.",
        "url": rows[0].get("url"), "expected_path": rows[0]["expected_path"],
        "resume_hint": "GeoForge verifies the placed files before the run continues.",
        "allow_note": True,
    })
    doc["id"] = MANUAL_REQUEST_ID
    doc["rows"] = rows
    (Path(project) / setup_flow.REQUEST_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    # Project status shows the run's recorded blocker first: make it this card, or the
    # panel keeps showing whatever card came before (the Retry card, on 2026-09-18).
    projectrun.report(Path(project), {"status": "waiting_for_user", "summary": doc["title"], "blocker": doc},
                      source="flow")
    return True


def run(project: Path, *, client=None, automatic_only: bool = False) -> dict:
    """One idempotent pass over every approved input. Safe after a restart.

    Returns {'status': done|pending|waiting|failed, 'items': {id: {...}}}.
    pending = a server clip is still processing; waiting = the user must place files;
    failed = at least one item cannot be acquired (the rest are still attempted).
    Background ticks use automatic_only: they do not treat a file appearing
    during a manual copy as the user's completed handoff.
    """
    project = Path(project).resolve()
    flow = _flow()
    if flow.approval.check(project) != "OK":
        raise ValueError("acquisition needs an approved plan")
    plan, inventory = flow.plan.read_artifacts(project)
    if errors := obs_access.delivery_preference_errors(inventory):
        raise ValueError("; ".join(errors))
    default_preference = obs_access.delivery_preference(inventory)
    approval = flow.approval.approval_id(flow.approval.read(project))
    doc = status(project)
    wanted = needed(plan, inventory, project)
    for item in wanted:
        if (obs_access.delivery_preference(item, default=default_preference) == "manual"
                and item.get("delivery") != "manual"):
            raise ValueError(f"item {item.get('id')!r}: manual delivery is unavailable for the selected delivery")
    keep = {str(i["id"]) for i in wanted}
    # A new approval or a replan that dropped/renamed an item must not inherit its old verdict.
    old_items = doc.get("items") or {} if doc.get("approval_sha256") == approval else {}
    items = {k: v for k, v in old_items.items() if k in keep}
    details = {k: v for k, v in _manual_details(project, approval).items() if k in keep}
    doc.update(approval_sha256=approval, status="running", items=items)
    manual_rows = []
    for item in wanted:
        # A user may queue a plan change while the current transfer is in flight.
        # Its valid receipt is retained, but no later input/job is started.
        if replan_requested(project, approval):
            doc["status"] = "pending"
            return _write_pass(project, flow, approval, doc)
        iid = str(item["id"])
        entry = items.get(iid) or {}
        entry.update(delivery=item.get("delivery"), dataset_id=item.get("dataset_id"))
        found = flow.receipts.find_download(project, item, approval_sha256=approval)
        if found:
            entry.update(status="done", receipt=str(found.path), error=None)
            items[iid] = entry
            continue
        if automatic_only and (item.get("delivery") == "manual" or entry.get("status") == "waiting"):
            # A tick never signs a manual file, not even a replacement for one the user
            # handed off: without an intact receipt it waits, with its card, for a new handoff.
            entry.update(status="waiting", expected_path=entry.get("expected_path") or
                         str(_manual_destination(project, item)))
            card = setup_flow.request(project)
            if not (card and card.get("status") == "waiting" and card.get("id") == MANUAL_REQUEST_ID):
                manual_rows.append((item, _saved_manual_row(project, item, entry, details)))
            items[iid] = entry
            continue
        try:
            if item.get("delivery") == "subset" and item.get("acquisition_id"):
                _admit_request(project, approval)
                info = obs_subset.advance_approved(project, item["acquisition_id"], client=client)
                if info.get("receipt"):
                    entry.update(status="done", receipt=info["receipt"], path=info.get("path"), error=None)
                elif info.get("status") in {"queued", "running", "ready", "downloading"}:
                    entry.update(status="pending", job_status=info.get("status"), error=None)
                else:
                    entry.update(status="failed", error=f"clip job {info.get('status')}")
            elif item.get("delivery") == "served":
                try:
                    out = _served(project, flow, item, approval, client=client)
                except obs_access.ObsAccessError as error:
                    if error.code != "destination_not_empty":
                        raise
                    raise ValueError(
                        f"{_manual_destination(project, item)} already holds files with no receipt "
                        "proving intact data for this exact approved request. The request may have "
                        "changed, evidence may be missing, or files may have changed. Existing files "
                        "were not overwritten. Move them away and Retry, or Modify the plan to use "
                        "them as a local input and validate them.") from None
                if out["status"] == "waiting":
                    row = _manual_row(project, item, out["manual"])
                    _save_manual_details(project, approval, details, item, row)
                    manual_rows.append((item, row))
                    entry.update(status="waiting", expected_path=row["expected_path"], error=None)
                else:
                    entry.update(status="done", receipt=out["receipt"], path=out.get("path"), error=None)
            elif item.get("delivery") == "manual":
                # Placed files first, so the server is only asked for a link while nothing is there.
                row = _manual_row(project, item, {})
                placed = _placed_receipt(project, flow, item, row, approval)
                if placed:
                    entry.update(status="done", receipt=placed["receipt"], path=placed["path"], error=None)
                else:
                    _admit_request(project, approval)
                    options = ({"manual_only": True}
                               if obs_access.delivery_preference(item, default=default_preference) == "manual"
                               else {})
                    info = (client or obs_access.Client()).download(str(item.get("dataset_id") or ""), project,
                                                                  **options)
                    row = _manual_row(project, item, info)
                    _save_manual_details(project, approval, details, item, row)
                    manual_rows.append((item, row))
                    entry.update(status="waiting", expected_path=row["expected_path"], error=None)
        except _ReplanQueued:
            doc["status"] = "pending"
            return _write_pass(project, flow, approval, doc)
        except (obs_access.ObsAccessError, OSError, ValueError, KeyError) as error:
            entry.update(status="failed", error=str(error))
        items[iid] = entry
    if replan_requested(project, approval):
        doc["status"] = "pending"
        return _write_pass(project, flow, approval, doc)
    states = {e.get("status") for e in items.values()}
    if "failed" in states:
        overall = "failed"
    elif "waiting" in states:
        overall = "waiting"
    elif "pending" in states:
        overall = "pending"
    else:
        overall = "done"
    doc["status"] = overall
    if not _current_approval(project, flow, approval):
        return doc  # no stale card, activity summary or status write for another plan
    if manual_rows:
        # Several plan items may pin one dataset: one download, one row.
        unique, seen = [], set()
        for _item, row in manual_rows:
            if row["expected_path"] in seen:
                continue
            seen.add(row["expected_path"]); unique.append(row)
        if not _manual_card(project, unique):
            doc["note"] = "another request is open; the download card is shown once it is answered"
    elif overall != "waiting":
        pending = setup_flow.request(project)
        if pending and pending.get("id") == MANUAL_REQUEST_ID:
            setup_flow.clear_request(project)
            from . import projectrun
            projectrun.report(project, {"status": "working", "summary": "Approved data received"},
                              source="flow")
    return _write_pass(project, flow, approval, doc)
