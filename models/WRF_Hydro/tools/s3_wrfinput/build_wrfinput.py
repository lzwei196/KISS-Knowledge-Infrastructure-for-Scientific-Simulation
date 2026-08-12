#!/usr/bin/env python3
"""
build_wrfinput.py  --  WRF-Hydro Phase 2, Tool 1
=================================================
Build wrfinput_d01.nc from geo_em.d01.nc, adding initial conditions
(soil moisture, soil temperature, snow, canopy water) and surface fields
required by Noah-MP.

The script:
  1. Reads geo_em variables: XLAT_M, XLONG_M, HGT_M, LU_INDEX, SCT_DOM,
     MAPFAC_MX, MAPFAC_MY, GREENFRAC, LAI12M, SOILTEMP, LANDMASK
  2. Renames per WRF-Hydro convention (HGT_M->HGT, XLAT_M->XLAT, etc.)
  3. Adds soil layers (DZS, ZS), initial soil moisture (SMOIS from
     SOILPARM.TBL REFSMC), initial soil temperature (TSLB interpolated
     TSK->TMN), and static defaults (SNOW, CANWAT, SEAICE, XLAND, TSK).
  4. Copies all geo_em global attributes.

Usage
-----
    python build_wrfinput.py \\
        --geo_em  outputs/chaohe_wrf_test/DOMAIN/geo_em.d01.nc \\
        --output_path outputs/chaohe_wrf_test/DOMAIN/wrfinput_d01.nc \\
        --start_month 1

Data sources
------------
- SOILPARM.TBL: STAS section for REFSMC per soil type
"""

import argparse
import os
import re
import sys
from pathlib import Path

import netCDF4 as nc
import numpy as np


# ===================================================================
# Constants
# ===================================================================
DZS = np.array([0.1, 0.3, 0.6, 1.0], dtype=np.float32)  # layer thickness (m)
ZS  = np.array([0.05, 0.25, 0.70, 1.50], dtype=np.float32)  # layer midpoint depth (m)
TSK_DEFAULT = 290.0  # skin temperature (K)
NSOIL = 4

DEFAULT_SOILPARM = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/wrf_hydro/source/trunk/NDHMS/Run/SOILPARM.TBL"))


def parse_soilparm_tbl(tbl_path):
    """Parse SOILPARM.TBL STAS section for per-type parameters.

    Returns dict: soil_type_id (1-19) -> dict of parameter values.
    Columns: BB, DRYSMC, F11, MAXSMC, REFSMC, SATPSI, SATDK, SATDW, WLTSMC, QTZ
    """
    text = Path(tbl_path).read_text()
    lines = text.splitlines()

    soil_params = {}
    # Find the first STAS section (not STAS-RUC)
    in_stas = False
    header_cols = None
    for line in lines:
        stripped = line.strip()
        if stripped == "STAS":
            in_stas = True
            continue
        if stripped == "STAS-RUC":
            break  # stop at RUC section
        if not in_stas:
            continue
        if stripped.startswith("'") and "BB" in stripped:
            # Header line: parse column names
            header_cols = [c.strip().strip("'") for c in stripped.split()]
            continue
        if not stripped or stripped.startswith("Soil Parameters"):
            if soil_params:
                break  # end of STAS section data
            continue

        # Data line: "1, 2.79, 0.010, ..."
        # Remove trailing soil name in quotes
        data_part = re.sub(r"'[^']*'", "", stripped).strip().rstrip(",")
        parts = [p.strip() for p in data_part.split(",") if p.strip()]
        if len(parts) >= 10:
            try:
                sid = int(parts[0])
                vals = [float(v) for v in parts[1:]]
                soil_params[sid] = {
                    "BB": vals[0], "DRYSMC": vals[1], "F11": vals[2],
                    "MAXSMC": vals[3], "REFSMC": vals[4], "SATPSI": vals[5],
                    "SATDK": vals[6], "SATDW": vals[7], "WLTSMC": vals[8],
                    "QTZ": vals[9],
                }
            except (ValueError, IndexError):
                pass

    if not soil_params:
        raise RuntimeError(f"Failed to parse any soil types from {tbl_path}")
    print(f"  Parsed {len(soil_params)} soil types from SOILPARM.TBL (STAS)")
    return soil_params


