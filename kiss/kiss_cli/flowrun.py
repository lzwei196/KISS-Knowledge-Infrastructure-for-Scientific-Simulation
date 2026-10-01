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
              card (always requiring the user's approval), or check receipts and
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

from . import flowgate, plan_review, projectrun, setup as setup_flow
from .acquire import INTENT_LOCK as _ACQ_INTENT_LOCK

APPROVAL_REQUEST_ID_PREFIX = plan_review.APPROVAL_REQUEST_ID_PREFIX
# continue_now follows only setup finishing AFTER the user approved (after() below): never "auto"
RUN_AFTER_SETUP = "Software verified. Starting your approved plan in a new session…"
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
    headers = {"X-GeoForge-Agent-Token": capability, "Content-Type": "application/json"}
    if sys.argv[1:2] == ["ask-question"]:
        question_token = os.environ.get("GEOFORGE_AGENT_QUESTION_TOKEN", "").strip()
        if not question_token:
            print("GeoForge question command is unavailable outside its owning project session.", file=sys.stderr)
            return 3
        headers["X-GeoForge-Question-Token"] = question_token
    body = json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                       "turn_id": os.environ.get("GEOFORGE_TURN_ID", ""),
                       "turn_project": os.environ.get("GEOFORGE_TURN_PROJECT", "")}).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers=headers,
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
    return projectrun.flow_display_stage(state, flow.states.DISPLAY_STAGE.get(state, "preparing"))


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

    # A queued acquisition change never starts an agent from its background tick.
    # Hand the saved user instruction to this next ordinary chat turn exactly once.
    with _ACQ_INTENT_LOCK:
        reason = _take_acquisition_replan(flow, ctx, project)
        uncertain = _uncertain_acquisition_replan(flow, ctx, project)
    if reason:
        return Pre(names=list(ctx.selected_kis or names), replan_reason=reason)
    if uncertain:
        return Pre(names=list(ctx.selected_kis or names), message=uncertain)

    # Plan Review owns the consent transaction; only its approved result starts data work.
    chosen = set(ctx.selected_kis or names)
    review = plan_review.respond(project, action=action, pending=pending, note=note,
                                 ki_roots={k.name: Path(k.root) for k in catalog if k.name in chosen})
    if review.disposition == "replan":
        return Pre(names=list(ctx.selected_kis or names), replan_reason=review.replan_reason)
    if review.disposition == "waiting":
        return Pre(names=list(ctx.selected_kis or names), message=review.message)
    if review.disposition == "approved":
        from . import obs_subset, obs_access
        inv = review.inventory
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
                'approval': flow.approval.approval_id(flow.approval.read(project)),   # issue #6b
                'message': 'Data binding failed: check the selected acquisition scope and intact file evidence. '
                           'Approval was saved, but dependent steps remain blocked.'})
        ctx.move("approved", {"approval": flow.approval.check(project)})
        result = _start_execution(flow, ctx, project, setup_ok)
        if ctx.state in (S.ACQUIRING, S.BLOCKED):
            # the host is still fetching data (or hit a wall): no agent turn yet
            return Pre(names=list(ctx.selected_kis or names), message=_acquisition_message(result))
        return Pre(names=list(ctx.selected_kis or names), message=None)

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
            return _request_acquisition_replan(flow, ctx, project, names,
                                               note or text or "user asked for changes")
        result = acquire_then_continue(flow, ctx, project, setup_ok)
        with _ACQ_INTENT_LOCK:
            reason = _take_acquisition_replan(flow, ctx, project)
        if reason:
            return Pre(names=list(ctx.selected_kis or names), replan_reason=reason)
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
        if _reload(flow, ctx, project) is not flow.states.State.ACQUIRING:
            from . import acquire
            return acquire.status(project)          # a background pass already moved it on
        return _acquire_pass(flow, ctx, project, setup_ok)


def _reload(flow, ctx, project: Path):
    """Adopt the Flow state on disk in the caller's context; another writer may have moved it."""
    ctx.__dict__.update(flow.states.FlowContext.load(project).__dict__)
    return ctx.state


