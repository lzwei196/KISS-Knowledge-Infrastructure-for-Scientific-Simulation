"""Small, durable state for the scientific work happening in one chat.

This is deliberately *not* a project-specific or adaptive KI harness.  The
agent still uses the ordinary, reusable KI.  A ProjectRun only records what the
agent is doing with that KI so the desktop can show useful progress without
turning ``dag.yaml`` into a form for the user.

Native agent CLIs can write ``runs/project-agent-status.json``.  Direct API
agents call the typed ``report_project_progress`` tool.  Both paths are
normalised here and produce the same state for the frontend.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


STATE_FILE = "project-run.json"
EVENTS_FILE = "project-events.jsonl"
AGENT_FILE = "project-agent-status.json"

STAGES = (
    "understanding", "choosing_ki", "software", "researching",
    "preparing", "validating", "running", "results",
)
STATUSES = ("idle", "working", "waiting_for_user", "complete", "failed")

STAGE_LABELS = {
    "understanding": "Understanding the request",
    "choosing_ki": "Choosing the scientific model",
    "software": "Checking scientific software",
    "researching": "Finding suitable data",
    "preparing": "Preparing model inputs",
    "validating": "Validating the project",
    "running": "Running the scientific model",
    "results": "Preparing results",
}


def _runs(project: Path) -> Path:
    path = Path(project) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(project: Path, name: str) -> Path:
    return _runs(project) / name


def _short(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _blocker_rows(value) -> list[dict]:
    """The N manual-download rows of an acquisition card (link, code, path per dataset)."""
    if not isinstance(value, list):
        return []
    out = []
    for raw in value[:12]:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")[:2000]
        out.append({
            "item_id": _short(raw.get("item_id"), 100), "dataset_id": _short(raw.get("dataset_id"), 200),
            "name": _short(raw.get("name"), 200), "size": raw.get("size") if isinstance(raw.get("size"), int) else None,
            "url": url if url.startswith(("https://", "http://")) else None,
            "code": _short(raw.get("code"), 40) or None,
            "path_in_share": str(raw.get("path_in_share") or "").strip()[:500] or None,
            "expected_path": str(raw.get("expected_path") or "").strip()[:1000],
        })
    return out


def _blocker_options(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for index, item in enumerate(value[:8]):
        raw = {"label": item} if isinstance(item, str) else item
        if not isinstance(raw, dict):
            continue
        label = _short(raw.get("label"), 240)
        if not label:
            continue
        out.append({
            "id": _short(raw.get("id"), 80) or f"option-{index + 1}",
            "label": label,
            "description": str(raw.get("description") or "").strip()[:2000],
            "response": str(raw.get("response") or label).strip()[:2000],
        })
    return out


def _intake(value) -> dict | None:
    """Normalise the agent's task-understanding handoff.

    This is conversation state, not authority: the flow still validates every KI name and
    owns the transition into planning.  Keeping the semantic fields here means the planner
    does not have to reconstruct the user's study from a title or a regex on every turn.
    """
    if not isinstance(value, dict):
        return None
    out = {
        "ready_for_planning": value.get("ready_for_planning") is True,
        "understanding": _short(value.get("understanding"), 1000),
        "study_area": _short(value.get("study_area"), 500),
        "period": _short(value.get("period"), 300),
        "process": _short(value.get("process"), 500),
        "scenario": _short(value.get("scenario"), 500),
        "requested_outputs": [
            _short(item, 160) for item in (value.get("requested_outputs") or [])
            if _short(item, 160)
        ][:20] if isinstance(value.get("requested_outputs", []), list) else [],
        "missing": [
            _short(item, 300) for item in (value.get("missing") or [])
            if _short(item, 300)
        ][:20] if isinstance(value.get("missing", []), list) else [],
    }
    return out


def _new(goal: str = "", selected_kis: list[str] | None = None) -> dict:
    now = time.time()
    return {
        "version": 1,
        "id": uuid.uuid4().hex[:12],
        "goal": _short(goal, 1000),
        "selected_kis": list(dict.fromkeys(selected_kis or []))[:20],
        "status": "idle",
        "stage": "understanding",
        "summary": "Ready to begin",
        "created_at": now,
        "updated_at": now,
    }


def _normalise(raw: dict | None, fallback: dict | None = None, *,
               allow_stage: bool = True) -> dict:
    """allow_stage=False (plan v3 B5): an AGENT report may change status/summary/goal/
    selected_kis/blocker but never the stage — the flow (flowgate) owns the stage. The
    desktop passes allow_stage=False for every agent-sourced update once a project has a
    flow state file; app-sourced updates keep the old behaviour."""
    base = dict(fallback or _new())
    raw = raw if isinstance(raw, dict) else {}
    if not allow_stage:
        raw = {k: v for k, v in raw.items() if k != "stage"}
    stage = str(raw.get("stage") or base.get("stage") or "understanding")
    status = str(raw.get("status") or base.get("status") or "idle")
    if stage not in STAGES:
        stage = base.get("stage") if base.get("stage") in STAGES else "understanding"
    if status not in STATUSES:
        status = base.get("status") if base.get("status") in STATUSES else "idle"
    chosen = raw.get("selected_kis", base.get("selected_kis", []))
    if not isinstance(chosen, list):
        chosen = []
    base.update({
        "version": 1,
        "id": _short(raw.get("id") or base.get("id") or uuid.uuid4().hex[:12], 32),
        "goal": _short(raw.get("goal", base.get("goal", "")), 1000),
        "selected_kis": list(dict.fromkeys(
            _short(name, 120) for name in chosen if _short(name, 120)))[:20],
        "status": status,
        "stage": stage,
        "summary": _short(raw.get("summary", base.get("summary", "")), 500),
        "updated_at": _number(raw.get("updated_at"), time.time()),
    })
    base["created_at"] = _number(raw.get("created_at", base.get("created_at")), time.time())
    blocker = raw.get("blocker", base.get("blocker"))
    if isinstance(blocker, dict):
        url = str(blocker.get("url") or "")[:2000]
        base["blocker"] = {
            "id": _short(blocker.get("id"), 100) or "request",
            "status": "waiting",
            "kind": _short(blocker.get("kind"), 40) or "other",
            "title": _short(blocker.get("title"), 160) or "Help needed",
            "message": str(blocker.get("message") or "").strip()[:8000],
            "url": url if url.startswith(("https://", "http://")) else None,
            "expected_path": str(blocker.get("expected_path") or "").strip()[:1000] or None,
            "command": str(blocker.get("command") or "").strip()[:2000] or None,
            "resume_hint": str(blocker.get("resume_hint") or "").strip()[:4000] or None,
            "options": _blocker_options(blocker.get("options")),
            "allow_note": bool(blocker.get("allow_note", True)),
            "rows": _blocker_rows(blocker.get("rows")),
        }
    else:
        base.pop("blocker", None)
    intake = _intake(raw.get("intake", base.get("intake")))
    if intake is not None:
        base["intake"] = intake
    else:
        base.pop("intake", None)
    return base


def _write(project: Path, state: dict) -> dict:
    path = _path(project, STATE_FILE)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return state


def _event(project: Path, kind: str, state: dict) -> None:
    item = {
        "ts": time.time(), "kind": kind, "run_id": state.get("id"),
        "status": state.get("status"), "stage": state.get("stage"),
        "summary": state.get("summary"),
    }
    with _path(project, EVENTS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def load(project: Path, *, goal: str = "", selected_kis: list[str] | None = None) -> dict:
    """Load the current run and safely adopt a native agent's latest report."""
    path = _path(project, STATE_FILE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = None
    valid_state = isinstance(raw, dict)
    state = _normalise(raw, _new(goal, selected_kis))
    agent_path = _path(project, AGENT_FILE)
    try:
        agent = json.loads(agent_path.read_text(encoding="utf-8"))
        if isinstance(agent, dict) and agent_path.stat().st_mtime >= path.stat().st_mtime:
            state = _normalise(agent, state, allow_stage=not flow_owned(project))
            state["updated_at"] = agent_path.stat().st_mtime
            _write(project, state)
            _event(project, "agent_progress", state)
    except (OSError, json.JSONDecodeError):
        pass
    return state if valid_state else _write(project, state)


def begin_turn(project: Path, message: str, selected_kis: list[str] | None = None) -> dict:
    state = load(project, goal=message, selected_kis=selected_kis)
    if not state.get("goal"):
        state["goal"] = _short(message, 1000)
    if selected_kis:
        state["selected_kis"] = list(dict.fromkeys(selected_kis))[:20]
    state.update({
        "status": "working",
        "summary": "Understanding your request" if state["stage"] == "understanding"
        else STAGE_LABELS[state["stage"]],
        "updated_at": time.time(),
    })
    state.pop("blocker", None)
    _write(project, state)
    _event(project, "turn_started", state)
    return state


FLOW_STATE_FILE = "flow-state.json"     # written by ki_tools_common.flow (flowgate), never by agents
FLOW_SOURCES = ("flow",)                # the only report() sources allowed to move the stage


def flow_owned(project: Path) -> bool:
    """True once the project has a flow state file: from then on the stage is the flow's."""
    return _path(project, FLOW_STATE_FILE).is_file()


def set_stage(project: Path, stage: str, summary: str = "", *, source: str = "flow") -> dict:
    """The flow's way to move the display stage (maps a flow state to the 8 UI labels)."""
    if source not in FLOW_SOURCES:
        raise ValueError("only the flow may set the stage")
    state = load(project)
    if stage in STAGES:
        state["stage"] = stage
    if summary:
        state["summary"] = _short(summary, 500)
    state["updated_at"] = time.time()
    _write(project, state)
    _event(project, f"stage:{source}", state)
    return state


def report(project: Path, payload: dict, *, source: str = "agent") -> dict:
    state = load(project)
    update = dict(payload or {})
    if update.get("status") != "waiting_for_user" and "blocker" not in update:
        state.pop("blocker", None)
    update["updated_at"] = time.time()
    state = _normalise(update, state,
                       allow_stage=(source in FLOW_SOURCES) or not flow_owned(project))
    _write(project, state)
    _event(project, f"progress:{source}", state)
    return state


def select_kis(project: Path, names: list[str]) -> dict:
    state = load(project)
    state["selected_kis"] = list(dict.fromkeys(str(n) for n in names if n))[:20]
    state["updated_at"] = time.time()
    _write(project, state)
    _event(project, "ki_selection", state)
    return state


def finish_turn(project: Path, *, request: dict | None = None,
                failed: str | None = None) -> dict:
    state = load(project)
    if request and request.get("status") == "waiting":
        state.update({
            "status": "waiting_for_user",
            "summary": _short(request.get("title") or "One thing needs you", 500),
            "blocker": request,
        })
    elif failed:
        state.update({"status": "failed", "summary": _short(failed, 500)})
    elif state.get("status") == "working":
        # A completed chat turn is not the same as a completed scientific run.
        # Keep the last truthful stage and wait for the next user/agent action.
        state["status"] = "idle"
        state["summary"] = "Ready to continue"
    state["updated_at"] = time.time()
    state = _normalise(state)
    _write(project, state)
    _event(project, "turn_finished", state)
    return state


def prompt_block(project: Path) -> str:
    status_path = _path(project, AGENT_FILE)
    request_path = Path(project) / "setup-request.json"
    if flow_owned(project):
        return f"""[PROJECT PROGRESS — REPORT WORK; GEOFORGE TRACKS THE STAGE]
You are using the reusable general KI directly. GeoForge moves the project stage itself
from the plan, the approval and the signed receipts — do NOT report a stage.
At meaningful transitions, call `report_project_progress` when that tool is available
(status + summary only). Otherwise write `{status_path}` as JSON with:
  {{"status":"working|waiting_for_user|complete|failed",
    "summary":"one short, plain-language description",
    "selected_kis":["KI name"]}}
If blocked by a download, login, licence, permission, or high-impact scientific choice,
write `{request_path}` using the request_user_action fields (status=waiting, kind, title,
message, optional url, `options` with id/label/description/response). One grouped action.
During the initial task-understanding turn also report `intake` with
ready_for_planning, understanding, study_area, period, process, scenario,
requested_outputs and missing. Selecting a KI does not by itself mean the study is ready
to plan.
"""
    return f"""[PROJECT PROGRESS — REPORT WORK, DO NOT INVENT A NEW KI]
You are using the reusable general KI directly. There is no adaptive or
project-specific KI harness in this version of GeoForge; never claim one was
created. The app shows the user a small, truthful project status instead of the
KI's internal checklist.

At meaningful transitions, call `report_project_progress` when that tool is
available. Otherwise write `{status_path}` as JSON with:
  {{"stage":"choosing_ki|software|researching|preparing|validating|running|results",
    "status":"working|waiting_for_user|complete|failed",
    "goal":"include only when the user materially changes the scientific case",
    "summary":"one short, plain-language description",
    "selected_kis":["KI name"]}}
Do not report a later stage until you actually reached it. If blocked by a
download, login, licence, permission, or high-impact scientific choice, also
write `{request_path}` using the request_user_action fields: status=waiting,
kind, title, message, optional url, and `options` when there are concrete
alternatives. Each option has id, label, description, and response. Ask for one
grouped action only; GeoForge renders the options as a picker.

Memory rule: preserve the existing goal for ordinary follow-ups such as
"continue", "retry", or "plot that". If the user changes the site, model,
period, scenario, or requested experiment enough to make it a different run,
report the new goal explicitly so the status panel and project memory do not
describe the previous case.
For initial task understanding, include an `intake` object with
ready_for_planning, understanding, study_area, period, process, scenario,
requested_outputs and missing. Set ready_for_planning=false while a critical scientific
question is unanswered; choosing a model alone is not readiness.
"""
