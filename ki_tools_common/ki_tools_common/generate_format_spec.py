#!/usr/bin/env python3
"""generate_format_spec — PROJECT docs/format_spec.yaml from dag.yaml + triplets.yaml.

Dag-driven rewrite 2026-08-15, revised same day after codex review (6 findings, all applied):
  1 inputs use `name` OR `var`;  2 all four input sections projected with their fields;
  3 triplet field synonyms resolved via ki_vocabulary (no literal "None");  4 observability
  carried per output;  5 unexpected dag shapes FAIL CLOSED;  6 collision-free backups.
"""
import argparse, sys, datetime as dt
from pathlib import Path
import yaml
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
from ki_vocabulary import canonical_key   # symptom/diagnosis/remedy synonym resolution
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ki_projection_common import (SourceShapeError, entry_name, observability, split_reason_items,
                                  read_triplet_entries)

class DagShapeError(RuntimeError): pass

_entry_name = entry_name   # ONE identity key rule, shared with the gate (co-review #6/#19)

def _trip_field(t, concept):
    for k, v in t.items():
        if canonical_key(k) == concept:
            return v
    return None

def _flat(x):
    _SKIP={"error_pattern","detection_method","regex","pattern"}
    if isinstance(x, dict):
        # kimi #5: non-string sub-values are stringified, not silently dropped
        return "; ".join(str(v) for k, v in x.items() if k not in _SKIP)[:300] or None
    if isinstance(x, list):
        return "; ".join(str(v) for v in x)[:300] or None
    return (str(x)[:300] if x is not None else None)

def build(ki: Path) -> dict:
    dag = yaml.safe_load((ki / "dag.yaml").read_text()) or {}
    ident = dag.get("identity") or {}
    ins = dag.get("inputs")
    if ins is not None and not isinstance(ins, dict):
        raise DagShapeError(f"{ki}: dag inputs is {type(ins).__name__}, expected mapping")
    outs = dag.get("outputs")
    if outs is not None and not isinstance(outs, list):
        raise DagShapeError(f"{ki}: dag outputs is {type(outs).__name__}, expected list")
    if not ident.get("model_id"):
        raise SourceShapeError(f"{ki}: dag identity.model_id missing — a projection must not "
                               f"invent an identity from the directory name")
    spec = {"model": {"name": ident.get("model_id"),
                      "language": ident.get("language"),
                      "implementation": ident.get("implementation"),
                      "scientific_reference_version": ident.get("scientific_reference_version")},
            "inputs": {}, "outputs": {"primary": [], "secondary": []}, "known_issues": []}
    for sec in ("forcing", "parameters", "initial_conditions", "boundary_conditions"):
        rows = (ins or {}).get(sec) or []
        # documented-empty marker: {_reason: "..."} means "none, and here is why" (QUINCY).
        # Honest emptiness is projected as an empty section carrying the reason — not an error.
        if isinstance(rows, dict) and set(rows) <= {"_reason", "_note"}:
            spec["inputs"][f"{sec}_note"] = rows.get("_reason") or rows.get("_note")
            rows = []
        if rows and not isinstance(rows, list):
            raise DagShapeError(f"{ki}: inputs.{sec} is {type(rows).__name__}, expected list")
        rows, _note = split_reason_items(rows)
        if _note: spec["inputs"][f"{sec}_note"] = _note
        spec["inputs"][sec] = [
            {k: e.get(k) for k in ("name","var","unit","description","category",
                                   "source_kind","model_input_format","notes") if e.get(k) is not None}
            | {"name": _entry_name(e)}                      # raises SourceShapeError on bad rows
            for e in rows]
    for o in outs or []:
        nm = _entry_name(o)                                 # raises on malformed — fail closed
        obsv = observability(o)                             # raises on non-dict (kimi #7)
        row = {"name": nm, "unit": o.get("unit"),
               "description": o.get("description"),
               "validation_rank": o.get("validation_rank"),
               "emitted_in": o.get("emitted_in")}
        if obsv:
            row["observability"] = obsv          # obs shapes, metrics, caveats — carried whole
        spec["outputs"]["primary" if obsv.get("comparable_obs_shapes") else "secondary"].append(row)
    for t in read_triplet_entries(ki):
        if True:
            spec["known_issues"].append({k: v for k, v in {
                "id": t.get("id"),
                "symptom": _flat(_trip_field(t, "symptom")),
                "diagnosis": _flat(_trip_field(t, "diagnosis")),
                "remedy": _flat(_trip_field(t, "remedy")),
                "severity": t.get("severity")}.items() if v is not None})
    return spec

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--ki_dir", required=True)
    ki = Path(ap.parse_args().ki_dir)
    spec = build(ki)
    out = ki / "docs" / "format_spec.yaml"; out.parent.mkdir(exist_ok=True)
    if out.is_file():
        # collision-free: microseconds + exclusive create
        while True:
            b = out.with_suffix(f".yaml.bak.{dt.datetime.now():%Y%m%dT%H%M%S_%f}")
            try:
                b.touch(exist_ok=False); b.write_bytes(out.read_bytes()); break
            except FileExistsError:
                continue
    out.write_text("# format_spec.yaml — projected from dag.yaml + diagnostics/triplets.yaml\n"
                   "# (format_spec generator, dag-driven + codex-reviewed 2026-08-15)\n\n"
                   + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100))
    n=spec["inputs"]
    print(f"Generated: {out}")
    print(f"  forcing={len(n['forcing'])} params={len(n['parameters'])} "
          f"init={len(n['initial_conditions'])} bounds={len(n['boundary_conditions'])} "
          f"primary={len(spec['outputs']['primary'])} issues={len(spec['known_issues'])}")

if __name__ == "__main__":
    main()
