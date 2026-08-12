#!/usr/bin/env python3
"""
author_steady_geometry.py -- Author a RUNNABLE steady HEC-RAS run file (.rNN) for
a NEW river reach from a DEM, with NO Wine Mono and NO ras_commander required.

WHY THIS TOOL EXISTS (the finding that unblocks new-river steady runs)
---------------------------------------------------------------------
Five prior verifier runs declared new-river geometry "structurally impossible"
because authoring a fresh project was believed to need `Ras.exe` (Wine Mono) or
`ras_commander` (which does not recognise the 6.7-Beta5 layout). That verdict was
WRONG for STEADY flow. Controlled experiment (2026-06-04): bump every bed
elevation in a working `MIXED.r01` by +5 ft, re-run `RasSteady.exe` under plain
wine -> the computed water surface rose by exactly +5 ft (range 66.00..72.93 ->
71.00..77.93). This proves the **.rNN run file is the authoritative geometry
source for the steady solver** -- it reads station/elevation directly from the
`.rNN`; the `.gNN.hdf` is only the *results-skeleton* seed (see run_hecras.py).

Therefore a new reach can be run by INJECTING new cross-section geometry into the
station/elevation rows of a template `.rNN`, keeping the array-size header valid
by reusing the template's cross-section count (19) and 4 points/XS (a trapezoidal
channel). Only the numeric Sta/Elev values, discharges, and downstream slope
change -- exactly the proven-safe value-swap.

PIPELINE
--------
  DEM (+ optional river centerline)
    -> ki_tools_common.terrain_ops.cut_cross_sections   (real DEM cross sections)
    -> trapezoidalise each XS to 4 points, convert m -> ft
    -> inject into template .rNN NODE blocks (upstream->downstream)
    -> set discharges (convert_flow_to_hecras) + downstream slope (edit_boundaries)
  Result: <out-dir>/<PRJ>.r01 ready for run_hecras.py (plain wine, no Mono).

LIMITATION (documented honestly): the longitudinal layout (reach lengths, river
stations) is inherited from the template -- this value-swap path keeps the
array-size header byte-identical, so it represents real DEM cross-section SHAPES
at the template's spacing. Fully general longitudinal re-authoring (arbitrary XS
count / spacing) additionally requires regenerating the "Section - Arrays Sizes"
header and is the next tool_build step. HEC-RAS steady CONSUMES discharge and
PRODUCES water-surface stage -- this tool computes stage, not discharge.

Usage:
  python3 author_steady_geometry.py --dem /tmp/bengbu_dem_utm.tif \
        --out-dir /tmp/bengbu_steady --flows-m3s 3810,6812 --dn-slope 0.0002
  python3 author_steady_geometry.py --dem dem.tif --centerline-wkt "LINESTRING(...)" \
        --observedq /path/Q.txt --quantiles 0.5,0.9 --dn-slope 0.0003
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

M_TO_FT = 3.280839895


def _trapezoid_ft(station_elevation):
    """Reduce a sampled DEM cross section (list of (s,z) in metres, left->right)
    to a 4-point trapezoidal channel in FEET: bank-top L, invert, invert, bank-top R.

    invert = thalweg (min elevation); banks placed at 40%/60% of width; bank tops
    = the max elevation on each half (floodplain edge). Returns 8 floats
    [s0,z0,s1,z1,s2,z2,s3,z3] in feet.
    """
    s = [p[0] for p in station_elevation]
    z = [p[1] for p in station_elevation]
    w = s[-1] - s[0]
    invert = min(z)
    half = len(z) // 2
    ztop_l = max(z[:half] or z)
    ztop_r = max(z[half:] or z)
    pts = [(0.0, ztop_l),
           (0.40 * w, invert),
           (0.60 * w, invert),
           (w, ztop_r)]
    out = []
    for st, el in pts:
        out.append(st * M_TO_FT)
        out.append(el * M_TO_FT)
    return out


def _fmt_row(vals8):
    """Format 8 floats as the fixed-width Fortran sta/elev row the solver reads
    (width-8 right-justified, %g) -- the exact format proven to run."""
    return "".join(f"{v:>8g}" for v in vals8)


def _resample_indices(n_available, n_want):
    if n_available <= n_want:
        return list(range(n_available))
    return [round(i * (n_available - 1) / (n_want - 1)) for i in range(n_want)]


def author(dem_path, out_dir, centerline=None, centerline_wkt=None,
           half_width=600.0, spacing=None, flows_m3s=None, observedq=None,
           quantiles=(0.5, 0.9), dn_slope=None, prj=TEMPLATE_PRJ, plan="01"):
    from shapely import wkt as _wkt
    from ki_tools_common.terrain_ops import (cut_cross_sections,
                                             extract_river_centerline_from_dem)

    # 1. centerline
    if centerline is None and centerline_wkt:
        centerline = _wkt.loads(centerline_wkt)
    if centerline is None:
        cl = extract_river_centerline_from_dem(dem_path, os.path.join(out_dir, "_cl"),
                                               stream_threshold=300, select="longest")
        centerline = cl["centerline"]

    # template has 19 XS / 4 pts -- match it so the array-size header stays valid
    N_XS = 19
    if spacing is None:
        spacing = max(centerline.length / (N_XS + 1), 30.0)

    cut = cut_cross_sections(centerline, dem_path, spacing=spacing,
                             half_width=half_width)
    xs = cut["cross_sections"]
    if len(xs) < 2:
        raise ValueError(f"only {len(xs)} cross sections cut; widen DEM or reduce spacing")

    # 2. pick exactly N_XS, order upstream(high thalweg)->downstream(low thalweg)
    idx = _resample_indices(len(xs), N_XS)
    chosen = [xs[i] for i in idx]
    chosen.sort(key=lambda c: -min(z for _, z in c["station_elevation"]))
    rows = [_trapezoid_ft(c["station_elevation"]) for c in chosen]
    while len(rows) < N_XS:                      # pad if DEM gave fewer
        rows.append(rows[-1])
    rows = rows[:N_XS]

    # 3. copy template, inject sta/elev rows into the 19 NODE blocks (file order
    #    is upstream->downstream, matching our ordering)
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(TEMPLATE_DIR):
        sp = os.path.join(TEMPLATE_DIR, f)
        if os.path.isfile(sp):
            shutil.copy2(sp, os.path.join(out_dir, f))
    run_file = os.path.join(out_dir, f"{prj}.r{plan}")
    with open(run_file) as fh:
        lines = fh.readlines()

    node_idx = [i for i, l in enumerate(lines) if l.startswith("NODE")]
    if len(node_idx) != N_XS:
        raise ValueError(f"template has {len(node_idx)} NODE blocks, expected {N_XS}")
    injected = 0
    for k, ni in enumerate(node_idx):
        # sta/elev row is the line after the point-count line ('       4')
        se_line = ni + 3
        # guard: confirm the target line is the 8-float geometry row
        if len(lines[se_line].split()) == 8:
            lines[se_line] = _fmt_row(rows[k]) + "\n"
            injected += 1
    with open(run_file, "w") as fh:
        fh.writelines(lines)

    actions = {"cross_sections_injected": injected, "n_xs": N_XS,
               "centerline_length_m": round(centerline.length, 1),
               "spacing_m": round(spacing, 1), "half_width_m": half_width}

    # 4. discharges
    if observedq:
        fl = cflow.flows_from_observedq(observedq, list(quantiles))
        flows_cfs = cflow._to_cfs(fl, "m3/s")
        actions["observedq_m3s"] = fl
    elif flows_m3s:
        fl = flows_m3s.split(",") if isinstance(flows_m3s, str) else flows_m3s
        flows_cfs = cflow._to_cfs(fl, "m3/s")
        actions["flows_m3s"] = [float(x) for x in fl]
    else:
        flows_cfs = None
    if flows_cfs:
        actions["flows"] = cflow.set_flows(run_file, run_file, flows_cfs)

    # 5. downstream normal-depth slope
    if dn_slope is not None:
        actions["boundaries"] = ebnd.edit_boundaries(run_file, run_file,
                                                     dn_slope=dn_slope)

    return {"out_dir": out_dir, "prj": prj, "plan": plan, "run_file": run_file,
            "actions": actions}


def validate_outputs(result):
    rf = result["run_file"]
    if not os.path.isfile(rf):
        return False, f"run file not written: {rf}"
    inj = result["actions"].get("cross_sections_injected", 0)
    if inj != result["actions"].get("n_xs"):
        return False, f"only {inj} cross sections injected"
    return True, (f"authored {rf}: {inj} DEM cross sections injected, "
                  f"ready for run_hecras.py (plain wine, no Mono)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", required=True, help="DEM raster (projected CRS, metres)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--centerline-wkt", default=None,
                    help="river centerline LineString WKT in the DEM CRS; "
                         "if omitted it is auto-extracted from the DEM")
    ap.add_argument("--half-width", type=float, default=600.0)
    ap.add_argument("--spacing", type=float, default=None)
    ap.add_argument("--flows-m3s", default=None, help="comma discharges in m3/s")
    ap.add_argument("--observedq", default=None, help="ObservedQ table (Huai format)")
    ap.add_argument("--quantiles", default="0.5,0.9")
    ap.add_argument("--dn-slope", type=float, default=None)
    ap.add_argument("--prj", default=TEMPLATE_PRJ)
    ap.add_argument("--plan", default="01")
    a = ap.parse_args()
    res = author(a.dem, a.out_dir, centerline_wkt=a.centerline_wkt,
                 half_width=a.half_width, spacing=a.spacing, flows_m3s=a.flows_m3s,
                 observedq=a.observedq,
                 quantiles=[float(x) for x in a.quantiles.split(",")],
                 dn_slope=a.dn_slope, prj=a.prj, plan=a.plan)
    ok, msg = validate_outputs(res)
    res["validation"] = {"ok": ok, "detail": msg}
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
