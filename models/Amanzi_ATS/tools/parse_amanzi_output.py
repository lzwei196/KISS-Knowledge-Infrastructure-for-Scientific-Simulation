#!/usr/bin/env python3
"""
parse_amanzi_output.py — Output Parser for Amanzi/ATS

Extracts simulation results from Amanzi HDF5 visualization files and
observation text files, converting them to CSV for analysis.

Supported output types:
  - Observation files (.out): ASCII time-series at observation points
  - Visualization files (.h5): HDF5 field data on mesh (pressure, saturation, etc.)
  - Checkpoint files (.h5): Full state snapshots for restart

Pattern: validate_inputs → process → validate_outputs

Usage:
  # Parse observation file
  python parse_amanzi_output.py --obs_file observations.out --output results.csv

  # Parse HDF5 visualization
  python parse_amanzi_output.py --vis_file plot_data.h5 --variable pressure --output pressure.csv

  # Parse both
  python parse_amanzi_output.py --obs_file obs.out --vis_file plot_data.h5 --output results.csv
"""

import argparse
import json
import os
import sys
import csv
import re

import numpy as np


# ============================================================================
# Constants
# ============================================================================
SECONDS_PER_YEAR = 3.15576e7
SECONDS_PER_DAY = 86400.0
WATER_DENSITY = 998.2
GRAVITY = 9.80665


# ============================================================================
# Validation
# ============================================================================
def validate_inputs(args):
    """Validate input files exist and are readable."""
    errors = []

    if args.obs_file and not os.path.exists(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if args.vis_file and not os.path.exists(args.vis_file):
        errors.append(f"Visualization file not found: {args.vis_file}")

    if not args.obs_file and not args.vis_file:
        errors.append("Must specify --obs_file and/or --vis_file")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Input validation passed.")


def validate_outputs(result):
    """Validate parsed output is physically reasonable."""
    warnings = []

    if "observations" in result:
        for obs_name, obs_data in result["observations"].items():
            values = obs_data.get("values", [])
            if len(values) == 0:
                warnings.append(f"Observation '{obs_name}' has no data points")
            else:
                arr = np.array(values, dtype=float)
                if np.any(np.isnan(arr)):
                    warnings.append(f"Observation '{obs_name}' contains NaN values")
                if np.any(np.isinf(arr)):
                    warnings.append(f"Observation '{obs_name}' contains Inf values")

    if "statistics" in result:
        stats = result["statistics"]
        if "pressure" in stats:
            p_max = stats["pressure"].get("max", 0)
            if p_max > 1e10:
                warnings.append(
                    f"Maximum pressure {p_max:.2e} Pa seems very high. "
                    f"Check boundary conditions."
                )

    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)

    if not warnings:
        print("[OK] Output validation passed.")

    return len(warnings) == 0


# ============================================================================
# Parsers
# ============================================================================
def parse_observation_file(obs_path):
    """Parse Amanzi observation output file (ASCII format).

    Format:
      # Header lines starting with #
      # "observation: Name1"
      # "observation: Name2"
      time  value1  value2  ...
    """
    print(f"[INFO] Parsing observation file: {obs_path}")

    obs_names = []
    times = []
    data_columns = []

    with open(obs_path, "r") as f:
        lines = f.readlines()

    # Parse header for observation names
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Look for observation name declarations
            match = re.search(r'"observation:\s*(.+?)"', stripped)
            if match:
                obs_names.append(match.group(1).strip())
            # Also try "Observation Name" = ... format
            match2 = re.search(r'Observation Name\s*=\s*"?([^"]+)"?', stripped)
            if match2:
                obs_names.append(match2.group(1).strip())
        elif stripped and not stripped.startswith("#"):
            data_start = i
            break

    # Parse data rows
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        try:
            vals = [float(v) for v in parts]
            if len(vals) >= 2:
                times.append(vals[0])
                data_columns.append(vals[1:])
        except ValueError:
            continue

    if not times:
        print(f"[WARNING] No data rows found in {obs_path}")
        return {"observations": {}, "n_timesteps": 0}

    data_array = np.array(data_columns)
    n_cols = data_array.shape[1] if data_array.ndim > 1 else 1

    # Generate names if not found in header
    if len(obs_names) < n_cols:
        for i in range(len(obs_names), n_cols):
            obs_names.append(f"obs_{i + 1}")

    result = {
        "n_timesteps": len(times),
        "time_start_s": times[0],
        "time_end_s": times[-1],
        "time_start_yr": times[0] / SECONDS_PER_YEAR,
        "time_end_yr": times[-1] / SECONDS_PER_YEAR,
        "observations": {},
    }

    for i, name in enumerate(obs_names[:n_cols]):
        if data_array.ndim > 1:
            vals = data_array[:, i].tolist()
        else:
            vals = data_array.tolist()

        result["observations"][name] = {
            "times_s": times,
            "times_yr": [t / SECONDS_PER_YEAR for t in times],
            "values": vals,
            "min": float(np.nanmin(vals)),
            "max": float(np.nanmax(vals)),
            "mean": float(np.nanmean(vals)),
            "unit": _guess_unit(name),
        }

    print(f"[OK] Parsed {len(times)} timesteps, {n_cols} observations")
    return result


def _guess_unit(name):
    """Guess the unit from the observation name."""
    name_lower = name.lower()
    if "pressure" in name_lower:
        return "Pa"
    elif "head" in name_lower or "drawdown" in name_lower:
        return "m"
    elif "concentration" in name_lower or "conc" in name_lower:
        return "mol/L"
    elif "flux" in name_lower:
        return "m³/m²/s"
    elif "saturation" in name_lower:
        return "dimensionless"
    elif "temperature" in name_lower:
        return "K"
    return "unknown"


