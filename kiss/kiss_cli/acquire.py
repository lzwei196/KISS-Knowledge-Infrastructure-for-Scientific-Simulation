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
import time
import urllib.parse
from pathlib import Path

from . import obs_access, obs_subset, setup as setup_flow

STATUS_FILE = Path(".geoforge/acquisition.json")
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


def _receipt_for(project: Path, flow, item: dict, approval: str, inventory: dict) -> str | None:
    for path, doc, ok in flow.receipts._read_all(project, flow.receipts.DATA_SUB):
        if (ok and doc.get("item_id") == item.get("id") and doc.get("approval_sha256") == approval
                and flow.receipts._download_files_valid(project, doc)
                and flow.receipts._download_still_valid(project, doc, inventory)):
            return str(path)
    for path, doc, ok in flow.receipts._read_all(project, flow.receipts.DATA_SUB):
        # a download from an earlier approval stays valid while the selection is unchanged
        if ok and doc.get("item_id") == item.get("id") and flow.receipts._download_still_valid(project, doc, inventory):
            return str(path)
    return None


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


def _rebind_existing(project: Path, flow, item: dict, dataset_id: str, approval: str) -> dict | None:
    """Files of this dataset already verified under an earlier approval or item id
    (a replan renamed the item): sign them again for the current plan, no re-download."""
    marker = f"/{obs_access._safe_component(dataset_id)}/"
    for _path, doc, ok in flow.receipts._read_all(project, flow.receipts.DATA_SUB):
        if not ok or doc.get("kind") != "download" or doc.get("source") != "GeoForge Database catalogue":
            continue
        raws = [r.get("path") or "" for r in doc.get("raw_files") or []]
        if not raws or not all(marker in f"/{r}" for r in raws):
            continue
        processed = [p.get("path") or "" for p in doc.get("processed_files") or []]
        if flow.receipts._download_files_valid(project, doc):
            raw_paths, proc_paths, tool = raws, processed, doc.get("transform_tool")
        elif processed and _entries_valid(project, flow, doc.get("processed_files") or []):
            # The transport archive is gone but every extracted file still matches its
            # recorded hash: the extracted files become the raw evidence of this receipt.
            raw_paths, proc_paths, tool = processed, [], "rebound_extracted_files"
        else:
            continue
        receipt = flow.receipts.record_download(
            project, item_id=str(item["id"]), source="GeoForge Database catalogue",
            request_url=doc.get("request_url") or "", http_status=doc.get("http_status"),
            raw_files=[project / r for r in raw_paths],
            processed_files=[project / r for r in proc_paths],
            transform_tool=tool, approval_sha256=approval,
            plan_step_id=item.get("_step"), inventory_item=item)
        return {"status": "done", "receipt": str(receipt), "path": str(Path(raw_paths[0]).parent)}
    return None


def _entries_valid(project: Path, flow, entries: list) -> bool:
    for entry in entries:
        path = Path(project) / str(entry.get("path") or "")
        try:
            if not path.is_file() or flow.receipts.sha256_file(path) != str(entry.get("sha256") or ""):
                return False
        except OSError:
            return False
    return True


def _served(project: Path, flow, item: dict, approval: str, client=None) -> dict:
    dataset_id = str(item.get("dataset_id") or item.get("chosen_source") or "")
    existing = _rebind_existing(project, flow, item, dataset_id, approval)
    if existing:
        return existing
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
            "path_in_share": info.get("path_in_share"),
            "expected_path": str(info.get("destination") or _manual_destination(project, item))}


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


def run(project: Path, *, client=None) -> dict:
    """One idempotent pass over every approved input. Safe after a restart.

    Returns {'status': done|pending|waiting|failed, 'items': {id: {...}}}.
    pending = a server clip is still processing; waiting = the user must place files;
    failed = at least one item cannot be acquired (the rest are still attempted).
    """
    project = Path(project).resolve()
    flow = _flow()
    if flow.approval.check(project) != "OK":
        raise ValueError("acquisition needs an approved plan")
    plan, inventory = flow.plan.read_artifacts(project)
    approval = flow.approval.approval_id(flow.approval.read(project))
    doc = status(project)
    wanted = needed(plan, inventory, project)
    keep = {str(i["id"]) for i in wanted}
    # A new approval or a replan that dropped/renamed an item must not inherit its old verdict.
    old_items = doc.get("items") or {} if doc.get("approval_sha256") == approval else {}
    items = {k: v for k, v in old_items.items() if k in keep}
    doc.update(approval_sha256=approval, status="running", items=items)
    manual_rows = []
    for item in wanted:
        iid = str(item["id"])
        entry = items.get(iid) or {}
        entry.update(delivery=item.get("delivery"), dataset_id=item.get("dataset_id"))
        receipt = _receipt_for(project, flow, item, approval, inventory)
        if receipt:
            entry.update(status="done", receipt=receipt, error=None)
            items[iid] = entry
            continue
        try:
            if item.get("delivery") == "subset" and item.get("acquisition_id"):
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
                        f"{_manual_destination(project, item)} already holds files that carry no receipt "
                        "(a download that was never recorded, or files copied in by hand). Move them "
                        "away and Retry, or Modify the plan to use them as a local input.") from None
                if out["status"] == "waiting":
                    row = _manual_row(project, item, out["manual"])
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
                    info = (client or obs_access.Client()).download(str(item.get("dataset_id") or ""), project)
                    row = _manual_row(project, item, info)
                    manual_rows.append((item, row))
                    entry.update(status="waiting", expected_path=row["expected_path"], error=None)
        except (obs_access.ObsAccessError, OSError, ValueError, KeyError) as error:
            entry.update(status="failed", error=str(error))
        items[iid] = entry
    states = {e.get("status") for e in items.values()}
    if "failed" in states:
        overall = "failed"
    elif "waiting" in states:
        overall = "waiting"
    elif "pending" in states:
        overall = "pending"
    else:
        overall = "done"
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
    doc["status"] = overall
    return _write(project, doc)
