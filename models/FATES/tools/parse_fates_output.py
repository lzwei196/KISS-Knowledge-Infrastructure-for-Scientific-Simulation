#!/usr/bin/env python3
"""
parse_fates_output.py — FATES NetCDF History Output Parser

Extracts FATES diagnostic variables from CLM/ELM history files (NetCDF),
computes derived metrics, and exports to CSV and/or plots.

Follows validate → process → validate pattern.

Usage:
    # Extract key variables to CSV
    python parse_fates_output.py \
        --input /path/to/case/run/*.clm2.h0.*.nc \
        --variables FATES_GPP,FATES_LAI,FATES_VEGC \
        --output timeseries.csv

    # Generate time series plot
    python parse_fates_output.py \
        --input /path/to/case/run/*.clm2.h0.*.nc \
        --variables FATES_GPP \
        --plot fates_gpp.png

    # Extract all FATES variables
    python parse_fates_output.py \
        --input /path/to/case/run/*.clm2.h0.*.nc \
        --all-fates --output all_fates.csv

    # Compare with observations
    python parse_fates_output.py \
        --input /path/to/case/run/*.clm2.h0.*.nc \
        --variables FATES_GPP \
        --obs-file observations.csv --obs-column GPP_gC_m2_day \
        --metrics --output comparison.csv --plot comparison.png
"""

import argparse
import glob
import json
import os
import sys
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# ─── FATES output variable metadata ─────────────────────────────────────────
FATES_VARIABLES = {
    # Carbon pools (kgC/m²)
    "FATES_VEGC":      {"units": "kgC/m²", "description": "Total vegetation carbon",
                        "category": "carbon_pool"},
    "FATES_LEAFC":     {"units": "kgC/m²", "description": "Leaf carbon",
                        "category": "carbon_pool"},
    "FATES_SAPWOODC":  {"units": "kgC/m²", "description": "Sapwood carbon",
                        "category": "carbon_pool"},
    "FATES_STRUCTC":   {"units": "kgC/m²", "description": "Structural (dead) wood carbon",
                        "category": "carbon_pool"},
    "FATES_STOREC":    {"units": "kgC/m²", "description": "Storage carbon",
                        "category": "carbon_pool"},
    "FATES_FROOTC":    {"units": "kgC/m²", "description": "Fine root carbon",
                        "category": "carbon_pool"},
    "FATES_LITTERC":   {"units": "kgC/m²", "description": "Total litter carbon",
                        "category": "carbon_pool"},
    "FATES_CWDC":      {"units": "kgC/m²", "description": "Coarse woody debris carbon",
                        "category": "carbon_pool"},

    # Carbon fluxes (kgC/m²/s → convert to gC/m²/day for analysis)
    "FATES_GPP":       {"units": "kgC/m²/s", "description": "Gross primary production",
                        "category": "carbon_flux",
                        "convert_to": {"target": "gC/m²/day", "factor": 1000 * 86400}},
    "FATES_NPP":       {"units": "kgC/m²/s", "description": "Net primary production",
                        "category": "carbon_flux",
                        "convert_to": {"target": "gC/m²/day", "factor": 1000 * 86400}},
    "FATES_AUTORESP":  {"units": "kgC/m²/s", "description": "Autotrophic respiration",
                        "category": "carbon_flux",
                        "convert_to": {"target": "gC/m²/day", "factor": 1000 * 86400}},

    # Structure
    "FATES_LAI":       {"units": "m²/m²", "description": "Leaf area index",
                        "category": "structure"},
    "FATES_NPLANT":    {"units": "stems/m²", "description": "Plant number density",
                        "category": "structure",
                        "convert_to": {"target": "stems/ha", "factor": 10000}},
    "FATES_CANOPY_AREA": {"units": "m²/m²", "description": "Canopy area fraction",
                          "category": "structure"},

    # Mortality and recruitment
    "FATES_MORTALITY":   {"units": "stems/m²/yr", "description": "Total mortality rate",
                          "category": "demographics"},
    "FATES_RECRUITMENT": {"units": "stems/m²/yr", "description": "Recruitment rate",
                          "category": "demographics"},

    # Fire
    "FATES_DISTURBANCE_RATE_FIRE": {"units": "fraction/yr",
                                     "description": "Fire disturbance rate",
                                     "category": "disturbance"},
    "FATES_FIRE_INTENSITY": {"units": "kW/m", "description": "Fire intensity",
                              "category": "disturbance"},
}

