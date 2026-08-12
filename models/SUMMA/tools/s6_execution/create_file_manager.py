#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_file_manager
Stage:        s6_execution
Description:  Generate the SUMMA master configuration file (fileManager.txt).
              This file points to ALL other config files. Uses ABSOLUTE paths
              to avoid Fortran path resolution issues (CHARACTER variable
              length truncation -- see dt_001).

              CRITICAL: controlVersion MUST be 'SUMMA_FILE_MANAGER_V3.0.0'.
              CRITICAL: All paths MUST be ABSOLUTE (Fortran reads from CWD).
              CRITICAL: Path strings MUST be enclosed in single quotes.
              CRITICAL: Paths that end in '/' indicate directories.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SETTINGS_PATH = ""
FORCING_PATH = ""
OUTPUT_PATH = ""
SIM_START = ""        # "YYYY-MM-DD hh:mm"
SIM_END = ""          # "YYYY-MM-DD hh:mm"
OUTPUT_PREFIX = "summa"
OUTPUT_FILE = ""

# File names within SETTINGS_PATH
DECISIONS_FILE = "decisions.txt"
OUTPUT_CONTROL_FILE = "outputControl.txt"
ATTRIBUTES_FILE = "attributes.nc"
HRU_PARAM_FILE = "localParamInfo.txt"
GRU_PARAM_FILE = "basinParamInfo.txt"
FORCING_LIST_FILE = "forcingFileList.txt"
INIT_COND_FILE = "coldState.nc"
TRIAL_PARAM_FILE = "trialParams.nc"
VEG_TABLE_FILE = "VEGPARM.TBL"
SOIL_TABLE_FILE = "SOILPARM.TBL"
GEN_TABLE_FILE = "GENPARM.TBL"
NOAHMP_TABLE_FILE = "MPTABLE.TBL"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Create SUMMA fileManager.txt")
    parser.add_argument("--settings_path", required=True)
    parser.add_argument("--forcing_path", required=True)
    parser.add_argument("--output_path", required=True)
    parser.add_argument("--sim_start", required=True, help="YYYY-MM-DD hh:mm")
    parser.add_argument("--sim_end", required=True, help="YYYY-MM-DD hh:mm")
    parser.add_argument("--output_prefix", default="summa")
    parser.add_argument("--output_file", required=True, help="Path for fileManager.txt")
    parser.add_argument("--decisions", default="decisions.txt")
    parser.add_argument("--attributes", default="attributes.nc")
    parser.add_argument("--init_cond", default="coldState.nc")
    parser.add_argument("--trial_params", default="trialParams.nc")
    parser.add_argument("--forcing_list", default="forcingFileList.txt")
    args = parser.parse_args()
    SETTINGS_PATH = args.settings_path
    FORCING_PATH = args.forcing_path
    OUTPUT_PATH = args.output_path
    SIM_START = args.sim_start
    SIM_END = args.sim_end
    OUTPUT_PREFIX = args.output_prefix
    OUTPUT_FILE = args.output_file
    DECISIONS_FILE = args.decisions
    ATTRIBUTES_FILE = args.attributes
    INIT_COND_FILE = args.init_cond
    TRIAL_PARAM_FILE = args.trial_params
    FORCING_LIST_FILE = args.forcing_list


# Maximum path length in SUMMA Fortran (from summaFileManager.f90)
MAX_PATH_LENGTH = 256


