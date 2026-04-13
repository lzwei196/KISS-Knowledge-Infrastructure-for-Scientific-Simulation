#!/usr/bin/env python3
"""create_remap_weights.py — Create spatial remapping weights from VIC grid to mizuRoute HRUs.

Computes area-weighted overlap between VIC regular lat/lon grid cells and mizuRoute
HRU catchment polygons. Each VIC cell's runoff is distributed proportionally to the
HRUs it overlaps.

The output is a NetCDF weight file that mizuRoute reads for spatial remapping
(is_remap = .True. in the control file).

CRITICAL: CRS must match between VIC grid (WGS84) and HRU polygons.
If CRS differs, overlaps will be wrong and runoff won't reach HRUs (dt_m005).

Usage:
    python create_remap_weights.py \\
        --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \\
        --network_nc outputs/<run>/mizuroute_input/network_topology.nc \\
        --subbasins_shp outputs/<run>/mizuroute_input/subbasins.shp \\
        --output outputs/<run>/mizuroute_input/remap_weights.nc
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import netCDF4 as nc
import geopandas as gpd
from shapely.geometry import box


def validate_inputs(args):
    errors = []
    if not os.path.isfile(args.grid_nc):
        errors.append(f"Grid NC not found: {args.grid_nc}")
    if not os.path.isfile(args.network_nc):
        errors.append(f"Network NC not found: {args.network_nc}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def build_vic_grid_polygons(grid_nc_path):
    """Build rectangular polygons for each VIC grid cell."""
    with nc.Dataset(grid_nc_path, 'r') as ds:
        if 'lat' in ds.variables:
            lats = ds.variables['lat'][:]
            lons = ds.variables['lon'][:]
        elif 'y' in ds.variables:
            lats = ds.variables['y'][:]
            lons = ds.variables['x'][:]
        else:
            raise KeyError(f"Grid file has no lat/lon or y/x variables. Found: {list(ds.variables.keys())}")

    # Determine resolution from spacing
    if len(lats) > 1:
        res_lat = abs(float(lats[1] - lats[0]))
    else:
        res_lat = 0.25
    if len(lons) > 1:
        res_lon = abs(float(lons[1] - lons[0]))
    else:
        res_lon = 0.25

    # Create grid cell polygons
    grid_cells = []
    for lat in lats:
        for lon in lons:
            lat, lon = float(lat), float(lon)
            cell = box(lon - res_lon / 2, lat - res_lat / 2,
                       lon + res_lon / 2, lat + res_lat / 2)
            grid_cells.append({
                'geometry': cell,
                'lat': lat,
                'lon': lon,
                'cell_area': cell.area,  # in degrees^2, will convert
            })

    gdf = gpd.GeoDataFrame(grid_cells, crs='EPSG:4326')
    gdf['grid_id'] = range(1, len(gdf) + 1)
    return gdf


def build_hru_polygons_from_network(network_nc_path):
    """Build simple circular HRU polygons from network topology centroids.

    If a real subbasins shapefile is available, use that instead.
    This fallback creates circular approximations from hru_area and centroid.
    """
    with nc.Dataset(network_nc_path, 'r') as ds:
        hru_ids = ds.variables['hru_id'][:]
        hru_areas = ds.variables['hru_area'][:]  # m^2
        hru_lats = ds.variables['hru_lat'][:]
        hru_lons = ds.variables['hru_lon'][:]

    from shapely.geometry import Point

    hrus = []
    for i in range(len(hru_ids)):
        # Create a circular polygon with equivalent area
        area_m2 = float(hru_areas[i])
        radius_m = np.sqrt(area_m2 / np.pi)
        # Convert radius to degrees (approximate)
        lat = float(hru_lats[i])
        radius_deg = radius_m / 111320.0

        point = Point(float(hru_lons[i]), lat)
        circle = point.buffer(radius_deg)

        hrus.append({
            'geometry': circle,
            'hru_id': int(hru_ids[i]),
            'hru_area_m2': area_m2,
        })

    return gpd.GeoDataFrame(hrus, crs='EPSG:4326')


def compute_overlap_weights(grid_gdf, hru_gdf):
    """Compute area-weighted overlap between grid cells and HRUs.

    weight[i,j] = area(grid_i INTERSECT hru_j) / area(hru_j)
    So that sum of weights for each HRU = 1.0 (all runoff accounted for).
    """
    print("Computing spatial intersections...")

    # Spatial overlay
    overlay = gpd.overlay(grid_gdf, hru_gdf, how='intersection')

    if len(overlay) == 0:
        raise RuntimeError("No spatial overlap between grid and HRUs. Check CRS alignment! (dt_m005)")

    # Compute intersection areas in equal-area projection
    overlay_proj = overlay.to_crs(epsg=6933)  # World Cylindrical Equal Area
    overlay['overlap_area'] = overlay_proj.geometry.area

    # Compute total HRU areas in same projection
    hru_proj = hru_gdf.to_crs(epsg=6933)
    hru_areas = dict(zip(hru_gdf['hru_id'], hru_proj.geometry.area))

    # Compute weights
    weights = []
    for _, row in overlay.iterrows():
        hru_id = row['hru_id']
        grid_id = row['grid_id']
        overlap_area = row['overlap_area']
        total_hru_area = hru_areas.get(hru_id, 1.0)

        weight = overlap_area / total_hru_area if total_hru_area > 0 else 0.0

        weights.append({
            'grid_id': int(grid_id),
            'hru_id': int(hru_id),
            'weight': float(weight),
            'overlap_area': float(overlap_area),
            'i_index': int(row.get('lat', 0)),  # Will be set properly
            'j_index': int(row.get('lon', 0)),
        })

    return weights


def write_remap_netcdf(weights, grid_gdf, hru_ids, output_path):
    """Write remapping weights in mizuRoute format.

    Follows the official mizuRoute Input_files.rst specification for Option 3
    (gridded runoff remapping). Uses two dimensions:
      - polyid: one entry per unique river network HRU
      - data:   one entry per HRU-grid overlap (concatenated across HRUs)

    Required variables (default names from docs):
      - polyId   (polyid) — river network HRU ID
      - nOverlaps(polyid) — count of overlapping grid boxes per HRU
      - weight   (data)   — areal weight of each overlap
      - i_index  (data)   — x/longitude grid index (1-based from left)
      - j_index  (data)   — y/latitude grid index (1-based from bottom)
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Build sorted unique lon/lat arrays from grid to compute i/j indices
    grid_lons = sorted(grid_gdf['lon'].unique())
    grid_lats = sorted(grid_gdf['lat'].unique())  # ascending = south to north
    lon_to_i = {lon: idx + 1 for idx, lon in enumerate(grid_lons)}  # 1-based from left
    lat_to_j = {lat: idx + 1 for idx, lat in enumerate(grid_lats)}  # 1-based from bottom

    # Group overlaps by HRU, preserving order of hru_ids
    from collections import OrderedDict, defaultdict
    overlaps_by_hru = OrderedDict()
    for hid in sorted(set(w['hru_id'] for w in weights)):
        overlaps_by_hru[hid] = []
    for w in weights:
        overlaps_by_hru[w['hru_id']].append(w)

    # Build HRU-level arrays (dim: polyid)
    unique_hru_ids = list(overlaps_by_hru.keys())
    n_hru = len(unique_hru_ids)
    num_qhru_arr = [len(overlaps_by_hru[h]) for h in unique_hru_ids]

    # Build overlap-level arrays (dim: data), concatenated in HRU order
    all_weights = []
    all_i_index = []
    all_j_index = []
    for hid in unique_hru_ids:
        for w in overlaps_by_hru[hid]:
            all_weights.append(w['weight'])
            # Look up the grid cell's lat/lon to get proper i/j indices
            grid_row = grid_gdf[grid_gdf['grid_id'] == w['grid_id']]
            if len(grid_row) > 0:
                lon_val = float(grid_row['lon'].iloc[0])
                lat_val = float(grid_row['lat'].iloc[0])
                all_i_index.append(lon_to_i.get(lon_val, 1))
                all_j_index.append(lat_to_j.get(lat_val, 1))
            else:
                all_i_index.append(1)
                all_j_index.append(1)

    n_data = len(all_weights)

    with nc.Dataset(output_path, 'w', format='NETCDF4') as ds:
        ds.createDimension('polyid', n_hru)
        ds.createDimension('data', n_data)

        # HRU-level variables (dim: polyid)
        v = ds.createVariable('HRUid', 'i4', ('polyid',))
        v.long_name = 'river network HRU ID'
        v[:] = unique_hru_ids

        v = ds.createVariable('num_qhru', 'i4', ('polyid',))
        v.long_name = 'number of overlapping runoff grid cells per HRU'
        v[:] = num_qhru_arr

        # Overlap-level variables (dim: data)
        v = ds.createVariable('weight', 'f8', ('data',))
        v.long_name = 'areal weight of overlapping grid box'
        v[:] = all_weights

        v = ds.createVariable('i_index', 'i4', ('data',))
        v.long_name = 'x (longitude) grid index, 1-based from left'
        v[:] = all_i_index

        v = ds.createVariable('j_index', 'i4', ('data',))
        v.long_name = 'y (latitude) grid index, 1-based from bottom'
        v[:] = all_j_index

        # Global attributes
        ds.title = 'mizuRoute spatial remapping weights'
        ds.source = 'create_remap_weights.py (HydroCraft)'
        ds.n_hru = n_hru
        ds.n_overlaps = n_data
        from datetime import datetime
        ds.history = f'Created {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'


