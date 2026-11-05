#!/usr/bin/env python3
"""
Parse GSFLOW output files and extract time series to CSV.

Usage:
    python parse_gsflow_output.py \
        --output-dir /path/to/model/output/ \
        --control-file /path/to/gsflow.control \
        --csv-out /path/to/extracted_timeseries.csv \
        --variables basin_cfs,basin_ppt,basin_actet

Pipeline Stage: s7 (Output Parsing)
Follows: validate → process → validate pattern

Supported output formats:
    - PRMS CSV basin summary (csv_output_file)
    - PRMS statvar output (stat_var_file)
    - PRMS basin summary (model_output_file)
    - MODFLOW listing file (water budget)
    - SFR gage output (streamflow at segments)
"""

import os
import sys
import argparse
import csv
import re
from datetime import datetime, timedelta

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None


# GSFLOW output variable metadata
OUTPUT_VARS = {
    "basin_cfs": {"units": "ft3/s", "description": "Basin outlet streamflow"},
    "basin_ppt": {"units": "inches", "description": "Basin precipitation"},
    "basin_tmax": {"units": "degF_or_C", "description": "Basin max temperature"},
    "basin_tmin": {"units": "degF_or_C", "description": "Basin min temperature"},
    "basin_potet": {"units": "inches", "description": "Basin potential ET"},
    "basin_actet": {"units": "inches", "description": "Basin actual ET"},
    "basin_sroff": {"units": "inches", "description": "Basin surface runoff"},
    "basin_ssflow": {"units": "inches", "description": "Basin subsurface flow"},
    "basin_gwflow": {"units": "inches", "description": "Basin groundwater flow"},
    "basin_stflow": {"units": "inches", "description": "Basin total streamflow"},
    "basin_soil_moist": {"units": "inches", "description": "Basin soil moisture"},
    "basin_recharge": {"units": "inches", "description": "Basin GW recharge"},
    "basin_snow": {"units": "inches", "description": "Basin snowpack SWE"},
}

CFS_TO_CMS = 0.028316847


def validate_inputs(output_dir, control_file, variables):
    """Validate inputs before parsing."""
    errors = []

    if output_dir and not os.path.isdir(output_dir):
        errors.append(f"Output directory not found: {output_dir}")

    if control_file and not os.path.isfile(control_file):
        errors.append(f"Control file not found: {control_file}")

    if variables:
        for var in variables:
            if var not in OUTPUT_VARS and not var.startswith("seg_") and not var.startswith("hru_"):
                print(f"WARNING: Unknown variable '{var}' — will attempt extraction anyway")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def parse_csv_output(csv_file, variables=None):
    """
    Parse PRMS CSV basin summary output.

    Format varies by GSFLOW version:
        New: Date,var1,var2,...
        Old: Year,Month,Day,var1,var2,...

    Returns: list of dicts with 'date' key and variable keys
    """
    if not os.path.isfile(csv_file):
        raise FileNotFoundError(f"CSV output not found: {csv_file}")

    records = []
    with open(csv_file) as f:
        reader = csv.reader(f)
        header = next(reader)
        header = [h.strip() for h in header]

        # Detect date format
        has_date_col = "Date" in header or "date" in header
        has_ymd = all(c in header for c in ["Year", "Month", "Day"])

        for row in reader:
            if not row or row[0].startswith("#"):
                continue

            record = {}
            if has_date_col:
                date_idx = header.index("Date") if "Date" in header else header.index("date")
                record["date"] = row[date_idx].strip()
                for i, col in enumerate(header):
                    if i != date_idx and col.strip():
                        try:
                            record[col.strip()] = float(row[i])
                        except (ValueError, IndexError):
                            pass
            elif has_ymd:
                y_idx = header.index("Year")
                m_idx = header.index("Month")
                d_idx = header.index("Day")
                try:
                    y, m, d = int(row[y_idx]), int(row[m_idx]), int(row[d_idx])
                    record["date"] = f"{y:04d}-{m:02d}-{d:02d}"
                except (ValueError, IndexError):
                    continue
                for i, col in enumerate(header):
                    if i not in (y_idx, m_idx, d_idx) and col.strip():
                        try:
                            record[col.strip()] = float(row[i])
                        except (ValueError, IndexError):
                            pass
            else:
                # Try parsing first 3 columns as Y M D
                try:
                    y, m, d = int(row[0]), int(row[1]), int(row[2])
                    record["date"] = f"{y:04d}-{m:02d}-{d:02d}"
                    for i in range(3, len(row)):
                        if i < len(header):
                            try:
                                record[header[i].strip()] = float(row[i])
                            except ValueError:
                                pass
                except (ValueError, IndexError):
                    continue

            records.append(record)

    # Filter variables if specified
    if variables:
        filtered = []
        for rec in records:
            frec = {"date": rec["date"]}
            for var in variables:
                if var in rec:
                    frec[var] = rec[var]
            filtered.append(frec)
        records = filtered

    return records


