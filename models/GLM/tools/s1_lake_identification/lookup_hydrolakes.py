#!/usr/bin/env python3
"""
lookup_hydrolakes.py — Find a lake in the HydroLAKES global database.

Given a lake name or lat/lon coordinates, searches the HydroLAKES v10 shapefile
(~1.4 million lakes globally) and returns morphometric parameters needed for GLM.

Usage:
    python lookup_hydrolakes.py --lat 46.0 --lon -89.7 --radius_km 10
    python lookup_hydrolakes.py --name "Sparkling" --country "United States"
    python lookup_hydrolakes.py --lat 40.48 --lon 116.97 --output morphometry.json

Output: JSON with lake attributes (area, depth, volume, elevation, etc.)
"""

import argparse
import json
import math
import os
import sys

import numpy as np


def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []
    if args.lat is None and args.name is None:
        errors.append("Must provide either --lat/--lon or --name")
    if args.lat is not None and args.lon is None:
        errors.append("--lon is required when --lat is provided")
    if args.lat is not None and (args.lat < -90 or args.lat > 90):
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon is not None and (args.lon < -180 or args.lon > 180):
        errors.append(f"--lon must be between -180 and 180, got {args.lon}")
    if args.radius_km <= 0:
        errors.append(f"--radius_km must be positive, got {args.radius_km}")

    # Check HydroLAKES shapefile exists
    if not os.path.exists(args.hydrolakes_shp):
        errors.append(
            f"HydroLAKES shapefile not found at {args.hydrolakes_shp}. "
            f"Download from https://data.hydrosheds.org/file/hydrolakes/"
            f"HydroLAKES_polys_v10_shp.zip and unzip to data/lakes/"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Search HydroLAKES for matching lakes."""
    import geopandas as gpd
    from shapely.geometry import Point

    print(f"Loading HydroLAKES from {args.hydrolakes_shp}...", file=sys.stderr)
    gdf = gpd.read_file(args.hydrolakes_shp)
    print(f"Loaded {len(gdf)} lakes.", file=sys.stderr)

    results = []

    if args.lat is not None and args.lon is not None:
        # Spatial search: find lakes within radius_km of the point
        search_point = Point(args.lon, args.lat)

        # Approximate degree buffer from km (rough, good enough for filtering)
        deg_buffer = args.radius_km / 111.0
        bbox_mask = (
            (gdf.geometry.centroid.x >= args.lon - deg_buffer) &
            (gdf.geometry.centroid.x <= args.lon + deg_buffer) &
            (gdf.geometry.centroid.y >= args.lat - deg_buffer) &
            (gdf.geometry.centroid.y <= args.lat + deg_buffer)
        )
        candidates = gdf[bbox_mask].copy()

        if len(candidates) == 0:
            # Try with pour point columns if available
            if 'Pour_long' in gdf.columns and 'Pour_lat' in gdf.columns:
                bbox_mask = (
                    (gdf['Pour_long'] >= args.lon - deg_buffer) &
                    (gdf['Pour_long'] <= args.lon + deg_buffer) &
                    (gdf['Pour_lat'] >= args.lat - deg_buffer) &
                    (gdf['Pour_lat'] <= args.lat + deg_buffer)
                )
                candidates = gdf[bbox_mask].copy()

        print(f"Found {len(candidates)} candidates within bounding box.", file=sys.stderr)

        # Compute actual distances
        for idx, row in candidates.iterrows():
            if 'Pour_lat' in row and 'Pour_long' in row:
                clat, clon = row['Pour_lat'], row['Pour_long']
            else:
                centroid = row.geometry.centroid
                clat, clon = centroid.y, centroid.x
            dist = haversine_km(args.lat, args.lon, clat, clon)
            if dist <= args.radius_km:
                results.append((dist, idx, row))

        results.sort(key=lambda x: x[0])

    if args.name is not None:
        # Name search: fuzzy match on Lake_name column
        name_col = None
        for col in ['Lake_name', 'LAKE_NAME', 'lake_name', 'Name']:
            if col in gdf.columns:
                name_col = col
                break
        if name_col is None:
            print(json.dumps({"status": "error",
                              "errors": ["No lake name column found in shapefile"]}))
            sys.exit(1)

        search_lower = args.name.lower()
        for idx, row in gdf.iterrows():
            lake_name = str(row[name_col]).strip()
            if search_lower in lake_name.lower():
                if args.country:
                    country_col = None
                    for c in ['Country', 'COUNTRY', 'country']:
                        if c in gdf.columns:
                            country_col = c
                            break
                    if country_col and args.country.lower() not in str(row[country_col]).lower():
                        continue
                results.append((0, idx, row))

    if not results:
        print(json.dumps({
            "status": "no_match",
            "message": "No lakes found matching criteria. "
                       "Try increasing --radius_km or check coordinates."
        }))
        sys.exit(0)

    # Format output
    lakes = []
    for dist, idx, row in results[:args.max_results]:
        lake_info = {
            "hylak_id": int(row.get('Hylak_id', row.get('HYLAK_ID', -1))),
            "lake_name": str(row.get('Lake_name', row.get('LAKE_NAME', 'Unknown'))).strip(),
            "country": str(row.get('Country', row.get('COUNTRY', 'Unknown'))).strip(),
            "lake_type": int(row.get('Lake_type', row.get('LAKE_TYPE', 0))),
            "lake_type_desc": {1: "Lake", 2: "Reservoir", 3: "Lake control"}.get(
                int(row.get('Lake_type', row.get('LAKE_TYPE', 0))), "Unknown"),
            "latitude": float(row.get('Pour_lat', row.get('POUR_LAT',
                              row.geometry.centroid.y))),
            "longitude": float(row.get('Pour_long', row.get('POUR_LONG',
                               row.geometry.centroid.x))),
            "lake_area_km2": float(row.get('Lake_area', row.get('LAKE_AREA', 0))),
            "shore_len_km": float(row.get('Shore_len', row.get('SHORE_LEN', 0))),
            "vol_total_mcm": float(row.get('Vol_total', row.get('VOL_TOTAL', 0))),
            "vol_res_mcm": float(row.get('Vol_res', row.get('VOL_RES', 0))),
            "depth_avg_m": float(row.get('Depth_avg', row.get('DEPTH_AVG', 0))),
            "dis_avg_m3s": float(row.get('Dis_avg', row.get('DIS_AVG', 0))),
            "res_time_days": float(row.get('Res_time', row.get('RES_TIME', 0))),
            "elevation_m": float(row.get('Elevation', row.get('ELEVATION', 0))),
            "shore_dev": float(row.get('Shore_dev', row.get('SHORE_DEV', 0))),
            "distance_km": round(dist, 2),
        }
        # Estimate max depth from avg depth (typical ratio for natural lakes)
        if lake_info["depth_avg_m"] > 0:
            lake_info["depth_max_est_m"] = round(lake_info["depth_avg_m"] * 2.5, 1)
        lakes.append(lake_info)

    return {"status": "success", "num_matches": len(lakes), "lakes": lakes}


def validate_outputs(result):
    """Validate search results."""
    if result["status"] != "success":
        return result
    for lake in result["lakes"]:
        if lake["lake_area_km2"] <= 0:
            print(f"WARNING: Lake {lake['lake_name']} has zero/negative area",
                  file=sys.stderr)
        if lake["depth_avg_m"] <= 0:
            print(f"WARNING: Lake {lake['lake_name']} has zero/negative depth. "
                  f"Manual morphometry input will be needed.", file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Search HydroLAKES for lake morphometric parameters")
    parser.add_argument("--lat", type=float, help="Latitude of search point")
    parser.add_argument("--lon", type=float, help="Longitude of search point")
    parser.add_argument("--name", type=str, help="Lake name (partial match)")
    parser.add_argument("--country", type=str, help="Country filter")
    parser.add_argument("--radius_km", type=float, default=10.0,
                        help="Search radius in km (default: 10)")
    parser.add_argument("--max_results", type=int, default=5,
                        help="Maximum results to return (default: 5)")
    parser.add_argument("--hydrolakes_shp", type=str,
                        default="/mnt/disk1/Hydrocraft_server/data/lakes/"
                                "HydroLAKES_polys_v10.shp",
                        help="Path to HydroLAKES shapefile")
    parser.add_argument("--output", type=str,
                        help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
