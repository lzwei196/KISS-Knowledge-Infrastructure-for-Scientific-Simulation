#!/usr/bin/env python3
"""
parse_issm_output.py — Parse ISSM simulation results to CSV and JSON summaries.

Reads ISSM model results (from saved .mat/.nc files or direct numpy arrays)
and produces:
1. CSV files with per-vertex results (velocity, thickness, temperature)
2. JSON summary with statistics (min, max, mean, std for each field)
3. Time series CSV for transient solutions

ISSM stores results in md.results.<SolutionType>:
  - StressbalanceSolution: Vx, Vy, Vz, Vel, Pressure
  - MasstransportSolution: Thickness, Surface
  - ThermalSolution: Temperature, Enthalpy
  - TransientSolution: Array of above per timestep

All velocities are in m/yr, temperatures in K, thicknesses in m.

Usage:
    python parse_issm_output.py \
        --results_dir ./issm_output/ \
        --mesh_x mesh_x.npy --mesh_y mesh_y.npy \
        --solution Stressbalance \
        --output_csv results.csv \
        --output_json summary.json

    python parse_issm_output.py \
        --netcdf_file output.nc \
        --solution Transient \
        --output_csv timeseries.csv \
        --output_json summary.json
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

try:
    from netCDF4 import Dataset as NCDataset
except ImportError:
    NCDataset = None


# =============================================================================
# Validation
# =============================================================================
def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.netcdf_file:
        if not os.path.exists(args.netcdf_file):
            errors.append(f"NetCDF file not found: {args.netcdf_file}")
        if NCDataset is None:
            errors.append("netCDF4 required for NetCDF parsing: pip install netCDF4")
    elif args.results_dir:
        if not os.path.isdir(args.results_dir):
            errors.append(f"Results directory not found: {args.results_dir}")
    else:
        errors.append("Must provide either --netcdf_file or --results_dir")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def validate_outputs(output_csv, output_json):
    """Validate generated outputs."""
    errors = []
    warnings = []

    if output_csv and os.path.exists(output_csv):
        size = os.path.getsize(output_csv)
        if size == 0:
            errors.append(f"Output CSV is empty: {output_csv}")
        elif size < 100:
            warnings.append(f"Output CSV very small ({size} bytes): {output_csv}")

    if output_json and os.path.exists(output_json):
        with open(output_json) as f:
            data = json.load(f)
        if "fields" not in data:
            errors.append("Output JSON missing 'fields' key")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return warnings


# =============================================================================
# Data loading
# =============================================================================
def load_from_npy_dir(results_dir):
    """Load results from a directory of .npy files.

    Expected files:
      vx.npy, vy.npy, vel.npy — velocity components (m/yr)
      thickness.npy — ice thickness (m)
      surface.npy — surface elevation (m)
      temperature.npy — temperature (K)
      pressure.npy — pressure (Pa)
    """
    fields = {}
    field_units = {
        "vx": "m/yr", "vy": "m/yr", "vz": "m/yr", "vel": "m/yr",
        "thickness": "m", "surface": "m", "base": "m",
        "temperature": "K", "pressure": "Pa",
        "damage": "-", "smb": "m/yr"
    }

    for fname in os.listdir(results_dir):
        if fname.endswith(".npy"):
            name = fname[:-4]
            try:
                data = np.load(os.path.join(results_dir, fname))
                fields[name] = data
            except Exception as e:
                print(f"WARNING: Failed to load {fname}: {e}", file=sys.stderr)

    return fields, field_units


def load_from_netcdf(nc_path, solution_type):
    """Load results from ISSM NetCDF output.

    ISSM's export_netCDF creates files with dimensions:
      - numberofvertices (or numberofnodes)
      - time (for transient)

    Variables follow naming: Vx, Vy, Vel, Thickness, Temperature, etc.
    """
    fields = {}
    field_units = {}

    with NCDataset(nc_path) as ds:
        for var_name in ds.variables:
            if var_name in ('x', 'y', 'z', 'elements', 'time'):
                continue
            var = ds.variables[var_name]
            data = np.array(var[:])
            fields[var_name] = data

            # Determine units
            if hasattr(var, 'units'):
                field_units[var_name] = var.units
            elif 'vel' in var_name.lower() or var_name in ('Vx', 'Vy', 'Vz', 'Vel'):
                field_units[var_name] = "m/yr"
            elif 'thick' in var_name.lower() or var_name == 'Thickness':
                field_units[var_name] = "m"
            elif 'temp' in var_name.lower() or var_name == 'Temperature':
                field_units[var_name] = "K"
            elif 'pressure' in var_name.lower() or var_name == 'Pressure':
                field_units[var_name] = "Pa"
            else:
                field_units[var_name] = "-"

    return fields, field_units


# =============================================================================
# Output generation
# =============================================================================
def compute_statistics(fields, field_units):
    """Compute summary statistics for each field."""
    stats = []
    for name, data in fields.items():
        if data.ndim == 1:
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape),
                "min": float(np.nanmin(data)),
                "max": float(np.nanmax(data)),
                "mean": float(np.nanmean(data)),
                "std": float(np.nanstd(data)),
                "n_nan": int(np.sum(np.isnan(data))),
                "n_total": int(data.size)
            }
        elif data.ndim == 2:
            # Time-varying field: compute per-timestep stats
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape),
                "n_timesteps": data.shape[0],
                "min": float(np.nanmin(data)),
                "max": float(np.nanmax(data)),
                "mean": float(np.nanmean(data)),
                "std": float(np.nanstd(data)),
                "final_mean": float(np.nanmean(data[-1])),
                "final_max": float(np.nanmax(data[-1]))
            }
        else:
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape)
            }
        stats.append(stat)
    return stats


def write_csv(fields, mesh_x, mesh_y, output_csv):
    """Write per-vertex results to CSV.

    Format: x, y, field1, field2, ...
    Only includes 1D (per-vertex) fields.
    """
    # Filter to 1D fields matching vertex count
    nv = len(mesh_x) if mesh_x is not None else None
    csv_fields = {}
    for name, data in fields.items():
        if data.ndim == 1:
            if nv is None or data.shape[0] == nv:
                csv_fields[name] = data

    if not csv_fields:
        print("WARNING: No 1D fields found for CSV output", file=sys.stderr)
        return

    header = []
    if mesh_x is not None:
        header.extend(["x", "y"])
    header.extend(sorted(csv_fields.keys()))

    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        n_rows = len(list(csv_fields.values())[0])
        for i in range(n_rows):
            row = []
            if mesh_x is not None:
                row.extend([f"{mesh_x[i]:.2f}", f"{mesh_y[i]:.2f}"])
            for name in sorted(csv_fields.keys()):
                row.append(f"{csv_fields[name][i]:.6g}")
            writer.writerow(row)

    print(f"CSV written: {output_csv} ({n_rows} rows, {len(header)} columns)", file=sys.stderr)


def write_timeseries_csv(fields, output_csv):
    """Write time series summary CSV for transient solutions.

    Format: timestep, field1_mean, field1_max, field2_mean, field2_max, ...
    """
    # Filter to 2D (time-varying) fields
    ts_fields = {name: data for name, data in fields.items() if data.ndim == 2}

    if not ts_fields:
        print("WARNING: No time-varying fields found for timeseries CSV", file=sys.stderr)
        return

    n_timesteps = max(data.shape[0] for data in ts_fields.values())

    header = ["timestep"]
    for name in sorted(ts_fields.keys()):
        header.extend([f"{name}_mean", f"{name}_max", f"{name}_min"])

    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for t in range(n_timesteps):
            row = [t]
            for name in sorted(ts_fields.keys()):
                data = ts_fields[name]
                if t < data.shape[0]:
                    row.extend([
                        f"{np.nanmean(data[t]):.6g}",
                        f"{np.nanmax(data[t]):.6g}",
                        f"{np.nanmin(data[t]):.6g}"
                    ])
                else:
                    row.extend(["", "", ""])
            writer.writerow(row)

    print(f"Timeseries CSV written: {output_csv} ({n_timesteps} timesteps)", file=sys.stderr)


# =============================================================================
# Processing
# =============================================================================
def process_results(args):
    """Main processing: load, compute stats, write outputs."""
    # Load results
    if args.netcdf_file:
        fields, field_units = load_from_netcdf(args.netcdf_file, args.solution)
    else:
        fields, field_units = load_from_npy_dir(args.results_dir)

    if not fields:
        print(json.dumps({"status": "error", "errors": ["No result fields found"]}))
        sys.exit(1)

    print(f"Loaded {len(fields)} fields: {', '.join(fields.keys())}", file=sys.stderr)

    # Load mesh coordinates if available
    mesh_x = np.load(args.mesh_x) if args.mesh_x and os.path.exists(args.mesh_x) else None
    mesh_y = np.load(args.mesh_y) if args.mesh_y and os.path.exists(args.mesh_y) else None

    # Compute statistics
    stats = compute_statistics(fields, field_units)

    # Write JSON summary
    if args.output_json:
        summary = {
            "status": "success",
            "solution_type": args.solution,
            "n_fields": len(fields),
            "fields": stats
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"JSON summary written: {args.output_json}", file=sys.stderr)

    # Write CSV
    if args.output_csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_csv)), exist_ok=True)

        # Check if transient (time-varying fields)
        has_timeseries = any(data.ndim == 2 for data in fields.values())

        if has_timeseries and args.solution == "Transient":
            write_timeseries_csv(fields, args.output_csv)
        else:
            write_csv(fields, mesh_x, mesh_y, args.output_csv)

    # Validate outputs
    warnings = validate_outputs(args.output_csv, args.output_json)

    # Print summary
    result = {
        "status": "success",
        "solution_type": args.solution,
        "n_fields": len(fields),
        "fields": stats,
        "csv": args.output_csv,
        "json": args.output_json,
        "warnings": warnings
    }
    print(json.dumps(result, indent=2))


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Parse ISSM simulation results")

    parser.add_argument("--results_dir", help="Directory with .npy result files")
    parser.add_argument("--netcdf_file", help="ISSM NetCDF output file")
    parser.add_argument("--mesh_x", help="Mesh x-coordinates (.npy)")
    parser.add_argument("--mesh_y", help="Mesh y-coordinates (.npy)")
    parser.add_argument("--solution", default="Stressbalance",
                        choices=["Stressbalance", "Masstransport", "Thermal",
                                 "Transient", "Balancethickness", "Hydrology",
                                 "DamageEvolution", "Steadystate"])
    parser.add_argument("--output_csv", help="Output CSV file path")
    parser.add_argument("--output_json", help="Output JSON summary path")

    args = parser.parse_args()
    validate_inputs(args)
    process_results(args)


if __name__ == "__main__":
    main()