# ─── Unit conversion factors ────────────────────────────────────────────────
UNIT_CONVERSIONS = {
    "kgC/m²/s_to_gC/m²/day": 1000.0 * 86400.0,
    "kgC/m²/s_to_tC/ha/yr": 1000.0 * 86400.0 * 365.0 * 10000.0 / 1e6,
    "stems/m²_to_stems/ha": 10000.0,
}


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate inputs."""
    errors = []

    # Expand glob patterns for input files
    input_files = []
    for pattern in args.input:
        matches = sorted(glob.glob(pattern))
        input_files.extend(matches)

    if not input_files:
        errors.append(f"No input files found matching: {args.input}")

    # Store resolved files
    args._input_files = input_files

    # Validate variable names
    if args.variables and not args.all_fates:
        for var in args.variables.split(","):
            var = var.strip()
            if var not in FATES_VARIABLES:
                print(f"Warning: Variable '{var}' not in known FATES variables. "
                      f"Will attempt extraction anyway.", file=sys.stderr)

    # Validate observation file
    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def load_netcdf_timeseries(input_files: List[str],
                            variables: List[str]) -> Dict[str, Any]:
    """Load FATES variables from NetCDF history files."""
    try:
        import xarray as xr
    except ImportError:
        try:
            import netCDF4 as nc
            return _load_with_netcdf4(input_files, variables)
        except ImportError:
            print("Error: Neither xarray nor netCDF4 available.", file=sys.stderr)
            sys.exit(1)

    # Use xarray for multi-file loading
    ds = xr.open_mfdataset(input_files, combine="by_coords",
                           data_vars="minimal", coords="minimal",
                           compat="override")

    result = {
        "time": ds["time"].values,
        "variables": {},
        "metadata": {
            "n_files": len(input_files),
            "time_range": [str(ds["time"].values[0]),
                           str(ds["time"].values[-1])],
            "n_timesteps": len(ds["time"]),
        },
    }

    for var in variables:
        if var in ds:
            data = ds[var].values
            # Handle multi-dimensional (spatial) data — take grid mean
            if data.ndim > 1:
                data = np.nanmean(data, axis=tuple(range(1, data.ndim)))
            result["variables"][var] = {
                "data": data,
                "units": ds[var].attrs.get("units", "unknown"),
                "long_name": ds[var].attrs.get("long_name", var),
            }
        else:
            print(f"  Warning: Variable '{var}' not found in dataset.",
                  file=sys.stderr)

    ds.close()
    return result


def _load_with_netcdf4(input_files: List[str],
                        variables: List[str]) -> Dict[str, Any]:
    """Fallback loader using netCDF4 directly."""
    import netCDF4 as nc

    all_times = []
    all_data = {v: [] for v in variables}

    for fpath in sorted(input_files):
        ds = nc.Dataset(fpath, "r")
        time_var = ds.variables.get("time")
        if time_var is not None:
            times = nc.num2date(time_var[:], time_var.units,
                                calendar=time_var.calendar)
            all_times.extend(times)

        for var in variables:
            if var in ds.variables:
                data = ds.variables[var][:]
                if data.ndim > 1:
                    data = np.nanmean(data, axis=tuple(range(1, data.ndim)))
                all_data[var].extend(data.tolist())
        ds.close()

    result = {
        "time": all_times,
        "variables": {},
        "metadata": {
            "n_files": len(input_files),
            "n_timesteps": len(all_times),
        },
    }

    for var in variables:
        if all_data[var]:
            result["variables"][var] = {
                "data": np.array(all_data[var]),
                "units": FATES_VARIABLES.get(var, {}).get("units", "unknown"),
                "long_name": FATES_VARIABLES.get(var, {}).get("description", var),
            }

    return result


def apply_unit_conversions(data: Dict[str, Any],
                            convert: bool = True) -> Dict[str, Any]:
    """Apply standard unit conversions for analysis-friendly units."""
    if not convert:
        return data

    for var_name, var_data in data["variables"].items():
        meta = FATES_VARIABLES.get(var_name, {})
        conv = meta.get("convert_to")
        if conv:
            var_data["data"] = var_data["data"] * conv["factor"]
            var_data["original_units"] = var_data["units"]
            var_data["units"] = conv["target"]

    return data


def compute_metrics(simulated: np.ndarray,
                    observed: np.ndarray) -> Dict[str, float]:
    """Compute standard performance metrics."""
    # Remove NaN pairs
    mask = ~(np.isnan(simulated) | np.isnan(observed))
    sim = simulated[mask]
    obs = observed[mask]

    if len(sim) < 3:
        return {"error": "Too few valid data points for metrics"}

    # Mean values
    sim_mean = np.mean(sim)
    obs_mean = np.mean(obs)

    # Pearson correlation
    r = np.corrcoef(sim, obs)[0, 1] if len(sim) > 1 else 0.0

    # Nash-Sutcliffe Efficiency
    ss_res = np.sum((sim - obs) ** 2)
    ss_tot = np.sum((obs - obs_mean) ** 2)
    nse = 1.0 - ss_res / ss_tot if ss_tot > 0 else -999

    # Percent Bias
    pbias = 100.0 * np.sum(sim - obs) / np.sum(obs) if np.sum(obs) != 0 else 0

    # RMSE
    rmse = np.sqrt(np.mean((sim - obs) ** 2))

    # KGE (Kling-Gupta Efficiency)
    r_val = r
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 1.0
    beta = sim_mean / obs_mean if obs_mean != 0 else 1.0
    kge = 1.0 - np.sqrt((r_val - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    return {
        "r": round(float(r), 4),
        "r_squared": round(float(r ** 2), 4),
        "nse": round(float(nse), 4),
        "rmse": round(float(rmse), 4),
        "pbias_pct": round(float(pbias), 2),
        "kge": round(float(kge), 4),
        "mean_sim": round(float(sim_mean), 4),
        "mean_obs": round(float(obs_mean), 4),
        "n_points": int(len(sim)),
    }


def export_to_csv(data: Dict[str, Any], output_path: str) -> None:
    """Export time series data to CSV."""
    import csv

    times = data["time"]
    variables = data["variables"]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = ["time"]
        units_row = [""]
        for var_name, var_data in variables.items():
            header.append(var_name)
            units_row.append(f"[{var_data['units']}]")
        writer.writerow(header)
        writer.writerow(units_row)

        # Data rows
        for i, t in enumerate(times):
            row = [str(t)]
            for var_name, var_data in variables.items():
                if i < len(var_data["data"]):
                    val = var_data["data"][i]
                    row.append(f"{val:.6g}" if not np.isnan(val) else "NaN")
                else:
                    row.append("NaN")
            writer.writerow(row)

    print(f"  CSV written: {output_path} ({len(times)} rows)", file=sys.stderr)


def create_plot(data: Dict[str, Any], plot_path: str,
                obs_data: Optional[Dict[str, np.ndarray]] = None,
                metrics: Optional[Dict[str, float]] = None) -> None:
    """Create time series plot with optional observations."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("Warning: matplotlib not available, skipping plot.", file=sys.stderr)
        return

    variables = data["variables"]
    n_vars = len(variables)
    fig, axes = plt.subplots(n_vars, 1, figsize=(12, 4 * n_vars), squeeze=False)

    times = data["time"]

    for i, (var_name, var_data) in enumerate(variables.items()):
        ax = axes[i, 0]
        values = var_data["data"]

        # Simulated
        ax.plot(times[:len(values)], values, color="#2563EB",
                linewidth=1.2, label="FATES Simulated", alpha=0.9)

        # Observations (if available)
        if obs_data and var_name in obs_data:
            obs = obs_data[var_name]
            obs_times = obs.get("time", times[:len(obs.get("data", []))])
            ax.plot(obs_times, obs["data"], color="black",
                    linewidth=1.0, linestyle="--", label="Observed", alpha=0.8)

        ax.set_ylabel(f"{var_name}\n[{var_data['units']}]", fontsize=10)
        ax.set_title(var_data.get("long_name", var_name), fontsize=11)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)

        # Metrics box
        if metrics and var_name in metrics:
            m = metrics[var_name]
            text = "\n".join([f"{k}: {v}" for k, v in m.items()
                              if k not in ("n_points",)])
            ax.text(0.98, 0.95, text, transform=ax.transAxes,
                    fontsize=8, verticalalignment="top",
                    horizontalalignment="right",
                    bbox=dict(boxstyle="round,pad=0.3",
                              facecolor="white", alpha=0.8))

    plt.tight_layout()
    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Plot saved: {plot_path}", file=sys.stderr)