def parse_statvar_output(statvar_file, variables=None):
    """
    Parse PRMS statvar output file.

    Format:
        n_variables
        var1 element_id
        var2 element_id
        ...
        timestep YYYY MM DD HH MM SS val1 val2 ...
    (statvar_out.f90 writes Timestep, Nowtime(1:6), values)
    """
    if not os.path.isfile(statvar_file):
        raise FileNotFoundError(f"Statvar file not found: {statvar_file}")

    with open(statvar_file) as f:
        lines = f.readlines()

    if not lines:
        raise ValueError(f"Empty statvar file: {statvar_file}")

    # Parse header
    n_vars = int(lines[0].strip())
    var_names = []
    for i in range(1, n_vars + 1):
        parts = lines[i].strip().split()
        var_names.append(parts[0])

    # Parse data
    records = []
    data_start = n_vars + 1
    for line in lines[data_start:]:
        parts = line.strip().split()
        if len(parts) < 7 + n_vars:
            continue
        try:
            y, m, d = int(parts[1]), int(parts[2]), int(parts[3])
            record = {"date": f"{y:04d}-{m:02d}-{d:02d}"}
            for j, var in enumerate(var_names):
                record[var] = float(parts[7 + j])
            records.append(record)
        except (ValueError, IndexError):
            continue

    return records


def parse_modflow_listing(listing_file):
    """
    Extract volumetric water budget from MODFLOW listing file.
    Returns list of budget records by stress period.
    """
    if not os.path.isfile(listing_file):
        raise FileNotFoundError(f"Listing file not found: {listing_file}")

    budgets = []
    with open(listing_file) as f:
        content = f.read()

    # Find VOLUMETRIC BUDGET sections
    budget_pattern = r"VOLUMETRIC BUDGET FOR ENTIRE MODEL.*?(?=VOLUMETRIC BUDGET|$)"
    matches = re.findall(budget_pattern, content, re.DOTALL)

    for match in matches:
        budget = {}
        # Extract IN and OUT components
        for line in match.split("\n"):
            line = line.strip()
            # Pattern: COMPONENT = value
            m = re.match(r"(\w[\w\s]+?)\s*=\s*([\d.E+\-]+)", line)
            if m:
                name = m.group(1).strip()
                value = float(m.group(2))
                budget[name] = value
        if budget:
            budgets.append(budget)

    return budgets


def parse_sfr_gage(gage_file):
    """
    Parse SFR gage output file for streamflow.

    Format varies but typically:
        DATA (header lines)
        time  stage  flow  ...
    """
    if not os.path.isfile(gage_file):
        raise FileNotFoundError(f"Gage file not found: {gage_file}")

    records = []
    with open(gage_file) as f:
        lines = f.readlines()

    # Skip header lines
    data_start = 0
    for i, line in enumerate(lines):
        if line.strip() and line.strip()[0].isdigit():
            data_start = i
            break

    for line in lines[data_start:]:
        parts = line.strip().split()
        if len(parts) >= 3:
            try:
                record = {
                    "time_step": float(parts[0]),
                    "stage": float(parts[1]),
                    "flow_cfs": float(parts[2]),
                }
                if len(parts) >= 4:
                    record["flow_cms"] = float(parts[2]) * CFS_TO_CMS
                records.append(record)
            except ValueError:
                continue

    return records


