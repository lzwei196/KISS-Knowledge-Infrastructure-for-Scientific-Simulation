#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      define_subbasins
Stage:        s1_watershed_delineation
Description:  Generate subbasin-level connectivity and channel definitions for SWAT+.

Inputs:
  - subbasin_shapefile: Subbasin boundaries from delineate_watershed
  - dem_path: Pit-filled DEM
  - stream_shapefile: Stream network
  - output_dir: TxtInOut directory

Outputs:
  - chandeg.con: Channel connectivity
  - rout_unit.con: Routing unit connectivity

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging
import json
from pathlib import Path

SUBBASIN_SHP = ""
DEM_PATH = ""
STREAM_SHP = ""
OUTPUT_DIR = ""

if len(sys.argv) >= 5:
    SUBBASIN_SHP = sys.argv[1]
    DEM_PATH = sys.argv[2]
    STREAM_SHP = sys.argv[3]
    OUTPUT_DIR = sys.argv[4]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    for path, name in [(SUBBASIN_SHP, "Subbasin shapefile"), (DEM_PATH, "DEM"), (STREAM_SHP, "Stream shapefile")]:
        if not path or not Path(path).exists():
            errors.append(f"{name} not found: {path}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """Generate SWAT+ connectivity files from spatial data."""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd

    subbasins = gpd.read_file(SUBBASIN_SHP)
    streams = gpd.read_file(STREAM_SHP)
    n_sub = len(subbasins)

    # Generate chandeg.con (channel connectivity)
    chandeg_path = output_dir / "chandeg.con"
    with open(chandeg_path, 'w') as f:
        f.write("chandeg.con: written by SWAT+ knowledge infrastructure\n")
        f.write(f"  gis_id       name             area       lat         lon         elev        "
                f"wst            obj_typ    obj_id     hd_typ     hd_id\n")
        for i in range(n_sub):
            centroid = subbasins.geometry.iloc[i].centroid
            f.write(f"  {i+1:<12d} cha{i+1:03d}           "
                    f"{subbasins.geometry.iloc[i].area/1e6:10.3f} "
                    f"{centroid.y:10.5f} {centroid.x:10.5f} "
                    f"{'0.0':>10s} {'wst001':>15s} "
                    f"{'sdc':>10s} {i+1:>10d} {'tot':>10s} {0:>10d}\n")
    logger.info(f"Wrote {chandeg_path} with {n_sub} channels")

    # Generate rout_unit.con (routing unit connectivity)
    rout_path = output_dir / "rout_unit.con"
    with open(rout_path, 'w') as f:
        f.write("rout_unit.con: written by SWAT+ knowledge infrastructure\n")
        f.write(f"  gis_id       name             area       lat         lon         elev        "
                f"wst            obj_typ    obj_id     hd_typ     hd_id\n")
        for i in range(n_sub):
            centroid = subbasins.geometry.iloc[i].centroid
            f.write(f"  {i+1:<12d} ru{i+1:04d}            "
                    f"{subbasins.geometry.iloc[i].area/1e6:10.3f} "
                    f"{centroid.y:10.5f} {centroid.x:10.5f} "
                    f"{'0.0':>10s} {'wst001':>15s} "
                    f"{'sdc':>10s} {i+1:>10d} {'tot':>10s} {i+1:>10d}\n")
    logger.info(f"Wrote {rout_path} with {n_sub} routing units")

    return {
        "status": "success",
        "chandeg_con": str(chandeg_path),
        "rout_unit_con": str(rout_path),
        "n_subbasins": n_sub
    }


def validate_outputs(result):
    errors = []
    for key in ["chandeg_con", "rout_unit_con"]:
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
