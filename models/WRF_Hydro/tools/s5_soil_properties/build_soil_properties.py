#!/usr/bin/env python3
"""
build_soil_properties.py  --  WRF-Hydro Phase 2, Tool 3
========================================================
Build soil_properties.nc from geo_em.d01.nc + SOILPARM.TBL + MPTABLE.TBL.

For each grid cell, look up ISLTYP (soil type) -> soil hydraulic params,
and IVGTYP (vegetation type) -> vegetation params.

Variables produced (matching reference):
  4-layer soil: bexp, smcmax, smcref, smcwlt, smcdry, dksat, dwsat, psisat, quartz
  2D soil:      slope, refdk, refkdt, rsurfexp
  2D vegetation: cwpvt, hvt, mfsno, mp, vcmx25

Usage
-----
    python build_soil_properties.py \\
        --geo_em  outputs/.../geo_em.d01.nc \\
        --output_path outputs/.../soil_properties.nc \\
        --soilparm_tbl model/wrf_hydro/.../SOILPARM.TBL \\
        --mptable_tbl  model/wrf_hydro/.../MPTABLE.TBL
"""

import argparse
import os
import re
import sys
from pathlib import Path

import netCDF4 as nc
import numpy as np


DEFAULT_SOILPARM = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/wrf_hydro/source/trunk/NDHMS/Run/SOILPARM.TBL"))
DEFAULT_MPTABLE  = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/wrf_hydro/source/trunk/NDHMS/Run/MPTABLE.TBL"))

NSOIL = 4


def parse_soilparm(tbl_path):
    """Parse SOILPARM.TBL STAS section.

    Returns dict: soil_type_id (1-19) -> dict with keys:
        BB, DRYSMC, F11, MAXSMC, REFSMC, SATPSI, SATDK, SATDW, WLTSMC, QTZ
    """
    text = Path(tbl_path).read_text()
    lines = text.splitlines()
    params = {}
    in_stas = False
    for line in lines:
        s = line.strip()
        if s == "STAS":
            in_stas = True
            continue
        if s == "STAS-RUC":
            break
        if not in_stas:
            continue
        # Skip header / empty / section markers
        if s.startswith("'") or not s or s.startswith("Soil Parameters"):
            if params:
                break
            continue
        # Data: "1, 2.79, 0.010, -0.472, 0.339, 0.192, 0.069, 4.66E-5, 2.65E-5, 0.010, 0.92, 'SAND'"
        data_part = re.sub(r"'[^']*'", "", s).strip().rstrip(",")
        parts = [p.strip() for p in data_part.split(",") if p.strip()]
        if len(parts) >= 10:
            try:
                sid = int(parts[0])
                vals = [float(v) for v in parts[1:]]
                params[sid] = {
                    "BB": vals[0], "DRYSMC": vals[1], "F11": vals[2],
                    "MAXSMC": vals[3], "REFSMC": vals[4], "SATPSI": vals[5],
                    "SATDK": vals[6], "SATDW": vals[7], "WLTSMC": vals[8],
                    "QTZ": vals[9],
                }
            except (ValueError, IndexError):
                pass
    print(f"  Parsed {len(params)} soil types from SOILPARM.TBL")
    return params


def parse_mptable_usgs(tbl_path):
    """Parse MPTABLE.TBL &noahmp_usgs_parameters section.

    Returns dict: veg_type_id (1-27) -> dict with keys:
        CWPVT, HVT, MFSNO, VCMX25, MP
    """
    text = Path(tbl_path).read_text()
    lines = text.splitlines()

    # Find &noahmp_usgs_parameters section
    in_usgs = False
    in_modis = False
    params_raw = {}
    target_keys = {"CWPVT", "HVT", "MFSNO", "VCMX25", "MP"}

    for line in lines:
        s = line.strip()
        if "&noahmp_usgs_parameters" in s:
            in_usgs = True
            in_modis = False
            continue
        if "&noahmp_modis" in s:
            in_usgs = False
            in_modis = True
            continue
        if s == "/" and in_usgs:
            break  # end of section
        if not in_usgs:
            continue

        # Parse "KEY = val1, val2, ..."
        for key in target_keys:
            # Match "KEY =" or "KEY=" at start (case sensitive)
            pattern = rf"^{key}\s*="
            m = re.match(pattern, s)
            if m:
                val_str = s[m.end():]
                # Remove trailing comma, split
                vals_text = re.sub(r",\s*$", "", val_str)
                vals = []
                for v in vals_text.split(","):
                    v = v.strip().rstrip(",")
                    if v:
                        try:
                            vals.append(float(v))
                        except ValueError:
                            pass
                params_raw[key] = vals
                break

    # Build per-type dict
    n_veg = 27  # USGS
    veg_params = {}
    for i in range(n_veg):
        veg_id = i + 1
        d = {}
        for key in target_keys:
            if key in params_raw and i < len(params_raw[key]):
                d[key] = params_raw[key][i]
            else:
                d[key] = 0.0
        veg_params[veg_id] = d

    print(f"  Parsed {len(veg_params)} veg types from MPTABLE.TBL (USGS)")
    return veg_params


