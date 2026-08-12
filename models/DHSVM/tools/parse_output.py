#!/usr/bin/env python3
"""
parse_output.py — Parse DHSVM output files to CSV and compute metrics.

Extracts data from Aggregated.Values, Stream.Flow, Mass.Balance, and
pixel time series files. Computes hydrology metrics (NSE, KGE, PBIAS)
when observed data is provided.

Usage:
  python parse_output.py --aggregated output/Aggregated.Values \\
      --output results.csv

  python parse_output.py --streamflow output/Stream.Flow \\
      --observed obs_Q.csv --metrics nse,kge,pbias \\
      --output validation.json

  python parse_output.py --mass-balance output/Mass.Final.Balance \\
      --output balance.json
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# DHSVM date parsing
# --------------------------------------------------------------------------- #

def parse_dhsvm_date(datestr):
    """Parse DHSVM date formats.

    Handles: MM/DD/YYYY-HH:MM:SS, MM/DD/YYYY-HH, MM.DD.YYYY-HH:MM:SS
    """
    datestr = datestr.strip()
    # Replace dots with slashes for Stream.Flow format
    datestr = datestr.replace(".", "/", 2)

    for fmt in ["%m/%d/%Y-%H:%M:%S", "%m/%d/%Y-%H", "%m/%d/%Y-%H:%M"]:
        try:
            return datetime.strptime(datestr, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse DHSVM date: {datestr}")


# --------------------------------------------------------------------------- #
# Output parsers
# --------------------------------------------------------------------------- #

def parse_aggregated(filepath):
    """Parse DHSVM Aggregated.Values file.

    Returns list of dicts with datetime + all variable columns.
    """
    records = []

    with open(filepath, "r") as f:
        lines = f.readlines()

    if not lines:
        return {"status": "error", "errors": ["Empty file"]}

    # First line is header (comma or whitespace separated)
    header_line = lines[0].strip()
    if "," in header_line:
        headers = [h.strip() for h in header_line.split(",")]
    else:
        headers = header_line.split()

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        else:
            parts = line.split()

        if len(parts) < 2:
            continue

        try:
            dt = parse_dhsvm_date(parts[0])
        except ValueError:
            continue

        record = {"datetime": dt.strftime("%Y-%m-%d %H:%M:%S")}
        for i, val in enumerate(parts[1:], 1):
            col_name = headers[i] if i < len(headers) else f"col_{i}"
            try:
                record[col_name] = float(val)
            except ValueError:
                record[col_name] = val
        records.append(record)

    return records


def parse_streamflow(filepath):
    """Parse DHSVM Stream.Flow file.

    Returns list of dicts with datetime, segment_id, flow, name.
    """
    records = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if len(parts) < 3:
                continue

            try:
                dt = parse_dhsvm_date(parts[0])
            except ValueError:
                continue

            try:
                segment_id = int(parts[1])
                flow = float(parts[2])
            except (ValueError, IndexError):
                continue

            # Extract name if quoted at end
            name_match = re.search(r'"([^"]+)"', line)
            name = name_match.group(1) if name_match else ""

            records.append({
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "segment_id": segment_id,
                "flow_m3s": flow,
                "name": name,
            })

    return records


def parse_mass_balance_final(filepath):
    """Parse DHSVM Mass.Final.Balance file (from stderr)."""
    balance = {}

    with open(filepath, "r") as f:
        text = f.read()

    patterns = {
        "total_inflow_mm": r"Total Inflow\s*\.+\s*([\d.e+-]+)",
        "precip_inflow_mm": r"Precip/Inflow\s*\.+\s*([\d.e+-]+)",
        "snow_vapor_flux_mm": r"SnowVaporFlux\s*\.+\s*([\d.e+-]+)",
        "total_outflow_mm": r"Total Outflow\s*\.+\s*([\d.e+-]+)",
        "et_mm": r"ET\s*\.+\s*([\d.e+-]+)",
        "channel_int_mm": r"ChannelInt\s*\.+\s*([\d.e+-]+)",
        "road_int_mm": r"RoadInt\s*\.+\s*([\d.e+-]+)",
        "storage_change_mm": r"Storage Change\s*\.+\s*([\d.e+-]+)",
        "initial_storage_mm": r"Initial Storage\s*\.+\s*([\d.e+-]+)",
        "final_storage_mm": r"Final Storage\s*\.+\s*([\d.e+-]+)",
        "final_swq_mm": r"Final SWQ\s*\.+\s*([\d.e+-]+)",
        "final_soil_moisture_mm": r"Final Soil Moisture\s*\.+\s*([\d.e+-]+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            try:
                balance[key] = float(match.group(1))
            except ValueError:
                pass

    return balance


def parse_pixel_output(filepath):
    """Parse DHSVM pixel time series output (same format as Aggregated)."""
    return parse_aggregated(filepath)


# --------------------------------------------------------------------------- #
# Hydrological metrics
# --------------------------------------------------------------------------- #

def calc_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return np.nan
    mean_obs = np.mean(obs)
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - mean_obs) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1.0 - ss_res / ss_tot


def calc_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else np.nan
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else np.nan
    if np.isnan(r) or np.isnan(alpha) or np.isnan(beta):
        return np.nan
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def calc_pbias(obs, sim):
    """Percent Bias (%)."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if np.sum(obs) == 0:
        return np.nan
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def calc_rmse(obs, sim):
    """Root Mean Square Error."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return np.nan
    return np.sqrt(np.mean((obs - sim) ** 2))


def calc_r(obs, sim):
    """Pearson correlation coefficient."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan
    return float(np.corrcoef(obs, sim)[0, 1])