def build_wrfinput(geo_em_path, output_path, start_month=1, soilparm_tbl=None):
    """Build wrfinput_d01.nc from geo_em.d01.nc."""

    if soilparm_tbl is None:
        soilparm_tbl = DEFAULT_SOILPARM

    print(f"[build_wrfinput] Reading geo_em: {geo_em_path}")
    geo = nc.Dataset(geo_em_path, "r")

    sn = len(geo.dimensions["south_north"])
    we = len(geo.dimensions["west_east"])
    print(f"  Grid: south_north={sn}, west_east={we}")

    # Read geo_em fields
    xlat   = geo["XLAT_M"][0, :, :]
    xlong  = geo["XLONG_M"][0, :, :]
    hgt    = geo["HGT_M"][0, :, :]
    lu_idx = geo["LU_INDEX"][0, :, :].astype(np.int32)
    sct    = geo["SCT_DOM"][0, :, :].astype(np.int32)
    mfx    = geo["MAPFAC_MX"][0, :, :]
    mfy    = geo["MAPFAC_MY"][0, :, :]
    gf     = geo["GREENFRAC"][0, :, :, :]  # (month, sn, we)
    lai12  = geo["LAI12M"][0, :, :, :]     # (month, sn, we)
    soilt  = geo["SOILTEMP"][0, :, :]
    lmask  = geo["LANDMASK"][0, :, :]

    # Parse soil table
    print(f"  Parsing SOILPARM.TBL: {soilparm_tbl}")
    sparams = parse_soilparm_tbl(soilparm_tbl)

    # --- Derived fields ---
    # IVGTYP = LU_INDEX as int
    ivgtyp = lu_idx.copy()

    # ISLTYP = SCT_DOM as int
    isltyp = sct.copy()

    # XLAND: 2=water (LU_INDEX=16 for USGS), 1=land
    xland = np.where(lu_idx == 16, 2, 1).astype(np.int32)

    # LAI for start month (0-indexed)
    month_idx = max(0, min(11, start_month - 1))
    lai = lai12[month_idx, :, :].astype(np.float32)

    # SHDMAX, SHDMIN from GREENFRAC (0-1 in geo_em -> 0-100 %)
    shdmax = np.max(gf, axis=0).astype(np.float32) * 100.0
    shdmin = np.min(gf, axis=0).astype(np.float32) * 100.0
    # dt_v005 fix: barren / high-altitude land cells with SHDMAX=0 and VAI=0 drive
    # Noah-MP ground temperature to ~630 K in summer and abort the run. Enforce a
    # small minimum green fraction (0.01 = 1%) on LAND cells (IVGTYP != water=16).
    land2d = lu_idx != 16
    shdmax[land2d & (shdmax < 1.0)] = 1.0
    shdmin = np.minimum(shdmin, shdmax)

    # TMN = SOILTEMP (annual mean deep-soil temperature, K)
    # Fix zero/missing values: SOILTEMP=0 means nodata (water cells etc.)
    tmn = soilt.astype(np.float32)
    tmn[tmn < 200.0] = TSK_DEFAULT  # replace unphysical values with TSK default

    # TSK = constant 290 K
    tsk = np.full((sn, we), TSK_DEFAULT, dtype=np.float32)

    # SMOIS: from SOILPARM REFSMC for each cell's soil type, 4 layers identical
    smois = np.zeros((NSOIL, sn, we), dtype=np.float32)
    for j in range(sn):
        for i in range(we):
            st = int(isltyp[j, i])
            if st in sparams:
                smois[:, j, i] = sparams[st]["REFSMC"]
            else:
                # Default: use type 6 (Loam) as fallback
                smois[:, j, i] = sparams.get(6, {}).get("REFSMC", 0.329)

    # TSLB: interpolate from TSK (surface) to TMN (deep)
    # Layer fractions: ZS / max_depth
    max_depth = ZS[-1] + DZS[-1] / 2.0  # ~ 2.0 m
    tslb = np.zeros((NSOIL, sn, we), dtype=np.float32)
    for k in range(NSOIL):
        frac = ZS[k] / max_depth
        tslb[k, :, :] = tsk * (1.0 - frac) + tmn * frac

    # SNOW, CANWAT, SEAICE = 0
    zeros = np.zeros((sn, we), dtype=np.float32)

    # --- Write output ---
    print(f"  Writing wrfinput: {output_path}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out = nc.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    out.createDimension("Time", 1)
    out.createDimension("south_north", sn)
    out.createDimension("west_east", we)
    out.createDimension("soil_layers_stag", NSOIL)

    # Copy ALL global attributes from geo_em
    for attr in geo.ncattrs():
        out.setncattr(attr, geo.getncattr(attr))

    # Helper to create a 2D (Time, sn, we) variable
    def write_2d(name, data, dtype="f4", **attrs):
        v = out.createVariable(name, dtype, ("Time", "south_north", "west_east"),
                               fill_value=False)
        for k, val in attrs.items():
            v.setncattr(k, val)
        v[0, :, :] = data

    # Helper to create 3D (Time, soil_layers_stag, sn, we) variable
    def write_soil(name, data, **attrs):
        v = out.createVariable(name, "f4",
                               ("Time", "soil_layers_stag", "south_north", "west_east"),
                               fill_value=False)
        for k, val in attrs.items():
            v.setncattr(k, val)
        v[0, :, :, :] = data

    # Write variables in same order as reference
    write_2d("CANWAT", zeros, units="kg/m^2")
    # DZS
    v_dzs = out.createVariable("DZS", "f4", ("Time", "soil_layers_stag"), fill_value=False)
    v_dzs.units = "m"
    v_dzs[0, :] = DZS

    write_2d("HGT", hgt, units="meters MSL", description="Topography height")
    write_2d("ISLTYP", isltyp, dtype="i4")
    write_2d("IVGTYP", ivgtyp, dtype="f4", units="category", description="Dominant category")
    write_2d("LAI", lai, units="m^2/m^2")
    write_2d("MAPFAC_MX", mfx, units="none", description="Mapfactor (x-dir) on mass grid")
    write_2d("MAPFAC_MY", mfy, units="none", description="Mapfactor (y-dir) on mass grid")
    write_2d("SEAICE", zeros)
    write_2d("SHDMAX", shdmax, units="%")
    write_2d("SHDMIN", shdmin, units="%")
    write_soil("SMOIS", smois, units="m^3/m^3")
    write_2d("SNOW", zeros, units="kg/m^2")
    write_2d("TMN", tmn, units="K")
    write_2d("TSK", tsk, units="K")
    write_soil("TSLB", tslb, units="K")
    write_2d("XLAND", xland, dtype="i4")
    write_2d("XLAT", xlat, units="degrees latitude", description="Latitude on mass grid")
    write_2d("XLONG", xlong, units="degrees longitude", description="Longitude on mass grid")

    # ZS
    v_zs = out.createVariable("ZS", "f4", ("Time", "soil_layers_stag"), fill_value=False)
    v_zs.units = "m"
    v_zs[0, :] = ZS

    out.close()
    geo.close()
    print(f"  [OK] wrfinput_d01.nc created: {sn}x{we}, {NSOIL} soil layers")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Build wrfinput_d01.nc from geo_em.d01.nc")
    parser.add_argument("--geo_em", required=True,
                        help="Path to geo_em.d01.nc")
    parser.add_argument("--output_path", required=True,
                        help="Output wrfinput_d01.nc path")
    parser.add_argument("--start_month", type=int, default=1,
                        help="Start month (1-12) for LAI selection (default: 1)")
    parser.add_argument("--soilparm_tbl",
                        default=str(DEFAULT_SOILPARM),
                        help="Path to SOILPARM.TBL")
    args = parser.parse_args()

    build_wrfinput(
        geo_em_path=args.geo_em,
        output_path=args.output_path,
        start_month=args.start_month,
        soilparm_tbl=args.soilparm_tbl,
    )


if __name__ == "__main__":
    main()
