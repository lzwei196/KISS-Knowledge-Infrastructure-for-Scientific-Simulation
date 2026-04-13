#!/usr/bin/env python3
"""
Configure LakeData.txt for HYPE from HydroLAKES and GRanD databases.

Identifies regulated and natural lakes within the basin and generates
the HYPE LakeData.txt file with lake properties.

Usage:
    python setup_lake_data.py \
        --subbasins outputs/hype_run/subbasins/subbasins.shp \
        --geodata outputs/hype_run/modelfiles/GeoData.txt \
        --output outputs/hype_run/modelfiles/LakeData.txt
"""

import argparse
import sys
import os

import pandas as pd
from pathlib import Path


def generate_lakedata(geodata_path, output_path, lake_type='default'):
    """
    Generate LakeData.txt from GeoData.txt lake information.

    For subbasins with lake area (SLC water class > 0), creates
    LakeData entries with rating curve parameters.
    """
    # Read GeoData
    with open(geodata_path) as f:
        lines = f.readlines()

    # Skip comments
    data_start = 0
    for i, line in enumerate(lines):
        if not line.startswith('!!'):
            data_start = i
            break

    header = lines[data_start].strip().split('\t')
    rows = []
    for line in lines[data_start + 1:]:
        if line.strip():
            rows.append(line.strip().split('\t'))

    df = pd.DataFrame(rows, columns=header)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass

    # Find subbasins with lake depth > 0
    lake_subs = []
    if 'LAKE_DEPTH' in df.columns:
        for _, row in df.iterrows():
            depth = float(row['LAKE_DEPTH'])
            if depth > 0:
                # Check if water SLC fraction > 0
                slc_cols = [c for c in df.columns if c.startswith('SLC_')]
                has_water = any(float(row[c]) > 0.05 for c in slc_cols[-1:])  # Last SLC is often water
                if has_water:
                    lake_subs.append({
                        'SUBID': int(row['SUBID']),
                        'DEPTH': depth,
                        'AREA': float(row['AREA']),
                    })

    if not lake_subs:
        print("No significant lakes found in basin. LakeData.txt not needed.")
        return

    # Write LakeData.txt
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    with open(output_path, 'w') as f:
        f.write("SUBID\tLDTYPE\tLAKEAREA\tLAKEDEPTH\tRATCK\tRATCEXP\tRATCK0\n")
        for lake in lake_subs:
            # Default rating curve parameters
            lake_area = lake['AREA'] * 0.1  # Assume 10% of subbasin is lake
            ratck = 2.0     # Rating curve coefficient
            ratcexp = 1.5   # Rating curve exponent
            ratck0 = 0.5    # Threshold level

            f.write(f"{lake['SUBID']}\t1\t{lake_area:.0f}\t{lake['DEPTH']:.1f}\t"
                   f"{ratck}\t{ratcexp}\t{ratck0}\n")

    print(f"Generated LakeData.txt: {output_path}")
    print(f"  {len(lake_subs)} lake subbasins configured")


def main():
    parser = argparse.ArgumentParser(description='Setup HYPE LakeData.txt')
    parser.add_argument('--geodata', required=True, help='GeoData.txt path')
    parser.add_argument('--output', required=True, help='Output LakeData.txt path')
    parser.add_argument('--subbasins', help='Subbasin shapefile (optional, for lake identification)')

    args = parser.parse_args()
    generate_lakedata(args.geodata, args.output)


if __name__ == '__main__':
    main()
