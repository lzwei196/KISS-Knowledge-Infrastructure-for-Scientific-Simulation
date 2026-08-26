#!/usr/bin/env python3
"""
convert_vic_to_inflow.py — Convert VIC runoff/baseflow output to reservoir inflow timeseries.

Identifies VIC grid cells upstream of a dam and sums (runoff + baseflow) * cell_area
to produce daily inflow in m3/s.

Upstream identification methods:
1. "all" — all VIC grid cells (for single-reservoir basin)
2. "upstream_lat" — cells with lat > dam_lat (simple, northern hemisphere)
3. "nearest" — only the cell containing the dam (small catchments)
4. "flow_direction" — use DEM flow direction (not implemented yet, TODO)

Usage:
    python convert_vic_to_inflow.py \
        --vic_dir outputs/bengbu/vic_result \
        --grid_nc outputs/bengbu/vic_temp/grid/basin_grid.nc \
        --dam_lat 31.43 --dam_lon 115.92 \
        --method all \
        --start_year 1980 --end_year 1990 \
        --output outputs/bengbu/pywr_inflow.csv

Output:
    CSV with columns: date, inflow_m3s, runoff_mm, baseflow_mm
    Exit codes: 0 = success, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY


def parse_vic_flux_file(filepath, start_year, end_year):
    """
    Parse a VIC classic flux output file.

    VIC classic output has columns (after preprocess: 7 cols):
        year, month, day, runoff, baseflow, evap, soil_moist
    Or raw (22+ cols):
        year, month, day, prec, evap, runoff, baseflow, ...

    We detect format by column count.
    Returns DataFrame with date index, runoff (mm/day), baseflow (mm/day).
    """
    # Read with pandas to handle non-'#' header lines
    raw = pd.read_csv(filepath, sep=r'\s+', comment='#', header=None)
    # If first row is non-numeric (column names), skip it
    try:
        raw.iloc[0, 0] = int(raw.iloc[0, 0])
    except (ValueError, TypeError):
        raw = raw.iloc[1:].reset_index(drop=True)
    data = raw.values.astype(float)

    ncols = data.shape[1]

    if ncols >= 22:
        # Raw VIC 22-col output (with # comments and text header):
        # 0:YEAR 1:MONTH 2:DAY 3:OUT_PREC 4:OUT_RAINF 5:OUT_SNOWF 6:OUT_AIR_TEMP
        # 7:OUT_SWDOWN 8:OUT_LWDOWN 9:OUT_PRESSURE 10:OUT_WIND 11:OUT_DENSITY
        # 12:OUT_REL_HUMID 13:OUT_QAIR 14:OUT_VP 15:OUT_VPD
        # 16:OUT_RUNOFF 17:OUT_BASEFLOW 18:OUT_EVAP ...
        years = data[:, 0].astype(int)
        months = data[:, 1].astype(int)
        days = data[:, 2].astype(int)
        runoff = data[:, 16]
        baseflow = data[:, 17]
    elif ncols >= 7:
        # Preprocessed: col 0-2=date, col 3=runoff, col 4=baseflow
        years = data[:, 0].astype(int)
        months = data[:, 1].astype(int)
        days = data[:, 2].astype(int)
        runoff = data[:, 3]
        baseflow = data[:, 4]
    elif ncols >= 5:
        # Minimal: year, month, day, runoff, baseflow
        years = data[:, 0].astype(int)
        months = data[:, 1].astype(int)
        days = data[:, 2].astype(int)
        runoff = data[:, 3]
        baseflow = data[:, 4]
    else:
        raise ValueError(f"Unexpected column count {ncols} in {filepath}")

    dates = [datetime(int(y), int(m), int(d))
             for y, m, d in zip(years, months, days)]

    df = pd.DataFrame({
        "date": dates,
        "runoff_mm": runoff,
        "baseflow_mm": baseflow,
    })
    df = df.set_index("date")

    # Filter by year range
    mask = (df.index.year >= start_year) & (df.index.year <= end_year)
    df = df[mask]

    return df


def compute_cell_area_m2(lat, lon, resolution):
    """
    Compute area of a lat/lon grid cell in m2.
    Uses spherical approximation.
    """
    R = 6371000.0  # Earth radius in meters
    lat_rad = np.radians(lat)
    dlat = np.radians(resolution)
    dlon = np.radians(resolution)

    area = (R ** 2) * dlon * (
        np.sin(lat_rad + dlat / 2) - np.sin(lat_rad - dlat / 2)
    )
    return abs(area)


def identify_upstream_cells(grid_lats, grid_lons, dam_lat, dam_lon, method):
    """
    Identify which VIC grid cells are upstream of the dam.

    Returns list of (lat, lon) tuples.
    """
    cells = list(zip(grid_lats, grid_lons))

    if method == "all":
        return cells

    elif method == "upstream_lat":
        # Simple: all cells with lat > dam_lat (assumes N hemisphere, river flows south)
        return [(la, lo) for la, lo in cells if la > dam_lat]

    elif method == "nearest":
        # Only the cell containing the dam
        if not cells:
            return []
        dists = [(la - dam_lat)**2 + (lo - dam_lon)**2 for la, lo in cells]
        idx = np.argmin(dists)
        return [cells[idx]]

    else:
        raise ValueError(f"Unknown method '{method}'. Use: all, upstream_lat, nearest")


def load_grid_coordinates(grid_nc_path):
    """Load grid cell coordinates from basin_grid.nc."""
    import xarray as xr

    ds = xr.open_dataset(grid_nc_path)

    # Try to find coordinate variables
    if "lat" in ds.coords and "lon" in ds.coords:
        lats = ds.coords["lat"].values
        lons = ds.coords["lon"].values
    elif "latitude" in ds.coords and "longitude" in ds.coords:
        lats = ds.coords["latitude"].values
        lons = ds.coords["longitude"].values
    elif "y" in ds.coords and "x" in ds.coords:
        # HydroCraft basin_grid.nc uses y/x for lat/lon
        lats = ds.coords["y"].values
        lons = ds.coords["x"].values
    else:
        raise ValueError("Cannot find lat/lon coordinates in grid file")

    # Get resolution
    if len(lats) > 1:
        resolution = abs(float(lats[1] - lats[0]))
    else:
        resolution = 0.25

    # Check if there's a mask variable
    mask_var = None
    for vname in ds.data_vars:
        if "mask" in vname.lower() or "basin" in vname.lower():
            mask_var = vname
            break

    if mask_var and ds[mask_var].ndim == 2:
        # 2D mask: extract active cells
        mask = ds[mask_var].values
        active_lats = []
        active_lons = []
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                if mask[i, j] > 0:
                    active_lats.append(float(lat))
                    active_lons.append(float(lon))
    else:
        # All combinations are active (1D coordinate lists mean it's a list of cells)
        if ds[list(ds.data_vars)[0]].ndim == 1:
            # 1D: lat and lon are cell coordinates directly
            active_lats = [float(l) for l in lats]
            active_lons = [float(l) for l in lons]
        else:
            # 2D grid: all cells
            active_lats = []
            active_lons = []
            for lat in lats:
                for lon in lons:
                    active_lats.append(float(lat))
                    active_lons.append(float(lon))

    ds.close()
    return active_lats, active_lons, resolution


def main():
    parser = argparse.ArgumentParser(
        description="Convert VIC output to reservoir inflow timeseries"
    )
    parser.add_argument("--vic_dir", type=str, required=True,
                        help="VIC result directory (contains flux files)")
    parser.add_argument("--grid_nc", type=str, required=True,
                        help="Basin grid NetCDF (for cell coordinates and resolution)")
    parser.add_argument("--dam_lat", type=float, required=True,
                        help="Dam latitude")
    parser.add_argument("--dam_lon", type=float, required=True,
                        help="Dam longitude")
    parser.add_argument("--method", type=str, default="all",
                        choices=["all", "upstream_lat", "nearest"],
                        help="Upstream cell identification method (default: all)")
    parser.add_argument("--start_year", type=int, required=True,
                        help="Start year for inflow extraction")
    parser.add_argument("--end_year", type=int, required=True,
                        help="End year for inflow extraction")
    parser.add_argument("--flux_prefix", type=str, default=None,
                        help="VIC flux file prefix (auto-detected if not given)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    parser.add_argument("--output_json", type=str, default=None,
                        help="Output summary JSON (optional)")

    args = parser.parse_args()

    vic_dir = Path(args.vic_dir)
    if not vic_dir.exists():
        print(json.dumps({"error": f"VIC dir not found: {args.vic_dir}"}))
        sys.exit(2)

    grid_nc = Path(args.grid_nc)
    if not grid_nc.exists():
        print(json.dumps({"error": f"Grid file not found: {args.grid_nc}"}))
        sys.exit(2)

    try:
        # Load grid
        grid_lats, grid_lons, resolution = load_grid_coordinates(str(grid_nc))

        # Identify upstream cells
        upstream_cells = identify_upstream_cells(
            grid_lats, grid_lons,
            args.dam_lat, args.dam_lon,
            args.method
        )

        if not upstream_cells:
            print(json.dumps({"error": "No upstream cells identified"}))
            sys.exit(1)

        # Detect flux file prefix
        flux_files = sorted(vic_dir.glob("*.txt")) + sorted(vic_dir.glob("*.csv"))
        if not flux_files:
            print(json.dumps({"error": f"No flux files found in {vic_dir}"}))
            sys.exit(2)

        # Auto-detect prefix from first file
        sample_name = flux_files[0].name
        # Pattern: prefix_LAT_LON.txt
        parts = sample_name.rsplit("_", 2)
        if len(parts) >= 3:
            detected_prefix = parts[0] + "_"
        else:
            detected_prefix = ""

        prefix = args.flux_prefix if args.flux_prefix else detected_prefix

        # Process each upstream cell
        total_inflow_df = None
        cells_found = 0
        cells_missing = 0

        for lat, lon in upstream_cells:
            # Construct filename with 4-decimal formatting
            fname = f"{prefix}{lat:.4f}_{lon:.4f}.txt"
            fpath = vic_dir / fname

            if not fpath.exists():
                # Try other common formats
                for fmt in [
                    f"{prefix}{lat:.4f}_{lon:.4f}.txt",
                    f"{prefix}{abs(lat):.4f}_{abs(lon):.4f}.txt",
                    f"fluxes_{lat:.4f}_{lon:.4f}.txt",
                ]:
                    fpath = vic_dir / fmt
                    if fpath.exists():
                        break

            if not fpath.exists():
                cells_missing += 1
                continue

            cells_found += 1
            cell_df = parse_vic_flux_file(fpath, args.start_year, args.end_year)

            # Compute cell area
            cell_area = compute_cell_area_m2(lat, lon, resolution)

            # Convert mm/day to m3/s: (mm/day * cell_area_m2) / (1000 * 86400)
            cell_df["inflow_m3s"] = (
                (cell_df["runoff_mm"] + cell_df["baseflow_mm"])
                * cell_area / (1000.0 * CMFD_PRECIP_KGM2S_TO_MMDAY)
            )
            cell_df["runoff_m3s"] = cell_df["runoff_mm"] * cell_area / (1000.0 * CMFD_PRECIP_KGM2S_TO_MMDAY)
            cell_df["baseflow_m3s"] = cell_df["baseflow_mm"] * cell_area / (1000.0 * CMFD_PRECIP_KGM2S_TO_MMDAY)

            if total_inflow_df is None:
                total_inflow_df = cell_df[["inflow_m3s", "runoff_m3s", "baseflow_m3s"]].copy()
            else:
                total_inflow_df["inflow_m3s"] += cell_df["inflow_m3s"]
                total_inflow_df["runoff_m3s"] += cell_df["runoff_m3s"]
                total_inflow_df["baseflow_m3s"] += cell_df["baseflow_m3s"]

        if total_inflow_df is None or len(total_inflow_df) == 0:
            print(json.dumps({
                "error": "No valid flux data found",
                "cells_tried": len(upstream_cells),
                "cells_missing": cells_missing,
            }))
            sys.exit(3)

        # Save CSV
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        total_inflow_df.index.name = "date"
        total_inflow_df.to_csv(out_path, float_format="%.4f")

        # Summary statistics
        summary = {
            "status": "OK",
            "method": args.method,
            "upstream_cells_total": len(upstream_cells),
            "cells_found": cells_found,
            "cells_missing": cells_missing,
            "resolution_deg": resolution,
            "period": f"{args.start_year}-{args.end_year}",
            "days": len(total_inflow_df),
            "statistics": {
                "mean_inflow_m3s": round(float(total_inflow_df["inflow_m3s"].mean()), 2),
                "max_inflow_m3s": round(float(total_inflow_df["inflow_m3s"].max()), 2),
                "min_inflow_m3s": round(float(total_inflow_df["inflow_m3s"].min()), 4),
                "mean_annual_volume_mcm": round(
                    float(total_inflow_df["inflow_m3s"].mean() * CMFD_PRECIP_KGM2S_TO_MMDAY * 365.25 / 1e6), 1
                ),
                "runoff_fraction": round(
                    float(total_inflow_df["runoff_m3s"].sum() /
                          max(total_inflow_df["inflow_m3s"].sum(), 1e-10)), 3
                ),
            },
            "output_file": str(out_path),
        }

        if args.output_json:
            with open(args.output_json, "w") as f:
                json.dump(summary, f, indent=2)

        print(json.dumps(summary, indent=2))
        sys.exit(0)

    except Exception as e:
        import traceback
        print(json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc(),
            "status": "FAIL"
        }))
        sys.exit(3)


if __name__ == "__main__":
    main()
