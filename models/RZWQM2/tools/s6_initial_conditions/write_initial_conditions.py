#!/usr/bin/env python3
"""
write_initial_conditions.py
===========================
Write initial soil water content/tension, temperature, chemistry (pH, CEC,
organic carbon), and nutrient pools to RZINIT.dat.

The tool writes three sections of RZINIT.dat:
  1. Water & temperature: initial tension and temperature per horizon
  2. Chemistry: pH, CEC, organic carbon, etc. per horizon (3 lines each)
  3. Nutrients: N pools per horizon (1 line each)

Uses write_new_soil_init_water_and_temp(), write_new_soil_init_chemistry(),
and write_new_soil_init_nutrient() from the RZWQM class in rzwqm_file.py.

Inputs:
    project_path    - RZWQM2 project root path
    station_id      - Station or grid identifier
    num_horizons    - Number of soil horizons (must match RZWQM.dat)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path
STATION_ID = ""         # Station or grid identifier
NUM_HORIZONS = ""       # Number of soil horizons

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id, num_horizons_raw):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    num_horizons = 0
    if not num_horizons_raw:
        errors.append("NUM_HORIZONS is required.")
    else:
        try:
            num_horizons = int(num_horizons_raw)
            if num_horizons < 1:
                errors.append("NUM_HORIZONS must be >= 1.")
            elif num_horizons > 20:
                errors.append(f"NUM_HORIZONS={num_horizons} exceeds MAXHOR=20.")
        except ValueError:
            errors.append(f"NUM_HORIZONS must be an integer, got: {num_horizons_raw}")

    # Check RZINIT.dat exists
    init_path = None
    if project_path and station_id:
        init_path = os.path.join(project_path, station_id, 'RZINIT.dat')
        if not os.path.isfile(init_path):
            alt_path = os.path.join(project_path, station_id, 'rzinit.dat')
            if os.path.isfile(alt_path):
                init_path = alt_path
            else:
                errors.append(f"RZINIT.dat not found: {init_path}")

    # Cross-check with RZWQM.dat horizon count
    if project_path and station_id and num_horizons > 0:
        dat_path = os.path.join(project_path, station_id, 'RZWQM.dat')
        if os.path.isfile(dat_path):
            try:
                from rzwqm_file import RZWQM
                rz = RZWQM(project_path, station_id)
                dat_horizons = rz.return_number_of_soil_horizons()
                if dat_horizons != num_horizons:
                    errors.append(
                        f"NUM_HORIZONS={num_horizons} does not match "
                        f"RZWQM.dat horizon count={dat_horizons}. "
                        f"These must be consistent."
                    )
            except Exception:
                pass  # Non-fatal: RZWQM.dat may not be set up yet

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'num_horizons': num_horizons,
        'init_path': init_path
    }


def process(args):
    """
    Write initial conditions to RZINIT.dat.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM

    project_path = args['project_path']
    station_id = args['station_id']
    num_horizons = args['num_horizons']

    try:
        rz = RZWQM(project_path, station_id)

        # Create a list of horizon indices for the write methods
        horizon_list = list(range(1, num_horizons + 1))

        # Write water & temperature initial conditions
        # Uses linear tension gradient: deepest horizon = 0 (saturated),
        # each horizon above gets -10 more tension
        rz.write_new_soil_init_water_and_temp(horizon_list)

        # Write chemistry initial conditions (placeholder values)
        rz.write_new_soil_init_chemistry(horizon_list)

        # Write nutrient initial conditions (placeholder values)
        rz.write_new_soil_init_nutrient(horizon_list)

        summary = {
            'num_horizons': num_horizons,
            'sections_written': ['water_and_temperature', 'chemistry', 'nutrients'],
            'init_water_mode': 'tension (tensio_flag=0)',
            'init_temperature': '10-15 C gradient'
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Verify that initial conditions were written."""
    errors = []

    init_path = args['init_path']
    if not os.path.isfile(init_path):
        return False, "RZINIT.dat disappeared after processing."

    try:
        with open(init_path, encoding="ISO-8859-1") as f:
            content = f.read()

        # Basic sanity: file should not be empty
        if len(content) < 100:
            errors.append("RZINIT.dat appears too short after write.")

    except Exception as e:
        errors.append(f"Could not read RZINIT.dat after write: {e}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    num_horizons_raw = sys.argv[3] if len(sys.argv) > 3 else NUM_HORIZONS

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, num_horizons_raw)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "init_file": args['init_path'],
        "summary": summary,
        "message": (
            f"Initial conditions written for {summary['num_horizons']} horizons. "
            f"Sections: {', '.join(summary['sections_written'])}."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
