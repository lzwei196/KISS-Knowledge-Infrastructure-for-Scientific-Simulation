#!/usr/bin/env python3
"""
find_dams_in_basin.py — Find GRanD dams within a basin boundary.

Usage:
    # Using shapefile:
    python find_dams_in_basin.py --shp data/shp/bengbu_shp/bengbu_clip.shp \
        --grand model/cmf_v420_pkg/map/data/GRanD_allocated.csv

    # Using basin_grid.nc (bounding box):
    python find_dams_in_basin.py --grid outputs/bengbu/vic_temp/grid/basin_grid.nc \
        --grand model/cmf_v420_pkg/map/data/GRanD_allocated.csv

    # With buffer (km) around basin boundary:
    python find_dams_in_basin.py --shp basin.shp --grand GRanD.csv --buffer_km 10

Output:
    JSON list of dams found within the basin, with properties from GRanD.
    Exit codes: 0 = dams found, 1 = no dams found, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_grand_csv(grand_path):
    """Load GRanD dam database from CSV."""
    df = pd.read_csv(grand_path)
    required = ["ID", "lat_alloc", "lon_alloc", "DamName", "CAP_MCM"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"GRanD CSV missing columns: {missing}")
    return df


def load_basin_from_shapefile(shp_path, buffer_km=0.0):
    """Load basin boundary from shapefile, optionally buffered."""
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    basin_geom = gdf.geometry.unary_union

    if buffer_km > 0:
        # Approximate buffer in degrees (1 deg ~ 111 km)
        buffer_deg = buffer_km / 111.0
        basin_geom = basin_geom.buffer(buffer_deg)

    # Compute basin area in km2
    gdf_proj = gdf.to_crs(gdf.estimate_utm_crs())
    area_km2 = gdf_proj.geometry.area.sum() / 1e6

    bounds = basin_geom.bounds  # (minx, miny, maxx, maxy)
    return basin_geom, bounds, area_km2


def load_basin_from_grid(grid_path, buffer_km=0.0):
    """Load basin extent from VIC basin_grid.nc."""
    import xarray as xr
    from shapely.geometry import box

    ds = xr.open_dataset(grid_path)

    # Try common variable names for lat/lon
    lat_names = ["lat", "latitude", "y"]
    lon_names = ["lon", "longitude", "x"]
    lats = lons = None
    for ln in lat_names:
        if ln in ds.coords or ln in ds:
            lats = ds[ln].values
            break
    for ln in lon_names:
        if ln in ds.coords or ln in ds:
            lons = ds[ln].values
            break
    if lats is None or lons is None:
        raise ValueError(f"Cannot find lat/lon in grid. Available: {list(ds.coords) + list(ds.data_vars)}")

    # Get resolution from grid spacing
    if len(lats) > 1:
        res = abs(float(lats[1] - lats[0]))
    else:
        res = 0.25  # fallback

    half = res / 2.0
    buffer_deg = buffer_km / 111.0

    minlat = float(np.min(lats)) - half - buffer_deg
    maxlat = float(np.max(lats)) + half + buffer_deg
    minlon = float(np.min(lons)) - half - buffer_deg
    maxlon = float(np.max(lons)) + half + buffer_deg

    basin_geom = box(minlon, minlat, maxlon, maxlat)
    bounds = (minlon, minlat, maxlon, maxlat)

    # Rough area from bounding box
    dlat = maxlat - minlat
    dlon = maxlon - minlon
    area_km2 = dlat * 111.0 * dlon * 111.0 * np.cos(np.radians((minlat + maxlat) / 2))

    ds.close()
    return basin_geom, bounds, area_km2


def find_dams(grand_df, basin_geom, bounds):
    """Find dams within basin geometry using two-phase filter."""
    from shapely.geometry import Point

    minlon, minlat, maxlon, maxlat = bounds

    # Phase 1: Bounding box filter (fast)
    mask = (
        (grand_df["lat_alloc"] >= minlat) &
        (grand_df["lat_alloc"] <= maxlat) &
        (grand_df["lon_alloc"] >= minlon) &
        (grand_df["lon_alloc"] <= maxlon)
    )
    candidates = grand_df[mask].copy()

    if len(candidates) == 0:
        return []

    # Phase 2: Point-in-polygon test (precise)
    results = []
    for _, row in candidates.iterrows():
        pt = Point(row["lon_alloc"], row["lat_alloc"])
        if basin_geom.contains(pt):
            dam_info = {
                "grand_id": int(row["ID"]),
                "name": str(row["DamName"]),
                "lat": float(row["lat_alloc"]),
                "lon": float(row["lon_alloc"]),
                "capacity_mcm": float(row["CAP_MCM"]) if pd.notna(row["CAP_MCM"]) else None,
                "dam_height_m": float(row["DAM_HGT_M"]) if pd.notna(row.get("DAM_HGT_M")) else None,
                "river_name": str(row.get("RiverName", "")) if pd.notna(row.get("RiverName")) else None,
                "year_completed": int(row["YEAR"]) if pd.notna(row.get("YEAR")) and row.get("YEAR", -99) != -99 else None,
                "elevation_masl": float(row["ELEV_MASL"]) if pd.notna(row.get("ELEV_MASL")) and row.get("ELEV_MASL", -99) != -99 else None,
                "upstream_area_km2": float(row["area_alloc"]) if pd.notna(row.get("area_alloc")) else None,
                "lat_original": float(row["lat_ori"]) if pd.notna(row.get("lat_ori")) else None,
                "lon_original": float(row["lon_ori"]) if pd.notna(row.get("lon_ori")) else None,
            }
            results.append(dam_info)

    # Sort by capacity (largest first)
    results.sort(key=lambda d: d["capacity_mcm"] or 0, reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Find GRanD dams within a basin boundary"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--shp", type=str,
                       help="Path to basin boundary shapefile (.shp)")
    group.add_argument("--grid", type=str,
                       help="Path to VIC basin_grid.nc (uses bounding box)")

    parser.add_argument("--grand", type=str, required=True,
                        help="Path to GRanD_allocated.csv")
    parser.add_argument("--buffer_km", type=float, default=0.0,
                        help="Buffer around basin boundary in km (default: 0)")
    parser.add_argument("--min_capacity_mcm", type=float, default=0.0,
                        help="Minimum dam capacity in MCM to include (default: 0)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    # Validate inputs
    grand_path = Path(args.grand)
    if not grand_path.exists():
        print(json.dumps({"error": f"GRanD CSV not found: {args.grand}"}))
        sys.exit(2)

    try:
        grand_df = load_grand_csv(grand_path)
    except Exception as e:
        print(json.dumps({"error": f"Failed to load GRanD CSV: {e}"}))
        sys.exit(2)

    try:
        if args.shp:
            shp_path = Path(args.shp)
            if not shp_path.exists():
                print(json.dumps({"error": f"Shapefile not found: {args.shp}"}))
                sys.exit(2)
            basin_geom, bounds, area_km2 = load_basin_from_shapefile(
                args.shp, buffer_km=args.buffer_km
            )
            source = "shapefile"
        else:
            grid_path = Path(args.grid)
            if not grid_path.exists():
                print(json.dumps({"error": f"Grid file not found: {args.grid}"}))
                sys.exit(2)
            basin_geom, bounds, area_km2 = load_basin_from_grid(
                args.grid, buffer_km=args.buffer_km
            )
            source = "grid_bbox"
    except Exception as e:
        print(json.dumps({"error": f"Failed to load basin boundary: {e}"}))
        sys.exit(3)

    # Find dams
    dams = find_dams(grand_df, basin_geom, bounds)

    # Filter by minimum capacity
    if args.min_capacity_mcm > 0:
        dams = [d for d in dams if (d["capacity_mcm"] or 0) >= args.min_capacity_mcm]

    result = {
        "status": "OK" if dams else "NO_DAMS",
        "basin_source": source,
        "basin_area_km2": round(area_km2, 1),
        "basin_bounds": {
            "min_lat": round(bounds[1], 4),
            "max_lat": round(bounds[3], 4),
            "min_lon": round(bounds[0], 4),
            "max_lon": round(bounds[2], 4),
        },
        "buffer_km": args.buffer_km,
        "grand_total_dams": len(grand_df),
        "dams_found": len(dams),
        "dams": dams,
    }

    output_str = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_str)
        print(f"Wrote {len(dams)} dams to {args.output}")
    else:
        print(output_str)

    sys.exit(0 if dams else 1)


if __name__ == "__main__":
    main()