# Control-file rules: the same code as tools/run_gsflow.py (kept in step).
def read_control(control_file):
    """GSFLOW/PRMS control file -> {name: [values as text]}, read like the engine
    (prms/sm_read_control_file.f90): a block starts at a line whose first four
    characters are '####', then the name, the number of values (>= 1), the type
    (1 integer, 2 real, 4 text); text values are one per line; numbers are read
    list-directed (separated by blanks or commas, may span lines, r*v = r copies of v).
    Raises ValueError for a malformed or incomplete block."""
    with open(control_file) as f:
        lines = [l.rstrip("\n") for l in f]
    params = {}
    i = 0
    while i < len(lines):
        if lines[i][:4] != "####":
            i += 1
            continue
        start = i + 1
        try:
            name = lines[i + 1].strip()
            n = int(lines[i + 2].replace(",", " ").split()[0])
            ptype = int(lines[i + 3].replace(",", " ").split()[0])
        except (IndexError, ValueError):
            raise ValueError(f"{control_file}: malformed block at line {start}")
        if not name or n < 1 or ptype not in (1, 2, 4):
            raise ValueError(f"{control_file}: malformed block '{name}' at line {start} "
                             f"(number of values {n}, type {ptype})")
        i += 4
        if ptype == 4:
            vals = [l.strip() for l in lines[i:i + n]]
            if len(vals) < n or any(v[:4] == "####" for v in vals):
                raise ValueError(f"{control_file}: block '{name}' has fewer than {n} text values")
            i += n
        else:
            vals = []
            while len(vals) < n:
                if i >= len(lines) or lines[i][:4] == "####":
                    raise ValueError(f"{control_file}: block '{name}' has fewer than {n} values")
                # list-directed read: '!' starts a comment
                for tok in lines[i].split("!", 1)[0].replace(",", " ").split():
                    if len(vals) >= n:
                        break  # the read is complete; the rest of the line is ignored
                    if "*" in tok:
                        rep, _, v = tok.partition("*")
                        try:
                            vals.extend([v] * min(int(rep), n - len(vals)))
                        except ValueError:
                            raise ValueError(f"{control_file}: bad value '{tok}' in block '{name}'")
                    else:
                        vals.append(tok)
                i += 1
            for v in vals[:n]:
                try:
                    int(v) if ptype == 1 else float(v.replace("d", "e").replace("D", "e"))
                except ValueError:
                    raise ValueError(f"{control_file}: bad value '{v}' in block '{name}'")
            vals = vals[:n]
        params[name] = vals
    return params


def model_kind(params):
    """Model dispatch as in gsflow/gsflow_prms.f90:
    'prms_only' (PRMS*, DAILY: full PRMS run, PRMS_only active),
    'prms_pre' (FROST, CLIMATE, WRITE_CLIMATE, POTET, TRANSPIRE, CONVERT: PRMS_only
               pre-process modes that return before the PRMS summary),
    'modsim_prms' (MODSIM-PRMS, MODSIM-PRMS-LOOSE: PRMS runs, PRMS_only off),
    'coupled' (GSFLOW*, MODSIM-GSFLOW), 'modflow' (MODFLOW*, MODSIM-MODFLOW, MODSIM)."""
    vals = params.get("model_mode") or ["GSFLOW5"]
    mode = vals[0]
    if mode[:4] == "    " or not mode.strip():
        mode = "GSFLOW5"
    up = mode.strip()
    if up[:4] in ("PRMS", "prms") or up[:5] == "DAILY":
        return "prms_only"
    if up[:6] in ("GSFLOW", "gsflow") or up[:13] == "MODSIM-GSFLOW":
        return "coupled"
    if up[:7] in ("MODFLOW", "modflow") or up[:14] == "MODSIM-MODFLOW":
        return "modflow"
    if up[:11] == "MODSIM-PRMS":
        return "modsim_prms"
    if up[:6] == "MODSIM":
        return "modflow"
    return "prms_pre"


def control_flag(params, name, default):
    """Integer control value; the engine default only when the entry is absent.
    A present but unreadable value is an error (never a silent default)."""
    vals = params.get(name)
    if not vals:
        return default
    try:
        return int(vals[0])
    except ValueError:
        raise ValueError(f"control parameter {name}: not an integer: {vals[0]!r}")


def enabled_outputs(params):
    """Output files this run writes, by the engine's switches and defaults
    (sm_read_control_file.f90, gsflow_prms.f90, gsflow_sum.f90):
    [(param, file name as in the control file or the engine default)]."""
    defaults = {"model_output_file": "prms.out", "csv_output_file": "prms_summary.csv",
                "gsflow_output_file": "gsflow.out", "stat_var_file": "statvar.out",
                "var_save_file": "prms_ic.out"}
    kind = model_kind(params)
    prms_runs = kind in ("prms_only", "modsim_prms", "coupled")
    names = []
    if kind == "coupled":
        names.append("gsflow_output_file")
        if control_flag(params, "gsf_rpt", 1) == 1:
            names.append("csv_output_file")
    if kind == "prms_only" and control_flag(params, "csvON_OFF", 0) > 0:
        names.append("csv_output_file")
    if kind == "prms_pre":
        # CLIMATE, TRANSPIRE and POTET call summary_output (statvar); the others write
        # no summary file this tool can check
        mode = (params.get("model_mode") or [""])[0].strip().upper()
        if (mode.startswith(("CLIMATE", "TRANSPIRE", "POTET"))
                and control_flag(params, "statsON_OFF", 0) == 1):
            names.append("stat_var_file")
    if prms_runs:
        if control_flag(params, "print_debug", 0) > -2:
            names.append("model_output_file")
        if control_flag(params, "statsON_OFF", 0) == 1:
            names.append("stat_var_file")
        if control_flag(params, "save_vars_to_file", 0) == 1:
            names.append("var_save_file")
    return [(n, (params.get(n) or [defaults[n]])[0]) for n in names]


