#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      hwsd_to_mhm_soil
Stage:        s2_morphology
Description:  Convert HWSD global soil database to mHM soil classification format.

This is the MOST CRITICAL data preparation tool. It:
1. Reads HWSD raster (MU_GLOBAL soil mapping unit IDs)
2. Looks up soil properties per mapping unit from the HWSD MDB database
3. Generates soil_class.asc (spatial grid of soil class IDs)
4. Generates soil_class_horizon_01.asc, soil_class_horizon_02.asc
5. Generates soil_classdefinition.txt (lookup table: class -> properties)

mHM soil classdefinition format (iFlag_soilDB=0):
  Line 1: nSoil_Types  <N>
  Header: MU_GLOBAL  HORIZON  UD[mm]  LD[mm]  CLAY[%]  SAND[%]  BD[gcm-3]
  Data: one row per mapping unit per horizon

CRITICAL: The column order MUST be exactly as shown above. Wrong order causes
silent parameter errors (Ksat, porosity all wrong but model still runs).

Inputs:
  - DOMAIN_INFO_PATH: domain_info.json from s1
  - CONFIG_PATH: config.json from s0
  - HWSD_RASTER: path to HWSD raster (hwsd.bil or hwsd.tif)
  - HWSD_MDB: path to HWSD MDB database
  - N_HORIZONS: number of soil horizons (default 2)
  - HORIZON_DEPTHS: depths in mm [upper1, lower1, upper2, lower2] default [0, 300, 300, 1000]

Outputs:
  - soil_class.asc: grid of HWSD MU_GLOBAL IDs
  - soil_class_horizon_01.asc: same as soil_class.asc
  - soil_class_horizon_02.asc: same as soil_class.asc
  - soil_classdefinition.txt: lookup table

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path
from collections import OrderedDict

try:
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.transform import from_bounds
    import geopandas as gpd
