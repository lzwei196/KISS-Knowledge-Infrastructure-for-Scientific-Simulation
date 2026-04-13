#!/usr/bin/env python3
"""
generate_met_file.py
====================
Generate a RZWQM2 .met file from CSV weather data.

Uses generate_rzwqm_met_header() and write_to_rzwqm_met() from rzwqm_file.py.
The input CSV must contain columns: date, tmin, tmax, wind, radiation, epan, rh, par, rain.
Date column must be parseable (YYYY-MM-DD recommended).

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
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# INPUTS (configure before running, or pass as CLI args)
# ---------------------------------------------------------------------------
INPUT_CSV = ""          # Path to input CSV with weather data
OUTPUT_PATH = ""        # Path for output .met file
START_DATE = ""         # Start date, YYYY-MM-DD
END_DATE = ""           # End date, YYYY-MM-DD

# ---------------------------------------------------------------------------
# Add lib to path so we can import rzwqm_file
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(input_csv, output_path, start_date_str, end_date_str):
    """Validate all inputs before processing. Returns (valid, error_msg, parsed_args)."""
    errors = []

    # Validate input CSV exists
    if not input_csv:
        errors.append("INPUT_CSV is required.")
    elif not os.path.isfile(input_csv):
        errors.append(f"Input CSV not found: {input_csv}")

    # Validate output path directory exists
    if not output_path:
        errors.append("OUTPUT_PATH is required.")
    else:
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.isdir(out_dir):
            errors.append(f"Output directory does not exist: {out_dir}")

    # Validate dates
    start_date = None
    end_date = None
    if not start_date_str:
        errors.append("START_DATE is required (YYYY-MM-DD).")
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        except ValueError:
            errors.append(f"START_DATE '{start_date_str}' is not valid YYYY-MM-DD.")

    if not end_date_str:
        errors.append("END_DATE is required (YYYY-MM-DD).")
    else:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        except ValueError:
            errors.append(f"END_DATE '{end_date_str}' is not valid YYYY-MM-DD.")

    if start_date and end_date and start_date > end_date:
        errors.append("START_DATE must be on or before END_DATE.")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'input_csv': input_csv,
        'output_path': output_path,
        'start_date': start_date,
        'end_date': end_date
    }


def process(args):
    """
    Read the CSV, build met content rows, generate header, and write .met file.
    Returns (success, error_msg, output_path).
    """
    from rzwqm_file import generate_rzwqm_met_header, write_to_rzwqm_met

    input_csv = args['input_csv']
    output_path = args['output_path']
    start_date = args['start_date']
    end_date = args['end_date']

    # Expected CSV columns (case-insensitive matching)
    required_cols = ['date', 'tmin', 'tmax', 'wind', 'radiation', 'epan', 'rh', 'par', 'rain']

    try:
        with open(input_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            # Normalise header names to lowercase
            if reader.fieldnames is None:
                return False, "CSV file has no header row.", None
            col_map = {}
            for col in reader.fieldnames:
                col_map[col.strip().lower()] = col

            missing = [c for c in required_cols if c not in col_map]
            if missing:
                return False, f"CSV missing required columns: {missing}", None

            # Read all rows into a dict keyed by date
            csv_data = {}
            for row in reader:
                date_str = row[col_map['date']].strip()
                # Try multiple date formats
                dt = None
                for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d'):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                if dt is None:
                    return False, f"Cannot parse date: {date_str}", None
                csv_data[dt.date()] = row

        # Build met content rows: each row is a list of 10 string values
        # [julian_day, year, tmin, tmax, wind, radiation, epan, rh, par, rain]
        parsed_content = []
        current = start_date
        while current <= end_date:
            key = current.date()
            if key not in csv_data:
                return False, f"CSV is missing data for date: {key.isoformat()}", None

            row = csv_data[key]
            julian_day = current.timetuple().tm_yday
            year = current.year

            try:
                tmin = float(row[col_map['tmin']])
                tmax = float(row[col_map['tmax']])
                wind = float(row[col_map['wind']])
                radiation = float(row[col_map['radiation']])
                epan = float(row[col_map['epan']])
                rh = float(row[col_map['rh']])
                par = float(row[col_map['par']])
                rain = float(row[col_map['rain']])
            except (ValueError, KeyError) as e:
                return False, f"Error parsing numeric values for {key}: {e}", None

            # E-pan and PAR must be 0 — let RZWQM2 compute them internally.
            # Non-zero values override the model's ET calculation and cause
            # incorrect water balance (crop water stress even with wet soil).
            parsed_content.append([
                str(julian_day), str(year),
                str(round(tmin, 2)), str(round(tmax, 2)),
                str(round(wind, 2)), str(round(radiation, 2)),
                '0', str(round(rh, 2)),
                '0', str(round(rain, 2))
            ])
            current += timedelta(days=1)

        # Generate header (36 lines)
        header = generate_rzwqm_met_header(start_date, end_date)

        # Write .met file
        write_to_rzwqm_met(output_path, parsed_content, header)

        return True, "", output_path

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(output_path, start_date, end_date):
    """Validate the generated .met file. Returns (valid, error_msg)."""
    errors = []

    if not os.path.isfile(output_path):
        return False, f"Output file was not created: {output_path}"

    with open(output_path, 'r') as f:
        lines = [line.rstrip('\n') for line in f]

    # Header must be exactly 36 lines
    if len(lines) < 36:
        errors.append(f"Met file has only {len(lines)} lines; expected at least 36 header lines.")
    else:
        # Check header markers
        if not lines[0].startswith("===="):
            errors.append("First header line does not start with '===='.")

        # Check data line count
        expected_days = (end_date - start_date).days + 1
        data_lines = lines[36:]
        # Filter out empty lines
        data_lines = [l for l in data_lines if l.strip()]
        if len(data_lines) != expected_days:
            errors.append(
                f"Expected {expected_days} data lines, found {len(data_lines)}."
            )

        # Spot-check first data line has 10 fields
        if data_lines:
            fields = data_lines[0].split()
            if len(fields) != 10:
                errors.append(
                    f"First data line has {len(fields)} fields, expected 10."
                )

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    # Allow CLI overrides: input_csv output_path start_date end_date
    input_csv = sys.argv[1] if len(sys.argv) > 1 else INPUT_CSV
    output_path = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_PATH
    start_date_str = sys.argv[3] if len(sys.argv) > 3 else START_DATE
    end_date_str = sys.argv[4] if len(sys.argv) > 4 else END_DATE

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(input_csv, output_path, start_date_str, end_date_str)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, out_path = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(out_path, args['start_date'], args['end_date'])
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "output_file": out_path,
        "message": f"Met file generated at {out_path}"
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
