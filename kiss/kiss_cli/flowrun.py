"""flowrun — one chat turn under the flow: resolve → plan → approve → execute → verify.

This is the desktop's driver for ``ki_tools_common.flow`` (plan v3 PART B, B1). gui.py
calls three functions and otherwise stays as it was:

  pre(...)    before the agent starts — handle the user's approval click, resolve which
              KIs the task involves (text + ticks), ask instead of guessing, move the
              state, and decide whether an agent turn is needed at all;
  turn(...)   inside _chat_with_models — open the FlowSession against the live KI roots,
              derive the draft plan (the app does this, not the agent), and return the
              prompt piece + tool policy + session rule for this state;
  after(...)  when the agent's turn ends — validate the plan files, show the approval
              card (auto-approve when nothing needs the user), or check receipts and
              move to COMPLETED / FAILED_VALIDATION.

The approval card reuses the desktop's existing "needs you" request (setup.request_user)
with two options: approve / modify. The user's click comes back as ``req["action"]`` on
the next turn, exactly like every other request.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import flowgate, projectrun, setup as setup_flow

APPROVAL_REQUEST_ID_PREFIX = "flow-approve-"
REPLAN_MARKER = "REPLAN_REQUIRED"
INTAKE_MARKER = "GEOFORGE_INTAKE"
_INTAKE_PATTERN = re.compile(
    r"<!--\s*" + INTAKE_MARKER + r"\s*(\{.*?\})\s*-->", re.S)

_DATABASE_HELPER = r'''#!/usr/bin/env python3
"""Process-local GeoForge Database search adapter.

