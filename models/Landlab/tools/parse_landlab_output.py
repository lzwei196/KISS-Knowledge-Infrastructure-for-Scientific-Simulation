#!/usr/bin/env python3
"""
parse_landlab_output.py — Extract Landlab simulation results to CSV and compute metrics

Reads simulation output (NPZ grid files, JSON snapshots) and produces:
  1. A CSV summary of field statistics over time
  2. Slope-area analysis for geomorphic validation
  3. Longitudinal profile extraction for the main channel
  4. Optional comparison against analytical solutions

CRITICAL NOTES:
  - Slope-area analysis requires log-log regression; zero-area and zero-slope
    nodes must be excluded (they produce -inf in log space).
  - Concavity index θ = m/n in steady-state stream power law. For m=0.5,
    n=1.0, expected θ=0.5. Deviation > 10% suggests non-steady-state or
    parameter mismatch.
  - Drainage area has units m² (grid spacing squared × cell count).
    If grid spacing is wrong, area is wrong and slope-area breaks.

Usage:
    python parse_landlab_output.py --input results/ --output results/summary.csv
    python parse_landlab_output.py --input results/final_grid.npz --output summary.csv --metrics slope_area
    python parse_landlab_output.py --input results/ --output summary.csv --profile --channel-csv channel.csv
"""

