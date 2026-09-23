"""flow.decisions — the ONE schema for a recorded decision, and the rules over it.

Design B (owner, 2026-09-15): a driver never reads prose. For every input the plan asked about,
exactly one structured record is kept:

    {"input_id": "<inventory item or choice id>", "source": "user" | "ki_default" | "open",
     "value": <the decision>, "rationale"?: str, "user_quote"?: str}

    source user       - the user decided it (value + rationale/quote kept)
    source ki_default - the KI protocol decides it; the user is TOLD, it is never their choice
    source open       - still needed from the user; an open input must never execute

This module owns the schema (validate_record), the fold (the last valid record per input wins,
`decision_superseded` retires one) and the revision hash the signed plan carries
(`decision_revision`). STORAGE stays with the driver: the web keeps records as `research_events`
rows (backend/services/flow_decisions.py), the desktop derives them from the approval card and
the plan's own inventory. Ported verbatim from the web implementation deployed 2026-09-15 so
both drivers apply one schema and one supersession rule.
"""
from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

SOURCES = ("user", "ki_default", "open")
SCOPE_IDS = ("site", "period")



def is_input_record(payload: dict) -> bool:
    return isinstance(payload, dict) and bool(str(payload.get("input_id") or "").strip())



def validate_record(payload: dict) -> tuple[bool, str]:
    """The ONE schema. (ok, why). Trims nothing silently: a source with stray spaces is invalid."""
    if not isinstance(payload, dict):
        return False, "payload must be an object"
    iid = payload.get("input_id")
    if not isinstance(iid, str) or not iid.strip() or iid != iid.strip():
        return False, "input_id must be a non-empty string without surrounding spaces"
    src = payload.get("source")
    if not isinstance(src, str) or src not in SOURCES:
        return False, f"source must be exactly one of {'|'.join(SOURCES)} (got {src!r})"
    val = payload.get("value")
    if val is None:
        return False, "value is required"
    if isinstance(val, str) and not val.strip():
        return False, "value is empty"
    if isinstance(val, (dict, list)) and not val:
        return False, "value is an empty container"
    key = iid.strip().lower()
    if key in SCOPE_IDS and src != "open":
        if not isinstance(val, dict):
            return False, f"{key}: value must be an object"
        if key == "site":
            lat, lon = val.get("lat"), val.get("lon")
            has_pt = lat is not None and lon is not None
            if has_pt:
                try:
                    lat, lon = float(lat), float(lon)
                except (TypeError, ValueError):
                    return False, "site: lat/lon must be numbers"
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return False, "site: lat/lon out of range"
            if not has_pt and not str(val.get("location_name") or "").strip():
                return False, "site: needs location_name or lat+lon"
        else:
            try:
                y0, y1 = int(val.get("start_year")), int(val.get("end_year"))
            except (TypeError, ValueError):
                return False, "period: start_year and end_year must be integers"
            if not (1900 <= y0 <= 2100 and 1900 <= y1 <= 2100) or y0 > y1:
                return False, "period: start_year must be <= end_year, both plausible years"
    return True, "ok"


# ─── effective records ───────────────────────────────────────────────────────────────────────
class RecordsUnavailable(RuntimeError):
    """The decision history could not be read — never sign or execute against it."""



def fold_rows(rows) -> dict[str, dict]:
    """PURE fold of (id, event_type, payload) rows -> {input_id(lower): effective record}.
    Shared by the server and the gate hook (the hook loads this file by path) so both sides apply
    the SAME schema and the SAME supersession rules (codex round-4 #7/#9):
      * the last VALID record per input wins; a malformed row is skipped (logged) and never blocks
        a later valid record for the same input;
      * `decision_superseded {supersedes_event_id}` retires ONLY that event: if a newer record for
        the same input is already effective, it stays;
      * `decision_superseded {input_id}` retires whatever is effective for that input."""
    eff: dict[str, dict] = {}
    by_event: dict[int, str] = {}
    for eid, et, p in rows:
        try:
            d = json.loads(p) if isinstance(p, str) else (p or {})
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if et == "decision_superseded":
            sev = d.get("supersedes_event_id")
            try:
                sev = int(sev) if sev is not None else None
            except (TypeError, ValueError):
                sev = None
            if sev is not None:
                key = by_event.get(sev)
                if key and eff.get(key, {}).get("event_id") == sev:
                    eff.pop(key, None)
            elif str(d.get("input_id") or "").strip():
                eff.pop(str(d["input_id"]).strip().lower(), None)
            continue
        if not is_input_record(d):
            continue
        ok, why = validate_record(d)
        if not ok:
            logger.warning("skipping malformed decision record %s: %s", eid, why)
            continue
        key = str(d["input_id"]).strip().lower()
        rec = {"input_id": d["input_id"], "source": d["source"], "value": d.get("value"),
               "rationale": d.get("rationale"), "user_quote": d.get("user_quote"),
               "user_message_id": d.get("user_message_id"), "event_id": eid,
               "text": str(d.get("decision") or f"INPUT {d['input_id']}")}
        eff[key] = rec
        by_event[eid] = key
    return eff



def revision_of(records: dict[str, dict]) -> str:
    slim = {k: {"source": v["source"], "value": v.get("value")} for k, v in sorted(records.items())}
    return hashlib.sha256(json.dumps(slim, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()[:16]


def fold_payloads(payloads) -> dict[str, dict]:
    """`fold_rows` for a driver with no event ids (the desktop): records in order, last wins."""
    return fold_rows([(i, "decision_pinned", p) for i, p in enumerate(payloads or [], 1)])


def open_inputs(records: dict) -> list:
    """The input ids still waiting on the user - approval must refuse while any remain."""
    return sorted(str(r.get("input_id") or k)
                  for k, r in (records or {}).items() if r.get("source") == "open")
