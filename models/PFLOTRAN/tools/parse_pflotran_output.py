#!/usr/bin/env python3
"""
parse_pflotran_output.py — Parse PFLOTRAN output files (HDF5, TecPlot) to CSV.

Reads PFLOTRAN HDF5 output and TecPlot observation files, extracts time series
of hydraulic head, saturation, velocity, and concentration fields, and writes
them to analysis-ready CSV and summary JSON.

Inputs:
    --hdf5-file    : Path to PFLOTRAN HDF5 output (.h5)
    --obs-file     : Path to TecPlot observation file (.tec) (optional)
    --variables    : Variables to extract (default: all)
    --output-dir   : Directory for output CSV/JSON files

Outputs:
    - Time series CSV per variable (e.g., liquid_pressure.csv)
    - Observation point CSV (from .tec files)
    - Summary statistics JSON
    - Water balance summary (if mass balance file exists)

Usage:
    python parse_pflotran_output.py \\
        --hdf5-file bengbu_richards.h5 \\
        --obs-file bengbu_richards-obs-0.tec \\
        --output-dir results/
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime

import numpy as np


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
SECONDS_PER_YEAR = 3.15576e7
SECONDS_PER_DAY = 86400.0
PA_TO_M_HEAD = 1.0 / (998.2 * 9.80665)  # Pa to m of water head


def validate_inputs(args):
    """Validate input paths and parameters.

    Returns:
        dict with 'valid' (bool), 'errors' (list)
    """
    errors = []

    if args.hdf5_file and not os.path.isfile(args.hdf5_file):
        errors.append(f"HDF5 file not found: {args.hdf5_file}")

    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if not args.hdf5_file and not args.obs_file:
        errors.append("At least one of --hdf5-file or --obs-file is required")

    return {"valid": len(errors) == 0, "errors": errors}


def parse_hdf5_output(hdf5_path, variables=None):
    """Parse PFLOTRAN HDF5 output file.

    HDF5 structure:
        /Coordinates/X [ncells]
        /Coordinates/Y [ncells]
        /Coordinates/Z [ncells]
        /Time:X.XXXXe+XX y/Liquid_Pressure [ncells]
        /Time:X.XXXXe+XX y/Liquid_Saturation [ncells]
        /Time:X.XXXXe+XX y/Material_ID [ncells]
        ...

    Returns:
        dict with:
            - coordinates: dict of X, Y, Z arrays
            - times: list of float (years)
            - variables: dict of {var_name: {time: array}}
            - ncells: int
    """
    try:
        import h5py
    except ImportError:
        print("ERROR: h5py required. Install with: pip install h5py")
        sys.exit(1)

    f = h5py.File(hdf5_path, "r")

    # Extract coordinates
    coords = {}
    if "Coordinates" in f:
        for dim in ["X", "Y", "Z"]:
            if dim in f["Coordinates"]:
                coords[dim] = np.array(f["Coordinates"][dim])

    ncells = len(coords.get("X", []))

    # Find time groups
    time_pattern = re.compile(r"Time:\s*([\d.eE+\-]+)\s*(\w+)")
    times = []
    time_groups = {}

    for key in f.keys():
        match = time_pattern.match(key)
        if match:
            time_val = float(match.group(1))
            time_unit = match.group(2)
            # Convert to years
            if time_unit == "s":
                time_yr = time_val / SECONDS_PER_YEAR
            elif time_unit == "d":
                time_yr = time_val / 365.25
            elif time_unit == "h":
                time_yr = time_val / (365.25 * 24)
            else:
                time_yr = time_val  # assume years

            times.append(time_yr)
            time_groups[time_yr] = key

    times.sort()

    # Extract variables at each time
    var_data = {}
    available_vars = set()

    for t_yr in times:
        group_name = time_groups[t_yr]
        group = f[group_name]
        for var_name in group.keys():
            available_vars.add(var_name)
            if variables and var_name not in variables:
                continue
            if var_name not in var_data:
                var_data[var_name] = {}
            var_data[var_name][t_yr] = np.array(group[var_name])

    f.close()

    return {
        "coordinates": coords,
        "times": times,
        "variables": var_data,
        "ncells": ncells,
        "available_variables": list(available_vars),
    }


def parse_tecplot_observation(obs_path):
    """Parse PFLOTRAN TecPlot observation file.

    Format:
        TITLE = ""
        VARIABLES = "Time [y]","Liq. Pressure [Pa]","Liq. Saturation [-]",...
        ZONE T="Observation: well_1"
        1.000000e-03  2.058000e+05  9.876543e-01
        ...

    Returns:
        dict with:
            - observation_name: str
            - variables: list of str (column names with units)
            - time: numpy array
            - data: dict of {variable_name: numpy array}
    """
    obs_name = ""
    var_names = []
    data_lines = []

    with open(obs_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("TITLE"):
                continue
            elif line.startswith("VARIABLES"):
                # Parse variable names from quoted strings
                matches = re.findall(r'"([^"]+)"', line)
                var_names = matches
            elif line.startswith("ZONE"):
                match = re.search(r'T="([^"]+)"', line)
                if match:
                    obs_name = match.group(1)
            elif line and not line.startswith("#"):
                try:
                    values = [float(x) for x in line.split()]
                    if len(values) == len(var_names):
                        data_lines.append(values)
                except ValueError:
                    continue

    if not data_lines:
        return {"observation_name": obs_name, "variables": var_names,
                "time": np.array([]), "data": {}}

    data_array = np.array(data_lines)
    result = {
        "observation_name": obs_name,
        "variables": var_names,
        "time": data_array[:, 0] if data_array.shape[1] > 0 else np.array([]),
        "data": {},
    }

    for i, var in enumerate(var_names):
        result["data"][var] = data_array[:, i]

    return result


def compute_water_balance(mas_path):
    """Parse PFLOTRAN mass balance file.

    Returns:
        dict with cumulative inflow, outflow, storage change, and balance error
    """
    if not os.path.isfile(mas_path):
        return None

    times = []
    data_cols = {}

    with open(mas_path, "r") as f:
        header = None
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                if line.startswith("#") and header is None:
                    header = line.lstrip("#").split(",")
                    for h in header:
                        data_cols[h.strip()] = []
                continue
            values = line.split()
            if header and len(values) == len(header):
                for h, v in zip(header, values):
                    try:
                        data_cols[h.strip()].append(float(v))
                    except ValueError:
                        data_cols[h.strip()].append(0.0)

    return data_cols if data_cols else None


def pressure_to_head(pressure_pa, elevation_m=0.0, reference_pressure=101325.0):
    """Convert liquid pressure (Pa) to hydraulic head (m).

    h = (P - P_atm) / (rho * g) + z

    CRITICAL: PFLOTRAN stores absolute liquid pressure, not gauge pressure.
    Must subtract atmospheric pressure before converting.

    Args:
        pressure_pa: liquid pressure in Pa
        elevation_m: cell center elevation in m
        reference_pressure: atmospheric pressure (default 101325 Pa)

    Returns:
        hydraulic head in m
    """
    return (pressure_pa - reference_pressure) * PA_TO_M_HEAD + elevation_m


def write_observation_csv(obs_data, output_path):
    """Write observation data to CSV.

    Adds derived columns:
    - head_m: hydraulic head from pressure (if pressure column exists)
    """
    if len(obs_data["time"]) == 0:
        print(f"  WARNING: No data in observation, skipping {output_path}")
        return

    # Find pressure column
    pressure_col = None
    for var in obs_data["variables"]:
        if "Pressure" in var or "pressure" in var:
            pressure_col = var
            break

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = list(obs_data["variables"])
        if pressure_col:
            header.append("Head_m")
        writer.writerow(header)

        # Data rows
        for i in range(len(obs_data["time"])):
            row = [obs_data["data"][var][i] for var in obs_data["variables"]]
            if pressure_col:
                head = pressure_to_head(obs_data["data"][pressure_col][i])
                row.append(head)
            writer.writerow(row)

    print(f"  Written {len(obs_data['time'])} records to {output_path}")


def write_spatial_csv(hdf5_data, output_dir):
    """Write spatial data at each time step to CSV.

    One CSV per time step with columns: X, Y, Z, var1, var2, ...
    """
    coords = hdf5_data["coordinates"]
    if not coords:
        return []

    written_files = []
    for var_name, time_data in hdf5_data["variables"].items():
        var_dir = os.path.join(output_dir, var_name.replace(" ", "_"))
        os.makedirs(var_dir, exist_ok=True)

        for t_yr, values in time_data.items():
            safe_time = f"{t_yr:.4e}".replace("+", "").replace(".", "p")
            csv_path = os.path.join(var_dir, f"t_{safe_time}_yr.csv")

            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["X_m", "Y_m", "Z_m", var_name])
                for i in range(min(len(values), len(coords.get("X", [])))):
                    writer.writerow([
                        coords["X"][i] if "X" in coords else 0,
                        coords["Y"][i] if "Y" in coords else 0,
                        coords["Z"][i] if "Z" in coords else 0,
                        values[i],
                    ])
            written_files.append(csv_path)

    return written_files


def compute_summary_statistics(hdf5_data, obs_data=None):
    """Compute summary statistics across all variables and times.

    Returns:
        dict with per-variable min, max, mean, std at each time
    """
    stats = {
        "simulation_duration_yr": max(hdf5_data["times"]) if hdf5_data["times"] else 0,
        "n_timesteps": len(hdf5_data["times"]),
        "n_cells": hdf5_data["ncells"],
        "available_variables": hdf5_data["available_variables"],
        "variable_stats": {},
    }

    for var_name, time_data in hdf5_data["variables"].items():
        var_stats = []
        for t_yr in sorted(time_data.keys()):
            values = time_data[t_yr]
            var_stats.append({
                "time_yr": float(t_yr),
                "min": float(np.nanmin(values)),
                "max": float(np.nanmax(values)),
                "mean": float(np.nanmean(values)),
                "std": float(np.nanstd(values)),
            })
        stats["variable_stats"][var_name] = var_stats

    # Add observation stats if available
    if obs_data and obs_data["time"].size > 0:
        stats["observation"] = {
            "name": obs_data["observation_name"],
            "n_records": len(obs_data["time"]),
            "time_range_yr": [float(obs_data["time"][0]), float(obs_data["time"][-1])],
        }

    return stats


def validate_outputs(output_dir, stats):
    """Validate parsed outputs for physical reasonableness.

    Returns:
        dict with 'valid' (bool), 'warnings' (list)
    """
    warnings = []

    for var_name, var_stats in stats.get("variable_stats", {}).items():
        if not var_stats:
            continue

        last = var_stats[-1]

        # Check pressure range
        if "Pressure" in var_name:
            if last["min"] < 0:
                warnings.append(
                    f"{var_name}: Negative pressure ({last['min']:.2e} Pa) "
                    "— may indicate fully unsaturated cells or numerical issues"
                )
            if last["max"] > 1e9:
                warnings.append(
                    f"{var_name}: Pressure > 1 GPa ({last['max']:.2e} Pa) "
                    "— check boundary conditions"
                )

        # Check saturation range
        if "Saturation" in var_name:
            if last["min"] < 0 or last["max"] > 1.001:
                warnings.append(
                    f"{var_name}: Saturation outside [0,1] "
                    f"(range: [{last['min']:.4f}, {last['max']:.4f}])"
                )

    return {"valid": len(warnings) == 0, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(
        description="Parse PFLOTRAN output to CSV and summary statistics"
    )
    parser.add_argument("--hdf5-file", help="Path to HDF5 output file")
    parser.add_argument("--obs-file", help="Path to TecPlot observation file")
    parser.add_argument("--variables", nargs="+", help="Variables to extract")
    parser.add_argument("--output-dir", required=True, help="Output directory")

    args = parser.parse_args()

    print("=" * 60)
    print("PFLOTRAN Output Parser")
    print("=" * 60)

    # Step 1: Validate inputs
    print("\n[1/4] Validating inputs...")
    validation = validate_inputs(args)
    if not validation["valid"]:
        for err in validation["errors"]:
            print(f"  ERROR: {err}")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 2: Parse HDF5
    hdf5_data = {"coordinates": {}, "times": [], "variables": {},
                 "ncells": 0, "available_variables": []}

    if args.hdf5_file:
        print(f"\n[2/4] Parsing HDF5: {args.hdf5_file}...")
        hdf5_data = parse_hdf5_output(args.hdf5_file, args.variables)
        print(f"  Cells: {hdf5_data['ncells']}")
        print(f"  Time steps: {len(hdf5_data['times'])}")
        print(f"  Variables: {hdf5_data['available_variables']}")

        # Write spatial CSVs
        written = write_spatial_csv(hdf5_data, args.output_dir)
        print(f"  Written {len(written)} spatial CSV files")
    else:
        print("\n[2/4] No HDF5 file specified, skipping.")

    # Step 3: Parse observation files
    obs_data = None
    if args.obs_file:
        print(f"\n[3/4] Parsing observation file: {args.obs_file}...")
        obs_data = parse_tecplot_observation(args.obs_file)
        print(f"  Observation: {obs_data['observation_name']}")
        print(f"  Records: {len(obs_data['time'])}")
        print(f"  Variables: {obs_data['variables']}")

        obs_csv = os.path.join(args.output_dir, "observations.csv")
        write_observation_csv(obs_data, obs_csv)
    else:
        print("\n[3/4] No observation file specified, skipping.")

    # Step 4: Summary and validation
    print("\n[4/4] Computing summary statistics...")
    stats = compute_summary_statistics(hdf5_data, obs_data)

    output_validation = validate_outputs(args.output_dir, stats)
    for w in output_validation["warnings"]:
        print(f"  WARNING: {w}")

    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"  Summary: {summary_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
