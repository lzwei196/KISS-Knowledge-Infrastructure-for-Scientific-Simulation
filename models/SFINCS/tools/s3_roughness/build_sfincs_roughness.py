#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sfincs_roughness
Stage:        s3_roughness
Description:  Generate spatially varying Manning's n from AVHRR land cover classification.

Inputs:
  --grid_info:    Path to grid_info.json from s1_domain
  --lulc_path:    Path to land use/land cover raster (default: AVHRR 1km)
  --output_dir:   Output directory
  --uniform_n:    Use uniform Manning's n instead of LULC-based (optional)

Outputs:
  - sfincs.man:   Manning's n file (binary float32, row-major)
  - roughness_summary.json

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# AVHRR land cover class to Manning's n lookup table
# Source: Chow (1959), Arcement & Schneider (1989), SFINCS documentation
MANNING_LOOKUP = {
    # AVHRR class: (Manning's n, description)
    0:  (0.025, "Water"),
    1:  (0.100, "Evergreen Needleleaf Forest"),
    2:  (0.100, "Evergreen Broadleaf Forest"),
    3:  (0.100, "Deciduous Needleleaf Forest"),
    4:  (0.100, "Deciduous Broadleaf Forest"),
    5:  (0.100, "Mixed Forest"),
    6:  (0.040, "Closed Shrubland"),
    7:  (0.035, "Open Shrubland"),
    8:  (0.040, "Woody Savannas"),
    9:  (0.035, "Savannas"),
    10: (0.035, "Grasslands"),
    11: (0.030, "Permanent Wetlands"),
    12: (0.040, "Croplands"),
    13: (0.080, "Urban and Built-Up"),
    14: (0.040, "Cropland/Natural Vegetation Mosaic"),
    15: (0.015, "Snow and Ice"),
    16: (0.030, "Barren or Sparsely Vegetated"),
}

# Default AVHRR path (same as VIC vegetation)
AVHRR_DEFAULT = "/mnt/disk1/Hydrocraft_server/data/forcing/AVHRR/"


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if args.lulc_path and not Path(args.lulc_path).exists():
        errors.append(f"LULC raster not found: {args.lulc_path}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if args.uniform_n is not None and (args.uniform_n < 0.001 or args.uniform_n > 1.0):
        errors.append(f"Manning's n must be 0.001-1.0, got {args.uniform_n}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    mmax = grid["mmax"]
    nmax = grid["nmax"]
    dx = grid["dx"]
    dy = grid["dy"]
    x0 = grid["x0"]
    y0 = grid["y0"]
    epsg = grid["epsg"]

    if args.uniform_n is not None:
        # Uniform Manning's n
        manning = np.full((nmax, mmax), args.uniform_n, dtype=np.float32)
        logger.info(f"Using uniform Manning's n = {args.uniform_n}")
        class_counts = {"uniform": mmax * nmax}
    else:
        # LULC-based Manning's n
        import rasterio
        from rasterio.warp import reproject, Resampling
        from rasterio.transform import from_origin
        from pyproj import CRS

        lulc_path = args.lulc_path
        if not lulc_path:
            # Try to find AVHRR
            import glob
            avhrr_files = glob.glob(os.path.join(AVHRR_DEFAULT, "**/*.tif"), recursive=True)
            if avhrr_files:
                lulc_path = avhrr_files[0]
                logger.info(f"Auto-selected AVHRR: {lulc_path}")
            else:
                logger.warning("No LULC data found. Falling back to uniform n=0.04")
                manning = np.full((nmax, mmax), 0.04, dtype=np.float32)
                class_counts = {"fallback_uniform": mmax * nmax}
                # Skip LULC processing
                man_path = output_dir / "sfincs.man"
                manning.tofile(str(man_path))
                summary = {
                    "status": "success",
                    "man_file": str(man_path),
                    "method": "fallback_uniform",
                    "manning_mean": 0.04,
                    "manning_min": 0.04,
                    "manning_max": 0.04,
                }
                summary_path = output_dir / "roughness_summary.json"
                with open(summary_path, "w") as f:
                    json.dump(summary, f, indent=2)
                print(json.dumps(summary, indent=2))
                return str(summary_path)

        target_crs = CRS.from_epsg(epsg)
        y_top = y0 + nmax * dy
        target_transform = from_origin(x0, y_top, dx, dy)

        with rasterio.open(lulc_path) as src:
            lulc_grid = np.zeros((nmax, mmax), dtype=np.int16)
            reproject(
                source=rasterio.band(src, 1),
                destination=lulc_grid,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=target_transform,
                dst_crs=target_crs,
                resampling=Resampling.nearest,
                dst_nodata=-1,
            )

        # Map LULC classes to Manning's n
        manning = np.full((nmax, mmax), 0.04, dtype=np.float32)  # default
        class_counts = {}
        for cls, (n_val, desc) in MANNING_LOOKUP.items():
            mask = (lulc_grid == cls)
            count = int(np.sum(mask))
            if count > 0:
                manning[mask] = n_val
                class_counts[f"{cls}_{desc}"] = count

        logger.info(f"LULC class distribution: {class_counts}")

    # Write Manning's n binary file
    man_path = output_dir / "sfincs.man"
    manning.tofile(str(man_path))
    logger.info(f"Wrote: {man_path} ({man_path.stat().st_size} bytes)")

    summary = {
        "status": "success",
        "man_file": str(man_path),
        "method": "uniform" if args.uniform_n is not None else "lulc_based",
        "manning_min": float(np.min(manning)),
        "manning_max": float(np.max(manning)),
        "manning_mean": float(np.mean(manning)),
        "manning_median": float(np.median(manning)),
        "class_counts": class_counts,
    }

    summary_path = output_dir / "roughness_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)
    parent = Path(output_path).parent
    man_path = parent / "sfincs.man"
    if not man_path.exists() or man_path.stat().st_size == 0:
        logger.error(f"Manning's n file missing or empty: {man_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SFINCS Manning's n roughness")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--lulc_path", default=None, help="LULC raster path")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--uniform_n", type=float, default=None, help="Uniform Manning's n (overrides LULC)")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
