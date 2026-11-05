#!/usr/bin/env python3
"""Build a QUINCY site configuration (site_config.json) for tools/run_quincy_engine.py.

It decides the namelist values that make a site: location, plant functional type (PFT)
and soil. Output = JSON with "nml": {group: {key: value}} that the run tool writes into
qs.namelist, plus a provenance record for every value.

PFT: --pft (name or 1-14) wins; else the site is looked up in the engine's own site lists
  src/data/fluxnet2_siteset_pft_info.csv and cruncep_v7_siteset_pft_info.csv
  (e.g. FI-Hyy -> BNE = 5). QUINCY PFTs: 1 BEM, 2 BED, 3 BDR, 4 BDS, 5 NE (BNE),
  6 NS, 7 TeH (C3 grass), 8 TrH (C4 grass), 9 TeP, 10 TrP, 11 TeC (C3 crop), 12 TrC, 13 BSO, 14 UAR.

Soil: --soil hwsd reads HWSD topsoil via ki_tools_common.soil_utils.lookup_hwsd (percent and
g cm-3) and converts to the engine units: sand/silt/clay as FRACTIONS (0-1) and bulk density
in kg m-3. --soil explicit takes --sand/--silt/--clay (fractions) and --bulk_density_kg_m3.
The same texture is written to all three engine namelists that read it
(lnd_spq_nml spq_soil_*, jsb_sse_nml qs_soil_*, and jsb_hydro_nml qs_soil_depth); setting only
one of them leaves the other processes on the 0.3/0.4/0.3 default.

Exit codes: 0 ok, 2 bad arguments / site or PFT not found / invalid soil values.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import ENGINE_DATA, PFT_IDS, finite  # noqa: E402

PFT_NAMES = {1: "BEM", 2: "BED", 3: "BDR", 4: "BDS", 5: "BNE", 6: "BNS", 7: "TeH", 8: "TrH",
             9: "TeP", 10: "TrP", 11: "TeC", 12: "TrC", 13: "BSO", 14: "UAR"}


def site_pft(site: str):
    for name in ("fluxnet2_siteset_pft_info.csv", "cruncep_v7_siteset_pft_info.csv"):
        f = ENGINE_DATA / name
        rows = [ln for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        for r in csv.DictReader(rows):
            if r["Site"].strip() == site:
                return int(r["PFTnum"]), r["PFTname"].strip(), str(f)
    return None


def parse_pft(text: str) -> int:
    if text.isdigit() and 1 <= int(text) <= 14:
        return int(text)
    key = text.upper()
    if key in PFT_IDS:
        return PFT_IDS[key]
    raise ValueError(f"unknown PFT {text!r}; use 1-14 or one of {sorted(PFT_IDS)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--site", help="site id to look up in the engine's site PFT lists (e.g. FI-Hyy)")
    ap.add_argument("--pft", help="PFT name or number (overrides the site list)")
    ap.add_argument("--soil", choices=["hwsd", "explicit", "default"], default="hwsd")
    ap.add_argument("--sand", type=float, help="sand fraction 0-1 (explicit soil)")
    ap.add_argument("--silt", type=float, help="silt fraction 0-1 (explicit soil)")
    ap.add_argument("--clay", type=float, help="clay fraction 0-1 (explicit soil)")
    ap.add_argument("--bulk_density_kg_m3", type=float, help="bulk density [kg m-3] (explicit soil)")
    ap.add_argument("--soil_ph", type=float, help="soil pH (lnd_sb_nml soil_ph)")
    ap.add_argument("--soil_depth_m", type=float, help="soil depth [m] (engine default 9.5)")
    ap.add_argument("--elevation_m", type=float, help="site elevation [m] (lnd_spq_nml spq_elevation)")
    ap.add_argument("--soil_note", default="", help="free-text source of explicit soil values")
    ap.add_argument("--out", required=True, help="output site_config.json")
    a = ap.parse_args(argv)
    prov = {}
    try:
        lat = finite(a.lat, "lat", -90, 90)
        lon = finite(a.lon, "lon", -180, 180)
        if a.pft:
            pft = parse_pft(a.pft)
            prov["pft"] = "command line --pft"
        elif a.site and site_pft(a.site):
            pft, pname, f = site_pft(a.site)
            prov["pft"] = f"{f}: {a.site} -> {pname} ({pft})"
        else:
            raise ValueError("no PFT: give --pft or a --site listed in the engine site PFT csv files")
        nml = {"grid_ctl": {"latitude": lat, "longitude": lon},
               "lnd_veg_nml": {"plant_functional_type_id": pft}}
        soil = None
        if a.soil == "hwsd":
            from ki_tools_common.soil_utils import lookup_hwsd
            h = lookup_hwsd(lat, lon)
            if h is None or h.get("sand") is None:
                raise ValueError("HWSD has no soil at this point; use --soil explicit")
            soil = {"sand": h["sand"] / 100.0, "silt": h["silt"] / 100.0, "clay": h["clay"] / 100.0,
                    "bd": h["bulk_density"] * 1000.0, "ph": h.get("ph")}
            prov["soil"] = (f"HWSD topsoil mu_id {h.get('mu_id')} texture {h.get('texture')} "
                            f"(percent -> fraction, g cm-3 -> kg m-3); organic C {h.get('oc')} %")
        elif a.soil == "explicit":
            if None in (a.sand, a.silt, a.clay, a.bulk_density_kg_m3):
                raise ValueError("--soil explicit needs --sand --silt --clay --bulk_density_kg_m3")
            soil = {"sand": finite(a.sand, "sand", 0, 1), "silt": finite(a.silt, "silt", 0, 1),
                    "clay": finite(a.clay, "clay", 0, 1),
                    "bd": finite(a.bulk_density_kg_m3, "bulk_density_kg_m3", 100, 2500), "ph": None}
            prov["soil"] = "explicit: " + (a.soil_note or "no source given")
        else:
            prov["soil"] = "engine defaults (sand 0.3, silt 0.4, clay 0.3, bulk density 1500 kg m-3)"
        if soil:
            total = soil["sand"] + soil["silt"] + soil["clay"]
            if abs(total - 1.0) > 0.02:
                raise ValueError(f"sand+silt+clay = {total:.3f}, must be 1 (fractions, not percent)")
            if not 100 <= soil["bd"] <= 2500:
                raise ValueError(f"bulk density {soil['bd']} kg m-3 is implausible")
            nml["lnd_spq_nml"] = {"spq_soil_sand": soil["sand"], "spq_soil_silt": soil["silt"],
                                  "spq_soil_clay": soil["clay"], "spq_bulk_density": soil["bd"]}
            nml["jsb_sse_nml"] = {"qs_soil_sand": soil["sand"], "qs_soil_silt": soil["silt"],
                                  "qs_soil_clay": soil["clay"], "qs_bulk_density": soil["bd"]}
        ph = a.soil_ph if a.soil_ph is not None else (soil or {}).get("ph")
        if ph is not None:
            nml["lnd_sb_nml"] = {"soil_ph": finite(ph, "soil_ph", 2.5, 11)}
            prov["soil_ph"] = "command line" if a.soil_ph is not None else "HWSD topsoil pH"
        if a.soil_depth_m is not None:
            d = finite(a.soil_depth_m, "soil_depth_m", 0.1, 50)
            nml.setdefault("lnd_spq_nml", {})["spq_soil_depth"] = d
            nml["jsb_hydro_nml"] = {"qs_soil_depth": d}
        if a.elevation_m is not None:
            nml.setdefault("lnd_spq_nml", {})["spq_elevation"] = finite(a.elevation_m, "elevation_m", -500, 9000)
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    cfg = {"site": a.site, "lat": lat, "lon": lon, "pft_id": pft, "pft_name": PFT_NAMES[pft],
           "nml": nml, "provenance": prov}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(cfg, indent=2))
    print(json.dumps(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