def validate_outputs(data: Dict[str, Any]) -> List[str]:
    """Stage 3: Validate extracted output data."""
    warnings = []

    for var_name, var_data in data.get("variables", {}).items():
        values = var_data.get("data")
        if values is None or len(values) == 0:
            warnings.append(f"No data extracted for {var_name}")
            continue

        arr = np.array(values)

        # Check for all-NaN
        if np.all(np.isnan(arr)):
            warnings.append(f"{var_name}: All values are NaN — variable may not be active")
            continue

        # Check for unrealistic values
        valid = arr[~np.isnan(arr)]

        if var_name in ("FATES_GPP", "FATES_NPP"):
            # After conversion to gC/m²/day, GPP should be 0-50
            if np.max(valid) > 50:
                warnings.append(
                    f"{var_name}: Max value {np.max(valid):.2f} {var_data['units']} "
                    "seems high — check unit conversion")
            if np.min(valid) < -1:
                warnings.append(
                    f"{var_name}: Negative values detected (min={np.min(valid):.4f}) "
                    "— GPP/NPP should be ≥ 0 in most cases")

        elif var_name == "FATES_LAI":
            if np.max(valid) > 15:
                warnings.append(
                    f"FATES_LAI max {np.max(valid):.2f} exceeds typical range (0-12)")

        elif var_name == "FATES_VEGC":
            if np.max(valid) > 100:
                warnings.append(
                    f"FATES_VEGC max {np.max(valid):.2f} kgC/m² seems extremely high "
                    "(typical tropical forest: 10-25 kgC/m²)")

        elif var_name == "FATES_NPLANT":
            if np.max(valid) > 5:
                warnings.append(
                    f"FATES_NPLANT max {np.max(valid):.4f} stems/m² = "
                    f"{np.max(valid)*10000:.0f} stems/ha — seems very high")

    # Check time coverage
    n_timesteps = data.get("metadata", {}).get("n_timesteps", 0)
    if n_timesteps < 12:
        warnings.append(f"Only {n_timesteps} timesteps — may be insufficient for analysis")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse FATES NetCDF history output to CSV/plots")
    parser.add_argument("--input", nargs="+", required=True,
                        help="Input NetCDF file(s) or glob pattern(s)")
    parser.add_argument("--variables",
                        help="Comma-separated variable names (e.g., FATES_GPP,FATES_LAI)")
    parser.add_argument("--all-fates", action="store_true",
                        help="Extract all known FATES variables")
    parser.add_argument("--output", help="Output CSV file path")
    parser.add_argument("--plot", help="Output plot file path (PNG)")
    parser.add_argument("--obs-file", help="Observation CSV file for comparison")
    parser.add_argument("--obs-column", help="Column name in obs file")
    parser.add_argument("--obs-time-column", default="time",
                        help="Time column in obs file (default: time)")
    parser.add_argument("--metrics", action="store_true",
                        help="Compute performance metrics against observations")
    parser.add_argument("--convert-units", action="store_true", default=True,
                        help="Apply standard unit conversions (default: True)")
    parser.add_argument("--no-convert", action="store_true",
                        help="Keep original units (no conversion)")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Determine variables to extract
    if args.all_fates:
        variables = list(FATES_VARIABLES.keys())
    elif args.variables:
        variables = [v.strip() for v in args.variables.split(",")]
    else:
        variables = ["FATES_GPP", "FATES_LAI", "FATES_VEGC", "FATES_NPP"]

    # Stage 2: Process
    print(f"Loading {len(args._input_files)} file(s)...", file=sys.stderr)
    data = load_netcdf_timeseries(args._input_files, variables)

    # Unit conversions
    if not args.no_convert:
        data = apply_unit_conversions(data)

    # Load observations if provided
    obs_data = None
    all_metrics = {}
    if args.obs_file and args.obs_column:
        try:
            import pandas as pd
            obs_df = pd.read_csv(args.obs_file, parse_dates=[args.obs_time_column])
            if args.obs_column in obs_df.columns:
                obs_data = {
                    variables[0]: {
                        "time": obs_df[args.obs_time_column].values,
                        "data": obs_df[args.obs_column].values,
                    }
                }
                if args.metrics and variables[0] in data["variables"]:
                    sim_values = data["variables"][variables[0]]["data"]
                    obs_values = obs_df[args.obs_column].values
                    n = min(len(sim_values), len(obs_values))
                    all_metrics[variables[0]] = compute_metrics(
                        sim_values[:n], obs_values[:n])
        except Exception as e:
            print(f"Warning: Could not load observations: {e}", file=sys.stderr)

    # Export CSV
    if args.output:
        export_to_csv(data, args.output)

    # Create plot
    if args.plot:
        create_plot(data, args.plot, obs_data, all_metrics)

    # Stage 3: Validate outputs
    warnings = validate_outputs(data)

    # Summary
    summary = {
        "status": "success",
        "n_files": len(args._input_files),
        "n_timesteps": data["metadata"]["n_timesteps"],
        "variables_extracted": list(data["variables"].keys()),
        "output_csv": args.output,
        "output_plot": args.plot,
        "metrics": all_metrics if all_metrics else None,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))

    if warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
