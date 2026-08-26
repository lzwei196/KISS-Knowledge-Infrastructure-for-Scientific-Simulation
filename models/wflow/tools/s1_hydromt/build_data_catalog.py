#!/usr/bin/env python3
"""
build_data_catalog.py — Create HydroMT data catalog pointing to HydroCraft datasets.

Generates a YAML data catalog that maps HydroMT dataset names to HydroCraft's
existing datasets (HWSD, AVHRR, CMFD/MSWX, China DEM / Copernicus GLO-30),
avoiding duplicate downloads of global datasets.

Usage:
    python build_data_catalog.py \
      --forcing cmfd \
      --dem_source china_90m \
      --output /path/to/data_catalog.yml
"""

import argparse
import json
import os
import sys
from pathlib import Path


HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")


def validate_inputs(args):
    """Check that data sources exist."""
    errors = []
    warnings = []

    # Check DEM
    if args.dem_source == "china_90m":
        dem_path = HYDROCRAFT_ROOT / "data" / "dem" / "china_dem_90m" / "china_dem_90m.tif"
        if not dem_path.exists():
            warnings.append(f"China DEM not found at {dem_path}, will use Copernicus GLO-30")
    elif args.dem_source == "copernicus":
        pass  # Downloaded on-the-fly by HydroMT

    # Check HWSD
    hwsd_raster = HYDROCRAFT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil"
    if not hwsd_raster.exists():
        warnings.append(f"HWSD raster not found at {hwsd_raster}")

    # Check AVHRR
    avhrr_dir = HYDROCRAFT_ROOT / "data" / "veg"
    if not avhrr_dir.exists():
        warnings.append(f"AVHRR vegetation data dir not found at {avhrr_dir}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    return warnings


def process(args):
    """Generate the HydroMT data catalog YAML content."""
    catalog = {}

    # --- DEM ---
    if args.dem_source == "china_90m":
        catalog["china_dem_90m"] = {
            "path": str(HYDROCRAFT_ROOT / "data" / "dem" / "china_dem_90m" / "china_dem_90m.tif"),
            "data_type": "RasterDataset",
            "driver": "raster",
            "crs": 4326,
            "meta": {
                "source": "HydroCraft China DEM 90m",
                "resolution": "90m (~3 arcsec)",
                "coverage": "China mainland",
            },
        }
    # Copernicus GLO-30 is handled natively by HydroMT — no catalog entry needed

    # --- Soil (HWSD) ---
    catalog["hwsd_raster"] = {
        "path": str(HYDROCRAFT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil"),
        "data_type": "RasterDataset",
        "driver": "raster",
        "crs": 4326,
        "meta": {
            "source": "HWSD v1.2 global soil database",
            "resolution": "30 arcsec (~1km)",
            "coverage": "Global",
        },
    }

    # --- Land cover (AVHRR) ---
    avhrr_path = HYDROCRAFT_ROOT / "data" / "veg" / "AVHRR"
    if avhrr_path.exists():
        catalog["avhrr_landcover"] = {
            "path": str(avhrr_path / "*.tif"),
            "data_type": "RasterDataset",
            "driver": "raster",
            "crs": 4326,
            "meta": {
                "source": "AVHRR 1km global land cover",
                "resolution": "1km",
                "coverage": "Global",
            },
        }

    # --- Forcing ---
    if args.forcing == "cmfd":
        catalog["cmfd_forcing"] = {
            "path": str(HYDROCRAFT_ROOT / "data" / "forcing" / "Data_forcing_03hr_010deg" / "{variable}" / "*.nc"),
            "data_type": "RasterDataset",
            "driver": "netcdf",
            "crs": 4326,
            "meta": {
                "source": "CMFD China Meteorological Forcing Dataset",
                "resolution": "0.1 deg, 3-hourly",
                "period": "1979-2018",
                "coverage": "China mainland",
                "variables": "prec, shum, srad, temp, wind, pres, lrad",
            },
        }
    elif args.forcing == "mswx":
        catalog["mswx_forcing"] = {
            "path": "KISSPATH_FORCING/{variable}/*.nc",
            "data_type": "RasterDataset",
            "driver": "netcdf",
            "crs": 4326,
            "meta": {
                "source": "MSWX Multi-Source Weather",
                "resolution": "0.1 deg, 3-hourly",
                "period": "1979-2026",
                "coverage": "Global",
            },
        }

    # --- GRDC stations ---
    grdc_shp = Path("KISSPATH_DATA/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc/shapefiles/grdc/grdc_basin_shapes.shp")
    if grdc_shp.exists():
        catalog["grdc_basins"] = {
            "path": str(grdc_shp),
            "data_type": "GeoDataFrame",
            "driver": "vector",
            "meta": {
                "source": "GRDC-Caravan basin polygons",
                "stations": 5357,
            },
        }

    return catalog


def write_catalog(catalog, output_path):
    """Write catalog to YAML file."""
    import yaml

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Write with custom formatting for readability
    with open(output_path, "w") as f:
        f.write("# HydroMT Data Catalog for HydroCraft wflow integration\n")
        f.write("# Points to existing HydroCraft datasets to avoid duplicate downloads\n")
        f.write(f"# Generated by build_data_catalog.py\n\n")
        yaml.dump(catalog, f, default_flow_style=False, sort_keys=False)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Create HydroMT data catalog pointing to HydroCraft datasets"
    )
    parser.add_argument(
        "--forcing",
        type=str,
        default="cmfd",
        choices=["cmfd", "mswx", "nasa_power"],
    )
    parser.add_argument(
        "--dem_source",
        type=str,
        default="china_90m",
        choices=["china_90m", "copernicus"],
    )
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()

    warnings = validate_inputs(args)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    catalog = process(args)
    out_path = write_catalog(catalog, args.output)

    print(
        json.dumps(
            {
                "status": "success",
                "catalog_path": out_path,
                "datasets": list(catalog.keys()),
                "warnings": warnings,
            },
            indent=2,
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
