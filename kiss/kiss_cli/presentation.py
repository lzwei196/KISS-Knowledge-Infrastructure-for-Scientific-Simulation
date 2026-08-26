"""Provider-neutral chat presentation events.

Agent CLIs and direct APIs expose work in incompatible wire formats. Chat
should not depend on those formats, so the backend reduces tool activity to a
small marker which the frontend can render consistently.
"""

from __future__ import annotations

import re


def activity_marker(name: str) -> str:
    """Return a safe marker for one internal tool step."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", str(name or "tool"))[:100] or "tool"
    return f"\n[[GEOF_TOOL:{safe}]]\n"
