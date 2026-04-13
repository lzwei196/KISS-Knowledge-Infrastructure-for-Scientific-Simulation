#!/usr/bin/env python3
"""
parse_output_quincy.py
Parse QUINCY model output files into timeseries CSV.

Handles QUINCY output from:
  1. Analytic model (CSV from run_quincy.py)
  2. Full QUINCY model (NetCDF output)
  3. Custom text output

Output variables: GPP, NEE, RECO, LE, H, LAI, RA, RH timeseries.

Follows validate -> process -> validate pattern.

Usage:
    # Parse analytic model output
    python parse_output_quincy.py --input quincy_output.csv --format csv \\
        --output parsed_quincy.csv

    # Parse with obs comparison and metrics
    python parse_output_quincy.py --input quincy_output.csv --format csv \\
        --output parsed_quincy.csv --compute-metrics

    # Extract specific variables
    python parse_output_quincy.py --input quincy_output.csv --format csv \\
        --output gpp_only.csv --variables GPP NEE

    # Compute seasonal cycle
    python parse_output_quincy.py --input quincy_output.csv --format csv \\
        --output seasonal.csv --aggregate seasonal

    # Summary statistics
    python parse_output_quincy.py --input quincy_output.csv --format csv \\
        --summary summary.json
"""

import os
import sys
import csv
import json
import argparse
import numpy as np
from typing import Dict, List, Optional


# ============================================================================
# Variable metadata
# ============================================================================

QUINCY_OUTPUT_VARS = {
    "GPP":  {"unit": "umol/m2/s", "description": "Gross primary production",
             "valid_range": (0.0, 30.0)},
    "NEE":  {"unit": "umol/m2/s", "description": "Net ecosystem exchange",
             "valid_range": (-15.0, 15.0)},
    "RECO": {"unit": "umol/m2/s", "description": "Ecosystem respiration",
             "valid_range": (0.0, 20.0)},
    "RA":   {"unit": "umol/m2/s", "description": "Autotrophic respiration",
             "valid_range": (0.0, 15.0)},
    "RH":   {"unit": "umol/m2/s", "description": "Heterotrophic respiration",
             "valid_range": (0.0, 10.0)},
    "LAI":  {"unit": "m2/m2", "description": "Leaf area index",
             "valid_range": (0.0, 12.0)},
    "LE":   {"unit": "W/m2", "description": "Latent heat flux",
             "valid_range": (0.0, 300.0)},
    "H":    {"unit": "W/m2", "description": "Sensible heat flux",
             "valid_range": (-50.0, 400.0)},
}

OBS_VARS = {
    "GPP_OBS":  {"unit": "umol/m2/s", "description": "Observed GPP"},
    "NEE_OBS":  {"unit": "umol/m2/s", "description": "Observed NEE"},
    "RECO_OBS": {"unit": "umol/m2/s", "description": "Observed Reco"},
    "LE_OBS":   {"unit": "W/m2", "description": "Observed LE"},
    "H_OBS":    {"unit": "W/m2", "description": "Observed H"},
}


# ============================================================================
# Validation: Stage 1 (inputs)
# ============================================================================

def validate_input_file(filepath, format_type):
    """
    Validate input file before parsing.

    Parameters
    ----------
    filepath : str
        Path to input file
    format_type : str
        Expected format ('csv', 'netcdf', 'text')

    Returns
    -------
    list of str
        Error messages
    """
    errors = []

    if not os.path.isfile(filepath):
        errors.append(f"File not found: {filepath}")
        return errors

    size = os.path.getsize(filepath)
    if size == 0:
        errors.append(f"File is empty: {filepath}")
        return errors

    print(f"Input file: {filepath} ({size} bytes, format={format_type})")

    # Check CSV has header with expected columns
    if format_type == "csv":
        with open(filepath, 'r') as f:
            header = f.readline().strip()
        has_model = any(v in header for v in QUINCY_OUTPUT_VARS)
        if not has_model:
            errors.append(
                f"CSV file missing model output columns "
                f"(expected at least one of: {list(QUINCY_OUTPUT_VARS.keys())}). "
                f"Header: {header[:100]}...")

    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)

    return errors


