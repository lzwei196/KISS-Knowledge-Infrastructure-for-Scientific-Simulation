#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_file_cio
Stage:        s7_simulation_config
Description:  Generate/update file.cio master control file for SWAT+.
              Lists all input file categories with their filenames.
              Use 'null' for unused optional files — do NOT delete lines.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

TXTINOUT_DIR = ""
OPTIONAL_MODULES = {}  # {"reservoir": False, "wetland": False, ...}

if len(sys.argv) >= 2:
    TXTINOUT_DIR = sys.argv[1]
if len(sys.argv) >= 3:
    OPTIONAL_MODULES = json.loads(sys.argv[2])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# file.cio category structure (order matters!)
FILE_CIO_CATEGORIES = [
    ("simulation", ["time.sim", "print.prt", "object.cnt", "null", "null"]),
    ("basin", ["codes.bsn", "parameters.bsn"]),
    ("climate", ["weather-wgn.cli", "weather-sta.cli", "null", "atmo.cli"]),
    ("connect", ["hru.con", "rout_unit.con", "aquifer.con", "chandeg.con",
                 "recall.con", "exco.con", "delr.con", "aquifer2d.con", "hrd.con", "ru.con"]),
    ("hru", ["hru-data.hru", "hru-lte.hru"]),
    ("lsunit", ["ls_unit.def", "ls_unit.ele"]),
    ("aquifer", ["aquifer.aqu", "initial.aqu"]),
    ("channel", ["channel-lte.cha", "hyd-sed-lte.cha", "null", "null", "null", "null", "null"]),
    ("reservoir", ["null", "null", "null", "null", "null"]),
    ("hydrology", ["hydrology.hyd", "topography.hyd", "field.fld"]),
    ("soils", ["soils.sol", "nutrients.sol"]),
    ("landuse", ["landuse.lum", "management.sch", "cntable.lum", "cons_practice.lum",
                 "ovn_table.lum", "null"]),
    ("calibration", ["calibration.cal", "cal_parms.cal"]),
]

def validate_inputs():
    if not TXTINOUT_DIR or not Path(TXTINOUT_DIR).is_dir():
        logger.error(f"TxtInOut directory not found: {TXTINOUT_DIR}"); sys.exit(1)
    logger.info("Input validation passed.")

def process():
    txtinout = Path(TXTINOUT_DIR)

    # Check which files exist and set missing ones to null
    file_cio_path = txtinout / "file.cio"
    missing_files = []

    with open(file_cio_path, 'w') as f:
        f.write("file.cio: written by SWAT+ knowledge infrastructure\n")
        for category, files in FILE_CIO_CATEGORIES:
            resolved = []
            for fname in files:
                if fname == "null":
                    resolved.append("null")
                elif (txtinout / fname).exists():
                    resolved.append(fname)
                else:
                    resolved.append("null")
                    if category not in ["reservoir", "channel"]:  # Optional categories
                        missing_files.append(f"{category}/{fname}")
            f.write(f"  {category:<18s} " + "  ".join(resolved) + "\n")

    if missing_files:
        logger.warning(f"Missing files set to null: {', '.join(missing_files[:10])}")

    return {
        "status": "success",
        "file_cio": str(file_cio_path),
        "missing_files": missing_files,
        "categories": len(FILE_CIO_CATEGORIES)
    }

def validate_outputs(result):
    if not Path(result["file_cio"]).exists():
        logger.error("file.cio not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
