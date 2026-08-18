"""Persistent app settings: API keys, default provider, general options.

The gap this fills was found by using the app as a user: with no key in the
environment, the API providers simply did not exist — no way to see them, no
way to add a key, no explanation. A GUI cannot ask people to export environment
variables; it needs a settings screen whose values persist.

Keys are stored in the platform data directory with 0600 permissions and
loaded into the process environment at startup (fill-gaps only, so a real
environment variable still wins). Persisted keys are returned to the UI only
as a masked tail — the full value never travels back out.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .firstrun import data_dir

KEY_NAMES = ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
             "OPENAI_API_KEY", "OPENROUTER_API_KEY")


def _path() -> Path:
    return data_dir() / "settings.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def apply_to_env() -> None:
    """Adopt saved keys into the environment. A real env var always wins."""
    keys = load().get("api_keys") or {}
    for k, v in keys.items():
        if k in KEY_NAMES and v and not os.environ.get(k):
            os.environ[k] = v


def masked() -> dict:
    """Settings for the UI: keys reduced to a recognisable tail."""
    s = load()
    out = {"default_provider": s.get("default_provider", ""),
           "api_keys": {}}
    for k in KEY_NAMES:
        v = (s.get("api_keys") or {}).get(k) or os.environ.get(k) or ""
        out["api_keys"][k] = (f"…{v[-4:]}" if v else "")
    return out


def update(payload: dict) -> None:
    """Apply a settings change from the UI.

    A key value that looks like our own mask ("…abcd") means unchanged; an
    empty string means delete; anything else is the new key.
    """
    s = load()
    s.setdefault("api_keys", {})
    for k, v in (payload.get("api_keys") or {}).items():
        if k not in KEY_NAMES or (v or "").startswith("…"):
            continue
        if v:
            s["api_keys"][k] = v
            os.environ[k] = v
        else:
            s["api_keys"].pop(k, None)
            os.environ.pop(k, None)
    if "default_provider" in payload:
        s["default_provider"] = payload["default_provider"]
    save(s)
