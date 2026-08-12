#!/usr/bin/env python3
"""
prepare_steady_run.py -- Materialise a ready-to-run HEC-RAS steady project into
a working directory, starting from a template (copy-first) and optionally
applying discharge / boundary / roughness edits via the other tools.

This is the single entry point that wires the ingestion tools together:
    copy template  ->  set flows  ->  set boundaries  ->  (scale Manning)
The result is a project directory you then hand to run_hecras.py.

Usage:
  python3 prepare_steady_run.py --out-dir myproj \
      --flows 600,1200 --dn-slope 0.0008 --mann-scale 1.1
  python3 prepare_steady_run.py --template <dir> --prj MIXED --out-dir myproj
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hecras_env import TEMPLATE_DIR, TEMPLATE_PRJ
import convert_flow_to_hecras as cflow
import edit_boundaries as ebnd
import edit_geometry as egeo


def prepare(out_dir, template=None, prj=TEMPLATE_PRJ, plan="01",
            flows=None, in_units="cfs", dn_slope=None, up_slope=None,
            all_slope=None, mann_scale=None, mann_set=None):
    src = template or TEMPLATE_DIR
    if not os.path.isdir(src):
        raise FileNotFoundError(src)
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(src):
        s = os.path.join(src, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(out_dir, f))

    run_file = os.path.join(out_dir, f"{prj}.r{plan}")
    geom_file = os.path.join(out_dir, f"{prj}.g{plan}")
    actions = {}

    if flows:
        flows_cfs = cflow._to_cfs(flows.split(",") if isinstance(flows, str) else flows,
                                  in_units)
        actions["flows"] = cflow.set_flows(run_file, run_file, flows_cfs)
    if dn_slope is not None or up_slope is not None or all_slope is not None:
        actions["boundaries"] = ebnd.edit_boundaries(
            run_file, run_file, dn_slope=dn_slope, up_slope=up_slope, all_slope=all_slope)
    if (mann_scale is not None or mann_set is not None) and os.path.isfile(geom_file):
        actions["geometry"] = egeo.edit_geometry(
            geom_file, geom_file, mann_scale=mann_scale, mann_set=mann_set)
        actions["geometry_note"] = ("geometry .gNN edited; for the edit to reach "
                                    "the solver the run file must be re-derived "
                                    "(GUI/ras-commander). For pure parametric n on "
                                    "the existing run file use the run-file roughness block.")

    return {"out_dir": out_dir, "prj": prj, "plan": plan, "actions": actions}


def validate_outputs(result):
    out = result["out_dir"]
    need = [f"{result['prj']}.r{result['plan']}"]
    missing = [n for n in need if not os.path.isfile(os.path.join(out, n))]
    if missing:
        return False, f"missing required files: {missing}"
    return True, f"project prepared in {out} ({len(os.listdir(out))} files)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=None)
    ap.add_argument("--prj", default=TEMPLATE_PRJ)
    ap.add_argument("--plan", default="01")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--flows", default=None)
    ap.add_argument("--in-units", default="cfs", choices=["cfs", "ft3/s", "m3/s"])
    ap.add_argument("--dn-slope", type=float, default=None)
    ap.add_argument("--up-slope", type=float, default=None)
    ap.add_argument("--all-slope", type=float, default=None)
    ap.add_argument("--mann-scale", type=float, default=None)
    ap.add_argument("--mann-set", type=float, default=None)
    a = ap.parse_args()
    res = prepare(a.out_dir, template=a.template, prj=a.prj, plan=a.plan,
                  flows=a.flows, in_units=a.in_units, dn_slope=a.dn_slope,
                  up_slope=a.up_slope, all_slope=a.all_slope,
                  mann_scale=a.mann_scale, mann_set=a.mann_set)
    ok, msg = validate_outputs(res)
    res["validation"] = {"ok": ok, "detail": msg}
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
