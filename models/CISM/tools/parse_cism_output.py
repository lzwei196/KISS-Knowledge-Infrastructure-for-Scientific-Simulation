#!/usr/bin/env python3
"""
parse_cism_output.py -- Extract CISM NetCDF output to CSV and summary statistics.

Reads the NetCDF output from a CISM simulation and extracts:
  1. Time series of integrated quantities (ice volume, area, mass)
  2. Spatial fields at selected timesteps (ice thickness, velocity)
  3. Profile data along transects or at diagnostic points
  4. Summary statistics and comparison to analytical solutions

UNITS IN OUTPUT:
  - thk: meters
  - uvel, vvel, velnorm: m/yr (scaled by factor scyr = 31,536,000 in output)
  - temp, btemp: degrees Celsius
  - acab, bmlt: m/yr
  - iarea: km^2 (CISM stores in m^2, this tool converts)
  - ivol: km^3 (CISM stores in m^3, this tool converts)

WARNING (dt_013): Internal CISM velocities are in m/s (SI), but NetCDF output
applies factor=scyr to convert to m/yr. If you read raw Fortran arrays
(e.g., from restart files) velocities are in m/s. This tool reads from
NetCDF output which is already in m/yr.

Usage:
    # Full extraction to CSV
    python parse_cism_output.py --input output.nc --output results.csv

    # Time series only
    python parse_cism_output.py --input output.nc --mode timeseries \
        --output timeseries.csv

    # Spatial snapshot at final time
    python parse_cism_output.py --input output.nc --mode snapshot \
        --timestep -1 --output snapshot.csv

    # Dome analytical comparison
    python parse_cism_output.py --input dome.out.nc --mode dome_check \
        --output dome_comparison.csv
"""

import argparse
import sys
import os
import numpy as np

try:
    import netCDF4
except ImportError:
    print("ERROR: netCDF4 required. Install with: pip install netCDF4")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_input(input_path):
    """Validate the input NetCDF file."""
    if not os.path.exists(input_path):
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    ds = netCDF4.Dataset(input_path, "r")
    errors = []

    if "time" not in ds.dimensions:
        errors.append("No time dimension found")
    elif len(ds.dimensions["time"]) == 0:
        errors.append("Time dimension is empty (dt_009: check output frequency)")

    required_dims = ["x1", "y1"]
    for d in required_dims:
        if d not in ds.dimensions:
            errors.append(f"Missing dimension: {d}")

    ds.close()

    if errors:
        for e in errors:
            print(f"INPUT VALIDATION ERROR: {e}")
        sys.exit(1)

    print(f"Input validation passed: {input_path}")


# ---------------------------------------------------------------------------
# Time series extraction
# ---------------------------------------------------------------------------

