#!/usr/bin/env python3
"""
Generate GeoData.txt for HYPE from subbasin shapefile and SLC fractions.

Combines subbasin properties (area, centroid, elevation, slope, river length)
with SLC fractions into a single GeoData.txt file.

Usage:
    python generate_geodata.py \
        --subbasins outputs/hype_run/subbasins/subbasins.shp \
        --slc_fractions outputs/hype_run/slc/slc_fractions.csv \
        --maindown outputs/hype_run/subbasins/maindown.csv \
        --dem data/dem/china_dem_90m/china_dem_90m.tif \
        --output outputs/hype_run/modelfiles/GeoData.txt
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path


def estimate_river_length(subbasin_geom):
    """
    Estimate main river length within a subbasin.

    Simple estimate based on longest axis of bounding box.
    """
    bounds = subbasin_geom.bounds  # minx, miny, maxx, maxy
    # Approximate in meters
    dlat = (bounds[3] - bounds[1]) * 111000
    dlon = (bounds[2] - bounds[0]) * 111000 * np.cos(np.radians((bounds[1] + bounds[3]) / 2))
    # River length ~ 0.7 * diagonal (sinuosity factor)
    diagonal = np.sqrt(dlat ** 2 + dlon ** 2)
    return max(1000, diagonal * 0.7)


def compute_subbasin_area_m2(geom, lat):
    """Convert geometry area from degrees^2 to m^2."""
    # Approximate: 1 degree lat ~ 111km, 1 degree lon ~ 111km * cos(lat)
    lat_m = 111000
    lon_m = 111000 * np.cos(np.radians(lat))
    return geom.area * lat_m * lon_m


def generate_geodata(subbasins_path, slc_path, maindown_path, output_path,
                     dem_path=None, lake_depth_default=2.0):
    """
    Generate HYPE GeoData.txt.
    """
    # Load subbasins
    sub_gdf = gpd.read_file(subbasins_path)

    # Load SLC fractions
    slc_df = pd.read_csv(slc_path, sep='\t')

    # Load MAINDOWN
    maindown_df = pd.read_csv(maindown_path, sep='\t')

    # Merge
    if 'SUBID' not in sub_gdf.columns:
        sub_gdf['SUBID'] = range(1, len(sub_gdf) + 1)

    # Compute properties per subbasin
    rows = []
    for _, sub_row in sub_gdf.iterrows():
        subid = sub_row['SUBID']
        geom = sub_row.geometry
        centroid = geom.centroid

        # MAINDOWN
        md_row = maindown_df[maindown_df['SUBID'] == subid]
        maindown = int(md_row['MAINDOWN'].iloc[0]) if len(md_row) > 0 else 0

        # Area in m^2
        area_m2 = compute_subbasin_area_m2(geom, centroid.y)

        # River length
        rivlen = estimate_river_length(geom)

        # Elevation and slope (defaults if no DEM)
        elev_mean = sub_row.get('ELEV_MEAN', 100)
        slope_mean = sub_row.get('SLOPE_MEAN', 0.03)

        row = {
            'SUBID': subid,
            'MAINDOWN': maindown,
            'AREA': f'{area_m2:.1E}',
            'RIVLEN': int(rivlen),
            'LATITUDE': f'{centroid.y:.4f}',
            'LONGITUDE': f'{centroid.x:.4f}',
            'ELEV_MEAN': f'{elev_mean:.0f}',
            'SLOPE_MEAN': f'{slope_mean:.4f}',
            'LAKE_DEPTH': f'{lake_depth_default:.1f}',
        }

        # Add SLC fractions
        slc_row = slc_df[slc_df['SUBID'] == subid]
        if len(slc_row) > 0:
            slc_cols = [c for c in slc_df.columns if c.startswith('SLC_')]
            for col in slc_cols:
                row[col] = f'{slc_row[col].iloc[0]:.4f}'

        rows.append(row)

    # Write GeoData.txt
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    # Build header
    slc_cols = [c for c in slc_df.columns if c.startswith('SLC_')]
    columns = ['SUBID', 'MAINDOWN', 'AREA'] + slc_cols + \
              ['RIVLEN', 'LATITUDE', 'LONGITUDE', 'ELEV_MEAN', 'SLOPE_MEAN', 'LAKE_DEPTH']

    with open(output_path, 'w') as f:
        f.write('\t'.join(columns) + '\n')
        for row in rows:
            values = [str(row.get(c, '0')) for c in columns]
            f.write('\t'.join(values) + '\n')

    print(f"Generated GeoData.txt: {output_path}")
    print(f"  {len(rows)} subbasins")
    print(f"  {len(slc_cols)} SLC classes")
    print(f"  Outlet: SUBID with MAINDOWN=0")

    # Validation check
    for row in rows:
        slc_sum = sum(float(row.get(c, 0)) for c in slc_cols)
        if abs(slc_sum - 1.0) > 0.01:
            print(f"  WARNING: SUBID {row['SUBID']} SLC fractions sum to {slc_sum:.4f} (should be 1.0)")


def main():
    parser = argparse.ArgumentParser(description='Generate HYPE GeoData.txt')
    parser.add_argument('--subbasins', required=True, help='Subbasin shapefile')
    parser.add_argument('--slc_fractions', required=True, help='SLC fractions CSV')
    parser.add_argument('--maindown', required=True, help='MAINDOWN topology CSV')
    parser.add_argument('--output', required=True, help='Output GeoData.txt path')
    parser.add_argument('--dem', help='DEM raster for elevation/slope (optional)')
    parser.add_argument('--lake_depth', type=float, default=2.0, help='Default lake depth (m)')

    args = parser.parse_args()

    generate_geodata(
        args.subbasins, args.slc_fractions, args.maindown, args.output,
        dem_path=args.dem, lake_depth_default=args.lake_depth
    )


if __name__ == '__main__':
    main()
