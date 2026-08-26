#!/usr/bin/env python3
"""
parse_ribasim_output.py — Extract Ribasim NetCDF results to CSV with metrics.

Reads the NetCDF output files from a Ribasim simulation, computes summary
statistics and water balance metrics, and exports time series to CSV format
for further analysis or comparison with observations.

Pattern: validate → process → validate

Usage:
    python parse_ribasim_output.py \
        --results_dir my_model/results/ \
        --output_csv basin_timeseries.csv \
        --flow_csv flow_timeseries.csv \
        --summary_json summary.json \
        --obs_csv observed_levels.csv
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_results_dir(results_dir: Path) -> list[str]:
    """Validate that required output files exist."""
    errors = []

    if not results_dir.exists():
        errors.append(f"Results directory not found: {results_dir}")
        return errors

    required = ["basin.nc"]
    for fname in required:
        fpath = results_dir / fname
        if not fpath.exists():
            errors.append(f"Required output file missing: {fpath}")
        elif fpath.stat().st_size < 100:
            errors.append(f"Output file appears empty: {fpath}")

    return errors


def validate_obs_csv(df: pd.DataFrame) -> list[str]:
    """Validate observation CSV format."""
    errors = []

    if "time" not in df.columns:
        errors.append("Observation CSV missing 'time' column")

    if "level" not in df.columns and "flow" not in df.columns:
        errors.append("Observation CSV missing 'level' or 'flow' column")

    return errors


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------
def compute_nse(obs: np.ndarray, sim: np.ndarray) -> float:
    """Nash-Sutcliffe Efficiency."""
    obs_mean = np.nanmean(obs)
    numerator = np.nansum((obs - sim) ** 2)
    denominator = np.nansum((obs - obs_mean) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs: np.ndarray, sim: np.ndarray) -> float:
    """Kling-Gupta Efficiency."""
    valid = ~(np.isnan(obs) | np.isnan(sim))
    obs_v, sim_v = obs[valid], sim[valid]
    if len(obs_v) < 2:
        return float("nan")

    r = np.corrcoef(obs_v, sim_v)[0, 1]
    alpha = np.std(sim_v) / np.std(obs_v) if np.std(obs_v) > 0 else float("nan")
    beta = np.mean(sim_v) / np.mean(obs_v) if np.mean(obs_v) != 0 else float("nan")

    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs: np.ndarray, sim: np.ndarray) -> float:
    """Percent Bias."""
    obs_sum = np.nansum(obs)
    if obs_sum == 0:
        return float("nan")
    return 100.0 * np.nansum(sim - obs) / obs_sum


def compute_rmse(obs: np.ndarray, sim: np.ndarray) -> float:
    """Root Mean Square Error."""
    return float(np.sqrt(np.nanmean((obs - sim) ** 2)))


def compute_r_squared(obs: np.ndarray, sim: np.ndarray) -> float:
    """Coefficient of determination (R²)."""
    valid = ~(np.isnan(obs) | np.isnan(sim))
    if valid.sum() < 2:
        return float("nan")
    r = np.corrcoef(obs[valid], sim[valid])[0, 1]
    return r ** 2


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def parse_basin_nc(results_dir: Path) -> pd.DataFrame:
    """Parse basin.nc into a pandas DataFrame."""
    import xarray as xr

    basin_path = results_dir / "basin.nc"
    ds = xr.open_dataset(basin_path, engine="h5netcdf")

    # Get all variables and flatten to DataFrame
    df = ds.to_dataframe().reset_index()
    ds.close()

    return df


def parse_flow_nc(results_dir: Path) -> pd.DataFrame | None:
    """Parse flow.nc into a pandas DataFrame."""
    import xarray as xr

    flow_path = results_dir / "flow.nc"
    if not flow_path.exists():
        return None

    ds = xr.open_dataset(flow_path, engine="h5netcdf")
    df = ds.to_dataframe().reset_index()
    ds.close()

    return df


def parse_basin_state_nc(results_dir: Path) -> pd.DataFrame | None:
    """Parse basin_state.nc for final states."""
    import xarray as xr

    state_path = results_dir / "basin_state.nc"
    if not state_path.exists():
        return None

    ds = xr.open_dataset(state_path, engine="h5netcdf")
    df = ds.to_dataframe().reset_index()
    ds.close()

    return df


def compute_water_balance_summary(basin_df: pd.DataFrame) -> dict:
    """Compute water balance statistics per basin."""
    summary = {}

    # Identify node_id column
    nid_col = "node_id" if "node_id" in basin_df.columns else basin_df.columns[0]

    for nid, group in basin_df.groupby(nid_col):
        nid_key = str(nid)
        stats = {}

        for var in ["level", "storage", "precipitation", "evaporation",
                     "drainage", "infiltration", "inflow_rate", "outflow_rate",
                     "balance_error", "relative_error"]:
            if var in group.columns:
                vals = group[var].dropna()
                if len(vals) > 0:
                    stats[var] = {
                        "mean": float(np.mean(vals)),
                        "std": float(np.std(vals)),
                        "min": float(np.min(vals)),
                        "max": float(np.max(vals)),
                    }

        # Check water balance closure
        if "balance_error" in group.columns:
            max_err = group["balance_error"].abs().max()
            stats["max_balance_error"] = float(max_err)
            stats["balance_ok"] = max_err < 0.01  # 1% threshold

        summary[nid_key] = stats

    return summary


def compare_with_observations(
    basin_df: pd.DataFrame, obs_df: pd.DataFrame, node_id: int, variable: str = "level"
) -> dict:
    """Compare simulated vs observed data for a specific node."""
    # Filter simulated
    nid_col = "node_id" if "node_id" in basin_df.columns else basin_df.columns[0]
    sim = basin_df[basin_df[nid_col] == node_id].copy()

    if len(sim) == 0:
        return {"error": f"No simulated data for node {node_id}"}

    # Ensure time columns are datetime
    sim["time"] = pd.to_datetime(sim["time"])
    obs_df["time"] = pd.to_datetime(obs_df["time"])

    # Merge on time (nearest)
    merged = pd.merge_asof(
        obs_df.sort_values("time"),
        sim[["time", variable]].sort_values("time"),
        on="time",
        suffixes=("_obs", "_sim"),
        direction="nearest",
        tolerance=pd.Timedelta("1D"),
    )

    obs_col = f"{variable}_obs" if f"{variable}_obs" in merged.columns else variable
    sim_col = f"{variable}_sim" if f"{variable}_sim" in merged.columns else variable

    obs_arr = merged[obs_col].values.astype(float)
    sim_arr = merged[sim_col].values.astype(float)

    valid = ~(np.isnan(obs_arr) | np.isnan(sim_arr))
    if valid.sum() < 2:
        return {"error": "Insufficient overlapping data points"}

    obs_v = obs_arr[valid]
    sim_v = sim_arr[valid]

    metrics = {
        "n_points": int(valid.sum()),
        "nse": round(compute_nse(obs_v, sim_v), 4),
        "kge": round(compute_kge(obs_v, sim_v), 4),
        "pbias": round(compute_pbias(obs_v, sim_v), 2),
        "rmse": round(compute_rmse(obs_v, sim_v), 4),
        "r_squared": round(compute_r_squared(obs_v, sim_v), 4),
        "obs_mean": round(float(np.mean(obs_v)), 4),
        "sim_mean": round(float(np.mean(sim_v)), 4),
        "obs_std": round(float(np.std(obs_v)), 4),
        "sim_std": round(float(np.std(sim_v)), 4),
    }

    return metrics


def validate_parsed_output(basin_df: pd.DataFrame) -> list[str]:
    """Post-parse validation checks."""
    errors = []

    if len(basin_df) == 0:
        errors.append("Parsed basin DataFrame is empty")
        return errors

    # Check for all-NaN columns
    for col in basin_df.columns:
        if basin_df[col].isna().all():
            errors.append(f"Column '{col}' is all NaN")

    # Check time range
    if "time" in basin_df.columns:
        times = pd.to_datetime(basin_df["time"])
        duration = (times.max() - times.min()).days
        if duration < 1:
            errors.append(f"Simulation duration is only {duration} days — likely solver failure")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Parse Ribasim output to CSV")
    parser.add_argument("--results_dir", required=True, help="Ribasim results directory")
    parser.add_argument("--output_csv", default="basin_timeseries.csv", help="Basin output CSV")
    parser.add_argument("--flow_csv", default="flow_timeseries.csv", help="Flow output CSV")
    parser.add_argument("--summary_json", default="output_summary.json", help="Summary JSON")
    parser.add_argument("--obs_csv", help="Observed data CSV for comparison")
    parser.add_argument("--obs_node_id", type=int, help="Node ID for observation comparison")
    parser.add_argument("--obs_variable", default="level", help="Variable to compare")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    # --- Input validation ---
    print("[1/3] Validating results directory...")
    errors = validate_results_dir(results_dir)
    if errors:
        print("ERROR: Results validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # --- Parse outputs ---
    print("[2/3] Parsing NetCDF outputs...")
    try:
        basin_df = parse_basin_nc(results_dir)
        print(f"  basin.nc: {len(basin_df)} records")
    except Exception as e:
        print(f"ERROR: Failed to parse basin.nc: {e}")
        sys.exit(1)

    flow_df = parse_flow_nc(results_dir)
    if flow_df is not None:
        print(f"  flow.nc: {len(flow_df)} records")

    # --- Post-parse validation ---
    errors = validate_parsed_output(basin_df)
    if errors:
        print("WARNING: Output parsing issues:")
        for e in errors:
            print(f"  - {e}")

    # --- Export to CSV ---
    print("[3/3] Exporting to CSV...")
    basin_csv_path = Path(args.output_csv)
    basin_df.to_csv(basin_csv_path, index=False)
    print(f"  Basin CSV: {basin_csv_path}")

    if flow_df is not None:
        flow_csv_path = Path(args.flow_csv)
        flow_df.to_csv(flow_csv_path, index=False)
        print(f"  Flow CSV: {flow_csv_path}")

    # --- Compute summary ---
    summary = {
        "status": "success",
        "n_basin_records": len(basin_df),
        "n_flow_records": len(flow_df) if flow_df is not None else 0,
        "water_balance": compute_water_balance_summary(basin_df),
    }

    # --- Compare with observations if provided ---
    if args.obs_csv and args.obs_node_id:
        print(f"\nComparing with observations (node {args.obs_node_id})...")
        obs_df = pd.read_csv(args.obs_csv)
        errors = validate_obs_csv(obs_df)
        if errors:
            print("WARNING: Observation validation issues:")
            for e in errors:
                print(f"  - {e}")
        else:
            metrics = compare_with_observations(
                basin_df, obs_df, args.obs_node_id, args.obs_variable
            )
            summary["observation_comparison"] = metrics
            print(f"  NSE: {metrics.get('nse', 'N/A')}")
            print(f"  KGE: {metrics.get('kge', 'N/A')}")
            print(f"  PBIAS: {metrics.get('pbias', 'N/A')}%")
            print(f"  RMSE: {metrics.get('rmse', 'N/A')}")

    # Write summary
    summary_path = Path(args.summary_json)
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary: {summary_path}")


if __name__ == "__main__":
    main()