METRIC_FUNCS = {
    "nse": calc_nse,
    "kge": calc_kge,
    "pbias": calc_pbias,
    "rmse": calc_rmse,
    "r": calc_r,
}


# --------------------------------------------------------------------------- #
# Main processing
# --------------------------------------------------------------------------- #

def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    sources = [args.aggregated, args.streamflow, args.mass_balance, args.pixel]
    if not any(sources):
        errors.append("Must provide at least one input: --aggregated, "
                      "--streamflow, --mass-balance, or --pixel")

    for src in sources:
        if src and not os.path.isfile(src):
            errors.append(f"File not found: {src}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed file not found: {args.observed}")

    if args.metrics:
        for m in args.metrics.split(","):
            if m.strip() not in METRIC_FUNCS:
                errors.append(f"Unknown metric: {m}. "
                              f"Valid: {list(METRIC_FUNCS.keys())}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def process(args):
    """Process DHSVM output files."""
    result = {"status": "success"}

    # Parse aggregated output
    if args.aggregated:
        records = parse_aggregated(args.aggregated)
        result["aggregated"] = {
            "file": args.aggregated,
            "n_records": len(records),
            "columns": list(records[0].keys()) if records else [],
        }

        # Write CSV
        if args.output and args.output.endswith(".csv"):
            write_csv(records, args.output)
            result["csv_output"] = args.output

    # Parse streamflow
    if args.streamflow:
        records = parse_streamflow(args.streamflow)
        segments = set(r["segment_id"] for r in records)
        result["streamflow"] = {
            "file": args.streamflow,
            "n_records": len(records),
            "n_segments": len(segments),
            "segments": sorted(segments),
        }

        # Write CSV (was previously only done for --aggregated, so a
        # documented `--streamflow ... --output results.csv` call silently
        # produced no file). Write the parsed streamflow records too.
        if args.output and args.output.endswith(".csv"):
            write_csv(records, args.output)
            result["csv_output"] = args.output

        # Compute metrics if observed data provided
        if args.observed:
            metrics = compute_validation_metrics(
                records, args.observed, args.metrics)
            result["metrics"] = metrics

    # Parse mass balance
    if args.mass_balance:
        balance = parse_mass_balance_final(args.mass_balance)
        result["mass_balance"] = balance

    # Parse pixel output
    if args.pixel:
        records = parse_pixel_output(args.pixel)
        result["pixel"] = {
            "file": args.pixel,
            "n_records": len(records),
            "columns": list(records[0].keys()) if records else [],
        }

    return result


def compute_validation_metrics(sim_records, obs_file, metric_str):
    """Compute validation metrics between simulated and observed."""
    import pandas as pd

    # Load observed data
    obs_df = pd.read_csv(obs_file)

    # Find datetime column
    date_cols = [c for c in obs_df.columns
                 if "date" in c.lower() or "time" in c.lower()]
    if date_cols:
        obs_df["datetime"] = pd.to_datetime(obs_df[date_cols[0]])
    else:
        obs_df["datetime"] = pd.to_datetime(obs_df.iloc[:, 0])

    # Find flow column
    flow_cols = [c for c in obs_df.columns
                 if any(k in c.lower() for k in ["flow", "q", "discharge"])]
    if flow_cols:
        obs_df["obs_flow"] = obs_df[flow_cols[0]]
    else:
        obs_df["obs_flow"] = obs_df.iloc[:, 1]

    # Get total flow from simulation (outlet segment)
    sim_df = pd.DataFrame(sim_records)
    sim_df["datetime"] = pd.to_datetime(sim_df["datetime"])

    # Use outlet (typically segment with name "Totals" or last segment)
    outlet_records = [r for r in sim_records
                      if r.get("name") in ["Totals", "OUTLET", ""]]
    if not outlet_records:
        outlet_records = sim_records

    sim_df = pd.DataFrame(outlet_records)
    sim_df["datetime"] = pd.to_datetime(sim_df["datetime"])

    # Merge on datetime
    merged = pd.merge(obs_df[["datetime", "obs_flow"]],
                       sim_df[["datetime", "flow_m3s"]],
                       on="datetime", how="inner")

    if len(merged) == 0:
        return {"error": "No overlapping timestamps between obs and sim"}

    obs = merged["obs_flow"].values
    sim = merged["flow_m3s"].values

    metrics_to_compute = (metric_str or "nse,kge,pbias,rmse,r").split(",")
    results = {
        "n_matched": len(merged),
        "obs_mean": float(np.nanmean(obs)),
        "sim_mean": float(np.nanmean(sim)),
    }

    for m in metrics_to_compute:
        m = m.strip()
        if m in METRIC_FUNCS:
            results[m] = round(float(METRIC_FUNCS[m](obs, sim)), 4)

    return results


def write_csv(records, filepath):
    """Write records to CSV."""
    if not records:
        return
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def validate_outputs(result):
    """Validate parsed output."""
    if result.get("status") != "success":
        return result

    warnings = []

    agg = result.get("aggregated", {})
    if agg and agg.get("n_records", 0) == 0:
        warnings.append("Aggregated file parsed but no records found")

    sf = result.get("streamflow", {})
    if sf and sf.get("n_records", 0) == 0:
        warnings.append("Stream.Flow file parsed but no records found")

    metrics = result.get("metrics", {})
    if metrics:
        nse = metrics.get("nse")
        if nse is not None and nse < 0:
            warnings.append(f"NSE = {nse} < 0: model worse than mean")
        kge = metrics.get("kge")
        if kge is not None and kge < -0.41:
            warnings.append(f"KGE = {kge} < -0.41: model not useful")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse DHSVM output files and compute metrics")
    parser.add_argument("--aggregated",
                        help="Path to Aggregated.Values file")
    parser.add_argument("--streamflow",
                        help="Path to Stream.Flow file")
    parser.add_argument("--mass-balance",
                        help="Path to Mass.Final.Balance file")
    parser.add_argument("--pixel",
                        help="Path to pixel time series file")
    parser.add_argument("--observed",
                        help="Observed data CSV for validation")
    parser.add_argument("--metrics", default="nse,kge,pbias,rmse,r",
                        help="Metrics to compute (comma-separated)")
    parser.add_argument("--output",
                        help="Output file (.csv or .json)")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    if args.output and args.output.endswith(".json"):
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Output written to {args.output}", file=sys.stderr)
    elif not (args.output and args.output.endswith(".csv")):
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
