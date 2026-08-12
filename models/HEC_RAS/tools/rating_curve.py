#!/usr/bin/env python3
"""
rating_curve.py -- Build a stage-discharge rating curve at a chosen cross
section by sweeping discharges through the REAL HEC-RAS steady solver.

For each discharge in the sweep it: copies the project, sets the flow
(convert_flow_to_hecras), runs RasSteady (run_hecras), and reads the computed
water-surface elevation at the target cross section (parse_output_hecras).
Every point is a genuine solver solution -- nothing is interpolated/fit.

Usage:
  python3 rating_curve.py --project <dir> --prj MIXED --plan 01 \
      --xs-index 9 --flows 300,500,800,1200,2000 --out rating.csv
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_hecras
import convert_flow_to_hecras as cflow
import parse_output_hecras as parse
from _hecras_env import TEMPLATE_DIR, TEMPLATE_PRJ


def rating_curve(project, prj, plan, xs_index, flows_cfs, out_csv=None, profile_index=0):
    import tempfile
    import shutil
    src = project or TEMPLATE_DIR
    points = []
    for q in flows_cfs:
        work = tempfile.mkdtemp(prefix="rating_")
        try:
            for f in os.listdir(src):
                s = os.path.join(src, f)
                if os.path.isfile(s):
                    shutil.copy2(s, os.path.join(work, f))
            run_file = os.path.join(work, f"{prj}.r{plan}")
            # set this single discharge on profile 1 (first profile)
            cflow.set_flows(run_file, run_file, [q])
            out = os.path.join(work, "out")
            status = run_hecras.run(project=work, prj=prj, plan=plan, output_dir=out)
            if not status["ok"]:
                points.append({"q_cfs": q, "ws": None, "note": "solver failed"})
                continue
            parsed = parse.parse(status["result_hdf"])
            rec = next((r for r in parsed["records"]
                        if r["xs_index"] == xs_index
                        and r["profile"] == parsed["summary"]["profiles"][profile_index]), None)
            if rec is None:
                points.append({"q_cfs": q, "ws": None, "note": "xs not found"})
            else:
                points.append({"q_cfs": q, "ws": rec.get("ws"),
                               "eg": rec.get("eg"), "vel": rec.get("vel_chnl"),
                               "froude": rec.get("froude"), "regime": rec.get("regime")})
        finally:
            shutil.rmtree(work, ignore_errors=True)

    if out_csv:
        keys = ["q_cfs", "ws", "eg", "vel", "froude", "regime"]
        with open(out_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for p in points:
                w.writerow(p)
    return points


def validate_outputs(points):
    valid = [p for p in points if p.get("ws") is not None]
    if len(valid) < 2:
        return False, "fewer than 2 valid rating points"
    # monotonicity: stage should not decrease as discharge increases
    valid_sorted = sorted(valid, key=lambda p: p["q_cfs"])
    ws = [p["ws"] for p in valid_sorted]
    nonmono = sum(1 for a, b in zip(ws, ws[1:]) if b < a - 0.05)
    if nonmono > 0:
        return False, f"non-monotonic rating curve ({nonmono} reversals) -- check geometry/boundaries"
    return True, f"{len(valid)} monotonic rating points, WS {ws[0]:.2f}->{ws[-1]:.2f} ft"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--prj", default=TEMPLATE_PRJ)
    ap.add_argument("--plan", default="01")
    ap.add_argument("--xs-index", type=int, default=0)
    ap.add_argument("--flows", required=True, help="comma list of discharges (cfs)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    flows = [float(x) for x in a.flows.split(",")]
    pts = rating_curve(a.project, a.prj, a.plan, a.xs_index, flows, out_csv=a.out)
    ok, msg = validate_outputs(pts)
    print(json.dumps({"points": pts, "validation": {"ok": ok, "detail": msg}}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