def _acquire_pass(flow, ctx, project: Path, setup_ok: bool, *, automatic_only: bool = False) -> dict:
    from . import acquire
    with _ACQ_INTENT_LOCK:
        if _apply_acquisition_replan(flow, ctx, project):
            return {"status": "replanning", "items": acquire.status(project).get("items") or {}}
    result = acquire.run(project, automatic_only=True) if automatic_only else acquire.run(project)
    # This short lock only serializes intent publication with the final state commit;
    # network transfers never hold it. The long acquisition lock still owns all writes.
    with _ACQ_INTENT_LOCK:
        if _apply_acquisition_replan(flow, ctx, project):
            return dict(result, status="replanning")
        return _finish_acquire_pass(flow, ctx, project, setup_ok, result)


def _finish_acquire_pass(flow, ctx, project: Path, setup_ok: bool, result: dict) -> dict:
    # Never write a stale state back over a change made while the pass ran.
    if _reload(flow, ctx, project) is not flow.states.State.ACQUIRING or flow.approval.check(project) != "OK" \
            or result.get("approval_sha256") != flow.approval.approval_id(flow.approval.read(project)):
        return {"status": "stale", "items": {}}
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
        summary = []
        if pending:
            summary.append("Fetching approved data: " + ", ".join(pending))
        if waiting:
            summary.append("Waiting for you to place: " + ", ".join(waiting))
        projectrun.set_stage(project, display_stage(flow, ctx.state),
                             ". ".join(summary) + ". Model execution has not started.")
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


def _apply_acquisition_replan(flow, ctx, project: Path) -> bool:
    """Called only by the acquisition lock owner with the short intent lock held."""
    from . import acquire, obs_access
    intent = acquire.replan_intent(project)
    if intent.get("status") != "queued":
        return False
    state = _reload(flow, ctx, project)
    approval = flow.approval.approval_id(flow.approval.read(project))
    if state is not flow.states.State.ACQUIRING or not approval \
            or intent.get("approval_sha256") != approval or flow.approval.check(project) != "OK":
        # A later approval must never inherit an earlier user's queued revocation.
        intent["status"] = "stale"
        obs_access._atomic_json(Path(project) / acquire.REPLAN_FILE, intent)
        return False
    setup_flow.clear_request(project)
    flow.approval.revoke(project, "user asked to modify the plan while data was pending")
    ctx.move("modify")
    intent.update(status="applied", applied_flow_updated_at=ctx.updated_at)
    obs_access._atomic_json(Path(project) / acquire.REPLAN_FILE, intent)
    projectrun.set_stage(project, display_stage(flow, ctx.state), "Plan change saved; ready to revise")
    projectrun.report(project, {"status": "waiting_for_user", "blocker": None,
                               "summary": "Plan change saved. Send a message to revise the plan; no run has started."},
                      source="flow")
    return True


def _take_acquisition_replan(flow, ctx, project: Path) -> str:
    """Consume a completed deferred change, never a stale note from another Flow state."""
    from . import acquire, obs_access
    intent = acquire.replan_intent(project)
    if intent.get("status") != "applied":
        return ""
    _reload(flow, ctx, project)
    if ctx.state is not flow.states.State.PLANNING \
            or ctx.updated_at != intent.get("applied_flow_updated_at"):
        return ""
    intent["status"] = "consumed"
    obs_access._atomic_json(Path(project) / acquire.REPLAN_FILE, intent)
    return str(intent.get("reason") or "user asked for changes")


def _uncertain_acquisition_replan(flow, ctx, project: Path) -> str:
    """Do not silently lose the note if a crash interrupted the final intent write.

    Without the recorded resulting Flow timestamp, an unrelated replan is also
    possible. Display the saved instruction for confirmation; never act on it.
    """
    from . import acquire, obs_access
    intent = acquire.replan_intent(project)
    if intent.get("status") != "queued" or ctx.state is not flow.states.State.PLANNING \
            or flow.approval.read(project):
        return ""
    intent["status"] = "needs_confirmation"
    obs_access._atomic_json(Path(project) / acquire.REPLAN_FILE, intent)
    return ("The project is back in planning, but an interrupted update left this saved plan-change "
            "request unconfirmed: " + str(intent.get("reason") or "user asked for changes")
            + ". Please confirm or restate the change before I revise the plan. No run has started.")