def process(args):
    print("Building VIC grid polygons...")
    grid_gdf = build_vic_grid_polygons(args.grid_nc)
    print(f"  VIC grid: {len(grid_gdf)} cells")

    if args.subbasins_shp and os.path.isfile(args.subbasins_shp):
        print(f"Reading HRU polygons from {args.subbasins_shp}...")
        hru_gdf = gpd.read_file(args.subbasins_shp)
        if hru_gdf.crs and hru_gdf.crs.to_epsg() != 4326:
            hru_gdf = hru_gdf.to_crs(epsg=4326)
    else:
        print("Building HRU polygons from network topology (circular approximation)...")
        hru_gdf = build_hru_polygons_from_network(args.network_nc)

    print(f"  HRUs: {len(hru_gdf)}")

    weights = compute_overlap_weights(grid_gdf, hru_gdf)
    print(f"  Overlaps found: {len(weights)}")

    hru_ids = sorted(hru_gdf['hru_id'].unique())

    # Validate: check each HRU has at least one weight
    hrus_with_weights = set(w['hru_id'] for w in weights)
    hrus_without = set(hru_ids) - hrus_with_weights
    if hrus_without:
        print(f"  WARNING: {len(hrus_without)} HRUs have no VIC grid overlap (dt_m010)")

    # Check weight sums
    from collections import defaultdict
    weight_sums = defaultdict(float)
    for w in weights:
        weight_sums[w['hru_id']] += w['weight']

    bad_sums = {h: s for h, s in weight_sums.items() if abs(s - 1.0) > 0.1}
    if bad_sums:
        print(f"  WARNING: {len(bad_sums)} HRUs have weight sums far from 1.0")

    write_remap_netcdf(weights, grid_gdf, hru_ids, args.output)

    return {
        'output_file': args.output,
        'n_overlaps': len(weights),
        'n_grid_cells': len(grid_gdf),
        'n_hrus': len(hru_ids),
        'hrus_without_weights': len(hrus_without),
    }


def main():
    parser = argparse.ArgumentParser(description='Create mizuRoute remapping weights')
    parser.add_argument('--grid_nc', required=True, help='VIC basin grid NetCDF')
    parser.add_argument('--network_nc', required=True, help='Network topology NetCDF')
    parser.add_argument('--subbasins_shp', default=None, help='Sub-basin shapefile (optional)')
    parser.add_argument('--output', required=True, help='Output remap weights NetCDF')

    args = parser.parse_args()

    if not validate_inputs(args):
        sys.exit(1)

    try:
        result = process(args)
        print(json.dumps(result, indent=2))
        print("\nSUCCESS: Remapping weights created")
    except Exception as e:
        print(f"PROCESSING ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