# ============================================================================
# Validation: Stage 3 (outputs)
# ============================================================================

def validate_parsed_data(data, variable_names):
    """
    Validate parsed output data for reasonableness.

    Parameters
    ----------
    data : dict
        Variable name -> numpy array
    variable_names : list of str
        Variables that were parsed

    Returns
    -------
    list of str
        Warning messages
    """
    warnings = []

    if not data:
        warnings.append("No data parsed")
        return warnings

    n_rows = 0
    for var in variable_names:
        if var in data and isinstance(data[var], np.ndarray):
            n_rows = max(n_rows, len(data[var]))

    if n_rows == 0:
        warnings.append("No data rows parsed")
        return warnings

    print(f"Parsed: {n_rows} rows, {len(variable_names)} variables")

    for var in variable_names:
        if var not in data:
            continue

        values = data[var]
        if not isinstance(values, np.ndarray):
            continue

        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            warnings.append(f"{var}: all values are NaN")
            continue

        meta = QUINCY_OUTPUT_VARS.get(var, {})
        vrange = meta.get("valid_range")
        if vrange:
            lo, hi = vrange
            vmin, vmax = float(np.min(valid)), float(np.max(valid))
            if vmin < lo * 2 and lo != 0:
                warnings.append(
                    f"{var}: min={vmin:.3f} below expected range "
                    f"[{lo}, {hi}] {meta.get('unit', '')}")
            if vmax > hi * 1.5:
                warnings.append(
                    f"{var}: max={vmax:.3f} above expected range "
                    f"[{lo}, {hi}] {meta.get('unit', '')}")

        # Check for constant values
        if len(valid) > 10 and np.std(valid) < 1e-10:
            warnings.append(
                f"{var}: all values constant ({valid[0]:.4g}) -- "
                f"possible model failure")

    for w in warnings:
        print(f"OUTPUT WARNING: {w}", file=sys.stderr)

    if not warnings:
        print(f"Output validated: {n_rows} rows, all values reasonable")

    return warnings


# ============================================================================
# CSV parser
# ============================================================================

def parse_csv_output(filepath, variables=None):
    """
    Parse QUINCY CSV output file.

    Parameters
    ----------
    filepath : str
        Path to CSV file
    variables : list of str or None
        Specific variables to extract (None = all)

    Returns
    -------
    dict
        Variable name -> numpy array, plus 'TIMESTAMP' list
    """
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return {}

    # Skip units row if present
    first_row = rows[0]
    if any(v in str(first_row) for v in ["umol/m2/s", "W/m2", "m2/m2"]):
        rows = rows[1:]

    n = len(rows)
    available_cols = set(rows[0].keys())

    # Determine which variables to extract
    all_vars = list(QUINCY_OUTPUT_VARS.keys()) + list(OBS_VARS.keys())
    if variables:
        target_vars = [v for v in variables if v in available_cols]
    else:
        target_vars = [v for v in all_vars if v in available_cols]

    data = {}

    # Timestamps
    if "TIMESTAMP" in available_cols:
        data["TIMESTAMP"] = [row["TIMESTAMP"] for row in rows]
    else:
        data["TIMESTAMP"] = [str(i) for i in range(n)]

    # Numeric columns
    for var in target_vars:
        vals = []
        for row in rows:
            try:
                v = float(row.get(var, "NaN"))
                vals.append(v)
            except (ValueError, TypeError):
                vals.append(np.nan)
        data[var] = np.array(vals)

    # Also extract YEAR and MONTH if available
    for aux in ["YEAR", "MONTH"]:
        if aux in available_cols:
            vals = []
            for row in rows:
                try:
                    vals.append(int(float(row[aux])))
                except (ValueError, TypeError):
                    vals.append(0)
            data[aux] = np.array(vals, dtype=int)

    return data


# ============================================================================
# NetCDF parser (for full QUINCY model)
# ============================================================================

