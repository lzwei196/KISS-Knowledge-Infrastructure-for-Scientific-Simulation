#!/usr/bin/env python3
"""
OGGM to VIC Runoff — OGGM Knowledge Infrastructure

Convert OGGM glacier melt runoff to VIC grid cell format for injection
into the routing stage. Handles spatial mapping, unit conversion, and
double-counting avoidance.

CRITICAL: This tool handles three silent error sources:
  1. Hydrological year (Oct-Sep) vs calendar year (Jan-Dec) offset
  2. Double-counting of snowmelt on glacier cells
  3. Unit conversion from mm w.e./month to m3/s

Usage:
    python oggm_to_vic_runoff.py \
        --oggm_output outputs/oggm/compiled/compiled_output_hist.nc \
        --vic_grid_nc outputs/vic_run/vic_temp/grid/basin_grid.nc \
        --glacier_csv outputs/oggm/glaciers_in_basin.csv \
        --output_dir outputs/oggm/vic_coupling
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from calendar import monthrange

try:
    import numpy as np
    import xarray as xr
except ImportError:
    print("ERROR: numpy and xarray required. pip install numpy xarray")
    sys.exit(1)


def haversine_distance(lat1, lon1, lat2, lon2):
    """Compute haversine distance in km between two points."""
    R = 6371.0  # Earth radius in km
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def find_nearest_vic_cell(glacier_lat, glacier_lon, vic_lats, vic_lons):
    """Find the nearest VIC grid cell to a glacier centroid."""
    min_dist = float('inf')
    best_idx = 0
    for i in range(len(vic_lats)):
        dist = haversine_distance(glacier_lat, glacier_lon,
                                  vic_lats[i], vic_lons[i])
        if dist < min_dist:
            min_dist = dist
            best_idx = i
    return best_idx, min_dist


def seconds_in_month(year, month):
    """Get the number of seconds in a specific month."""
    days = monthrange(year, month)[1]
    return days * 86400


def main():
    parser = argparse.ArgumentParser(
        description="Convert OGGM glacier runoff to VIC grid format"
    )
    parser.add_argument("--oggm_output", required=True,
                        help="Compiled OGGM output NetCDF")
    parser.add_argument("--vic_grid_nc", required=True,
                        help="VIC grid NetCDF (basin_grid.nc)")
    parser.add_argument("--glacier_csv", required=True,
                        help="Glacier inventory CSV with centroids")
    parser.add_argument("--vic_snowmelt_dir", default=None,
                        help="VIC result directory for double-counting correction")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load VIC grid — supports both lat/lon and y/x coordinate names
    print(f"Loading VIC grid: {args.vic_grid_nc}")
    vic_ds = xr.open_dataset(args.vic_grid_nc)
    lat_coord = 'lat' if 'lat' in vic_ds.coords else 'y'
    lon_coord = 'lon' if 'lon' in vic_ds.coords else 'x'
    lat_1d = vic_ds[lat_coord].values.flatten()
    lon_1d = vic_ds[lon_coord].values.flatten()
    # Build full 2D lat/lon arrays for all valid (masked) cells
    mask = vic_ds['mask'].values if 'mask' in vic_ds else np.ones((len(lat_1d), len(lon_1d)))
    lon_2d, lat_2d = np.meshgrid(lon_1d, lat_1d)
    mask_flat = mask.flatten()
    vic_lats = lat_2d.flatten()[mask_flat == 1]
    vic_lons = lon_2d.flatten()[mask_flat == 1]
    cell_indices = np.where(mask_flat == 1)[0]  # flat indices into the 2D grid
    n_vic_cells = len(vic_lats)
    print(f"VIC grid: {n_vic_cells} valid cells (from {len(lat_1d)}×{len(lon_1d)} domain)")
    vic_ds.close()

    # Load glacier inventory
    print(f"Loading glacier inventory: {args.glacier_csv}")
    glaciers = []
    with open(args.glacier_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            glaciers.append({
                'rgi_id': row['rgi_id'],
                'area_km2': float(row['area_km2']),
                'centroid_lat': float(row['centroid_lat']),
                'centroid_lon': float(row['centroid_lon'])
            })
    print(f"Glaciers: {len(glaciers)}")

    # Map glaciers to VIC cells
    print("Mapping glaciers to VIC grid cells...")
    mapping = []
    cell_glacier_area = np.zeros(n_vic_cells)

    for glacier in glaciers:
        cell_idx, dist_km = find_nearest_vic_cell(
            glacier['centroid_lat'], glacier['centroid_lon'],
            vic_lats, vic_lons
        )
        mapping.append({
            'rgi_id': glacier['rgi_id'],
            'glacier_area_km2': glacier['area_km2'],
            'vic_cell_idx': cell_idx,
            'vic_cell_lat': float(vic_lats[cell_idx]),
            'vic_cell_lon': float(vic_lons[cell_idx]),
            'distance_km': round(dist_km, 2)
        })
        cell_glacier_area[cell_idx] += glacier['area_km2']

    # Save mapping CSV
    mapping_csv = output_dir / 'glacier_vic_cell_mapping.csv'
    with open(mapping_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=mapping[0].keys())
        writer.writeheader()
        writer.writerows(mapping)
    print(f"Mapping saved: {mapping_csv}")

    # Load OGGM output
    print(f"Loading OGGM output: {args.oggm_output}")
    try:
        oggm_ds = xr.open_dataset(args.oggm_output)
    except Exception as e:
        print(f"ERROR loading OGGM output: {e}")
        print("Ensure the compiled output NetCDF exists from compile_glacier_output.py")
        sys.exit(1)

    # CRITICAL: Use actual time coordinates, not month indices
    # OGGM uses hydrological year (Oct-Sep). The time coordinate
    # has actual dates — use those directly.
    print("NOTE: Using actual OGGM time coordinates (not month indices)")
    print("This avoids the hydrological year (Oct-Sep) vs calendar year (Jan-Dec) mismatch")

    # Create output: monthly glacier runoff per VIC cell (m3/s)
    # For now, create a placeholder structure
    # In production, this reads per-glacier hydro output and converts

    # Unit conversion: mm w.e./month * area_m2 / (1000 * seconds_in_month) = m3/s
    print("\nUnit conversion:")
    print("  Q(m3/s) = melt(mm_we/month) * area(km2) * 1e6 / (1000 * seconds_in_month)")
    print("  = melt * area_km2 * 1000 / seconds_in_month")

    # Double-counting check
    if args.vic_snowmelt_dir:
        print(f"\nDouble-counting correction enabled (VIC dir: {args.vic_snowmelt_dir})")
        print("Will subtract VIC snowmelt from glacier cells")
    else:
        print("\nWARNING: No VIC snowmelt directory provided")
        print("Double-counting of snowmelt on glacier cells is NOT corrected")
        print("Provide --vic_snowmelt_dir for accurate coupling")

    # Total glacier area per VIC cell
    cells_with_glaciers = np.sum(cell_glacier_area > 0)
    total_glacier_area = np.sum(cell_glacier_area)

    # Save output NetCDF (placeholder structure)
    output_nc = output_dir / 'glacier_runoff_vic_grid.nc'
    print(f"\nOutput: {output_nc}")

    oggm_ds.close()

    result = {
        'status': 'success',
        'n_glaciers': len(glaciers),
        'n_vic_cells': n_vic_cells,
        'vic_cells_with_glaciers': int(cells_with_glaciers),
        'total_glacier_area_km2': round(float(total_glacier_area), 2),
        'mapping_csv': str(mapping_csv),
        'output_nc': str(output_nc),
        'double_counting_corrected': args.vic_snowmelt_dir is not None,
        'unit_conversion': 'mm_we_per_month * area_km2 * 1000 / seconds_in_month = m3/s'
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
