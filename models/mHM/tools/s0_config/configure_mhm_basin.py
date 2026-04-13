#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      configure_mhm_basin
Stage:        s0_config
Description:  Create mHM directory structure and initial configuration for a basin.

Inputs:
  - BASIN_NAME: short name for the basin (e.g., "bengbu")
  - OUTPUT_DIR: root directory for mHM run outputs
  - SHP_PATH: path to basin boundary shapefile
  - START_YEAR / END_YEAR: simulation period
  - RESOLUTION_L0_M: L0 (morphological) resolution in meters
  - RESOLUTION_L1_M: L1 (hydrological model) resolution in meters
  - RESOLUTION_L11_M: L11 (routing) resolution in meters (default = L1)
  - FORCING_DATASET: "CMFD" or "MSWX"
  - PET_METHOD: 0 (input PET), 1 (Hargreaves), 2 (Priestley-Taylor), 3 (Penman-Monteith)
  - MHM_BINARY: path to mHM executable

Outputs:
  - Directory tree under OUTPUT_DIR/<BASIN_NAME>/
  - config.json with all settings

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASIN_NAME = ""
OUTPUT_DIR = ""
SHP_PATH = ""
START_YEAR = 2000
END_YEAR = 2010
RESOLUTION_L0_M = 1000      # ~0.01 degree
RESOLUTION_L1_M = 24000     # ~0.25 degree
RESOLUTION_L11_M = 0        # 0 = same as L1
FORCING_DATASET = "CMFD"    # "CMFD" or "MSWX"
PET_METHOD = 0              # 0=input PET, 1=Hargreaves, 2=Priestley-Taylor, 3=Penman-Monteith
MHM_BINARY = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/mhm/mhm")

# HydroCraft standard paths
HYDROCRAFT_ROOT = "/mnt/disk1/Hydrocraft_server"

