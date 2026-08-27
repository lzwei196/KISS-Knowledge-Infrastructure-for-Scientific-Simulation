#!/usr/bin/env python3
"""
Configure CLM (Community Land Model) coupling for ParFlow.

Generates:
- drv_clmin.dat: CLM driver configuration (timestep, output, options)
- drv_vegm.dat: Vegetation type map (IGBP class per grid cell)
- drv_vegp.dat: Vegetation parameter file (LAI, SAI, z0 per PFT)

CLM provides the land surface boundary condition for ParFlow:
evapotranspiration, snow, canopy interception, radiation balance.

Usage:
    python setup_clm_driver.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --surface_mask_npy outputs/parflow_run/domain/surface_mask.npy \
        --start_date 2000-01-01 --end_date 2010-12-31 \
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


def generate_drv_vegm(output_dir, nx, ny, vegtype_map, mask_2d, lat_map, lon_map):
    """Generate drv_vegm.dat vegetation type map."""
    path = os.path.join(output_dir, "drv_vegm.dat")
    with open(path, "w") as f:
        # CLM's drv_readvegtf skips exactly two header lines, then reads
        # "x y lat lon sand clay color frac1..frac18" per cell (washita format)
        f.write(" x  y   lat     lon    sand clay color  fractional coverage of grid by vegetation class (Must/Should Add to 1.0)\n")
        f.write("        (Deg)   (Deg)    (%/100)  index  1    2    3    4    5    6    7    8    9   10  11  12   13   14   15   16   17   18\n")
        for j in range(ny):
            for i in range(nx):
                if mask_2d[j, i] == 0:
                    vt = 17  # Water for inactive
                else:
                    vt = int(vegtype_map[j, i])
                # Write: x y lat lon sand clay color frac1 frac2 ... frac18
                lat = lat_map[j, i] if lat_map is not None else 0.0
                lon = lon_map[j, i] if lon_map is not None else 0.0
                fracs = [0.0] * 18
                if vt >= 1 and vt <= 17:
                    fracs[vt - 1] = 1.0
                frac_str = " ".join(f"{v:.2f}" for v in fracs)
                f.write(f"{i+1} {j+1} {lat:.4f} {lon:.4f} "
                        f"0.40 0.20 4 {frac_str}\n")
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


def process(domain_json, surface_mask_npy, start_date, end_date, output_dir,
            dt_seconds=3600, run_name="parflow_run", startcode=2):
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_2d = np.load(surface_mask_npy)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    # Build vegetation type map
    vegtype = np.full((ny, nx), 10, dtype=np.int32)  # Default: grassland

    # Try AVHRR lookup
    if not os.path.exists(AVHRR_FILE):
        # all-default grassland veg silently kills spatial ET (dt_pf_030 class)
        raise FileNotFoundError(f"AVHRR land cover not found: {AVHRR_FILE}")
    avhrr_file = AVHRR_FILE

    lat_map = np.zeros((ny, nx))
    lon_map = np.zeros((ny, nx))
    transformer = Transformer.from_crs(
        f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
    )

    for j in range(ny):
        for i in range(nx):
            cx = origin_x + (i + 0.5) * dx
            cy = origin_y + (j + 0.5) * dy
            lo, la = transformer.transform(cx, cy)
            lat_map[j, i] = la
            lon_map[j, i] = lo

    if avhrr_file:
        with rasterio.open(avhrr_file) as src:
            for j in range(ny):
                for i in range(nx):
                    if mask_2d[j, i] == 0:
                        continue
                    try:
                        row, col = src.index(lon_map[j, i], lat_map[j, i])
                        lc = int(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                        vegtype[j, i] = AVHRR_TO_IGBP.get(lc, 10)
                    except Exception:
                        vegtype[j, i] = 10

    # Generate CLM files
    met_prefix = "NLDAS"
    clmin_path = generate_drv_clmin(output_dir, nx, ny, dt_seconds,
                                     start_date, end_date, run_name, met_prefix,
                                     startcode=startcode)
    vegm_path = generate_drv_vegm(output_dir, nx, ny, vegtype, mask_2d,
                                   lat_map, lon_map)
    vegp_path = generate_drv_vegp(output_dir)

    result = {
        "status": "success",
        "files": {
            "drv_clmin": clmin_path,
            "drv_vegm": vegm_path,
            "drv_vegp": vegp_path,
        },
        "clm_timestep_seconds": dt_seconds,
        "grid": {"nx": nx, "ny": ny},
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
    args = parser.parse_args()

    result = process(args.domain_json, args.surface_mask_npy,
                     args.start_date, args.end_date, args.output_dir,
                     args.dt_seconds, args.run_name, args.startcode)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
