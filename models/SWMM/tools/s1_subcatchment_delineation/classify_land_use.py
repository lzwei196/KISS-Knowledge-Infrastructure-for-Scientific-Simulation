#!/usr/bin/env python3
"""
Classify land use within SWMM subcatchments.

Overlays a land use raster on subcatchment polygons and computes per-subcatchment:
  - Percent impervious area (%Imperv)
  - Manning's N for impervious and pervious surfaces
  - Depression storage depths (mm) for impervious and pervious surfaces

Uses a lookup table that maps land use class IDs to hydrological parameters.

Inputs:
  - Subcatchment shapefile
  - Land use raster (GeoTIFF, integer class IDs)
  - Optional lookup CSV (columns: class_id, name, imperv_pct, n_imperv, n_perv,
    ds_imperv_mm, ds_perv_mm)

Outputs:
  - CSV with per-subcatchment land use parameters
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Default land-use lookup table (class_id -> parameters)
DEFAULT_LOOKUP = {
    1: {"name": "urban_dense",   "imperv_pct": 85.0, "n_imperv": 0.015, "n_perv": 0.24,  "ds_imperv_mm": 1.5, "ds_perv_mm": 5.0},
    2: {"name": "commercial",    "imperv_pct": 95.0, "n_imperv": 0.014, "n_perv": 0.10,  "ds_imperv_mm": 1.5, "ds_perv_mm": 3.0},
    3: {"name": "residential",   "imperv_pct": 40.0, "n_imperv": 0.015, "n_perv": 0.20,  "ds_imperv_mm": 2.0, "ds_perv_mm": 5.0},
    4: {"name": "industrial",    "imperv_pct": 72.0, "n_imperv": 0.014, "n_perv": 0.15,  "ds_imperv_mm": 1.5, "ds_perv_mm": 4.0},
    5: {"name": "forest",        "imperv_pct": 5.0,  "n_imperv": 0.015, "n_perv": 0.40,  "ds_imperv_mm": 2.0, "ds_perv_mm": 7.5},
    6: {"name": "grassland",     "imperv_pct": 10.0, "n_imperv": 0.015, "n_perv": 0.25,  "ds_imperv_mm": 2.0, "ds_perv_mm": 5.0},
    7: {"name": "agriculture",   "imperv_pct": 8.0,  "n_imperv": 0.015, "n_perv": 0.15,  "ds_imperv_mm": 2.0, "ds_perv_mm": 5.0},
    8: {"name": "water",         "imperv_pct": 100.0,"n_imperv": 0.012, "n_perv": 0.012, "ds_imperv_mm": 0.0, "ds_perv_mm": 0.0},
    9: {"name": "bare_soil",     "imperv_pct": 2.0,  "n_imperv": 0.015, "n_perv": 0.02,  "ds_imperv_mm": 2.0, "ds_perv_mm": 3.0},
}


def load_lookup(csv_path):
    """Load land-use lookup table from CSV."""
    lookup = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = int(row["class_id"])
            lookup[cid] = {
                "name": row["name"],
                "imperv_pct": float(row["imperv_pct"]),
                "n_imperv": float(row["n_imperv"]),
                "n_perv": float(row["n_perv"]),
                "ds_imperv_mm": float(row["ds_imperv_mm"]),
                "ds_perv_mm": float(row["ds_perv_mm"]),
            }
    return lookup


def classify_subcatchments(subcatchment_shp, landuse_raster, lookup):
    """
    Overlay land use raster on subcatchments and compute weighted-average
    parameters per subcatchment.
    """
    try:
        import geopandas as gpd
        import rasterio
        from rasterio.mask import mask as rio_mask
        import numpy as np
    except ImportError as e:
        print(f"ERROR: Required package not installed: {e}", file=sys.stderr)
        print("Install with: pip install geopandas rasterio numpy", file=sys.stderr)
        sys.exit(1)

    gdf = gpd.read_file(subcatchment_shp)
    src = rasterio.open(landuse_raster)

    # Reproject subcatchments to raster CRS if needed
    if gdf.crs and src.crs and gdf.crs != src.crs:
        gdf = gdf.to_crs(src.crs)

    results = []
    for idx, row in gdf.iterrows():
        sc_id = row.get("id", f"S{idx}")
        geom = row.geometry

        try:
            clipped, _ = rio_mask(src, [geom], crop=True, nodata=-9999)
            data = clipped[0]  # single band
            valid = data[data != -9999]
        except Exception as e:
            print(f"WARNING: Could not clip raster for {sc_id}: {e}", file=sys.stderr)
            # Use default residential values
            results.append({
                "id": sc_id,
                "imperv_pct": 40.0,
                "n_imperv": 0.015,
                "n_perv": 0.20,
                "ds_imperv_mm": 2.0,
                "ds_perv_mm": 5.0,
                "dominant_class": "residential",
            })
            continue

        if len(valid) == 0:
            print(f"WARNING: No land use data for {sc_id}, using defaults", file=sys.stderr)
            results.append({
                "id": sc_id,
                "imperv_pct": 40.0,
                "n_imperv": 0.015,
                "n_perv": 0.20,
                "ds_imperv_mm": 2.0,
                "ds_perv_mm": 5.0,
                "dominant_class": "unknown",
            })
            continue

        # Count pixels per class and compute area-weighted parameters
        unique, counts = np.unique(valid.astype(int), return_counts=True)
        total = counts.sum()

        imperv_pct = 0.0
        n_imperv = 0.0
        n_perv = 0.0
        ds_imperv = 0.0
        ds_perv = 0.0
        dominant_class = "unknown"
        max_count = 0

        for cls, cnt in zip(unique, counts):
            weight = cnt / total
            params = lookup.get(int(cls), lookup.get(3, DEFAULT_LOOKUP[3]))  # default residential
            imperv_pct += weight * params["imperv_pct"]
            n_imperv += weight * params["n_imperv"]
            n_perv += weight * params["n_perv"]
            ds_imperv += weight * params["ds_imperv_mm"]
            ds_perv += weight * params["ds_perv_mm"]
            if cnt > max_count:
                max_count = cnt
                dominant_class = params["name"]

        results.append({
            "id": sc_id,
            "imperv_pct": round(imperv_pct, 2),
            "n_imperv": round(n_imperv, 4),
            "n_perv": round(n_perv, 4),
            "ds_imperv_mm": round(ds_imperv, 2),
            "ds_perv_mm": round(ds_perv, 2),
            "dominant_class": dominant_class,
        })

    src.close()
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Classify land use within SWMM subcatchments"
    )
    parser.add_argument("--subcatchment_shp", required=True,
                        help="Subcatchment polygon shapefile")
    parser.add_argument("--landuse_raster", required=True,
                        help="Land use raster (GeoTIFF, integer classes)")
    parser.add_argument("--output", required=True,
                        help="Output CSV path")
    parser.add_argument("--lookup_csv", default=None,
                        help="Custom land-use lookup CSV (class_id,name,imperv_pct,...)")
    args = parser.parse_args()

    for fpath in [args.subcatchment_shp, args.landuse_raster]:
        if not os.path.isfile(fpath):
            print(f"ERROR: File not found: {fpath}", file=sys.stderr)
            sys.exit(1)

    # Load lookup table
    if args.lookup_csv:
        if not os.path.isfile(args.lookup_csv):
            print(f"ERROR: Lookup CSV not found: {args.lookup_csv}", file=sys.stderr)
            sys.exit(1)
        lookup = load_lookup(args.lookup_csv)
        print(f"Loaded {len(lookup)} land-use classes from {args.lookup_csv}")
    else:
        lookup = DEFAULT_LOOKUP
        print(f"Using default lookup table ({len(lookup)} classes)")

    print(f"Classifying land use for subcatchments in {args.subcatchment_shp}...")
    results = classify_subcatchments(args.subcatchment_shp, args.landuse_raster, lookup)

    # Write output CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "imperv_pct", "n_imperv", "n_perv",
            "ds_imperv_mm", "ds_perv_mm", "dominant_class",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"Output written: {output_path} ({len(results)} subcatchments)")


if __name__ == "__main__":
    main()