def validate_inputs():
    errors = []
    warnings = []

    if not SETTINGS_PATH:
        errors.append("SETTINGS_PATH is not set")
    if not FORCING_PATH:
        errors.append("FORCING_PATH is not set")
    if not OUTPUT_PATH:
        errors.append("OUTPUT_PATH is not set")
    if not SIM_START:
        errors.append("SIM_START is not set")
    if not SIM_END:
        errors.append("SIM_END is not set")
    if not OUTPUT_FILE:
        errors.append("OUTPUT_FILE is not set")

    # Check absolute paths
    for name, path in [('SETTINGS_PATH', SETTINGS_PATH),
                        ('FORCING_PATH', FORCING_PATH),
                        ('OUTPUT_PATH', OUTPUT_PATH)]:
        if path and not os.path.isabs(path):
            errors.append(f"{name} must be an ABSOLUTE path (got: {path}). "
                          "SUMMA Fortran resolves paths from the executable CWD, "
                          "not from the fileManager location.")
        if path and len(path) > MAX_PATH_LENGTH:
            errors.append(f"{name} path length {len(path)} exceeds Fortran "
                          f"CHARACTER limit {MAX_PATH_LENGTH}. Use symlinks.")

    # Validate time format
    import re
    time_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}'
    if SIM_START and not re.match(time_pattern, SIM_START):
        errors.append(f"SIM_START format must be 'YYYY-MM-DD hh:mm', got '{SIM_START}'")
    if SIM_END and not re.match(time_pattern, SIM_END):
        errors.append(f"SIM_END format must be 'YYYY-MM-DD hh:mm', got '{SIM_END}'")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    for w in warnings:
        logger.warning(w)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    errors = []
    if not Path(output_path).exists():
        errors.append(f"Output not created: {output_path}")
    else:
        with open(output_path) as f:
            content = f.read()
            if "SUMMA_FILE_MANAGER_V3.0.0" not in content:
                errors.append("controlVersion not found in fileManager.txt")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def ensure_forcing_list(settings, forcing):
    """Guarantee forcingListFile exists where SUMMA actually reads it.

    dt_032. SUMMA resolves the forcing file list against settingsPath, NOT
    forcingPath:

        ffile_info.f90:86   infile = trim(SETTINGS_PATH)//trim(FORCING_FILELIST)

    The individual .nc names *inside* that list are then resolved against
    forcingPath (ffile_info.f90:120), so the list and the data it names live in
    two DIFFERENT directories. That asymmetry is easy to miss, and the s2
    forcing builders write forcingFileList.txt next to the .nc files they
    produce (i.e. in forcingPath) because that is the only directory they are
    given. The result is a fileManager that references a file SUMMA cannot
    find, surfacing much later as validate_file_manager's
    "forcingListFile: file not found at '<settings>/forcingFileList.txt'".

    create_file_manager is the one tool that knows BOTH paths, so it owns this
    contract. Resolution order:
      1. already in settingsPath  -> leave it alone (author's own list wins)
      2. present in forcingPath   -> copy it across, preserving order
      3. neither                  -> synthesise from the .nc files in
                                     forcingPath, sorted by name (the s2 tools
                                     emit forcing_YYYY.nc, so lexical order IS
                                     chronological order; SUMMA requires
                                     chronological order, ffile_info.f90:145).
    Returns a dict describing what happened, for the stdout JSON.
    """
    import glob as _glob
    import shutil as _shutil

    dst = os.path.join(settings, FORCING_LIST_FILE)
    src = os.path.join(forcing, FORCING_LIST_FILE)

    if os.path.isfile(dst):
        return {"action": "already_present", "path": dst}

    os.makedirs(settings, exist_ok=True)

    if os.path.isfile(src):
        _shutil.copyfile(src, dst)
        logger.info(
            f"forcingListFile: copied {src} -> {dst} (SUMMA reads the list "
            f"from settingsPath, ffile_info.f90:86)")
        action = "copied_from_forcing_path"
    else:
        names = sorted(os.path.basename(p)
                       for p in _glob.glob(os.path.join(forcing, "*.nc")))
        if not names:
            logger.error(
                f"no forcing list and no *.nc files in {forcing} -- cannot "
                f"build forcingListFile")
            raise FileNotFoundError(
                f"forcingListFile missing from both '{settings}' and "
                f"'{forcing}', and '{forcing}' contains no *.nc forcing files")
        with open(dst, 'w') as fh:
            for n in names:
                fh.write(f"{n}\n")
        logger.info(f"forcingListFile: synthesised {dst} from {len(names)} "
                    f"*.nc files in forcingPath (sorted chronologically)")
        action = "synthesised_from_forcing_dir"

    with open(dst) as fh:
        entries = [l.strip() for l in fh if l.strip()
                   and not l.strip().startswith('!')]
    missing = [e for e in entries if not os.path.isfile(os.path.join(forcing, e))]
    if missing:
        logger.warning(
            f"forcingListFile names {len(missing)} file(s) absent from "
            f"forcingPath (SUMMA resolves them there): {missing[:5]}")
    return {"action": action, "path": dst, "n_entries": len(entries),
            "n_missing_in_forcing_path": len(missing)}


