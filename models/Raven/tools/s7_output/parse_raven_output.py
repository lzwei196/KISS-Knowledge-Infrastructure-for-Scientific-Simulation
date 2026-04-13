#!/usr/bin/env python3
"""
parse_raven_output.py — Parse Raven output files and extract results.

Reads Hydrographs.csv, WatershedStorage.csv, Diagnostics.csv and produces
standardized output: discharge time series, water balance components,
performance metrics, and summary statistics.

Usage:
    python parse_raven_output.py \
        --output_dir outputs/chaohe_raven/output/ \
        --basin_name chaohe \
        --obs_file data/obs/chaohe/observed.txt \
        --export_csv outputs/chaohe_raven/raven_discharge.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


def find_output_file(output_dir, basename, filename):
    """Find an output file with or without RunName prefix."""
    candidates = [
        os.path.join(output_dir, filename),
        os.path.join(output_dir, f"{basename}_{filename}"),
    ]
    # Also check for files with RunName pattern
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if filename.lower() in f.lower():
                candidates.append(os.path.join(output_dir, f))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def parse_hydrographs(filepath):
    """
    Parse Raven Hydrographs.csv.

    Format (comma-separated):
    date,hour,sub1 [m3/s],sub1 (observed) [m3/s],...
    or
    date,hour,sub_ID [m3/s] (sim),sub_ID [m3/s] (obs),...

    Returns DataFrame with columns: date, simulated, observed (if present).
    """
    try:
        df = pd.read_csv(filepath, skip_blank_lines=True)
    except Exception as e:
        return None, str(e)

    # Find date column
    date_col = None
    for c in df.columns:
        if "date" in c.lower():
            date_col = c
            break

    if date_col is None and len(df.columns) >= 1:
        date_col = df.columns[0]

    # Find simulated discharge column (typically 3rd column)
    sim_col = None
    obs_col = None
    for c in df.columns:
        cl = c.lower().strip()
        if "m3/s" in cl or "cms" in cl:
            if "obs" in cl or "observed" in cl:
                obs_col = c
            elif sim_col is None:
                sim_col = c

    if sim_col is None and len(df.columns) >= 3:
        sim_col = df.columns[2]  # Default: 3rd column is simulated

    if obs_col is None:
        # Check 4th column
        if len(df.columns) >= 4:
            c4 = df.columns[3].lower()
            if "obs" in c4 or "observed" in c4:
                obs_col = df.columns[3]

    result = pd.DataFrame()
    if date_col:
        result["date"] = pd.to_datetime(df[date_col], errors="coerce")
    if sim_col:
        result["simulated_m3s"] = pd.to_numeric(df[sim_col], errors="coerce")
    if obs_col:
        result["observed_m3s"] = pd.to_numeric(df[obs_col], errors="coerce")
        # Replace Raven's missing value marker
        result.loc[result["observed_m3s"] < -9000, "observed_m3s"] = np.nan

    return result, None


def parse_diagnostics(filepath):
    """Parse Diagnostics.csv for performance metrics."""
    metrics = {}
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("*"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    try:
                        metrics[parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    except Exception:
        pass
    return metrics


def parse_watershed_storage(filepath):
    """Parse WatershedStorage.csv for water balance components."""
    try:
        df = pd.read_csv(filepath, skip_blank_lines=True)
        summary = {}
        for col in df.columns:
            if col.lower() in ("date", "hour"):
                continue
            try:
                values = pd.to_numeric(df[col], errors="coerce").dropna()
                if len(values) > 0:
                    summary[col.strip()] = {
                        "mean": round(float(values.mean()), 3),
                        "min": round(float(values.min()), 3),
                        "max": round(float(values.max()), 3),
                    }
            except Exception:
                continue
        return summary
    except Exception:
        return {}


def compute_additional_metrics(sim, obs):
    """Compute NSE, KGE, PBIAS, RMSE from simulated and observed arrays."""
    metrics = {}

    # Remove NaN pairs
    mask = ~(np.isnan(sim) | np.isnan(obs))
    s = sim[mask]
    o = obs[mask]

    if len(s) < 10:
        return {"warning": f"Only {len(s)} valid data points — metrics unreliable"}

    # NSE
    numerator = np.sum((s - o) ** 2)
    denominator = np.sum((o - np.mean(o)) ** 2)
    nse = 1 - numerator / denominator if denominator > 0 else -999
    metrics["NSE"] = round(nse, 4)

    # PBIAS
    pbias = 100 * np.sum(s - o) / np.sum(o) if np.sum(o) != 0 else -999
    metrics["PBIAS"] = round(pbias, 2)

    # RMSE
    rmse = np.sqrt(np.mean((s - o) ** 2))
    metrics["RMSE"] = round(rmse, 3)

    # KGE
    r = np.corrcoef(s, o)[0, 1] if len(s) > 1 else 0
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else 1
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else 1
    kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    metrics["KGE"] = round(kge, 4)

    # Correlation
    metrics["r"] = round(r, 4)

    # Volume ratio
    metrics["volume_ratio"] = round(np.sum(s) / np.sum(o), 3) if np.sum(o) > 0 else -999

    return metrics


def process(args):
    """Main processing."""
    results = {}

    # Parse Hydrographs.csv
    hydro_path = find_output_file(args.output_dir, args.basin_name, "Hydrographs.csv")
    if hydro_path:
        df_hydro, err = parse_hydrographs(hydro_path)
        if err:
            results["hydrograph_error"] = err
        elif df_hydro is not None and "simulated_m3s" in df_hydro.columns:
            sim = df_hydro["simulated_m3s"].dropna()
            results["discharge_stats"] = {
                "mean_m3s": round(float(sim.mean()), 2),
                "max_m3s": round(float(sim.max()), 2),
                "min_m3s": round(float(sim.min()), 2),
                "std_m3s": round(float(sim.std()), 2),
                "n_records": len(sim),
            }

            # Export CSV if requested
            if args.export_csv:
                os.makedirs(os.path.dirname(args.export_csv) or ".", exist_ok=True)
                df_hydro.to_csv(args.export_csv, index=False)
                results["exported_csv"] = args.export_csv

            # Compute metrics if observed data available
            if "observed_m3s" in df_hydro.columns:
                obs = df_hydro["observed_m3s"].values
                sim_arr = df_hydro["simulated_m3s"].values
                metrics = compute_additional_metrics(sim_arr, obs)
                results["computed_metrics"] = metrics
    else:
        results["hydrograph_warning"] = "Hydrographs.csv not found"

    # Parse Diagnostics.csv
    diag_path = find_output_file(args.output_dir, args.basin_name, "Diagnostics.csv")
    if diag_path:
        results["raven_diagnostics"] = parse_diagnostics(diag_path)

    # Parse WatershedStorage.csv
    storage_path = find_output_file(args.output_dir, args.basin_name, "WatershedStorage.csv")
    if storage_path:
        results["watershed_storage"] = parse_watershed_storage(storage_path)

    # Check for solution.rvc (for warm restart)
    sol_path = find_output_file(args.output_dir, args.basin_name, "solution.rvc")
    if sol_path:
        results["solution_rvc"] = sol_path

    results["status"] = "success"
    results["output_dir"] = args.output_dir

    return results


def main():
    parser = argparse.ArgumentParser(description="Parse Raven output files")
    parser.add_argument("--output_dir", required=True, help="Raven output directory")
    parser.add_argument("--basin_name", default="", help="Basin name (RunName prefix)")
    parser.add_argument("--obs_file", default=None, help="Observed discharge file")
    parser.add_argument("--export_csv", default=None, help="Export discharge to CSV")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(json.dumps(results, indent=2, default=str))
    sys.exit(0)


if __name__ == "__main__":
    main()