def _request_acquisition_replan(flow, ctx, project: Path, names: list[str], reason: str) -> Pre:
    from . import acquire, obs_access
    with _ACQ_INTENT_LOCK:
        state = _reload(flow, ctx, project)
        approval = flow.approval.approval_id(flow.approval.read(project))
        if state is not flow.states.State.ACQUIRING or not approval or flow.approval.check(project) != "OK":
            return Pre(names=list(ctx.selected_kis or names),
                       message="Acquisition has changed. Check Project status before changing the plan.")
        obs_access._atomic_json(Path(project) / acquire.REPLAN_FILE, {
            "status": "queued", "approval_sha256": approval, "reason": reason,
            "requested_at": time.time(),
        })
        lock = _acq_lock(project)
        if lock.acquire(blocking=False):
            try:
                _apply_acquisition_replan(flow, ctx, project)
                saved_reason = _take_acquisition_replan(flow, ctx, project)
                if saved_reason:
                    return Pre(names=list(ctx.selected_kis or names), replan_reason=saved_reason)
            finally:
                lock.release()
        return Pre(names=list(ctx.selected_kis or names), message=(
            "Your plan change is saved. The current transfer may finish, but no next input or model run "
            "will start. GeoForge will return the project to planning when that transfer ends. "
            "Then send a message to revise the plan using your saved request."))


def _acq_lock(project: Path) -> threading.Lock:
    # ponytail: one lock per project for the process lifetime; the dict never shrinks
    with _ACQ_POLL_LOCK:
        return _ACQ_RUN_LOCKS.setdefault(str(Path(project).resolve()), threading.Lock())


def poll_acquisition(project: Path, setup_ok: bool, *, automatic_only: bool = False) -> str | None:
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
        return _acquire_pass(flow, ctx, project, setup_ok, automatic_only=automatic_only)["status"]
    except Exception:  # noqa: BLE001 — a poll must never break the panel
        return None
    finally:
        lock.release()


def _acquisition_message(result: dict) -> str:
    state = result.get("status")
    items = result.get("items") or {}
    if state == "replanning":
        return "Plan change saved. Send a message to revise the plan; no run has started."
    if state == "stale":
        return ("The acquisition state or approved plan changed during this pass. "
                "Check Project status before continuing; this result cannot start a run.")
    if state in {"waiting", "pending"}:
        sections = []
        automatic = []
        for key, item in items.items():
            if item.get("status") == "pending":
                job = item.get("job_status")
                label = job if isinstance(job, str) and job in {"queued", "running", "ready", "downloading"} else "pending"
                automatic.append(f"{key} (last reported: {label})")
        if automatic:
            sections.append("**GeoForge is fetching the approved data:** " + ", ".join(automatic)
                            + ". Automatic acquisition is separate from the manual inputs below. "
                            "The run starts when every input has a receipt; if automatic acquisition "
                            "finishes last, click **Start the approved run**.")
        manual = [f"`{v.get('expected_path')}`" for v in items.values() if v.get("status") == "waiting"]
        if manual:
            sections.append("**GeoForge needs you:** place the selected manual dataset(s) at "
                            + ", ".join(manual) + ". The links and extraction codes are in **Project status**. "
                            "Then click **Files are in place, continue**.")
        sections.append("Model execution has not started; required source data must be acquired first. "
                        "KI input preparation and scientific checks still remain after acquisition.")
        return "\n\n".join(sections)
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
    question_handoff_closed: bool = False  # an ended question turn cannot later submit its old drafts


