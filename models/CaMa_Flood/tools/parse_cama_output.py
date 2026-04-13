#!/usr/bin/env python3
"""
parse_cama_output.py -- Extract and analyze CaMa-Flood output.

Capabilities:
  1. Extract discharge (outflw) time series at a gauge point (lat/lon)
  2. Extract flood depth/extent statistics
  3. Compute summary metrics (peak Q, mean Q, flood duration)
  4. Output CSV for downstream analysis/plotting

This is Stage 4 of the CaMa-Flood pipeline.

Usage:
    # Extract discharge at Bengbu station
    python parse_cama_output.py \\
        --output_dir /mnt/disk1/Hydrocraft_server/model/cmf_v420_pkg/out/bengbu_2000_2005_cama \\
        --variable outflw \\
        --lat 32.95 --lon 117.35 \\
        --start_year 2000 --end_year 2005 \\
        --csv discharge_bengbu.csv

    # Extract flood depth spatial statistics
    python parse_cama_output.py \\
        --output_dir /path/to/output \\
        --variable flddph \\
        --start_year 2003 --end_year 2003 \\
        --spatial_stats

    # Extract all variables at a point
    python parse_cama_output.py \\
        --output_dir /path/to/output \\
        --variable outflw,rivdph,sfcelv,flddph \\
        --lat 32.95 --lon 117.35 \\
        --start_year 2000 --end_year 2005
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np

try:
    import xarray as xr
except ImportError:
    print("ERROR: xarray not installed. Run: pip install xarray")
    sys.exit(1)


def find_nearest_cell(ds, target_lat, target_lon):
    """Find the nearest CaMa-Flood grid cell to the target coordinates.

    Returns (lat_idx, lon_idx, actual_lat, actual_lon, distance_km).
    """
    lats = ds.lat.values
    lons = ds.lon.values

    # Simple nearest-neighbor (fine for 0.25-degree resolution)
    lat_idx = int(np.argmin(np.abs(lats - target_lat)))
    lon_idx = int(np.argmin(np.abs(lons - target_lon)))

    actual_lat = float(lats[lat_idx])
    actual_lon = float(lons[lon_idx])

    # Approximate distance in km
    dlat = (actual_lat - target_lat) * 111.0
    dlon = (actual_lon - target_lon) * 111.0 * np.cos(np.radians(target_lat))
    dist_km = np.sqrt(dlat**2 + dlon**2)

    return lat_idx, lon_idx, actual_lat, actual_lon, dist_km


def extract_point_timeseries(output_dir, variables, target_lat, target_lon,
                              start_year, end_year):
    """Extract time series at a point for one or more variables."""
    results = {}

    for var in variables:
        all_times = []
        all_values = []

        for year in range(start_year, end_year + 1):
            nc_file = os.path.join(output_dir, f"o_{var}{year}.nc")
            if not os.path.isfile(nc_file):
                print(f"  WARNING: {nc_file} not found, skipping")
                continue

            ds = xr.open_dataset(nc_file)

            if var not in ds.data_vars:
                print(f"  WARNING: Variable '{var}' not in {nc_file}")
                ds.close()
                continue

            lat_idx, lon_idx, act_lat, act_lon, dist = find_nearest_cell(
                ds, target_lat, target_lon
            )

            if year == start_year:
                print(f"  Variable: {var}")
                print(f"    Target:  ({target_lat:.4f}, {target_lon:.4f})")
                print(f"    Nearest: ({act_lat:.4f}, {act_lon:.4f}), distance: {dist:.1f} km")
                if dist > 30:
                    print(f"    WARNING: Nearest cell is {dist:.1f} km away. "
                          f"Check coordinates.")

            values = ds[var].values[:, lat_idx, lon_idx]
            times = ds.time.values

            all_times.extend(times)
            all_values.extend(values)
            ds.close()

        if all_values:
            results[var] = {
                "times": all_times,
                "values": np.array(all_values, dtype=float),
                "lat": act_lat,
                "lon": act_lon,
            }

    return results


def compute_statistics(values, var_name):
    """Compute summary statistics for a time series."""
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return {}

    stats = {
        "n_timesteps": len(valid),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "median": float(np.median(valid)),
        "p95": float(np.percentile(valid, 95)),
        "p99": float(np.percentile(valid, 99)),
    }

    # Variable-specific metrics
    if var_name == "outflw":
        stats["peak_discharge_m3s"] = stats["max"]
        stats["mean_discharge_m3s"] = stats["mean"]
        # Days above threshold (flood days)
        if stats["mean"] > 0:
            flood_threshold = stats["mean"] * 2.0
            stats["flood_days_2x_mean"] = int(np.sum(valid > flood_threshold))
    elif var_name == "flddph":
        stats["max_flood_depth_m"] = stats["max"]
        stats["flooded_days"] = int(np.sum(valid > 0.01))  # >1cm threshold
    elif var_name == "fldfrc":
        stats["max_flood_fraction"] = stats["max"]
        stats["mean_flood_fraction"] = stats["mean"]

    return stats


def extract_spatial_stats(output_dir, variable, start_year, end_year):
    """Compute spatial statistics over the entire domain for each time step."""
    print(f"\n  Spatial statistics for: {variable}")

    all_stats = []

    for year in range(start_year, end_year + 1):
        nc_file = os.path.join(output_dir, f"o_{variable}{year}.nc")
        if not os.path.isfile(nc_file):
            print(f"  WARNING: {nc_file} not found")
            continue

        ds = xr.open_dataset(nc_file)
        data = ds[variable].values  # (time, lat, lon)
        times = ds.time.values

        for t in range(len(times)):
            snapshot = data[t, :, :]
            valid = snapshot[~np.isnan(snapshot)]
            if len(valid) == 0:
                continue

            stat = {
                "time": str(times[t])[:10],
                "spatial_mean": float(np.mean(valid)),
                "spatial_max": float(np.max(valid)),
                "spatial_min": float(np.min(valid)),
            }

            if variable == "flddph":
                stat["flooded_cells"] = int(np.sum(valid > 0.01))
                stat["total_cells"] = len(valid)
                stat["flooded_fraction"] = stat["flooded_cells"] / stat["total_cells"]
            elif variable == "outflw":
                stat["max_discharge_m3s"] = stat["spatial_max"]

            all_stats.append(stat)
        ds.close()

    return all_stats


def write_csv(results, csv_path):
    """Write extracted time series to CSV."""
    import csv

    # Determine all variable names
    var_names = list(results.keys())
    if not var_names:
        print("  No data to write")
        return

    # Use times from first variable
    first_var = var_names[0]
    times = results[first_var]["times"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = ["datetime"] + [f"{v}_value" for v in var_names]
        writer.writerow(header)

        # Data rows
        for i, t in enumerate(times):
            row = [str(t)[:10]]
            for var in var_names:
                if i < len(results[var]["values"]):
                    row.append(f"{results[var]['values'][i]:.6f}")
                else:
                    row.append("")
            writer.writerow(row)

    print(f"  CSV written: {csv_path} ({len(times)} rows)")


def write_spatial_csv(stats, csv_path):
    """Write spatial statistics to CSV."""
    import csv

    if not stats:
        print("  No spatial stats to write")
        return

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=stats[0].keys())
        writer.writeheader()
        writer.writerows(stats)

    print(f"  Spatial stats CSV: {csv_path} ({len(stats)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Parse CaMa-Flood output: extract time series and compute statistics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Variables:
  outflw   River discharge (m3/s) -- primary validation variable
  rivdph   River channel water depth (m)
  sfcelv   Water surface elevation (m ASL)
  flddph   Floodplain inundation depth (m)
  fldfrc   Floodplain inundation fraction (0-1)
  rivsto   River channel storage (m3)
"""
    )
    parser.add_argument("--output_dir", required=True,
                        help="CaMa-Flood output directory containing o_*.nc files")
    parser.add_argument("--variable", required=True,
                        help="Variable(s) to extract (comma-separated, e.g. outflw,flddph)")
    parser.add_argument("--lat", type=float, help="Target latitude for point extraction")
    parser.add_argument("--lon", type=float, help="Target longitude for point extraction")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--csv", help="Output CSV file path")
    parser.add_argument("--spatial_stats", action="store_true",
                        help="Compute spatial statistics instead of point extraction")
    parser.add_argument("--obs_csv", help="Observed discharge CSV for comparison (date,Q columns)")

    args = parser.parse_args()

    variables = [v.strip() for v in args.variable.split(",")]

    print(f"{'='*60}")
    print(f"  CaMa-Flood Output Parser")
    print(f"  Directory:  {args.output_dir}")
    print(f"  Variables:  {variables}")
    print(f"  Period:     {args.start_year}-{args.end_year}")
    print(f"{'='*60}")

    if not os.path.isdir(args.output_dir):
        print(f"ERROR: Output directory not found: {args.output_dir}")
        sys.exit(1)

    # List available output files
    nc_files = sorted([f for f in os.listdir(args.output_dir)
                       if f.endswith(".nc") and f.startswith("o_")])
    print(f"\n  Available output files: {len(nc_files)}")
    available_vars = set()
    for f in nc_files:
        # Parse variable name from o_{var}{year}.nc pattern
        # e.g., o_outflw2003.nc -> outflw
        base = f[2:]  # strip "o_"
        base = base.rsplit(".", 1)[0]  # strip ".nc"
        # Remove trailing digits (year)
        var = base.rstrip("0123456789")
        if var:
            available_vars.add(var)
    print(f"  Available variables: {sorted(available_vars)}")

    if args.spatial_stats:
        # Spatial statistics mode
        for var in variables:
            stats = extract_spatial_stats(args.output_dir, var,
                                          args.start_year, args.end_year)
            if stats:
                # Print summary
                max_vals = [s.get("spatial_max", 0) for s in stats]
                print(f"\n  {var} spatial summary:")
                print(f"    Time steps: {len(stats)}")
                print(f"    Overall max: {max(max_vals):.2f}")

                if args.csv:
                    csv_path = args.csv.replace(".csv", f"_{var}_spatial.csv")
                    write_spatial_csv(stats, csv_path)
    else:
        # Point extraction mode
        if args.lat is None or args.lon is None:
            print("ERROR: --lat and --lon required for point extraction")
            print("       Use --spatial_stats for domain-wide statistics")
            sys.exit(1)

        results = extract_point_timeseries(args.output_dir, variables,
                                            args.lat, args.lon,
                                            args.start_year, args.end_year)

        # Print statistics
        for var, data in results.items():
            stats = compute_statistics(data["values"], var)
            print(f"\n  {var} statistics at ({data['lat']:.4f}, {data['lon']:.4f}):")
            for key, val in stats.items():
                if isinstance(val, float):
                    print(f"    {key}: {val:.4f}")
                else:
                    print(f"    {key}: {val}")

        # Write CSV
        if args.csv and results:
            write_csv(results, args.csv)

        # Compare with observations if provided
        if args.obs_csv and "outflw" in results:
            compare_with_obs(results["outflw"], args.obs_csv)


