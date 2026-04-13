#!/usr/bin/env python3
"""
parse_delft3d_output.py — Extract Delft3D results to CSV + compute metrics

Parses Delft3D NetCDF output files (_map.nc, _his.nc) and extracts
key variables (water level, velocity, salinity, temperature) to CSV.
Computes validation metrics (RMSE, bias, R², skill score) when observed
data is provided.

Pipeline stage: s7 (output analysis)
Pattern: validate → process → validate

Supports:
  - D-Flow FM output (_his.nc history, _map.nc spatial)
  - Delft3D-FLOW output (trim-*.nc, trih-*.nc)
  - Time series extraction at observation points
  - Spatial field extraction at specific timesteps
  - Comparison with observed data + metric computation
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

KEY_VARIABLES = {
    # D-Flow FM variable names
    "s1": {"long_name": "water_level", "unit": "m"},
    "ucx": {"long_name": "velocity_x", "unit": "m/s"},
    "ucy": {"long_name": "velocity_y", "unit": "m/s"},
    "waterdepth": {"long_name": "water_depth", "unit": "m"},
    "sa1": {"long_name": "salinity", "unit": "PSU"},
    "tem1": {"long_name": "temperature", "unit": "degC"},
    "q1": {"long_name": "discharge", "unit": "m3/s"},
    "taus": {"long_name": "bed_shear_stress", "unit": "N/m2"},
    # Delft3D-FLOW variable names
    "S1": {"long_name": "water_level", "unit": "m"},
    "U1": {"long_name": "velocity_u", "unit": "m/s"},
    "V1": {"long_name": "velocity_v", "unit": "m/s"},
}


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────

def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if args.his_file and not os.path.isfile(args.his_file):
        errors.append(f"History file not found: {args.his_file}")
    if args.map_file and not os.path.isfile(args.map_file):
        errors.append(f"Map file not found: {args.map_file}")
    if not args.his_file and not args.map_file:
        errors.append("Must provide at least --his_file or --map_file")
    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("[validate_inputs] All inputs valid.")


def validate_outputs(output_csv, metrics):
    """Validate extracted output for physical plausibility."""
    warnings = []

    if os.path.isfile(output_csv):
        df = pd.read_csv(output_csv) if pd else None
        if df is not None:
            for col in df.columns:
                if col == "time":
                    continue
                vals = df[col].dropna()
                if len(vals) == 0:
                    warnings.append(f"Column {col} is all NaN")
                    continue
                if col.startswith("water_level") or col.startswith("s1"):
                    if vals.max() > 50 or vals.min() < -50:
                        warnings.append(
                            f"Water level range [{vals.min():.1f}, {vals.max():.1f}] m "
                            "seems extreme"
                        )
                if col.startswith("velocity") or col.startswith("uc"):
                    if vals.max() > 10:
                        warnings.append(
                            f"Velocity max {vals.max():.1f} m/s seems extreme"
                        )

    if metrics:
        if "rmse" in metrics and metrics["rmse"] > 2.0:
            warnings.append(f"RMSE = {metrics['rmse']:.3f} — relatively large error")

    if warnings:
        print("[validate_outputs] WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("[validate_outputs] Output validation passed.")

    return warnings


# ──────────────────────────────────────────────────────────────────────
# NetCDF reading
# ──────────────────────────────────────────────────────────────────────

def read_his_file(his_file, variables=None, stations=None):
    """Read D-Flow FM history file (_his.nc) or Delft3D-FLOW trih file."""
    if nc is None:
        print("ERROR: netCDF4 not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading history file: {his_file}")
    ds = nc.Dataset(his_file, "r")

    # Get time
    time_var = None
    for tname in ["time", "TIMESTEP"]:
        if tname in ds.variables:
            time_var = tname
            break

    if time_var is None:
        print("ERROR: No time variable found", file=sys.stderr)
        ds.close()
        return None

    times = nc.num2date(ds.variables[time_var][:],
                        ds.variables[time_var].units,
                        only_use_cftime_datetimes=False)
    n_times = len(times)

    # Get station names
    station_names = []
    for sname in ["station_name", "NAMST", "station_id"]:
        if sname in ds.variables:
            raw = ds.variables[sname][:]
            if hasattr(raw, "tobytes"):
                # Character array → strings
                station_names = [
                    b"".join(raw[i]).decode("utf-8", errors="ignore").strip()
                    for i in range(raw.shape[0])
                ]
            else:
                station_names = [str(s) for s in raw]
            break

    n_stations = len(station_names) if station_names else 1
    print(f"  Timesteps: {n_times}, Stations: {n_stations}")
    if station_names:
        print(f"  Station names: {station_names[:10]}")

    # Extract variables
    if variables is None:
        variables = [v for v in KEY_VARIABLES if v in ds.variables]

    results = {"time": [str(t) for t in times]}

    for var_name in variables:
        if var_name not in ds.variables:
            continue
        var = ds.variables[var_name]
        data = var[:]

        if isinstance(data, np.ma.MaskedArray):
            data = data.filled(np.nan)

        info = KEY_VARIABLES.get(var_name, {"long_name": var_name, "unit": "?"})

        if data.ndim == 1:
            # Single station / scalar
            results[f"{info['long_name']}_{info['unit']}"] = data
        elif data.ndim == 2:
            # (time, station)
            for si in range(min(data.shape[1], n_stations)):
                sname = station_names[si] if si < len(station_names) else f"sta_{si}"
                if stations and sname not in stations:
                    continue
                col = f"{info['long_name']}_{sname}_{info['unit']}"
                results[col] = data[:, si]
        elif data.ndim == 3:
            # (time, station, layer) → take surface layer
            for si in range(min(data.shape[1], n_stations)):
                sname = station_names[si] if si < len(station_names) else f"sta_{si}"
                if stations and sname not in stations:
                    continue
                col = f"{info['long_name']}_{sname}_{info['unit']}"
                results[col] = data[:, si, 0]  # surface layer

        print(f"  Extracted: {var_name} ({info['long_name']})")

    ds.close()
    return results


def read_map_file(map_file, variables=None, timestep=-1):
    """Read D-Flow FM map file (_map.nc) at a specific timestep."""
    if nc is None:
        print("ERROR: netCDF4 not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading map file: {map_file}")
    ds = nc.Dataset(map_file, "r")

    # Get time
    time_var = None
    for tname in ["time", "TIMESTEP"]:
        if tname in ds.variables:
            time_var = tname
            break

    if time_var:
        times = nc.num2date(ds.variables[time_var][:],
                            ds.variables[time_var].units,
                            only_use_cftime_datetimes=False)
        n_times = len(times)
        print(f"  Timesteps: {n_times}, extracting step {timestep}")
    else:
        n_times = 1
        timestep = 0

    # Get coordinates
    x_coords, y_coords = None, None
    for xname in ["FlowElem_xcc", "mesh2d_face_x", "XZ", "x"]:
        if xname in ds.variables:
            x_coords = ds.variables[xname][:]
            break
    for yname in ["FlowElem_ycc", "mesh2d_face_y", "YZ", "y"]:
        if yname in ds.variables:
            y_coords = ds.variables[yname][:]
            break

    # Extract variables at timestep
    if variables is None:
        variables = [v for v in KEY_VARIABLES if v in ds.variables]

    results = {}
    if x_coords is not None:
        results["x"] = x_coords
        results["y"] = y_coords

    for var_name in variables:
        if var_name not in ds.variables:
            continue
        var = ds.variables[var_name]
        data = var[timestep] if var.ndim > 1 else var[:]

        if isinstance(data, np.ma.MaskedArray):
            data = data.filled(np.nan)

        # Flatten multi-dimensional data (take surface layer for 3D)
        while data.ndim > 1:
            data = data[..., 0]

        info = KEY_VARIABLES.get(var_name, {"long_name": var_name, "unit": "?"})
        results[f"{info['long_name']}_{info['unit']}"] = data
        print(f"  Extracted: {var_name}, range=[{np.nanmin(data):.4f}, {np.nanmax(data):.4f}]")

    ds.close()
    return results


# ──────────────────────────────────────────────────────────────────────
# Metrics computation
# ──────────────────────────────────────────────────────────────────────

def compute_metrics(observed, simulated):
    """Compute validation metrics between observed and simulated time series."""
    # Align and remove NaN
    mask = ~(np.isnan(observed) | np.isnan(simulated))
    obs = observed[mask]
    sim = simulated[mask]

    if len(obs) < 3:
        return {"error": "Insufficient overlapping data points"}

    n = len(obs)
    metrics = {}

    # RMSE
    metrics["rmse"] = np.sqrt(np.mean((obs - sim) ** 2))

    # Bias (mean error)
    metrics["bias"] = np.mean(sim - obs)

    # R² (coefficient of determination)
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    metrics["r_squared"] = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Pearson correlation
    r = np.corrcoef(obs, sim)[0, 1]
    metrics["r"] = r

    # NSE (Nash-Sutcliffe Efficiency)
    metrics["nse"] = 1.0 - ss_res / ss_tot if ss_tot > 0 else -999

    # PBIAS (Percent Bias)
    metrics["pbias"] = 100.0 * np.sum(sim - obs) / np.sum(obs) if np.sum(obs) != 0 else 0

    # Willmott Skill Score
    d_num = np.sum((obs - sim) ** 2)
    d_den = np.sum((np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs))) ** 2)
    metrics["willmott_d"] = 1.0 - d_num / d_den if d_den > 0 else 0.0

    # MAE
    metrics["mae"] = np.mean(np.abs(obs - sim))

    # Sample size
    metrics["n_points"] = n

    return metrics


# ──────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────

def write_csv(output_csv, results):
    """Write extracted results to CSV."""
    if pd is None:
        # Manual CSV writing
        keys = list(results.keys())
        n_rows = max(len(v) for v in results.values() if hasattr(v, "__len__"))

        with open(output_csv, "w") as f:
            f.write(",".join(keys) + "\n")
            for i in range(n_rows):
                row = []
                for k in keys:
                    v = results[k]
                    if hasattr(v, "__len__") and i < len(v):
                        row.append(str(v[i]))
                    else:
                        row.append("")
                f.write(",".join(row) + "\n")
    else:
        df = pd.DataFrame(results)
        df.to_csv(output_csv, index=False)

    print(f"  Written: {output_csv}")


def plot_comparison(output_plot, times, observed, simulated, metrics,
                    variable_name="Water Level", station_name=""):
    """Create comparison plot: observed vs simulated with metrics box."""
    if plt is None:
        print("  WARNING: matplotlib not available, skipping plot")
        return

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))

    # Convert times to datetime if needed
    if isinstance(times[0], str):
        times = [datetime.fromisoformat(t) for t in times]

    n = min(len(times), len(observed), len(simulated))
    t = times[:n]

    ax.plot(t, observed[:n], color="black", linewidth=0.8, label="Observed", alpha=0.8)
    ax.plot(t, simulated[:n], color="#2563EB", linewidth=0.8, label="Simulated", alpha=0.8)

    ax.set_xlabel("Time")
    ax.set_ylabel(f"{variable_name}")
    title = f"{variable_name}"
    if station_name:
        title += f" — {station_name}"
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Metrics box
    if metrics:
        metrics_text = "\n".join([
            f"RMSE = {metrics.get('rmse', 0):.4f}",
            f"R² = {metrics.get('r_squared', 0):.4f}",
            f"NSE = {metrics.get('nse', 0):.4f}",
            f"Bias = {metrics.get('bias', 0):.4f}",
            f"N = {metrics.get('n_points', 0)}",
        ])
        props = dict(boxstyle="round,pad=0.5", facecolor="wheat", alpha=0.8)
        ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
                fontsize=9, verticalalignment="top", horizontalalignment="right",
                bbox=props, fontfamily="monospace")

    fig.tight_layout()
    os.makedirs(os.path.dirname(output_plot) or ".", exist_ok=True)
    fig.savefig(output_plot, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Written: {output_plot}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse Delft3D output and compute validation metrics"
    )
    parser.add_argument("--his_file", help="History output file (_his.nc)")
    parser.add_argument("--map_file", help="Map output file (_map.nc)")
    parser.add_argument("--obs_file", help="Observation CSV (time, value)")
    parser.add_argument("--output_csv", required=True, help="Output CSV path")
    parser.add_argument("--plot", help="Output plot path (.png)")
    parser.add_argument("--variables", nargs="+",
                        help="Variables to extract (default: all available)")
    parser.add_argument("--stations", nargs="+",
                        help="Station names to extract (default: all)")
    parser.add_argument("--timestep", type=int, default=-1,
                        help="Map file timestep to extract (default: last)")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Process
    results = {}
    metrics = {}

    if args.his_file:
        his_results = read_his_file(args.his_file, args.variables, args.stations)
        if his_results:
            results.update(his_results)

    if args.map_file:
        map_results = read_map_file(args.map_file, args.variables, args.timestep)
        if map_results:
            # Map results are spatial, save separately
            map_csv = args.output_csv.replace(".csv", "_map.csv")
            write_csv(map_csv, map_results)

    # Write time series CSV
    if results:
        write_csv(args.output_csv, results)

    # Compare with observations if provided
    if args.obs_file and results:
        print(f"\n[compare] Loading observations: {args.obs_file}")

        if pd is not None:
            obs_df = pd.read_csv(args.obs_file, parse_dates=[0])
            obs_times = obs_df.iloc[:, 0].values
            obs_values = obs_df.iloc[:, 1].values.astype(float)

            # Find matching simulated variable
            sim_cols = [c for c in results if c != "time" and "water_level" in c.lower()]
            if not sim_cols:
                sim_cols = [c for c in results if c != "time"]

            if sim_cols:
                sim_col = sim_cols[0]
                sim_values = np.array(results[sim_col], dtype=float)

                # Align time series (simple: truncate to shorter)
                n = min(len(obs_values), len(sim_values))
                obs_aligned = obs_values[:n]
                sim_aligned = sim_values[:n]

                metrics = compute_metrics(obs_aligned, sim_aligned)
                print(f"\n[metrics] Validation results:")
                for k, v in metrics.items():
                    if isinstance(v, float):
                        print(f"  {k}: {v:.4f}")
                    else:
                        print(f"  {k}: {v}")

                # Plot
                if args.plot:
                    plot_comparison(
                        args.plot,
                        results.get("time", list(range(n))),
                        obs_aligned, sim_aligned,
                        metrics,
                        variable_name=sim_col,
                    )

    # Step 3: Validate outputs
    validate_outputs(args.output_csv, metrics)

    print(f"\n[DONE] Output parsing completed")
    if metrics:
        print(f"  RMSE: {metrics.get('rmse', 'N/A')}")
        print(f"  R²: {metrics.get('r_squared', 'N/A')}")
        print(f"  NSE: {metrics.get('nse', 'N/A')}")


if __name__ == "__main__":
    main()
