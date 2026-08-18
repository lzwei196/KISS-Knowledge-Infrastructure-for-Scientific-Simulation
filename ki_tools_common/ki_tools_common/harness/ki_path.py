#!/usr/bin/env python3
"""ki_path — resolve a model's KI directory from the DATABASE (never fabricate from spelling).

    python3 ki_path.py HBV
    python3 ki_path.py "SWAT+" --json

WHY: 25 of 450 models have a KI folder whose name differs from the model id (SWAT+ -> SWAT_Plus,
HEC-RAS -> HEC_RAS, WAVEWATCH III -> WAVEWATCH_III ...). Building `models/<Model>/...` from the id
fabricates a wrong path for those — the bug class resolve_ki_path() fixed loop-side. This tool is
the chat-side equivalent: DB `models.ki_path` FIRST, normalized-id match second, NEVER a guess.

Exit 0: prints the absolute KI dir (or JSON with --json).
Exit 2: model not found / ki_path NULL / dir missing / no SKILL.md — with a precise message.
A loud refusal beats a fabricated path (35 models have NULL ki_path by design).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

DB = "KISSPATH_ROOT/hydrocraft.db"


def _norm(s: str) -> str:
    return re.sub(r"[-_/+ ]+", " ", str(s or "")).strip().lower()


def resolve(model_id: str) -> dict:
    """{'model_id', 'ki_path', 'skill_md', 'warnings': [...]} or raises LookupError."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute("SELECT id, ki_path FROM models WHERE id=?", (model_id,)).fetchone()
    if row is None:
        norm = _norm(model_id)
        hits = [r for r in con.execute("SELECT id, ki_path FROM models")
                if _norm(r[0]) == norm]
        if len(hits) > 1:
            raise LookupError(f"model {model_id!r} is ambiguous after normalization: "
                              f"{[h[0] for h in hits]} — use the exact id")
        if not hits:
            # second fallback (same authority as loop resolve_ki_path): the KI FOLDER name —
            # users legitimately type the folder spelling (SWAT_Plus for SWAT+)
            hits = [r for r in con.execute(
                        "SELECT id, ki_path FROM models WHERE ki_path IS NOT NULL")
                    if norm in {_norm(p) for p in re.split(r"[\\/]", r[1])[-2:]}]
        if len(hits) == 1:
            row = hits[0]
        elif len(hits) > 1:
            raise LookupError(f"model {model_id!r} matches several KI folders: "
                              f"{[h[0] for h in hits]} — use the exact id")
        else:
            raise LookupError(f"model {model_id!r} not in the models table — check the id "
                              f"(this tool never guesses a folder from spelling)")
    mid, kp = row
    if not kp:
        raise LookupError(f"model {mid!r} has NO ki_path in the DB (35 models are unregistered "
                          f"by design) — do NOT fabricate models/{mid}/...; report this as a gap")
    if not os.path.isdir(kp):
        raise LookupError(f"model {mid!r}: DB ki_path does not exist on disk: {kp} — "
                          f"the registry has drifted; report, do not guess")
    warnings = []
    skill = os.path.join(kp, "SKILL.md")
    if not os.path.isfile(skill):
        warnings.append(f"no SKILL.md at {kp} (thin/unbuilt KI — protocol missing)")
    return {"model_id": mid, "ki_path": kp,
            "skill_md": skill if os.path.isfile(skill) else None, "warnings": warnings}


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    try:
        r = resolve(args[0])
    except LookupError as e:
        print(f"KI_PATH ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    if as_json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(r["ki_path"])
        for w in r["warnings"]:
            print(f"WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
