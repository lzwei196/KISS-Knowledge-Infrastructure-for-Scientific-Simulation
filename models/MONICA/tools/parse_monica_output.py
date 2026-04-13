#!/usr/bin/env python3
"""
parse_monica_output.py — Parse MONICA output CSV into clean timeseries and metrics

Handles the multi-header-row MONICA output format and extracts:
  - Clean daily/monthly/yearly timeseries CSV
  - Summary statistics (yield, total ET, N leaching, etc.)
  - Domain-appropriate metrics vs. observed data (RMSE, R², PBIAS, d-index)

Usage:
    python parse_monica_output.py --input out.csv --output-dir ./parsed/

    python parse_monica_output.py --input out.csv --output-dir ./parsed/ \
        --observed obs_yield.csv --obs-col Yield_kgha --sim-col Yield \
        --metric rmse r2 pbias
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    n = len(obs)
    if n == 0:
        return float("nan")
    return math.sqrt(sum((o - s) ** 2 for o, s in zip(obs, sim)) / n)


def compute_r2(obs, sim):
    """Coefficient of determination (R²)."""
    n = len(obs)
    if n < 2:
        return float("nan")
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs)
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def compute_pbias(obs, sim):
    """Percent bias (%)."""
    sum_obs = sum(obs)
    if sum_obs == 0:
        return float("nan")
    return 100.0 * sum(s - o for o, s in zip(obs, sim)) / sum_obs


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    n = len(obs)
    if n < 2:
        return float("nan")
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs)
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def compute_d_index(obs, sim):
    """Willmott's index of agreement (d)."""
    n = len(obs)
    if n == 0:
        return float("nan")
    mean_o = sum(obs) / n
    num = sum((o - s) ** 2 for o, s in zip(obs, sim))
    den = sum((abs(s - mean_o) + abs(o - mean_o)) ** 2 for o, s in zip(obs, sim))
    if den == 0:
        return float("nan")
    return 1.0 - num / den


