#!/usr/bin/env python3
"""
parse_pflotran_output.py — Parse PFLOTRAN output files (HDF5, TecPlot) to CSV.

Reads PFLOTRAN HDF5 output and TecPlot observation files, extracts time series
of hydraulic head, saturation, velocity, and concentration fields, and writes
them to analysis-ready CSV and summary JSON.

Inputs:
    --hdf5-file    : Path to PFLOTRAN HDF5 output (.h5)
    --obs-file     : Path to observation file (<prefix>-obs-N.tec or .pft) (optional)
    --regression-file : Path to a PFLOTRAN .regression file (optional)
    --variables    : Variables to extract (default: all)
    --output-dir   : Directory for output CSV/JSON files

Outputs:
    - Time series CSV per variable (e.g., liquid_pressure.csv)
    - Observation point CSV (from .tec files)
    - regression.csv (section, quantity, key, component, value) from a .regression file
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
# PFLOTRAN's own year: DAYS_PER_YEAR = 365 (src/pflotran/pflotran_constants.F90);
# time unit factors as in src/pflotran/units.F90
SECONDS_PER_DAY = 86400.0
SECONDS_PER_YEAR = 365.0 * SECONDS_PER_DAY
TIME_UNIT_SECONDS = {
    "s": 1.0, "sec": 1.0, "second": 1.0,
    "min": 60.0, "minute": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0,
    "d": SECONDS_PER_DAY, "day": SECONDS_PER_DAY,
    "w": 7 * SECONDS_PER_DAY, "week": 7 * SECONDS_PER_DAY,
    "mo": SECONDS_PER_YEAR / 12.0, "month": SECONDS_PER_YEAR / 12.0,
    "y": SECONDS_PER_YEAR, "yr": SECONDS_PER_YEAR, "year": SECONDS_PER_YEAR,
}


def time_to_years(value, unit):
    """Convert a PFLOTRAN time value to years (365-day PFLOTRAN year)."""
    if unit not in TIME_UNIT_SECONDS:
        raise ValueError(f"unknown PFLOTRAN time unit '{unit}'")
    return value * TIME_UNIT_SECONDS[unit] / SECONDS_PER_YEAR
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

    if args.regression_file and not os.path.isfile(args.regression_file):
        errors.append(f"Regression file not found: {args.regression_file}")

    if not args.hdf5_file and not args.obs_file and not args.regression_file:
        errors.append("At least one of --hdf5-file, --obs-file or --regression-file is required")

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

    # Extract coordinates. PFLOTRAN v6 structured-grid output stores the grid
    # lines as "Coordinates/X [m]" (nx+1 values) etc. and each variable as an
    # (nx, ny, nz) array; cell centres are the midpoints of the grid lines.
    coords = {}
    grid_lines = {}
    if "Coordinates" in f:
        for key in f["Coordinates"].keys():
            dim = key.split()[0]
            if dim in ("X", "Y", "Z"):
                grid_lines[dim] = np.array(f["Coordinates"][key], dtype=float)
    for dim, gl in grid_lines.items():
        if gl.ndim != 1 or len(gl) < 2 or not np.all(np.isfinite(gl)) or np.any(np.diff(gl) <= 0):
            raise ValueError(f"Coordinates/{dim}: grid lines must be finite and increasing")
    if len(grid_lines) == 3:
        mids = [0.5 * (grid_lines[d][1:] + grid_lines[d][:-1]) for d in ("X", "Y", "Z")]
        cx, cy, cz = np.meshgrid(*mids, indexing="ij")
        coords = {"X": cx.ravel(), "Y": cy.ravel(), "Z": cz.ravel()}
        grid_shape = tuple(len(m) for m in mids)
    else:
        grid_shape = None

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
            # Convert to years (raises on an unknown unit)
            time_yr = time_to_years(time_val, time_unit)

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
            arr = np.array(group[var_name])
            if grid_shape is not None:
                if arr.shape != grid_shape:
                    raise ValueError(f"{group_name}/{var_name} has shape {arr.shape}, grid "
                                     f"is {grid_shape} (only cell-centred structured output "
                                     "is supported)")
                arr = arr.ravel()  # same (i, j, k) order as the cell centres
            var_data[var_name][t_yr] = arr

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
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if line.startswith("TITLE"):
                continue
            elif line.startswith('"') and not var_names:
                # PFLOTRAN v6 observation files (-obs-N.tec / .pft): first line is the
                # quoted column names, e.g. "Time [y]","2-Liquid Pressure [Pa] east (100) ..."
                var_names = re.findall(r'"([^"]+)"', line)
            elif line.startswith("VARIABLES"):
                # Parse variable names from quoted strings
                matches = re.findall(r'"([^"]+)"', line)
                var_names = matches
            elif line.startswith("ZONE"):
                match = re.search(r'T="([^"]+)"', line)
                if match:
                    obs_name = match.group(1)
            elif line and not line.startswith("#"):
                # A data row: every value a finite number, one per column
                try:
                    values = [float(x) for x in line.split()]
                except ValueError:
                    raise ValueError(f"{obs_path}:{lineno}: not a data row: {line[:80]}")
                if not var_names:
                    raise ValueError(f"{obs_path}:{lineno}: data before the column-name line")
                if len(values) != len(var_names):
                    raise ValueError(f"{obs_path}:{lineno}: {len(values)} values for "
                                     f"{len(var_names)} columns")
                if not all(np.isfinite(values)):
                    raise ValueError(f"{obs_path}:{lineno}: non-finite value")
                data_lines.append(values)

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


def parse_regression_file(reg_path):
    """Parse a PFLOTRAN .regression file.

    Format (written by PFLOTRAN's REGRESSION block):
        -- PRESSURE: Liquid Pressure --
              Max:   4.0763719684121E+05
               29:   2.3584750178849E+05
        -- GENERIC: LIQUID VELOCITY [m/y] --
               29:  -2.2482369131225E+02  1.4654128808109E+02 -1.2881825353295E+00
        -- SOLUTION: Flow --
           Time Steps:          100

    Returns:
        list of dicts with section, quantity, key, values (list of float)
    """
    records = []
    section = quantity = None
    with open(reg_path) as f:
        for lineno, line in enumerate(f, 1):
            m = re.match(r"^--\s*([A-Za-z_]+):\s*(.*?)\s*--\s*$", line.strip())
            if m:
                section, quantity = m.group(1), m.group(2)
                continue
            if section is None or ":" not in line:
                continue
            key, rest = line.split(":", 1)
            try:
                values = [float(v) for v in rest.split()]
            except ValueError:
                raise ValueError(f"{reg_path}:{lineno}: not a number: {line.strip()[:80]}")
            if not values:
                raise ValueError(f"{reg_path}:{lineno}: no value: {line.strip()[:80]}")
            if not all(np.isfinite(values)):
                raise ValueError(f"{reg_path}:{lineno}: non-finite value")
            if values:
                records.append({"section": section, "quantity": quantity,
                                "key": key.strip(), "values": values})
    return records


def write_regression_csv(records, output_path):
    """One row per value: section, quantity, key, component, value."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["section", "quantity", "key", "component", "value"])
        for r in records:
            for i, v in enumerate(r["values"]):
                writer.writerow([r["section"], r["quantity"], r["key"], i, repr(v)])
    print(f"  Written {sum(len(r['values']) for r in records)} values to {output_path}")


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
    if pressure_col:
        print(f"  NOTE: Head_m = (P - 101325 Pa) / (998.2 kg/m3 * 9.80665 m/s2) from column "
              f"'{pressure_col}' with elevation 0 m: a pressure head, not the hydraulic head "
              "at the point's elevation")

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
                if len(values) != len(coords.get("X", [])):
                    raise ValueError(f"{var_name}: {len(values)} values but "
                                     f"{len(coords.get('X', []))} cell coordinates")
                for i in range(len(values)):
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
        t0, t1 = float(obs_data["time"][0]), float(obs_data["time"][-1])
        m = re.search(r"\[(\w+)\]", obs_data["variables"][0]) if obs_data["variables"] else None
        unit = m.group(1) if m else None
        stats["observation"] = {
            "name": obs_data["observation_name"],
            "n_records": len(obs_data["time"]),
        }
        if unit in TIME_UNIT_SECONDS:
            stats["observation"]["time_range_yr"] = [time_to_years(t0, unit), time_to_years(t1, unit)]
        else:
            # unit unknown: report the file's own values and say so
            stats["observation"]["time_range"] = [t0, t1]
            stats["observation"]["time_unit"] = unit or "unknown"

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
    parser.add_argument("--obs-file", help="Path to observation file (-obs-N.tec or .pft)")
    parser.add_argument("--regression-file", help="Path to a PFLOTRAN .regression file")
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

    failures = []

    # Step 2: Parse HDF5
    hdf5_data = {"coordinates": {}, "times": [], "variables": {},
                 "ncells": 0, "available_variables": []}

    if args.hdf5_file:
        print(f"\n[2/4] Parsing HDF5: {args.hdf5_file}...")
        try:
            hdf5_data = parse_hdf5_output(args.hdf5_file, args.variables)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)
        print(f"  Cells: {hdf5_data['ncells']}")
        print(f"  Time steps: {len(hdf5_data['times'])}")
        print(f"  Variables: {hdf5_data['available_variables']}")
        if not hdf5_data["times"]:
            print(f"  ERROR: no 'Time: ...' groups in {args.hdf5_file}")
            failures.append("hdf5")
        elif not hdf5_data["variables"]:
            what = f"none of {args.variables}" if args.variables else "no datasets"
            print(f"  ERROR: {what} in the time groups of {args.hdf5_file}")
            failures.append("hdf5")

        # Write spatial CSVs
        try:
            written = write_spatial_csv(hdf5_data, args.output_dir)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            written = []
            failures.append("hdf5")
        print(f"  Written {len(written)} spatial CSV files")
        if hdf5_data["variables"] and not written and "hdf5" not in failures:
            print("  ERROR: no cell coordinates found (only structured-grid "
                  "'Coordinates/X|Y|Z' output is supported); no spatial CSVs written")
            failures.append("hdf5")
    else:
        print("\n[2/4] No HDF5 file specified, skipping.")

    # Step 3: Parse observation files
    obs_data = None
    if args.obs_file:
        print(f"\n[3/4] Parsing observation file: {args.obs_file}...")
        try:
            obs_data = parse_tecplot_observation(args.obs_file)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)
        print(f"  Observation: {obs_data['observation_name']}")
        print(f"  Records: {len(obs_data['time'])}")
        print(f"  Variables: {obs_data['variables']}")

        obs_csv = os.path.join(args.output_dir, "observations.csv")
        if len(obs_data["time"]) == 0:
            print(f"  ERROR: no data rows read from {args.obs_file}")
            failures.append("obs")
        write_observation_csv(obs_data, obs_csv)
    else:
        print("\n[3/4] No observation file specified, skipping.")

    # Regression file (optional)
    reg_records = None
    if args.regression_file:
        print(f"\n[3b] Parsing regression file: {args.regression_file}...")
        try:
            reg_records = parse_regression_file(args.regression_file)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            sys.exit(1)
        if not reg_records:
            print(f"  ERROR: no values read from {args.regression_file}")
            failures.append("regression")
        else:
            print(f"  Sections: {sorted({r['section'] for r in reg_records})}")
            write_regression_csv(reg_records, os.path.join(args.output_dir, "regression.csv"))

    # Step 4: Summary and validation
    print("\n[4/4] Computing summary statistics...")
    stats = compute_summary_statistics(hdf5_data, obs_data)
    if reg_records:
        reg = {}
        for r in reg_records:
            sec = reg.setdefault(f"{r['section']}: {r['quantity']}", {"values": {}})
            sec["values"][r["key"]] = r["values"] if len(r["values"]) > 1 else r["values"][0]
        stats["regression"] = reg

    output_validation = validate_outputs(args.output_dir, stats)
    for w in output_validation["warnings"]:
        print(f"  WARNING: {w}")

    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(stats, f, indent=2, default=str)
    print(f"  Summary: {summary_path}")

    if failures:
        print(f"\nFAILED: no data read from: {failures}")
        sys.exit(1)
    print("\nDone.")


if __name__ == "__main__":
    main()