def process():
    """Generate fileManager.txt."""
    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    os.makedirs(OUTPUT_PATH, exist_ok=True)

    # Ensure paths end with /
    settings = SETTINGS_PATH.rstrip('/') + '/'
    forcing = FORCING_PATH.rstrip('/') + '/'
    output = OUTPUT_PATH.rstrip('/') + '/'

    forcing_list_info = ensure_forcing_list(settings, forcing)

    with open(OUTPUT_FILE, 'w') as f:
        f.write("! ====================================================================\n")
        f.write("! SUMMA fileManager.txt\n")
        f.write("! Generated by create_file_manager.py (Knowledge Infrastructure)\n")
        f.write("! CRITICAL: All paths are ABSOLUTE to avoid Fortran CWD issues\n")
        f.write("! ====================================================================\n\n")

        f.write(f"controlVersion   'SUMMA_FILE_MANAGER_V3.0.0'\n")
        f.write(f"simStartTime     '{SIM_START}'\n")
        f.write(f"simEndTime       '{SIM_END}'\n")
        f.write(f"tmZoneInfo       'utcTime'\n\n")

        f.write(f"! --- Paths ---\n")
        f.write(f"settingsPath     '{settings}'\n")
        f.write(f"forcingPath      '{forcing}'\n")
        f.write(f"outputPath       '{output}'\n\n")

        f.write(f"! --- Configuration files (relative to settingsPath) ---\n")
        f.write(f"decisionsFile    '{DECISIONS_FILE}'\n")
        f.write(f"outputControlFile '{OUTPUT_CONTROL_FILE}'\n")
        f.write(f"attributeFile    '{ATTRIBUTES_FILE}'\n")
        f.write(f"globalHruParamFile '{HRU_PARAM_FILE}'\n")
        f.write(f"globalGruParamFile '{GRU_PARAM_FILE}'\n")
        f.write(f"trialParamFile   '{TRIAL_PARAM_FILE}'\n")
        f.write(f"forcingListFile  '{FORCING_LIST_FILE}'\n")
        f.write(f"initConditionFile '{INIT_COND_FILE}'\n\n")

        f.write(f"! --- Parameter tables (relative to settingsPath) ---\n")
        f.write(f"vegTableFile     '{VEG_TABLE_FILE}'\n")
        f.write(f"soilTableFile    '{SOIL_TABLE_FILE}'\n")
        f.write(f"generalTableFile '{GEN_TABLE_FILE}'\n")
        f.write(f"noahmpTableFile  '{NOAHMP_TABLE_FILE}'\n\n")

        f.write(f"! --- Output prefix ---\n")
        f.write(f"outFilePrefix    '{OUTPUT_PREFIX}'\n")

    logger.info(f"fileManager.txt created: {OUTPUT_FILE}")

    print(json.dumps({
        "status": "success",
        "output": OUTPUT_FILE,
        "settings_path": settings,
        "forcing_path": forcing,
        "output_path": output,
        "sim_period": f"{SIM_START} to {SIM_END}",
        "forcing_list": forcing_list_info
    }))

    return OUTPUT_FILE


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