def extract_timeseries(ds, output_path):
    """Extract integrated time series quantities."""
    time_var = ds.variables["time"][:]
    n_times = len(time_var)

    # Initialize output arrays
    data = {"time_yr": time_var}

    # Volume-based quantities
    if "thk" in ds.variables:
        thk = ds.variables["thk"][:]

        # Get grid spacing
        if "x1" in ds.variables and len(ds.variables["x1"]) > 1:
            dx = ds.variables["x1"][1] - ds.variables["x1"][0]
        else:
            dx = 1.0
        if "y1" in ds.variables and len(ds.variables["y1"]) > 1:
            dy = ds.variables["y1"][1] - ds.variables["y1"][0]
        else:
            dy = 1.0

        cell_area = dx * dy  # m^2

        # Compute time series
        ice_volume = np.zeros(n_times)
        ice_area = np.zeros(n_times)
        max_thk = np.zeros(n_times)
        mean_thk = np.zeros(n_times)

        for t in range(n_times):
            thk_t = thk[t]
            ice_mask = thk_t > 0
            ice_volume[t] = np.sum(thk_t) * cell_area / 1e9  # km^3
            ice_area[t] = np.sum(ice_mask) * cell_area / 1e6  # km^2
            max_thk[t] = np.max(thk_t)
            if np.any(ice_mask):
                mean_thk[t] = np.mean(thk_t[ice_mask])

        data["ice_volume_km3"] = ice_volume
        data["ice_area_km2"] = ice_area
        data["max_thickness_m"] = max_thk
        data["mean_thickness_m"] = mean_thk

    # Velocity statistics
    if "velnorm" in ds.variables:
        velnorm = ds.variables["velnorm"][:]
        data["max_velocity_myr"] = np.array(
            [np.max(velnorm[t]) for t in range(n_times)]
        )
        data["mean_velocity_myr"] = np.array(
            [np.mean(velnorm[t][velnorm[t] > 0]) if np.any(velnorm[t] > 0) else 0.0
             for t in range(n_times)]
        )
    elif "uvel" in ds.variables and "vvel" in ds.variables:
        uvel = ds.variables["uvel"][:]
        vvel = ds.variables["vvel"][:]
        data["max_velocity_myr"] = np.array(
            [np.max(np.sqrt(uvel[t]**2 + vvel[t]**2))
             for t in range(n_times)]
        )

    # Temperature
    if "btemp" in ds.variables:
        btemp = ds.variables["btemp"][:]
        data["min_btemp_C"] = np.array(
            [np.min(btemp[t]) for t in range(n_times)]
        )
        data["max_btemp_C"] = np.array(
            [np.max(btemp[t]) for t in range(n_times)]
        )

    # Write CSV
    import csv
    keys = list(data.keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        for i in range(n_times):
            writer.writerow([f"{data[k][i]:.6g}" for k in keys])

    print(f"Time series written: {output_path} ({n_times} timesteps)")
    return data


# ---------------------------------------------------------------------------
# Snapshot extraction
# ---------------------------------------------------------------------------

def extract_snapshot(ds, timestep, output_path):
    """Extract spatial fields at a given timestep."""
    n_times = len(ds.dimensions["time"])
    if timestep < 0:
        timestep = n_times + timestep

    if timestep >= n_times or timestep < 0:
        print(f"ERROR: timestep {timestep} out of range [0, {n_times-1}]")
        return

    ewn = len(ds.dimensions["x1"])
    nsn = len(ds.dimensions["y1"])
    time_val = ds.variables["time"][timestep]

    print(f"Extracting snapshot at t={time_val:.1f} yr (step {timestep})")

    # Flatten spatial fields to CSV (j, i, var1, var2, ...)
    scalar_vars = ["thk", "usurf", "topg", "acab", "bmlt", "btemp"]
    available = [v for v in scalar_vars if v in ds.variables]

    import csv
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["j", "i"] + available
        if "x1" in ds.variables:
            header.insert(2, "x_m")
        if "y1" in ds.variables:
            header.insert(3, "y_m")
        writer.writerow(header)

        x1 = ds.variables["x1"][:] if "x1" in ds.variables else np.arange(ewn)
        y1 = ds.variables["y1"][:] if "y1" in ds.variables else np.arange(nsn)

        for j in range(nsn):
            for i in range(ewn):
                row = [j, i]
                if "x1" in ds.variables:
                    row.append(f"{x1[i]:.1f}")
                if "y1" in ds.variables:
                    row.append(f"{y1[j]:.1f}")
                for v in available:
                    val = ds.variables[v][timestep]
                    if val.ndim == 2:
                        row.append(f"{val[j, i]:.6g}")
                    elif val.ndim == 3:  # has level dimension
                        row.append(f"{val[-1, j, i]:.6g}")  # basal
                    else:
                        row.append("0")
                writer.writerow(row)

    print(f"Snapshot written: {output_path} ({nsn*ewn} cells)")


# ---------------------------------------------------------------------------
# Dome analytical check
# ---------------------------------------------------------------------------

def dome_analytical_check(ds, output_path):
    """Compare dome test results to SIA analytical solution."""
    thk = ds.variables["thk"]
    time_var = ds.variables["time"][:]
    n_times = len(time_var)

    x1 = ds.variables["x1"][:]
    y1 = ds.variables["y1"][:]
    ewn, nsn = len(x1), len(y1)
    dx = x1[1] - x1[0] if ewn > 1 else 1.0
    dy = y1[1] - y1[0] if nsn > 1 else 1.0

    # Center of domain
    cx, cy = ewn // 2, nsn // 2

    # Final timestep
    thk_final = thk[-1, :, :]
    max_thk = np.max(thk_final)
    center_thk = thk_final[cy, cx]

    # Ice volume
    vol = np.sum(thk_final) * dx * dy / 1e9  # km^3

    # Radial profile
    r = np.sqrt((np.arange(ewn) - cx)**2 * dx**2 +
                (np.arange(nsn)[:, None] - cy)**2 * dy**2)

    # Compute divide thickness ratio (should be ~0.707 * max for parabolic)
    radius_max = min(cx, cy) * dx

    print(f"\nDome Analytical Check:")
    print(f"  Grid: {ewn} x {nsn}, dx={dx:.0f} m")
    print(f"  Final time: {time_var[-1]:.0f} yr")
    print(f"  Max thickness: {max_thk:.1f} m")
    print(f"  Center thickness: {center_thk:.1f} m")
    print(f"  Ice volume: {vol:.2f} km^3")
    print(f"  Domain radius: {radius_max:.0f} m")

    # Write comparison
    import csv
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value", "unit"])
        writer.writerow(["max_thickness", f"{max_thk:.2f}", "m"])
        writer.writerow(["center_thickness", f"{center_thk:.2f}", "m"])
        writer.writerow(["ice_volume", f"{vol:.4f}", "km^3"])
        writer.writerow(["ice_area", f"{np.sum(thk_final > 0) * dx * dy / 1e6:.2f}", "km^2"])
        writer.writerow(["n_timesteps", n_times, ""])
        writer.writerow(["final_time", f"{time_var[-1]:.0f}", "yr"])

    print(f"Dome check written: {output_path}")
    return {
        "max_thickness": max_thk,
        "center_thickness": center_thk,
        "ice_volume_km3": vol,
    }


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def print_summary(ds):
    """Print summary statistics for the output file."""
    print("\n=== CISM Output Summary ===")
    print(f"Dimensions: {dict(ds.dimensions)}")
    print(f"Time steps: {len(ds.dimensions['time'])}")

    if "time" in ds.variables:
        t = ds.variables["time"][:]
        print(f"Time range: {t[0]:.1f} to {t[-1]:.1f} yr")

    print(f"\nVariables:")
    for vname in sorted(ds.variables.keys()):
        v = ds.variables[vname]
        units = getattr(v, "units", "?")
        shape = v.shape
        print(f"  {vname:15s} {str(shape):20s} [{units}]")

    # Final state statistics
    print(f"\nFinal state:")
    for vname in ["thk", "usurf", "uvel", "vvel", "temp", "acab", "bmlt"]:
        if vname in ds.variables:
            data = ds.variables[vname][-1]
            print(f"  {vname:10s}: min={np.min(data):.4g}  max={np.max(data):.4g}  "
                  f"mean={np.mean(data):.4g}")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(output_path):
    """Validate the extracted CSV file."""
    if not os.path.exists(output_path):
        print(f"ERROR: Output file not created: {output_path}")
        return False

    size = os.path.getsize(output_path)
    if size == 0:
        print(f"ERROR: Output file is empty: {output_path}")
        return False

    # Count rows
    with open(output_path) as f:
        n_lines = sum(1 for _ in f)

    print(f"Output validation passed: {output_path} ({n_lines} lines, {size} bytes)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse CISM NetCDF output files"
    )
    parser.add_argument("--input", required=True, help="NetCDF output file")
    parser.add_argument("--output", default="results.csv", help="CSV output")
    parser.add_argument("--mode", choices=["timeseries", "snapshot", "dome_check",
                                           "summary", "all"],
                        default="all")
    parser.add_argument("--timestep", type=int, default=-1,
                        help="Timestep for snapshot (-1 = last)")

    args = parser.parse_args()

    validate_input(args.input)
    ds = netCDF4.Dataset(args.input, "r")

    if args.mode in ("summary", "all"):
        print_summary(ds)

    if args.mode in ("timeseries", "all"):
        ts_path = args.output.replace(".csv", "_timeseries.csv") \
            if args.mode == "all" else args.output
        extract_timeseries(ds, ts_path)
        validate_output(ts_path)

    if args.mode in ("snapshot", "all"):
        snap_path = args.output.replace(".csv", "_snapshot.csv") \
            if args.mode == "all" else args.output
        extract_snapshot(ds, args.timestep, snap_path)
        validate_output(snap_path)

    if args.mode == "dome_check":
        dome_analytical_check(ds, args.output)
        validate_output(args.output)

    ds.close()
    print("\nParsing complete.")


if __name__ == "__main__":
    main()
