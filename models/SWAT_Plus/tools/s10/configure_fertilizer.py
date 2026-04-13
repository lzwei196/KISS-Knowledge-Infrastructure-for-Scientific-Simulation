#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_fertilizer
Stage:        s10_water_quality
Description:  Generate realistic fertilizer and crop management schedules in
              management.sch for Chinese agricultural systems.

Usage:
    python configure_fertilizer.py --management_sch <path> --crop <crop> --region <region> [--append]

Crops:   wheat, maize, rice, wheat_maize (double-cropping)
Regions: huai_river, north_china, northeast, south_china

Fertilizer rates are based on Chinese agricultural survey data and the
NPKGRIDS dataset (Lu & Tian, 2017; Zhang et al., 2021).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import argparse
import logging
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ========================================================================
# Chinese agricultural fertilizer schedules
# Reference: Chinese Agricultural Statistics Yearbook, NPKGRIDS dataset
# Rates are in kg/ha of elemental N or P
# ========================================================================

# Each schedule is a list of operations: (op_type, month, day, hu_sch, op_data1, op_data2, op_data3)
# op_data3 for fert = application rate in kg/ha

CROP_SCHEDULES = {
    # Winter wheat: plant Oct, harvest Jun (Huai River / North China)
    "wheat": {
        "huai_river": {
            "name": "wwheat_huaihe",
            "ops": [
                ("till",  9, 20, 0.0, "fldcult",    "null",       0.0),
                ("fert", 10,  1, 0.0, "elem_n",     "broadcast",  150.0),  # Basal N
                ("fert", 10,  1, 0.0, "elem_p",     "broadcast",  40.0),   # Basal P
                ("plnt", 10,  5, 0.0, "wwht",       "null",       0.0),
                ("fert",  3, 10, 0.0, "elem_n",     "broadcast",  75.0),   # Topdress at jointing
                ("harv",  6,  5, 0.0, "wwht",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "north_china": {
            "name": "wwheat_ncplain",
            "ops": [
                ("till",  9, 25, 0.0, "fldcult",    "null",       0.0),
                ("fert", 10,  5, 0.0, "elem_n",     "broadcast",  165.0),
                ("fert", 10,  5, 0.0, "elem_p",     "broadcast",  45.0),
                ("plnt", 10, 10, 0.0, "wwht",       "null",       0.0),
                ("fert",  3, 15, 0.0, "elem_n",     "broadcast",  90.0),
                ("harv",  6, 10, 0.0, "wwht",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "northeast": {
            "name": "swheat_northeast",
            # Spring wheat for northeast
            "ops": [
                ("till",  4,  1, 0.0, "fldcult",    "null",       0.0),
                ("fert",  4,  5, 0.0, "elem_n",     "broadcast",  120.0),
                ("fert",  4,  5, 0.0, "elem_p",     "broadcast",  35.0),
                ("plnt",  4, 10, 0.0, "swht",       "null",       0.0),
                ("fert",  5, 25, 0.0, "elem_n",     "broadcast",  60.0),
                ("harv",  8, 20, 0.0, "swht",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "south_china": {
            "name": "wwheat_south",
            "ops": [
                ("till", 10, 15, 0.0, "fldcult",    "null",       0.0),
                ("fert", 10, 20, 0.0, "elem_n",     "broadcast",  135.0),
                ("fert", 10, 20, 0.0, "elem_p",     "broadcast",  35.0),
                ("plnt", 10, 25, 0.0, "wwht",       "null",       0.0),
                ("fert",  2, 20, 0.0, "elem_n",     "broadcast",  70.0),
                ("harv",  5, 20, 0.0, "wwht",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
    },

    # Summer maize: plant Jun, harvest Oct
    "maize": {
        "huai_river": {
            "name": "smaize_huaihe",
            "ops": [
                ("till",  6,  5, 0.0, "fldcult",    "null",       0.0),
                ("fert",  6, 10, 0.0, "elem_n",     "broadcast",  120.0),
                ("fert",  6, 10, 0.0, "elem_p",     "broadcast",  35.0),
                ("plnt",  6, 15, 0.0, "corn",       "null",       0.0),
                ("fert",  7, 15, 0.0, "elem_n",     "broadcast",  60.0),   # V6 topdress
                ("harv", 10,  1, 0.0, "corn",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "north_china": {
            "name": "smaize_ncplain",
            "ops": [
                ("till",  6, 10, 0.0, "fldcult",    "null",       0.0),
                ("fert",  6, 12, 0.0, "elem_n",     "broadcast",  135.0),
                ("fert",  6, 12, 0.0, "elem_p",     "broadcast",  40.0),
                ("plnt",  6, 15, 0.0, "corn",       "null",       0.0),
                ("fert",  7, 20, 0.0, "elem_n",     "broadcast",  75.0),
                ("harv", 10,  5, 0.0, "corn",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "northeast": {
            "name": "smaize_northeast",
            "ops": [
                ("till",  4, 25, 0.0, "fldcult",    "null",       0.0),
                ("fert",  5,  1, 0.0, "elem_n",     "broadcast",  100.0),
                ("fert",  5,  1, 0.0, "elem_p",     "broadcast",  30.0),
                ("plnt",  5,  5, 0.0, "corn",       "null",       0.0),
                ("fert",  6, 20, 0.0, "elem_n",     "broadcast",  50.0),
                ("harv",  9, 25, 0.0, "corn",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "south_china": {
            "name": "smaize_south",
            "ops": [
                ("till",  3, 10, 0.0, "fldcult",    "null",       0.0),
                ("fert",  3, 15, 0.0, "elem_n",     "broadcast",  110.0),
                ("fert",  3, 15, 0.0, "elem_p",     "broadcast",  30.0),
                ("plnt",  3, 20, 0.0, "corn",       "null",       0.0),
                ("fert",  4, 20, 0.0, "elem_n",     "broadcast",  55.0),
                ("harv",  7, 15, 0.0, "corn",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
    },

    # Paddy rice: transplant May/Jun, harvest Sep/Oct
    "rice": {
        "huai_river": {
            "name": "rice_huaihe",
            "ops": [
                ("till",  5, 10, 0.0, "fldcult",    "null",       0.0),
                ("fert",  5, 15, 0.0, "elem_n",     "broadcast",  100.0),  # Basal
                ("fert",  5, 15, 0.0, "elem_p",     "broadcast",  40.0),
                ("plnt",  5, 20, 0.0, "rice",       "null",       0.0),
                ("fert",  6, 10, 0.0, "elem_n",     "broadcast",  50.0),   # Tillering
                ("fert",  7, 10, 0.0, "elem_n",     "broadcast",  40.0),   # Panicle
                ("harv", 10,  5, 0.0, "rice",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "south_china": {
            "name": "rice_south",
            # Early rice in south China
            "ops": [
                ("till",  3, 15, 0.0, "fldcult",    "null",       0.0),
                ("fert",  3, 20, 0.0, "elem_n",     "broadcast",  110.0),
                ("fert",  3, 20, 0.0, "elem_p",     "broadcast",  45.0),
                ("plnt",  4,  1, 0.0, "rice",       "null",       0.0),
                ("fert",  4, 25, 0.0, "elem_n",     "broadcast",  55.0),
                ("fert",  5, 25, 0.0, "elem_n",     "broadcast",  45.0),
                ("harv",  7, 15, 0.0, "rice",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "north_china": {
            "name": "rice_ncplain",
            "ops": [
                ("till",  5,  5, 0.0, "fldcult",    "null",       0.0),
                ("fert",  5, 10, 0.0, "elem_n",     "broadcast",  90.0),
                ("fert",  5, 10, 0.0, "elem_p",     "broadcast",  35.0),
                ("plnt",  5, 15, 0.0, "rice",       "null",       0.0),
                ("fert",  6,  5, 0.0, "elem_n",     "broadcast",  45.0),
                ("fert",  7,  5, 0.0, "elem_n",     "broadcast",  35.0),
                ("harv",  9, 25, 0.0, "rice",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
        "northeast": {
            "name": "rice_northeast",
            "ops": [
                ("till",  5, 10, 0.0, "fldcult",    "null",       0.0),
                ("fert",  5, 15, 0.0, "elem_n",     "broadcast",  80.0),
                ("fert",  5, 15, 0.0, "elem_p",     "broadcast",  30.0),
                ("plnt",  5, 20, 0.0, "rice",       "null",       0.0),
                ("fert",  6, 15, 0.0, "elem_n",     "broadcast",  40.0),
                ("fert",  7, 15, 0.0, "elem_n",     "broadcast",  30.0),
                ("harv",  9, 20, 0.0, "rice",       "grain",      0.0),
                ("skip",  0,  0, 0.0, "null",       "null",       0.0),
            ],
        },
    },
}

# Double-cropping: wheat_maize rotation
# Built dynamically by combining wheat + maize schedules (remove terminal skip from wheat)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Configure fertilizer and crop management schedules for SWAT+"
    )
    parser.add_argument(
        "--management_sch", required=True,
        help="Path to management.sch (will be modified or created)"
    )
    parser.add_argument(
        "--crop", required=True,
        choices=["wheat", "maize", "rice", "wheat_maize"],
        help="Crop system to configure"
    )
    parser.add_argument(
        "--region", required=True,
        choices=["huai_river", "north_china", "northeast", "south_china"],
        help="Agricultural region for fertilizer rates"
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append new schedule to existing management.sch instead of replacing"
    )
    return parser.parse_args()


def validate_inputs(args):
    errors = []
    if args.crop == "wheat_maize":
        if args.region not in CROP_SCHEDULES["wheat"]:
            errors.append(f"Wheat schedule not available for region: {args.region}")
        if args.region not in CROP_SCHEDULES["maize"]:
            errors.append(f"Maize schedule not available for region: {args.region}")
    else:
        if args.region not in CROP_SCHEDULES.get(args.crop, {}):
            errors.append(f"No schedule for crop={args.crop}, region={args.region}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def format_op_line(op):
    """Format a single operation line in SWAT+ management.sch format."""
    op_type, mon, day, hu_sch, data1, data2, data3 = op
    return (
        f"{'':>48s}{op_type:>8s}"
        f"{mon:>6d}{day:>6d}{hu_sch:>10.3f}"
        f"{'':>2s}{data1:>12s}{'':>2s}{data2:>12s}{data3:>10.3f}"
    )


def format_schedule_header(name, n_ops):
    """Format the schedule header line."""
    return f"{name:<18s}{n_ops:>8d}{0:>10d}{'':>50s}"


def build_schedule(crop, region):
    """Build a single crop schedule."""
    sched = CROP_SCHEDULES[crop][region]
    return sched["name"], sched["ops"]


def build_double_crop_schedule(region):
    """Build wheat-maize double cropping schedule."""
    w_sched = CROP_SCHEDULES["wheat"][region]
    m_sched = CROP_SCHEDULES["maize"][region]

    name = f"wht_mz_{region[:5]}"

    # Combine: all wheat ops except terminal skip, then all maize ops
    combined_ops = []
    for op in w_sched["ops"]:
        if op[0] != "skip":
            combined_ops.append(op)
    for op in m_sched["ops"]:
        combined_ops.append(op)

    return name, combined_ops


def process(args):
    sch_path = Path(args.management_sch)

    # Build schedule(s)
    if args.crop == "wheat_maize":
        sched_name, ops = build_double_crop_schedule(args.region)
    else:
        sched_name, ops = build_schedule(args.crop, args.region)

    n_ops = len(ops)

    # Compute total N and P applied
    total_n = sum(op[6] for op in ops if op[0] == "fert" and "elem_n" in op[4])
    total_p = sum(op[6] for op in ops if op[0] == "fert" and "elem_p" in op[4])

    logger.info(f"Schedule '{sched_name}': {n_ops} operations, "
                f"total N={total_n:.0f} kgN/ha, total P={total_p:.0f} kgP/ha")

    # Format output
    new_lines = []
    new_lines.append(format_schedule_header(sched_name, n_ops))
    for op in ops:
        new_lines.append(format_op_line(op))

    if args.append and sch_path.exists():
        # Read existing content and append
        existing = sch_path.read_text()
        with open(sch_path, "w") as f:
            f.write(existing.rstrip("\n") + "\n")
            for line in new_lines:
                f.write(line + "\n")
        logger.info(f"Appended schedule '{sched_name}' to {sch_path}")
    else:
        # Write new file with header
        with open(sch_path, "w") as f:
            f.write("management.sch: written by SWAT+ knowledge infrastructure (water quality module)\n")
            f.write(
                f"{'name':<18s}{'numb_ops':>8s}{'numb_auto':>10s}"
                f"{'':>14s}{'op_typ':>8s}{'mon':>6s}{'day':>6s}{'hu_sch':>10s}"
                f"{'':>2s}{'op_data1':>12s}{'':>2s}{'op_data2':>12s}{'op_data3':>10s}\n"
            )
            for line in new_lines:
                f.write(line + "\n")
        logger.info(f"Wrote management.sch with schedule '{sched_name}' to {sch_path}")

    return {
        "status": "success",
        "management_sch": str(sch_path),
        "schedule_name": sched_name,
        "crop": args.crop,
        "region": args.region,
        "n_operations": n_ops,
        "total_n_kg_ha": total_n,
        "total_p_kg_ha": total_p,
        "notes": [
            f"Total N application: {total_n:.0f} kgN/ha (Chinese average: 200-300 kgN/ha for grain crops)",
            f"Total P application: {total_p:.0f} kgP/ha",
            "Update landuse.lum to reference this schedule name for agricultural HRUs",
            "Verify fertilizer.frt contains elem_n and elem_p entries",
        ],
    }


def validate_outputs(result):
    sch_path = Path(result["management_sch"])
    if not sch_path.exists():
        logger.error("management.sch not created")
        sys.exit(3)
    # Sanity check: N should be 50-400 kg/ha for Chinese agriculture
    n = result["total_n_kg_ha"]
    if n < 50 or n > 400:
        logger.warning(f"Total N = {n:.0f} kgN/ha is outside typical Chinese range (50-400)")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    args = parse_args()
    validate_inputs(args)
    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