def build_soil_properties(geo_em_path, output_path,
                          soilparm_tbl=None, mptable_tbl=None, refkdt=0.8):
    """Build soil_properties.nc.

    refkdt : uniform REFKDT (infiltration vs surface-runoff split), the #1
             calibration knob. Default 0.8 is mountain/semi-arid tuned. For
             HUMID / FLAT basins (e.g. tropical plateau, plain) use 3.0 per
             SKILL.md's humid-basin recipe — 0.8 over-produces flashy surface
             runoff peaks there (Balsas 2026-07: REFKDT=0.8 gave sim std 5x obs,
             NSE=-18 despite r=0.68).
    """
    if soilparm_tbl is None:
        soilparm_tbl = DEFAULT_SOILPARM
    if mptable_tbl is None:
        mptable_tbl = DEFAULT_MPTABLE

    print(f"[build_soil_properties] Reading geo_em: {geo_em_path}")
    geo = nc.Dataset(geo_em_path, "r")

    sn = len(geo.dimensions["south_north"])
    we = len(geo.dimensions["west_east"])

    isltyp = geo["SCT_DOM"][0, :, :].astype(np.int32)
    ivgtyp = geo["LU_INDEX"][0, :, :].astype(np.int32)
    geo.close()

    print(f"  Grid: {sn} x {we}")
    print(f"  Soil types present: {np.unique(isltyp)}")
    print(f"  Veg types present: {np.unique(ivgtyp)}")

    # Parse tables
    sparams = parse_soilparm(soilparm_tbl)
    vparams = parse_mptable_usgs(mptable_tbl)

    # Allocate 4-layer soil arrays
    bexp   = np.zeros((NSOIL, sn, we), dtype=np.float32)
    smcmax = np.zeros((NSOIL, sn, we), dtype=np.float32)
    smcref = np.zeros((NSOIL, sn, we), dtype=np.float32)
    smcwlt = np.zeros((NSOIL, sn, we), dtype=np.float32)
    smcdry = np.zeros((NSOIL, sn, we), dtype=np.float32)
    dksat  = np.zeros((NSOIL, sn, we), dtype=np.float32)
    dwsat  = np.zeros((NSOIL, sn, we), dtype=np.float32)
    psisat = np.zeros((NSOIL, sn, we), dtype=np.float32)
    quartz = np.zeros((NSOIL, sn, we), dtype=np.float32)

    # 2D arrays
    slope    = np.full((sn, we), 0.1,  dtype=np.float32)
    refdk    = np.zeros((sn, we), dtype=np.float32)
    refkdt   = np.full((sn, we), float(refkdt),  dtype=np.float32)  # default 0.8 mountain; 3.0 for humid/flat (SKILL humid recipe)
    rsurfexp = np.full((sn, we), 5.0,  dtype=np.float32)

    # Vegetation arrays
    cwpvt  = np.zeros((sn, we), dtype=np.float32)
    hvt    = np.zeros((sn, we), dtype=np.float32)
    mfsno  = np.zeros((sn, we), dtype=np.float32)
    mp     = np.zeros((sn, we), dtype=np.float32)
    vcmx25 = np.zeros((sn, we), dtype=np.float32)

    # Default soil fallback (type 6 = Loam)
    default_soil = sparams.get(6, sparams.get(1, {}))
    # Default veg fallback (type 7 = Grassland)
    default_veg = vparams.get(7, vparams.get(1, {}))

    for j in range(sn):
        for i in range(we):
            # Soil lookup
            st = int(isltyp[j, i])
            sp = sparams.get(st, default_soil)
            for k in range(NSOIL):
                bexp[k, j, i]   = sp.get("BB", 0.0)
                smcmax[k, j, i] = sp.get("MAXSMC", 0.0)
                smcref[k, j, i] = sp.get("REFSMC", 0.0)
                smcwlt[k, j, i] = sp.get("WLTSMC", 0.0)
                smcdry[k, j, i] = sp.get("DRYSMC", 0.0)
                dksat[k, j, i]  = sp.get("SATDK", 0.0)
                dwsat[k, j, i]  = sp.get("SATDW", 0.0)
                psisat[k, j, i] = sp.get("SATPSI", 0.0)
                quartz[k, j, i] = sp.get("QTZ", 0.0)
            refdk[j, i] = sp.get("SATDK", 0.0)

            # Vegetation lookup
            vt = int(ivgtyp[j, i])
            vp = vparams.get(vt, default_veg)
            cwpvt[j, i]  = vp.get("CWPVT", 0.18)
            hvt[j, i]    = vp.get("HVT", 0.0)
            mfsno[j, i]  = vp.get("MFSNO", 2.5)
            mp[j, i]     = vp.get("MP", 9.0)
            vcmx25[j, i] = vp.get("VCMX25", 0.0)

    # --- Write output ---
    print(f"  Writing: {output_path}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out = nc.Dataset(output_path, "w", format="NETCDF4")

    out.createDimension("Time", 1)
    out.createDimension("soil_layers_stag", NSOIL)
    out.createDimension("south_north", sn)
    out.createDimension("west_east", we)

    def write_soil(name, data, **attrs):
        v = out.createVariable(name, "f4",
                               ("Time", "soil_layers_stag", "south_north", "west_east"),
                               fill_value=False)
        for k, val in attrs.items():
            v.setncattr(k, val)
        v[0, :, :, :] = data

    def write_2d(name, data, **attrs):
        v = out.createVariable(name, "f4",
                               ("Time", "south_north", "west_east"),
                               fill_value=False)
        for k, val in attrs.items():
            v.setncattr(k, val)
        v[0, :, :] = data

    # Write in alphabetical order to match reference
    write_soil("bexp", bexp)
    write_2d("cwpvt", cwpvt)
    write_soil("dksat", dksat)
    write_soil("dwsat", dwsat)
    write_2d("hvt", hvt)
    write_2d("mfsno", mfsno)
    write_2d("mp", mp)
    write_soil("psisat", psisat)
    write_soil("quartz", quartz)
    write_2d("refdk", refdk)
    write_2d("refkdt", refkdt)
    write_2d("rsurfexp", rsurfexp)
    write_2d("slope", slope)
    write_soil("smcdry", smcdry)
    write_soil("smcmax", smcmax)
    write_soil("smcref", smcref)
    write_soil("smcwlt", smcwlt)
    write_2d("vcmx25", vcmx25)

    out.close()
    print(f"  [OK] soil_properties.nc created: Time=1, soil_layers={NSOIL}, "
          f"south_north={sn}, west_east={we}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Build soil_properties.nc for WRF-Hydro")
    parser.add_argument("--geo_em", required=True, help="Path to geo_em.d01.nc")
    parser.add_argument("--output_path", required=True, help="Output soil_properties.nc path")
    parser.add_argument("--soilparm_tbl", default=str(DEFAULT_SOILPARM),
                        help="Path to SOILPARM.TBL")
    parser.add_argument("--mptable_tbl", default=str(DEFAULT_MPTABLE),
                        help="Path to MPTABLE.TBL")
    parser.add_argument("--refkdt", type=float, default=0.8,
                        help="Uniform REFKDT (infiltration/surface-runoff split). "
                             "Default 0.8 (mountain/semi-arid). Use 3.0 for humid/flat basins.")
    args = parser.parse_args()

    build_soil_properties(
        geo_em_path=args.geo_em,
        output_path=args.output_path,
        soilparm_tbl=args.soilparm_tbl,
        mptable_tbl=args.mptable_tbl,
        refkdt=args.refkdt,
    )


if __name__ == "__main__":
    main()
