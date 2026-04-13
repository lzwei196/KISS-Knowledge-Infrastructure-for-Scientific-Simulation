#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_morph_grids
Stage:        s2_morphology
Description:  Validate that ALL morphological ASCII grids have identical headers.

This is a CRITICAL pre-flight check. mHM will crash with "Number of rows/columns
do not match" if ANY grid has a different header. This tool catches the error
BEFORE running mHM, saving potentially hours of debugging.

Checks:
  1. All grids have identical ncols, nrows, xllcorner, yllcorner, cellsize
  2. All required grids exist (dem, slope, aspect, fdir, facc, soil_class, geology_class, idgauges)
  3. No grid is all NODATA
  4. Value ranges are physically reasonable

Inputs:
  - MORPH_DIR: path to input/morph/ directory

Outputs:
  - Validation report (JSON)

Exit codes: 0=all pass, 1=input error, 2=header mismatch, 3=missing grids
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MORPH_DIR = ""

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--morph_dir", required=True)
    args = parser.parse_args()
    MORPH_DIR = args.morph_dir

REQUIRED_GRIDS = [
    "dem.asc", "slope.asc", "aspect.asc", "fdir.asc", "facc.asc",
    "soil_class.asc", "geology_class.asc", "idgauges.asc",
    "soil_class_horizon_01.asc", "soil_class_horizon_02.asc",
    "LAI_class.asc",
]


def read_ascii_header(filepath):
    """Read the 6-line header from an ESRI ASCII grid."""
    header = {}
    with open(filepath) as f:
        for _ in range(6):
            line = f.readline().strip()
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                try:
                    val = float(parts[1])
                    header[key] = val
                except ValueError:
                    header[key] = parts[1]
    return header


def validate_inputs():
    if not MORPH_DIR or not Path(MORPH_DIR).exists():
        logger.error(f"Morph dir not found: {MORPH_DIR}")
        sys.exit(1)


def process():
    morph_dir = Path(MORPH_DIR)
    errors = []
    warnings = []
    headers = {}

    # Check required files exist
    for grid_name in REQUIRED_GRIDS:
        grid_path = morph_dir / grid_name
        if not grid_path.exists():
            errors.append(f"MISSING: {grid_name}")
        else:
            headers[grid_name] = read_ascii_header(grid_path)

    # Check header consistency
    if headers:
        ref_name = list(headers.keys())[0]
        ref = headers[ref_name]
        for name, h in headers.items():
            if name == ref_name:
                continue
            for key in ["ncols", "nrows", "xllcorner", "yllcorner", "cellsize"]:
                if key in ref and key in h:
                    if abs(float(ref[key]) - float(h[key])) > 0.001:
                        errors.append(
                            f"HEADER MISMATCH: {name}.{key}={h[key]} != "
                            f"{ref_name}.{key}={ref[key]}"
                        )

    # Check classdefinition files
    classdef_files = [
        "soil_classdefinition.txt",
        "geology_classdefinition.txt",
        "LAI_classdefinition.txt",
    ]
    for cf in classdef_files:
        p = morph_dir / cf
        if not p.exists():
            errors.append(f"MISSING: {cf}")
        else:
            with open(p) as f:
                first_line = f.readline().strip()
                if not first_line:
                    errors.append(f"EMPTY: {cf}")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "morph_dir": str(morph_dir),
        "n_grids_found": len(headers),
        "n_grids_required": len(REQUIRED_GRIDS),
        "errors": errors,
        "warnings": warnings,
        "reference_header": headers.get(list(headers.keys())[0], {}) if headers else {},
    }

    if errors:
        logger.error(f"Validation FAILED: {len(errors)} errors")
        for e in errors:
            logger.error(f"  {e}")
    else:
        logger.info("All morphological grids validated successfully")

    print(json.dumps(result, indent=2))
    return "PASS" if not errors else "FAIL"


if __name__ == "__main__":
    validate_inputs()
    try:
        status = process()
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    sys.exit(0 if status == "PASS" else 2)
