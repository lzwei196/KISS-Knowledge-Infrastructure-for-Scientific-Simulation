#!/usr/bin/env python3
"""ki_attention — the RUN-TIME ATTENTION digest for a model KI (KI_HARNESS_SPEC Appendix C.1).

    python3 ki_attention.py HBV
    python3 ki_attention.py HBV --var Q
    python3 ki_attention.py "SWAT+" --budget 4000

Prints, budget-capped and source-tagged, the details an agent must PAY ATTENTION TO while running:
  1. WHAT THIS MODEL PRODUCES — per output (target var, else rank<=3): unit, rank, admissible
     comparison shapes + metric families, and the dag's own CAVEATS (spin-up, unit conversion,
     alignment traps). Source: dag.yaml.
  2. OUTPUT FORMAT — key facts from docs/format_spec.yaml.
  3. PREPARATION — one-liners from docs/input_preparation.md / filename_grammar.md /
     variables_and_units.md when present.
  4. KNOWN FAILURES — top triplets matched to the target var (else the first N). Source:
     diagnostics/triplets.yaml.
  5. OPERATIONAL RULES — detached long jobs, no duplicate launches, verify outputs per stage.
  6. MISSING — every absent artifact, including files SKILL.md references that do not exist
     (VERIFIED POINTERS: the 162-class index-vs-disk gaps).

Read-only. Never guesses: every line carries `[source-file]`; absent artifact => MISSING line.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

try:
    from .ki_path import resolve
except ImportError:  # CLI execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ki_path import resolve

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

OP_RULES = """[operational]
- LONG JOBS: launch detached (setsid nohup ... &) and WAIT in the same turn; ending the turn kills the run.
- NEVER launch the same generation job twice concurrently (duplicate writers corrupt outputs).
- After each stage: verify the output exists and values are plausible BEFORE the next stage.
- Use a UNIQUE output dir per run; check for prior outputs before re-running (no duplicates).
- Bare `python` must be the project env: KISSPATH_PYTHON_ENV/bin/python."""


def _safe_yaml(p: Path):
    if yaml is None or not p.is_file():
        return None
    try:
        return yaml.safe_load(p.read_text(errors="ignore"))
    except Exception:
        return "PARSE_ERROR"


def _outputs_digest(ki: Path, target_var: str | None, lines: list, missing: list):
    dag = _safe_yaml(ki / "dag.yaml")
    if dag is None:
        missing.append("dag.yaml — no output contract: units/admissible metrics unknown")
        return
    if dag == "PARSE_ERROR" or not isinstance(dag, dict):
        missing.append("dag.yaml PRESENT BUT UNPARSEABLE — treat outputs as unverified")
        return
    outs = dag.get("outputs") or []
    if isinstance(outs, dict):
        outs = list(outs.values())
    picked = []
    for o in outs:
        if not isinstance(o, dict) or o.get("var") is None:
            continue
        if target_var:
            if str(o["var"]) == target_var or str(o["var"]).split("(")[0].strip() == target_var:
                picked = [o]
                break
        else:
            r = o.get("validation_rank")
            if isinstance(r, int) and r <= 3:
                picked.append(o)
    if target_var and not picked:
        missing.append(f"dag.yaml has no output named {target_var!r} — target/dag drift; "
                       f"regenerate L1 or fix the caller")
        return
    lines.append("WHAT THIS MODEL PRODUCES  [dag.yaml]")
    for o in sorted(picked, key=lambda x: (x.get("validation_rank") or 99)):
        lines.append(f"- {o.get('var')}  (unit: {o.get('unit') or '?'}, rank {o.get('validation_rank')})")
        d = str(o.get("description") or "").strip()
        if d:
            lines.append(f"    {d[:180]}")
        for s in ((o.get("observability") or {}).get("comparable_obs_shapes") or []):
            fams = ",".join(s.get("metric_families") or [])
            lines.append(f"    admissible: {s.get('obs_shape')} -> [{fams}]"
                         + (f" (determining: {s.get('determining_metric')})" if s.get('determining_metric') else ""))
            for c in (s.get("caveats") or [])[:4]:
                lines.append(f"    ! {str(c)[:200]}")


def _format_digest(ki: Path, lines: list, missing: list, budget=1200):
    p = ki / "docs" / "format_spec.yaml"
    d = _safe_yaml(p)
    if d is None:
        missing.append("docs/format_spec.yaml — output format unverified; read the model docs before parsing")
        return
    if d == "PARSE_ERROR":
        missing.append("docs/format_spec.yaml PRESENT BUT UNPARSEABLE")
        return
    txt = yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=100)
    lines.append("OUTPUT FORMAT  [docs/format_spec.yaml]" + ("" if len(txt) <= budget else "  (truncated — open the file)"))
    lines.append(txt[:budget].rstrip())


def _prep_digest(ki: Path, lines: list):
    hits = []
    for name in ("input_preparation.md", "filename_grammar.md", "variables_and_units.md"):
        p = ki / "docs" / name
        if p.is_file():
            first = next((l.strip() for l in p.read_text(errors="ignore").splitlines()
                          if l.strip() and not l.startswith("#")), "")
            hits.append(f"- docs/{name}: {first[:140]}  -> READ IT before preparing inputs")
    if hits:
        lines.append("PREPARATION  [docs/]")
        lines.extend(hits)


def _triplets_digest(ki: Path, target_var: str | None, lines: list, missing: list, top=3):
    p = ki / "diagnostics" / "triplets.yaml"
    doc = _safe_yaml(p)
    if doc is None:
        alt = ki / "diagnostics" / "triplets.md"
        missing.append("diagnostics/triplets.yaml missing"
                       + (" (triplets.md exists — grep that instead)" if alt.is_file() else ""))
        return
    if doc == "PARSE_ERROR":
        missing.append("diagnostics/triplets.yaml PRESENT BUT UNPARSEABLE")
        return
    trips = doc if isinstance(doc, list) else (doc.get("triplets") or doc.get("diagnostic_triplets") or [])
    trips = [t for t in trips if isinstance(t, dict)]
    if not trips:
        missing.append("diagnostics/triplets.yaml has no entries")
        return
    scored = []
    tv = (target_var or "").lower()
    for t in trips:
        blob = " ".join(str(t.get(k) or "") for k in ("symptom", "diagnosis", "remedy")).lower()
        score = (2 if tv and tv in blob else 0) + (1 if any(w in blob for w in ("unit", "format", "align", "spin")) else 0)
        scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    def _flat(v):
        # triplet fields are strings in most KIs but dicts in some (description/action/…)
        if isinstance(v, dict):
            return str(v.get("description") or v.get("action") or v.get("error_pattern")
                       or next(iter(v.values()), ""))
        return str(v or "")
    lines.append(f"KNOWN FAILURES (top {top} of {len(trips)})  [diagnostics/triplets.yaml — grep it on ANY error]")
    for _, t in scored[:top]:
        lines.append(f"- symptom: {_flat(t.get('symptom'))[:130]}")
        lines.append(f"  remedy:  {_flat(t.get('remedy'))[:150]}")


def _verified_pointers(ki: Path, missing: list):
    """The 162-class: SKILL.md references that do not exist on disk."""
    sk = ki / "SKILL.md"
    if not sk.is_file():
        missing.append("SKILL.md MISSING — no protocol; do not improvise a pipeline")
        return
    txt = sk.read_text(errors="ignore")
    refs = set(re.findall(r"(?:docs|diagnostics|tools|workflow|examples)/[A-Za-z0-9_.\-/]+"
                          r"\.(?:md|yaml|yml|py|json|rst|txt)", txt))
    broken = sorted(r for r in refs if not (ki / r).exists())[:8]
    for r in broken:
        missing.append(f"SKILL.md references {r} — ABSENT on disk (do not search for it; it does not exist)")


def digest(model_id: str, target_var: str | None = None, budget: int = 4500) -> str:
    r = resolve(model_id)
    ki = Path(r["ki_path"])
    lines: list[str] = [f"[RUN-TIME ATTENTION — {r['model_id']}]  KI: {ki}"]
    missing: list[str] = list(r["warnings"])
    _outputs_digest(ki, target_var, lines, missing)
    _format_digest(ki, lines, missing)
    _prep_digest(ki, lines)
    _triplets_digest(ki, target_var, lines, missing)
    lines.append(OP_RULES)
    _verified_pointers(ki, missing)
    if missing:
        lines.append("MISSING / VERIFY-FAILED")
        lines.extend(f"- {m}" for m in missing)
    out = "\n".join(lines)
    if len(out) > budget:
        out = out[:budget].rsplit("\n", 1)[0] + f"\n[truncated at {budget} chars — open the source files above]"
    return out


def main():
    args = sys.argv[1:]
    var = None
    budget = 4500
    if "--var" in args:
        i = args.index("--var"); var = args[i + 1]; del args[i:i + 2]
    if "--budget" in args:
        i = args.index("--budget"); budget = int(args[i + 1]); del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    try:
        print(digest(args[0], var, budget))
    except LookupError as e:
        print(f"KI_ATTENTION ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
