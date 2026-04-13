#!/usr/bin/env python3
"""
Parse HEC-RAS (GR4J surrogate) simulation output to standardized discharge CSV.

Reads the raw simulation output CSV produced by run_hecras.py and extracts
daily discharge time series in a clean format suitable for validation and
comparison with observations or other models.

Supports:
  - Date filtering (--start_date, --end_date)
  - Column auto-detection (sim_q_m3s, q_total_m3s, Q, discharge, etc.)
  - Summary statistics and diagnostics
  - Comparison with observation data (--obs_file)

Usage:
  python3 parse_output_hecras.py \\
    --input_csv ./sim_output.csv \\
    --output_csv ./discharge_daily.csv \\
    --start_date 1981-01-01 --end_date 1990-12-31

  # With observation comparison:
  python3 parse_output_hecras.py \\
    --input_csv ./sim_output.csv \\
    --output_csv ./discharge_daily.csv \\
    --obs_file /path/to/obs.txt \\
    --start_date 1986-01-01 --end_date 1990-12-31

References:
  - dt_205: Q conversion m3/s <-> mm/day
  - dt_208: Spinup days should be excluded from evaluation
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Candidate column names for discharge (checked in order)
DISCHARGE_COLUMNS = [
    "sim_q_m3s",
    "q_total_m3s",
    "Q_m3s",
    "discharge_m3s",
    "discharge",
    "flow",
    "Q",
]


# ===========================================================================
# Validate inputs
# ===========================================================================
def validate_inputs(args):
    """Check input file exists.

    Args:
        args: Parsed argparse namespace.

    Raises:
        SystemExit: If input file is missing.
    """
    errors = []

    if not os.path.isfile(args.input_csv):
        errors.append(f"Input file not found: {args.input_csv}")

    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if args.start_date and args.end_date:
        try:
            s = pd.Timestamp(args.start_date)
            e = pd.Timestamp(args.end_date)
            if s >= e:
                errors.append("start_date must be before end_date")
        except Exception as ex:
            errors.append(f"Invalid date format: {ex}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[validate_inputs] Input: {args.input_csv}")


# ===========================================================================
# Detect discharge column
# ===========================================================================
def detect_discharge_column(df):
    """Auto-detect the discharge column from common naming conventions.

    Args:
        df: Input DataFrame.

    Returns:
        q_col: Name of the discharge column.

    Raises:
        SystemExit: If no discharge column is found.
    """
    # Check exact matches first
    for col in DISCHARGE_COLUMNS:
        if col in df.columns:
            return col

    # Fuzzy match: look for 'm3' or 'discharge' or 'flow' in column name
    for col in df.columns:
        col_lower = col.lower()
        if "m3" in col_lower or "discharge" in col_lower or "flow" in col_lower:
            return col

    print("ERROR: Could not identify discharge column", file=sys.stderr)
    print(f"  Available columns: {list(df.columns)}", file=sys.stderr)
    sys.exit(1)


# ===========================================================================
# Performance metrics
# ===========================================================================
def calc_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    return 1.0 - np.sum((o - s) ** 2) / np.sum((o - np.mean(o)) ** 2)


def calc_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o)
    beta = np.mean(s) / np.mean(o)
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def calc_pbias(obs, sim):
    """Percent bias."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10 or np.sum(o) == 0:
        return np.nan
    return 100.0 * np.sum(s - o) / np.sum(o)


def calc_rmse(obs, sim):
    """Root mean square error."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    return np.sqrt(np.mean((o - s) ** 2))


def calc_corr(obs, sim):
    """Pearson correlation coefficient."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    return np.corrcoef(o, s)[0, 1]


