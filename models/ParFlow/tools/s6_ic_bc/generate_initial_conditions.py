#!/usr/bin/env python3
"""
Generate initial pressure head field for ParFlow.

CRITICAL CONCEPTS:
  - Pressure head < 0 = unsaturated (suction/tension)
  - Pressure head > 0 = saturated (positive pressure above atmospheric)
  - Pressure head = 0 = water table surface
  - Units: meters of water (NOT Pa, NOT kPa)

Methods:
  1. Hydrostatic from water table depth: p = z_wt - z_cell
     where z_wt is water table elevation and z_cell is cell center elevation
  2. Uniform pressure head: constant value everywhere
  3. From Reinecke global water table depth map (reuses HydroCraft MODFLOW data)

Every cell of the rectangular grid gets its initial pressure, inside AND
outside the basin mask: the s7 run script uses Box geometry, so ParFlow
simulates every cell. (Outside cells used to get pressure 0 in every layer, a
column that is not in hydrostatic balance.) For the reinecke method a cell
with no usable water-table depth stops the tool (no fall-back to --wtd).

Usage:
    python generate_initial_conditions.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --mask_npy outputs/parflow_run/domain/domain_mask.npy \
        --elevation_npy outputs/parflow_run/topography/elevation.npy \
        --method hydrostatic --wtd 5.0 \
        --output_dir outputs/parflow_run/ic_bc/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(domain_json, mask_npy):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(mask_npy):
        errors.append(f"Mask file not found: {mask_npy}")
    return errors


def compute_cell_elevations(domain, elevation_2d):
    """Compute 3D cell center elevations for terrain-following grid."""
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dz_layers = grid["dz_layers_m"]
    total_depth = grid["total_depth_m"]
    tfg = grid.get("terrain_following", True)

    cell_z = np.zeros((nz, ny, nx), dtype=np.float64)

    for j in range(ny):
        for i in range(nx):
            surf_elev = elevation_2d[j, i] if elevation_2d is not None else 0.0
            if tfg:
                # Terrain-following: layers follow surface topography
                z_bottom = surf_elev - total_depth
                z_current = z_bottom
                for k in range(nz):
                    dz = dz_layers[k]
                    cell_z[k, j, i] = z_current + dz / 2.0
                    z_current += dz
            else:
                # Orthogonal: flat layers at fixed elevations
                z_current = 0.0
                for k in range(nz):
                    dz = dz_layers[k]
                    cell_z[k, j, i] = z_current + dz / 2.0
                    z_current += dz

    return cell_z


def process(domain_json, mask_npy, output_dir, method="hydrostatic",
            wtd=5.0, uniform_pressure=-1.0, elevation_npy=None):
    """
    Generate initial pressure head field.

    Parameters
    ----------
    domain_json : str
        Path to domain definition JSON.
    mask_npy : str
        Path to 3D domain mask.
    output_dir : str
        Output directory.
    method : str
        'hydrostatic', 'uniform', or 'reinecke'.
    wtd : float
        Water table depth below surface (m) for hydrostatic method.
    uniform_pressure : float
        Pressure head (m) for uniform method.
    elevation_npy : str, optional
        Path to 2D elevation array (for hydrostatic method).
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_3d = np.load(mask_npy)
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    if mask_3d.shape != (nz, ny, nx):
        raise ValueError(f"mask shape {mask_3d.shape} does not match grid ({nz}, {ny}, {nx})")
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    dz_layers = grid["dz_layers_m"]
    total_depth = grid["total_depth_m"]

    # Load elevation if provided
    elevation_2d = None
    if elevation_npy:
        if not os.path.exists(elevation_npy):
            raise FileNotFoundError(f"elevation_npy not found: {elevation_npy}")
        elevation_2d = np.load(elevation_npy)
        if elevation_2d.shape != (ny, nx) or not np.isfinite(elevation_2d).all():
            raise ValueError(f"elevation_npy must be a finite ({ny}, {nx}) array, "
                             f"got {elevation_2d.shape}")
    tfg = grid.get("terrain_following", True)

    def surface_z(j, i):
        # Same surface compute_cell_elevations builds the cells from:
        # terrain-following -> DEM (or 0 without one); flat grid -> its top.
        if tfg:
            return float(elevation_2d[j, i]) if elevation_2d is not None else 0.0
        return float(total_depth)

    # Compute 3D cell center elevations
    cell_z = compute_cell_elevations(domain, elevation_2d)

    # Initialize pressure head array
    pressure = np.zeros((nz, ny, nx), dtype=np.float64)

    if method == "hydrostatic":
        # p(z) = z_wt - z_cell
        # z_wt = surface_elevation - wtd
        for j in range(ny):
            for i in range(nx):
                wt_elev = surface_z(j, i) - wtd
                for k in range(nz):
                    pressure[k, j, i] = wt_elev - cell_z[k, j, i]
                    # Positive = saturated, Negative = unsaturated

    elif method == "uniform":
        pressure[:, :, :] = uniform_pressure

    elif method == "reinecke":
        # Spatially varying WTD from the equilibrium mean water-table map on
        # disk (Fan 2013, staged under data/soil/water_table_depth/). The
        # previous path 'reinecke_wtd.tif' never existed, so this method
        # SILENTLY fell back to uniform hydrostatic -- now a hard error.
        wtd_file = os.path.join("KISSPATH_ROOT",
                                "data/groundwater/fan_wtd/MeanWaterTableDepth_meter.tif")
        if not os.path.exists(wtd_file):
            raise FileNotFoundError(
                f"Water-table-depth map not found: {wtd_file} -- "
                "use --method hydrostatic explicitly if a uniform IC is intended")
        import rasterio
        from pyproj import Transformer
        utm_epsg = domain["crs"]["epsg"]
        transformer = Transformer.from_crs(
            f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
        )
        failures = []
        with rasterio.open(wtd_file) as src:
            for j in range(ny):
                for i in range(nx):
                    cx = origin_x + (i + 0.5) * dx
                    cy = origin_y + (j + 0.5) * dy
                    lon, lat = transformer.transform(cx, cy)
                    try:
                        row, col = src.index(lon, lat)
                        if not (0 <= row < src.height and 0 <= col < src.width):
                            raise ValueError("outside the water-table-depth raster")
                        local_wtd = float(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                    except Exception as exc:
                        failures.append(f"(i={i}, j={j}) {exc}")
                        continue
                    if (not np.isfinite(local_wtd) or local_wtd < 0 or local_wtd > 500
                            or (src.nodata is not None and local_wtd == src.nodata)):
                        failures.append(f"(i={i}, j={j}) no usable depth ({local_wtd})")
                        continue
                    wt_elev = surface_z(j, i) - local_wtd
                    for k in range(nz):
                        pressure[k, j, i] = wt_elev - cell_z[k, j, i]
        if failures:
            raise ValueError(
                f"water-table-depth map has no usable value for {len(failures)} cell(s); no "
                f"fall-back depth is used. First {min(10, len(failures))}: "
                + "; ".join(failures[:10]))

    # Save
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "initial_pressure.npy")
    np.save(output_file, pressure)

    # Try PFB
    pfb_file = None
    try:
        from parflow.tools.io import write_pfb
        pfb_path = os.path.join(output_dir, "initial_pressure.pfb")
        write_pfb(pfb_path, pressure, dx=dx, dy=dy, dz=1.0,
                  x=origin_x, y=origin_y, z=0.0)
        pfb_file = pfb_path
    except ImportError:
        pass

    # Statistics
    # Stats over every simulated cell (the whole Box)
    active = np.ones((nz, ny, nx), dtype=bool)
    p_active = pressure[active]
    n_saturated = int(np.sum(p_active > 0))
    n_unsaturated = int(np.sum(p_active <= 0))

    result = {
        "status": "success",
        "method": method,
        "ic_cells": ("every cell of the rectangular grid (s7 uses Box geometry, so cells "
                     "outside the basin mask are simulated with the same IC rule)"),
        "cells_outside_mask": int(np.sum(mask_3d[0] == 0)),
        "output_npy": output_file,
        "output_pfb": pfb_file,
        "pressure_stats": {
            "min": float(np.min(p_active)) if len(p_active) > 0 else 0,
            "max": float(np.max(p_active)) if len(p_active) > 0 else 0,
            "mean": float(np.mean(p_active)) if len(p_active) > 0 else 0,
        },
        "saturated_cells": n_saturated,
        "unsaturated_cells": n_unsaturated,
        "saturation_fraction": round(n_saturated / max(len(p_active), 1), 4),
        "water_table_depth_setting": wtd if method != "uniform" else None,
        "notes": [
            "Pressure < 0 = unsaturated (suction)",
            "Pressure > 0 = saturated (positive pore pressure)",
            "Pressure = 0 = water table surface",
            "Units: meters of water head",
            "Spinup of 10-100 years recommended for equilibrium",
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate initial pressure head for ParFlow"
    )
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--mask_npy", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--method", choices=["hydrostatic", "uniform", "reinecke"],
                        default="hydrostatic")
    parser.add_argument("--wtd", type=float, default=5.0,
                        help="Water table depth below surface (m)")
    parser.add_argument("--uniform_pressure", type=float, default=-1.0,
                        help="Uniform pressure head (m)")
    parser.add_argument("--elevation_npy", default=None,
                        help="2D elevation array")
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    try:
        result = process(args.domain_json, args.mask_npy, args.output_dir,
                         args.method, args.wtd, args.uniform_pressure,
                         args.elevation_npy)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}))
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
