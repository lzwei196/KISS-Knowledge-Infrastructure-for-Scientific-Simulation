#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      validate_file_manager
Stage:        s6_execution
Description:  Validate SUMMA fileManager.txt by checking that all referenced
              files exist, paths are absolute, version string is correct,
              and NetCDF files have consistent dimensions.

              This prevents the #1 SUMMA runtime error: "file not found"
              crashes from Fortran open() calls that produce cryptic error
              messages (STOP 10, STOP 20, etc.).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FILE_MANAGER_PATH = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Validate SUMMA fileManager.txt")
    parser.add_argument("--file_manager", required=True)
    args = parser.parse_args()
    FILE_MANAGER_PATH = args.file_manager


def validate_inputs():
    errors = []
    if not FILE_MANAGER_PATH or not Path(FILE_MANAGER_PATH).exists():
        errors.append(f"fileManager.txt not found: {FILE_MANAGER_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """Parse and validate fileManager.txt."""
    errors = []
    warnings = []

    # Parse fileManager
    config = {}
    with open(FILE_MANAGER_PATH) as f:
        for line in f:
            line = line.split('!')[0].strip()  # remove comments
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0]
                # Extract value from quotes
                value_match = re.search(r"'([^']*)'", line)
                if value_match:
                    config[key] = value_match.group(1)
                else:
                    config[key] = parts[1]

    logger.info(f"Parsed {len(config)} entries from fileManager.txt")

    # 1. Check version
    version = config.get('controlVersion', '')
    if version != 'SUMMA_FILE_MANAGER_V3.0.0':
        errors.append(f"controlVersion must be 'SUMMA_FILE_MANAGER_V3.0.0', got '{version}'")

    # 2. Check base paths exist and are absolute
    for key in ['settingsPath', 'forcingPath', 'outputPath']:
        path = config.get(key, '')
        if not path:
            errors.append(f"Missing required path: {key}")
        elif not os.path.isabs(path):
            errors.append(f"{key}='{path}' is not an absolute path. "
                          "SUMMA resolves from CWD, not from fileManager location.")
        elif not os.path.exists(path):
            warnings.append(f"{key}='{path}' does not exist (will be created for outputPath)")
            if key != 'outputPath':
                errors.append(f"{key}='{path}' directory does not exist")

    # 3. Check referenced files exist
    settings = config.get('settingsPath', '')
    forcing = config.get('forcingPath', '')

    file_keys = {
        'decisionsFile': settings,
        'outputControlFile': settings,
        'attributeFile': settings,
        'globalHruParamFile': settings,
        'globalGruParamFile': settings,
        'trialParamFile': settings,
        'forcingListFile': settings,
        'initConditionFile': settings,
        'vegTableFile': settings,
        'soilTableFile': settings,
        'generalTableFile': settings,
        'noahmpTableFile': settings,
    }

    for key, base_path in file_keys.items():
        filename = config.get(key, '')
        if not filename:
            if key in ('trialParamFile',):  # optional
                continue
            errors.append(f"Missing required entry: {key}")
            continue
        full_path = os.path.join(base_path, filename)
        if not os.path.exists(full_path):
            errors.append(f"{key}: file not found at '{full_path}'")
        else:
            logger.info(f"  OK: {key} -> {full_path}")

    # 4. Check forcing files listed in forcingListFile
    forcing_list = config.get('forcingListFile', '')
    if forcing_list and settings:
        flist_path = os.path.join(settings, forcing_list)
        if os.path.exists(flist_path):
            with open(flist_path) as fl:
                for line in fl:
                    fname = line.strip().strip("'\"")
                    if fname:
                        fpath = os.path.join(forcing, fname)
                        if not os.path.exists(fpath):
                            errors.append(f"Forcing file not found: '{fpath}'")
                        else:
                            logger.info(f"  OK: forcing -> {fpath}")

    # 5. Check time format
    for key in ['simStartTime', 'simEndTime']:
        val = config.get(key, '')
        if not re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', val):
            errors.append(f"{key}='{val}' does not match 'YYYY-MM-DD hh:mm' format")

    # 6. Check NetCDF dimension consistency
    nc_files = ['attributeFile', 'initConditionFile', 'trialParamFile']
    hru_counts = {}
    for key in nc_files:
        filename = config.get(key, '')
        if not filename:
            continue
        full_path = os.path.join(settings, filename)
        if os.path.exists(full_path) and full_path.endswith('.nc'):
            try:
                from netCDF4 import Dataset
                ds = Dataset(full_path, 'r')
                if 'hru' in ds.dimensions:
                    hru_counts[key] = len(ds.dimensions['hru'])
                ds.close()
            except Exception as e:
                warnings.append(f"Cannot read {key} for dimension check: {e}")

    if len(set(hru_counts.values())) > 1:
        errors.append(f"Inconsistent hru dimensions across NetCDF files: {hru_counts}")
    elif hru_counts:
        logger.info(f"  HRU dimension consistent: {list(hru_counts.values())[0]} across {list(hru_counts.keys())}")

    # 7. Check path lengths (Fortran CHARACTER limit)
    for key, val in config.items():
        if 'Path' in key or 'File' in key:
            total_len = len(config.get('settingsPath', '')) + len(val)
            if total_len > 256:
                warnings.append(f"Total path for {key} is {total_len} chars, "
                                f"may exceed Fortran CHARACTER(256) limit")

    # Report
    report = {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "entries_parsed": len(config),
        "hru_dimensions": hru_counts
    }

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        logger.error(f"Validation FAILED: {len(errors)} error(s)")
        print(json.dumps(report, indent=2))
        sys.exit(2)
    else:
        logger.info(f"Validation PASSED ({len(warnings)} warning(s))")
        print(json.dumps(report, indent=2))

    return FILE_MANAGER_PATH


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        process()
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(2)
    sys.exit(0)
