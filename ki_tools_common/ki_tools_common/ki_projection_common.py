"""ki_projection_common — shared rules for the KI projection generators AND their gate.

Born from the codex+kimi co-review (2026-08-15): the generators and the gate each had private
copies of "what is an output's name", "which files count as tools", "how to read triplets" — and
every private copy disagreed with another. One rule each, imported by all sides.
"""
import sys
from pathlib import Path
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")

class SourceShapeError(RuntimeError):
    """A source row/section has an unexpected shape. FAIL CLOSED — never project around it."""

def split_reason_items(rows):
    """A list may carry {_reason:/_note:} items documenting WHY entries are absent (GEOPHIRES,
    SHEMAT-Suite). Honest emptiness, list form. Returns (real_rows, note_or_None)."""
    real=[]; note=None
    for e in rows or []:
        if isinstance(e,dict) and set(e) <= {"_reason","_note"}:
            note=e.get("_reason") or e.get("_note")
        else:
            real.append(e)
    return real, note

def entry_name(e):
    """THE output/input identity key: `name` or `var`, both sides of every comparison."""
    if not isinstance(e, dict):
        raise SourceShapeError(f"entry is {type(e).__name__}, expected mapping: {str(e)[:80]}")
    n = e.get("name") or e.get("var")
    if not n:
        raise SourceShapeError(f"entry has neither name nor var: {str(e)[:100]}")
    return str(n)

def observability(o):
    ob = o.get("observability")
    if ob is None: return {}
    if not isinstance(ob, dict):
        raise SourceShapeError(f"observability is {type(ob).__name__} for {o.get('var') or o.get('name')}")
    return ob

_TOOL_EXCLUDE = ("__pycache__", "_rejected", ".kdt_")     # kimi #13: was "(.kdt_", could never match

def tool_files(ki: Path):
    """Every tool the KI carries, BOTH layouts, rejects/caches excluded. Used by generator AND gate."""
    out = set()
    roots = ([ki / "tools"] if (ki / "tools").is_dir() else []) +             [d for d in ki.glob("s[0-9]*_*") if d.is_dir()]
    for r in roots:
        for q in r.rglob("*.py"):
            if q.name.startswith("__"): continue
            if any(x in str(q) for x in _TOOL_EXCLUDE): continue
            out.add(str(q.relative_to(ki)))
    return sorted(out)

def read_triplet_entries(ki: Path):
    """Via the ONE tolerant reader (candidate_overlay) — accepts list / {triplets} / {diagnostic_triplets}."""
    import yaml
    from candidate_overlay import read_triplets
    p = ki / "diagnostics" / "triplets.yaml"
    if not p.is_file(): return []
    entries, status = read_triplets(yaml.safe_load(p.read_text()))
    if status == "unreadable":
        raise SourceShapeError(f"{p} is unreadable")
    return entries