# ===========================================================================
# Process
# ===========================================================================
def process(args):
    """Main output parsing workflow.

    Steps:
      1. Read simulation CSV
      2. Detect discharge column
      3. Filter to requested date range
      4. Build clean output DataFrame
      5. Optionally compare with observations

    Args:
        args: Parsed argparse namespace.

    Returns:
        out_df: Clean DataFrame with sim_discharge_m3s column.
        metrics: dict of comparison metrics (empty if no obs).
    """
    print("=" * 60)
    print("HEC-RAS Output Parser (GR4J Surrogate)")
    print("=" * 60)

    # 1. Read simulation output
    print("\n[read] Loading simulation output...")
    df = pd.read_csv(args.input_csv, index_col=0, parse_dates=True)
    print(f"  Loaded {len(df)} rows, columns: {list(df.columns)}")

    # 2. Detect discharge column
    q_col = detect_discharge_column(df)
    print(f"  Discharge column: {q_col}")

    # 3. Filter to date range
    if args.start_date:
        df = df[df.index >= args.start_date]
    if args.end_date:
        df = df[df.index <= args.end_date]

    if len(df) == 0:
        print("ERROR: No data in requested period", file=sys.stderr)
        sys.exit(1)

    print(f"  Filtered: {df.index[0]} to {df.index[-1]}, {len(df)} days")

    # 4. Extract and clean discharge
    q = df[q_col].values.copy()
    q = np.maximum(q, 0.0)  # No negative discharge

    out_df = pd.DataFrame(
        {"sim_discharge_m3s": q},
        index=df.index,
    )
    out_df.index.name = "date"

    # 5. Summary statistics
    print(f"\n[stats] Discharge statistics:")
    print(f"  Mean:   {out_df['sim_discharge_m3s'].mean():.1f} m3/s")
    print(f"  Max:    {out_df['sim_discharge_m3s'].max():.1f} m3/s")
    print(f"  Min:    {out_df['sim_discharge_m3s'].min():.1f} m3/s")
    print(f"  Std:    {out_df['sim_discharge_m3s'].std():.1f} m3/s")

    # 6. Compare with observations if provided
    metrics = {}
    if args.obs_file:
        print(f"\n[compare] Comparing with observations...")
        obs_df = pd.read_csv(args.obs_file, sep="\t", encoding="gbk")
        obs_df["date"] = pd.to_datetime(obs_df["dates"], format="mixed")
        obs_df = obs_df[["date", "Q"]].set_index("date").sort_index()
        obs_df.loc[obs_df["Q"] < 0, "Q"] = np.nan

        common_idx = out_df.index.intersection(obs_df.index)
        if len(common_idx) > 0:
            obs_vals = obs_df.loc[common_idx, "Q"].values
            sim_vals = out_df.loc[common_idx, "sim_discharge_m3s"].values

            metrics = {
                "n_days": int(len(common_idx)),
                "NSE": round(float(calc_nse(obs_vals, sim_vals)), 4),
                "KGE": round(float(calc_kge(obs_vals, sim_vals)), 4),
                "PBIAS_pct": round(float(calc_pbias(obs_vals, sim_vals)), 2),
                "RMSE_m3s": round(float(calc_rmse(obs_vals, sim_vals)), 1),
                "r": round(float(calc_corr(obs_vals, sim_vals)), 4),
                "mean_obs_m3s": round(float(np.nanmean(obs_vals)), 1),
                "mean_sim_m3s": round(float(np.nanmean(sim_vals)), 1),
            }

            print(f"  Common days: {metrics['n_days']}")
            print(f"  NSE:   {metrics['NSE']}")
            print(f"  KGE:   {metrics['KGE']}")
            print(f"  PBIAS: {metrics['PBIAS_pct']}%")
            print(f"  RMSE:  {metrics['RMSE_m3s']} m3/s")
            print(f"  r:     {metrics['r']}")

            # Add obs to output for convenience
            out_df = out_df.join(
                obs_df.rename(columns={"Q": "obs_discharge_m3s"}),
                how="left",
            )
        else:
            print("  WARNING: No overlapping dates between sim and obs")

    # 7. Write output
    out_dir = os.path.dirname(args.output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_df.to_csv(args.output_csv)
    print(f"\n[write] Output: {args.output_csv}")
    print(f"  Columns: {list(out_df.columns)}")

    # Write metrics if available
    if metrics:
        metrics_path = args.output_csv.replace(".csv", "_metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"  Metrics: {metrics_path}")

    return out_df, metrics


# ===========================================================================
# Validate outputs
# ===========================================================================
def validate_outputs(out_df):
    """Validate parsed output for physical consistency.

    Args:
        out_df: Output DataFrame with sim_discharge_m3s column.

    Returns:
        warnings_list: List of warning strings.
    """
    warnings_list = []
    q = out_df["sim_discharge_m3s"]

    # Missing values
    n_missing = q.isna().sum()
    if n_missing > 0:
        warnings_list.append(f"{n_missing} missing values in discharge")

    # Zero-flow days
    n_zero = (q == 0).sum()
    if n_zero > len(q) * 0.5:
        warnings_list.append(
            f"{n_zero}/{len(q)} days have zero discharge -- check model parameters"
        )

    # Extreme values
    if q.max() > 100000:
        warnings_list.append(
            f"Max discharge = {q.max():.0f} m3/s is extremely high -- "
            f"check unit conversion (dt_205)"
        )

    # Constant output (model may not be running)
    if q.std() < 0.01 * q.mean() and q.mean() > 0:
        warnings_list.append(
            "Discharge has very low variability -- model may not be responding to forcing"
        )

    for w in warnings_list:
        print(f"  WARNING: {w}")

    if not warnings_list:
        print("[validate_outputs] All output checks passed.")

    return warnings_list


# ===========================================================================
# Main
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Parse HEC-RAS (GR4J) output to standardized discharge CSV"
    )
    parser.add_argument(
        "--input_csv", required=True,
        help="Simulation output CSV from run_hecras.py",
    )
    parser.add_argument(
        "--output_csv", required=True,
        help="Parsed output CSV (standardized format)",
    )
    parser.add_argument(
        "--start_date", default=None,
        help="Start date filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end_date", default=None,
        help="End date filter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--obs_file", default=None,
        help="Observation file for comparison (optional)",
    )
    args = parser.parse_args()

    # Validate-process-validate
    validate_inputs(args)
    out_df, metrics = process(args)
    validate_outputs(out_df)


if __name__ == "__main__":
    main()