except ImportError as e:
    print(f"ERROR: Required: rasterio, geopandas. {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
HWSD_RASTER = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/soil/HWSD_RASTER/hwsd.bil")
HWSD_MDB = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/forcing/huaihe_raw/soil/HWSD.mdb")
N_HORIZONS = 2
HORIZON_DEPTHS = [0, 300, 300, 1000]  # UD1, LD1, UD2, LD2 in mm

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="HWSD to mHM soil classes")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--hwsd_raster", default=HWSD_RASTER)
    parser.add_argument("--hwsd_mdb", default=HWSD_MDB)
    parser.add_argument("--n_horizons", type=int, default=2)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    HWSD_RASTER = args.hwsd_raster
    HWSD_MDB = args.hwsd_mdb
    N_HORIZONS = args.n_horizons

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def read_hwsd_properties(mdb_path, mu_globals):
    """Read soil properties from HWSD MDB for given MU_GLOBAL IDs."""
    import subprocess
    import tempfile

    # Try reading MDB with mdbtools or pandas+pyodbc
    props = {}

    try:
        # Method 1: mdbtools (Linux)
        result = subprocess.run(
            ["mdb-export", mdb_path, "HWSD_DATA"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            import csv
            import io
            reader = csv.DictReader(io.StringIO(result.stdout))
            for row in reader:
                mu = int(row.get("MU_GLOBAL", 0))
                if mu in mu_globals:
                    def safe_float(val, default):
                        try:
                            v = float(val) if val not in (None, '', ' ') else default
                            return v
                        except (ValueError, TypeError):
                            return default
                    props[mu] = {
                        "T_CLAY": safe_float(row.get("T_CLAY"), 25.0),
                        "T_SAND": safe_float(row.get("T_SAND"), 50.0),
                        "T_BULK_DENSITY": safe_float(row.get("T_BULK_DENSITY"), 1.5),
                        "S_CLAY": safe_float(row.get("S_CLAY"), 25.0),
                        "S_SAND": safe_float(row.get("S_SAND"), 50.0),
                        "S_BULK_DENSITY": safe_float(row.get("S_BULK_DENSITY"), 1.5),
                        "T_OC": safe_float(row.get("T_OC"), 1.0),
                        "S_OC": safe_float(row.get("S_OC"), 0.5),
                    }
            logger.info(f"Read {len(props)} soil mapping units from MDB via mdbtools")
            return props
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        # Method 2: pyodbc
        import pyodbc
        conn = pyodbc.connect(f"DRIVER={{MDBTools}};DBQ={mdb_path};")
        cursor = conn.cursor()
        cursor.execute("SELECT MU_GLOBAL, T_CLAY, T_SAND, T_BULK_DENSITY, "
                       "S_CLAY, S_SAND, S_BULK_DENSITY, T_OC, S_OC FROM HWSD_DATA")
        for row in cursor:
            mu = int(row[0])
            if mu in mu_globals:
                props[mu] = {
                    "T_CLAY": float(row[1] or 25),
                    "T_SAND": float(row[2] or 50),
                    "T_BULK_DENSITY": float(row[3] or 1.5),
                    "S_CLAY": float(row[4] or 25),
                    "S_SAND": float(row[5] or 50),
                    "S_BULK_DENSITY": float(row[6] or 1.5),
                    "T_OC": float(row[7] or 1.0),
                    "S_OC": float(row[8] or 0.5),
                }
        conn.close()
        logger.info(f"Read {len(props)} soil mapping units from MDB via pyodbc")
        return props
    except Exception:
        pass

    # Method 3: Fallback defaults
    logger.warning("Could not read HWSD MDB. Using default soil properties.")
    for mu in mu_globals:
        props[mu] = {
            "T_CLAY": 25.0, "T_SAND": 50.0, "T_BULK_DENSITY": 1.50,
            "S_CLAY": 30.0, "S_SAND": 45.0, "S_BULK_DENSITY": 1.55,
            "T_OC": 1.0, "S_OC": 0.5,
        }
    return props


def write_ascii_grid(filepath, data, header):
    """Write numpy array as ESRI ASCII grid."""
    with open(filepath, 'w') as f:
        f.write(f"ncols         {header['ncols']}\n")
        f.write(f"nrows         {header['nrows']}\n")
        f.write(f"xllcorner     {header['xllcorner']}\n")
        f.write(f"yllcorner     {header['yllcorner']}\n")
        f.write(f"cellsize      {header['cellsize']}\n")
        f.write(f"NODATA_value  {header['NODATA_value']}\n")
        nodata = header['NODATA_value']
        for row in data:
            vals = []
            for v in row:
                if np.isnan(v) or v == nodata:
                    vals.append(str(int(nodata)))
                else:
                    vals.append(str(int(v)))
            f.write(" ".join(vals) + "\n")
    logger.info(f"Written: {filepath}")


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if not Path(HWSD_RASTER).exists():
        errors.append(f"HWSD raster not found: {HWSD_RASTER}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))
    header = domain_info["header_L0"]
    morph_dir = Path(config["output_dir"]) / "input" / "morph"
    morph_dir.mkdir(parents=True, exist_ok=True)

    nrows = header["nrows"]
    ncols = header["ncols"]
    xll = header["xllcorner"]
    yll = header["yllcorner"]
    cs = header["cellsize"]
    xur = xll + ncols * cs
    yur = yll + nrows * cs

    # Read and clip HWSD raster
    logger.info("Reading HWSD raster...")
    with rasterio.open(HWSD_RASTER) as src:
        dst_transform = from_bounds(xll, yll, xur, yur, ncols, nrows)
        soil_grid = np.full((nrows, ncols), -9999, dtype=np.int32)

        reproject(
            source=rasterio.band(src, 1),
            destination=soil_grid,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
            dst_nodata=-9999,
        )

    # Replace 0 (water/nodata in HWSD) with -9999
    soil_grid[soil_grid == 0] = -9999

    # Get unique MU_GLOBAL values
    unique_mu = set(soil_grid[soil_grid > 0].tolist())
    logger.info(f"Found {len(unique_mu)} unique HWSD mapping units")

    # Read soil properties from MDB
    props = read_hwsd_properties(HWSD_MDB, unique_mu)

    # CRITICAL: Remap HWSD MU_GLOBAL IDs to sequential 1-N.
    # mHM uses soil IDs as array indices internally. Raw HWSD IDs (e.g. 11020-11929)
    # exceed allocated array bounds. Must be remapped to 1, 2, 3, ..., N.
    sorted_mu = sorted(unique_mu)
    mu_to_seq = {int(mu): idx + 1 for idx, mu in enumerate(sorted_mu)}
    logger.info(f"Remapping {len(sorted_mu)} HWSD IDs to sequential 1-{len(sorted_mu)}")

    # Apply remapping to grid
    remap_vec = np.vectorize(lambda x: mu_to_seq.get(int(x), -9999) if x > 0 else -9999)
    soil_grid_seq = remap_vec(soil_grid).astype(float)

    # Write soil_class.asc (sequential IDs)
    write_ascii_grid(morph_dir / "soil_class.asc", soil_grid_seq, header)

    # Write horizon grids (same sequential IDs)
    for h in range(1, N_HORIZONS + 1):
        write_ascii_grid(
            morph_dir / f"soil_class_horizon_{h:02d}.asc",
            soil_grid_seq, header
        )

    # Write soil_classdefinition.txt
    # Format: nSoil_Types <N>
    # MU_GLOBAL  HORIZON  UD[mm]  LD[mm]  CLAY[%]  SAND[%]  BD[gcm-3]
    classdef_path = morph_dir / "soil_classdefinition.txt"
    with open(classdef_path, 'w') as f:
        f.write(f"nSoil_Types  {len(unique_mu)}\n")
        f.write("MU_GLOBAL\tHORIZON\tUD[mm]\tLD[mm]\tCLAY[%]\tSAND[%]\tBD[gcm-3]\n")

        for mu in sorted_mu:  # sorted_mu defined above during remapping
            p = props.get(mu, {
                "T_CLAY": 25.0, "T_SAND": 50.0, "T_BULK_DENSITY": 1.50,
                "S_CLAY": 30.0, "S_SAND": 45.0, "S_BULK_DENSITY": 1.55,
            })

            # Horizon 1 (topsoil)
            clay1 = p["T_CLAY"]
            sand1 = p["T_SAND"]
            bd1 = p["T_BULK_DENSITY"]
            # Clamp to valid ranges
            clay1 = max(1.0, min(99.0, clay1))
            sand1 = max(1.0, min(99.0, sand1))
            bd1 = max(0.5, min(2.5, bd1))
            # Ensure sand + clay <= 100
            if sand1 + clay1 > 100:
                excess = (sand1 + clay1 - 100) / 2
                sand1 -= excess
                clay1 -= excess

            seq_id = mu_to_seq[int(mu)]
            f.write(f"{seq_id}\t1\t{HORIZON_DEPTHS[0]}\t{HORIZON_DEPTHS[1]}\t"
                    f"{clay1:.1f}\t{sand1:.1f}\t{bd1:.2f}\n")

            # Horizon 2 (subsoil)
            clay2 = p["S_CLAY"]
            sand2 = p["S_SAND"]
            bd2 = p["S_BULK_DENSITY"]
            clay2 = max(1.0, min(99.0, clay2))
            sand2 = max(1.0, min(99.0, sand2))
            bd2 = max(0.5, min(2.5, bd2))
            if sand2 + clay2 > 100:
                excess = (sand2 + clay2 - 100) / 2
                sand2 -= excess
                clay2 -= excess

            f.write(f"{seq_id}\t2\t{HORIZON_DEPTHS[2]}\t{HORIZON_DEPTHS[3]}\t"
                    f"{clay2:.1f}\t{sand2:.1f}\t{bd2:.2f}\n")

    logger.info(f"Soil classdefinition written: {classdef_path} ({len(unique_mu)} types)")

    result = {
        "status": "success",
        "morph_dir": str(morph_dir),
        "files": [
            "soil_class.asc",
            "soil_class_horizon_01.asc",
            "soil_class_horizon_02.asc",
            "soil_classdefinition.txt",
        ],
        "n_soil_types": len(unique_mu),
        "n_horizons": N_HORIZONS,
    }
    print(json.dumps(result, indent=2))
    return str(morph_dir)


def validate_outputs(output_path):
    morph_dir = Path(output_path)
    required = [
        "soil_class.asc",
        "soil_class_horizon_01.asc",
        "soil_class_horizon_02.asc",
        "soil_classdefinition.txt",
    ]
    for f in required:
        p = morph_dir / f
        if not p.exists():
            logger.error(f"Missing: {p}")
            sys.exit(3)

    # Validate classdefinition format
    with open(morph_dir / "soil_classdefinition.txt") as f:
        first_line = f.readline().strip()
        if not first_line.startswith("nSoil_Types"):
            logger.error(f"soil_classdefinition.txt must start with 'nSoil_Types'")
            sys.exit(3)
        header_line = f.readline().strip()
        expected_cols = ["MU_GLOBAL", "HORIZON", "UD[mm]", "LD[mm]", "CLAY[%]", "SAND[%]", "BD[gcm-3]"]
        actual_cols = header_line.split("\t")
        if actual_cols != expected_cols:
            logger.error(f"Wrong classdefinition header: {actual_cols} != {expected_cols}")
            sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