def compare_with_obs(sim_data, obs_csv_path):
    """Compare simulated discharge with observed data."""
    import csv

    print(f"\n  --- Comparison with Observations ---")
    print(f"  Observed data: {obs_csv_path}")

    if not os.path.isfile(obs_csv_path):
        print(f"  ERROR: Observed CSV not found: {obs_csv_path}")
        return

    # Read observed data
    obs_dates = []
    obs_values = []
    with open(obs_csv_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            try:
                date = row[0].strip()
                val = float(row[1])
                obs_dates.append(date)
                obs_values.append(val)
            except (IndexError, ValueError):
                continue

    obs_values = np.array(obs_values)
    print(f"  Observed: {len(obs_values)} values, "
          f"range [{obs_values.min():.1f}, {obs_values.max():.1f}] m3/s")

    # Match dates between sim and obs
    sim_times = sim_data["times"]
    sim_values = sim_data["values"]

    # Convert sim times to date strings
    sim_date_strs = [str(t)[:10] for t in sim_times]

    matched_sim = []
    matched_obs = []

    for i, date in enumerate(obs_dates):
        if date in sim_date_strs:
            sim_idx = sim_date_strs.index(date)
            matched_sim.append(sim_values[sim_idx])
            matched_obs.append(obs_values[i])

    if len(matched_sim) < 10:
        print(f"  WARNING: Only {len(matched_sim)} matching dates. Cannot compute metrics.")
        return

    matched_sim = np.array(matched_sim)
    matched_obs = np.array(matched_obs)

    # Compute NSE
    nse = 1.0 - (np.sum((matched_obs - matched_sim)**2) /
                  np.sum((matched_obs - np.mean(matched_obs))**2))

    # Compute PBIAS
    pbias = 100.0 * np.sum(matched_sim - matched_obs) / np.sum(matched_obs)

    # Compute KGE
    r = np.corrcoef(matched_sim, matched_obs)[0, 1]
    alpha = np.std(matched_sim) / np.std(matched_obs)
    beta = np.mean(matched_sim) / np.mean(matched_obs)
    kge = 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

    print(f"\n  Performance Metrics ({len(matched_sim)} matched days):")
    print(f"    NSE:   {nse:.4f}")
    print(f"    PBIAS: {pbias:.2f}%")
    print(f"    KGE:   {kge:.4f}")
    print(f"    r:     {r:.4f}")

    if nse < 0:
        print("    NOTE: NSE < 0 means model performs worse than mean observed.")
    elif nse > 0.5:
        print("    NOTE: NSE > 0.5 is generally considered acceptable.")


if __name__ == "__main__":
    main()
