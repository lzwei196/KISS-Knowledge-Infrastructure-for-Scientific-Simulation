#!/usr/bin/env python3
"""
Configure CLM (Community Land Model) coupling for ParFlow.

Generates:
- drv_clmin.dat: CLM driver configuration (timestep, output, options)
- drv_vegm.dat: per cell lat/lon, HWSD topsoil sand/clay fractions, the
  user-chosen soil colour class, and the AVHRR->IGBP vegetation class, for
  EVERY cell of the Box grid (inside and outside the basin mask). Any cell
  without land cover or soil stops the tool; there are no default values.
- drv_vegp.dat: Vegetation parameter file (LAI, SAI, z0 per PFT)

CLM provides the land surface boundary condition for ParFlow:
evapotranspiration, snow, canopy interception, radiation balance.

Usage:
    python setup_clm_driver.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --surface_mask_npy outputs/parflow_run/domain/surface_mask.npy \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --soil_color N  (CLM colour class 1-8 that you choose; no default) \
        --output_dir outputs/parflow_run/clm/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import rasterio
    from pyproj import Transformer
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


HYDROCRAFT_ROOT = "KISSPATH_ROOT"
# data/forcing/AVHRR never existed on this server; the global AVHRR land
# cover file lives under data/landcover/. Globbing a directory here is unsafe
# (data/landcover also holds CLCD/ESA-CCI tifs) -- pin the exact file.
AVHRR_FILE = os.path.join(
    HYDROCRAFT_ROOT, "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif")
# Global HWSD raster (same file as s2 build_subsurface_properties.py); with
# HWSD_DATA.csv it gives the per-cell topsoil sand/clay written to drv_vegm.dat.
HWSD_RASTER = os.path.join(HYDROCRAFT_ROOT, "data/soil/HWSD_RASTER/hwsd.bil")

# AVHRR 1km 1981-1994 (Hansen/UMD) -> IGBP mapping for CLM.
# The raster's legend is the UMD 14-class scheme (verified from its .vat.dbf:
# values 0-13(+14), value 12 = bare ground globally dominant), NOT IGBP.
# The previous identity mapping silently turned UMD 11 'cropland' into IGBP 11
# 'permanent wetland' and UMD 6 'woodland' into 'closed shrubland'.
AVHRR_TO_IGBP = {
    0: 17,   # Water -> Water Bodies
    1: 1,    # Evergreen Needleleaf -> ENF
    2: 2,    # Evergreen Broadleaf -> EBF
    3: 3,    # Deciduous Needleleaf -> DNF
    4: 4,    # Deciduous Broadleaf -> DBF
    5: 5,    # Mixed Forest
    6: 8,    # Woodland -> Woody Savannas
    7: 9,    # Wooded Grassland -> Savannas
    8: 6,    # Closed Shrubland
    9: 7,    # Open Shrubland
    10: 10,  # Grassland
    11: 12,  # Cropland
    12: 16,  # Bare Ground -> Barren
    13: 13,  # Urban
    14: 16,  # (rare fill class) -> Barren
}



def generate_drv_clmin(output_dir, nx, ny, dt_seconds, start_date, end_date,
                       run_name, met_prefix, startcode=2):
    """Generate drv_clmin.dat with the key set CLM's drv_readclmin.f90 actually
    reads, mirroring the shipped working reference
    parflow/source/test/tcl/washita/clm_input/drv_clmin.dat.

    The previous version emitted invented keys ('maession', 'clm_nx', 'vegp',
    'vegm', 'ts', ...) that CLM never parses, while omitting required ones
    (maxt, vclass, vegtf, vegpf, timing fields in CLM's fixed format).

    startcode/clm_ic: 2 = cold defined ICs, 1 = restart from clm.rst files.
    """
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "workflow", "drv_clmin_template.dat")
    with open(tmpl) as f:
        body = f.read().format(
            met_prefix=met_prefix, startcode=startcode,
            sda=f"{s.day:02d}", smo=f"{s.month:02d}", syr=s.year,
            eda=f"{e.day:02d}", emo=f"{e.month:02d}", eyr=e.year)
    path = os.path.join(output_dir, "drv_clmin.dat")
    with open(path, "w") as f:
        f.write(body)
    return path


def generate_drv_vegm(output_dir, nx, ny, vegtype_map, sand_map, clay_map,
                      soil_color, lat_map, lon_map):
    """Write drv_vegm.dat: one line per cell, every cell of the grid.

    CLM's drv_readvegtf.F90 skips exactly two header lines, then reads
    "x y lat lon sand clay color frac1..frac18" per cell, rows (y) outer and
    columns (x) inner (washita format). sand and clay are FRACTIONS (0-1);
    drv_clmini.F90 multiplies them by 100 for bsw/sucsat/xksat and the soil
    thermal properties. color is the CLM soil colour class (clm_varcon.F90
    albsat/albdry tables, classes 1-8) used by clm_soilalb.F90.
    """
    path = os.path.join(output_dir, "drv_vegm.dat")
    with open(path, "w") as f:
        f.write(" x  y   lat     lon    sand clay color  fractional coverage of grid by vegetation class (Must/Should Add to 1.0)\n")
        f.write("        (Deg)   (Deg)    (%/100)  index  1    2    3    4    5    6    7    8    9   10  11  12   13   14   15   16   17   18\n")
        for j in range(ny):
            for i in range(nx):
                vt = int(vegtype_map[j, i])
                if not 1 <= vt <= 18:
                    raise ValueError(f"cell (i={i}, j={j}) has no IGBP class ({vt})")
                fracs = [0.0] * 18
                fracs[vt - 1] = 1.0
                frac_str = " ".join(f"{v:.2f}" for v in fracs)
                f.write(f"{i+1} {j+1} {lat_map[j, i]:.4f} {lon_map[j, i]:.4f} "
                        f"{sand_map[j, i]:.4f} {clay_map[j, i]:.4f} {int(soil_color)} "
                        f"{frac_str}\n")
    return path


SHIPPED_VEGP = os.path.join(
    HYDROCRAFT_ROOT,
    "model/parflow/source/test/tcl/washita/clm_input/drv_vegp.dat")


def generate_drv_vegp(output_dir):
    """Stage the SHIPPED IGBP drv_vegp.dat (parflow source, washita example).

    CLM's drv_getvegp.f90 reads a named-parameter file (~40 parameters x 18
    classes). The 7-column table this tool previously generated is not that
    format and CLM cannot parse it; the shipped file is the validated input.
    """
    import shutil
    if not os.path.exists(SHIPPED_VEGP):
        raise FileNotFoundError(
            f"Shipped drv_vegp.dat not found: {SHIPPED_VEGP} -- "
            "CLM cannot run without a valid vegetation parameter file")
    path = os.path.join(output_dir, "drv_vegp.dat")
    shutil.copyfile(SHIPPED_VEGP, path)
    return path


def _load_s2_module():
    """The s2 tool's HWSD reader (same raster, same dominant-row rule), so
    CLM sand/clay come from exactly the soil that gives ParFlow its
    hydraulic classes."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "s2_subsurface", "build_subsurface_properties.py")
    spec = importlib.util.spec_from_file_location("parflow_s2_subsurface", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fail_report(what, failures):
    n_out = sum(1 for f in failures if not f[4])
    lines = [f"  cell (i={i}, j={j}) lon={lon:.5f} lat={lat:.5f} "
             f"{'inside' if m else 'OUTSIDE'} basin mask: {why}"
             for i, j, lon, lat, m, why in failures[:10]]
    return (f"{what} for {len(failures)} cell(s) ({n_out} outside the basin mask); no "
            f"default value is used. The run script uses Box geometry, so every cell of "
            f"the rectangle is simulated by CLM and needs real data: shrink/move the domain "
            f"rectangle or fix the data source. First {len(lines)}:\n" + "\n".join(lines))


def process(domain_json, surface_mask_npy, start_date, end_date, output_dir,
            dt_seconds=3600, run_name="parflow_run", startcode=2, soil_color=None):
    # Soil colour: no soil-colour map exists on this server, so it must be
    # chosen by the user (CLM classes 1 light .. 8 dark); never invented here.
    if soil_color is None or isinstance(soil_color, bool) or int(soil_color) != soil_color \
            or not 1 <= int(soil_color) <= 8:
        raise ValueError(f"soil_color must be a CLM soil colour class 1-8 chosen by the user "
                         f"(--soil_color); got {soil_color!r}. There is no default.")
    soil_color = int(soil_color)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_2d = np.load(surface_mask_npy)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]
    if mask_2d.shape != (ny, nx):
        raise ValueError(f"surface mask shape {mask_2d.shape} does not match grid ({ny}, {nx})")

    if not os.path.exists(AVHRR_FILE):
        # all-default grassland veg silently kills spatial ET (dt_pf_030 class)
        raise FileNotFoundError(f"AVHRR land cover not found: {AVHRR_FILE}")
    if not os.path.exists(HWSD_RASTER):
        raise FileNotFoundError(f"HWSD raster not found: {HWSD_RASTER}")
    s2 = _load_s2_module()
    hwsd_dom = s2.load_hwsd_dominant(HYDROCRAFT_ROOT)

    transformer = Transformer.from_crs(
        f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
    )
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny))
    lon_map, lat_map = transformer.transform(origin_x + (ii + 0.5) * dx,
                                             origin_y + (jj + 0.5) * dy)
    lon_map, lat_map = np.asarray(lon_map), np.asarray(lat_map)

    # EVERY cell of the Box gets its own land cover and soil (inside and
    # outside the basin mask): the s7 run script uses Box geometry, so CLM
    # computes every cell. There is no default class and no default soil.
    vegtype = np.zeros((ny, nx), dtype=np.int32)
    sand = np.full((ny, nx), np.nan)
    clay = np.full((ny, nx), np.nan)
    lc_fail, soil_fail = [], []
    with rasterio.open(AVHRR_FILE) as lc_src, rasterio.open(HWSD_RASTER) as hwsd_src:
        for j in range(ny):
            for i in range(nx):
                lo, la = float(lon_map[j, i]), float(lat_map[j, i])
                in_mask = bool(mask_2d[j, i] != 0)
                try:
                    row, col = lc_src.index(lo, la)
                    if not (0 <= row < lc_src.height and 0 <= col < lc_src.width):
                        raise ValueError(f"outside the AVHRR raster (row {row}, col {col})")
                    lc = int(lc_src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                    if lc_src.nodata is not None and lc == lc_src.nodata:
                        raise ValueError(f"AVHRR nodata ({lc})")
                    if lc not in AVHRR_TO_IGBP:
                        raise ValueError(f"AVHRR value {lc} has no IGBP mapping")
                    vegtype[j, i] = AVHRR_TO_IGBP[lc]
                except Exception as exc:
                    lc_fail.append((i, j, lo, la, in_mask, str(exc)))
                try:
                    vals, _mu = s2.sample_hwsd_topsoil(hwsd_src, hwsd_dom, lo, la)
                    sa, cl = vals["T_SAND"] / 100.0, vals["T_CLAY"] / 100.0
                    if not (0.0 <= sa <= 1.0 and 0.0 <= cl <= 1.0 and sa + cl <= 1.0 + 1e-6
                            and sa + cl > 0.0):
                        raise s2.NoHwsdSoil(f"MU_GLOBAL {_mu} sand {sa} / clay {cl} "
                                            f"is not a valid fraction pair")
                    sand[j, i], clay[j, i] = sa, cl
                except s2.NoHwsdSoil as exc:
                    soil_fail.append((i, j, lo, la, in_mask, str(exc)))
    problems = []
    if lc_fail:
        problems.append(_fail_report("AVHRR gave no land-cover class", lc_fail))
    if soil_fail:
        problems.append(_fail_report("HWSD gave no topsoil sand/clay", soil_fail))
    if problems:
        raise ValueError("\n".join(problems))
    if np.any(vegtype == 0) or not (np.isfinite(sand).all() and np.isfinite(clay).all()):
        raise RuntimeError("internal error: a cell has no land cover or soil after sampling")

    # Generate CLM files (only after every cell has real data)
    os.makedirs(output_dir, exist_ok=True)
    met_prefix = "NLDAS"
    clmin_path = generate_drv_clmin(output_dir, nx, ny, dt_seconds,
                                     start_date, end_date, run_name, met_prefix,
                                     startcode=startcode)
    vegm_path = generate_drv_vegm(output_dir, nx, ny, vegtype, sand, clay,
                                   soil_color, lat_map, lon_map)
    vegp_path = generate_drv_vegp(output_dir)

    classes, counts = np.unique(vegtype, return_counts=True)
    provenance = {
        "landcover_source": f"{AVHRR_FILE} (UMD classes mapped to IGBP), every cell",
        "soil_source": (f"{HWSD_RASTER} + HWSD_DATA.csv dominant component (largest SHARE, "
                        f"ties -> lowest SEQ) topsoil T_SAND/T_CLAY (0-30 cm) / 100, every "
                        f"cell; same reader as s2. CLM applies this one value to all its "
                        f"soil layers."),
        "soil_color": {"value": soil_color,
                       "source": "user-supplied (--soil_color); the same class in every "
                                 "cell. No soil-colour map is on this server, so this is a "
                                 "stated assumption, not data."},
        "cells": nx * ny,
        "cells_outside_mask": int(np.sum(mask_2d == 0)),
        "igbp_class_counts": {int(c): int(n) for c, n in zip(classes, counts)},
        "sand_fraction": {"min": float(sand.min()), "max": float(sand.max()),
                          "mean": float(sand.mean())},
        "clay_fraction": {"min": float(clay.min()), "max": float(clay.max()),
                          "mean": float(clay.mean())},
    }
    prov_path = os.path.join(output_dir, "clm_provenance.json")
    with open(prov_path, "w") as f:
        json.dump(provenance, f, indent=2)

    result = {
        "status": "success",
        "files": {
            "drv_clmin": clmin_path,
            "drv_vegm": vegm_path,
            "drv_vegp": vegp_path,
            "clm_provenance": prov_path,
        },
        "clm_timestep_seconds": dt_seconds,
        "grid": {"nx": nx, "ny": ny},
        "provenance": provenance,
        "stated_assumptions": [
            f"soil colour class {soil_color} (user-supplied) in every cell; not from data"],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Setup CLM driver for ParFlow")
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--surface_mask_npy", required=True)
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--dt_seconds", type=int, default=3600)
    parser.add_argument("--run_name", default="parflow_run")
    parser.add_argument("--startcode", type=int, default=2,
                        help="2=cold defined ICs, 1=restart from clm.rst")
    parser.add_argument("--soil_color", type=int, required=True, choices=range(1, 9),
                        metavar="{1..8}",
                        help="CLM soil colour class (1 = lightest .. 8 = darkest; "
                             "clm_varcon.F90 albsat/albdry). REQUIRED, no default: there is "
                             "no soil-colour map on this server, so you choose it; it is "
                             "written to every cell and recorded as a stated assumption")
    args = parser.parse_args()

    try:
        result = process(args.domain_json, args.surface_mask_npy,
                         args.start_date, args.end_date, args.output_dir,
                         args.dt_seconds, args.run_name, args.startcode,
                         soil_color=args.soil_color)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}))
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