The real activation token stays in GeoForge Desktop.  This helper receives a
short-lived loopback capability in its child environment and becomes useless
as soon as that Desktop process exits.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description="Search GeoForge Database")
    parser.add_argument("keywords", nargs="?", default="")
    parser.add_argument("--query", dest="query", default="")
    parser.add_argument("--bbox", default="", help="min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--start", default="", help="YYYY-MM-DD")
    parser.add_argument("--end", default="", help="YYYY-MM-DD")
    parser.add_argument("--variable", default="")
    parser.add_argument("--describe", dest="describe_dataset_id", default="", help="Read the actual source schema before selecting subset variables")
    parser.add_argument("--resolve", dest="resolve_dataset_id", default="")
    parser.add_argument("--subset", default="", help="Estimate native-grid server clipping for this dataset; no job is created")
    parser.add_argument("--time-step", default="", choices=["", "daily", "3hr"])
    parser.add_argument("--category", default="")
    parser.add_argument("--delivery", default="", choices=["", "served", "manual"])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    endpoint = os.environ.get("GEOFORGE_AGENT_DATABASE_URL", "").strip()
    capability = os.environ.get("GEOFORGE_AGENT_DATABASE_TOKEN", "").strip()
    if not endpoint or not capability:
        print("GeoForge Database is not available in this agent session. Start the search from GeoForge Desktop.", file=sys.stderr)
        return 3
    params = urllib.parse.urlencode({
        "q": args.query or args.keywords,
        "bbox": args.bbox, "start": args.start, "end": args.end,
        "variable": args.variable, "category": args.category, "delivery": args.delivery,
        "describe_dataset_id": args.describe_dataset_id,
        "resolve_dataset_id": args.resolve_dataset_id, "time_step": args.time_step,
        "subset_dataset_id": args.subset, "cwd": os.getcwd() if args.subset else "",
        "offset": max(0, args.offset),
        "limit": max(1, min(args.limit, 100)),
    })
    request = urllib.request.Request(
        endpoint + ("&" if "?" in endpoint else "?") + params,
        headers={"X-GeoForge-Agent-Token": capability, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8", "replace")).get("message")
        except Exception:
            detail = None
        print("GeoForge Database search failed: " + (detail or f"HTTP {error.code}"), file=sys.stderr)
        return 3
    except Exception as error:
        print(f"GeoForge Database search failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_FLOW_HELPER = r'''#!/usr/bin/env python3
"""Forward one gated flow command to the owning GeoForge Desktop process."""
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    endpoint = os.environ.get("GEOFORGE_AGENT_FLOW_URL", "").strip()
    capability = os.environ.get("GEOFORGE_AGENT_DATABASE_TOKEN", "").strip()
    if not endpoint or not capability:
        print("GeoForge flow command is unavailable outside its Desktop agent session.", file=sys.stderr)
        return 3
    body = json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"X-GeoForge-Agent-Token": capability, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=None) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8", "replace")).get("message")
        except Exception:
            detail = None
        print(detail or f"GeoForge flow command failed: HTTP {error.code}", file=sys.stderr)
        return 3
    except Exception as error:
        print(f"GeoForge flow command failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    if result.get("stdout"):
        print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
    if result.get("stderr"):
        print(result["stderr"], end="" if result["stderr"].endswith("\n") else "\n", file=sys.stderr)
    return int(result.get("returncode", 1))


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def catalogue_entries(catalog) -> list[dict]:
    return [{"id": ki.name, "name": ki.name, "ki_path": str(ki.root)} for ki in catalog]


def _flow():
    return flowgate.load()


_SERVER_STRATEGIES = ("from_forcing_provider", "from_dataset_lookup")
_CATALOGUE_HINT = "GeoForge Database: search by variable, place and period, then pin dataset_id"


def _localize_draft(plan: dict, inventory: dict) -> None:
    """Strip server-era data sources from a desktop draft.

    The bundled planner cards still name the server's forcing providers
    (``cmfd_v1``, ``mswx_v1`` …) and dataset lookups, none of which exist on a
    desktop.  Those items become honest gaps the Agent fills from the GeoForge
    Database, and the provider-id choice disappears from the approval card.
    """
    for item in inventory.get("items") or []:
        if not isinstance(item, dict) or item.get("strategy") not in _SERVER_STRATEGIES:
            continue
        item.update({"status": "missing", "chosen_source": None,
                     "acceptable_sources": [_CATALOGUE_HINT],
                     "needs_user": False, "agent_resolvable": True,
                     "rationale": "desktop: no local data service; pick an exact GeoForge "
                                  "Database dataset_id during planning"})
    plan["scientific_choices"] = [
        c for c in plan.get("scientific_choices") or []
        if not (isinstance(c, dict) and c.get("kind") == "forcing_source")]


def _data_roots(flow, repo_root: Path | None):
    """Bundled planner data (flow/data) if present, else the server's ata-kdt tree."""
    import ki_tools_common.flow as _pkg
    bundled = Path(_pkg.__file__).resolve().parent / "data"
    if (bundled / "cards").is_dir():
        return flow.plan.DataRoots.bundled(bundled)
    return flow.plan.DataRoots.server()


def _explicit_positive_model_mention(text: str, model: str) -> bool:
    """True when *model* is actually named in prose and is not locally negated.

    Catalogue resolution deliberately has fuzzy aliases, which is useful in Auto-KI
    mode but unsafe for expanding a pinned selection: ``grid cell`` has matched
    Cell2Fire, and ``do not invoke CaMa-Flood`` still contains a literal model name.
    """
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", model) if p]
    if not parts:
        return False
    aliases = [r"[\s_-]*".join(map(re.escape, parts))]
    # Coupling shorthand commonly uses the distinctive first component (VIC-CaMa).
    if len(parts) > 1 and len(parts[0]) >= 4:
        aliases.append(re.escape(parts[0]))
    negation = re.compile(
        r"(?:do\s+not|don't|without|exclude|excluding|not\s+using|no|"
        r"不要|不使用|不用|不调用|禁止|排除)[^.;,，。]{0,32}$", re.I)
    for alias in aliases:
        for match in re.finditer(r"(?<![A-Za-z0-9])" + alias + r"(?![A-Za-z0-9])",
                                 text, re.I):
            if not negation.search(text[max(0, match.start() - 48):match.start()]):
                return True
    return False


def current_state(project: Path) -> str:
    """The flow state name on disk, or '' when the project has no flow yet."""
    try:
        return _flow().states.FlowContext.load(Path(project)).state.value
    except Exception:  # noqa: BLE001 — no flow, unreadable state: not a flow project
        return ""


def replan_reason_from(reply: str) -> str:
    """The agent's own words after the REPLAN_REQUIRED marker, for the re-planning turn."""
    match = re.search(REPLAN_MARKER + r"\s*[:：]?\s*([^\n]{1,400})", reply or "")
    return match.group(1).strip() if match else ""


def display_stage(flow, state) -> str:
    return flow.states.DISPLAY_STAGE.get(state, "preparing")


# ---------------------------------------------------------------------------
# pre: resolution + approval handling
# ---------------------------------------------------------------------------

@dataclass
class Pre:
    names: list[str]                       # KI names for this turn (may include added partners)
    message: str | None = None             # reply INSTEAD of an agent turn (question / refusal)
    gated: bool = True                     # False = ordinary chat, no flow
    replan_reason: str = ""


def pre(project: Path, text: str, names: list[str], catalog, action: dict | None,
        pending: dict | None, note: str = "", couplings_dir: Path | None = None,
        setup_ok: bool = True) -> Pre:
    flow = _flow()
    ctx = flow.states.FlowContext.load(project)
    S = flow.states.State

    # 1. the user's answer to the approval card
    if pending and str(pending.get("id", "")).startswith(APPROVAL_REQUEST_ID_PREFIX) and action \
            and str(action.get("request_id")) == str(pending.get("id")):
        choice = str(action.get("option_id") or "")
        if choice == "approve":
            pj, inv = flow.plan.read_artifacts(project)
            review = pending.get("review") or {}
            if (pj is None or inv is None or review.get("plan_sha256") != flow.plan.sha256(pj)
                    or review.get("inventory_sha256") != flow.plan.sha256(inv)):
                setup_flow.clear_request(project)
                ctx.move("modify")
                return Pre(names=list(ctx.selected_kis or names),
                           replan_reason="The plan or inventory changed after review. Review this revision before approval.")
        setup_flow.clear_request(project)
        if choice == "approve":
            from . import obs_subset, obs_access
            pj, inv = flow.plan.read_artifacts(project)
            picks = action.get("choices") if isinstance(action.get("choices"), dict) else {}
            repinned = apply_data_choices(pj, inv, picks) if picks else []
            if repinned:
                # The user chose different data on the card: re-pin, re-stamp (incl. the
                # host's clip check), rewrite the plan files and show the card again unsigned.
                errs = obs_access.stamp_inventory(inv, project=project)
                flow.plan.write_artifacts(project, pj, inv)
                chosen = set(ctx.selected_kis or names)
                roots = {k.name: Path(k.root) for k in catalog if k.name in chosen}
                fs = flowgate.FlowSession.open(project, roots, database_access_mode="direct")
                note_text = str(((pending or {}).get("plan_review") or {}).get("tool_policy") or "")
                _issue_card(project, fs, pj, inv, note_text,
                            extra_why=(["data re-pinned to your choice: " + ", ".join(repinned)] + errs))
                return Pre(names=list(ctx.selected_kis or names),
                           message="Data re-pinned to your choice: " + ", ".join(repinned)
                                   + ". The updated card is in the chat; approve it to start.")
            if picks:
                for c in pj.get("scientific_choices") or []:
                    if isinstance(c, dict) and c.get("kind") == "data_source" and picks.get(str(c.get("id"))):
                        c["decision"] = picks[str(c.get("id"))]
                flow.plan.write_artifacts(project, pj, inv)
                pj, inv = flow.plan.read_artifacts(project)
            # Fresh numbers for every server clip before anything is signed. If a
            # clip grew or its source changed, the card comes back unsigned.
            changed = obs_subset.refresh_inventory(project, inv)
            stamp_errors = obs_access.stamp_inventory(inv, project=project) if changed else []
            for err in stamp_errors:
                changed.setdefault("inventory", []).append(err)
            if changed:
                flow.plan.write_artifacts(project, pj, inv)
                chosen = set(ctx.selected_kis or names)
                roots = {k.name: Path(k.root) for k in catalog if k.name in chosen}
                fs = flowgate.FlowSession.open(project, roots, database_access_mode="direct")
                why = [f"{item}: {'; '.join(reasons)}" for item, reasons in changed.items()]
                note_text = str(((pending or {}).get("plan_review") or {}).get("tool_policy") or "")
                _issue_card(project, fs, pj, inv, note_text,
                            extra_why=["clip estimates changed since you reviewed: "] + why)
                return Pre(names=list(ctx.selected_kis or names),
                           message="The server clip estimates changed since you reviewed the plan: "
                                   + "; ".join(why) + ". The updated card is in the chat; approve again if it still fits.")
            # Who decided what. An input still waiting on the user never starts a run
            # (the web chat's rule since 2026-09-15), and the user is told which inputs the
            # KI's own protocol decided. `user` comes ONLY from the host-written answer store.
            if apply_choice_picks(pj, picks):
                flow.plan.write_artifacts(project, pj, inv)
                pj, inv = flow.plan.read_artifacts(project)
            answers = record_user_answers(project, pending, picks)
            records, invalid = decision_records(flow, pj, inv, answers)
            blocking = [display_input_id(i) for i in flow.decisions.open_inputs(records)] + invalid
            if blocking:
                chosen = set(ctx.selected_kis or names)
                roots = {k.name: Path(k.root) for k in catalog if k.name in chosen}
                fs = flowgate.FlowSession.open(project, roots, database_access_mode="direct")
                note_text = str(((pending or {}).get("plan_review") or {}).get("tool_policy") or "")
                _issue_card(project, fs, pj, inv, note_text,
                            extra_why=["still waiting on your decision: " + ", ".join(blocking[:8])])
                # Only the data sources have a control on the card; everything else is answered
                # by sending the plan back — never tell the user a note will clear it (kimi #2).
                return Pre(names=list(ctx.selected_kis or names),
                           message="These still need your decision before anything runs: "
                                   + ", ".join(blocking[:8])
                                   + ". Pick a data source on the card where one is offered; for "
                                     "anything else choose \u201cModify the plan\u201d and say what to use.")
            revision = flow.decisions.revision_of(records)
            if pj.get("decision_revision") != revision:
                pj["decision_revision"] = revision          # inside the hash the approval signs
                flow.plan.write_artifacts(project, pj, inv)
                pj, inv = flow.plan.read_artifacts(project)
            verdict = flow.approval.check(project)
            if verdict != "OK":
                # (re)approve the CURRENT plan files by the user's click
                decided = dict(records)
                if note:
                    decided["note"] = {"input_id": "note", "source": "user", "value": note}
                flow.approval.approve(project, decided, by="user")
            # Approving the plan approves its data: start the server clips now.
            # A creation that fails here is retried by the execution turn.
            for r in obs_subset.approve_inventory(project, inv):
                if not r["ok"]:
                    projectrun.report(project, {"status": "needs_attention",
                                                "summary": f"clip job for {r['item']} not started: {r['error']}"},
                                      source="flow")
            try:
                obs_subset.bind_approved(project)
            except (ValueError, OSError, KeyError):
                obs_access._atomic_json(Path(project) / '.geoforge/data-binding-status.json', {
                    'status': 'needs_review',
                    'message': 'Data binding failed: check the selected acquisition scope and intact file evidence. '
                               'Approval was saved, but dependent steps remain blocked.'})
            ctx.move("approved", {"approval": flow.approval.check(project)})
            result = _start_execution(flow, ctx, project, setup_ok)
            if ctx.state in (S.ACQUIRING, S.BLOCKED):
                # the host is still fetching data (or hit a wall): no agent turn yet
                return Pre(names=list(ctx.selected_kis or names), message=_acquisition_message(result))
            return Pre(names=list(ctx.selected_kis or names), message=None)
        # modify → back to planning with the note as the reason
        ctx.move("modify")
        projectrun.set_stage(project, display_stage(flow, ctx.state), "Revising the plan")
        return Pre(names=list(ctx.selected_kis or names), replan_reason=note or "user asked for changes")

    # 1b. the acquisition-blocked card: retry the missing data or go back to planning
    if pending and str(pending.get("id")) == BLOCKED_REQUEST_ID and action \
            and str(action.get("request_id")) == str(pending.get("id")):
        setup_flow.clear_request(project)
        if str(action.get("option_id")) == "retry":
            ctx.move("retry_acquire", {"approval": flow.approval.check(project)})
            result = acquire_then_continue(flow, ctx, project, setup_ok)
            return Pre(names=list(ctx.selected_kis or names),
                       message=None if result["status"] == "done" else _acquisition_message(result))
        flow.approval.revoke(project, "user asked to modify the plan after a data failure")
        ctx.move("unblocked")
        return Pre(names=list(ctx.selected_kis or names), replan_reason=note or "user asked for changes after a data failure")

    # 1c. while the host is acquiring data, a message (or "files are in place") re-runs the pass
    if ctx.state is S.BLOCKED:
        from . import acquire
        current = setup_flow.request(project)
        if not (current and current.get("status") == "waiting" and current.get("id") == BLOCKED_REQUEST_ID):
            _acquisition_card(project, acquire.status(project))      # the card was dismissed: show it again
        return Pre(names=list(ctx.selected_kis or names), message=_acquisition_message(acquire.status(project)))
    if ctx.state is S.ACQUIRING:
        from . import acquire
        if action and str(action.get("request_id")) == acquire.MANUAL_REQUEST_ID \
                and str(action.get("option_id")) == "modify":
            # the manual-download card's "change the plan": drop the approval, replan now
            setup_flow.clear_request(project)
            flow.approval.revoke(project, "user asked to modify the plan while data was pending")
            ctx.move("modify")
            projectrun.set_stage(project, display_stage(flow, ctx.state), "Revising the plan")
            return Pre(names=list(ctx.selected_kis or names), replan_reason=note or text or "user asked for changes")
        result = acquire_then_continue(flow, ctx, project, setup_ok)
        if result["status"] == "done":
            return Pre(names=list(ctx.selected_kis or names), message=None)
        return Pre(names=list(ctx.selected_kis or names), message=_acquisition_message(result))

    # 1d. continuing after a failed run: rerun under the same approval (through ACQUIRING)
    if ctx.state in (S.FAILED, S.FAILED_VALIDATION) and flow.approval.check(project) == "OK":
        ctx.move("rerun", {"approval": "OK"})
        result = _start_execution(flow, ctx, project, setup_ok)
        if ctx.state in (S.ACQUIRING, S.BLOCKED):
            return Pre(names=list(ctx.selected_kis or names), message=_acquisition_message(result))
        return Pre(names=list(ctx.selected_kis or names))

    # 2. ordinary chat stays ungated until a scientific task starts a flow — with or
    #    without a pinned KI ("thanks" in a VIC chat is not a run request)
    if ctx.state is S.NEW and not flow.resolve.is_scientific_task(text):
        return Pre(names=list(names), gated=False)

    # 3. resolve which KIs the task involves — never guess
    cat = catalogue_entries(catalog)
    pairs = flow.resolve.coupling_pairs(couplings_dir) if couplings_dir else None
    res = flow.resolve.resolve_kis(text, list(ctx.selected_kis or names), cat, couplings=pairs)
    if ctx.state in (S.NEW,):
        ctx.move("task_received")
    if ctx.state is S.RESOLVING_KIS:
        # A free-language first message belongs to the task-understanding Agent, not to a
        # collection of host regexes.  Known-name matches are useful hints, but are not a
        # semantic decision and must not produce host-authored clarification questions.
        # A non-empty ``names`` list is different: the user explicitly pinned a KI in the UI.
        # Once the user explicitly pins a KI, unrelated uppercase terms in the
        # scientific request (NASA POWER, API, DEM, CMFD, etc.) are data/tool
        # vocabulary, not evidence that a second unknown model was requested.
        # A pinned selection is authoritative by default.  Do not fuzzily expand it
        # from prose: a
        # task may mention another model in a comparison or a negation ("do not
        # invoke CaMa-Flood"), and ordinary terms such as "grid cell" can also
        # collide with catalogue aliases (for example Cell2Fire).  Coupled runs
        # must therefore be pinned as a multi-KI selection by the UI/intake.
        if not names:
            ctx.save()
            projectrun.set_stage(project, display_stage(flow, ctx.state),
                                 "Understanding the task and choosing the KI")
            return Pre(names=[], message=None)
        selected = list(dict.fromkeys(names))
        selected.extend(k for k in res.resolved if k not in selected
                        and _explicit_positive_model_mention(text, k))
        ctx.selected_kis = selected
        ctx.move("kis_resolved", {"selected_kis": ctx.selected_kis})
        projectrun.select_kis(project, ctx.selected_kis)
        projectrun.set_stage(project, display_stage(flow, ctx.state), "Planning the run")
        return Pre(names=list(ctx.selected_kis))
    if ctx.state is S.WAITING_FOR_USER and (res.resolved and not res.ambiguous and not res.unknown):
        # the user answered the "which model?" question
        ctx.selected_kis = list(res.resolved)
        ctx.move("kis_resolved", {"selected_kis": ctx.selected_kis})
        projectrun.select_kis(project, ctx.selected_kis)
        return Pre(names=list(ctx.selected_kis))
    ctx.save()
    return Pre(names=list(ctx.selected_kis or res.resolved or names))


BLOCKED_REQUEST_ID = "flow-acquisition-blocked"


def _acquisition_card(project: Path, result: dict) -> dict:
    failed = [f"{k}: {v.get('error')}" for k, v in (result.get("items") or {}).items() if v.get("status") == "failed"]
    doc = setup_flow.request_user(project, {
        "kind": "choice", "title": "Some approved data could not be fetched",
        "message": "GeoForge could not bring in every input of the approved plan:\n  " + "\n  ".join(failed[:8])
                   + "\n\nRetry fetches only the missing items. Modify sends the plan back to the agent with your note.",
        "allow_note": True,
        "options": [
            {"id": "retry", "label": "Retry the missing data", "response": "Retry the data acquisition."},
            {"id": "modify", "label": "Modify the plan", "response": "Please revise the plan."},
        ]})
    doc["id"] = BLOCKED_REQUEST_ID
    (Path(project) / setup_flow.REQUEST_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    projectrun.report(project, {"status": "waiting_for_user", "summary": doc["title"], "blocker": doc}, source="flow")
    return doc


def acquire_then_continue(flow, ctx, project: Path, setup_ok: bool) -> dict:
    """Run the host acquisition pass from ACQUIRING and move on when it is complete.

    Returns the pass result; its status is done (now APPROVED→EXECUTING/SETUP), pending
    (server clip still processing), waiting (user must place files) or failed (BLOCKED).
    Serialized per project with the panel poll so two passes never overlap."""
    with _acq_lock(project):
        return _acquire_pass(flow, ctx, project, setup_ok)


def _acquire_pass(flow, ctx, project: Path, setup_ok: bool) -> dict:
    from . import acquire
    result = acquire.run(project)
    state = result["status"]
    if state == "done":
        ctx.move("acquired", {"data_receipted": True})
        _enter_execution(flow, ctx, project, setup_ok)
    elif state == "failed":
        ctx.move("acquisition_failed")
        _acquisition_card(project, result)
        projectrun.set_stage(project, display_stage(flow, ctx.state), "Some approved data could not be fetched")
    else:
        waiting = [k for k, v in result["items"].items() if v.get("status") == "waiting"]
        pending = [k for k, v in result["items"].items() if v.get("status") == "pending"]
        projectrun.set_stage(project, display_stage(flow, ctx.state),
                             ("Waiting for you to place: " + ", ".join(waiting)) if waiting
                             else ("Fetching approved data: " + ", ".join(pending)))
    ctx.save()
    return result


def _enter_execution(flow, ctx, project: Path, setup_ok: bool) -> None:
    if setup_ok:
        ctx.move("execution_started", {"setup_verified": True})
        projectrun.set_stage(project, display_stage(flow, ctx.state), "Approved — running the plan")
    else:
        ctx.move("setup_needed")
        projectrun.set_stage(project, display_stage(flow, ctx.state),
                             "Approved — the scientific software must be set up first")


_ACQ_POLL: dict[str, float] = {}
_ACQ_POLL_LOCK = threading.Lock()
_ACQ_RUN_LOCKS: dict[str, threading.Lock] = {}
ACQ_POLL_SECONDS = 8.0


def _acq_lock(project: Path) -> threading.Lock:
    # ponytail: one lock per project for the process lifetime; the dict never shrinks
    with _ACQ_POLL_LOCK:
        return _ACQ_RUN_LOCKS.setdefault(str(Path(project).resolve()), threading.Lock())


def poll_acquisition(project: Path, setup_ok: bool) -> str | None:
    """Advance an ACQUIRING project from a status poll (no user message needed).

    Rate-limited per project and never overlapping a chat-driven pass; safe to call
    from the panel's refresh loop. Returns the pass status when one ran, else None."""
    project = Path(project)
    flow = _flow()
    ctx = flow.states.FlowContext.load(project)
    if ctx.state is not flow.states.State.ACQUIRING:
        return None
    key = str(project.resolve())
    with _ACQ_POLL_LOCK:
        last = _ACQ_POLL.get(key, 0.0)
        if time.time() - last < ACQ_POLL_SECONDS:
            return None
        _ACQ_POLL[key] = time.time()
    lock = _acq_lock(project)
    if not lock.acquire(blocking=False):
        return None                       # a chat-driven pass is running
    try:
        ctx = flow.states.FlowContext.load(project)   # re-read under the lock
        if ctx.state is not flow.states.State.ACQUIRING:
            return None
        return _acquire_pass(flow, ctx, project, setup_ok)["status"]
    except Exception:  # noqa: BLE001 — a poll must never break the panel
        return None
    finally:
        lock.release()


def _acquisition_message(result: dict) -> str:
    state = result.get("status")
    items = result.get("items") or {}
    if state == "waiting":
        rows = [f"`{v.get('expected_path')}`" for v in items.values() if v.get("status") == "waiting"]
        return ("**GeoForge needs you:** place the Baidu Pan dataset(s) at " + ", ".join(rows)
                + ". The link and extraction code are in **Project status**. Then click "
                "**Files are in place, continue**. Nothing runs until the files are there.")
    if state == "pending":
        rows = [f"{k} ({v.get('job_status')})" for k, v in items.items() if v.get("status") == "pending"]
        return ("**GeoForge is fetching the approved data:** " + ", ".join(rows)
                + ". Send any message to check again; the run starts when every input has a receipt.")
    return "**Some approved data could not be fetched.** Use the card in the chat to retry or modify the plan."


def _start_execution(flow, ctx, project: Path, setup_ok: bool) -> dict:
    """APPROVED → ACQUIRING (host fetches every approved input) → APPROVED → EXECUTING when
    every selected KI's software is verified, else the SETUP sub-flow. The execution turn
    starts a fresh agent session."""
    ctx.move("acquire", {"approval": flow.approval.check(project)})
    return acquire_then_continue(flow, ctx, project, setup_ok)


# ---------------------------------------------------------------------------
# turn: what this state's agent turn gets
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    session: object                        # flowgate.FlowSession
    execute: bool                          # compose(..., execute=)
    extra_prompt: str                      # appended to the [TASK]
    drop_scope_rules: bool                 # SCOPE_FIRST_RULES are the flow's job now
    policy: object                         # flow.policy.ProviderPolicy
    fingerprint_extra: str                 # forces a fresh CLI session when the state changes
    planning_worktree: Path | None = None  # codex/kimi PLANNING: run here, harvest plan files
    wrappers: dict = field(default_factory=dict)
    kind: str = "planning"                 # planning | execution | setup | readonly | auto
    draft_before: dict = field(default_factory=dict)
    project_before: dict = field(default_factory=dict)
    provider_succeeded: bool | None = None
    confirmation_required: bool = False
    started_at: float = 0.0                # wall clock when the turn was handed to the provider


def _receipts_since(project: Path, since: float) -> int:
    """Signed receipts (runs and downloads) written after *since*."""
    count = 0
    for sub in ("model-runs", "data-receipts"):
        folder = Path(project) / ".geoforge" / "receipts" / sub
        if folder.is_dir():
            count += sum(1 for f in folder.glob("*.json") if f.stat().st_mtime >= since)
    return count


def turn(project: Path, resolved, cfg, provider_kind: str, provider_name: str,
         repo_root: Path | None, goal: str, replan_reason: str = "",
         base_allowed_tools: list[str] | None = None,
         database_access_mode: str = "direct") -> Turn | None:
    """resolved = the live KI objects (name, root) the agent will see."""
    flow = _flow()
    S = flow.states.State
    ki_roots = {k.name: Path(k.root) for k in resolved}
    fs = flowgate.FlowSession.open(
        project, ki_roots, python=str(getattr(cfg, "python", "") or "python3"),
        database_access_mode=database_access_mode)
    state = fs.state
    provider = "api" if provider_kind == "api" else provider_name
    wrappers = wrapper_commands() if provider != "api" else None
    if wrappers and database_access_mode == "off":
        wrappers = dict(wrappers)
        wrappers.pop("obs_search", None)
        wrappers.pop("obs_download", None)

    if state in (S.PLANNING, S.REPLAN_REQUIRED):
        planning_wrappers = wrappers
        if planning_wrappers and database_access_mode != "direct":
            planning_wrappers = dict(planning_wrappers)
            planning_wrappers.pop("obs_search", None)
        # the app derives the draft plan; the agent corrects it
        if fs.plan is None or fs.inventory is None or state is S.REPLAN_REQUIRED and replan_reason:
            roots = _data_roots(flow, repo_root)
            intake = projectrun.load(project).get("intake") or {}
            intent = _intent_from_goal(goal + " " + str(intake.get("period") or ""))
            for key in ("understanding", "study_area", "period", "process", "scenario",
                        "requested_outputs"):
                if intake.get(key):
                    intent[key] = intake[key]
            try:
                _full, pj, inv = flow.plan.derive(list(ki_roots), intent, goal, roots, ki_roots)
                _localize_draft(pj, inv)
            except Exception as e:  # noqa: BLE001 — a missing card is a planning fact, not a crash
                pj, inv = {"schema_version": "1.0", "goal": goal, "selected_kis": list(ki_roots),
                           "coupling": [], "intent": intent, "steps": [], "scientific_choices": [],
                           "unresolved_questions": [f"draft plan could not be derived: {e}"],
                           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, \
                          {"schema_version": "1.0", "items": []}
            if fs.plan is None or fs.inventory is None:
                flow.plan.write_artifacts(project, pj, inv)
                fs.reload_artifacts()
        edges = flow.resolve.couplings_for(list(ki_roots), _data_roots(flow, repo_root).couplings, one_end=True)
        partners = [e["partner_missing"] for e in edges if e.get("partner_missing")]
        pp = flow.policy.for_state(state, provider, project, ki_roots,
                                   python=str(getattr(cfg, "python", "") or "python3"),
                                   wrappers=planning_wrappers)
        wt = _planning_worktree(project) if pp.planning_worktree else None
        draft_root = wt or project
        draft_plan, draft_inv = flow.plan.read_artifacts(draft_root)
        extra = flow.contracts.planning_block(ki_roots,
                                              draft_plan if isinstance(draft_plan, dict) else {},
                                              draft_inv if isinstance(draft_inv, dict) else {}, draft_root,
                                              partners_to_ask=sorted(set(partners)) or None,
                                              replan_reason=replan_reason,
                                              wrappers=planning_wrappers,
                                              database_access_mode=database_access_mode)
        if database_access_mode == "direct":
            # What the database holds for this study, derived by the desktop, so the
            # agent presents real options instead of waiting to be told they exist.
            from . import obs_access
            store = obs_access.load_catalogue() or {}
            known = projectrun.load(project).get("intake") or {}
            extra += "\n" + obs_access.study_hint_block(
                store.get("datasets") or [], goal, known.get("study_area"),
                known.get("understanding"), known.get("process"))
        extra += (f"\n[PLAN HANDOFF] Save BOTH JSON files under {draft_root / 'runs'}, even if "
                  "your review leaves their content unchanged. The app must observe a submission "
                  "from this turn; an untouched auto-draft is never a completed plan. "
                  "For API providers call write_plan. Stop after saving.\n")
        if wt:
            extra += (f"Original project {project} is READ ONLY. It is for inventory inspection, "
                      f"not plan writes. The only draft submission location is {draft_root}.\n")
        errors = project / "runs" / "plan-validation.txt"
        if errors.is_file():
            extra += "\n[PREVIOUS SUBMISSION NEEDS REPAIR]\n" + errors.read_text(encoding="utf-8")[:16000]
        import uuid
        import re
        confirm = bool(re.search(r"未确认|先只|只做|先.*规划|plan(?:ning)?[- ]only|do not|don't|before.*approv", goal, re.I))
        # "Plan first, I approve before anything runs" holds for the whole project,
        # including repair and modify rounds whose goal text is only the user's note.
        review_flag = project / ".geoforge" / "plan-review-requested"
        if confirm:
            review_flag.parent.mkdir(parents=True, exist_ok=True)
            review_flag.touch()
        confirm = confirm or review_flag.is_file()
        return Turn(fs, False, extra, True, pp, f"flow:{state.value}:{uuid.uuid4().hex}", wt, planning_wrappers or {},
                    draft_before=_plan_versions(draft_root), project_before=_plan_versions(project),
                    confirmation_required=confirm)

    if state is S.EXECUTING:
        if fs.approval_status() != "OK":
            fs.move("drift")
            projectrun.set_stage(project, display_stage(flow, fs.state), "Plan changed — needs re-approval")
            return turn(project, resolved, cfg, provider_kind, provider_name, repo_root, goal,
                        replan_reason="the plan files changed after approval")
        extra = flow.contracts.execution_block(ki_roots, fs.plan or {}, fs.approval_doc or {}, project,
                                               provider=provider, wrappers=wrappers,
                                               host_acquired=True)      # ACQUIRING ran before this turn
        # The user did not choose these; the KI's protocol did. Say so when reporting, so a
        # default is never presented as the user's decision (web chat rule, 2026-09-15).
        _defaults, _suggested = [], []
        for k, r in sorted(((fs.approval_doc or {}).get("decisions") or {}).items()):
            if not isinstance(r, dict) or r.get("source") != "ki_default":
                continue
            line = f"{display_input_id(r.get('input_id') or k)}: {str(r.get('value') or '')[:100]}"
            (_suggested if r.get("rationale") == _SUGGESTION_WHY else _defaults).append(line)
        if _defaults:
            extra += ("\n[INPUTS ON KI PROTOCOL DEFAULTS] The user was not asked about these; the KI's "
                      "own dag.yaml/SKILL.md decides them. Say which ones you relied on when you "
                      "report the result:\n  " + "\n  ".join(_defaults[:20])
                      + (f"\n  … and {len(_defaults) - 20} more" if len(_defaults) > 20 else "") + "\n")
        if _suggested:
            extra += ("\n[RECOMMENDATIONS THE USER ACCEPTED] The card showed these under "
                      "\u201cYou decide\u201d with a suggestion, and approving the plan accepted the "
                      "suggestion — the user did not pick them deliberately. Name them when you "
                      "report:\n  " + "\n  ".join(_suggested[:20])
                      + (f"\n  … and {len(_suggested) - 20} more" if len(_suggested) > 20 else "") + "\n")
        # Projects approved before ACQUIRING existed, or a replan that added data: one
        # idempotent host pass brings the approved inputs in before the agent runs steps.
        try:
            from . import acquire
            acq = acquire.run(project)
        except Exception as error:  # noqa: BLE001 — network trouble is reported, not fatal
            acq = {"status": "failed", "items": {}, "error": str(error)}
        if acq.get("status") != "done":
            unfinished = [f"{k}: {v.get('status')}{' (' + str(v.get('error')) + ')' if v.get('error') else ''}"
                          for k, v in (acq.get("items") or {}).items() if v.get("status") != "done"]
            extra += ("\n[DATA STATUS] GeoForge has not finished bringing in these approved inputs: "
                      + "; ".join(unfinished or [acq.get("error", "unknown")])
                      + ". Do not run steps that need them and do not fetch them yourself; "
                      "run the other steps or call request_replan if the plan must change.\n")
        pp = flow.policy.for_state(state, provider, project, ki_roots,
                                   python=str(getattr(cfg, "python", "") or "python3"),
                                   base_allowed_tools=base_allowed_tools, wrappers=wrappers)
        fs.ctx.enforcement = flow.states.Enforcement(pp.enforcement.value); fs.ctx.save()
        return Turn(fs, True, extra, True, pp, f"flow:{state.value}:{fs.approval_id}", None, wrappers or {},
                    kind="execution", started_at=time.time())

    if state in (S.ACQUIRING, S.BLOCKED):
        # pre() already ran the acquisition pass and replied, or the blocked card is
        # waiting for a click; nothing for an agent to do.
        return None

    if state in (S.SETUP_REQUIRED, S.SETUP_RUNNING):
        pp = flow.policy.for_state(state, provider, project, ki_roots)
        return Turn(fs, False, "[SETUP] The KI software is not verified yet. Finish setup; the "
                    "approved plan runs afterwards in a new session.", False, pp,
                    f"flow:{state.value}", None, {}, kind="setup")

    # PLAN_REVIEW / WAITING_FOR_USER / APPROVED / VERIFYING / COMPLETED / FAILED*: read-only turn
    pp = flow.policy.for_state(state, provider, project, ki_roots)
    extra = (f"[FLOW STATE: {state.value}] Answer the user's question from the project files. Do not "
             f"run, download, or write inputs; " + flowgate._hint(state))
    return Turn(fs, False, extra, True, pp, f"flow:{state.value}:{fs.approval_id}", None, {}, kind="readonly")


def _intent_from_goal(goal: str) -> dict:
    """Cheap intent: years and a lat/lon pair when the user typed them. Everything else is a
    planning question (the agent and the user fill it in)."""
    import re
    intent: dict = {"user_message": goal[:2000]}
    years = [int(y) for y in re.findall(r"\b(19[5-9]\d|20[0-4]\d)\b", goal)]
    if years:
        intent["start_year"], intent["end_year"] = min(years), max(years)
    m = re.search(r"(-?\d{1,2}\.\d+)\s*[,;]\s*(-?\d{1,3}\.\d+)", goal)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if abs(a) <= 90 and abs(b) <= 180:
            intent["lat"], intent["lon"] = a, b
    return intent


def _planning_worktree(project: Path) -> Path:
    """codex/kimi have no read-only mode: plan in a throwaway copy of the project (no outputs,
    no receipts); only the two plan files are harvested back by after()."""
    import uuid
    wt = Path(project) / ".geoforge" / "planning" / uuid.uuid4().hex
    (wt / "runs").mkdir(parents=True)
    source = project
    previous = project / ".geoforge" / "planning-last.json"
    try:
        candidate = Path(json.loads(previous.read_text(encoding="utf-8"))["draft_root"]).resolve()
        if (project / ".geoforge" / "planning").resolve() in candidate.parents:
            if len(_plan_versions(candidate)) == 2:
                source = candidate
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Only the drafts are copied, never inputs, binaries, approval keys or outputs.
    for rel in ("runs/plan.json", "runs/data-inventory.json"):
        shutil.copy2(source / rel, wt / rel)
    return wt


# ---------------------------------------------------------------------------
# after: validate / approve / verify
# ---------------------------------------------------------------------------

def _plan_versions(root: Path) -> dict:
    """Detect saves, including a deliberate rewrite of an unchanged reviewed draft."""
    import hashlib
    versions = {}
    for rel in ("runs/plan.json", "runs/data-inventory.json"):
        p = root / rel
        try:
            if p.is_symlink():
                continue
            st = p.stat()
            versions[rel] = (st.st_mtime_ns, st.st_ctime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:
            pass
    return versions


def _planning_failure(project: Path, t: Turn, errors: list[str], *, repair: bool = False) -> "Result":
    message = "Plan was not submitted for approval:\n- " + "\n- ".join(errors[:30])
    (project / "runs" / "plan-validation.txt").write_text(message, encoding="utf-8")
    projectrun.report(project, {"status": "needs_attention", "summary": message}, source="flow")
    if t.planning_worktree:
        meta = project / ".geoforge" / "planning-last.json"
        meta.write_text(json.dumps({"draft_root": str(t.planning_worktree)}), encoding="utf-8")
    # Identical rejected revisions must not trigger an infinite retry loop.
    versions = _plan_versions(t.planning_worktree or project)
    fingerprint = t.session.flow.plan.sha256({"errors": errors, "files": {k: v[-1] for k, v in versions.items()}})
    return Result(message=message, retry_planning=repair, revision=fingerprint)


def _ki_roots_for(plan: dict, project: Path | None) -> dict[str, Path]:
    """The materialised KI folders of the plan's KIs inside the project (models/<KI>/ki)."""
    roots = {}
    for name in plan.get("selected_kis") or []:
        if project is None:
            continue
        cand = Path(project) / "models" / str(name) / "ki"
        if (cand / "dag.yaml").is_file():
            roots[str(name)] = cand
    return roots


def _data_groups(plan: dict, inv: dict, project: Path | None = None) -> dict:
    """Inputs in the three groups the user needs: fetch / you / run.

    Decided by the host from facts, never from the agent's bookkeeping: the catalogue
    delivery, the plan's step outputs, files on disk, and the KI's own declaration of
    each input (source kind, format, notes, the tool that prepares it). See
    ki_tools_common.flow.declared."""
    from . import obs_access
    flow = _flow()
    items = [it for it in inv.get("items") or [] if isinstance(it, dict)]
    produced = {str(o) for st in plan.get("steps") or [] if isinstance(st, dict)
                for o in st.get("outputs") or []}
    declared = ()
    for root in _ki_roots_for(plan, project).values():
        declared = declared + flow.declared.declared_inputs(str(root))

    def _row(it, verdict):
        cat = it.get("catalogue") or {}
        return {"id": it.get("id"), "for": list(it.get("required_by") or []),
                "resolution": cat.get("resolution"),
                "dataset_id": it.get("dataset_id"), "size": cat.get("size"),
                "size_label": obs_access.size_label(cat.get("size")),
                "name": cat.get("name"), "how": verdict["how"],
                "declared": (verdict.get("declared") or {}).get("name"),
                "facts": {k: (verdict.get("declared") or {}).get(k) for k in ("format", "unit", "notes", "default_tool")},
                "target_path": f"inputs/user/{it.get('id')}" if verdict["how"] == "provide" else None,
                "note": flow.declared.instructions(it, verdict),
                "period": [cat.get("start_date"), cat.get("end_date")] if cat.get("start_date") else None}

    groups = {"fetch": [], "you": [], "run": []}
    for it in items:
        verdict = flow.declared.classify(it, declared, produced)
        groups[verdict["group"]].append(_row(it, verdict))
    return {"total": len(items), **groups}


def plan_data_status(project: Path) -> dict | None:
    """Every input of the approved/drafted plan with what has happened to it.

    done: on disk with a receipt or a present local path; waiting_for_you: the
    manual download GeoForge is currently asking the user for; pending: not yet
    downloaded or generated; missing: no source at all."""
    project = Path(project)
    try:
        flow = _flow()
        pj, inv = flow.plan.read_artifacts(project)
    except Exception:  # noqa: BLE001 — no flow or unreadable plan: no plan data
        return None
    if not isinstance(pj, dict) or not isinstance(inv, dict):
        return None
    from . import obs_access
    groups = _data_groups(pj, inv, project)
    by_id = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    receipted: set[str] = set()
    acquisitions: dict[str, dict] = {}
    for f in (project / ".geoforge" / "receipts" / "data-receipts").glob("*.json"):
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
            if (isinstance(receipt, dict) and receipt.get("kind") == "download"
                    and flow.receipts.verify(project, receipt)
                    and flow.receipts._download_still_valid(project, receipt, inv)):
                receipted.add(str(receipt.get("item_id")))
                if receipt.get('acquisition'):
                    acquisitions[str(receipt.get('item_id'))] = receipt['acquisition']
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    try:
        passed = set(json.loads((project / "runs" / "evidence.json").read_text(encoding="utf-8")).get("steps_passed") or [])
    except (OSError, json.JSONDecodeError):
        passed = set()
    produced_by = {str(o): str(st.get("id")) for st in pj.get("steps") or [] if isinstance(st, dict)
                   for o in st.get("outputs") or []}
    request = setup_flow.request(project)
    waiting_title = str(request.get("title") or "") if request and request.get("status") == "waiting" else ""
    waiting_items = {str(r.get("item_id")) for r in (request or {}).get("rows") or []} if waiting_title else set()
    from . import acquire
    acq_items = acquire.status(project).get("items") or {}

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
                status = "done" if produced_by.get(str(row.get("id"))) in passed else "pending"
            elif how in ("prepared", "default"):
                status = "pending"
            elif how == "provide":
                target = project / str(row.get("target_path") or "")
                status = "done" if any(p.is_file() and not p.name.startswith(".") for p in target.rglob("*")) \
                    else "waiting_for_you"
            elif how == "choose":
                status = "waiting_for_you"
            elif str(row.get('id')) in acquisitions:
                status = 'acquired'
            elif str(row.get("id")) in receipted or (how == "on_disk" and _local(item)):
                status = "done"
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
            elif status in {"done", "acquired"}:
                action = "agent_validate"
            elif item.get('delivery') == 'subset':
                action = 'acquire_subset'
            elif group == "generated":
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
                         "resolution": (item.get("catalogue") or {}).get("resolution"),
                         "size": (item.get("catalogue") or {}).get("size"),
                         'acquisition_id': item.get('acquisition_id'),
                         'scientific_validation': 'pending' if item.get('acquisition_id') else None,
                         "dataset_id": dataset_id or None, "size_label": row.get("size_label") or "",
                         "for": row.get("for") or [], "delivery": item.get("delivery")})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    binding_status = obs_access._read_snapshot(project / '.geoforge/data-binding-status.json') or {}
    return {"items": rows, "counts": counts, "total": len(rows), 'binding_status': binding_status}


def _data_summary(plan: dict, inv: dict, project: Path | None = None) -> str:
    """The text twin of the card's data section: fetch / you / run."""
    from . import obs_access
    g = _data_groups(plan, inv, project)
    by_id = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    lines = [f"Data: {g['total']} inputs"]
    if g["fetch"]:
        lines.append(f"  ✓ GeoForge fetches after approval ({len(g['fetch'])})")
        for r in g["fetch"][:8]:
            it = by_id.get(str(r["id"]), {})
            es = it.get("estimate_summary") or {}
            what = (f"server clip, {obs_access.size_label(es.get('bytes')) or 'size unknown'}, {es.get('n_parts') or '?'} files"
                    if r["how"] == "clip" else f"{r['size_label'] or 'size unknown'}")
            lines.append(f"    {r['id']} ← {r['dataset_id']} ({what})")
    if g["you"]:
        lines.append(f"  ⬇ you ({len(g['you'])})")
        for r in g["you"][:8]:
            if r["how"] == "manual":
                lines.append(f"    download {r['dataset_id']} ({r['size_label'] or 'size unknown'}) from the Baidu link GeoForge shows after approval → {r['id']}")
            else:
                lines.append(f"    {r['id']}: {r['note'] or 'provide it'}")
    if g["run"]:
        kinds = {"on_disk": "already on disk", "generated": "made by a step", "default": "KI default method",
                 "prepared": "prepared during the run"}
        counts = {}
        for r in g["run"]:
            counts[r["how"]] = counts.get(r["how"], 0) + 1
        lines.append("  ⚙ the run prepares itself (" + ", ".join(f"{n} {kinds[k]}" for k, n in counts.items()) + ")")
    for it in inv.get("items") or []:
        res = ((it or {}).get("catalogue") or {}).get("resolution") or {}
        if isinstance(it, dict) and res.get("spatial_filter_applied") is False:
            lines.append(f"  {it.get('id')}: uncut delivery extent {res.get('delivery_extent')}; "
                         f"study bbox {res.get('requested_bbox')}; local extraction required.")
    return "\n".join(lines)


def _data_choices(plan: dict, inv: dict) -> list[dict]:
    """The candidates the agent considered per input, with catalogue facts, for the card.

    This is the missing step the user asked for: what the database holds for each input,
    shown before approval, with the recommendation preselected and the user free to pick."""
    from . import obs_access
    store = obs_access.load_catalogue() or {}
    by_id = {str(d.get("id")): d for d in store.get("datasets") or [] if d.get("id")}
    items = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    out = []
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") != "data_source":
            continue
        item_id = str(c.get("item") or str(c.get("id") or "").replace("data:", "", 1))
        options = []
        for ds in c.get("options") or []:
            rec = by_id.get(str(ds))
            if rec is None:
                continue                # invented ids never reach the user
            options.append({"dataset_id": str(ds), "name": rec.get("name"), "delivery": rec.get("delivery"),
                            "size": rec.get("size"), "size_label": obs_access.size_label(rec.get("size")),
                            "period": [rec.get("start_date"), rec.get("end_date")] if rec.get("start_date") else None,
                            "bbox": rec.get("bbox")})
        if not options:
            continue
        picked = str(c.get("decision") or c.get("picked") or items.get(item_id, {}).get("dataset_id") or "")
        out.append({"id": str(c.get("id")), "item": item_id, "picked": picked,
                    "rationale": str(c.get("rationale") or ""), "options": options})
    return out


def apply_choice_picks(plan: dict, choices: dict) -> list[str]:
    """Write NON-data card picks into the plan so a re-issued card keeps them (codex/kimi #5).
    A pick that is not one of the offered options is ignored."""
    done = []
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") == "data_source" or not c.get("id"):
            continue
        pick = (choices or {}).get(str(c["id"]))
        if pick and str(pick) in [str(o) for o in c.get("options") or []]:
            c["decision"], c["decision_source"] = pick, "user"      # display only; provenance
            done.append(str(c["id"]))                               # comes from the answer store
    return done


def apply_data_choices(plan: dict, inv: dict, choices: dict) -> list[str]:
    """The user's picks from the card: re-pin the items, clear stale stamps. Returns changed item ids."""
    changed = []
    items = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") != "data_source":
            continue
        pick = choices.get(str(c.get("id")))
        if not pick or pick not in [str(o) for o in c.get("options") or []]:
            continue
        item_id = str(c.get("item") or str(c.get("id") or "").replace("data:", "", 1))
        item = items.get(item_id)
        if item is None or item.get("dataset_id") == pick:
            c["decision"], c["decision_source"] = pick, "user"
            continue
        c["decision"], c["decision_source"] = pick, "user"
        c["picked"] = pick
        item["decision_source"] = "user"
        for key in ("acquisition_id", "acquisition_request_sha256", "acquisition_offer", "estimate_summary", "catalogue"):
            item.pop(key, None)
        item["dataset_id"] = pick
        item["chosen_source"] = pick
        item.pop("delivery", None)
        changed.append(item_id)
    return changed


ANSWERS_FILE = "user-answers.json"          # under .geoforge/ — policy.ALWAYS_PROTECTED


def _answers_path(project: Path) -> Path:
    return Path(project) / ".geoforge" / ANSWERS_FILE


def load_user_answers(project: Path) -> dict:
    """What the USER actually answered, host-written. The plan files are agent-writable, so a
    provenance marker inside them proves nothing (codex/kimi review, 2026-09-25)."""
    try:
        doc = json.loads(_answers_path(project).read_text(encoding="utf-8"))
        return doc.get("answers") or {} if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def record_user_answers(project: Path, card: dict | None, picks: dict | None) -> dict:
    """Store the picks that are a real answer, at the moment of the click.

    The approval card pre-selects the recommendation and the UI submits EVERY checked radio
    (web/app.html L1339), so a pick equal to what the card recommended is not evidence that the
    user chose anything — it is the default coming back. Only a pick that DIFFERS from the
    recommendation (or answers something the card recommended nothing for) is recorded as the
    user's. Anything else stays a disclosed default.
    """
    review = (card or {}).get("plan_review") or {}
    suggested = {}
    for ch in review.get("data_choices") or []:
        if isinstance(ch, dict) and ch.get("id"):
            suggested[str(ch["id"])] = str(ch.get("picked") or "")
    for ch in review.get("decisions") or []:
        if isinstance(ch, dict) and ch.get("id"):
            suggested[str(ch["id"])] = str(ch.get("picked") or "")
    answers = load_user_answers(project)
    for raw_id, value in (picks or {}).items():
        cid = str(raw_id)
        if value in (None, ""):
            continue
        if str(value) == suggested.get(cid, object()):
            continue                     # the pre-selected recommendation came back untouched
        answers[f"choice:{cid}"] = {"value": value, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    p = _answers_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": 1, "answers": answers}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)
    return answers


_KI_DEFAULT_WHY = "KI protocol default (its dag.yaml / SKILL.md decides it)"
_SUGGESTION_WHY = "planner recommendation shown on the card; accepted by approving the plan"


def decision_records(flow, plan: dict, inv: dict, answers: dict | None = None) -> tuple[dict, list]:
    """Who decided each thing the plan asked about — the web chat's schema (flow.decisions).

        user       the user answered it; taken ONLY from the host-written answer store
        ki_default the KI's protocol, or a planner recommendation the card showed and the user
                   accepted by approving; disclosed on every execution turn, never "their" choice
        open       nothing to fall back on — approving cannot answer it, so it must not start

    Ids are namespaced (`item:`, `choice:`, `question:`): desktop ids are free-form, and the
    shared schema reserves the bare names `site` and `period` for the web's scope records
    (a plain `period` choice would otherwise be unapprovable). Namespacing also keeps two
    same-named things in different namespaces from folding into one record.

    Returns (records, invalid); the caller refuses the approval while either blocks.
    """
    answers = answers or {}
    built: list[dict] = []
    invalid: list[str] = []
    seen: set[str] = set()

    def _add(ns: str, raw_id: str, source: str, value, why: str = "") -> None:
        iid = f"{ns}:{raw_id}"
        if iid.lower() in seen:
            invalid.append(f"{iid}: duplicate id in the plan — ids must be unique")
            return
        seen.add(iid.lower())
        built.append({"input_id": iid, "source": source, "value": value, "rationale": why or None})

    def _answer(ns: str, raw_id: str):
        rec = answers.get(f"{ns}:{raw_id}") or answers.get(f"choice:{raw_id}")
        return rec.get("value") if isinstance(rec, dict) else None

    for it in inv.get("items") or []:
        if not isinstance(it, dict):
            continue
        if not it.get("id"):
            invalid.append("an inventory item has no id")
            continue
        iid = str(it["id"])
        answered = _answer("item", iid) or _answer("item", f"data:{iid}")
        concrete = (it.get("dataset_id") or it.get("chosen_source") or it.get("decision")
                    or (", ".join(str(p) for p in it.get("local_paths") or []) or None))
        if answered:
            _add("item", iid, "user", answered, "you chose this on the approval card")
        elif it.get("needs_user") and not concrete:
            _add("item", iid, "open", f"{it.get('category') or 'input'} still needs your decision")
        elif concrete:
            _add("item", iid, "ki_default", str(concrete), _KI_DEFAULT_WHY)
        else:
            kd = it.get("ki_default") or {}
            _add("item", iid, "ki_default",
                 str(kd.get("default_source") or kd.get("source_kind") or it.get("strategy")
                     or "the KI prepares it per its SKILL.md"), _KI_DEFAULT_WHY)

    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict):
            continue
        if not c.get("id"):
            invalid.append("a scientific choice has no id")
            continue
        cid = str(c["id"])
        answered = _answer("choice", cid)
        if answered:
            _add("choice", cid, "user", answered, "you chose this on the approval card")
        elif c.get("decision"):
            _add("choice", cid, "ki_default", str(c["decision"]), _KI_DEFAULT_WHY)
        elif c.get("picked"):
            _add("choice", cid, "ki_default", str(c["picked"]), _SUGGESTION_WHY)
        elif c.get("high_impact"):
            opts = ", ".join(str(o) for o in (c.get("options") or [])[:6])
            _add("choice", cid, "open", f"{c.get('kind') or 'choice'}: {opts or 'needs your decision'}")

    # The planner saying "this is unresolved" is exactly an open input (Design B parity): the
    # card already lists these under "Waiting on you", so approval must not run past them.
    for n, q in enumerate(plan.get("unresolved_questions") or [], 1):
        if str(q or "").strip():
            _add("question", str(n), "open", str(q)[:300])

    invalid += [f"{r['input_id']}: {why}" for r in built
                for ok, why in [flow.decisions.validate_record(r)] if not ok]
    return flow.decisions.fold_payloads(built), invalid


def display_input_id(iid: str) -> str:
    """`item:forcing` → `forcing` for anything a person reads."""
    return str(iid).split(":", 1)[1] if ":" in str(iid) else str(iid)


def _card(flow, fs, plan: dict, inv: dict, provider_note: str) -> dict:
    """The PLAN_REVIEW card, in the shape setup.request_user renders (issue §UI)."""
    can = [f"prepare inputs for {k}" for k in plan.get("selected_kis") or []]
    edges = [c.get("edge_id") for c in plan.get("coupling") or [] if c.get("edge_id")]
    if edges:
        can.append("couple: " + ", ".join(edges))
    decide = [f"{c.get('kind')}: {', '.join(map(str, c.get('options') or []))} (suggested {c.get('picked')})"
              for c in plan.get("scientific_choices") or [] if c.get("high_impact") and not c.get("decision")]
    msg = (f"What I understood\n  {plan.get('goal')}\n\n"
           f"GeoForge can do itself\n  " + ("\n  ".join("✓ " + c for c in can) or "—") + "\n\n"
           + _data_summary(plan, inv, fs.project) + "\n\n"
           + ("You decide\n  " + "\n  ".join(decide) + "\n\n" if decide else "")
           + f"Steps: {len(plan.get('steps') or [])}   Tool policy: {provider_note}\n"
           f"Details: runs/plan.json, runs/data-inventory.json")
    intent = plan.get("intent") if isinstance(plan.get("intent"), dict) else {}
    steps = []
    for st in plan.get("steps") or []:
        if not isinstance(st, dict):
            continue
        tool = str(st.get("tool") or "")
        steps.append({"id": st.get("id"), "kind": st.get("kind"), "ki": st.get("ki"),
                      "tool": Path(tool).name if tool else None,
                      "env": sorted((st.get("env") or {}).keys()),
                      "inputs": list(st.get("inputs") or []), "outputs": list(st.get("outputs") or [])})
    decisions = [{"id": c.get("id"), "kind": c.get("kind"), "options": list(c.get("options") or []),
                  "picked": c.get("picked"), "decided": bool(c.get("decision")),
                  "high_impact": bool(c.get("high_impact"))}
                 for c in plan.get("scientific_choices") or [] if isinstance(c, dict)
                 and c.get("kind") != "data_source"]
    data_choices = _data_choices(plan, inv)
    review = {"goal": plan.get("goal"), "kis": list(plan.get("selected_kis") or []),
              "coupling": edges, "study_area": intent.get("study_area"), "period": intent.get("period"),
              "data": _data_groups(plan, inv, fs.project), "steps": steps, "decisions": decisions,
              "data_choices": data_choices,
              "tool_policy": provider_note, "blockers": [], "not_ready": []}
    return {
        "id": APPROVAL_REQUEST_ID_PREFIX + fs.flow.plan.sha256(plan)[:10] + "-" + fs.flow.plan.sha256(inv)[:6],
        "plan_review": review,
        "kind": "choice", "title": "Approve the plan?", "message": msg, "allow_note": True,
        "options": [
            {"id": "approve", "label": "Approve and start",
             "description": "Execution starts in a fresh session with the approved plan; every run and download gets a receipt.",
             "response": "Approved. Start the execution."},
            {"id": "modify", "label": "Modify the plan",
             "description": "Tell me what to change in the note; I will revise the plan and ask again.",
             "response": "Please revise the plan."},
        ],
    }


def _issue_card(project: Path, fs, pj: dict, inv: dict, provider_note: str, *,
                turn_id: str = "", extra_why: list[str] | None = None) -> dict:
    """Show the one approval card for exactly this plan/inventory pair (WAITING_FOR_USER).

    There is no automatic approval: the card is the contract between the user and the run.
    Also used when the Approve click finds that a clip estimate changed."""
    from . import obs_access
    flow = fs.flow
    project = Path(project)
    # The approval UI is bound to exactly the reviewed pair, not just a plan filename.
    receipt = {"plan_sha256": flow.plan.sha256(pj), "inventory_sha256": flow.plan.sha256(inv),
               "turn": turn_id, "submitted_at": time.time()}
    (project / "runs" / "plan-review.json").write_text(json.dumps(receipt), encoding="utf-8")
    _ok, why = flow.approval.may_auto_approve(pj, inv)
    # `may_auto_approve` answers "could this be approved with no user at all"; the desktop always
    # asks the user, and approving ACCEPTS a shown recommendation. Saying "undecided" about a
    # choice the click will accept made the card contradict the approval rule (kimi review #6).
    _suggested = {str(c.get("id")) for c in pj.get("scientific_choices") or []
                  if isinstance(c, dict) and c.get("picked") and not c.get("decision")}
    why = [w for w in why if not any(f"{cid!r}" in str(w) for cid in _suggested)]
    for c in pj.get("scientific_choices") or []:
        if isinstance(c, dict) and str(c.get("id")) in _suggested and c.get("high_impact"):
            why.append(f"{c.get('kind') or 'choice'} {c.get('id')}: defaults to "
                       f"{c.get('picked')} unless you pick another")
    why = list(extra_why or []) + list(why)
    manual = [it for it in inv.get("items") or []
              if isinstance(it, dict) and it.get("delivery") == "manual"]
    if manual:
        why.append("manual download needed: " + ", ".join(
            f"{it.get('dataset_id') or it.get('id')}"
            + (f" ({obs_access.size_label((it.get('catalogue') or {}).get('size'))})"
               if (it.get('catalogue') or {}).get('size') else "")
            for it in manual[:6]))
    ready = flow.plan.validate(pj, inv, list(fs.ki_roots), fs.ki_roots, for_execution=True)
    card = _card(flow, fs, pj, inv, provider_note)
    if why:
        card["message"] += "\n\nWaiting on you\n  " + "\n  ".join(why[:8])
        card["plan_review"]["blockers"] = list(why[:8])
    if ready:
        card["message"] += "\n\nNot ready to execute yet\n  " + "\n  ".join(ready[:6])
        card["plan_review"]["not_ready"] = list(ready[:6])
    doc = setup_flow.request_user(project, card)
    doc["id"] = card["id"]
    doc["review"] = receipt
    doc["plan_review"] = card["plan_review"]
    (project / setup_flow.REQUEST_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if fs.state is not flow.states.State.WAITING_FOR_USER:
        fs.move("needs_user")
    projectrun.report(project, {"status": "waiting_for_user", "summary": card["title"], "blocker": doc},
                      source="flow")
    return doc


@dataclass
class Result:
    request: dict | None = None     # the approval card (setup.request_user doc) to show
    continue_now: bool = False      # setup verified: start the execution turn right away
    message: str = ""
    retry_planning: bool = False
    revision: str = ""


def claim_planning_repair(result: Result, rejected: set[str]) -> bool:
    """Retry changed rejected drafts, but never spin on the same failure/content."""
    if not result.retry_planning or not result.revision or result.revision in rejected:
        return False
    rejected.add(result.revision)
    return True


def after(project: Path, t: Turn | None, reply: str, provider_note: str = "",
          setup_ok: bool = True) -> Result:
    """Close the turn: validate the plan / show the approval card / check receipts."""
    if t is None:
        return Result()
    flow = t.session.flow
    S = flow.states.State
    fs = t.session
    fs.ctx = flow.states.FlowContext.load(project)     # tools may have moved nothing, but reload
    state = fs.ctx.state
    fs.reload_artifacts()
    if t.kind in ("setup", "auto") and state is S.EXECUTING:
        return Result(continue_now=True)          # setup verified → run the approved plan now

    if state in (S.PLANNING, S.REPLAN_REQUIRED):
        submitted = getattr(fs, "plan_submission", None)
        if (t.provider_succeeded is False or getattr(fs, "provider_succeeded", None) is False) and not submitted:
            # A plan that was submitted before the connection died is still a plan;
            # only a turn that never submitted is a failure.
            return _planning_failure(project, t, ["The provider failed or was interrupted. Your draft is preserved; retry planning."])
        draft_root = t.planning_worktree or project
        current = _plan_versions(draft_root)
        saved_both = len(current) == 2 and all(current.get(k) != v for k, v in t.draft_before.items())
        api_submission = getattr(fs, "plan_submission", None)
        pj, inv = flow.plan.read_artifacts(draft_root)
        asked = setup_flow.request(project)
        if (not saved_both and not api_submission and asked and asked.get("status") == "waiting"
                and not str(asked.get("id", "")).startswith(APPROVAL_REQUEST_ID_PREFIX)):
            # The agent asked the user one question instead of writing the plan: that is
            # a pause, not a failed submission. Planning resumes with the answer.
            projectrun.report(project, {"status": "waiting_for_user", "summary": asked.get("title") or "Question for you",
                                        "blocker": asked}, source="flow")
            return Result()
        if not saved_both and not api_submission:
            unsaved = [k for k in ("runs/plan.json", "runs/data-inventory.json")
                       if k not in current or current[k] == t.draft_before.get(k)]
            return _planning_failure(project, t, [
                "No current-turn submission of both plan files. The generated draft is not an agent-reviewed plan.",
                "Save these files again even if unchanged: " + ", ".join(unsaved),
            ], repair=t.provider_succeeded is True)
        if pj is None or inv is None:
            return _planning_failure(project, t, ["Both plan files must contain valid JSON objects."], repair=True)
        if api_submission and api_submission != (flow.plan.sha256(pj), flow.plan.sha256(inv)):
            return _planning_failure(project, t, ["The files changed after write_plan submitted them. Submit the current revision again."])
        errs = flow.plan.validate(pj, inv, list(fs.ki_roots), fs.ki_roots)
        if errs:
            return _planning_failure(project, t, errs, repair=True)
        # Every pinned GeoForge Database id becomes a verified fact on the item
        # (delivery, size, coverage) before the user sees the card.
        from . import obs_access
        stamp_errors = obs_access.stamp_inventory(inv, project=project)
        if stamp_errors:
            return _planning_failure(project, t, stamp_errors, repair=True)
        # Fresh clip numbers on the card: re-estimate every attached clip now and
        # stamp again so the sizes the user reads are seconds old, not minutes.
        from . import obs_subset
        obs_subset.refresh_inventory(project, inv)
        stamp_errors = obs_access.stamp_inventory(inv, project=project)
        if stamp_errors:
            return _planning_failure(project, t, stamp_errors, repair=True)
        if t.planning_worktree and _plan_versions(project) != t.project_before:
            return _planning_failure(project, t, ["The original plan changed while planning. Both revisions are preserved; review and resubmit instead of overwriting."])
        flow.plan.write_artifacts(project, pj, inv)
        fs.reload_artifacts()
        (project / "runs" / "plan-validation.txt").unlink(missing_ok=True)
        (project / ".geoforge" / "planning-last.json").unlink(missing_ok=True)
        fs.move("plan_written", {"plan_valid": True})
        doc = _issue_card(project, fs, pj, inv, provider_note, turn_id=t.fingerprint_extra)
        return Result(request=doc)

    if state is S.EXECUTING:
        if REPLAN_MARKER in (reply or ""):
            fs.move("replan")
            flow.approval.revoke(project, "agent reported REPLAN_REQUIRED")
            projectrun.set_stage(project, display_stage(flow, fs.state), "The agent needs a plan change")
            return Result()
        ev = fs.evidence(enforcement=fs.ctx.enforcement.value)
        (project / "runs" / "evidence.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
        if ev["validation"] == "failed":
            fs.move("run_finished"); fs.move("validation_failed")
            projectrun.set_stage(project, display_stage(flow, fs.state),
                                 "A run failed validation — see runs/evidence.json")
        elif ev["receipts_verified"] and ev["validation"] == "passed":
            fs.move("run_finished")
            fs.move("validated", {"receipts_verified": True, "validation": "passed"})
            projectrun.set_stage(project, display_stage(flow, fs.state), "Completed — every step has a verified receipt")
        else:
            missing = ev.get("steps_missing") or []
            done = len(ev.get("steps_passed") or [])
            projectrun.set_stage(project, display_stage(flow, state),
                                 f"Running — {done} steps done, "
                                 f"{len(missing)} to go" + (f", {len(ev['unreceipted_artifacts'])} unreceipted files"
                                                             if ev.get("unreceipted_artifacts") else ""))
            pending = setup_flow.request(project)
            if pending and pending.get("status") == "waiting" and pending.get("kind") == "download":
                # The link and code are private to the user; the chat only points there.
                return Result(message=(
                    f"**GeoForge needs you:** {pending.get('title')}. The download link and "
                    "extraction code are in **Project status**. Place the files at "
                    f"`{pending.get('expected_path') or 'the path shown there'}`, then click "
                    "**Files are in place, continue** or reply here. The run waits until then."))
            # The agent's prose is not evidence.  Say in the chat what the receipts say,
            # so a turn that describes work it never ran is contradicted right there.
            if t.started_at and (reply or "").strip() and _receipts_since(project, t.started_at) == 0:
                return Result(message=(
                    f"**GeoForge verification:** this turn ran no receipted step and downloaded "
                    f"nothing. Steps with a verified receipt: {done} of {done + len(missing)}. "
                    "Anything described above as produced does not exist until a receipt records it."))
        return Result()
    return Result()


# ---------------------------------------------------------------------------
# small helpers gui.py calls
# ---------------------------------------------------------------------------

def wrapper_commands() -> dict:
    """The receipt wrappers a CLI agent must use (plan v3 B7 / 06 §3.6). They are the app
    itself — the frozen binary accepts CLI sub-commands; from source `python -m kiss_cli`.
    The exact string is also what the Claude Bash allow-list grants — nothing else runs.

    codex desktop review #4: the frozen binary is "GeoForge Desktop" (a space), which is
    neither shell-safe nor a stable allow-list prefix. So the wrapper is a tiny launcher
    script at a space-free path (``~/.kiss/bin/geoforge-flow``) that execs the real binary."""
    import os as _os
    import shlex
    import sys as _sys
    database_launcher = _database_launcher_path()
    if not getattr(_sys, "frozen", False):
        base = f"{_sys.executable} -m kiss_cli"
        if " " in _sys.executable:
            base = f"{shlex.quote(_sys.executable)} -m kiss_cli"
        return {"run_tool": f"{base} run-tool", "fetch": f"{base} fetch",
                "obs_search": (str(database_launcher) if database_launcher else
                               f"{base} obs-search")}
    launcher = _launcher_path()
    if launcher is None:
        base = shlex.quote(_sys.executable)
    else:
        base = str(launcher)
    return {"run_tool": f"{base} run-tool", "fetch": f"{base} fetch",
            "obs_search": (str(database_launcher) if database_launcher else
                           f"{base} obs-search")}


def wrapper_access_roots(wrappers: dict | None) -> list[str]:
    """Return only the launcher directory needed by a scoped CLI.

    Frozen builds use ``~/.kiss/bin/geoforge-flow`` so a bundle path containing
    spaces remains shell-safe. Kimi's outer macOS sandbox needs that one
    directory declared explicitly; the rest of the user's home stays closed.
    """
    import shlex
    roots: list[str] = []
    for command in (wrappers or {}).values():
        try:
            executable = Path(shlex.split(str(command))[0]).resolve(strict=False)
        except (IndexError, OSError, ValueError):
            continue
        if executable.name not in {"geoforge-flow", "geoforge-flow.cmd",
                                   "geoforge-db", "geoforge-db.cmd"}:
            continue
        parent = str(executable.parent)
        if executable.is_file() and parent not in roots:
            roots.append(parent)
    return roots


def _launcher_path() -> Path | None:
    """Create a stable IPC launcher for gated flow commands.

    The previous launcher executed the frozen app binary a second time.  A
    development build below Documents therefore crossed both Kimi's Seatbelt
    boundary and macOS TCC, causing a permission popup on every command.  This
    helper talks only to the already-running Desktop process over loopback.
    """
    import os as _os
    home = Path.home()
    # user-owned locations only (kimi desktop R2 #3: never a world-writable temp dir). When
    # every candidate has a space in it the caller quotes the binary path instead.
    candidates = [home / ".kiss" / "bin", home / ".config" / "geoforge" / "bin"]
    for d in candidates:
        if " " in str(d):
            continue
        try:
            d.mkdir(parents=True, exist_ok=True)
            try:
                _os.chmod(d, 0o755)
            except OSError:
                pass
            if _os.name == "nt":
                script = d / "geoforge-flow.py"
                p = d / "geoforge-flow.cmd"
                body = '@echo off\r\npy -3 "%~dp0geoforge-flow.py" %*\r\n'
                if (not script.is_file() or
                        script.read_text(encoding="utf-8", errors="replace") != _FLOW_HELPER):
                    script.write_text(_FLOW_HELPER, encoding="utf-8")
            else:
                p = d / "geoforge-flow"
                body = _FLOW_HELPER
            if not p.is_file() or p.read_text(encoding="utf-8", errors="replace") != body:
                p.write_text(body, encoding="utf-8")
            if _os.name != "nt":
                p.chmod(0o755)
            return p
        except OSError:
            continue
    return None


def _database_launcher_path() -> Path | None:
    """Install the token-free database KI adapter in a stable user path.

    Unlike ``geoforge-flow``, this helper never jumps back into the frozen app
    bundle.  That distinction matters when a development build lives below
    Documents: macOS TCC otherwise asks for folder access on every invocation,
    while Kimi's outer sandbox correctly refuses the bundle target.
    """
    import os as _os
    import sys as _sys
    home = Path.home()
    helper_body = _DATABASE_HELPER
    # The task-workflow KI is the reviewed source of the adapter.  Keep the
    # inline copy only as a recovery fallback for a partially downloaded KI
    # library; normal source and frozen builds both find models/ here.
    roots = [Path(__file__).resolve().parents[2]]
    frozen_root = getattr(_sys, "_MEIPASS", None)
    if frozen_root:
        roots.insert(0, Path(frozen_root))
    for root in roots:
        for source in (
                root / "system_kis" / "GeoForge_Database" / "tools" / "search_catalogue.py",
                root / "kiss" / "system_kis" / "GeoForge_Database" / "tools" / "search_catalogue.py"):
            try:
                if source.is_file():
                    helper_body = source.read_text(encoding="utf-8")
                    break
            except OSError:
                continue
        else:
            continue
        break
    candidates = [home / ".kiss" / "bin", home / ".config" / "geoforge" / "bin"]
    for directory in candidates:
        if " " in str(directory):
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if _os.name == "nt":
                script = directory / "geoforge-db.py"
                launcher = directory / "geoforge-db.cmd"
                body = '@echo off\r\npy -3 "%~dp0geoforge-db.py" %*\r\n'
                if (not script.is_file() or
                        script.read_text(encoding="utf-8", errors="replace") != helper_body):
                    script.write_text(helper_body, encoding="utf-8")
                if (not launcher.is_file() or
                        launcher.read_text(encoding="utf-8", errors="replace") != body):
                    launcher.write_text(body, encoding="utf-8")
            else:
                launcher = directory / "geoforge-db"
                if (not launcher.is_file() or
                        launcher.read_text(encoding="utf-8", errors="replace") != helper_body):
                    launcher.write_text(helper_body, encoding="utf-8")
                launcher.chmod(0o755)
            return launcher
        except OSError:
            continue
    return None


def couplings_dir() -> Path | None:
    """Where the coupling configs live: the bundled flow/data copy, else the server tree."""
    try:
        flow = _flow()
        roots = _data_roots(flow, None)
        return roots.couplings if Path(roots.couplings).is_dir() else None
    except Exception:  # noqa: BLE001
        return None


def setup_turn(project: Path, resolved, cfg, provider_kind: str, provider_name: str,
               database_access_mode: str = "direct") -> Turn | None:
    """A software-setup turn under the flow: the SETUP sub-flow, never a scientific run."""
    flow = _flow()
    S = flow.states.State
    ki_roots = {k.name: Path(k.root) for k in resolved}
    fs = flowgate.FlowSession.open(
        project, ki_roots, python=str(getattr(cfg, "python", "") or "python3"),
        database_access_mode=database_access_mode)
    if fs.state is S.APPROVED:
        fs.move("setup_needed")
    if fs.state is S.SETUP_REQUIRED:
        fs.move("setup_started")
    provider = "api" if provider_kind == "api" else provider_name
    pp = flow.policy.for_state(fs.state, provider, project, ki_roots)
    projectrun.set_stage(project, display_stage(flow, fs.state), "Setting up the scientific software")
    return Turn(fs, False, "", False, pp, f"flow:{fs.state.value}", None, {}, kind="setup")


def setup_verified(project: Path, resolved, cfg) -> None:
    """Called when the KI's preflight passed after a setup turn: SETUP_RUNNING → VERIFIED → APPROVED."""
    flow = _flow()
    S = flow.states.State
    ki_roots = {k.name: Path(k.root) for k in resolved}
    fs = flowgate.FlowSession.open(project, ki_roots)
    if fs.state is S.SETUP_RUNNING:
        fs.move("setup_verified", {"preflight_ok": True})
        fs.move("resume")                                   # → APPROVED
        _start_execution(flow, fs.ctx, project, True)      # → EXECUTING (codex R2 #2)
        projectrun.set_stage(project, display_stage(flow, fs.state), "Software verified — running the approved plan")


def policy_for_cli(t: Turn, provider_name: str, pol) -> object:
    """Recompute the flow policy for a CLI provider with the desktop's base grants (only
    their path-scoped READ grants are reused; see flow.policy._claude_executing_tools)."""
    flow = t.session.flow
    S = flow.states.State
    if t.kind == "setup" or t.session.state in (S.SETUP_REQUIRED, S.SETUP_RUNNING, S.SETUP_VERIFIED):
        # kimi desktop R2 #1: the setup sub-flow is driven by the desktop's own setup grants
        # (_grant_setup_execution); a flow policy here would replace them with read-only argv
        return None
    base: list[str] | None = None
    if provider_name == "claude" and pol is not None:
        from . import policy as _pol
        args, _enf = _pol.claude_args(pol)
        if len(args) >= 2 and args[0] == "--allowedTools":
            base = args[1:]
    if t.session.state is S.EXECUTING:
        return flow.policy.for_state(S.EXECUTING, provider_name, t.session.project, t.session.ki_roots,
                                     python=t.session.python, base_allowed_tools=base, wrappers=t.wrappers)
    return t.policy


def describe_policy(t: Turn) -> str:
    try:
        return t.session.flow.policy.describe(t.policy)
    except Exception:  # noqa: BLE001
        return ""


def auto_turn(project: Path, provider_kind: str, provider_name: str,
              database_access_mode: str = "direct") -> Turn | None:
    """The 'choose a model' turn when nothing resolved (codex desktop review #1/#2): a real
    FlowSession in RESOLVING_KIS (API tools filtered to read-only + report/request; CLI argv
    read-only), never project writes, never a worktree. Providers that cannot be gated are
    refused for scientific projects."""
    flow = _flow()
    fs = flowgate.FlowSession.open(
        project, {}, database_access_mode=database_access_mode)
    provider = "api" if provider_kind == "api" else provider_name
    if provider in flow.policy.NOT_OFFERED:
        raise flowgate.FlowDenied(
            f"{provider} cannot be held to the planning gate; choose Claude Code, Codex, Kimi or "
            f"an API provider for scientific projects")
    # Data availability can materially change both the KI choice and the first
    # clarification question.  Give CLI providers the same Desktop-owned,
    # read-only catalogue adapter during intake that they receive during
    # planning.  Do not expose fetch/download/run wrappers in RESOLVING_KIS.
    # API providers already receive ``search_observation_data`` through the
    # flow-filtered tool schema, so they need no shell adapter.
    wrappers: dict[str, str] = {}
    if provider_kind != "api" and database_access_mode == "direct":
        commands = wrapper_commands()
        if commands.get("obs_search"):
            wrappers["obs_search"] = commands["obs_search"]
    pp = flow.policy.for_state(fs.state, provider, project, {}, wrappers=wrappers)
    return Turn(fs, False, "", False, pp, f"flow:{fs.state.value}", None,
                wrappers, kind="auto")


def database_hint_for(goal: str, database_access_mode: str = "direct") -> str:
    """Intake-time list of catalogue records that match the user's goal text."""
    if database_access_mode != "direct":
        return ""
    from . import obs_access
    store = obs_access.load_catalogue() or {}
    return obs_access.study_hint_block(store.get("datasets") or [], goal)


def setup_allowed(project: Path) -> bool:
    """Scientific-software setup may run only after the plan is approved (APPROVED →
    SETUP_REQUIRED → SETUP_RUNNING), or in a project with no flow at all."""
    if not (Path(project) / "runs" / "flow-state.json").is_file():
        return True
    flow = _flow()
    S = flow.states.State
    st = flow.states.FlowContext.load(project).state
    return st in (S.APPROVED, S.SETUP_REQUIRED, S.SETUP_RUNNING, S.SETUP_VERIFIED)


def provider_refusal(provider_kind: str, provider_name: str) -> str | None:
    """Why a provider may not drive a flow-managed (scientific) chat, or None (kimi desktop
    review #2: NOT_OFFERED providers must be refused, not merely labelled)."""
    provider = "api" if provider_kind == "api" else (provider_name or "")
    try:
        flow = _flow()
    except Exception:  # noqa: BLE001
        return None
    if provider in flow.policy.NOT_OFFERED:
        return (f"{provider} cannot be held to the planning gate (no per-tool policy); for scientific "
                f"projects use Claude Code, Codex, Kimi or an API provider.")
    return None


def _intake_from_reply(reply: str) -> dict | None:
    """Read the invisible CLI handoff marker from an Agent response.

    Direct APIs use the typed progress tool. CLI providers are read-only during intake, so
    they cannot safely write a status file; an HTML comment is the provider-neutral return
    channel. It is untrusted JSON and is normalised/validated before any state transition.
    """
    for match in reversed(list(_INTAKE_PATTERN.finditer(reply or ""))):
        try:
            value = json.loads(match.group(1))
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def strip_intake_markers(reply: str) -> str:
    """Remove the private intake handoff before a reply is saved or displayed."""
    return _INTAKE_PATTERN.sub("", reply or "")


def promote_auto_choice(project: Path, catalog, reply: str = "") -> list[str]:
    """Validate the task-understanding handoff and only then enter PLANNING.

    Model selection alone is deliberately insufficient. The Agent must say the task is ready
    for a meaningful plan; otherwise the natural conversation remains in RESOLVING_KIS while
    it asks the user for the missing scientific fact.
    """
    flow = _flow()
    S = flow.states.State
    ctx = flow.states.FlowContext.load(project)
    if ctx.state is not S.RESOLVING_KIS:
        return list(ctx.selected_kis)
    state = projectrun.load(project)
    marker = _intake_from_reply(reply)
    if marker is not None:
        projectrun.report(project, {
            "status": "working" if marker.get("ready_for_planning") is True else "waiting_for_user",
            "summary": str(marker.get("understanding") or "Understanding the scientific task"),
            "selected_kis": marker.get("selected_kis") or [],
            "intake": marker,
        }, source="agent")
        state = projectrun.load(project)
    intake = state.get("intake") if isinstance(state.get("intake"), dict) else {}
    reported = [str(n) for n in (state.get("selected_kis") or [])]
    known = {ki.name for ki in catalog}
    names = [n for n in reported if n in known]
    # A popup/question and an incomplete or internally inconsistent intake are explicit
    # reasons not to plan yet.  ``ready_for_planning`` is Agent evidence, not authority:
    # the Desktop still checks that the Agent explained the task and did not list an
    # unanswered material question while claiming readiness.
    waiting = setup_flow.request(project)
    if not names or not str(intake.get("understanding") or "").strip():
        return []
    if waiting and waiting.get("status") == "waiting":
        return []
    # The Agent's one material question was answered by the user (the request is
    # "ready") and this turn brought no new intake: the stored intake is complete
    # now.  Promote instead of letting the Agent open a second round of questions.
    answered = bool(waiting and waiting.get("status") == "ready")
    ready = intake.get("ready_for_planning") is True and not intake.get("missing")
    if not ready and not (marker is None and answered):
        return []
    ctx.selected_kis = names
    ctx.move("kis_resolved", {"selected_kis": names})
    projectrun.select_kis(project, names)
    projectrun.set_stage(project, display_stage(flow, ctx.state), "Planning the run")
    return names
