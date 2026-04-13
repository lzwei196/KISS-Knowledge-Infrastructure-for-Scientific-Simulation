#!/usr/bin/env python3
"""
Find Glaciers in Basin — OGGM Knowledge Infrastructure

Perform spatial intersection of Randolph Glacier Inventory (RGI) outlines
with a basin boundary shapefile to identify all glaciers within the basin.

Usage:
    python find_glaciers_in_basin.py \
        --basin_shp data/shp/yarlung_shp/yarlung_boundary.shp \
        --min_area_km2 0.01 \
        --output outputs/oggm/glaciers_in_basin.csv
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import mapping
except ImportError:
    print("ERROR: Required packages not installed. Run: pip install geopandas shapely")
    sys.exit(1)


# RGI v6 first-order region bounding boxes (approximate lat/lon)
RGI_REGIONS = {
    '01': {'name': 'Alaska', 'lat': (53, 72), 'lon': (-176, -126)},
    '02': {'name': 'Western Canada and US', 'lat': (35, 62), 'lon': (-133, -104)},
    '03': {'name': 'Arctic Canada North', 'lat': (68, 84), 'lon': (-125, -60)},
    '04': {'name': 'Arctic Canada South', 'lat': (58, 75), 'lon': (-95, -55)},
    '05': {'name': 'Greenland Periphery', 'lat': (59, 84), 'lon': (-74, -12)},
    '06': {'name': 'Iceland', 'lat': (63, 67), 'lon': (-25, -13)},
    '07': {'name': 'Svalbard and Jan Mayen', 'lat': (70, 81), 'lon': (-10, 35)},
    '08': {'name': 'Scandinavia', 'lat': (58, 72), 'lon': (4, 32)},
    '09': {'name': 'Russian Arctic', 'lat': (68, 82), 'lon': (30, 105)},
    '10': {'name': 'North Asia', 'lat': (42, 70), 'lon': (46, 180)},
    '11': {'name': 'Central Europe', 'lat': (42, 48), 'lon': (5, 17)},
    '12': {'name': 'Caucasus and Middle East', 'lat': (30, 45), 'lon': (40, 55)},
    '13': {'name': 'Central Asia', 'lat': (27, 50), 'lon': (60, 105)},
    '14': {'name': 'South Asia West', 'lat': (25, 40), 'lon': (66, 82)},
    '15': {'name': 'South Asia East', 'lat': (25, 40), 'lon': (80, 105)},
    '16': {'name': 'Low Latitudes', 'lat': (-20, 20), 'lon': (-82, 40)},
    '17': {'name': 'Southern Andes', 'lat': (-56, -17), 'lon': (-76, -65)},
    '18': {'name': 'New Zealand', 'lat': (-46, -42), 'lon': (166, 175)},
    '19': {'name': 'Antarctic and Subantarctic', 'lat': (-78, -53), 'lon': (-180, 180)},
}


def detect_rgi_region(lat, lon):
    """Auto-detect RGI region(s) from coordinates."""
    candidates = []
    for region_id, info in RGI_REGIONS.items():
        lat_range = info['lat']
        lon_range = info['lon']
        if lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]:
            candidates.append(region_id)
    return candidates


def find_rgi_shapefile(rgi_dir, rgi_region, rgi_version='62'):
    """Find the RGI shapefile in the given directory."""
    rgi_dir = Path(rgi_dir)

    # Try common naming patterns
    patterns = [
        f"{rgi_region}_rgi{rgi_version}_*.shp",
        f"*rgi{rgi_version}*{rgi_region}*.shp",
        f"*{rgi_region}*.shp",
    ]

    for pattern in patterns:
        matches = list(rgi_dir.rglob(pattern))
        if matches:
            return matches[0]

    # Try direct subdirectories
    for subdir in rgi_dir.iterdir():
        if subdir.is_dir() and rgi_region in subdir.name:
            shp_files = list(subdir.glob("*.shp"))
            if shp_files:
                return shp_files[0]

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Find glaciers within a basin using RGI spatial intersection"
    )
    parser.add_argument("--basin_shp", required=True, help="Basin boundary shapefile")
    parser.add_argument("--rgi_dir", default=None,
                        help="RGI directory (auto-detected via OGGM if omitted)")
    parser.add_argument("--rgi_version", default="62", help="RGI version: 62 or 70")
    parser.add_argument("--rgi_region", default=None,
                        help="RGI region number (auto-detected from basin centroid)")
    parser.add_argument("--buffer_km", type=float, default=0,
                        help="Buffer around basin in km (default 0)")
    parser.add_argument("--min_area_km2", type=float, default=0.01,
                        help="Minimum glacier area threshold (default 0.01 km2)")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    # Load basin shapefile
    print(f"Loading basin shapefile: {args.basin_shp}")
    basin_gdf = gpd.read_file(args.basin_shp)

    # Ensure EPSG:4326
    if basin_gdf.crs is None:
        print("WARNING: Basin shapefile has no CRS. Assuming EPSG:4326.")
        basin_gdf = basin_gdf.set_crs('EPSG:4326')
    elif basin_gdf.crs.to_epsg() != 4326:
        print(f"Reprojecting basin from {basin_gdf.crs} to EPSG:4326")
        basin_gdf = basin_gdf.to_crs('EPSG:4326')

    # Compute basin centroid and area
    basin_union = basin_gdf.geometry.union_all()
    centroid = basin_union.centroid
    basin_lat, basin_lon = centroid.y, centroid.x
    print(f"Basin centroid: {basin_lat:.4f}N, {basin_lon:.4f}E")

    # Compute basin area (approximate)
    basin_area_km2 = basin_gdf.to_crs('+proj=eck4').geometry.area.sum() / 1e6
    print(f"Basin area: {basin_area_km2:.1f} km2")

    # Apply buffer
    if args.buffer_km > 0:
        buffer_deg = args.buffer_km / 111.0  # approximate
        basin_gdf = basin_gdf.copy()
        basin_gdf['geometry'] = basin_gdf.geometry.buffer(buffer_deg)
        print(f"Applied {args.buffer_km} km buffer")

    # Determine RGI region
    if args.rgi_region:
        regions = [args.rgi_region.zfill(2)]
    else:
        regions = detect_rgi_region(basin_lat, basin_lon)
        if not regions:
            print(f"ERROR: Could not auto-detect RGI region for ({basin_lat}, {basin_lon})")
            print("Please specify --rgi_region manually")
            sys.exit(1)
        print(f"Auto-detected RGI region(s): {regions}")

    # Find RGI data
    rgi_dir = args.rgi_dir
    if rgi_dir is None:
        try:
            from oggm import utils
            rgi_dir = utils.get_rgi_dir(version=args.rgi_version)
            print(f"Using OGGM RGI directory: {rgi_dir}")
        except ImportError:
            print("ERROR: --rgi_dir not provided and OGGM not installed for auto-download")
            print("Install OGGM: pip install oggm")
            print("Or download RGI manually from https://www.glims.org/RGI/")
            sys.exit(1)

    # Load and merge RGI data for all relevant regions
    all_glaciers = []
    for region in regions:
        rgi_shp = find_rgi_shapefile(rgi_dir, region, args.rgi_version)
        if rgi_shp is None:
            print(f"WARNING: Could not find RGI shapefile for region {region} in {rgi_dir}")
            continue
        print(f"Loading RGI region {region}: {rgi_shp}")
        rgi_gdf = gpd.read_file(rgi_shp)
        all_glaciers.append(rgi_gdf)

    if not all_glaciers:
        print("ERROR: No RGI data found for any detected region")
        sys.exit(1)

    rgi_gdf = gpd.pd.concat(all_glaciers, ignore_index=True)
    print(f"Total RGI glaciers in region(s): {len(rgi_gdf)}")

    # Ensure same CRS
    if rgi_gdf.crs is None:
        rgi_gdf = rgi_gdf.set_crs('EPSG:4326')
    elif rgi_gdf.crs.to_epsg() != 4326:
        rgi_gdf = rgi_gdf.to_crs('EPSG:4326')

    # Spatial intersection
    print("Performing spatial intersection...")
    glaciers_in_basin = gpd.sjoin(rgi_gdf, basin_gdf, how='inner', predicate='intersects')

    # Remove duplicates (from multi-region query)
    id_col = 'RGIId' if 'RGIId' in glaciers_in_basin.columns else 'rgi_id'
    glaciers_in_basin = glaciers_in_basin.drop_duplicates(subset=[id_col])

    print(f"Glaciers intersecting basin: {len(glaciers_in_basin)}")

    # Apply area filter
    area_col = 'Area' if 'Area' in glaciers_in_basin.columns else 'area'
    if area_col in glaciers_in_basin.columns:
        before_filter = len(glaciers_in_basin)
        glaciers_in_basin = glaciers_in_basin[
            glaciers_in_basin[area_col] >= args.min_area_km2
        ]
        filtered = before_filter - len(glaciers_in_basin)
        if filtered > 0:
            print(f"Filtered {filtered} glaciers below {args.min_area_km2} km2 threshold")

    print(f"Final glacier count: {len(glaciers_in_basin)}")

    if len(glaciers_in_basin) == 0:
        print("No glaciers found in basin.")
        print("Check: (1) Basin is in a glacierized region, (2) CRS alignment correct")

    # Compute centroids and prepare output
    output_data = []
    for _, row in glaciers_in_basin.iterrows():
        centroid = row.geometry.centroid
        glacier_info = {
            'rgi_id': row.get(id_col, ''),
            'name': row.get('Name', row.get('name', '')),
            'area_km2': row.get(area_col, 0),
            'centroid_lat': centroid.y,
            'centroid_lon': centroid.x,
            'min_elev': row.get('Zmin', row.get('zmin', -999)),
            'max_elev': row.get('Zmax', row.get('zmax', -999)),
            'debris_flag': row.get('Debris', row.get('debris', 0)),
        }
        output_data.append(glacier_info)

    # Write output CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import csv
    with open(output_path, 'w', newline='') as f:
        if output_data:
            writer = csv.DictWriter(f, fieldnames=output_data[0].keys())
            writer.writeheader()
            writer.writerows(output_data)
        else:
            f.write("rgi_id,name,area_km2,centroid_lat,centroid_lon,min_elev,max_elev,debris_flag\n")

    print(f"Output written: {output_path}")

    # Write summary JSON
    total_glacier_area = sum(g['area_km2'] for g in output_data)
    glacier_fraction = total_glacier_area / basin_area_km2 * 100 if basin_area_km2 > 0 else 0

    summary = {
        'n_glaciers': len(output_data),
        'total_glacier_area_km2': round(total_glacier_area, 2),
        'basin_area_km2': round(basin_area_km2, 1),
        'glacier_fraction_pct': round(glacier_fraction, 3),
        'rgi_regions': regions,
        'rgi_version': args.rgi_version,
        'min_area_threshold_km2': args.min_area_km2,
        'recommendation': (
            'SKIP OGGM — glacier fraction negligible (<0.1%)' if glacier_fraction < 0.1
            else 'Optional — minimal glacier impact' if glacier_fraction < 1
            else 'Recommended — glaciers affect summer discharge' if glacier_fraction < 10
            else 'Required — glaciers dominate summer hydrology'
        )
    }

    summary_path = output_path.with_suffix('.csv.summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"Summary: {json.dumps(summary, indent=2)}")
    print(f"Summary written: {summary_path}")


if __name__ == "__main__":
    main()
