#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      build_management_schedules
Stage:        s5_landuse_management
Description:  Generate management.sch with operation sequences for each land use type.
              Operations: plant, fert, irrigate, harvest, kill, tillage.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

LANDUSE_TYPES = []
CROP_CALENDAR = {}  # {crop: {plant_mon, plant_day, harvest_mon, harvest_day}}
FERTILIZER_RATES = {}  # {crop: {n_rate_kgha, p_rate_kgha}}
OUTPUT_DIR = ""

if len(sys.argv) >= 4:
    LANDUSE_TYPES = json.loads(sys.argv[1])
    CROP_CALENDAR = json.loads(sys.argv[2])
    OUTPUT_DIR = sys.argv[3]
if len(sys.argv) >= 5:
    FERTILIZER_RATES = json.loads(sys.argv[4])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Default management templates
DEFAULT_SCHEDULES = {
    "CORN": {"plant": (4, 15), "harvest": (10, 15), "n_rate": 170, "ops": 6},
    "SOYB": {"plant": (5, 1), "harvest": (10, 1), "n_rate": 0, "ops": 4},
    "WWHT": {"plant": (10, 15), "harvest": (6, 15), "n_rate": 120, "ops": 5},
    "AGRL": {"plant": (4, 15), "harvest": (10, 15), "n_rate": 100, "ops": 5},
    "PAST": {"ops": 0},
    "FRSD": {"ops": 0},
    "FRSE": {"ops": 0},
    "FRST": {"ops": 0},
    "RNGE": {"ops": 0},
    "WATR": {"ops": 0},
    "URBN": {"ops": 0},
    "WETL": {"ops": 0},
}

def validate_inputs():
    errors = []
    if not LANDUSE_TYPES:
        errors.append("No land use types provided")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    mgmt_path = output_dir / "management.sch"
    schedules_written = 0

    with open(mgmt_path, 'w') as f:
        f.write("management.sch: written by SWAT+ knowledge infrastructure\n")
        f.write("  name             numb_ops  numb_auto\n")

        for lu in LANDUSE_TYPES:
            template = DEFAULT_SCHEDULES.get(lu, DEFAULT_SCHEDULES.get("AGRL"))
            if template["ops"] == 0:
                # Non-agricultural — minimal schedule
                f.write(f"  {lu.lower()}_mgmt      0         0\n")
                schedules_written += 1
                continue

            plant = CROP_CALENDAR.get(lu, {})
            pm = plant.get("plant_mon", template.get("plant", (4, 15))[0])
            pd = plant.get("plant_day", template.get("plant", (4, 15))[1])
            hm = plant.get("harvest_mon", template.get("harvest", (10, 15))[0])
            hd = plant.get("harvest_day", template.get("harvest", (10, 15))[1])
            n_rate = FERTILIZER_RATES.get(lu, {}).get("n_rate_kgha", template.get("n_rate", 100))

            n_ops = 4  # plant, fert, harvest, kill
            if n_rate > 0:
                n_ops = 5  # add second fert
            f.write(f"  {lu.lower()}_mgmt      {n_ops}         0\n")

            # Operation header
            f.write("  op_typ    mon  day  hu_sch    op_data1      op_data2      op_data3\n")

            # Planting
            f.write(f"  plant     {pm:<4d} {pd:<4d} 0.000     {lu.lower():<14s} null           null\n")

            # Fertilizer at planting
            if n_rate > 0:
                f.write(f"  fert      {pm:<4d} {pd+10:<4d} 0.000     elem_n         {n_rate*0.4:<14.1f} null\n")
                # Side-dress
                side_m = pm + 2 if pm + 2 <= 12 else pm + 2 - 12
                f.write(f"  fert      {side_m:<4d} {1:<4d} 0.000     elem_n         {n_rate*0.6:<14.1f} null\n")

            # Harvest
            f.write(f"  harvest   {hm:<4d} {hd:<4d} 1.200     {lu.lower():<14s} grain          null\n")

            # Kill
            kill_d = hd + 1 if hd < 28 else 1
            kill_m = hm if hd < 28 else (hm + 1 if hm < 12 else 1)
            f.write(f"  kill      {kill_m:<4d} {kill_d:<4d} 0.000     null           null           null\n")

            schedules_written += 1

    logger.info(f"Wrote {schedules_written} management schedules to management.sch")
    return {
        "status": "success",
        "management_sch": str(mgmt_path),
        "n_schedules": schedules_written
    }

def validate_outputs(result):
    if not Path(result["management_sch"]).exists():
        logger.error("management.sch not created"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
