#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_time_sim
Stage:        s7_simulation_config
Description:  Generate time.sim with simulation period, time step, and warmup.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path
from datetime import datetime

START_DATE = ""  # YYYY-MM-DD
END_DATE = ""
WARMUP_YEARS = 2
OUTPUT_DIR = ""

if len(sys.argv) >= 4:
    START_DATE = sys.argv[1]
    END_DATE = sys.argv[2]
    OUTPUT_DIR = sys.argv[3]
if len(sys.argv) >= 5:
    WARMUP_YEARS = int(sys.argv[4])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not START_DATE or not END_DATE:
        errors.append("Start and end dates required")
    else:
        try:
            start = datetime.strptime(START_DATE, "%Y-%m-%d")
            end = datetime.strptime(END_DATE, "%Y-%m-%d")
            if start >= end:
                errors.append(f"Start date {START_DATE} must be before end date {END_DATE}")
        except ValueError:
            errors.append("Dates must be YYYY-MM-DD format")
    if WARMUP_YEARS < 0:
        errors.append("Warmup years must be >= 0")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")

    day_start = start.timetuple().tm_yday
    yrc_start = start.year
    day_end = end.timetuple().tm_yday
    yrc_end = end.year

    time_sim_path = output_dir / "time.sim"
    with open(time_sim_path, 'w') as f:
        f.write("time.sim: written by SWAT+ knowledge infrastructure\n")
        f.write("  day_start    yrc_start    day_end    yrc_end    step\n")
        f.write(f"  {day_start:<12d} {yrc_start:<12d} {day_end:<10d} {yrc_end:<10d} {'0':>6s}\n")

    logger.info(f"Wrote time.sim: {START_DATE} to {END_DATE}, warmup={WARMUP_YEARS} years")
    return {
        "status": "success",
        "time_sim": str(time_sim_path),
        "period": f"{START_DATE} to {END_DATE}",
        "warmup_years": WARMUP_YEARS
    }

def validate_outputs(result):
    if not Path(result["time_sim"]).exists():
        logger.error("time.sim not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
