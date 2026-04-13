#!/usr/bin/env python3
"""
inject_releases_to_cama.py — Inject Pywr reservoir releases into CaMa-Flood runoff NetCDF.

Replaces VIC runoff at the dam's downstream grid cell with Pywr-regulated release,
enabling re-running CaMa-Flood with reservoir-regulated flow.

Logic:
    1. Load Pywr release timeseries (m3/s)
    2. Load CaMa runoff NetCDF (mm/day per grid cell)
    3. Identify dam grid cell (nearest to dam lat/lon)
    4. Convert release: Q_mm = Q_m3s * CMFD_PRECIP_KGM2S_TO_MMDAY / cell_area_m2 * 1000
    5. Replace runoff at dam cell with regulated release
    6. Write modified NetCDF

Usage:
    python inject_releases_to_cama.py \
        --release_csv results/release_timeseries.csv \
        --release_col "Meishan_release_m3s" \
        --cama_nc outputs/bengbu/cama_input/bengbu_runoff_1d_1985.nc \
        --dam_lat 31.43 --dam_lon 115.92 \
        --output outputs/bengbu/cama_input_regulated/bengbu_runoff_1d_1985.nc

    # Multiple years:
    python inject_releases_to_cama.py \
        --release_csv results/release_timeseries.csv \
        --release_col "Meishan_release_m3s" \
        --cama_dir outputs/bengbu/cama_input \
        --dam_lat 31.43 --dam_lon 115.92 \
        --output_dir outputs/bengbu/cama_input_regulated/ \
        --start_year 1980 --end_year 1990

Output:
    Modified CaMa-Flood runoff NetCDF files with regulated flow.
    Exit codes: 0 = success, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY


def find_nearest_cell(lats, lons, target_lat, target_lon):
    """Find nearest grid cell to target coordinates. Returns (i_lat, i_lon)."""
    lat_idx = np.argmin(np.abs(np.array(lats) - target_lat))
    lon_idx = np.argmin(np.abs(np.array(lons) - target_lon))
    return int(lat_idx), int(lon_idx)


def compute_cell_area_m2(lat, resolution):
    """Compute grid cell area in m2 for a given latitude and resolution."""
    R = 6371000.0
    lat_rad = np.radians(lat)
    dlat = np.radians(resolution)
    dlon = np.radians(resolution)
    area = (R ** 2) * dlon * abs(np.sin(lat_rad + dlat / 2) - np.sin(lat_rad - dlat / 2))
    return abs(area)


def inject_single_file(nc_path, release_series, dam_lat, dam_lon, output_path):
    """Inject releases into a single CaMa runoff NetCDF file."""
    import xarray as xr

    ds = xr.open_dataset(nc_path)

    # Identify coordinate names
    lat_name = "lat" if "lat" in ds.coords else "latitude" if "latitude" in ds.coords else None
    lon_name = "lon" if "lon" in ds.coords else "longitude" if "longitude" in ds.coords else None
    time_name = "time" if "time" in ds.coords else "t" if "t" in ds.coords else None

    if lat_name is None or lon_name is None:
        raise ValueError(f"Cannot find lat/lon coordinates in {nc_path}")

    lats = ds.coords[lat_name].values
    lons = ds.coords[lon_name].values

    # Find runoff variable
    runoff_var = None
    for vname in ds.data_vars:
        if "runoff" in vname.lower() or "routtot" in vname.lower():
            runoff_var = vname
            break
    if runoff_var is None:
        # Use first data variable
        runoff_var = list(ds.data_vars)[0]

    # Get resolution
    if len(lats) > 1:
        resolution = abs(float(lats[1] - lats[0]))
    else:
        resolution = 0.25

    # Find dam cell
    lat_idx, lon_idx = find_nearest_cell(lats, lons, dam_lat, dam_lon)
    cell_lat = float(lats[lat_idx])
    cell_lon = float(lons[lon_idx])
    cell_area = compute_cell_area_m2(cell_lat, resolution)

    # Copy dataset for modification
    ds_out = ds.copy(deep=True)

    # Get time values
    if time_name:
        times = pd.DatetimeIndex(ds.coords[time_name].values)
    else:
        # Assume daily from Jan 1
        n_times = ds[runoff_var].shape[0]
        year = int(nc_path.stem.split("_")[-1])
        times = pd.date_range(f"{year}-01-01", periods=n_times, freq="D")

    # Inject releases
    modified_count = 0
    original_values = []
    new_values = []

    for t_idx, date in enumerate(times):
        date_str = date.strftime("%Y-%m-%d")
        if date in release_series.index:
            release_m3s = float(release_series.loc[date])

            # Convert m3/s to mm/day: Q * 86400 / area_m2 * 1000
            release_mm = release_m3s * CMFD_PRECIP_KGM2S_TO_MMDAY / cell_area * 1000.0

            # Ensure non-negative
            release_mm = max(0.0, release_mm)

            # Store original for logging
            if time_name:
                orig_val = float(ds_out[runoff_var].values[t_idx, lat_idx, lon_idx])
            else:
                orig_val = float(ds_out[runoff_var].values[t_idx, lat_idx, lon_idx])

            original_values.append(orig_val)
            new_values.append(release_mm)

            # Replace
            ds_out[runoff_var].values[t_idx, lat_idx, lon_idx] = release_mm
            modified_count += 1

    # Save
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ds_out.to_netcdf(output_path)
    ds.close()
    ds_out.close()

    info = {
        "input_file": str(nc_path),
        "output_file": str(output_path),
        "dam_cell": {"lat": cell_lat, "lon": cell_lon,
                     "lat_idx": lat_idx, "lon_idx": lon_idx},
        "cell_area_km2": round(cell_area / 1e6, 2),
        "timesteps_modified": modified_count,
        "original_mean_mm": round(float(np.mean(original_values)), 4) if original_values else None,
        "regulated_mean_mm": round(float(np.mean(new_values)), 4) if new_values else None,
    }

    return info


def main():
    parser = argparse.ArgumentParser(
        description="Inject Pywr releases into CaMa-Flood runoff NetCDF"
    )

    parser.add_argument("--release_csv", type=str, required=True,
                        help="Pywr release timeseries CSV")
    parser.add_argument("--release_col", type=str, default=None,
                        help="Column name in release CSV (auto-detected if not given)")

    # Single file mode
    parser.add_argument("--cama_nc", type=str, default=None,
                        help="Single CaMa runoff NetCDF file")
    parser.add_argument("--output", type=str, default=None,
                        help="Output NetCDF path (single file mode)")

    # Multi-file mode
    parser.add_argument("--cama_dir", type=str, default=None,
                        help="Directory with CaMa runoff NetCDF files")
    parser.add_argument("--output_dir", type=str, default=None,
                        help="Output directory (multi-file mode)")
    parser.add_argument("--start_year", type=int, default=None,
                        help="Start year (multi-file mode)")
    parser.add_argument("--end_year", type=int, default=None,
                        help="End year (multi-file mode)")

    parser.add_argument("--dam_lat", type=float, required=True,
                        help="Dam latitude")
    parser.add_argument("--dam_lon", type=float, required=True,
                        help="Dam longitude")

    args = parser.parse_args()

    try:
        # Load release data
        release_df = pd.read_csv(args.release_csv, parse_dates=["date"],
                                  index_col="date")

        # Auto-detect release column
        if args.release_col:
            if args.release_col not in release_df.columns:
                print(json.dumps({
                    "error": f"Column '{args.release_col}' not found",
                    "available": list(release_df.columns),
                }))
                sys.exit(2)
            release_col = args.release_col
        else:
            # Pick first column with "release" in name
            candidates = [c for c in release_df.columns if "release" in c.lower()]
            if not candidates:
                candidates = list(release_df.columns)
            release_col = candidates[0]

        release_series = release_df[release_col]

        results = []

        if args.cama_nc:
            # Single file mode
            if not args.output:
                print(json.dumps({"error": "Single file mode requires --output"}))
                sys.exit(2)

            info = inject_single_file(
                args.cama_nc, release_series,
                args.dam_lat, args.dam_lon, args.output
            )
            results.append(info)

        elif args.cama_dir:
            # Multi-file mode
            if not args.output_dir:
                print(json.dumps({"error": "Multi-file mode requires --output_dir"}))
                sys.exit(2)

            cama_dir = Path(args.cama_dir)
            nc_files = sorted(cama_dir.glob("*.nc"))

            if args.start_year and args.end_year:
                # Filter by year
                filtered = []
                for f in nc_files:
                    for y in range(args.start_year, args.end_year + 1):
                        if str(y) in f.name:
                            filtered.append(f)
                            break
                nc_files = filtered

            for nc_file in nc_files:
                out_path = Path(args.output_dir) / nc_file.name
                info = inject_single_file(
                    str(nc_file), release_series,
                    args.dam_lat, args.dam_lon, str(out_path)
                )
                results.append(info)

        else:
            print(json.dumps({"error": "Provide --cama_nc or --cama_dir"}))
            sys.exit(2)

        # Check for negative runoff (diagnostic)
        negative_warning = False
        for r in results:
            if r.get("regulated_mean_mm") is not None and r["regulated_mean_mm"] < 0:
                negative_warning = True

        summary = {
            "status": "WARNING" if negative_warning else "OK",
            "release_column": release_col,
            "files_processed": len(results),
            "dam_location": {"lat": args.dam_lat, "lon": args.dam_lon},
            "results": results,
        }

        if negative_warning:
            summary["warning"] = ("Negative runoff values detected after injection. "
                                  "This may indicate unit conversion error.")

        print(json.dumps(summary, indent=2))
        sys.exit(0)

    except Exception as e:
        import traceback
        print(json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "status": "FAIL",
        }))
        sys.exit(3)


if __name__ == "__main__":
    main()
