#!/usr/bin/env python3
"""agent_spawn — env for spawning CLI agents. THE SOURCE OF TRUTH IS THE WEBAPP.

There were already TWO chat-side `_clean_env` implementations (`llm/cli_providers.py` — no
interpreter pinning — and `services/cli_process_manager.py` — with python_env pinning, the
memory-documented fix). This module must NOT become a third: it imports the webapp's
`cli_process_manager._clean_env` (same pattern as `codex_exec_common` importing the webapp's
`codex_cli` — one bin/argv policy, one env policy). The tiny local fallback below exists ONLY
for the case where the webapp tree is unreadable, is clearly marked, and must not grow.

Scope stays ENV ONLY (MERGE_PLAN V2): stream handling, sessions, providers, detached protocols
remain driver-side.
"""
from __future__ import annotations

import os
import sys

_HYDROCRAFT_WEB = "KISSPATH_ROOT/Hydrocraft/hydrocraft-web"
PYTHON_ENV = os.environ.get("HC_PYTHON_ENV", "KISSPATH_PYTHON_ENV")


def clean_env() -> dict:
    """The webapp's canonical cleaned+pinned env; local fallback only if it is unimportable."""
    try:
        if _HYDROCRAFT_WEB not in sys.path:
            sys.path.insert(0, _HYDROCRAFT_WEB)
        from backend.services.cli_process_manager import _clean_env  # canonical
        return _clean_env()
    except Exception:
        return _fallback_clean_env()


def _fallback_clean_env() -> dict:
    """MINIMAL mirror of the canonical policy — used ONLY when the webapp tree is unreadable.
    If you are editing behaviour here instead of in cli_process_manager._clean_env, stop."""
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    for key in ("ALL_PROXY", "all_proxy"):
        if "socks" in env.get(key, "").lower():
            env[key] = ""
    env_bin = f"{PYTHON_ENV}/bin"
    if os.path.isdir(env_bin):
        path = env.get("PATH", "")
        if not path.startswith(env_bin + os.pathsep):
            env["PATH"] = env_bin + os.pathsep + path
        env["VIRTUAL_ENV"] = PYTHON_ENV
        env.pop("PYTHONHOME", None)
    return env
