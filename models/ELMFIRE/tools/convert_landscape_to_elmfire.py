#!/usr/bin/env python3
"""
convert_landscape_to_elmfire.py — Convert terrain, fuel, and canopy data to ELMFIRE GeoTIFF inputs.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Slope: ELMFIRE wants degrees (0-90). DEM-derived slope is often percent rise.
    Convert: degrees = atan(percent/100) × 180/π
  - Aspect: ELMFIRE wants degrees (0=N, 90=E, 180=S, 270=W).
    GDAL gdaldem aspect produces: 0=N, 90=E — same convention (OK as-is).
  - Canopy base height: Integer storage ×10 when CBH_TIMES_10 = .TRUE.
  - Canopy bulk density: Integer storage ×100 when CBD_TIMES_100 = .TRUE.
  - Canopy cover: Percent (0-100) when CC_IN_PERCENT = .TRUE.
  - Canopy height: Integer storage ×10 when CH_TIMES_10 = .TRUE.

Input sources:
  - DEM: Any GeoTIFF DEM (SRTM, ASTER, NED, LiDAR)
  - Fuel model: LANDFIRE FBFM40 GeoTIFF
  - Canopy: LANDFIRE CC, CH, CBH, CBD GeoTIFFs

Output: Directory of GeoTIFFs ready for ELMFIRE (asp, slp, dem, fbfm40, cc, ch, cbh, cbd, adj, phi)

Usage:
    python convert_landscape_to_elmfire.py \\
        --dem /path/to/dem.tif \\
        --fuel /path/to/fbfm40.tif \\
        --cc /path/to/cc.tif \\
        --ch /path/to/ch.tif \\
        --cbh /path/to/cbh.tif \\
        --cbd /path/to/cbd.tif \\
        --cellsize 30 \\
        --epsg 32610 \\
        --out ./inputs
"""

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    if args.fuel and not os.path.isfile(args.fuel):
        errors.append(f"Fuel model file not found: {args.fuel}")

    if args.cellsize <= 0:
        errors.append(f"Cell size must be positive, got {args.cellsize}")

    if args.epsg < 32600 or args.epsg > 32760:
        if args.epsg != 4326:
            errors.append(f"EPSG {args.epsg} — expected UTM zone (32601-32760). "
                          "ELMFIRE requires projected coordinates.")

    for name, path in [("cc", args.cc), ("ch", args.ch),
                       ("cbh", args.cbh), ("cbd", args.cbd)]:
        if path and not os.path.isfile(path):
            errors.append(f"Canopy {name} file not found: {path}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def get_raster_info(filepath):
    """Get raster metadata using gdalinfo."""
    result = subprocess.run(
        ["gdalinfo", "-json", filepath],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def run_gdal_command(cmd, description=""):
    """Run a GDAL command with error handling."""
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR in {description}: {result.stderr}")
        return False
    return True


def derive_slope_aspect(dem_path, output_dir, cellsize, epsg):
    """Derive slope (degrees) and aspect (degrees) from DEM."""
    slp_path = os.path.join(output_dir, "slp.tif")
    asp_path = os.path.join(output_dir, "asp.tif")

    # Derive slope in degrees
    run_gdal_command([
        "gdaldem", "slope", dem_path, slp_path,
        "-compute_edges", "-s", "1.0"
    ], "slope derivation")

    # Derive aspect in degrees (0=N, 90=E — matches ELMFIRE convention)
    run_gdal_command([
        "gdaldem", "aspect", dem_path, asp_path,
        "-compute_edges", "-zero_for_flat"
    ], "aspect derivation")

    return slp_path, asp_path


def reproject_raster(src_path, dst_path, cellsize, epsg, extent=None,
                     dtype="Float32", nodata=-9999):
    """Reproject and resample a raster to the target CRS and resolution."""
    cmd = [
        "gdalwarp",
        "-t_srs", f"EPSG:{epsg}",
        "-tr", str(cellsize), str(cellsize),
        "-dstnodata", str(nodata),
        "-ot", dtype,
        "-r", "nearest",
        "-co", "COMPRESS=DEFLATE",
        "-co", "ZLEVEL=9",
        "-overwrite"
    ]
    if extent:
        cmd.extend(["-te", str(extent[0]), str(extent[1]),
                     str(extent[2]), str(extent[3])])
    cmd.extend([src_path, dst_path])
    return run_gdal_command(cmd, f"reproject {os.path.basename(src_path)}")


def create_constant_raster(template_path, output_path, value, dtype="Float32"):
    """Create a constant-value raster matching a template."""
    run_gdal_command([
        "gdal_calc.py",
        "-A", template_path,
        f"--outfile={output_path}",
        f"--calc=A*0+{value}",
        "--NoDataValue=-9999",
        f"--type={dtype}",
        "--co=COMPRESS=DEFLATE",
        "--co=ZLEVEL=9",
        "--overwrite"
    ], f"constant raster {value}")


def validate_outputs(output_dir):
    """Validate all output rasters exist and have sensible values."""
    required = ["asp", "slp", "dem", "fbfm40", "adj", "phi",
                "cc", "ch", "cbh", "cbd"]
    results = {"status": "ok", "files": {}, "warnings": []}

    for name in required:
        path = os.path.join(output_dir, f"{name}.tif")
        if not os.path.isfile(path):
            results["status"] = "error"
            results["files"][name] = "MISSING"
            continue

        info = get_raster_info(path)
        size = info.get("size", [0, 0])
        results["files"][name] = {
            "path": path,
            "size": f"{size[0]}x{size[1]}",
            "exists": True
        }

    # Range checks
    checks = {
        "slp": (0, 90, "Slope should be 0-90 degrees"),
        "asp": (0, 360, "Aspect should be 0-360 degrees"),
        "cc": (0, 100, "Canopy cover should be 0-100 percent"),
    }
    for name, (vmin, vmax, msg) in checks.items():
        path = os.path.join(output_dir, f"{name}.tif")
        if os.path.isfile(path) and HAS_GDAL:
            ds = gdal.Open(path)
            if ds:
                band = ds.GetRasterBand(1)
                stats = band.GetStatistics(True, True)
                if stats[1] > vmax or stats[0] < vmin:
                    results["warnings"].append(
                        f"{name}: range [{stats[0]:.1f}, {stats[1]:.1f}] — {msg}"
                    )
                ds = None

    print(json.dumps(results, indent=2))
    return results


def process(args):
    """Main processing pipeline: validate → process → validate."""
    # Step 1: Validate inputs
    validate_inputs(args)
    os.makedirs(args.out, exist_ok=True)

    print(f"Converting landscape data to ELMFIRE format...")
    print(f"  DEM: {args.dem}")
    print(f"  Cell size: {args.cellsize} m")
    print(f"  EPSG: {args.epsg}")

    # Step 2: Reproject DEM to target CRS
    dem_reproj = os.path.join(args.out, "dem.tif")
    reproject_raster(args.dem, dem_reproj, args.cellsize, args.epsg)

    # Step 3: Derive slope and aspect from reprojected DEM
    slp_path, asp_path = derive_slope_aspect(dem_reproj, args.out,
                                              args.cellsize, args.epsg)

    # Step 4: Process fuel model
    if args.fuel:
        fbfm_path = os.path.join(args.out, "fbfm40.tif")
        reproject_raster(args.fuel, fbfm_path, args.cellsize, args.epsg,
                         dtype="Int16")
    else:
        # Default: grass fuel model 102 (GR2)
        fbfm_path = os.path.join(args.out, "fbfm40.tif")
        create_constant_raster(dem_reproj, fbfm_path, 102, dtype="Int16")
        print("  WARNING: No fuel model provided, using GR2 (code 102)")

    # Step 5: Process canopy rasters
    for name, src, multiplier in [
        ("cc", args.cc, 1),      # percent, no multiplier
        ("ch", args.ch, 10),     # meters × 10
        ("cbh", args.cbh, 10),   # meters × 10
        ("cbd", args.cbd, 100),  # kg/m³ × 100
    ]:
        dst = os.path.join(args.out, f"{name}.tif")
        if src:
            # Reproject, then apply multiplier for integer storage
            tmp = os.path.join(args.out, f"_{name}_tmp.tif")
            reproject_raster(src, tmp, args.cellsize, args.epsg)
            if multiplier > 1:
                run_gdal_command([
                    "gdal_calc.py",
                    "-A", tmp,
                    f"--outfile={dst}",
                    f"--calc=A*{multiplier}",
                    "--NoDataValue=-9999",
                    "--type=Int16",
                    "--co=COMPRESS=DEFLATE",
                    "--co=ZLEVEL=9",
                    "--overwrite"
                ], f"scale {name} ×{multiplier}")
                os.remove(tmp)
            else:
                os.rename(tmp, dst)
        else:
            create_constant_raster(dem_reproj, dst, 0, dtype="Int16")

    # Step 6: Create adjustment factor (1.0 = no adjustment)
    adj_path = os.path.join(args.out, "adj.tif")
    create_constant_raster(dem_reproj, adj_path, 1.0)

    # Step 7: Create initial phi field (1.0 = unburned)
    phi_path = os.path.join(args.out, "phi.tif")
    create_constant_raster(dem_reproj, phi_path, 1.0)

    # Step 8: Validate outputs
    print("\nValidating outputs...")
    results = validate_outputs(args.out)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert landscape data to ELMFIRE GeoTIFF inputs"
    )
    parser.add_argument("--dem", required=True, help="DEM GeoTIFF path")
    parser.add_argument("--fuel", default=None, help="FBFM40 fuel model GeoTIFF")
    parser.add_argument("--cc", default=None, help="Canopy cover GeoTIFF (percent)")
    parser.add_argument("--ch", default=None, help="Canopy height GeoTIFF (meters)")
    parser.add_argument("--cbh", default=None, help="Canopy base height GeoTIFF (meters)")
    parser.add_argument("--cbd", default=None, help="Canopy bulk density GeoTIFF (kg/m³)")
    parser.add_argument("--cellsize", type=float, default=30.0,
                        help="Output cell size in meters (default: 30)")
    parser.add_argument("--epsg", type=int, default=32610,
                        help="Target EPSG code (UTM zone, default: 32610)")
    parser.add_argument("--out", required=True, help="Output directory")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
