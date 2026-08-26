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


def _normalise(raw: dict | None, fallback: dict | None = None) -> dict:
    base = dict(fallback or _new())
    raw = raw if isinstance(raw, dict) else {}
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
        }
    else:
        base.pop("blocker", None)
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
            state = _normalise(agent, state)
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


def report(project: Path, payload: dict, *, source: str = "agent") -> dict:
    state = load(project)
    update = dict(payload or {})
    if update.get("status") != "waiting_for_user" and "blocker" not in update:
        state.pop("blocker", None)
    update["updated_at"] = time.time()
    state = _normalise(update, state)
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
"""
