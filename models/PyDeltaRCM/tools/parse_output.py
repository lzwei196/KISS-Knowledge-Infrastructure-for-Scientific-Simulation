#!/usr/bin/env python3
"""
Parse pyDeltaRCM NetCDF output and extract results to CSV and summary plots.

Reads the model output NetCDF file and produces:
- Time series CSV of key delta metrics (area, volume, shoreline length)
- Grid snapshots as images
- Summary statistics

Pattern: validate input → process → validate output
"""

import argparse
import csv
import json
import os
import sys
from typing import Optional

import numpy as np


def validate_netcdf(nc_path: str) -> list:
    """Validate a pyDeltaRCM output NetCDF file.

    Parameters
    ----------
    nc_path : str
        Path to the NetCDF output file.

    Returns
    -------
    list
        List of error/warning strings.
    """
    errors = []

    if not os.path.isfile(nc_path):
        errors.append(f"File not found: {nc_path}")
        return errors

    try:
        import netCDF4
        ds = netCDF4.Dataset(nc_path, "r")
    except Exception as e:
        errors.append(f"Cannot open NetCDF: {e}")
        return errors

    # Check expected dimensions
    for dim in ["x", "y"]:
        if dim not in ds.dimensions:
            errors.append(f"Missing dimension: {dim}")

    time_dim = None
    for t in ["seconds", "time"]:
        if t in ds.dimensions:
            time_dim = t
            break
    if time_dim is None:
        errors.append("Missing time dimension (expected 'seconds' or 'time')")

    # Check for at least one variable
    data_vars = [v for v in ds.variables if v not in ds.dimensions]
    if not data_vars:
        errors.append("No data variables found in NetCDF")

    info = {
        "dimensions": {k: len(v) for k, v in ds.dimensions.items()},
        "variables": list(ds.variables.keys()),
        "time_steps": len(ds.dimensions.get(time_dim, [])) if time_dim else 0,
    }

    ds.close()
    return errors, info


