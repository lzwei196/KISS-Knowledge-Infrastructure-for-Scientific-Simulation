#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_landuse
Stage:        s5_landuse_management
Description:  Generate landuse.lum linking land use codes to management schedules, CN tables.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

LANDUSE_TYPES = []
MANAGEMENT_SCH_PATH = ""
OUTPUT_DIR = ""

if len(sys.argv) >= 4:
    LANDUSE_TYPES = json.loads(sys.argv[1])
    MANAGEMENT_SCH_PATH = sys.argv[2]
    OUTPUT_DIR = sys.argv[3]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Default CN2 values by land use and hydrologic group
DEFAULT_CN2 = {
    "CORN": {"A": 67, "B": 77, "C": 83, "D": 87},
    "SOYB": {"A": 67, "B": 77, "C": 83, "D": 87},
    "WWHT": {"A": 63, "B": 73, "C": 80, "D": 84},
    "AGRL": {"A": 67, "B": 77, "C": 83, "D": 87},
    "PAST": {"A": 49, "B": 69, "C": 79, "D": 84},
    "FRSD": {"A": 30, "B": 55, "C": 70, "D": 77},
    "FRSE": {"A": 30, "B": 55, "C": 70, "D": 77},
    "FRST": {"A": 30, "B": 55, "C": 70, "D": 77},
    "RNGE": {"A": 49, "B": 69, "C": 79, "D": 84},
    "URBN": {"A": 77, "B": 85, "C": 90, "D": 92},
    "WATR": {"A": 98, "B": 98, "C": 98, "D": 98},
    "WETL": {"A": 85, "B": 90, "C": 93, "D": 95},
}

def validate_inputs():
    errors = []
    if not LANDUSE_TYPES:
        errors.append("No land use types")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    lum_path = output_dir / "landuse.lum"
    with open(lum_path, 'w') as f:
        f.write("landuse.lum: written by SWAT+ knowledge infrastructure\n")
        f.write("  name            cal_group     plnt_com      mgt_sch       cn2_name      cons_prac     ov_mann      tile_drain    sep_perf     filt_perf     strip_perf    fire_freq     bmp_flag\n")
        for lu in LANDUSE_TYPES:
            cn2 = DEFAULT_CN2.get(lu, DEFAULT_CN2["AGRL"])
            mgmt = f"{lu.lower()}_mgmt"
            f.write(f"  {lu.lower():<16s} {'null':>13s} {lu.lower():>13s} {mgmt:>13s} "
                    f"{'cn_' + lu.lower():>13s} {'null':>13s} {'ov_' + lu.lower():>12s} "
                    f"{'null':>13s} {'null':>13s} {'null':>13s} {'null':>13s} {'null':>13s} {'0':>13s}\n")

    logger.info(f"Wrote landuse.lum with {len(LANDUSE_TYPES)} entries")
    return {
        "status": "success",
        "landuse_lum": str(lum_path),
        "n_landuse": len(LANDUSE_TYPES)
    }

def validate_outputs(result):
    if not Path(result["landuse_lum"]).exists():
        logger.error("landuse.lum not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
