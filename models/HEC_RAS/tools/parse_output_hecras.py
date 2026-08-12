#!/usr/bin/env python3
"""
parse_output_hecras.py -- Extract hydraulic results from a HEC-RAS steady
results HDF5 (<prj>.pNN.tmp.hdf or <prj>.pNN.hdf produced by RasSteady.exe).

Reads the genuine solver output -- no recomputation. Emits per-(profile, cross
section) records of the primary hydraulic variables plus a derived Froude number
and flow-regime classification.

Usage:
  python3 parse_output_hecras.py --hdf <results.hdf> [--csv out.csv] [--json out.json]
"""
import argparse
import json
import os
import sys

import h5py
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hecras_env import STEADY_XS

# variable name in HDF -> (output key, description, units[English])
PRIMARY = {
    "Water Surface": ("ws", "Water surface elevation", "ft"),
    "Energy Grade":  ("eg", "Energy grade elevation", "ft"),
    "Flow":          ("q",  "Total discharge", "cfs"),
}
ADDITIONAL = {
    "Velocity Channel":      ("vel_chnl", "Main-channel velocity", "ft/s"),
    "Velocity Total":        ("vel_total", "Average velocity", "ft/s"),
    "Hydraulic Depth Total": ("hyd_depth", "Hydraulic depth", "ft"),
    "Top Width Total":       ("top_width", "Top width", "ft"),
    "Area Flow Total":       ("flow_area", "Flow area", "ft^2"),
    "Froude # Channel":      ("froude_chnl", "Froude number (channel)", "-"),
    "Shear":                 ("shear", "Channel shear stress", "lb/ft^2"),
    "Friction Slope":        ("frict_slope", "Friction slope", "ft/ft"),
    "Critical Water Surface":("crit_ws", "Critical water surface", "ft"),
}
G_ENGLISH = 32.174  # ft/s^2


def parse(hdf_path):
    if not os.path.isfile(hdf_path):
        raise FileNotFoundError(hdf_path)
    with h5py.File(hdf_path, "r") as f:
        if STEADY_XS not in f and (STEADY_XS + "Water Surface") not in f:
            # try without trailing slash resolution issues
            pass
        base = f[STEADY_XS]
        ws = base["Water Surface"][:]            # (n_prof, n_xs)
        n_prof, n_xs = ws.shape
        data = {}
        for hkey, (okey, _d, _u) in PRIMARY.items():
            if hkey in base:
                data[okey] = base[hkey][:]
        add = base["Additional Variables"] if "Additional Variables" in base else {}
        for hkey, (okey, _d, _u) in ADDITIONAL.items():
            if hkey in add:
                data[okey] = add[hkey][:]

        # profile names
        prof_names = None
        for cand in ("Profile Names", "../Profile Names"):
            try:
                prof_names = [p.decode().strip() for p in base.get(cand)[:]]  # type: ignore
            except Exception:  # noqa
                prof_names = None
        if not prof_names:
            try:
                pn = f["/Results/Steady/Output/Output Blocks/Base Output/"
                       "Steady Profiles/Profile Names"][:]
                prof_names = [p.decode().strip() for p in pn]
            except Exception:  # noqa
                prof_names = [f"PF {i+1}" for i in range(n_prof)]

        # river-station labels from geometry, if present
        def _dec(v):
            if isinstance(v, bytes):
                return v.decode(errors="ignore").strip()
            return str(v).strip()

        rs = None
        for path in ("/Geometry/Cross Sections/River Stations",
                     "/Geometry/Cross Sections/Attributes"):
            try:
                node = f[path]
                if path.endswith("Attributes"):
                    rs = [_dec(r["RS"]) if hasattr(r, "__getitem__") else _dec(r)
                          for r in node[:]]
                else:
                    rs = [_dec(x) for x in node[:]]
                break
            except Exception:  # noqa
                rs = None

    # Froude: prefer solver value; else derive V/sqrt(g*D)
    records = []
    for ip in range(n_prof):
        for ix in range(n_xs):
            rec = {"profile": prof_names[ip], "xs_index": ix}
            if rs and ix < len(rs):
                rec["river_station"] = rs[ix]
            for okey in list(PRIMARY.values()):
                pass
            for okey in [v[0] for v in PRIMARY.values()] + [v[0] for v in ADDITIONAL.values()]:
                if okey in data:
                    rec[okey] = float(data[okey][ip, ix])
            # derived Froude / regime
            fr = rec.get("froude_chnl")
            if (fr is None or fr == 0) and "vel_chnl" in rec and rec.get("hyd_depth", 0) > 0:
                fr = rec["vel_chnl"] / np.sqrt(G_ENGLISH * rec["hyd_depth"])
            if fr is not None:
                rec["froude"] = round(float(fr), 4)
                rec["regime"] = ("supercritical" if fr > 1.0
                                 else "subcritical" if fr < 1.0 else "critical")
            records.append(rec)
    summary = {
        "n_profiles": int(n_prof),
        "n_cross_sections": int(n_xs),
        "profiles": prof_names,
        "variables": [k for k in (list(PRIMARY.values()) + list(ADDITIONAL.values()))],
    }
    return {"summary": summary, "records": records}


def to_csv(parsed, path):
    import csv
    recs = parsed["records"]
    if not recs:
        return
    keys = []
    for r in recs:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in recs:
            w.writerow(r)


def validate_outputs(parsed):
    recs = parsed["records"]
    if not recs:
        return False, "no records parsed"
    ws = [r["ws"] for r in recs if "ws" in r]
    if not ws:
        return False, "no water-surface values"
    if not all(np.isfinite(ws)):
        return False, "non-finite WS"
    return True, f"{len(recs)} records, WS {min(ws):.2f}..{max(ws):.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hdf", required=True)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    parsed = parse(a.hdf)
    ok, msg = validate_outputs(parsed)
    if a.csv:
        to_csv(parsed, a.csv)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(parsed, fh, indent=2)
    print(json.dumps({"summary": parsed["summary"],
                      "validation": {"ok": ok, "detail": msg},
                      "first_records": parsed["records"][:3]}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