def parse_netcdf_output(filepath, variables=None):
    """
    Parse QUINCY NetCDF output file.

    Parameters
    ----------
    filepath : str
        Path to NetCDF file
    variables : list of str or None
        Variables to extract

    Returns
    -------
    dict
        Variable name -> numpy array
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required for NetCDF parsing. "
              "Install: pip install netCDF4", file=sys.stderr)
        sys.exit(1)

    ds = nc.Dataset(filepath, 'r')

    # Map QUINCY NetCDF variable names to standard names
    nc_var_map = {
        "gpp": "GPP",
        "nee": "NEE",
        "reco": "RECO",
        "ra": "RA",
        "rh": "RH",
        "lai": "LAI",
        "le": "LE",
        "latent_heat": "LE",
        "h": "H",
        "sensible_heat": "H",
        "resp_eco": "RECO",
        "resp_auto": "RA",
        "resp_hetero": "RH",
    }

    data = {}

    # Time variable
    if "time" in ds.variables:
        time_var = ds.variables["time"]
        try:
            times = nc.num2date(time_var[:], time_var.units)
            data["TIMESTAMP"] = [str(t) for t in times]
        except Exception:
            data["TIMESTAMP"] = [str(i) for i in range(len(time_var[:]))]
    else:
        data["TIMESTAMP"] = []

    # Extract variables
    for nc_name, std_name in nc_var_map.items():
        if variables and std_name not in variables:
            continue
        if nc_name in ds.variables:
            vals = ds.variables[nc_name][:]
            if hasattr(vals, 'filled'):
                vals = vals.filled(np.nan)
            data[std_name] = np.array(vals).flatten()

    ds.close()
    return data


# ============================================================================
# Aggregation
# ============================================================================

def aggregate_seasonal(data):
    """
    Compute mean seasonal cycle (monthly climatology).

    Parameters
    ----------
    data : dict
        Parsed output data with MONTH column

    Returns
    -------
    dict
        Seasonal means per variable, indexed by month (1-12)
    """
    if "MONTH" not in data:
        print("WARNING: No MONTH column, cannot compute seasonal cycle",
              file=sys.stderr)
        return {}

    months = data["MONTH"]
    seasonal = {"MONTH": np.arange(1, 13)}

    for var in QUINCY_OUTPUT_VARS:
        if var not in data:
            continue
        values = data[var]
        monthly_means = []
        for m in range(1, 13):
            mask = months == m
            vals = values[mask]
            valid = vals[~np.isnan(vals)]
            monthly_means.append(float(np.mean(valid)) if len(valid) > 0 else np.nan)
        seasonal[var] = np.array(monthly_means)

    # Also aggregate obs if present
    for var in OBS_VARS:
        if var not in data:
            continue
        values = data[var]
        monthly_means = []
        for m in range(1, 13):
            mask = months == m
            vals = values[mask]
            valid = vals[~np.isnan(vals)]
            monthly_means.append(float(np.mean(valid)) if len(valid) > 0 else np.nan)
        seasonal[var] = np.array(monthly_means)

    return seasonal


def aggregate_annual(data):
    """
    Compute annual means.

    Parameters
    ----------
    data : dict
        Parsed output data with YEAR column

    Returns
    -------
    dict
        Annual means per variable
    """
    if "YEAR" not in data:
        print("WARNING: No YEAR column, cannot compute annual means",
              file=sys.stderr)
        return {}

    years = data["YEAR"]
    unique_years = sorted(set(years))
    annual = {"YEAR": np.array(unique_years)}

    for var in list(QUINCY_OUTPUT_VARS.keys()) + list(OBS_VARS.keys()):
        if var not in data:
            continue
        values = data[var]
        yearly_means = []
        for yr in unique_years:
            mask = years == yr
            vals = values[mask]
            valid = vals[~np.isnan(vals)]
            yearly_means.append(float(np.mean(valid)) if len(valid) > 0 else np.nan)
        annual[var] = np.array(yearly_means)

    return annual


# ============================================================================
# Metrics
# ============================================================================

def compute_metrics(data):
    """
    Compute validation metrics (R, RMSE, bias, NSE) for all obs-model pairs.

    Parameters
    ----------
    data : dict
        Data with both model and observation columns

    Returns
    -------
    dict
        Metrics per variable
    """
    metrics = {}

    obs_mod_pairs = [
        ("GPP_OBS", "GPP"),
        ("NEE_OBS", "NEE"),
        ("RECO_OBS", "RECO"),
        ("LE_OBS", "LE"),
        ("H_OBS", "H"),
    ]

    for obs_var, mod_var in obs_mod_pairs:
        if obs_var not in data or mod_var not in data:
            continue

        obs = data[obs_var]
        mod = data[mod_var]
        mask = ~np.isnan(obs) & ~np.isnan(mod)

        if mask.sum() < 3:
            continue

        o = obs[mask]
        m = mod[mask]

        r = float(np.corrcoef(o, m)[0, 1]) if len(o) > 2 else np.nan
        rmse = float(np.sqrt(np.mean((m - o) ** 2)))
        bias = float(np.mean(m - o))
        ss_res = float(np.sum((m - o) ** 2))
        ss_tot = float(np.sum((o - np.mean(o)) ** 2))
        nse = float(1 - ss_res / ss_tot) if ss_tot > 0 else np.nan

        metrics[mod_var] = {
            "R": round(r, 4),
            "RMSE": round(rmse, 4),
            "bias": round(bias, 4),
            "NSE": round(nse, 4),
            "n": int(mask.sum()),
            "obs_mean": round(float(np.mean(o)), 4),
            "mod_mean": round(float(np.mean(m)), 4),
        }

        print(f"  {mod_var}: R={r:.3f}, RMSE={rmse:.3f}, "
              f"bias={bias:.3f}, NSE={nse:.3f} (n={mask.sum()})")

    return metrics


# ============================================================================
# Summary statistics
# ============================================================================

def compute_summary(data):
    """
    Compute summary statistics for all variables.

    Parameters
    ----------
    data : dict
        Parsed data

    Returns
    -------
    dict
        Summary statistics per variable
    """
    summary = {}

    for var in list(QUINCY_OUTPUT_VARS.keys()) + list(OBS_VARS.keys()):
        if var not in data:
            continue
        values = data[var]
        if not isinstance(values, np.ndarray):
            continue

        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            continue

        summary[var] = {
            "n_total": int(len(values)),
            "n_valid": int(len(valid)),
            "pct_valid": round(100 * len(valid) / len(values), 1),
            "min": round(float(np.min(valid)), 4),
            "max": round(float(np.max(valid)), 4),
            "mean": round(float(np.mean(valid)), 4),
            "std": round(float(np.std(valid)), 4),
            "median": round(float(np.median(valid)), 4),
            "unit": QUINCY_OUTPUT_VARS.get(var, OBS_VARS.get(var, {})).get("unit", ""),
        }

    return summary


# ============================================================================
# Export
# ============================================================================

def export_csv(data, output_path, variables=None):
    """
    Export parsed data to CSV.

    Parameters
    ----------
    data : dict
        Data dictionary
    output_path : str
        Output file path
    variables : list of str or None
        Variables to export (None = all)
    """
    timestamps = data.get("TIMESTAMP", [])
    n = len(timestamps)

    if variables:
        write_vars = [v for v in variables if v in data]
    else:
        write_vars = [v for v in data
                      if v not in ("TIMESTAMP", "YEAR", "MONTH")
                      and isinstance(data.get(v), np.ndarray)]

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        header = ["TIMESTAMP"] + write_vars
        writer.writerow(header)

        for i in range(n):
            row = [timestamps[i] if i < len(timestamps) else str(i)]
            for var in write_vars:
                arr = data[var]
                if i < len(arr):
                    val = arr[i]
                    row.append(f"{val:.4f}" if not np.isnan(val) else "NaN")
                else:
                    row.append("NaN")
            writer.writerow(row)

    print(f"Exported: {output_path} ({n} rows, {len(write_vars)} variables)")


# ============================================================================
# Full parsing pipeline
# ============================================================================

def parse_pipeline(input_path, output_path, format_type="csv",
                   variables=None, aggregate=None,
                   do_metrics=False, summary_path=None):
    """
    Full parsing pipeline: validate -> parse -> validate -> export.

    Parameters
    ----------
    input_path : str
        Input file path
    output_path : str
        Output CSV path
    format_type : str
        'csv', 'netcdf', or 'auto'
    variables : list of str or None
        Variables to extract
    aggregate : str or None
        'seasonal', 'annual', or None
    do_metrics : bool
        Compute validation metrics
    summary_path : str or None
        Path to write summary JSON

    Returns
    -------
    dict
        Pipeline results
    """
    # Auto-detect format
    if format_type == "auto":
        if input_path.endswith(".nc") or input_path.endswith(".nc4"):
            format_type = "netcdf"
        else:
            format_type = "csv"

    # Stage 1: Validate inputs
    print("Stage 1: Validating input file...")
    errors = validate_input_file(input_path, format_type)
    if errors:
        return {"status": "error", "errors": errors}

    # Stage 2: Parse
    print("Stage 2: Parsing output file...")
    if format_type == "csv":
        data = parse_csv_output(input_path, variables)
    elif format_type == "netcdf":
        data = parse_netcdf_output(input_path, variables)
    else:
        return {"status": "error", "message": f"Unknown format: {format_type}"}

    if not data:
        return {"status": "error", "message": "No data parsed"}

    # Aggregate if requested
    if aggregate == "seasonal":
        print("  Computing seasonal cycle...")
        data = aggregate_seasonal(data)
    elif aggregate == "annual":
        print("  Computing annual means...")
        data = aggregate_annual(data)

    # Stage 3: Validate outputs
    print("Stage 3: Validating parsed data...")
    parsed_vars = [v for v in data
                   if v in QUINCY_OUTPUT_VARS and isinstance(data.get(v), np.ndarray)]
    warnings = validate_parsed_data(data, parsed_vars)

    # Metrics
    metrics = {}
    if do_metrics:
        print("Computing validation metrics...")
        metrics = compute_metrics(data)

    # Summary
    summary = compute_summary(data)
    if summary_path:
        with open(summary_path, 'w') as f:
            json.dump({"summary": summary, "metrics": metrics}, f, indent=2)
        print(f"Summary written to {summary_path}")

    # Export
    print("Stage 4: Exporting...")
    export_csv(data, output_path, variables)

    result = {
        "status": "success" if not warnings else "completed_with_warnings",
        "input_file": input_path,
        "output_file": output_path,
        "format": format_type,
        "n_timesteps": len(data.get("TIMESTAMP",
                                     next((v for v in data.values()
                                           if isinstance(v, np.ndarray)), []))),
        "variables_parsed": parsed_vars,
        "warnings": warnings,
        "metrics": metrics,
        "summary": summary,
    }

    return result


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse QUINCY model output into timeseries CSV. "
                    "Handles CSV and NetCDF formats with validation."
    )
    parser.add_argument("--input", required=True,
                        help="Input file (CSV or NetCDF)")
    parser.add_argument("--format", choices=["csv", "netcdf", "auto"],
                        default="auto",
                        help="Input format (default: auto-detect)")
    parser.add_argument("--output", required=True,
                        help="Output CSV file")
    parser.add_argument("--variables", nargs="+", default=None,
                        help="Variables to extract (e.g., GPP NEE RECO)")
    parser.add_argument("--aggregate", choices=["seasonal", "annual"],
                        default=None,
                        help="Temporal aggregation")
    parser.add_argument("--compute-metrics", action="store_true",
                        help="Compute validation metrics against observations")
    parser.add_argument("--summary", default=None,
                        help="Write summary statistics to JSON file")
    args = parser.parse_args()

    result = parse_pipeline(
        args.input, args.output,
        format_type=args.format,
        variables=args.variables,
        aggregate=args.aggregate,
        do_metrics=args.compute_metrics,
        summary_path=args.summary,
    )

    print(json.dumps(result, indent=2, default=str))

    if result.get("status") == "error":
        sys.exit(1)
