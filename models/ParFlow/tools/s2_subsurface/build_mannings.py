#!/usr/bin/env python3
"""
Build Manning's roughness coefficient field for ParFlow overland flow.

Maps AVHRR land cover classes to Manning's n values. These control the
speed of surface water movement over the landscape.

CRITICAL: Manning's n too low (< 0.01) causes CFL instability.
         Manning's n too high (> 1.0) prevents overland flow entirely.

Usage:
    python build_mannings.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --surface_mask_npy outputs/parflow_run/domain/surface_mask.npy \
        --output_dir outputs/parflow_run/subsurface/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import rasterio
    from pyproj import Transformer
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)

# AVHRR land cover class -> Manning's n
# Source: Literature survey (Chow, 1959; Arcement & Schneider, 1989)
AVHRR_MANNINGS = {
    0:  0.035,   # Water
    1:  0.100,   # Evergreen Needleleaf Forest
    2:  0.120,   # Evergreen Broadleaf Forest
    3:  0.100,   # Deciduous Needleleaf Forest
    4:  0.120,   # Deciduous Broadleaf Forest
    5:  0.110,   # Mixed Forest
    6:  0.050,   # Closed Shrublands
    7:  0.040,   # Open Shrublands
    8:  0.060,   # Woody Savannas
    9:  0.050,   # Savannas
    10: 0.040,   # Grasslands
    11: 0.040,   # Permanent Wetlands
    12: 0.035,   # Croplands
    13: 0.015,   # Urban and Built-Up
    14: 0.035,   # Cropland/Natural Vegetation Mosaic
    15: 0.022,   # Snow and Ice
    16: 0.030,   # Barren or Sparsely Vegetated
}

HYDROCRAFT_ROOT = "/mnt/disk1/Hydrocraft_server"
AVHRR_PATH = os.path.join(HYDROCRAFT_ROOT, "data/forcing/AVHRR")


def validate_inputs(domain_json, surface_mask_npy):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(surface_mask_npy):
        errors.append(f"Surface mask not found: {surface_mask_npy}")
    return errors


def process(domain_json, surface_mask_npy, output_dir, uniform_n=None):
    """
    Build Manning's n field from AVHRR land cover.

    Parameters
    ----------
    domain_json : str
        Path to domain definition JSON.
    surface_mask_npy : str
        Path to 2D surface mask numpy file.
    output_dir : str
        Output directory.
    uniform_n : float or None
        If set, use uniform Manning's n instead of AVHRR lookup.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_2d = np.load(surface_mask_npy)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    mannings = np.full((ny, nx), 0.035, dtype=np.float64)

    if uniform_n is not None:
        mannings[:, :] = uniform_n
        mannings[mask_2d == 0] = 0.0
        method = f"uniform ({uniform_n})"
        class_counts = {"uniform": int(np.sum(mask_2d > 0))}
    else:
        # Find AVHRR file
        avhrr_file = None
        if os.path.isdir(AVHRR_PATH):
            import glob
            candidates = glob.glob(os.path.join(AVHRR_PATH, "*.tif"))
            candidates += glob.glob(os.path.join(AVHRR_PATH, "**/*.tif"), recursive=True)
            if candidates:
                avhrr_file = candidates[0]

        if avhrr_file is None:
            # Fall back to uniform
            mannings[mask_2d > 0] = 0.04
            method = "uniform fallback (0.04, AVHRR not found)"
            class_counts = {"fallback": int(np.sum(mask_2d > 0))}
        else:
            transformer = Transformer.from_crs(
                f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
            )
            class_counts = {}
            with rasterio.open(avhrr_file) as src:
                for j in range(ny):
                    for i in range(nx):
                        if mask_2d[j, i] == 0:
                            continue
                        cx = origin_x + (i + 0.5) * dx
                        cy = origin_y + (j + 0.5) * dy
                        lon, lat = transformer.transform(cx, cy)
                        try:
                            row, col = src.index(lon, lat)
                            lc = int(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                        except Exception:
                            lc = -1
                        n_val = AVHRR_MANNINGS.get(lc, 0.04)
                        mannings[j, i] = n_val
                        class_counts[str(lc)] = class_counts.get(str(lc), 0) + 1
            method = "AVHRR land cover lookup"

    # Enforce minimum Manning's n for active cells (CFL stability)
    min_n = 0.01
    low_cells = int(np.sum((mannings < min_n) & (mask_2d > 0)))
    mannings[(mannings < min_n) & (mask_2d > 0)] = min_n

    # Set inactive cells to 0
    mannings[mask_2d == 0] = 0.0

    # Save
    output_file = os.path.join(output_dir, "mannings_n.npy")
    np.save(output_file, mannings)

    # Try PFB
    pfb_file = None
    try:
        from parflow.tools.io import write_pfb
        pfb_path = os.path.join(output_dir, "mannings_n.pfb")
        write_pfb(pfb_path, mannings[np.newaxis, :, :].astype(np.float64),
                  dx=dx, dy=dy, dz=1.0, x=origin_x, y=origin_y, z=0.0)
        pfb_file = pfb_path
    except ImportError:
        pass

    active = mannings[mask_2d > 0]
    result = {
        "status": "success",
        "method": method,
        "output_npy": output_file,
        "output_pfb": pfb_file,
        "class_distribution": class_counts,
        "stats": {
            "min": float(np.min(active)) if len(active) > 0 else 0,
            "max": float(np.max(active)) if len(active) > 0 else 0,
            "mean": float(np.mean(active)) if len(active) > 0 else 0,
        },
        "cells_clipped_to_min": low_cells,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Build Manning's n field for ParFlow")
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--surface_mask_npy", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--uniform_n", type=float, default=None,
                        help="Use uniform Manning's n instead of AVHRR")
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.surface_mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.domain_json, args.surface_mask_npy, args.output_dir,
                     args.uniform_n)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