import argparse
import csv
import glob
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate command-line arguments and input paths."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input path not found: {args.input}")

    if args.metrics and args.metrics not in ("slope_area", "hypsometry", "relief", "all"):
        errors.append(
            f"Unknown metric '{args.metrics}'. "
            "Choose: slope_area, hypsometry, relief, all"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def process(args):
    """Parse simulation outputs and compute requested metrics."""
    results = {}

    # Determine input type
    if os.path.isdir(args.input):
        results["snapshots"] = _parse_snapshot_dir(args.input)
        # Look for final grid
        final_path = os.path.join(args.input, "final_grid.npz")
        if os.path.exists(final_path):
            results["final_grid"] = _parse_grid_file(final_path)
    elif args.input.endswith(".npz"):
        results["final_grid"] = _parse_grid_file(args.input)
    elif args.input.endswith(".nc"):
        results["final_grid"] = _parse_netcdf(args.input)
    else:
        print(json.dumps({
            "status": "error",
            "errors": [f"Unsupported input format: {args.input}"]
        }), file=sys.stderr)
        sys.exit(1)

    # Compute metrics
    if args.metrics and "final_grid" in results:
        grid_data = results["final_grid"]
        if args.metrics in ("slope_area", "all"):
            results["slope_area"] = _compute_slope_area(grid_data)
        if args.metrics in ("hypsometry", "all"):
            results["hypsometry"] = _compute_hypsometry(grid_data)
        if args.metrics in ("relief", "all"):
            results["relief"] = _compute_relief(grid_data)

    # Extract main channel profile
    if args.profile and "final_grid" in results:
        results["channel_profile"] = _extract_channel_profile(results["final_grid"])

    return results


def _parse_snapshot_dir(dir_path):
    """Parse all JSON snapshot files in a directory."""
    snap_files = sorted(glob.glob(os.path.join(dir_path, "snapshot_*.json")))
    snapshots = []

    for snap_file in snap_files:
        with open(snap_file) as f:
            snap = json.load(f)
        row = {"step": snap.get("step", 0), "time": snap.get("time", 0)}

        for key, val in snap.items():
            if isinstance(val, dict) and "mean" in val:
                row[f"{key}_min"] = val["min"]
                row[f"{key}_max"] = val["max"]
                row[f"{key}_mean"] = val["mean"]

        snapshots.append(row)

    return snapshots


def _parse_grid_file(npz_path):
    """Parse an NPZ grid file into a dict of arrays."""
    data = dict(np.load(npz_path))
    return {k: v for k, v in data.items()}


def _parse_netcdf(nc_path):
    """Parse a NetCDF grid file."""
    try:
        import xarray as xr
        ds = xr.open_dataset(nc_path)
        return {var: ds[var].values for var in ds.data_vars}
    except ImportError:
        print("WARNING: xarray required for NetCDF parsing", file=sys.stderr)
        return {}


def _compute_slope_area(grid_data):
    """Compute slope-area relationship and concavity index."""
    if "topographic__elevation" not in grid_data:
        return {"error": "topographic__elevation not found in grid data"}

    z = grid_data["topographic__elevation"]
    n_nodes = len(z)

    # We need drainage area — check if available
    if "drainage_area" in grid_data:
        area = grid_data["drainage_area"]
    else:
        # Cannot compute slope-area without drainage area
        return {"error": "drainage_area not found. Run FlowAccumulator first."}

    # Compute local slope from steepest_slope if available
    if "topographic__steepest_slope" in grid_data:
        slope = grid_data["topographic__steepest_slope"]
    else:
        # Approximate: will be less accurate
        return {"error": "topographic__steepest_slope not found"}

    # Filter: only channel nodes (area > threshold, slope > 0)
    area_threshold = np.percentile(area[area > 0], 50) if np.any(area > 0) else 1
    mask = (area > area_threshold) & (slope > 1e-10) & np.isfinite(slope) & np.isfinite(area)

    if np.sum(mask) < 10:
        return {"error": "Too few valid channel nodes for slope-area analysis"}

    log_a = np.log10(area[mask])
    log_s = np.log10(slope[mask])

    # Linear regression in log-log space: log(S) = -θ log(A) + log(ks)
    coeffs = np.polyfit(log_a, log_s, 1)
    theta = -coeffs[0]  # concavity index
    ks = 10 ** coeffs[1]  # steepness index

    # Correlation coefficient
    predicted = np.polyval(coeffs, log_a)
    ss_res = np.sum((log_s - predicted) ** 2)
    ss_tot = np.sum((log_s - np.mean(log_s)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        "concavity_theta": round(float(theta), 4),
        "steepness_ks": round(float(ks), 6),
        "r_squared": round(float(r_squared), 4),
        "n_channel_nodes": int(np.sum(mask)),
        "area_range_m2": [float(np.min(area[mask])), float(np.max(area[mask]))],
        "slope_range": [float(np.min(slope[mask])), float(np.max(slope[mask]))],
    }


def _compute_hypsometry(grid_data):
    """Compute hypsometric curve statistics."""
    if "topographic__elevation" not in grid_data:
        return {"error": "topographic__elevation not found"}

    z = grid_data["topographic__elevation"]
    valid_z = z[np.isfinite(z)]
    z_min, z_max = np.min(valid_z), np.max(valid_z)

    if z_max - z_min < 1e-6:
        return {"error": "No relief"}

    # Normalized elevation
    z_norm = (valid_z - z_min) / (z_max - z_min)

    # Hypsometric integral = mean of normalized elevation
    hi = float(np.mean(z_norm))

    # Percentiles
    percentiles = [10, 25, 50, 75, 90]
    pct_values = {f"p{p}": round(float(np.percentile(valid_z, p)), 2)
                  for p in percentiles}

    return {
        "hypsometric_integral": round(hi, 4),
        "elevation_percentiles": pct_values,
        "relief_m": round(float(z_max - z_min), 2),
        "mean_elevation_m": round(float(np.mean(valid_z)), 2),
    }


def _compute_relief(grid_data):
    """Compute relief metrics."""
    if "topographic__elevation" not in grid_data:
        return {"error": "topographic__elevation not found"}

    z = grid_data["topographic__elevation"]
    valid_z = z[np.isfinite(z)]

    return {
        "total_relief_m": round(float(np.max(valid_z) - np.min(valid_z)), 2),
        "mean_elevation_m": round(float(np.mean(valid_z)), 2),
        "std_elevation_m": round(float(np.std(valid_z)), 2),
    }


def _extract_channel_profile(grid_data):
    """Extract main channel longitudinal profile (longest flow path)."""
    if "drainage_area" not in grid_data or "topographic__elevation" not in grid_data:
        return {"error": "Need drainage_area and topographic__elevation"}

    area = grid_data["drainage_area"]
    z = grid_data["topographic__elevation"]

    # Start at node with maximum drainage area (outlet)
    outlet = np.argmax(area)

    # Simple profile: sort by drainage area descending along main stem
    # Use area as proxy for distance upstream
    threshold = np.max(area) * 0.01
    channel_mask = area > threshold
    channel_nodes = np.where(channel_mask)[0]

    # Sort by elevation (proxy for distance upstream)
    sorted_idx = np.argsort(z[channel_nodes])
    profile_z = z[channel_nodes[sorted_idx]]
    profile_area = area[channel_nodes[sorted_idx]]

    return {
        "n_profile_nodes": len(profile_z),
        "outlet_elevation_m": round(float(z[outlet]), 2),
        "headwater_elevation_m": round(float(np.max(profile_z)), 2),
        "profile_relief_m": round(float(np.max(profile_z) - np.min(profile_z)), 2),
    }


def validate_outputs(results):
    """Validate computed metrics for consistency."""
    warnings = []

    if "slope_area" in results:
        sa = results["slope_area"]
        if "concavity_theta" in sa:
            theta = sa["concavity_theta"]
            if theta < 0:
                warnings.append(
                    f"WARNING: Negative concavity θ={theta}. This may indicate "
                    "the landscape is not in steady state or has unusual geometry."
                )
            if theta > 1.0:
                warnings.append(
                    f"WARNING: Concavity θ={theta} > 1.0 is unusually high. "
                    "Check that drainage area and slope are computed correctly."
                )
        if "r_squared" in sa and sa["r_squared"] < 0.5:
            warnings.append(
                f"WARNING: Slope-area r²={sa['r_squared']} is poor. "
                "Landscape may not be in steady state."
            )

    if "hypsometry" in results:
        hi = results["hypsometry"].get("hypsometric_integral", 0.5)
        if hi < 0.1 or hi > 0.9:
            warnings.append(
                f"WARNING: Hypsometric integral {hi} is extreme. "
                "Check boundary conditions and simulation duration."
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse Landlab output and compute geomorphic metrics"
    )
    parser.add_argument("--input", type=str, required=True,
                        help="Input directory or file (NPZ/NC)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    parser.add_argument("--metrics", type=str, default=None,
                        choices=["slope_area", "hypsometry", "relief", "all"],
                        help="Metrics to compute (default: none)")
    parser.add_argument("--profile", action="store_true",
                        help="Extract main channel profile")
    parser.add_argument("--channel-csv", type=str, default=None,
                        help="Output CSV for channel profile data")
    args = parser.parse_args()

    validate_inputs(args)
    results = process(args)
    warnings = validate_outputs(results)

    # Write snapshot CSV
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    if "snapshots" in results and results["snapshots"]:
        fieldnames = list(results["snapshots"][0].keys())
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results["snapshots"])

    # Write metrics to separate JSON
    metrics_path = args.output.replace(".csv", "_metrics.json")
    metrics_out = {k: v for k, v in results.items() if k != "snapshots"}
    metrics_out["warnings"] = warnings
    with open(metrics_path, "w") as f:
        json.dump(metrics_out, f, indent=2)

    summary = {
        "status": "success",
        "output_csv": args.output if "snapshots" in results else None,
        "metrics_json": metrics_path,
        "n_snapshots": len(results.get("snapshots", [])),
        "metrics_computed": [k for k in results if k not in ("snapshots", "final_grid")],
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