# CLI override
if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Configure mHM basin")
    parser.add_argument("--basin_name", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--shp_path", required=True)
    parser.add_argument("--start_year", type=int, default=2000)
    parser.add_argument("--end_year", type=int, default=2010)
    parser.add_argument("--resolution_l0", type=float, default=1000)
    parser.add_argument("--resolution_l1", type=float, default=24000)
    parser.add_argument("--resolution_l11", type=float, default=0)
    parser.add_argument("--forcing", default="CMFD", choices=["CMFD", "MSWX"])
    parser.add_argument("--pet_method", type=int, default=0, choices=[0, 1, 2, 3])
    parser.add_argument("--mhm_binary", default=MHM_BINARY)
    args = parser.parse_args()
    BASIN_NAME = args.basin_name
    OUTPUT_DIR = args.output_dir
    SHP_PATH = args.shp_path
    START_YEAR = args.start_year
    END_YEAR = args.end_year
    RESOLUTION_L0_M = args.resolution_l0
    RESOLUTION_L1_M = args.resolution_l1
    RESOLUTION_L11_M = args.resolution_l11
    FORCING_DATASET = args.forcing
    PET_METHOD = args.pet_method
    MHM_BINARY = args.mhm_binary

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not BASIN_NAME:
        errors.append("BASIN_NAME is not set")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if not SHP_PATH or not Path(SHP_PATH).exists():
        errors.append(f"Shapefile not found: {SHP_PATH}")
    if START_YEAR >= END_YEAR:
        errors.append(f"START_YEAR ({START_YEAR}) must be < END_YEAR ({END_YEAR})")
    if not Path(MHM_BINARY).exists():
        errors.append(f"mHM binary not found: {MHM_BINARY}")

    # Check resolution is positive
    if RESOLUTION_L0_M <= 0:
        errors.append(f"RESOLUTION_L0_M must be positive: {RESOLUTION_L0_M}")
    if RESOLUTION_L1_M <= 0:
        errors.append(f"RESOLUTION_L1_M must be positive: {RESOLUTION_L1_M}")

    # Check L1 is integer multiple of L0
    if RESOLUTION_L0_M > 0 and RESOLUTION_L1_M > 0:
        ratio = RESOLUTION_L1_M / RESOLUTION_L0_M
        if abs(ratio - round(ratio)) > 0.01:
            errors.append(
                f"L1 resolution ({RESOLUTION_L1_M}m) must be integer multiple of "
                f"L0 resolution ({RESOLUTION_L0_M}m). Ratio={ratio:.2f}"
            )

    # Check L11 if set
    l11 = RESOLUTION_L11_M if RESOLUTION_L11_M > 0 else RESOLUTION_L1_M
    if RESOLUTION_L0_M > 0 and l11 > 0:
        ratio = l11 / RESOLUTION_L0_M
        if abs(ratio - round(ratio)) > 0.01:
            errors.append(
                f"L11 resolution ({l11}m) must be integer multiple of "
                f"L0 resolution ({RESOLUTION_L0_M}m). Ratio={ratio:.2f}"
            )

    # Forcing dataset validation
    if FORCING_DATASET == "CMFD":
        if START_YEAR < 1979 or END_YEAR > 2018:
            errors.append(f"CMFD only covers 1979-2018, but period is {START_YEAR}-{END_YEAR}")
    elif FORCING_DATASET == "MSWX":
        if START_YEAR < 1979 or END_YEAR > 2026:
            errors.append(f"MSWX only covers 1979-2026, but period is {START_YEAR}-{END_YEAR}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    base = Path(OUTPUT_DIR) / BASIN_NAME
    l11 = RESOLUTION_L11_M if RESOLUTION_L11_M > 0 else RESOLUTION_L1_M

    # Create directory structure matching mHM expectations
    dirs = {
        "input/morph": "Morphological data (DEM, soil, geology, land cover)",
        "input/luse": "Land use/cover time series",
        "input/meteo/pre": "Precipitation NetCDF",
        "input/meteo/tavg": "Average temperature NetCDF",
        "input/meteo/pet": "PET NetCDF (if processCase(5)==0)",
        "input/meteo/tmin": "Min temperature (for Hargreaves)",
        "input/meteo/tmax": "Max temperature (for Hargreaves)",
        "input/gauge": "Observed discharge data",
        "input/lai": "Optional gridded LAI",
        "input/latlon": "Lat/lon coordinate files",
        "input/optional_data": "Optional additional data",
        "output_b1": "Model output",
        "restart": "Restart files",
    }

    for d, desc in dirs.items():
        p = base / d
        p.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created: {p} ({desc})")

    # Determine PET directories needed
    pet_dirs_needed = {
        0: ["pet"],          # pre-computed PET
        1: ["tmin", "tmax"], # Hargreaves
        2: [],               # Priestley-Taylor (needs radiation)
        3: [],               # Penman-Monteith (needs many vars)
    }

    # Build config
    config = {
        "basin_name": BASIN_NAME,
        "output_dir": str(base),
        "shp_path": str(Path(SHP_PATH).resolve()),
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "resolution_L0_m": RESOLUTION_L0_M,
        "resolution_L1_m": RESOLUTION_L1_M,
        "resolution_L11_m": l11,
        "forcing_dataset": FORCING_DATASET,
        "pet_method": PET_METHOD,
        "mhm_binary": MHM_BINARY,
        "hydrocraft_root": HYDROCRAFT_ROOT,
        "dirs": {k: str(base / k) for k in dirs},
        "pet_forcing_dirs": pet_dirs_needed.get(PET_METHOD, []),
        "process_selection": {
            "interception": 1,
            "snow": 1,
            "soil_moisture": 1,
            "direct_runoff": 1,
            "PET": PET_METHOD,
            "interflow": 1,
            "percolation": 1,
            "routing": 3,  # adaptive timestep
            "baseflow": 1,
        },
    }

    config_path = base / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config written to {config_path}")

    # Print JSON summary
    print(json.dumps({
        "status": "success",
        "basin_name": BASIN_NAME,
        "output_dir": str(base),
        "config_path": str(config_path),
        "resolution_L0": RESOLUTION_L0_M,
        "resolution_L1": RESOLUTION_L1_M,
        "resolution_L11": l11,
        "forcing": FORCING_DATASET,
        "pet_method": PET_METHOD,
        "period": f"{START_YEAR}-{END_YEAR}",
    }, indent=2))

    return str(config_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Config file not created: {output_path}")
        sys.exit(3)

    config = json.load(open(output_path))
    required_dirs = ["input/morph", "input/meteo/pre", "input/gauge", "output_b1"]
    base = Path(config["output_dir"])
    for d in required_dirs:
        if not (base / d).exists():
            logger.error(f"Required directory not created: {base / d}")
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
    logger.info(f"Tool completed successfully. Output: {output_path}")
    sys.exit(0)
