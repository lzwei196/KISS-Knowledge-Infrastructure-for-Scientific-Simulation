#!/usr/bin/env python3
"""
parse_prms_output.py — Parse PRMS output files and compute hydrologic metrics.

Parses output from:
  - CSV summary files (basin_summary.csv, prms_summary.csv)
  - Model output file (prms.out with daily/monthly/yearly water balance)
  - NetCDF output files (nhru_*.nc, nsegment_*.nc)
  - Statvar files

Computes domain-appropriate metrics:
  - NSE (Nash-Sutcliffe Efficiency)
  - KGE (Kling-Gupta Efficiency)
  - PBIAS (Percent Bias)
  - RMSE (Root Mean Square Error)
  - R2 (coefficient of determination)

Generates validation figures.

Usage:
  python parse_prms_output.py \\
    --output_dir /path/to/prms_output \\
    --observed /path/to/observed_flow.csv \\
    --results_dir /path/to/results \\
    --figure /path/to/validation.png
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Hydrologic Metrics
# ---------------------------------------------------------------------------

def compute_nse(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Nash-Sutcliffe Efficiency.

    NSE = 1 - sum((obs - sim)^2) / sum((obs - mean(obs))^2)
    Range: -inf to 1.0. Perfect = 1.0. Acceptable > 0.5.
    """
    if len(observed) == 0:
        return np.nan
    obs_mean = np.mean(observed)
    numerator = np.sum((observed - simulated) ** 2)
    denominator = np.sum((observed - obs_mean) ** 2)
    if denominator == 0:
        return np.nan
    return 1.0 - numerator / denominator


def compute_kge(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Kling-Gupta Efficiency.

    KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)
    where r = correlation, alpha = std_sim/std_obs, beta = mean_sim/mean_obs
    Range: -inf to 1.0. Perfect = 1.0. Acceptable > 0.5.
    """
    if len(observed) < 3:
        return np.nan
    r = np.corrcoef(observed, simulated)[0, 1]
    alpha = np.std(simulated) / np.std(observed) if np.std(observed) > 0 else np.nan
    beta = np.mean(simulated) / np.mean(observed) if np.mean(observed) > 0 else np.nan
    if np.isnan(r) or np.isnan(alpha) or np.isnan(beta):
        return np.nan
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Percent Bias.

    PBIAS = 100 * sum(sim - obs) / sum(obs)
    Positive = overestimation. Acceptable: |PBIAS| < 25%.
    """
    obs_sum = np.sum(observed)
    if obs_sum == 0:
        return np.nan
    return 100.0 * np.sum(simulated - observed) / obs_sum


