#!/usr/bin/env python3
"""
convert_params_to_ef5.py — Convert HWSD soil data to CREST parameter grids.

Derives CREST water balance parameter grids (WM, IM, FC, B) from the
Harmonized World Soil Database (HWSD) and writes them as EF5-compatible
GeoTIFF or ESRI ASCII grids.

Pipeline stage: s3 (Soil/Parameter Conversion)
Pattern: validate → process → validate

Input:
  - HWSD raster (GeoTIFF or ERDAS Imagine .img)
  - HWSD_DATA.csv lookup table
  - Basin bounding box or DEM grid for spatial extent
  - Target resolution (default: match DEM)

Output:
  - wm.tif — Maximum soil water capacity (mm)
  - im.tif — Impervious area ratio (%)
  - fc.tif — Saturated hydraulic conductivity (mm/hr)
  - b.tif — Variable infiltration curve exponent (-)

HWSD soil property → CREST parameter mapping:
  - WM: derived from AWC (available water capacity) × soil depth
  - FC (Ksat): from USDA texture class → hydraulic conductivity lookup
  - IM: estimated from urban land use fraction
  - B: estimated from clay content via empirical relationship
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np

try:
    from osgeo import gdal, osr
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False


# ── Constants ──────────────────────────────────────────────────────────────

EF5_NODATA = -9999.0

# USDA texture class → approximate Ksat (mm/hr)
# Source: Rawls et al. (1982), various pedotransfer functions
TEXTURE_KSAT = {
    "clay": 0.6,
    "silty clay": 0.9,
    "sandy clay": 1.2,
    "clay loam": 2.3,
    "silty clay loam": 1.5,
    "sandy clay loam": 4.3,
    "loam": 13.2,
    "silt loam": 6.8,
    "silt": 6.8,
    "sandy loam": 25.9,
    "loamy sand": 61.1,
    "sand": 120.4,
}

# Default Ksat by dominant HWSD texture class code (T_USDA_TEX_CLASS)
TEXTURE_CODE_KSAT = {
    1: 0.6,    # clay
    2: 0.9,    # silty clay
    3: 1.2,    # sandy clay
    4: 2.3,    # clay loam
    5: 1.5,    # silty clay loam
    6: 4.3,    # sandy clay loam
    7: 13.2,   # loam
    8: 6.8,    # silt loam
    9: 6.8,    # silt
    10: 25.9,  # sandy loam
    11: 61.1,  # loamy sand
    12: 120.4, # sand
    13: 0.0,   # no data
}

# Default soil depths by HWSD reference depth (cm)
DEFAULT_SOIL_DEPTH_CM = 100.0


# ── Validation ─────────────────────────────────────────────────────────────

def validate_inputs(hwsd_raster, hwsd_csv, dem_path, bbox):
    """Validate all input files exist and are readable."""
    errors = []

    if hwsd_raster and not os.path.isfile(hwsd_raster):
        errors.append(f"HWSD raster not found: {hwsd_raster}")

    if hwsd_csv and not os.path.isfile(hwsd_csv):
        errors.append(f"HWSD CSV not found: {hwsd_csv}")

    if dem_path and not os.path.isfile(dem_path):
        errors.append(f"DEM file not found: {dem_path}")

    if not HAS_GDAL:
        errors.append("GDAL/OGR not installed. Install with: pip install GDAL")

    if bbox is not None and len(bbox) != 4:
        errors.append(f"Bounding box must have 4 values, got {len(bbox)}")

    return errors


def validate_outputs(output_dir, expected_files):
    """Validate output parameter grids exist and have valid values."""
    errors = []

    for fname in expected_files:
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            errors.append(f"Output file not created: {fpath}")
            continue

        if HAS_GDAL:
            ds = gdal.Open(fpath)
            if ds is None:
                errors.append(f"Cannot open output: {fpath}")
                continue
            band = ds.GetRasterBand(1)
            data = band.ReadAsArray()
            nodata = band.GetNoDataValue()
            valid = data[data != nodata] if nodata is not None else data.flatten()

            if len(valid) == 0:
                errors.append(f"No valid data in {fpath}")
            elif "wm" in fname and (np.min(valid) < 0 or np.max(valid) > 2000):
                errors.append(f"WM values out of range [0, 2000] in {fpath}: "
                              f"[{np.min(valid):.1f}, {np.max(valid):.1f}]")
            elif "fc" in fname and (np.min(valid) < 0 or np.max(valid) > 500):
                errors.append(f"FC values out of range [0, 500] in {fpath}: "
                              f"[{np.min(valid):.1f}, {np.max(valid):.1f}]")
            elif "im" in fname and (np.min(valid) < 0 or np.max(valid) > 100):
                errors.append(f"IM values out of range [0, 100] in {fpath}: "
                              f"[{np.min(valid):.1f}, {np.max(valid):.1f}]")
            elif "b" in fname and (np.min(valid) < 0 or np.max(valid) > 5):
                errors.append(f"B values out of range [0, 5] in {fpath}: "
                              f"[{np.min(valid):.1f}, {np.max(valid):.1f}]")
            ds = None

    return errors


# ── Processing ─────────────────────────────────────────────────────────────

def load_hwsd_lookup(csv_path):
    """Load HWSD_DATA.csv into a dictionary keyed by MU_GLOBAL."""
    lookup = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                mu = int(float(row.get("MU_GLOBAL", row.get("mu_global", 0))))
                lookup[mu] = row
            except (ValueError, KeyError):
                continue
    return lookup


def get_dem_info(dem_path):
    """Get spatial info from DEM for resampling."""
    ds = gdal.Open(dem_path)
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    nx, ny = ds.RasterXSize, ds.RasterYSize
    ds = None
    return {
        "xmin": gt[0], "ymax": gt[3],
        "xres": gt[1], "yres": gt[5],
        "nx": nx, "ny": ny,
        "projection": proj,
        "geotransform": gt,
    }


def hwsd_raster_to_params(hwsd_raster, hwsd_lookup, dem_info, bbox=None):
    """Convert HWSD raster to CREST parameter arrays."""
    # Open HWSD raster
    hwsd_ds = gdal.Open(hwsd_raster)
    hwsd_band = hwsd_ds.GetRasterBand(1)

    # Resample HWSD to match DEM resolution
    mem_driver = gdal.GetDriverByName("MEM")
    nx, ny = dem_info["nx"], dem_info["ny"]
    gt = dem_info["geotransform"]

    target_ds = mem_driver.Create("", nx, ny, 1, gdal.GDT_Int32)
    target_ds.SetGeoTransform(gt)
    target_ds.SetProjection(dem_info["projection"])

    gdal.ReprojectImage(hwsd_ds, target_ds, hwsd_ds.GetProjection(),
                        dem_info["projection"], gdal.GRA_NearestNeighbour)

    mu_data = target_ds.GetRasterBand(1).ReadAsArray()

    # Initialize parameter arrays
    wm = np.full((ny, nx), EF5_NODATA, dtype=np.float32)
    fc = np.full((ny, nx), EF5_NODATA, dtype=np.float32)
    im = np.full((ny, nx), EF5_NODATA, dtype=np.float32)
    b = np.full((ny, nx), EF5_NODATA, dtype=np.float32)

    # Map HWSD mapping units to CREST parameters
    for iy in range(ny):
        for ix in range(nx):
            mu = int(mu_data[iy, ix])
            if mu <= 0 or mu not in hwsd_lookup:
                continue

            row = hwsd_lookup[mu]

            # WM: from AWC (available water content) × depth
            try:
                t_awc = float(row.get("AWC_CLASS", row.get("T_AWC", 0)))
                if t_awc <= 0:
                    t_awc = 150.0  # default mm/m
                # AWC class: 1=very low, 2=low, ..., 7=very high
                # Map to approximate AWC in mm/m: class × 25 + 25
                if t_awc < 10:  # it's a class code
                    t_awc = t_awc * 25.0 + 25.0
                soil_depth_m = DEFAULT_SOIL_DEPTH_CM / 100.0
                wm[iy, ix] = t_awc * soil_depth_m  # mm
            except (ValueError, KeyError):
                wm[iy, ix] = 150.0  # default

            # FC (Ksat): from texture class
            try:
                tex_class = int(float(row.get("T_USDA_TEX_CLASS",
                                              row.get("TEXTURE", 7))))
                fc[iy, ix] = TEXTURE_CODE_KSAT.get(tex_class, 13.2)
            except (ValueError, KeyError):
                fc[iy, ix] = 13.2  # default loam

            # IM: from impervious estimate (low for natural soils)
            try:
                # Use drainage class as proxy: poor drainage → higher IM
                drainage = int(float(row.get("T_DRAINAGE",
                                             row.get("DRAINAGE", 3))))
                im[iy, ix] = max(0.0, min(15.0, (7 - drainage) * 2.5))
            except (ValueError, KeyError):
                im[iy, ix] = 1.0  # default 1%

            # B: from clay content via empirical relationship
            # B = 0.0145 * clay% + 0.14 (approximate)
            try:
                clay = float(row.get("T_CLAY", row.get("CLAY", 20)))
                b[iy, ix] = max(0.05, min(3.0, 0.0145 * clay + 0.14))
            except (ValueError, KeyError):
                b[iy, ix] = 0.4  # default

    # Clamp to valid ranges
    valid_wm = wm != EF5_NODATA
    wm[valid_wm] = np.clip(wm[valid_wm], 10.0, 1500.0)

    valid_fc = fc != EF5_NODATA
    fc[valid_fc] = np.clip(fc[valid_fc], 0.01, 300.0)

    valid_im = im != EF5_NODATA
    im[valid_im] = np.clip(im[valid_im], 0.0, 100.0)

    valid_b = b != EF5_NODATA
    b[valid_b] = np.clip(b[valid_b], 0.01, 3.0)

    hwsd_ds = None
    target_ds = None

    return {"wm": wm, "fc": fc, "im": im, "b": b}


def write_param_grid(filepath, data, dem_info, nodata=EF5_NODATA):
    """Write parameter grid as GeoTIFF."""
    ny, nx = data.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(filepath, nx, ny, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(dem_info["geotransform"])
    ds.SetProjection(dem_info["projection"])
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(data)
    ds.FlushCache()
    ds = None


def generate_default_params(dem_path, output_dir, wm=150.0, fc=13.2,
                            im=1.0, b_val=0.4):
    """Generate uniform parameter grids from DEM extent (no HWSD needed)."""
    os.makedirs(output_dir, exist_ok=True)
    dem_info = get_dem_info(dem_path)
    ny, nx = dem_info["ny"], dem_info["nx"]

    params = {
        "wm": np.full((ny, nx), wm, dtype=np.float32),
        "fc": np.full((ny, nx), fc, dtype=np.float32),
        "im": np.full((ny, nx), im, dtype=np.float32),
        "b": np.full((ny, nx), b_val, dtype=np.float32),
    }

    for name, data in params.items():
        fpath = os.path.join(output_dir, f"{name}.tif")
        write_param_grid(fpath, data, dem_info)
        print(f"  Written: {fpath} (uniform value: {data[0,0]:.2f})")

    return params


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD soil data to CREST parameter grids"
    )
    parser.add_argument("--hwsd-raster", help="HWSD raster file (.tif or .img)")
    parser.add_argument("--hwsd-csv", help="HWSD_DATA.csv lookup table")
    parser.add_argument("--dem", required=True, help="DEM file for spatial reference")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--bbox", nargs=4, type=float,
                        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                        help="Bounding box for clipping")
    parser.add_argument("--default-wm", type=float, default=150.0,
                        help="Default WM if no HWSD (mm)")
    parser.add_argument("--default-fc", type=float, default=13.2,
                        help="Default FC/Ksat if no HWSD (mm/hr)")
    parser.add_argument("--default-im", type=float, default=1.0,
                        help="Default IM if no HWSD (%%)")
    parser.add_argument("--default-b", type=float, default=0.4,
                        help="Default B if no HWSD (-)")

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.hwsd_raster, args.hwsd_csv, args.dem, args.bbox)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)
    print("  Input validation passed.")

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 2: Process
    print("=== Step 2: Generating CREST parameter grids ===")
    if args.hwsd_raster and args.hwsd_csv:
        dem_info = get_dem_info(args.dem)
        hwsd_lookup = load_hwsd_lookup(args.hwsd_csv)
        print(f"  Loaded {len(hwsd_lookup)} HWSD mapping units")
        params = hwsd_raster_to_params(args.hwsd_raster, hwsd_lookup,
                                       dem_info, args.bbox)
        for name, data in params.items():
            fpath = os.path.join(args.output_dir, f"{name}.tif")
            write_param_grid(fpath, data, dem_info)
            valid = data[data != EF5_NODATA]
            if len(valid) > 0:
                print(f"  Written: {fpath} (range: [{np.min(valid):.2f}, {np.max(valid):.2f}])")
            else:
                print(f"  Written: {fpath} (all nodata)")
    else:
        print("  No HWSD data provided. Generating uniform parameter grids.")
        generate_default_params(args.dem, args.output_dir,
                                wm=args.default_wm, fc=args.default_fc,
                                im=args.default_im, b_val=args.default_b)

    # Step 3: Validate outputs
    print("=== Step 3: Validating outputs ===")
    expected = ["wm.tif", "fc.tif", "im.tif", "b.tif"]
    errors = validate_outputs(args.output_dir, expected)
    if errors:
        for e in errors:
            print(f"WARNING: {e}")
    else:
        print("  Output validation passed.")

    print("Done.")


if __name__ == "__main__":
    main()