def _command_gist(command, limit: int = 90) -> str:
    """The tail of a recorded command on one short line, for chat messages.

    Agents pass whole Python snippets through ``-c``; quoted verbatim they
    buried the "Completed." verdict under screens of code."""
    text = " ".join(" ".join(map(str, (command or [])[-3:])).split()).replace("`", "'")
    return text if len(text) <= limit else text[:limit - 1] + "…"


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
        extra += plan_review.settled_answers_block(project)   # outlives the 20-message chat window
        extra += ("\n[PLAN HANDOFF] If a planning decision needs the user, issue ONE request_user_action "
                  "(API tool, or the exact CLI QUESTION HANDOFF command above) "
                  "and stop for the user's answer. Ask before rewriting either full draft; "
                  "the conversation retains previous answers. Existing partial drafts are not "
                  "a final submission while a question remains. Only when the planning decisions "
                  f"are settled, save BOTH JSON files under {draft_root / 'runs'}, even if your review "
                  "leaves their content unchanged. The app must observe a final submission from this "
                  "turn; an untouched auto-draft is never a completed plan. For API providers call "
                  "write_plan. Stop after the final submission and wait for the user's approval.\n")
        if wt:
            extra += (f"Original project {project} is READ ONLY. It is for inventory inspection, "
                      f"not plan writes. The only draft submission location is {draft_root}.\n")
            extra += (
                "[QUESTION FALLBACK — THIS PLANNING WORKTREE ONLY] Prefer the exact CLI "
                "QUESTION HANDOFF command above. If it cannot reach the Desktop (for example, "
                "the shell sandbox blocks loopback), do not retry repeatedly, change the sandbox "
                "or request broad network permission. Instead write ONE JSON object to "
                f"`{wt / 'runs' / 'question-request.json'}` and STOP. Envelope: "
                f'{{"turn_id":"{wt.name}","question":{{"kind":"choice","title":"...",'
                '"message":"...","options":[{"id":"ki-default","label":"...",'
                '"description":"KI evidence and applicability","response":"..."}],"allow_note":true}}. '
                "The question uses the same narrow schema as the command and the whole file "
                "must be at most 64 KiB. Include the actual current decision, supported default "
                "and alternatives, not the placeholder text above. The app reads only this "
                "turn's exact file after you stop and displays the question; this is not a "
                "final plan submission or approval. Keep unresolved questions in your drafts. "
                "Do not put this file in the original project or reuse a previous turn_id. "
                "This fallback is not available during intake or outside a planning worktree.\n")
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
            line = f"{plan_review.display_input_id(r.get('input_id') or k)}: {str(r.get('value') or '')[:100]}"
            (_suggested if plan_review.is_accepted_suggestion(r.get("rationale")) else _defaults).append(line)
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
        if pp.enforcement is not flow.states.Enforcement.EXACT:
            extra += (f"\n[PROVENANCE UNDER {provider}] The tool fence for this provider is approximate: "
                      "an agent turn before approval could have altered the host-written answer store or "
                      "the host's record of the approval card (runs/plan-review.json). Inputs labelled as "
                      "the user's are as the host recorded them at the Approve click.\n")
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
    no receipts). after() harvests plans or validates a current-turn question artifact."""
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
    # Only the drafts are copied, never question requests, inputs, binaries,
    # approval keys or outputs. Every question belongs to one fresh worktree.
    for rel in ("runs/plan.json", "runs/data-inventory.json"):
        shutil.copy2(source / rel, wt / rel)
    return wt


def _planning_question_artifact(project: Path, t: Turn) -> dict | None:
    """Read one bounded question from the host-owned Turn's unique worktree.

    No project identity comes from agent-authored JSON. On POSIX, directory-fd
    traversal and O_NOFOLLOW reject swapped symlinks, including the runs folder.
    This does not add a writable location to intake, API or Claude turns.
    """
    if t.kind != "planning" or t.planning_worktree is None:
        return None
    import os
    import stat
    from contextlib import ExitStack

    project = Path(project).resolve()
    worktree = Path(t.planning_worktree).absolute()
    base = project / ".geoforge" / "planning"
    if worktree.parent != base or not re.fullmatch(r"[a-f0-9]{32}", worktree.name):
        raise ValueError("question fallback is not in this turn's project planning worktree")
    directories = [project / ".geoforge", base, worktree, worktree / "runs"]
    if any(directory.is_symlink() for directory in directories):
        raise ValueError("question fallback directories must not be symlinks")
    path = worktree / "runs" / "question-request.json"
    maximum = 64 * 1024
    try:
        with ExitStack() as stack:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            if os.open in os.supports_dir_fd:
                directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                directory_fd = os.open(project, directory_flags)
                stack.callback(os.close, directory_fd)
                for name in (".geoforge", "planning", worktree.name, "runs"):
                    directory_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                    stack.callback(os.close, directory_fd)
                fd = os.open("question-request.json", flags, dir_fd=directory_fd)
            else:
                # Windows lacks dir_fd traversal. Reject every symlink component
                # and non-regular leaf before opening; the provider turn has ended.
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError("question fallback must be a regular file, not a symlink")
                fd = os.open(path, flags | getattr(os, "O_BINARY", 0))
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("question fallback must be one regular, non-linked file")
            if info.st_size > maximum:
                raise ValueError("question fallback is larger than 64 KiB")
            with os.fdopen(os.dup(fd), "rb") as stream:
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError("question fallback is larger than 64 KiB")
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("question fallback could not be read safely; use a regular file in this worktree") from error
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("question fallback must contain valid UTF-8 JSON") from error
    if not isinstance(envelope, dict) or set(envelope) != {"turn_id", "question"}:
        raise ValueError("question fallback must contain only turn_id and question")
    if envelope["turn_id"] != worktree.name:
        raise ValueError("question fallback belongs to another planning turn; do not reuse old questions")
    if not isinstance(envelope["question"], dict):
        raise ValueError("question fallback question must be a JSON object")
    return envelope["question"]


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


_SOURCE_FIELDS = ("dataset_id", "delivery", "chosen_source", "decision", "local_paths", "ki_default")


def _unsourced(plan: dict, inv: dict) -> list[str]:
    """Bug #2 (live Mac test, 2026-09-29): 'resolved' means a source is known (plan.derive).
    An input marked resolved or ready that names none, and that no step produces, would show
    on the card as "prepared during the run" while nothing can actually supply it."""
    produced = {str(o) for st in plan.get("steps") or [] if isinstance(st, dict)
                for o in st.get("outputs") or []}
    bare = [str(it.get("id")) for it in inv.get("items") or [] if isinstance(it, dict)
            and it.get("status") in ("resolved", "ready") and str(it.get("id")) not in produced
            and not any(it.get(k) for k in _SOURCE_FIELDS)]
    return [f"{iid} is marked resolved but names no source. Set dataset_id and delivery for "
            "GeoForge Database data, chosen_source for a public source or method, local_paths for "
            "an existing file, the step that produces it, or the KI default with its evidence; "
            "if no source is known yet, mark it missing and ask the user." for iid in bare]


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


def plan_data_status(project: Path) -> dict | None:
    """Compatibility query; project_status owns all input-status interpretation."""
    from . import project_status
    return project_status.snapshot(project)["plan_data"]


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
        asked = setup_flow.request(project)
        waiting = bool(asked and asked.get("status") == "waiting")
        if not waiting and t.question_handoff_closed:
            return Result(message="This planning turn already asked a question. Continue with a new planning turn after answering it; its old drafts were not submitted.")
        if not waiting and t.planning_worktree is not None and t.kind == "planning":
            try:
                question = _planning_question_artifact(project, t)
                if question is not None:
                    asked = request_planning_question(project, question)
            except (ValueError, OSError) as error:
                return _planning_failure(project, t, [f"Question fallback rejected: {error}"],
                                         repair=t.provider_succeeded is True)
        if (asked and asked.get("status") == "waiting"
                and not str(asked.get("id", "")).startswith(APPROVAL_REQUEST_ID_PREFIX)):
            t.question_handoff_closed = True
            # Saved files are still drafts while a question is unanswered. Do not let
            # finalization (or a provider failure) replace the current user handoff.
            # Keep worktree drafts for the next turn without harvesting over the
            # original project's files; the normal validation/conflict checks remain.
            if t.planning_worktree:
                meta = project / ".geoforge" / "planning-last.json"
                meta.write_text(json.dumps({"draft_root": str(t.planning_worktree)}), encoding="utf-8")
            projectrun.report(project, {"status": "waiting_for_user", "summary": asked.get("title") or "Question for you",
                                        "blocker": asked}, source="flow")
            interrupted = t.provider_succeeded is False or getattr(fs, "provider_succeeded", None) is False
            return Result(message=(
                "The provider failed or was interrupted. The planning question still needs your answer; "
                "saved drafts are preserved and no approval review was issued."
            ) if interrupted else "")
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
        errs = (flow.plan.validate(pj, inv, list(fs.ki_roots), fs.ki_roots) + _unsourced(pj, inv)
                + plan_review.data_choice_errors(pj, inv))
        if errs:
            return _planning_failure(project, t, errs, repair=True)
        if fs.database_access_mode == "off":
            # DB gating: an old cached catalogue must not put Database data in a plan the
            # user cannot acquire (access off or not activated)
            from .acquire import ACQUIRABLE
            pinned = [str(it.get("id")) for it in inv.get("items") or [] if isinstance(it, dict)
                      and (it.get("dataset_id") or it.get("delivery") in ACQUIRABLE)]
            if pinned:
                return _planning_failure(project, t, [
                    f"GeoForge Database access is off or not activated, but {', '.join(pinned)} "
                    "pins a Database dataset. Use a public source, the user's own file or a KI "
                    "method instead, or tell the user that this input needs the Database."], repair=True)
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
        doc = plan_review.issue(project, fs, pj, inv, provider_note, turn_id=t.fingerprint_extra)
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
            # The agent's own summary is not the verdict (2026-10-01: it said "validation passed"
            # while the project was FAILED_VALIDATION and the chat showed nothing else).
            failing = "; ".join(
                f"{f.get('plan_step_id')} (`{_command_gist([Path(str(c)).name if '/' in str(c) else c for c in (f.get('command') or [])[1:]])}`): "
                + (", ".join(f.get("failed_checks")[:3]) or "no passing validation")
                for f in (ev.get("failed_steps") or [])[:5])
            return Result(message=(
                "**GeoForge verification:** failed. The latest run of each of these steps did not "
                f"pass its checks: {failing or 'see runs/evidence.json'}. Earlier passing attempts "
                "of a step no longer count once a later attempt fails; rerun the step to continue."))
        elif ev["receipts_verified"] and ev["validation"] == "passed":
            fs.move("run_finished")
            fs.move("validated", {"receipts_verified": True, "validation": "passed"})
            projectrun.set_stage(project, display_stage(flow, fs.state), "Completed — every step has a verified receipt")
            retried = ev.get("superseded_failures") or []
            if retried:
                # A passing retry supersedes a failure; the user still sees that it happened.
                runs = "; ".join(f"{f.get('plan_step_id')} (`{_command_gist(f.get('command'))}`)"
                                 for f in retried[:5])
                return Result(message=(
                    f"**Completed.** {len(retried)} earlier failed attempt{'s were' if len(retried) > 1 else ' was'} "
                    f"superseded by a passing retry: {runs}. They stay in the run history (runs/evidence.json)."))
        else:
            from .execution import stop_requested
            if stop_requested(project):
                # The user's Stop: resumable as it is, never rerun on its own.
                projectrun.set_stage(project, display_stage(flow, state),
                                     "Stopped by you — send a message to continue")
                projectrun.report(project, {"status": "idle", "summary":
                                  "Stopped by you — send a message to continue"}, source="flow")
                return Result()
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
            stale = ev.get("stale_steps") or []
            unvouched = ev.get("unreceipted_artifacts") or []
            if stale or (unvouched and not missing):
                why = []
                if stale:
                    why.append("these steps passed on input files that were rewritten afterwards; rerun them: "
                               + ", ".join(stale))
                if unvouched:
                    why.append("these files are not vouched for by a passing receipted run (left by a failed "
                               "attempt or written outside run-tool); regenerate or remove them: "
                               + ", ".join(f"`{f}`" for f in unvouched[:10]))
                return Result(message="**GeoForge verification:** not complete yet — " + "; ".join(why) + ".")
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
    # Questions are host-owned state, including in source builds. A planning
    # worktree must not gain write access to the real project's request file.
    question_launcher = _launcher_path()
    question = ({"request_user_action": f"{question_launcher} ask-question"}
                if question_launcher else {})
    if not getattr(_sys, "frozen", False):
        base = f"{_sys.executable} -m kiss_cli"
        if " " in _sys.executable:
            base = f"{shlex.quote(_sys.executable)} -m kiss_cli"
        return {**question, "run_tool": f"{base} run-tool", "fetch": f"{base} fetch",
                "obs_search": (str(database_launcher) if database_launcher else
                               f"{base} obs-search")}
    launcher = _launcher_path()
    if launcher is None:
        base = shlex.quote(_sys.executable)
    else:
        base = str(launcher)
    return {**question, "run_tool": f"{base} run-tool", "fetch": f"{base} fetch",
            "obs_search": (str(database_launcher) if database_launcher else
                           f"{base} obs-search")}


_QUESTION_LOCKS: dict[str, threading.Lock] = {}
_QUESTION_LOCKS_LOCK = threading.Lock()


def request_planning_question(project: Path, payload: dict) -> dict:
    """Create one host-owned choice card, never approve or execute anything.

    The authenticated Desktop bridge resolves the real project from the caller's
    cwd, including disposable planning worktrees. The standalone CLI uses the
    same validator. Repeating the same call is idempotent; a different question
    cannot replace one which the user has not answered.
    """
    project = Path(project).resolve()
    permitted = {"kind", "title", "message", "options", "allow_note", "resume_hint"}
    if not isinstance(payload, dict) or set(payload) - permitted:
        raise ValueError("a planning question accepts only kind, title, message, options, allow_note and resume_hint")
    if payload.get("kind", "choice") != "choice":
        raise ValueError("planning questions must be kind 'choice'; permissions and approvals are separate")
    for field, maximum in (("title", 160), ("message", 8000)):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{field} must be a nonempty string of at most {maximum} characters")
    if "allow_note" in payload and not isinstance(payload["allow_note"], bool):
        raise ValueError("allow_note must be a boolean")
    if "resume_hint" in payload and (not isinstance(payload["resume_hint"], str)
                                       or len(payload["resume_hint"]) > 4000):
        raise ValueError("resume_hint must be a string of at most 4000 characters")
    options = payload.get("options", [])
    if not isinstance(options, list):
        raise ValueError("options must be a list")
    seen = set()
    for index, option in enumerate(options):
        if not isinstance(option, dict) or set(option) - {"id", "label", "description", "response"}:
            raise ValueError("each option accepts only id, label, description and response")
        label = option.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 240:
            raise ValueError("each option needs a nonempty label of at most 240 characters")
        identifier = option.get("id", f"option-{index + 1}")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", identifier)
                or identifier != identifier.strip("-.")
                or identifier in seen or identifier in {"approve", "modify", "enable_https", "__custom_answer__"}
                or identifier.startswith("allow-kimi-")):
            raise ValueError("option ids must be unique choice ids, not permission or approval actions")
        seen.add(identifier)
        for field in ("description", "response"):
            if field in option and (not isinstance(option[field], str) or len(option[field]) > 2000):
                raise ValueError(f"option {field} must be a string of at most 2000 characters")
    normalized = {
        "kind": "choice", "title": " ".join(payload["title"].split()),
        "message": payload["message"].strip(), "options": setup_flow._request_options(options),
        "allow_note": payload.get("allow_note", True),
        "resume_hint": str(payload.get("resume_hint") or "").strip() or None,
    }
    # Never silently discard valid candidates through an older request normalizer.
    if len(normalized["options"]) != len(options):
        raise ValueError("the request renderer cannot preserve all options; no question was saved")
    # Bug #3: say which whole-product offers were never checked for clipping in this project
    from . import obs_subset
    shown = " ".join([normalized["message"]] + [f"{o.get('label', '')} {o.get('description', '')}"
                                                 for o in normalized["options"]])
    unchecked = obs_subset.unchecked_whole_products(project, shown)
    if unchecked:
        ids = ", ".join(unchecked)
        normalized["message"] += ("\n\nGeoForge 提示：本项目尚未检查 " + ids + " 能否按你的研究区裁剪，所列大小为整包大小；"
                                  "如考虑该选项，请让 Agent 先检查能否裁剪。"
                                  if re.search(r"[\u4e00-\u9fff]", shown) else
                                  "\n\nGeoForge note: clipping to your study area has not been checked in this "
                                  f"project for {ids}. Sizes shown for it are the whole product; if you are "
                                  "considering it, ask the agent to check whether it can be clipped.")
    with _QUESTION_LOCKS_LOCK:
        lock = _QUESTION_LOCKS.setdefault(str(project), threading.Lock())
    with lock:
        state = current_state(project)
        if state not in {"RESOLVING_KIS", "PLANNING", "REPLAN_REQUIRED"}:
            raise ValueError(f"planning question refused in {state or 'uninitialized project'}")
        request_path = project / setup_flow.REQUEST_FILE
        if request_path.is_symlink():
            raise ValueError("planning question request path must not be a symlink")
        current = setup_flow.request(project)
        if current and current.get("status") == "waiting":
            if all(current.get(key) == value for key, value in normalized.items()):
                return current
            raise ValueError("one question is already waiting; stop and wait for the user's answer")
        if current:
            setup_flow.clear_request(project)
        request = setup_flow.request_user(project, normalized)
        projectrun.report(project, {"status": "waiting_for_user", "summary": request["title"],
                                    "blocker": request},
                          source="agent")
        return request


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
    if provider_kind != "api":
        commands = wrapper_commands()
        if commands.get("request_user_action"):
            wrappers["request_user_action"] = commands["request_user_action"]
        if database_access_mode == "direct" and commands.get("obs_search"):
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
