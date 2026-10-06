#!/usr/bin/env python3
"""kineros2_soil_params.py -- KINEROS2 infiltration parameters (KS, G, DIST, POR, ROCK) for a site.

KINEROS2's infiltration model (Smith-Parlange 3-parameter, Brooks-Corey soil) needs per element:
  KS   saturated hydraulic conductivity     mm/hr (metric) | in/hr (english)
  G    mean net capillary drive             mm            | in
  DIST pore size distribution index lambda  -   (engine stops if > 1.5)
  POR  porosity                             -
  ROCK volumetric rock fraction             -   (manual: if KS comes from texture, multiply by 1-ROCK)
  SAT  initial relative saturation          -   (event-specific; NOT derived here -- see --sat)

Source of the numbers (no invented values):
  * POR, DIST, G by USDA texture class: KINEROS2 manual 'Infiltration' Table 1 (src/doc/Infilt.pdf),
    itself from Rawls, Brakensiek & Saxton (1982); G there is in cm.
  * KS: ki_tools_common.soil_utils.lookup_hwsd(lat, lon)['hydraulics']['ksat_cm_hr'] (Rawls 1982
    class value for the HWSD dominant component's texture) or, with --texture, the same Rawls (1982)
    Green-Ampt Ks table; multiplied by (1 - ROCK) as the manual instructs.
  * ROCK: HWSD topsoil gravel volume % / 100 (only with --hwsd; 0 with --texture unless --rock).

Optionally writes the values into a parameter file (copy-first, via edit_kineros2_par logic):
  --apply-to PAR --out NEW [--elements PLANE|ID,...]   (channels are left alone: bed material
  differs from hillslope soil -- set channel KS/G by hand or from field data)

Usage
  kineros2_soil_params.py --hwsd --lat 31.72 --lon -110.06 --units english --json soil.json
  kineros2_soil_params.py --texture loam --units metric --apply-to EX1.PAR --out ex1_loam.par
Exit codes: 0 ok | 2 bad input / unknown texture / no HWSD cell
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402

# KINEROS2 Infilt.pdf Table 1 (Rawls et al. 1982): porosity n, pore size distribution lambda, G (cm)
TABLE1 = {
    "sand":            {"por": 0.437, "dist": 0.69, "g_cm": 5.0},
    "loamy_sand":      {"por": 0.437, "dist": 0.55, "g_cm": 7.0},
    "sandy_loam":      {"por": 0.453, "dist": 0.38, "g_cm": 13.0},
    "loam":            {"por": 0.463, "dist": 0.25, "g_cm": 11.0},
    "silt_loam":       {"por": 0.501, "dist": 0.23, "g_cm": 20.0},
    "sandy_clay_loam": {"por": 0.398, "dist": 0.32, "g_cm": 26.0},
    "clay_loam":       {"por": 0.464, "dist": 0.24, "g_cm": 26.0},
    "silty_clay_loam": {"por": 0.471, "dist": 0.18, "g_cm": 35.0},
    "sandy_clay":      {"por": 0.430, "dist": 0.22, "g_cm": 30.0},
    "silty_clay":      {"por": 0.479, "dist": 0.15, "g_cm": 38.0},
    "clay":            {"por": 0.475, "dist": 0.16, "g_cm": 41.0},
}
# Rawls, Brakensiek & Saxton (1982) Green-Ampt saturated conductivity by class, cm/hr
RAWLS_KS_CM_HR = {"sand": 21.0, "loamy_sand": 6.11, "sandy_loam": 2.59, "loam": 1.32, "silt_loam": 0.68,
                  "sandy_clay_loam": 0.43, "clay_loam": 0.23, "silty_clay_loam": 0.15, "sandy_clay": 0.12,
                  "silty_clay": 0.09, "clay": 0.06}
ALIASES = {"silt": "silt_loam"}   # Table 1 has no 'silt' row; Rawls groups it with silt loam


def _hwsd(lat, lon):
    try:
        from ki_tools_common.soil_utils import lookup_hwsd
    except ImportError:
        sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
        from ki_tools_common.soil_utils import lookup_hwsd
    return lookup_hwsd(lat, lon)


def derive(texture, ks_cm_hr=None, rock=0.0, units="metric") -> dict:
    tex = ALIASES.get(texture, texture).lower().replace(" ", "_")
    if tex not in TABLE1:
        raise ValueError(f"texture {texture!r} not in KINEROS2 Table 1 classes {sorted(TABLE1)}")
    if not 0.0 <= rock < 1.0:
        raise ValueError(f"rock fraction {rock} must be in [0, 1)")
    row = TABLE1[tex]
    ks = (ks_cm_hr if ks_cm_hr is not None else RAWLS_KS_CM_HR[tex]) * (1.0 - rock)   # cm/hr
    ks_mm, g_mm = ks * 10.0, row["g_cm"] * 10.0
    if units == "english":
        ks_v, g_v, ku, gu = ks_mm / k2.IN_TO_MM, g_mm / k2.IN_TO_MM, "in/hr", "in"
    else:
        ks_v, g_v, ku, gu = ks_mm, g_mm, "mm/hr", "mm"
    out = {"texture": tex, "units": units,
           "KS": round(ks_v, 4), "KS_unit": ku, "G": round(g_v, 3), "G_unit": gu,
           "DIST": row["dist"], "POR": row["por"], "ROCK": round(rock, 3),
           "provenance": {"POR,DIST,G": "KINEROS2 manual Infilt.pdf Table 1 (Rawls et al. 1982)",
                          "KS": "Rawls et al. 1982 class Ks x (1-ROCK)" if ks_cm_hr is None
                          else "HWSD hydraulics ksat_cm_hr (Rawls class value) x (1-ROCK)"}}
    if out["DIST"] > 1.5:
        raise ValueError("DIST > 1.5 is rejected by the engine")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--hwsd", action="store_true", help="look up the dominant HWSD soil at --lat/--lon")
    src.add_argument("--texture", help="USDA texture class, e.g. sandy_loam")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--rock", type=float, help="override rock fraction (0-1)")
    ap.add_argument("--units", choices=["metric", "english"], required=True,
                    help="must match the parameter file's GLOBAL UNITS")
    ap.add_argument("--json", help="write the derived parameters here")
    ap.add_argument("--apply-to", help="parameter file to copy and fill")
    ap.add_argument("--out", help="output parameter file (with --apply-to)")
    ap.add_argument("--elements", default="PLANE", help="PLANE (all planes) or comma list of element IDs")
    a = ap.parse_args(argv)
    try:
        meta = {}
        if a.hwsd:
            if a.lat is None or a.lon is None:
                raise ValueError("--hwsd needs --lat and --lon")
            s = _hwsd(a.lat, a.lon)
            if not s or not s.get("texture"):
                raise ValueError(f"no HWSD soil at {a.lat},{a.lon}")
            rock = a.rock if a.rock is not None else float(s.get("gravel") or 0.0) / 100.0
            ks = (s.get("hydraulics") or {}).get("ksat_cm_hr")
            res = derive(s["texture"], ks, rock, a.units)
            meta = {"hwsd_mu_id": s.get("mu_id"), "sand": s.get("sand"), "silt": s.get("silt"),
                    "clay": s.get("clay"), "gravel_pct": s.get("gravel"),
                    "hwsd_component": s.get("hwsd_component")}
        else:
            res = derive(a.texture, None, a.rock or 0.0, a.units)
        res["site"] = {"lat": a.lat, "lon": a.lon, **meta}
        res["note"] = ("SAT (initial relative saturation) is event-specific and is NOT derived here; "
                       "set it per element or per rain gage (gage SAT overrides element SA).")
        print(json.dumps({k: v for k, v in res.items() if k != "site"}, indent=1))
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=2))
        if a.apply_to:
            if not a.out:
                raise ValueError("--apply-to needs --out")
            from edit_kineros2_par import apply_sets
            tf = k2.read_tagged(a.apply_to)
            if k2.par_units(tf) != a.units:
                raise ValueError(f"--units {a.units} but {a.apply_to} is {k2.par_units(tf)}")
            sels = ["PLANE"] if a.elements.upper() == "PLANE" else [s.strip() for s in a.elements.split(",")]
            specs = [f"{sel}:{tag}={res[tag]}" for sel in sels for tag in ("KS", "G", "DI", "POR", "ROCK")
                     if tag != "DI"] + [f"{sel}:DI={res['DIST']}" for sel in sels]
            log = apply_sets(tf, specs)
            tf.write(a.out)
            v = k2.validate_parfile(k2.read_tagged(a.out))
            print(f"wrote {a.out}: {len(log)} value(s) set; validation errors: {v['errors'] or 'none'}")
            if v["errors"]:
                return 2
    except (ValueError, k2.EngineError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