def compute_rmse(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Root Mean Square Error."""
    return np.sqrt(np.mean((observed - simulated) ** 2))


def compute_r2(observed: np.ndarray, simulated: np.ndarray) -> float:
    """Coefficient of determination (R-squared)."""
    if len(observed) < 3:
        return np.nan
    r = np.corrcoef(observed, simulated)[0, 1]
    return r ** 2


def compute_all_metrics(observed: np.ndarray, simulated: np.ndarray) -> dict:
    """Compute all hydrologic performance metrics."""
    # Filter out NaN values
    mask = ~(np.isnan(observed) | np.isnan(simulated))
    obs = observed[mask]
    sim = simulated[mask]

    if len(obs) == 0:
        return {"nse": np.nan, "kge": np.nan, "pbias": np.nan,
                "rmse": np.nan, "r2": np.nan, "n": 0}

    return {
        "nse": round(compute_nse(obs, sim), 4),
        "kge": round(compute_kge(obs, sim), 4),
        "pbias": round(compute_pbias(obs, sim), 2),
        "rmse": round(compute_rmse(obs, sim), 4),
        "r2": round(compute_r2(obs, sim), 4),
        "n": len(obs),
    }


# ---------------------------------------------------------------------------
# Output Parsing
# ---------------------------------------------------------------------------

def parse_csv_output(csv_path: str) -> pd.DataFrame:
    """Parse PRMS CSV summary output file.

    Expected format:
        Year,Month,Day,basin_potet,basin_actet,basin_ppt,...
    """
    df = pd.read_csv(csv_path, skipinitialspace=True)

    # PRMS writes column names with leading spaces (", basin_cfs"); normalize.
    df.columns = [str(c).strip() for c in df.columns]

    # Build date index.
    if all(c in df.columns for c in ["Year", "Month", "Day"]):
        df["date"] = pd.to_datetime(
            df[["Year", "Month", "Day"]].rename(
                columns={"Year": "year", "Month": "month", "Day": "day"}
            )
        )
        df = df.set_index("date")
        df = df.drop(columns=["Year", "Month", "Day"], errors="ignore")
    else:
        # PRMS basin_summary / prms_summary (csvON_OFF) write a single combined
        # "Date" column formatted as YYYY-MM-DD, not separate Year/Month/Day.
        # The first data row of prms_summary.csv is a units row ("year-month-day,
        # inches/day,...") that must be dropped before datetime parsing.
        date_col = next((c for c in df.columns
                         if c.lower() in ("date", "year-month-day", "year_month_day")),
                        None)
        if date_col is not None:
            parsed = pd.to_datetime(df[date_col], errors="coerce")
            df = df.loc[parsed.notna()].copy()
            df["date"] = parsed[parsed.notna()].values
            df = df.set_index("date")
            df = df.drop(columns=[date_col], errors="ignore")
            # Remaining value columns may be strings (units row removed) — coerce.
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def parse_model_output(output_path: str) -> pd.DataFrame:
    """Parse PRMS model output file (.out format).

    The model output file contains daily, monthly, yearly, and total summaries.
    This parser extracts daily values.
    """
    records = []
    try:
        with open(output_path, "r") as f:
            for line in f:
                # Look for daily summary lines
                # Format varies, but typically: Year Month Day value1 value2 ...
                parts = line.strip().split()
                if len(parts) >= 6:
                    try:
                        year = int(parts[0])
                        month = int(parts[1])
                        day = int(parts[2])
                        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                            record = {
                                "year": year, "month": month, "day": day,
                            }
                            for i, v in enumerate(parts[3:]):
                                try:
                                    record[f"var_{i}"] = float(v)
                                except ValueError:
                                    pass
                            records.append(record)
                    except ValueError:
                        continue
    except Exception as e:
        print(f"[parse] Warning: Error reading model output: {e}")

    if records:
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df[["year", "month", "day"]])
        df = df.set_index("date")
        return df

    return pd.DataFrame()


def parse_statvar_output(statvar_path: str) -> pd.DataFrame:
    """Parse PRMS statvar file.

    Format:
        Line 1: number of variables
        Lines 2-N+1: variable names
        Data lines: timestep year month day hour min sec val1 val2 ...
    """
    try:
        with open(statvar_path, "r") as f:
            lines = f.readlines()

        n_vars = int(lines[0].strip())
        var_names = [lines[i + 1].strip() for i in range(n_vars)]

        records = []
        for line in lines[n_vars + 1:]:
            parts = line.strip().split()
            if len(parts) >= 7 + n_vars:
                record = {
                    "timestep": int(parts[0]),
                    "year": int(parts[1]),
                    "month": int(parts[2]),
                    "day": int(parts[3]),
                }
                for j, vname in enumerate(var_names):
                    record[vname] = float(parts[7 + j])
                records.append(record)

        if records:
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df[["year", "month", "day"]])
            df = df.set_index("date")
            return df

    except Exception as e:
        print(f"[parse] Warning: Error reading statvar: {e}")

    return pd.DataFrame()


def find_output_files(output_dir: str) -> dict:
    """Discover PRMS output files in directory."""
    out_path = Path(output_dir)
    found = {}

    for pattern, key in [
        ("*.csv", "csv"),
        ("*.out", "model_output"),
        ("*.nc", "netcdf"),
        ("*statvar*", "statvar"),
    ]:
        files = sorted(out_path.glob(pattern))
        if files:
            found[key] = [str(f) for f in files]

    return found


def read_observed(observed_path: str) -> pd.DataFrame:
    """Read observed streamflow data.

    Expected CSV format:
        date,flow_cms (or flow_cfs)
    """
    df = pd.read_csv(observed_path, parse_dates=["date"])
    df = df.set_index("date")

    # Standardize column name
    for col in df.columns:
        if "flow" in col.lower() or "discharge" in col.lower() or "q" in col.lower():
            df = df.rename(columns={col: "observed"})
            break

    if "observed" not in df.columns and len(df.columns) >= 1:
        df = df.rename(columns={df.columns[0]: "observed"})

    return df


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def create_validation_figure(observed: pd.Series, simulated: pd.Series,
                             metrics: dict, output_path: str,
                             basin_name: str = "Test Basin"):
    """Create validation hydrograph figure.

    Uses observed=black, simulated=#2563EB (blue).
    Metrics box in top-right corner.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1])

    # --- Top: Hydrograph ---
    ax = axes[0]
    ax.plot(observed.index, observed.values, color="black", linewidth=0.8,
            label="Observed", alpha=0.8)
    ax.plot(simulated.index, simulated.values, color="#2563EB", linewidth=0.8,
            label="Simulated", alpha=0.8)
    ax.set_ylabel("Streamflow (cfs)")
    ax.set_title(f"PRMS Validation — {basin_name}")
    ax.legend(loc="upper left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())

    # Metrics box
    metrics_text = (
        f"NSE = {metrics['nse']:.3f}\n"
        f"KGE = {metrics['kge']:.3f}\n"
        f"PBIAS = {metrics['pbias']:.1f}%\n"
        f"R² = {metrics['r2']:.3f}\n"
        f"n = {metrics['n']}"
    )
    props = dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9,
                 edgecolor="gray")
    ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes, fontsize=10,
            verticalalignment="top", horizontalalignment="right", bbox=props)

    # --- Bottom: Residuals ---
    ax2 = axes[1]
    common_idx = observed.index.intersection(simulated.index)
    residuals = simulated.loc[common_idx] - observed.loc[common_idx]
    ax2.bar(common_idx, residuals.values, color="#2563EB", alpha=0.5, width=1)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel("Residual (cfs)")
    ax2.set_xlabel("Date")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[figure] Saved: {output_path}")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_to_csv(df: pd.DataFrame, output_path: str):
    """Export parsed data to standardized CSV."""
    df.to_csv(output_path)
    print(f"[export] CSV: {output_path} ({len(df)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Parse PRMS output and compute metrics"
    )
    parser.add_argument("--output_dir", required=True,
                        help="Directory containing PRMS output files")
    parser.add_argument("--observed", default=None,
                        help="Path to observed streamflow CSV")
    parser.add_argument("--results_dir", default=None,
                        help="Directory for parsed results")
    parser.add_argument("--figure", default=None,
                        help="Path for validation figure")
    parser.add_argument("--basin_name", default="Test Basin",
                        help="Basin name for figure title")
    args = parser.parse_args()

    print("=" * 60)
    print("PRMS Output Parser")
    print("=" * 60)

    # Step 1: Find output files
    print("\n--- Discovering output files ---")
    found = find_output_files(args.output_dir)
    for ftype, files in found.items():
        for f in files:
            print(f"  {ftype}: {f}")

    if not found:
        print("  No output files found!")
        sys.exit(1)

    # Step 2: Parse outputs
    print("\n--- Parsing outputs ---")
    sim_df = None

    if "csv" in found:
        for csv_file in found["csv"]:
            try:
                df = parse_csv_output(csv_file)
                if len(df) > 0:
                    print(f"  Parsed CSV: {csv_file} ({len(df)} rows)")
                    sim_df = df
                    break
            except Exception as e:
                print(f"  Error parsing {csv_file}: {e}")

    if sim_df is None and "model_output" in found:
        for out_file in found["model_output"]:
            try:
                df = parse_model_output(out_file)
                if len(df) > 0:
                    print(f"  Parsed model output: {out_file} ({len(df)} rows)")
                    sim_df = df
                    break
            except Exception as e:
                print(f"  Error parsing {out_file}: {e}")

    if sim_df is None:
        print("  Could not parse any output files")
        sys.exit(1)

    # Step 3: Export parsed results
    if args.results_dir:
        results_path = Path(args.results_dir)
        results_path.mkdir(parents=True, exist_ok=True)
        export_to_csv(sim_df, str(results_path / "parsed_output.csv"))

    # Step 4: Compare with observations
    if args.observed and Path(args.observed).exists():
        print("\n--- Computing metrics ---")
        obs_df = read_observed(args.observed)

        # Find matching flow variable
        sim_flow_col = None
        for col in sim_df.columns:
            if "stflow" in col.lower() or "cfs" in col.lower() or "flow" in col.lower():
                sim_flow_col = col
                break
        if sim_flow_col is None and len(sim_df.columns) > 0:
            sim_flow_col = sim_df.columns[-1]

        if sim_flow_col:
            common_idx = obs_df.index.intersection(sim_df.index)
            if len(common_idx) > 0:
                obs_vals = obs_df.loc[common_idx, "observed"].values
                sim_vals = sim_df.loc[common_idx, sim_flow_col].values

                metrics = compute_all_metrics(obs_vals, sim_vals)
                print(f"\n  Metrics (n={metrics['n']}):")
                print(f"    NSE   = {metrics['nse']}")
                print(f"    KGE   = {metrics['kge']}")
                print(f"    PBIAS = {metrics['pbias']}%")
                print(f"    RMSE  = {metrics['rmse']}")
                print(f"    R²    = {metrics['r2']}")

                # Step 5: Create figure
                if args.figure:
                    create_validation_figure(
                        obs_df.loc[common_idx, "observed"],
                        sim_df.loc[common_idx, sim_flow_col],
                        metrics, args.figure, args.basin_name
                    )
            else:
                print("  No overlapping dates between observed and simulated")
    else:
        print("\n  No observed data provided — skipping metrics")

    print("\nDone.")


if __name__ == "__main__":
    main()
