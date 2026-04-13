#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      generate_latlon_files
Stage:        s1_domain
Description:  Create lat/lon NetCDF file for mHM domain at L0, L1, and L11 resolutions.

mHM requires a latlon NetCDF file (file_LatLon in mhm.nml) with 2D arrays
of latitude and longitude at ALL three resolution levels:
  - lat_l0 / lon_l0  (L0 = morphological)
  - lat / lon         (L1 = hydrological model)
  - lat_l11 / lon_l11 (L11 = routing)

CRITICAL: Dimension names must be yc_l0/xc_l0 for L0, yc/xc for L1,
yc_l11/xc_l11 for L11 — matching the convention from working mHM runs.
The first dimension (yc) = nrows (lat direction), second (xc) = ncols (lon direction).

Inputs:
  - CONFIG_PATH: config.json
  - DOMAIN_INFO_PATH: domain_info.json (with header_L0, header_L1, header_L11)

Outputs:
  - latlon_1.nc in input/latlon/
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

try:
    import netCDF4 as nc4
    _HAS_NC4 = True
except ImportError:
    _HAS_NC4 = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if not _HAS_NC4:
        errors.append("netCDF4 not installed — required for latlon NC generation")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def make_latlon_2d(header):
    """Generate 2D lat/lon arrays for an mHM grid level.

    Returns (lat_2d, lon_2d) with shape (nrows, ncols).
    lat_2d[0,:] = northernmost row, lat_2d[-1,:] = southernmost.
    """
    nrows = header["nrows"]
    ncols = header["ncols"]
    xll = header["xllcorner"]
    yll = header["yllcorner"]
    cs = header["cellsize"]

    lat_2d = np.zeros((nrows, ncols), dtype=np.float64)
    lon_2d = np.zeros((nrows, ncols), dtype=np.float64)

    for i in range(nrows):
        for j in range(ncols):
            lat_2d[i, j] = yll + (nrows - 1 - i) * cs + cs / 2
            lon_2d[i, j] = xll + j * cs + cs / 2

    return lat_2d, lon_2d


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))

    header_L0 = domain_info["header_L0"]
    header_L1 = domain_info["header_L1"]
    header_L11 = domain_info.get("header_L11", header_L1)  # L11 defaults to L1

    # Generate lat/lon arrays for each level
    lat_l0, lon_l0 = make_latlon_2d(header_L0)
    lat_l1, lon_l1 = make_latlon_2d(header_L1)
    lat_l11, lon_l11 = make_latlon_2d(header_L11)

    # Write NetCDF with mHM-expected dimension names
    latlon_dir = Path(config["output_dir"]) / "input" / "latlon"
    latlon_dir.mkdir(parents=True, exist_ok=True)
    out_path = latlon_dir / "latlon_1.nc"

    ds = nc4.Dataset(str(out_path), "w", format="NETCDF4")

    # L0 dimensions and variables
    ds.createDimension("yc_l0", header_L0["nrows"])
    ds.createDimension("xc_l0", header_L0["ncols"])
    v = ds.createVariable("lat_l0", "f8", ("yc_l0", "xc_l0"))
    v[:] = lat_l0
    v.units = "degrees_north"
    v = ds.createVariable("lon_l0", "f8", ("yc_l0", "xc_l0"))
    v[:] = lon_l0
    v.units = "degrees_east"

    # L1 dimensions and variables
    ds.createDimension("yc", header_L1["nrows"])
    ds.createDimension("xc", header_L1["ncols"])
    v = ds.createVariable("lat", "f8", ("yc", "xc"))
    v[:] = lat_l1
    v.units = "degrees_north"
    v = ds.createVariable("lon", "f8", ("yc", "xc"))
    v[:] = lon_l1
    v.units = "degrees_east"

    # L11 dimensions and variables
    ds.createDimension("yc_l11", header_L11["nrows"])
    ds.createDimension("xc_l11", header_L11["ncols"])
    v = ds.createVariable("lat_l11", "f8", ("yc_l11", "xc_l11"))
    v[:] = lat_l11
    v.units = "degrees_north"
    v = ds.createVariable("lon_l11", "f8", ("yc_l11", "xc_l11"))
    v[:] = lon_l11
    v.units = "degrees_east"

    ds.close()

    logger.info(f"Written: {out_path}")
    logger.info(f"  L0: {header_L0['nrows']}x{header_L0['ncols']} (yc_l0 x xc_l0)")
    logger.info(f"  L1: {header_L1['nrows']}x{header_L1['ncols']} (yc x xc)")
    logger.info(f"  L11: {header_L11['nrows']}x{header_L11['ncols']} (yc_l11 x xc_l11)")

    result = {
        "status": "success",
        "file": str(out_path),
        "L0_shape": [header_L0["nrows"], header_L0["ncols"]],
        "L1_shape": [header_L1["nrows"], header_L1["ncols"]],
        "L11_shape": [header_L11["nrows"], header_L11["ncols"]],
        "lat_range": [float(lat_l1.min()), float(lat_l1.max())],
        "lon_range": [float(lon_l1.min()), float(lon_l1.max())],
    }
    print(json.dumps(result, indent=2))
    return str(out_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"latlon file not created: {output_path}")
        sys.exit(3)


if __name__ == "__main__":
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