def _enabled_output(control_file, run_dir=None):
    """(path, 'csv'|'statvar') of the time-series output this run writes (CSV first,
    else statvar), else (None, None). Relative paths are taken from run_dir (the
    folder GSFLOW ran in; default the control file's folder, as run_gsflow.py)."""
    params = read_control(control_file)
    base = os.path.abspath(run_dir or os.path.dirname(os.path.abspath(control_file)))
    outs = dict(enabled_outputs(params))
    for name, kind in (("csv_output_file", "csv"), ("stat_var_file", "statvar")):
        if name in outs:
            f = outs[name]
            return (f if os.path.isabs(f) else os.path.join(base, f)), kind
    return None, None


def convert_cfs_to_cms(records, var_name="basin_cfs"):
    """Convert streamflow from cfs to cms."""
    for rec in records:
        if var_name in rec:
            rec[f"{var_name}_cms"] = rec[var_name] * CFS_TO_CMS
    return records


def runoff_inches_to_cms(records, basin_area_km2, var_name="basin_stflow"):
    """
    Convert basin runoff from inches/day to m³/s.

    Formula: Q_cms = runoff_inches * 25.4 / 1000 * area_km2 * 1e6 / 86400
           = runoff_inches * area_km2 * 25.4 * 1000 / 86400
           = runoff_inches * area_km2 * 0.29398
    """
    factor = basin_area_km2 * 25.4 * 1000.0 / 86400.0
    for rec in records:
        if var_name in rec:
            rec[f"{var_name}_cms"] = rec[var_name] * factor
    return records


def write_csv(records, output_path, variables=None):
    """Write extracted records to CSV file."""
    if not records:
        print("WARNING: No records to write", file=sys.stderr)
        return

    # Determine columns
    if variables:
        columns = ["date"] + [v for v in variables if any(v in r for r in records)]
    else:
        columns = sorted(set().union(*(r.keys() for r in records)))
        if "date" in columns:
            columns.remove("date")
            columns = ["date"] + columns

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    print(f"  Wrote {len(records)} records to {output_path}")
    print(f"  Columns: {', '.join(columns)}")


# Date text as written by GSFLOW: 2.4.0 gsflow.csv uses MM/DD/YYYY; the statvar
# and Year/Month/Day paths of this tool write YYYY-MM-DD
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")


