#!/usr/bin/env python3
"""
output_parser.py — Parse MOM6 diagnostic NetCDF output and ocean.stats to CSV.

Extracts key variables (SST, SSS, SSH, MLD, KE), computes domain-averaged
timeseries, and calculates validation metrics against observations.

Pipeline stage: S7 (Output Analysis)
Pattern: validate → process → validate
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Key diagnostic variables to extract
TARGET_VARS = {
    "temp":    {"long_name": "Temperature",           "units": "degC",  "surface_only": False},
    "salt":    {"long_name": "Salinity",              "units": "PSU",   "surface_only": False},
    "ssh":     {"long_name": "Sea surface height",    "units": "m",     "surface_only": True},
    "SST":     {"long_name": "Sea surface temperature","units": "degC", "surface_only": True},
    "SSS":     {"long_name": "Sea surface salinity",  "units": "PSU",   "surface_only": True},
    "u":       {"long_name": "Zonal velocity",        "units": "m/s",   "surface_only": False},
    "v":       {"long_name": "Meridional velocity",   "units": "m/s",   "surface_only": False},
    "e":       {"long_name": "Interface heights",     "units": "m",     "surface_only": False},
    "h":       {"long_name": "Layer thickness",       "units": "m",     "surface_only": False},
    "KE":      {"long_name": "Kinetic energy",        "units": "m2/s2", "surface_only": False},
    "MLD_003": {"long_name": "Mixed layer depth",     "units": "m",     "surface_only": True},
}

# Physical bounds for quality check
VALID_RANGES = {
    "temp": (-3.0, 42.0),
    "salt": (-0.1, 50.0),
    "ssh":  (-15.0, 15.0),
    "SST":  (-3.0, 42.0),
    "SSS":  (-0.1, 50.0),
    "u":    (-8.0, 8.0),
    "v":    (-8.0, 8.0),
    "KE":   (0.0, 25.0),
    "MLD_003": (0.0, 6000.0),
}


def validate_input(diag_dir: str, stats_file: str = None) -> dict:
    """Pre-validate: find diagnostic NetCDF files and ocean.stats."""
    info = {"diag_files": [], "stats_file": None, "valid": True, "warnings": []}

    if not os.path.isdir(diag_dir):
        log.error(f"Diagnostic directory not found: {diag_dir}")
        sys.exit(1)

    # Find NetCDF diagnostic files
    nc_files = sorted([
        os.path.join(diag_dir, f) for f in os.listdir(diag_dir)
        if f.endswith(".nc") and not f.startswith("MOM.res")
    ])

    if nc_files:
        info["diag_files"] = nc_files
        log.info(f"Found {len(nc_files)} diagnostic NetCDF files")
    else:
        info["warnings"].append("No diagnostic NetCDF files found")

    # Find ocean.stats
    if stats_file and os.path.isfile(stats_file):
        info["stats_file"] = stats_file
    else:
        default_stats = os.path.join(diag_dir, "ocean.stats")
        if os.path.isfile(default_stats):
            info["stats_file"] = default_stats
        else:
            info["warnings"].append("ocean.stats not found")

    if not nc_files and not info["stats_file"]:
        log.error("No diagnostic files or ocean.stats found — nothing to parse")
        info["valid"] = False

    # Scan first NetCDF for available variables
    if nc_files:
        try:
            import netCDF4
            ds = netCDF4.Dataset(nc_files[0], "r")
            available = list(ds.variables.keys())
            found = [v for v in TARGET_VARS if v in available]
            log.info(f"Variables in {os.path.basename(nc_files[0])}: {found}")
            info["available_vars"] = found
            info["all_vars"] = available
            ds.close()
        except Exception as e:
            info["warnings"].append(f"Error reading first file: {e}")

    for w in info["warnings"]:
        log.warning(w)

    return info


def parse_ocean_stats(stats_file: str) -> list:
    """Parse ocean.stats file into list of timestep records."""
    records = []
    with open(stats_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("Step") or line.startswith("-"):
                continue

            parts = {}
            # Extract step number
            step_m = re.match(r"\s*(\d+),", line)
            if step_m:
                parts["step"] = int(step_m.group(1))

            # Extract day
            day_m = re.search(r",\s*([\d.]+),", line)
            if day_m:
                parts["day"] = float(day_m.group(1))

            # Extract energy
            en_m = re.search(r"En\s+([\d.Ee+-]+)", line)
            if en_m:
                parts["energy"] = float(en_m.group(1))

            # Extract CFL
            cfl_m = re.search(r"CFL\s+([\d.Ee+-]+)", line)
            if cfl_m:
                parts["cfl"] = float(cfl_m.group(1))

            # Extract sea level
            sl_m = re.search(r"SL\s+([\d.Ee+-]+)", line)
            if sl_m:
                parts["sea_level"] = float(sl_m.group(1))

            # Extract truncations
            tr_m = re.search(r"Truncs\s+(\d+)", line)
            if tr_m:
                parts["truncations"] = int(tr_m.group(1))

            if parts:
                records.append(parts)

    log.info(f"Parsed {len(records)} timestep records from ocean.stats")
    return records


def extract_timeseries(diag_files: list, variables: list = None,
                       lat_range: tuple = None, lon_range: tuple = None) -> dict:
    """Extract domain-averaged timeseries from diagnostic NetCDF files."""
    import netCDF4

    if variables is None:
        variables = list(TARGET_VARS.keys())

    timeseries = {v: {"time": [], "mean": [], "min": [], "max": [], "std": []}
                  for v in variables}

    for fpath in diag_files:
        try:
            ds = netCDF4.Dataset(fpath, "r")
        except Exception as e:
            log.warning(f"Cannot open {fpath}: {e}")
            continue

        available = list(ds.variables.keys())

        # Get time
        time_var = None
        for tn in ["time", "Time", "TIME", "t"]:
            if tn in available:
                time_var = tn
                break

        if time_var:
            time_data = ds.variables[time_var][:]
            time_units = getattr(ds.variables[time_var], "units", "days")
        else:
            time_data = np.arange(1)
            time_units = "unknown"

        # Get spatial coords for subsetting
        lat_idx = lon_idx = None
        if lat_range or lon_range:
            for ln in ["lat", "yh", "latitude", "y"]:
                if ln in available:
                    lat_data = ds.variables[ln][:]
                    if lat_range:
                        lat_idx = np.where((lat_data >= lat_range[0]) &
                                           (lat_data <= lat_range[1]))[0]
                    break
            for ln in ["lon", "xh", "longitude", "x"]:
                if ln in available:
                    lon_data = ds.variables[ln][:]
                    if lon_range:
                        lon_idx = np.where((lon_data >= lon_range[0]) &
                                           (lon_data <= lon_range[1]))[0]
                    break

        for vname in variables:
            if vname not in available:
                continue

            data = ds.variables[vname][:]

            # Subset spatially
            if data.ndim >= 3 and lat_idx is not None:
                # Assume dims are (time, [z], lat, lon)
                if data.ndim == 4:
                    data = data[:, :, lat_idx, :]
                elif data.ndim == 3:
                    data = data[:, lat_idx, :]
            if data.ndim >= 3 and lon_idx is not None:
                if data.ndim == 4:
                    data = data[:, :, :, lon_idx]
                elif data.ndim == 3:
                    data = data[:, :, lon_idx]

            # Handle masked arrays
            if hasattr(data, "filled"):
                data = data.filled(np.nan)

            # Surface extract for 3D+ fields
            if TARGET_VARS.get(vname, {}).get("surface_only", False) is False and data.ndim == 4:
                data = data[:, 0, :, :]  # Top layer

            # Compute spatial statistics per timestep
            for t in range(len(time_data)):
                if data.ndim == 1:
                    # Scalar timeseries
                    snapshot = data[t] if t < len(data) else np.nan
                    vals = np.array([snapshot])
                elif t < data.shape[0]:
                    snapshot = data[t]
                    vals = snapshot[~np.isnan(snapshot)] if np.any(~np.isnan(snapshot)) else np.array([np.nan])
                else:
                    vals = np.array([np.nan])

                timeseries[vname]["time"].append(float(time_data[t]))
                timeseries[vname]["mean"].append(float(np.nanmean(vals)))
                timeseries[vname]["min"].append(float(np.nanmin(vals)))
                timeseries[vname]["max"].append(float(np.nanmax(vals)))
                timeseries[vname]["std"].append(float(np.nanstd(vals)))

        ds.close()

    # Remove empty variables
    timeseries = {k: v for k, v in timeseries.items() if v["time"]}
    log.info(f"Extracted timeseries for {len(timeseries)} variables")
    return timeseries


def compute_metrics(simulated: np.ndarray, observed: np.ndarray) -> dict:
    """Compute validation metrics: RMSE, bias, correlation, NSE."""
    mask = ~(np.isnan(simulated) | np.isnan(observed))
    sim = simulated[mask]
    obs = observed[mask]

    if len(sim) < 2:
        return {"error": "Insufficient non-NaN data points"}

    residual = sim - obs
    rmse = float(np.sqrt(np.mean(residual**2)))
    bias = float(np.mean(residual))
    mae = float(np.mean(np.abs(residual)))

    # Correlation
    if np.std(sim) > 0 and np.std(obs) > 0:
        r = float(np.corrcoef(sim, obs)[0, 1])
    else:
        r = 0.0

    # Nash-Sutcliffe Efficiency
    ss_res = np.sum(residual**2)
    ss_tot = np.sum((obs - np.mean(obs))**2)
    nse = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else -999.0

    # Percent bias
    pbias = float(100.0 * np.sum(residual) / np.sum(obs)) if np.sum(obs) != 0 else 0.0

    return {
        "rmse": round(rmse, 4),
        "bias": round(bias, 4),
        "mae": round(mae, 4),
        "r": round(r, 4),
        "r2": round(r**2, 4),
        "nse": round(nse, 4),
        "pbias": round(pbias, 2),
        "n_points": int(len(sim)),
    }


def write_csv(timeseries: dict, output_path: str, variable: str = None):
    """Write timeseries data to CSV file."""
    if variable:
        vars_to_write = {variable: timeseries[variable]} if variable in timeseries else {}
    else:
        vars_to_write = timeseries

    if not vars_to_write:
        log.warning(f"No data to write for variable={variable}")
        return

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["time"]
        for vname in vars_to_write:
            header.extend([f"{vname}_mean", f"{vname}_min", f"{vname}_max", f"{vname}_std"])
        writer.writerow(header)

        # Use first variable's time axis
        first_var = list(vars_to_write.keys())[0]
        times = vars_to_write[first_var]["time"]

        for i in range(len(times)):
            row = [times[i]]
            for vname, data in vars_to_write.items():
                if i < len(data["mean"]):
                    row.extend([
                        data["mean"][i], data["min"][i],
                        data["max"][i], data["std"][i],
                    ])
                else:
                    row.extend([np.nan] * 4)
            writer.writerow(row)

    log.info(f"Wrote CSV: {output_path} ({len(times)} rows, {len(vars_to_write)} variables)")


def validate_output(timeseries: dict) -> dict:
    """Post-validate: check extracted data for physical sanity."""
    report = {"valid": True, "warnings": [], "stats": {}}

    for vname, data in timeseries.items():
        means = np.array(data["mean"])
        valid = means[~np.isnan(means)]

        if len(valid) == 0:
            report["warnings"].append(f"{vname}: all NaN values")
            continue

        report["stats"][vname] = {
            "n_timesteps": len(data["time"]),
            "global_mean": float(np.mean(valid)),
            "global_min": float(np.min(valid)),
            "global_max": float(np.max(valid)),
        }

        # Physical bounds check
        if vname in VALID_RANGES:
            vmin, vmax = VALID_RANGES[vname]
            if np.min(valid) < vmin:
                report["warnings"].append(
                    f"{vname}: min={np.min(valid):.3g} below physical bound {vmin}"
                )
            if np.max(valid) > vmax:
                report["warnings"].append(
                    f"{vname}: max={np.max(valid):.3g} above physical bound {vmax}"
                )

    for w in report["warnings"]:
        log.warning(w)

    if not report["warnings"]:
        log.info("Output validation PASSED — all values within physical bounds")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Parse MOM6 diagnostic output to CSV and compute metrics"
    )
    parser.add_argument("diag_dir", help="Directory containing diagnostic NetCDF files")
    parser.add_argument("-o", "--output", default="mom6_timeseries.csv",
                        help="Output CSV path (default: mom6_timeseries.csv)")
    parser.add_argument("--stats-file", default=None,
                        help="Path to ocean.stats (auto-detected if in diag_dir)")
    parser.add_argument("--variables", nargs="+", default=None,
                        help="Variables to extract (default: all available)")
    parser.add_argument("--obs-file", default=None,
                        help="Observations NetCDF for metrics (optional)")
    parser.add_argument("--obs-var", default="SST",
                        help="Observation variable name (default: SST)")
    parser.add_argument("--lat-range", type=float, nargs=2, metavar=("S", "N"),
                        help="Latitude range for subsetting")
    parser.add_argument("--lon-range", type=float, nargs=2, metavar=("W", "E"),
                        help="Longitude range for subsetting")
    parser.add_argument("--json-report", default=None,
                        help="Write report to JSON")
    args = parser.parse_args()

    # Step 1: Validate input
    log.info("=== Step 1: Input validation ===")
    info = validate_input(args.diag_dir, args.stats_file)
    if not info["valid"]:
        sys.exit(1)

    full_report = {"input": info}

    # Step 2: Process
    log.info("=== Step 2: Extracting timeseries ===")

    # Parse ocean.stats
    if info["stats_file"]:
        stats_records = parse_ocean_stats(info["stats_file"])
        stats_csv = args.output.replace(".csv", "_stats.csv")
        with open(stats_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["step", "day", "energy", "cfl",
                                                    "sea_level", "truncations"])
            writer.writeheader()
            writer.writerows(stats_records)
        log.info(f"Wrote ocean.stats CSV: {stats_csv}")

    # Parse NetCDF diagnostics
    if info["diag_files"]:
        variables = args.variables or info.get("available_vars", list(TARGET_VARS.keys()))
        timeseries = extract_timeseries(
            info["diag_files"], variables,
            lat_range=tuple(args.lat_range) if args.lat_range else None,
            lon_range=tuple(args.lon_range) if args.lon_range else None,
        )
        write_csv(timeseries, args.output)
    else:
        timeseries = {}

    # Compute validation metrics if observations provided
    if args.obs_file and os.path.isfile(args.obs_file) and timeseries:
        import netCDF4
        log.info("=== Computing validation metrics ===")
        ds_obs = netCDF4.Dataset(args.obs_file, "r")
        obs_data = ds_obs.variables[args.obs_var][:]
        if hasattr(obs_data, "filled"):
            obs_data = obs_data.filled(np.nan)
        ds_obs.close()

        sim_var = args.obs_var if args.obs_var in timeseries else "SST"
        if sim_var in timeseries:
            sim_data = np.array(timeseries[sim_var]["mean"])
            n = min(len(sim_data), len(obs_data))
            metrics = compute_metrics(sim_data[:n], obs_data[:n].flatten()[:n])
            full_report["metrics"] = metrics
            log.info(f"Validation metrics: {json.dumps(metrics, indent=2)}")

    # Step 3: Validate output
    log.info("=== Step 3: Output validation ===")
    if timeseries:
        val_report = validate_output(timeseries)
        full_report["validation"] = val_report

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(full_report, f, indent=2, default=str)
        log.info(f"Report: {args.json_report}")


if __name__ == "__main__":
    main()
