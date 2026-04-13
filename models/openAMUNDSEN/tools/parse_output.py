#!/usr/bin/env python3
"""
parse_output.py — Extract openAMUNDSEN results to analysis-ready CSV and compute
summary statistics.

openAMUNDSEN outputs:
  - Point time series: NetCDF or CSV with variables like swe, snow_depth, temp, etc.
  - Gridded fields: NetCDF, GeoTIFF, or ASCII Grid with spatial data

This tool:
  1. Reads point output NetCDF/CSV files
  2. Extracts key snow/hydro variables
  3. Computes summary statistics (seasonal peaks, melt dates, totals)
  4. Exports to flat CSV for analysis
  5. Optionally computes validation metrics against observations

CRITICAL: openAMUNDSEN variable naming uses dot notation internally
(e.g., snow.swe) but output files use underscores (e.g., swe).

Usage:
  python parse_output.py --results-dir ./output --format csv
  python parse_output.py --results-dir ./output --point station_A --variables swe,snow_depth,temp
  python parse_output.py --results-dir ./output --observed obs.csv --metrics nse,kge,rmse
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


# Default variables to extract
DEFAULT_VARIABLES = [
    "swe", "snow_depth", "snow_melt", "snow_runoff",
    "temp", "precip", "snowfall", "rainfall",
    "sw_in", "lw_in", "surface_temp", "surface_albedo",
]

# Variable name mappings (output name → description and units)
VARIABLE_INFO = {
    "swe": {"long_name": "Snow Water Equivalent", "units": "kg m-2"},
    "snow_depth": {"long_name": "Snow Depth", "units": "m"},
    "snow_melt": {"long_name": "Snowmelt", "units": "kg m-2"},
    "snow_runoff": {"long_name": "Snow Runoff", "units": "kg m-2"},
    "snow_temp": {"long_name": "Snow Temperature", "units": "K"},
    "snow_density": {"long_name": "Snow Density", "units": "kg m-3"},
    "snow_sublimation": {"long_name": "Snow Sublimation", "units": "kg m-2"},
    "temp": {"long_name": "Air Temperature", "units": "K"},
    "precip": {"long_name": "Precipitation", "units": "kg m-2"},
    "snowfall": {"long_name": "Snowfall", "units": "kg m-2"},
    "rainfall": {"long_name": "Rainfall", "units": "kg m-2"},
    "sw_in": {"long_name": "Incoming Shortwave Radiation", "units": "W m-2"},
    "lw_in": {"long_name": "Incoming Longwave Radiation", "units": "W m-2"},
    "surface_temp": {"long_name": "Surface Temperature", "units": "K"},
    "surface_albedo": {"long_name": "Surface Albedo", "units": "-"},
    "sens_heat_flux": {"long_name": "Sensible Heat Flux", "units": "W m-2"},
    "lat_heat_flux": {"long_name": "Latent Heat Flux", "units": "W m-2"},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.results_dir):
        errors.append(f"Results directory not found: {args.results_dir}")

    if args.observed and not os.path.exists(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return True


def read_point_output_netcdf(results_dir, point_name=None):
    """Read point output from NetCDF files."""
    try:
        import xarray as xr
    except ImportError:
        print("ERROR: xarray required for NetCDF reading", file=sys.stderr)
        sys.exit(1)

    nc_files = sorted([f for f in os.listdir(results_dir) if f.endswith(".nc")])
    if not nc_files:
        return None

    datasets = {}
    for nc_file in nc_files:
        path = os.path.join(results_dir, nc_file)
        try:
            ds = xr.open_dataset(path)

            # Check if this is a point output file (has 'time' and optionally 'point' dims)
            if "time" in ds.dims:
                name = os.path.splitext(nc_file)[0]
                datasets[name] = ds
        except Exception as e:
            print(f"WARNING: Cannot read {nc_file}: {e}", file=sys.stderr)

    if not datasets:
        return None

    # If point_name specified, filter
    if point_name and point_name in datasets:
        return {point_name: datasets[point_name]}

    return datasets


def read_point_output_csv(results_dir, point_name=None):
    """Read point output from CSV files."""
    csv_files = sorted([f for f in os.listdir(results_dir) if f.endswith(".csv")])
    if not csv_files:
        return None

    datasets = {}
    for csv_file in csv_files:
        path = os.path.join(results_dir, csv_file)
        try:
            df = pd.read_csv(path, parse_dates=[0], index_col=0)
            df.index.name = "time"
            name = os.path.splitext(csv_file)[0]
            datasets[name] = df
        except Exception as e:
            print(f"WARNING: Cannot read {csv_file}: {e}", file=sys.stderr)

    if point_name and point_name in datasets:
        return {point_name: datasets[point_name]}

    return datasets


def extract_variables(data, variables):
    """Extract specified variables from dataset."""
    if isinstance(data, pd.DataFrame):
        available = [v for v in variables if v in data.columns]
        return data[available]
    else:
        # xarray Dataset
        available = [v for v in variables if v in data.data_vars]
        df = data[available].to_dataframe()
        return df


def compute_snow_statistics(df):
    """Compute summary snow statistics from time series."""
    stats = {}

    if "swe" in df.columns:
        swe = df["swe"].dropna()
        if len(swe) > 0:
            stats["peak_swe_kg_m2"] = round(float(swe.max()), 1)
            stats["peak_swe_date"] = str(swe.idxmax().date()) if not swe.empty else None
            stats["mean_swe_kg_m2"] = round(float(swe.mean()), 1)

            # Snow-free date (last date SWE drops to 0 after peak)
            peak_idx = swe.idxmax()
            post_peak = swe[peak_idx:]
            zero_swe = post_peak[post_peak <= 0.1]
            if len(zero_swe) > 0:
                stats["snowfree_date"] = str(zero_swe.index[0].date())

    if "snow_depth" in df.columns:
        depth = df["snow_depth"].dropna()
        if len(depth) > 0:
            stats["peak_depth_m"] = round(float(depth.max()), 3)
            stats["peak_depth_date"] = str(depth.idxmax().date()) if not depth.empty else None

    if "snow_melt" in df.columns or "snowmelt" in df.columns:
        melt_col = "snow_melt" if "snow_melt" in df.columns else "snowmelt"
        melt = df[melt_col].dropna()
        if len(melt) > 0:
            stats["total_melt_kg_m2"] = round(float(melt.sum()), 1)

    if "precip" in df.columns and "snowfall" in df.columns:
        precip = df["precip"].dropna().sum()
        snowfall = df["snowfall"].dropna().sum()
        if precip > 0:
            stats["snow_fraction"] = round(float(snowfall / precip), 3)
            stats["total_precip_kg_m2"] = round(float(precip), 1)
            stats["total_snowfall_kg_m2"] = round(float(snowfall), 1)

    if "temp" in df.columns:
        temp = df["temp"].dropna()
        if len(temp) > 0:
            stats["mean_temp_K"] = round(float(temp.mean()), 1)
            stats["mean_temp_C"] = round(float(temp.mean() - 273.15), 1)

    return stats


def compute_metrics(simulated, observed, metric_names):
    """Compute validation metrics between simulated and observed data."""
    # Align time series
    common_idx = simulated.index.intersection(observed.index)
    if len(common_idx) == 0:
        return {"error": "No overlapping dates between simulated and observed"}

    sim = simulated.loc[common_idx].values.astype(float)
    obs = observed.loc[common_idx].values.astype(float)

    # Remove NaN pairs
    valid = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[valid]
    obs = obs[valid]

    if len(sim) < 3:
        return {"error": f"Only {len(sim)} valid data pairs — need at least 3"}

    metrics = {"n_pairs": int(len(sim))}

    if "rmse" in metric_names or "all" in metric_names:
        metrics["rmse"] = round(float(np.sqrt(np.mean((sim - obs) ** 2))), 4)

    if "mae" in metric_names or "all" in metric_names:
        metrics["mae"] = round(float(np.mean(np.abs(sim - obs))), 4)

    if "bias" in metric_names or "all" in metric_names:
        metrics["bias"] = round(float(np.mean(sim - obs)), 4)

    if "pbias" in metric_names or "all" in metric_names:
        obs_sum = np.sum(obs)
        if obs_sum != 0:
            metrics["pbias_percent"] = round(float(100 * np.sum(sim - obs) / obs_sum), 2)

    if "r" in metric_names or "all" in metric_names:
        if np.std(sim) > 0 and np.std(obs) > 0:
            metrics["r"] = round(float(np.corrcoef(sim, obs)[0, 1]), 4)

    if "nse" in metric_names or "all" in metric_names:
        ss_res = np.sum((obs - sim) ** 2)
        ss_tot = np.sum((obs - np.mean(obs)) ** 2)
        if ss_tot > 0:
            metrics["nse"] = round(float(1 - ss_res / ss_tot), 4)

    if "kge" in metric_names or "all" in metric_names:
        if np.std(sim) > 0 and np.std(obs) > 0:
            r = np.corrcoef(sim, obs)[0, 1]
            alpha = np.std(sim) / np.std(obs)
            beta = np.mean(sim) / np.mean(obs)
            kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
            metrics["kge"] = round(float(kge), 4)

    return metrics


def validate_outputs(result):
    """Validate parsed output data."""
    warnings = result.get("warnings", [])

    for point_name, stats in result.get("statistics", {}).items():
        if "peak_swe_kg_m2" in stats:
            if stats["peak_swe_kg_m2"] > 5000:
                warnings.append(f"{point_name}: Peak SWE={stats['peak_swe_kg_m2']} kg/m2 — unrealistically high")
            if stats["peak_swe_kg_m2"] < 1:
                warnings.append(f"{point_name}: Peak SWE={stats['peak_swe_kg_m2']} kg/m2 — suspiciously low")

        if "mean_temp_K" in stats:
            if stats["mean_temp_K"] < 230:
                warnings.append(f"{point_name}: Mean temp={stats['mean_temp_K']}K — verify units")
            if stats["mean_temp_K"] > 310:
                warnings.append(f"{point_name}: Mean temp={stats['mean_temp_K']}K — unusually warm for snow model")

    if warnings:
        result["warnings"] = warnings
        if result["status"] == "success":
            result["status"] = "warning"

    return result


def process(args):
    """Main processing: read outputs, extract variables, compute stats."""
    variables = args.variables.split(",") if args.variables else DEFAULT_VARIABLES

    # Read output data
    datasets = None
    nc_datasets = read_point_output_netcdf(args.results_dir, args.point)
    if nc_datasets:
        datasets = nc_datasets
        print(f"Read {len(datasets)} NetCDF output files", file=sys.stderr)
    else:
        csv_datasets = read_point_output_csv(args.results_dir, args.point)
        if csv_datasets:
            datasets = csv_datasets
            print(f"Read {len(datasets)} CSV output files", file=sys.stderr)

    if not datasets:
        result = {"status": "error", "errors": ["No output data found in results directory"]}
        print(json.dumps(result, indent=2))
        return result

    all_stats = {}
    exported_files = []

    for point_name, data in datasets.items():
        print(f"Processing: {point_name}", file=sys.stderr)

        df = extract_variables(data, variables)

        # Compute statistics
        stats = compute_snow_statistics(df)
        all_stats[point_name] = stats

        # Export to CSV
        if args.export_csv:
            export_dir = args.export_csv
            os.makedirs(export_dir, exist_ok=True)
            export_path = os.path.join(export_dir, f"{point_name}_parsed.csv")
            df.to_csv(export_path, index=True, date_format="%Y-%m-%d %H:%M")
            exported_files.append(export_path)
            print(f"  Exported: {export_path}", file=sys.stderr)

    # Compute validation metrics if observed data provided
    metrics = {}
    if args.observed:
        obs_df = pd.read_csv(args.observed, parse_dates=[0], index_col=0)
        metric_names = args.metrics.split(",") if args.metrics else ["all"]

        for point_name, data in datasets.items():
            df = extract_variables(data, variables)
            # Match variable names between sim and obs
            for col in obs_df.columns:
                if col in df.columns:
                    m = compute_metrics(df[col], obs_df[col], metric_names)
                    metrics[f"{point_name}.{col}"] = m

    result = {
        "status": "success",
        "points_processed": len(datasets),
        "variables_extracted": variables,
        "statistics": all_stats,
        "exported_files": exported_files,
        "warnings": [],
    }

    if metrics:
        result["validation_metrics"] = metrics

    result = validate_outputs(result)
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse openAMUNDSEN output and compute statistics"
    )
    parser.add_argument("--results-dir", required=True, help="Model results directory")
    parser.add_argument("--point", help="Specific output point name to extract")
    parser.add_argument("--variables", help="Comma-separated variable names to extract")
    parser.add_argument("--export-csv", help="Directory to export parsed CSV files")
    parser.add_argument("--observed", help="Path to observed data CSV for validation")
    parser.add_argument("--metrics", help="Comma-separated metric names (nse,kge,rmse,mae,bias,pbias,r,all)")

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