def parse_vis_file(vis_path, variable=None, timestep=None):
    """Parse Amanzi HDF5 visualization file.

    HDF5 structure:
      /time/             - Time values
      /pressure.cell.0/  - Pressure field at timestep 0
      /saturation_liquid.cell.0/ - Saturation field
      etc.
    """
    try:
        import h5py
    except ImportError:
        print("[ERROR] h5py required for HDF5 parsing. pip install h5py", file=sys.stderr)
        return {"error": "h5py not installed"}

    print(f"[INFO] Parsing visualization file: {vis_path}")

    result = {"vis_file": vis_path, "variables": {}, "statistics": {}}

    with h5py.File(vis_path, "r") as f:
        # List all datasets
        all_keys = list(f.keys())
        print(f"[INFO] Datasets in file: {len(all_keys)}")

        # Extract variable names
        var_names = set()
        for key in all_keys:
            # Pattern: variable_name.cell.timestep
            match = re.match(r"(.+)\.cell\.(\d+)", key)
            if match:
                var_names.add(match.group(1))

        result["available_variables"] = sorted(var_names)
        print(f"[INFO] Variables: {sorted(var_names)}")

        # Extract time array if present
        if "time" in f:
            times = f["time"][:]
            result["times_s"] = times.tolist()
            result["n_timesteps"] = len(times)

        # Extract requested variable
        target_vars = [variable] if variable else list(var_names)[:5]  # Default: first 5

        for var in target_vars:
            if var not in var_names:
                print(f"[WARNING] Variable '{var}' not found in file")
                continue

            # Find all timesteps for this variable
            ts_keys = sorted(
                [k for k in all_keys if k.startswith(f"{var}.cell.")],
                key=lambda k: int(k.split(".")[-1])
            )

            if not ts_keys:
                continue

            # Read last timestep (or specified one)
            if timestep is not None:
                key = f"{var}.cell.{timestep}"
            else:
                key = ts_keys[-1]  # Last timestep

            if key in f:
                data = f[key][:]
                result["variables"][var] = {
                    "n_cells": len(data),
                    "timestep": int(key.split(".")[-1]),
                    "n_available_timesteps": len(ts_keys),
                }
                result["statistics"][var] = {
                    "min": float(np.nanmin(data)),
                    "max": float(np.nanmax(data)),
                    "mean": float(np.nanmean(data)),
                    "std": float(np.nanstd(data)),
                }
                print(f"[OK] {var}: min={np.nanmin(data):.4e}, max={np.nanmax(data):.4e}, "
                      f"mean={np.nanmean(data):.4e}")

    return result


def write_csv(result, output_path):
    """Write parsed results to CSV."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if "observations" in result and result["observations"]:
        # Write observation time series
        obs = result["observations"]
        first_key = list(obs.keys())[0]
        times = obs[first_key]["times_yr"]

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            header = ["time_yr", "time_s"] + list(obs.keys())
            writer.writerow(header)

            for i, t_yr in enumerate(times):
                row = [f"{t_yr:.6f}", f"{obs[first_key]['times_s'][i]:.1f}"]
                for name in obs:
                    vals = obs[name]["values"]
                    row.append(f"{vals[i]:.6e}" if i < len(vals) else "")
                writer.writerow(row)

        print(f"[OK] Wrote observation CSV to {output_path}")

    elif "statistics" in result and result["statistics"]:
        # Write variable statistics
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["variable", "min", "max", "mean", "std", "n_cells"])
            for var, stats in result["statistics"].items():
                vinfo = result.get("variables", {}).get(var, {})
                writer.writerow([
                    var, stats["min"], stats["max"], stats["mean"],
                    stats.get("std", ""), vinfo.get("n_cells", "")
                ])

        print(f"[OK] Wrote statistics CSV to {output_path}")


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Parse Amanzi/ATS output files to CSV"
    )
    parser.add_argument("--obs_file", type=str,
                        help="Path to observation output file (.out)")
    parser.add_argument("--vis_file", type=str,
                        help="Path to visualization HDF5 file (.h5)")
    parser.add_argument("--variable", type=str,
                        help="Variable to extract from HDF5 (e.g., 'pressure')")
    parser.add_argument("--timestep", type=int, default=None,
                        help="Specific timestep to extract (default: last)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    parser.add_argument("--summary", type=str, default=None,
                        help="Output JSON summary file path")
    args = parser.parse_args()

    # Validate
    validate_inputs(args)

    # Process
    result = {}

    if args.obs_file:
        obs_result = parse_observation_file(args.obs_file)
        result.update(obs_result)

    if args.vis_file:
        vis_result = parse_vis_file(args.vis_file, args.variable, args.timestep)
        result.update(vis_result)

    # Validate outputs
    validate_outputs(result)

    # Write CSV
    write_csv(result, args.output)

    # Write JSON summary
    if args.summary:
        # Remove large data arrays for summary
        summary = {}
        for k, v in result.items():
            if k == "observations":
                summary[k] = {
                    name: {kk: vv for kk, vv in data.items()
                           if kk not in ("times_s", "times_yr", "values")}
                    for name, data in v.items()
                }
            elif k == "times_s":
                summary["n_timesteps"] = len(v)
                summary["time_range_yr"] = [v[0] / SECONDS_PER_YEAR, v[-1] / SECONDS_PER_YEAR]
            else:
                summary[k] = v

        os.makedirs(os.path.dirname(args.summary) or ".", exist_ok=True)
        with open(args.summary, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"[OK] Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
