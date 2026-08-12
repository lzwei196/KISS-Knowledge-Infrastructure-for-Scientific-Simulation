#!/usr/bin/env python3
"""
edit_boundaries.py -- Set steady-flow boundary conditions in a HEC-RAS run file
(.rNN) 'Section - Reach Boundaries' block. Copy-first: replace the numeric value
field in place, preserving column width.

HEC-RAS steady boundary TYPE codes (per reach end, per profile):
    1 = Known Water Surface  (value = WS elevation, ft/m)
    2 = Critical Depth       (value ignored)
    3 = Normal Depth         (value = energy/friction slope, ft/ft)  <-- default
    4 = Rating Curve         (value = stage; full curve lives elsewhere)

Block layout (verified on Mixed Flow example):
    Section - Reach Boundaries
    <flags...  reach name ...>
       <type>   0   <value>      <- upstream  (one line per profile if set)
       ...
       <type>   0   <value>      <- downstream (last triplet line)

Because the per-line ordering is positional and varies by project, this tool
operates by ROLE:
    --dn-slope S      set the downstream normal-depth slope (last triplet)
    --up-slope S      set the upstream normal-depth slope(s)
    --all-slope S     set every normal-depth (type 3) slope

For non-slope boundary types, edit the .fNN flow file in the GUI/ras-commander
and re-derive the run file -- changing the TYPE code in the run file alone can
desync the boundary value semantics.

Usage:
  python3 edit_boundaries.py --run MIXED.r01 --out MIXED.r01 --dn-slope 0.0008
  python3 edit_boundaries.py --run MIXED.r01 --out MIXED.r01 --all-slope 0.001
"""
import argparse
import json
import re
import shutil
import sys

TRIPLET = re.compile(r"^(\s*)(\d+)(\s+)(\d+)(\s+)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(\s*)$")


def _set_value(line, newval):
    m = TRIPLET.match(line.rstrip("\n"))
    if not m:
        return line, False
    a, typ, b, mid, c, val, d = m.groups()
    width = len(c) + len(val)
    field = ("%g" % newval).rjust(width)
    return f"{a}{typ}{b}{mid}{field}{d}\n", True


def edit_boundaries(run_path, out_path, dn_slope=None, up_slope=None, all_slope=None):
    if out_path != run_path:
        shutil.copy2(run_path, out_path)
    with open(out_path) as fh:
        lines = fh.readlines()

    start = next((i for i, l in enumerate(lines)
                  if l.strip() == "Section - Reach Boundaries"), None)
    if start is None:
        raise ValueError("no 'Section - Reach Boundaries' block; "
                         "see triplets.yaml 'no_boundary_section'")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("Section - ")), len(lines))

    triplet_idx = [i for i in range(start + 1, end) if TRIPLET.match(lines[i].rstrip("\n"))]
    changed = 0

    if all_slope is not None:
        for i in triplet_idx:
            if lines[i].strip().startswith("3"):
                lines[i], ok = _set_value(lines[i], all_slope)
                changed += ok
    if dn_slope is not None and triplet_idx:
        i = triplet_idx[-1]
        lines[i], ok = _set_value(lines[i], dn_slope)
        changed += ok
    if up_slope is not None:
        for i in triplet_idx[:-1] or triplet_idx[:1]:
            if lines[i].strip().startswith("3"):
                lines[i], ok = _set_value(lines[i], up_slope)
                changed += ok

    with open(out_path, "w") as fh:
        fh.writelines(lines)
    return {"triplets_found": len(triplet_idx), "values_changed": changed,
            "out": out_path}


def validate_outputs(result):
    if result["values_changed"] == 0:
        return False, "no boundary values changed (check --dn/--up/--all flags)"
    return True, f"changed {result['values_changed']} of {result['triplets_found']} boundary triplets"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dn-slope", type=float, default=None)
    ap.add_argument("--up-slope", type=float, default=None)
    ap.add_argument("--all-slope", type=float, default=None)
    a = ap.parse_args()
    if a.dn_slope is None and a.up_slope is None and a.all_slope is None:
        ap.error("provide at least one of --dn-slope / --up-slope / --all-slope")
    res = edit_boundaries(a.run, a.out, dn_slope=a.dn_slope,
                          up_slope=a.up_slope, all_slope=a.all_slope)
    ok, msg = validate_outputs(res)
    res["validation"] = {"ok": ok, "detail": msg}
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