def compute_delta_metrics(eta: np.ndarray, H_SL: float = 0.0) -> dict:
    """Compute delta geomorphological metrics from a single eta grid.

    Parameters
    ----------
    eta : np.ndarray
        2D bed elevation array (L x W).
    H_SL : float
        Sea level elevation.

    Returns
    -------
    dict
        Dictionary of metrics.
    """
    # Land mask: cells above sea level
    land_mask = eta > H_SL

    # Remove the initial land (inlet area) — approximate as cells where
    # the entire row is land
    row_land_frac = land_mask.mean(axis=1)

    # Delta area (cells above sea level, excluding full-land rows)
    delta_cells = land_mask.copy()
    for i in range(len(row_land_frac)):
        if row_land_frac[i] > 0.9:
            delta_cells[i, :] = False
        else:
            break

    delta_area_cells = delta_cells.sum()
    total_cells = eta.size

    # Volume above sea level
    delta_volume = np.sum(np.maximum(eta - H_SL, 0) * delta_cells)

    # Shoreline length (perimeter of land above sea level)
    from scipy import ndimage
    if delta_cells.sum() > 0:
        # Find boundary cells
        eroded = ndimage.binary_erosion(delta_cells)
        boundary = delta_cells & ~eroded
        shoreline_cells = boundary.sum()
    else:
        shoreline_cells = 0

    # Max delta extent (furthest row with any land)
    rows_with_land = np.where(delta_cells.any(axis=1))[0]
    max_extent = rows_with_land[-1] if len(rows_with_land) > 0 else 0

    # Channel count (number of connected water regions at a mid-delta cross-section)
    if len(rows_with_land) > 0:
        mid_row = rows_with_land[len(rows_with_land) // 2]
        cross_section = ~land_mask[mid_row, :]
        labeled, n_channels = ndimage.label(cross_section)
    else:
        n_channels = 0

    return {
        "delta_area_cells": int(delta_area_cells),
        "delta_area_fraction": float(delta_area_cells / total_cells),
        "delta_volume_m3_per_dx2": float(delta_volume),
        "shoreline_cells": int(shoreline_cells),
        "max_extent_cells": int(max_extent),
        "n_channels_midslice": int(n_channels),
        "mean_elevation_above_sl": float(
            eta[delta_cells].mean() - H_SL if delta_cells.sum() > 0 else 0
        ),
    }


def parse_output(
    nc_path: str,
    output_dir: str,
    dx: float = 50.0,
    H_SL: float = 0.0,
    save_csv: bool = True,
    save_snapshots: bool = True,
    snapshot_times: Optional[list] = None,
) -> dict:
    """Parse pyDeltaRCM output and extract metrics.

    Parameters
    ----------
    nc_path : str
        Path to pyDeltaRCM_output.nc.
    output_dir : str
        Directory for output CSV and images.
    dx : float
        Grid cell size in meters (for area/volume conversion).
    H_SL : float
        Sea level elevation.
    save_csv : bool
        Whether to save time series CSV.
    save_snapshots : bool
        Whether to save grid snapshot images.
    snapshot_times : list, optional
        List of time indices for snapshots. If None, use first/mid/last.

    Returns
    -------
    dict
        Summary of parsed results.
    """
    import netCDF4

    os.makedirs(output_dir, exist_ok=True)

    ds = netCDF4.Dataset(nc_path, "r")

    # Determine time dimension
    time_dim = "seconds" if "seconds" in ds.dimensions else "time"
    n_times = len(ds.dimensions[time_dim])

    # Get time values
    if time_dim in ds.variables:
        time_values = ds.variables[time_dim][:]
    else:
        time_values = np.arange(n_times)

    # Get eta if available
    has_eta = "eta" in ds.variables

    results = {
        "nc_path": nc_path,
        "n_timesteps": n_times,
        "variables": list(ds.variables.keys()),
        "grid_shape": None,
        "metrics_timeseries": [],
    }

    if has_eta:
        # Get grid shape from first timestep
        eta_0 = ds.variables["eta"][0, :, :]
        results["grid_shape"] = list(eta_0.shape)

        # Compute metrics for each timestep
        csv_rows = []
        for t in range(n_times):
            eta_t = ds.variables["eta"][t, :, :]
            metrics = compute_delta_metrics(np.array(eta_t), H_SL)
            metrics["time_index"] = t
            metrics["time_seconds"] = float(time_values[t])
            metrics["time_days"] = float(time_values[t] / 86400)

            # Convert to real units
            metrics["delta_area_km2"] = (
                metrics["delta_area_cells"] * dx * dx / 1e6
            )
            metrics["delta_volume_m3"] = (
                metrics["delta_volume_m3_per_dx2"] * dx * dx
            )
            metrics["shoreline_length_km"] = (
                metrics["shoreline_cells"] * dx / 1000
            )
            metrics["max_extent_km"] = metrics["max_extent_cells"] * dx / 1000

            csv_rows.append(metrics)
            results["metrics_timeseries"].append(metrics)

        # Save CSV
        if save_csv and csv_rows:
            csv_path = os.path.join(output_dir, "delta_metrics.csv")
            fieldnames = csv_rows[0].keys()
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_rows)
            results["csv_path"] = csv_path

        # Save snapshot images
        if save_snapshots:
            if snapshot_times is None:
                snapshot_times = [0]
                if n_times > 2:
                    snapshot_times.append(n_times // 2)
                if n_times > 1:
                    snapshot_times.append(n_times - 1)

            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt

                results["snapshots"] = []
                for t_idx in snapshot_times:
                    if t_idx >= n_times:
                        continue
                    eta_t = np.array(ds.variables["eta"][t_idx, :, :])
                    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
                    im = ax.pcolormesh(
                        np.arange(eta_t.shape[1] + 1) * dx / 1000,
                        np.arange(eta_t.shape[0] + 1) * dx / 1000,
                        eta_t,
                        cmap="terrain",
                        vmin=-5,
                        vmax=2,
                    )
                    ax.set_xlabel("Width (km)")
                    ax.set_ylabel("Length (km)")
                    ax.set_title(
                        f"Bed Elevation — Day {time_values[t_idx]/86400:.0f}"
                    )
                    ax.set_aspect("equal")
                    plt.colorbar(im, ax=ax, label="Elevation (m)")

                    snap_path = os.path.join(
                        output_dir, f"eta_snapshot_t{t_idx:04d}.png"
                    )
                    fig.savefig(snap_path, dpi=150, bbox_inches="tight")
                    plt.close(fig)
                    results["snapshots"].append(snap_path)

            except ImportError:
                results["warnings"] = ["matplotlib not available for snapshots"]

    # Extract other variables summary
    for var_name in ["depth", "velocity", "discharge", "sandfrac"]:
        if var_name in ds.variables:
            var_data = np.array(ds.variables[var_name][-1, :, :])
            results[f"{var_name}_final_stats"] = {
                "min": float(np.nanmin(var_data)),
                "max": float(np.nanmax(var_data)),
                "mean": float(np.nanmean(var_data)),
                "std": float(np.nanstd(var_data)),
            }

    ds.close()

    # Save summary JSON
    summary_path = os.path.join(output_dir, "parse_summary.json")
    # Remove large timeseries from saved summary
    save_results = {k: v for k, v in results.items() if k != "metrics_timeseries"}
    save_results["n_metric_records"] = len(results["metrics_timeseries"])
    if results["metrics_timeseries"]:
        save_results["final_metrics"] = results["metrics_timeseries"][-1]

    with open(summary_path, "w") as f:
        json.dump(save_results, f, indent=2, default=str)
    results["summary_path"] = summary_path

    return results


def validate_output_results(results: dict) -> list:
    """Validate parsed output results.

    Parameters
    ----------
    results : dict
        Results from parse_output.

    Returns
    -------
    list
        List of warning/error strings.
    """
    issues = []

    if results["n_timesteps"] == 0:
        issues.append("ERROR: No timesteps in output")

    if results.get("metrics_timeseries"):
        final = results["metrics_timeseries"][-1]
        if final["delta_area_cells"] == 0:
            issues.append(
                "WARNING: No delta formed (0 cells above sea level). "
                "Check if model ran long enough or if parameters are correct."
            )
        if final.get("n_channels_midslice", 0) == 0:
            issues.append(
                "WARNING: No channels detected at mid-delta cross-section"
            )

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="Parse pyDeltaRCM output NetCDF to CSV and plots"
    )
    parser.add_argument("nc_path", help="Path to pyDeltaRCM_output.nc")
    parser.add_argument("-o", "--output-dir", default="parsed_output",
                        help="Output directory for CSV and images")
    parser.add_argument("--dx", type=float, default=50.0,
                        help="Grid cell size in meters")
    parser.add_argument("--sea-level", type=float, default=0.0,
                        help="Sea level elevation")
    parser.add_argument("--no-snapshots", action="store_true",
                        help="Skip snapshot images")

    args = parser.parse_args()

    print(f"Parsing: {args.nc_path}")

    # Validate input
    errors, info = validate_netcdf(args.nc_path)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"  Timesteps: {info['time_steps']}")
    print(f"  Variables: {', '.join(info['variables'])}")

    # Parse
    results = parse_output(
        args.nc_path,
        args.output_dir,
        dx=args.dx,
        H_SL=args.sea_level,
        save_snapshots=not args.no_snapshots,
    )

    # Validate output
    issues = validate_output_results(results)
    for issue in issues:
        print(f"  {issue}")

    if results.get("csv_path"):
        print(f"\nCSV saved: {results['csv_path']}")
    if results.get("snapshots"):
        print(f"Snapshots: {len(results['snapshots'])} images saved")
    if results.get("summary_path"):
        print(f"Summary: {results['summary_path']}")

    if results.get("metrics_timeseries"):
        final = results["metrics_timeseries"][-1]
        print(f"\nFinal delta metrics (day {final['time_days']:.0f}):")
        print(f"  Area: {final['delta_area_km2']:.3f} km2")
        print(f"  Volume: {final['delta_volume_m3']:.0f} m3")
        print(f"  Shoreline: {final['shoreline_length_km']:.2f} km")
        print(f"  Max extent: {final['max_extent_km']:.2f} km")
        print(f"  Channels at midpoint: {final['n_channels_midslice']}")


if __name__ == "__main__":
    main()
