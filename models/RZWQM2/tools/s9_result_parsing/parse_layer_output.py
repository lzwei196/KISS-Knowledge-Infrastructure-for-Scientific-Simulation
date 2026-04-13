#!/usr/bin/env python3
"""
parse_layer_output.py
=====================
Parse RZWQM2 profile output (Layer.plt) to extract depth-resolved variables
like soil temperature by node.

The Layer.plt file contains records for each computational node at each
output time step. This tool extracts a specific column and organises it
by depth, producing a CSV with one row per depth and columns for each
time step.

Uses rzwqm_parse_layer() and return_soil_temperature() from the RZWQM
class in rzwqm_file.py.

Inputs:
    project_path    - RZWQM2 project root path
    station_id      - Station or grid identifier
    column_num      - Column index to extract (e.g., 4 for soil temperature)
    output_csv      - Output CSV path (optional; defaults to
                      <project_path>/<station_id>/layer_col<N>.csv)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import csv
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path
STATION_ID = ""         # Station or grid identifier
COLUMN_NUM = ""         # Column index for desired variable
OUTPUT_CSV = ""         # Output CSV path (optional)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id, column_num_raw, output_csv):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    column_num = None
    if not column_num_raw:
        errors.append("COLUMN_NUM is required (integer column index).")
    else:
        try:
            column_num = int(column_num_raw)
            if column_num < 0:
                errors.append("COLUMN_NUM must be >= 0.")
        except ValueError:
            errors.append(f"COLUMN_NUM must be an integer, got: {column_num_raw}")

    # Check Layer.plt file exists (case varies: LAYER.PLT on Windows, Layer.plt mixed)
    layer_path = None
    if project_path and station_id:
        base_dir = os.path.join(project_path, station_id)
        for candidate in ('LAYER.PLT', 'Layer.plt', 'layer.plt'):
            p = os.path.join(base_dir, candidate)
            if os.path.isfile(p):
                layer_path = p
                break
        if layer_path is None:
            layer_path = os.path.join(base_dir, 'LAYER.PLT')
            errors.append(f"Layer.plt not found: {layer_path}")

    # Set default output path
    if not output_csv and project_path and station_id and column_num is not None:
        output_csv = os.path.join(
            project_path, station_id,
            f"layer_col{column_num}.csv"
        )

    if output_csv:
        out_dir = os.path.dirname(output_csv)
        if out_dir and not os.path.isdir(out_dir):
            errors.append(f"Output directory does not exist: {out_dir}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'column_num': column_num,
        'output_csv': output_csv,
        'layer_path': layer_path
    }


def process(args):
    """
    Parse Layer.plt and extract the specified column by depth.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM

    project_path = args['project_path']
    station_id = args['station_id']
    column_num = args['column_num']
    output_csv = args['output_csv']

    try:
        rz = RZWQM(project_path, station_id)
        depth_data = rz.return_soil_temperature(column_num)

        if not depth_data:
            return False, (
                f"No data extracted from Layer.plt for column {column_num}."
            ), None

        # Write to CSV: rows are depths, columns are time steps
        depths = sorted(depth_data.keys())
        max_timesteps = max(len(depth_data[d]) for d in depths)

        with open(output_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            header = ['depth_cm'] + [f't{i+1}' for i in range(max_timesteps)]
            writer.writerow(header)
            for depth in depths:
                row = [depth] + depth_data[depth]
                writer.writerow(row)

        summary = {
            'output_csv': output_csv,
            'column_num': column_num,
            'num_depths': len(depths),
            'depths_cm': depths,
            'timesteps_per_depth': max_timesteps
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(output_csv, column_num):
    """Validate the output CSV."""
    errors = []

    if not os.path.isfile(output_csv):
        return False, f"Output CSV was not created: {output_csv}"

    with open(output_csv, 'r') as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        errors.append("Output CSV has no data rows.")
    else:
        header = rows[0]
        if header[0] != 'depth_cm':
            errors.append(f"Unexpected header: {header[0]}, expected 'depth_cm'.")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    column_num_raw = sys.argv[3] if len(sys.argv) > 3 else COLUMN_NUM
    output_csv = sys.argv[4] if len(sys.argv) > 4 else OUTPUT_CSV

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, column_num_raw, output_csv)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args['output_csv'], args['column_num'])
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "summary": summary,
        "message": (
            f"Extracted column {summary['column_num']} from Layer.plt. "
            f"{summary['num_depths']} depths, {summary['timesteps_per_depth']} timesteps each. "
            f"Written to {summary['output_csv']}."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