def parse_date(text):
    """datetime for a date in one of DATE_FORMATS, else None."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def validate_outputs(output_path, records):
    """Validate the extracted data."""
    errors = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return False

    if len(records) == 0:
        errors.append("No records extracted")
        return False

    # Check for constant values (sign of parsing error)
    if "basin_cfs" in records[0]:
        vals = [r.get("basin_cfs", 0) for r in records]
        if len(set(vals)) == 1:
            errors.append("basin_cfs is constant — possible parsing error")

    # Check for negative streamflow
    for var in ["basin_cfs", "basin_stflow"]:
        if var in records[0]:
            neg_count = sum(1 for r in records if r.get(var, 0) < 0)
            if neg_count > 0:
                errors.append(f"{var} has {neg_count} negative values")

    # Check date continuity
    if "date" in records[0]:
        dates = [r["date"] for r in records]
        if len(dates) > 1:
            d0, d1 = parse_date(dates[0]), parse_date(dates[-1])
            if d0 is None or d1 is None:
                errors.append(f"Date format not recognised ({dates[0]!r}); date check skipped")
            else:
                expected_days = (d1 - d0).days + 1
                if len(records) != expected_days:
                    errors.append(f"Date gaps: expected {expected_days} days, got {len(records)}")

    if errors:
        for e in errors:
            print(f"WARNING: {e}", file=sys.stderr)
        return False

    print("  Output validation PASSED")
    return True


def main():
    parser = argparse.ArgumentParser(description="Parse GSFLOW output to CSV")
    parser.add_argument("--output-dir", help="Model output directory")
    parser.add_argument("--control-file", help="Control file (to find output paths)")
    parser.add_argument("--csv-file", help="Direct path to PRMS CSV output")
    parser.add_argument("--statvar-file", help="Direct path to statvar output")
    parser.add_argument("--csv-out", required=True, help="Output CSV file path")
    parser.add_argument("--working-dir", default=None,
                        help="Folder GSFLOW ran in (relative paths of the control file are taken "
                             "from it; default: the control file's folder, as run_gsflow.py)")
    parser.add_argument("--variables", help="Comma-separated variable names")
    parser.add_argument("--basin-area-km2", type=float, help="Basin area for runoff→Q conversion")
    args = parser.parse_args()

    variables = args.variables.split(",") if args.variables else None

    print("=" * 60)
    print("GSFLOW Output Parser")
    print("=" * 60)

    # ── Step 1: Validate ──
    print(f"\n[1/3] Validating inputs")
    source = args.csv_file or args.statvar_file or args.output_dir
    if not source:
        print("ERROR: Must specify --csv-file, --statvar-file, or --output-dir", file=sys.stderr)
        sys.exit(1)

    # ── Step 2: Parse ──
    print(f"\n[2/3] Parsing output")
    records = []

    if args.csv_file:
        print(f"  Parsing CSV: {args.csv_file}")
        records = parse_csv_output(args.csv_file, variables)
    elif args.statvar_file:
        print(f"  Parsing statvar: {args.statvar_file}")
        records = parse_statvar_output(args.statvar_file, variables)
    elif args.output_dir:
        # Which file: with --control-file, the CSV or statvar file the control file
        # switches on; otherwise the only CSV, else the only statvar file in the
        # folder. Several candidates -> error (no guessing).
        if args.control_file:
            try:
                path, kind = _enabled_output(args.control_file, args.working_dir)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)
            if path is None:
                print("ERROR: the control file switches on neither a CSV summary nor a statvar "
                      "file", file=sys.stderr)
                sys.exit(1)
            if not os.path.isfile(path):
                print(f"ERROR: {kind} output named in the control file not found: {path}",
                      file=sys.stderr)
                sys.exit(1)
            print(f"  Using {kind} output from the control file: {path}")
            records = (parse_csv_output(path, variables) if kind == "csv"
                       else parse_statvar_output(path, variables))
        else:
            csv_files = sorted(f for f in os.listdir(args.output_dir) if f.endswith(".csv"))
            stat_files = sorted(f for f in os.listdir(args.output_dir) if "statvar" in f.lower())
            if len(csv_files) > 1 or (not csv_files and len(stat_files) > 1):
                print(f"ERROR: several candidate files in {args.output_dir}: "
                      f"{csv_files or stat_files}; give --csv-file, --statvar-file or "
                      "--control-file", file=sys.stderr)
                sys.exit(1)
            if csv_files:
                csv_path = os.path.join(args.output_dir, csv_files[0])
                print(f"  Found CSV output: {csv_path}")
                records = parse_csv_output(csv_path, variables)
            elif stat_files:
                stat_path = os.path.join(args.output_dir, stat_files[0])
                print(f"  Found statvar output: {stat_path}")
                records = parse_statvar_output(stat_path, variables)

    if not records:
        print("ERROR: No records extracted from output files", file=sys.stderr)
        sys.exit(1)
    if variables:
        missing = [v for v in variables if not any(v in r for r in records)]
        if missing:
            print(f"ERROR: variable(s) {missing} not in the output", file=sys.stderr)
            sys.exit(1)

    print(f"  Extracted {len(records)} records")

    # Convert units if needed
    if args.basin_area_km2:
        records = runoff_inches_to_cms(records, args.basin_area_km2)
    records = convert_cfs_to_cms(records)

    # ── Step 3: Write CSV ──
    print(f"\n[3/3] Writing output")
    write_csv(records, args.csv_out, variables)

    # ── Step 4: Validate ── (date gaps, constant or negative flow are advisory
    # warnings; a missing output file is a failure)
    validate_outputs(args.csv_out, records)
    if not os.path.isfile(args.csv_out):
        print(f"ERROR: output CSV not written: {args.csv_out}", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone! Extracted time series → {args.csv_out}")


if __name__ == "__main__":
    main()
