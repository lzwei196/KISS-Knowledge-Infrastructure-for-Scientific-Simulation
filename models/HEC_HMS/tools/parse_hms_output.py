#!/usr/bin/env python3
"""
Parse HEC-HMS simulation output to standardized discharge CSV.

Reads the raw simulation output CSV (from run_hec_hms.py or native HEC-HMS DSS)
and extracts daily discharge time series in a clean format suitable for
validation and comparison with observations.

Also supports reading native HEC-DSS output if pydsstools is available.

Usage:
  python3 parse_hms_output.py \
    --input_csv ./sim_discharge.csv \
    --output_csv ./discharge_daily.csv \
    --start_date 1981-01-01 --end_date 1990-12-31
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check input file exists."""
    if not os.path.isfile(args.input_csv):
        print(f"ERROR: Input file not found: {args.input_csv}", file=sys.stderr)
        sys.exit(1)
    print(f"[validate_inputs] Input: {args.input_csv}")


# ---------------------------------------------------------------------------
# Read simulation output
# ---------------------------------------------------------------------------
def read_simulation_output(input_csv):
    """Read simulation output CSV."""
    df = pd.read_csv(input_csv, index_col=0, parse_dates=True)
    print(f"[read] Loaded {len(df)} rows, columns: {list(df.columns)}")

    # Identify discharge column
    q_col = None
    for col in ["q_total_m3s", "Q_m3s", "discharge", "flow", "Q"]:
        if col in df.columns:
            q_col = col
            break

    if q_col is None:
        # Try to find any column with 'm3s' or 'discharge'
        for col in df.columns:
            if "m3" in col.lower() or "discharge" in col.lower() or "flow" in col.lower():
                q_col = col
                break

    if q_col is None:
        print("ERROR: Could not identify discharge column", file=sys.stderr)
        print(f"  Available columns: {list(df.columns)}", file=sys.stderr)
        sys.exit(1)

    print(f"  Discharge column: {q_col}")
    return df, q_col


# ---------------------------------------------------------------------------
# Read native HEC-DSS output (if available)
# ---------------------------------------------------------------------------
def read_dss_output(dss_file, pathname):
    """
    Read discharge from HEC-DSS file.
    Requires pydsstools package.
    """
    try:
        from pydsstools.heclib.dss import HecDss

        with HecDss.Open(dss_file) as fid:
            ts = fid.read_ts(pathname)
            times = ts.pytimes
            values = ts.values

        df = pd.DataFrame({"date": times, "q_total_m3s": values})
        df.set_index("date", inplace=True)
        print(f"[read_dss] Loaded {len(df)} records from DSS")
        return df, "q_total_m3s"

    except ImportError:
        print("WARNING: pydsstools not available — cannot read DSS files")
        return None, None
    except Exception as e:
        print(f"WARNING: Error reading DSS: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
def process(args):
    """Main processing workflow."""
    print("=" * 60)
    print("HEC-HMS Output Parser")
    print("=" * 60)

    # Read simulation output
    df, q_col = read_simulation_output(args.input_csv)

    # Filter to requested period
    if args.start_date:
        df = df[df.index >= args.start_date]
    if args.end_date:
        df = df[df.index <= args.end_date]
    print(f"  Filtered period: {df.index[0]} to {df.index[-1]}, {len(df)} days")

    # Extract discharge
    q = df[q_col].values.copy()
    q = np.maximum(q, 0.0)  # No negative discharge

    # Build clean output
    out_df = pd.DataFrame({
        "date": df.index,
        "sim_discharge_m3s": q,
    })
    out_df.set_index("date", inplace=True)

    # Resample to daily if needed
    if hasattr(out_df.index, "freq") and out_df.index.freq and out_df.index.freq != pd.tseries.offsets.Day():
        out_df = out_df.resample("D").mean()
        print(f"  Resampled to daily: {len(out_df)} days")

    # Statistics
    print(f"\n[stats] Discharge statistics:")
    print(f"  Mean:   {out_df['sim_discharge_m3s'].mean():.1f} m³/s")
    print(f"  Max:    {out_df['sim_discharge_m3s'].max():.1f} m³/s")
    print(f"  Min:    {out_df['sim_discharge_m3s'].min():.1f} m³/s")
    print(f"  Std:    {out_df['sim_discharge_m3s'].std():.1f} m³/s")

    # Write output
    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)
    out_df.to_csv(args.output_csv)
    print(f"\n[write] Output: {args.output_csv}")

    return out_df


# ---------------------------------------------------------------------------
# Validate outputs
# ---------------------------------------------------------------------------
def validate_outputs(df):
    """Validate parsed output."""
    warnings_list = []

    q = df["sim_discharge_m3s"]
    n_missing = q.isna().sum()
    if n_missing > 0:
        warnings_list.append(f"{n_missing} missing values in discharge")

    n_zero = (q == 0).sum()
    if n_zero > len(q) * 0.5:
        warnings_list.append(f"{n_zero}/{len(q)} days have zero discharge — check model")

    if q.max() > 100000:
        warnings_list.append(f"Max discharge {q.max():.0f} m³/s is extremely high — check unit conversion (dt_108)")

    for w in warnings_list:
        print(f"  WARNING: {w}")

    return warnings_list


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Parse HEC-HMS output to standardized CSV")
    parser.add_argument("--input_csv", required=True, help="Simulation output CSV")
    parser.add_argument("--output_csv", required=True, help="Parsed output CSV")
    parser.add_argument("--start_date", default=None, help="Start date filter")
    parser.add_argument("--end_date", default=None, help="End date filter")
    parser.add_argument("--dss_file", default=None, help="HEC-DSS file (alternative input)")
    parser.add_argument("--dss_pathname", default=None, help="DSS pathname for discharge")
    args = parser.parse_args()

    validate_inputs(args)
    df = process(args)
    validate_outputs(df)


if __name__ == "__main__":
    main()