METRIC_FUNCS = {
    "rmse": compute_rmse,
    "r2": compute_r2,
    "pbias": compute_pbias,
    "nse": compute_nse,
    "d": compute_d_index,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(parsed_data, output_dir):
    """Validate parsed output data."""
    warnings = []
    if not parsed_data:
        warnings.append("No data rows parsed from output file")
        return warnings

    n_rows = len(parsed_data)
    warnings.append(f"Parsed {n_rows} data rows")

    # Check for common issues
    if "Yield" in parsed_data[0]:
        yields = [float(r["Yield"]) for r in parsed_data
                  if r.get("Yield") and r["Yield"] != ""]
        if yields:
            max_yield = max(yields)
            if max_yield > 50000:
                warnings.append(f"Max yield = {max_yield:.0f} kg ha⁻¹ — suspiciously high, "
                                "check radiation units")
            elif max_yield == 0:
                warnings.append("All yields are 0 — check if crop rotation was configured")

    return warnings


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_monica_output(input_path):
    """
    Parse MONICA's multi-header CSV output.

    MONICA outputs have 3-4 header rows:
      Row 1: column names (e.g., Date, Crop, Yield, Mois/1)
      Row 2: units (e.g., [mm], [kg ha-1])
      Row 3: aggregation metadata or JSON refs
      Row 4+: data
    """
    with open(input_path, "r", newline="") as f:
        lines = f.readlines()

    if len(lines) < 3:
        return [], [], []

    # Detect separator
    sep = ","
    if ";" in lines[0]:
        sep = ";"
    elif "\t" in lines[0]:
        sep = "\t"

    # Parse headers
    header_names = [h.strip().strip('"') for h in lines[0].strip().split(sep)]
    header_units = [u.strip().strip('"') for u in lines[1].strip().split(sep)]

    # Find where data starts (skip rows starting with "m:" or "j:" or containing metadata)
    data_start = 2
    for i in range(2, min(6, len(lines))):
        first_cell = lines[i].strip().split(sep)[0].strip().strip('"')
        if first_cell.startswith(("m:", "j:", "c:")):
            data_start = i + 1
        else:
            break

    # Parse data rows
    data = []
    for line in lines[data_start:]:
        vals = line.strip().split(sep)
        if len(vals) != len(header_names):
            continue
        row = {}
        for name, val in zip(header_names, vals):
            row[name] = val.strip().strip('"')
        data.append(row)

    return header_names, header_units, data


def extract_timeseries(data, columns, date_col="Date"):
    """Extract specific columns as a clean timeseries."""
    ts = []
    for row in data:
        entry = {}
        if date_col in row:
            entry["date"] = row[date_col]
        for col in columns:
            if col in row and row[col] != "":
                try:
                    entry[col] = float(row[col])
                except ValueError:
                    entry[col] = row[col]
        ts.append(entry)
    return ts


def compute_summary(data, header_names):
    """Compute summary statistics from parsed data."""
    summary = {}

    # Yield: take max non-empty value
    if "Yield" in header_names:
        yields = [float(r["Yield"]) for r in data
                  if r.get("Yield", "") not in ("", "0")]
        if yields:
            summary["max_yield_kg_ha"] = round(max(yields), 1)
            summary["n_harvests"] = len(yields)

    # Cumulative variables
    cum_vars = {
        "Act_ET": "total_et_mm",
        "Precip": "total_precip_mm",
        "NLeach": "total_n_leach_kg_ha",
        "Denit": "total_denit_kg_ha",
        "N2O": "total_n2o_kg_ha",
        "Irrig": "total_irrig_mm",
    }
    for var, key in cum_vars.items():
        if var in header_names:
            vals = [float(r[var]) for r in data if r.get(var, "") not in ("", )]
            if vals:
                summary[key] = round(sum(vals), 2)

    # Mean soil moisture (top layer)
    if "Mois/1" in header_names:
        mois = [float(r["Mois/1"]) for r in data if r.get("Mois/1", "") != ""]
        if mois:
            summary["mean_mois_layer1_m3m3"] = round(sum(mois) / len(mois), 4)

    return summary


def compare_with_observed(data, args):
    """Compare simulated vs observed data and compute metrics."""
    if not args.observed or not args.sim_col:
        return {}

    # Read observed data
    obs_data = {}
    with open(args.observed, "r", newline="") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            date_key = rec.get(args.obs_date_col or "date", "").strip()
            val = rec.get(args.obs_col, "").strip()
            if date_key and val:
                try:
                    obs_data[date_key] = float(val)
                except ValueError:
                    pass

    # Match dates
    obs_vals = []
    sim_vals = []
    for row in data:
        date_key = row.get("Date", "").strip()
        if date_key in obs_data and row.get(args.sim_col, "") != "":
            try:
                sim_val = float(row[args.sim_col])
                obs_vals.append(obs_data[date_key])
                sim_vals.append(sim_val)
            except ValueError:
                pass

    if not obs_vals:
        return {"error": "No matching date pairs found between observed and simulated"}

    metrics = {"n_pairs": len(obs_vals)}
    requested = args.metric or ["rmse", "r2", "pbias"]
    for m in requested:
        if m in METRIC_FUNCS:
            metrics[m] = round(METRIC_FUNCS[m](obs_vals, sim_vals), 4)

    return metrics


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_clean_csv(timeseries, output_path, sep=","):
    """Write clean CSV from timeseries data."""
    if not timeseries:
        return
    keys = list(timeseries[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, delimiter=sep)
        writer.writeheader()
        writer.writerows(timeseries)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse MONICA output CSV and compute metrics")
    parser.add_argument("--input", required=True, help="MONICA output CSV path")
    parser.add_argument("--output-dir", required=True, help="Output directory for parsed files")
    parser.add_argument("--columns", nargs="*",
                        help="Columns to extract (default: all)")
    parser.add_argument("--observed", help="Observed data CSV for comparison")
    parser.add_argument("--obs-col", help="Observed value column name")
    parser.add_argument("--obs-date-col", default="date", help="Observed date column")
    parser.add_argument("--sim-col", help="Simulated column to compare")
    parser.add_argument("--metric", nargs="*", choices=list(METRIC_FUNCS.keys()),
                        help="Metrics to compute")

    args = parser.parse_args()
    validate_inputs(args)

    os.makedirs(args.output_dir, exist_ok=True)

    # Parse
    header_names, header_units, data = parse_monica_output(args.input)
    warnings = validate_outputs(data, args.output_dir)

    # Extract columns
    cols = args.columns or [h for h in header_names if h not in ("Date", "Crop")]
    ts = extract_timeseries(data, cols)

    # Write clean CSV
    clean_csv = os.path.join(args.output_dir, "timeseries.csv")
    write_clean_csv(ts, clean_csv)

    # Compute summary
    summary = compute_summary(data, header_names)

    # Compare with observed
    metrics = {}
    if args.observed:
        metrics = compare_with_observed(data, args)

    # Write summary
    result = {
        "status": "success",
        "input": args.input,
        "n_rows": len(data),
        "columns": header_names,
        "units": header_units,
        "clean_csv": clean_csv,
        "summary": summary,
        "metrics": metrics,
        "warnings": warnings,
    }

    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
