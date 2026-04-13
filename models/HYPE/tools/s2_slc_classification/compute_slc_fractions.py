#!/usr/bin/env python3
"""
Compute SLC (Soil-Land use Class) fractions per subbasin for HYPE.

Uses AVHRR 1km land cover and HWSD soil data to classify each pixel
within each subbasin into soil-landcover combinations.

Usage:
    python compute_slc_fractions.py \
        --subbasins outputs/hype_run/subbasins/subbasins.shp \
        --landcover data/vegetation/AVHRR/ \
        --soil_raster data/soil/HWSD_RASTER/hwsd.bil \
        --output outputs/hype_run/slc/
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from pathlib import Path


# AVHRR UMD land cover classification -> HYPE land use types
AVHRR_TO_HYPE_LANDUSE = {
    0: 3,   # Water -> 3 (water)
    1: 1,   # Evergreen Needleleaf Forest -> 1 (forest)
    2: 1,   # Evergreen Broadleaf Forest -> 1 (forest)
    3: 1,   # Deciduous Needleleaf Forest -> 1 (forest)
    4: 1,   # Deciduous Broadleaf Forest -> 1 (forest)
    5: 1,   # Mixed Forest -> 1 (forest)
    6: 2,   # Closed Shrublands -> 2 (open land/crop)
    7: 2,   # Open Shrublands -> 2 (open land/crop)
    8: 1,   # Woody Savannas -> 1 (forest)
    9: 2,   # Savannas -> 2 (open land/crop)
    10: 2,  # Grasslands -> 2 (open land/crop)
    11: 2,  # Permanent Wetlands -> 2 (open land/crop) — NOT water. In Asia, wetlands are often rice paddies.
    12: 2,  # Croplands -> 2 (open land/crop)
    13: 4,  # Urban and Built-Up -> 4 (urban)
    14: 2,  # Cropland/Natural Vegetation -> 2 (open land/crop)
    15: 5,  # Snow and Ice -> 5 (glacier)
    16: 2,  # Barren or Sparsely Vegetated -> 2 (open land)
}

# HWSD soil texture classes -> HYPE soil types
HWSD_TO_HYPE_SOIL = {
    # Sandy -> 1 (coarse)
    1: 1, 2: 1,
    # Loamy -> 2 (medium)
    3: 2, 4: 2, 5: 2,
    # Clay -> 3 (fine)
    6: 3, 7: 3, 8: 3,
    # Organic -> 4 (organic)
    9: 4, 10: 4, 11: 4, 12: 4,
}


def compute_slc_for_subbasin(subbasin_geom, landcover_src, soil_src):
    """
    Compute SLC fractions for a single subbasin.

    Returns dict mapping (landuse, soil) -> fraction
    """
    try:
        # Clip landcover to subbasin
        lc_data, lc_transform = rio_mask(landcover_src, [subbasin_geom], crop=True, nodata=255)
        lc_data = lc_data[0]

        # Clip soil to subbasin
        soil_data, soil_transform = rio_mask(soil_src, [subbasin_geom], crop=True, nodata=0)
        soil_data = soil_data[0]

        # Ensure same shape (use minimum)
        min_rows = min(lc_data.shape[0], soil_data.shape[0])
        min_cols = min(lc_data.shape[1], soil_data.shape[1])
        lc_data = lc_data[:min_rows, :min_cols]
        soil_data = soil_data[:min_rows, :min_cols]

        # Valid pixels
        valid = (lc_data != 255) & (soil_data != 0)
        total_valid = np.sum(valid)

        if total_valid == 0:
            return {(2, 2): 1.0}  # Default: open land / medium soil

        # Map to HYPE classes
        lc_hype = np.vectorize(lambda x: AVHRR_TO_HYPE_LANDUSE.get(x, 2))(lc_data)
        soil_hype = np.vectorize(lambda x: HWSD_TO_HYPE_SOIL.get(x, 2))(soil_data)

        # Count combinations
        slc_counts = {}
        for lu, so in zip(lc_hype[valid], soil_hype[valid]):
            key = (int(lu), int(so))
            slc_counts[key] = slc_counts.get(key, 0) + 1

        # Convert to fractions
        slc_fractions = {k: v / total_valid for k, v in slc_counts.items()}

        return slc_fractions

    except Exception as e:
        print(f"  Warning: SLC computation failed ({e}), using defaults")
        return {(2, 2): 1.0}


def main():
    parser = argparse.ArgumentParser(description='Compute SLC fractions for HYPE')
    parser.add_argument('--subbasins', required=True, help='Subbasin shapefile')
    parser.add_argument('--landcover', help='AVHRR land cover directory or raster')
    parser.add_argument('--soil_raster', help='HWSD soil raster (.bil)')
    parser.add_argument('--output', required=True, help='Output directory')
    parser.add_argument('--default_slc', action='store_true',
                       help='Use default SLC fractions instead of computing from rasters')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    sub_gdf = gpd.read_file(args.subbasins)
    print(f"Loaded {len(sub_gdf)} subbasins")

    if args.default_slc or not args.landcover or not args.soil_raster:
        # Use default SLC fractions
        print("Using default SLC fractions (forest/coarse=40%, crop/medium=40%, water/fine=20%)")
        all_slc = {}
        for _, row in sub_gdf.iterrows():
            subid = row.get('SUBID', row.name + 1)
            all_slc[subid] = {(1, 1): 0.4, (2, 2): 0.4, (3, 3): 0.2}
    else:
        # Compute from rasters
        landcover_path = args.landcover
        if os.path.isdir(landcover_path):
            # Find AVHRR raster in directory
            for f in os.listdir(landcover_path):
                if f.endswith('.tif') or f.endswith('.bil'):
                    landcover_path = os.path.join(args.landcover, f)
                    break

        print(f"Land cover: {landcover_path}")
        print(f"Soil raster: {args.soil_raster}")

        lc_src = rasterio.open(landcover_path)
        soil_src = rasterio.open(args.soil_raster)

        all_slc = {}
        for _, row in sub_gdf.iterrows():
            subid = row.get('SUBID', row.name + 1)
            print(f"  Processing subbasin {subid}...")
            all_slc[subid] = compute_slc_for_subbasin(row.geometry, lc_src, soil_src)

        lc_src.close()
        soil_src.close()

    # Build unique SLC list
    all_combinations = set()
    for fracs in all_slc.values():
        all_combinations.update(fracs.keys())

    slc_list = sorted(all_combinations)
    slc_id_map = {combo: i + 1 for i, combo in enumerate(slc_list)}

    # Save SLC fractions
    import csv
    with open(output_dir / 'slc_fractions.csv', 'w', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        header = ['SUBID'] + [f'SLC_{slc_id_map[c]}' for c in slc_list]
        writer.writerow(header)

        for subid in sorted(all_slc.keys()):
            row = [subid]
            for combo in slc_list:
                row.append(f"{all_slc[subid].get(combo, 0.0):.4f}")
            writer.writerow(row)

    # Save SLC definitions (for GeoClass.txt generation)
    with open(output_dir / 'slc_definitions.csv', 'w', newline='') as f:
        writer = csv.writer(f, delimiter='\t')
        writer.writerow(['SLC_ID', 'LANDUSE', 'SOIL'])
        for combo, slc_id in sorted(slc_id_map.items(), key=lambda x: x[1]):
            writer.writerow([slc_id, combo[0], combo[1]])

    print(f"\nResults:")
    print(f"  {len(slc_list)} unique SLC classes")
    print(f"  Fractions: {output_dir / 'slc_fractions.csv'}")
    print(f"  Definitions: {output_dir / 'slc_definitions.csv'}")

    for i, combo in enumerate(slc_list):
        print(f"  SLC_{i+1}: landuse={combo[0]}, soil={combo[1]}")


if __name__ == '__main__':
    main()
