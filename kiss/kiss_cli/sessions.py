"""Chat sessions: the primary object of the app.

The redesign follows the shape every agent product converged on — a list of
conversations on the left, one conversation in the middle — because the user's
unit of work is "the thing I am trying to do", not "the package I clicked".
The KI library becomes a place you visit to set models up, not the home screen.

Each session carries its own model selection. Empty selection means AUTO: the
agent is handed the catalogue (name + one-line description for all 127 — the
frontmatter written earlier exists precisely so this list can be generated
rather than authored) and told to choose, announce the choice, and then follow
the chosen KI's own contract. The transcript is replayed into every turn
because the CLI driver is one-shot: without it each message would start from
amnesia.

Storage is one JSON file per session under the workroot — greppable,
hand-fixable, no database to corrupt.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


def _dir(workroot: Path) -> Path:
    d = Path(workroot) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(workroot: Path, sid: str) -> Path:
    safe = "".join(c for c in sid if c.isalnum() or c == "-")
    return _dir(workroot) / f"{safe}.json"


def create(workroot: Path, models: list[str] | None = None,
           provider: str = "") -> dict:
    s = {"id": uuid.uuid4().hex[:12], "title": "New session",
         "created": time.time(), "models": models or [], "provider": provider,
         "messages": []}
    save(workroot, s)
    return s


def load(workroot: Path, sid: str) -> dict | None:
    p = _path(workroot, sid)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(workroot: Path, s: dict) -> None:
    _path(workroot, s["id"]).write_text(json.dumps(s, indent=1), encoding="utf-8")


def delete(workroot: Path, sid: str) -> bool:
    p = _path(workroot, sid)
    if p.exists():
        p.unlink()
        return True
    return False


def list_all(workroot: Path) -> list[dict]:
    out = []
    for p in _dir(workroot).glob("*.json"):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": s["id"], "title": s.get("title", "?"),
                        "created": s.get("created", 0),
                        "models": s.get("models", []),
                        "n": len(s.get("messages", []))})
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(out, key=lambda x: -x["created"])


def transcript(s: dict, limit: int = 20) -> str:
    """Prior turns, replayed for the one-shot CLI driver."""
    msgs = s.get("messages", [])[-limit:]
    if not msgs:
        return ""
    lines = ["[CONVERSATION SO FAR — continue it, do not restart]"]
    for m in msgs:
        who = "USER" if m["role"] == "user" else "YOU"
        lines.append(f"{who}: {m['text'][:2000]}")
    return "\n".join(lines) + "\n"


def catalogue_block(catalog) -> str:
    """The auto-routing index: every KI in one screenful.

    Generated from dag.yaml identity — the same source the SKILL.md
    frontmatter descriptions come from — so it never drifts from the packages.
    """
    lines = [
        "[KI CATALOGUE — 127 models available on this machine]",
        "Format: name — what it is. To USE one: read <models_root>/<name>/SKILL.md",
        "FIRST and follow it exactly; its tools are run by absolute path.",
        "",
    ]
    for ki in catalog:
        ref = (ki.meta or {}).get("reference") or (ki.meta or {}).get("model_id") or ki.name
        lines.append(f"  {ki.name} — {str(ref)[:110]}")
    return "\n".join(lines)


AUTO_RULES = """[MODEL CHOICE IS YOURS]
No model was pre-selected for this session. From the catalogue above:
1. CHOOSE the most suitable model(s) for the task — prefer one unless the task
   genuinely needs a comparison.
2. ANNOUNCE the choice and why, in one sentence, before doing anything else.
3. THEN read the chosen KI's SKILL.md and follow it. Do not improvise a
   pipeline the KI already defines; do not substitute simplified formulas for
   the real model.
If the task needs no model at all (a general question), say so and answer.
"""
