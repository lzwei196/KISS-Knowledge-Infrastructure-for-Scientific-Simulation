#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_print_prt
Stage:        s7_simulation_config
Description:  Generate print.prt for SWAT+ output configuration.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

OUTPUT_VARIABLES = {}  # {"basin_wb": {"daily": True}, "channel_sd": {"daily": True}, ...}
NYSKIP = 2
OUTPUT_DIR = ""

if len(sys.argv) >= 3:
    OUTPUT_VARIABLES = json.loads(sys.argv[1])
    OUTPUT_DIR = sys.argv[2]
if len(sys.argv) >= 4:
    NYSKIP = int(sys.argv[3])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ALL_OUTPUT_CATEGORIES = [
    "basin_wb", "basin_nb", "basin_ls", "basin_psc", "basin_aqu",
    "channel_sd", "channel_sdmorph",
    "aquifer",
    "reservoir",
    "recall",
    "hru_wb", "hru_nb", "hru_ls", "hru_pw",
    "hru-lte_wb", "hru-lte_nb", "hru-lte_ls", "hru-lte_pw",
    "lsunit_wb", "lsunit_nb", "lsunit_ls", "lsunit_pw",
]

def validate_inputs():
    if not OUTPUT_DIR:
        logger.error("OUTPUT_DIR is not set"); sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    print_prt_path = output_dir / "print.prt"
    with open(print_prt_path, 'w') as f:
        f.write("print.prt: written by SWAT+ knowledge infrastructure\n")
        f.write(f"  nyskip    day_start    yrc_start    day_end    yrc_end    interval\n")
        f.write(f"  {NYSKIP:<10d} {'0':>10s} {'0':>12s} {'0':>10s} {'0':>10s} {'1':>10s}\n")
        f.write("  aa_int_cnt\n")
        f.write("  0\n")
        f.write(f"{'':>20s}{'daily':>10s}{'monthly':>10s}{'yearly':>10s}{'avann':>10s}\n")

        for cat in ALL_OUTPUT_CATEGORIES:
            config = OUTPUT_VARIABLES.get(cat, {})
            daily = "y" if config.get("daily", False) else "n"
            monthly = "y" if config.get("monthly", False) else "n"
            yearly = "y" if config.get("yearly", False) else "n"
            avann = "y" if config.get("avann", False) else "n"
            f.write(f"  {cat:<18s}{daily:>10s}{monthly:>10s}{yearly:>10s}{avann:>10s}\n")

    logger.info(f"Wrote print.prt with {len(OUTPUT_VARIABLES)} configured outputs, nyskip={NYSKIP}")
    return {
        "status": "success",
        "print_prt": str(print_prt_path),
        "nyskip": NYSKIP,
        "configured_outputs": list(OUTPUT_VARIABLES.keys())
    }

def validate_outputs(result):
    if not Path(result["print_prt"]).exists():
        logger.error("print.prt not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
