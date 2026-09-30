"""Pin the shared Flow package against the last server sync (issue #7).

Desktop and the web server ship the same ki_tools_common.flow. Since the 2026-09-21 sync
(server = reference) the Desktop has changed some files. Repeating that sync would silently
undo them, and nothing warned, because the parity tests skip when the server tree is absent.
flow/UPSTREAM.json records every file's hash at that sync and, for each file that differs
since, why it differs and what to carry to the server. That list is the next sync's checklist.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

FLOW = Path(__file__).resolve().parents[2] / "ki_tools_common" / "flow"
SERVER_FLOW = Path("/mnt/disk1/Hydrocraft_server/models/ki_tools_common/ki_tools_common/flow")
PIN_FILE = "UPSTREAM.json"


def _pin() -> dict:
    return json.loads((FLOW / PIN_FILE).read_text(encoding="utf-8"))


def _files(root: Path) -> dict[str, str]:
    # Hash the committed LF text: a Windows checkout with core.autocrlf writes CRLF, which
    # is neither a change to carry upstream nor one a sync would undo.
    return {p.relative_to(root).as_posix():
            hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.name != PIN_FILE}


def _drifted(root: Path, baseline: dict) -> list[str]:
    now = _files(root)
    return sorted({f for f, h in now.items() if baseline.get(f) != h} | (set(baseline) - set(now)))


def test_every_file_that_differs_from_the_last_sync_is_on_the_checklist():
    pin = _pin()
    unrecorded = [f for f in _drifted(FLOW, pin["baseline"]) if f not in pin["pending"]]
    assert not unrecorded, (f"changed since the last server sync but not listed in flow/{PIN_FILE} "
                            f"'pending' (say why, or the next sync undoes it): {unrecorded}")


def test_the_checklist_has_no_stale_entries():
    pin = _pin()
    stale = sorted(set(pin["pending"]) - set(_drifted(FLOW, pin["baseline"])))
    assert not stale, f"back in line with the server copy; remove from 'pending': {stale}"


def test_every_checklist_entry_says_why():
    short = [f for f, why in _pin()["pending"].items() if not isinstance(why, str) or len(why) < 40]
    assert not short, f"each pending entry needs its reason and what to carry upstream: {short}"


@pytest.mark.skipif(not SERVER_FLOW.is_dir(), reason="server tree not present")
def test_the_server_copy_has_not_moved_since_the_pinned_sync():
    moved = _drifted(SERVER_FLOW, _pin()["baseline"])
    assert not moved, ("the server copy changed since the pinned sync; reconcile both sides and "
                       f"re-pin the baseline before the next sync: {moved}")
