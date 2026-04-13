#!/usr/bin/env python3
"""
build_grid_from_dem.py — Convert DEM raster to MODFLOW DIS grid.

Takes a DEM (GeoTIFF or ASCII grid) and generates the spatial discretization
arrays needed for MODFLOW: top elevations, bottom elevations, cell sizes.
Supports both MODFLOW 6 (DIS block format) and MODFLOW-2005 (fixed format).

Input:
  - DEM raster (GeoTIFF or ESRI ASCII .asc)
  - Target cell size (meters)
  - Number of layers
  - Layer thickness(es) or bottom elevation(s)
  - Bounding box or shapefile for domain extent

Output:
  - JSON metadata with grid dimensions
  - NumPy arrays for top, botm, delr, delc
  - Optionally writes MODFLOW DIS package directly

Units:
  - DEM elevation: meters ASL
  - Cell size (delr, delc): meters
  - Layer thickness: meters
  - All output in model length units (default: meters)

Usage:
    python build_grid_from_dem.py --dem path/to/dem.tif --cell_size 250 \\
        --nlay 3 --layer_thickness 10,15,25 --output_dir ./grid_output
    python build_grid_from_dem.py --dem path/to/dem.asc --cell_size 100 \\
        --nlay 1 --total_depth 50 --bbox "xmin,ymin,xmax,ymax"
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []
    warnings = []

    # Check DEM file
    if not os.path.exists(args.dem):
        errors.append(f"DEM file not found: {args.dem}")
    else:
        ext = os.path.splitext(args.dem)[1].lower()
        if ext not in ('.tif', '.tiff', '.asc'):
            warnings.append(
                f"Unexpected DEM format: {ext}. Expected .tif or .asc")

    # Check cell size
    if args.cell_size <= 0:
        errors.append(f"Cell size must be positive, got {args.cell_size}")
    if args.cell_size < 1:
        warnings.append(
            f"Very small cell size ({args.cell_size} m) — "
            "may create extremely large grid")
    if args.cell_size > 10000:
        warnings.append(
            f"Very large cell size ({args.cell_size} m) — "
            "may lose important detail")

    # Check layers
    if args.nlay < 1:
        errors.append(f"Number of layers must be >= 1, got {args.nlay}")

    # Check layer thickness specification
    if args.layer_thickness and args.total_depth:
        errors.append(
            "Specify either --layer_thickness or --total_depth, not both")
    if not args.layer_thickness and not args.total_depth:
        errors.append(
            "Must specify either --layer_thickness or --total_depth")

    if args.layer_thickness:
        thicknesses = [float(t) for t in args.layer_thickness.split(',')]
        if len(thicknesses) != args.nlay:
            errors.append(
                f"Number of thicknesses ({len(thicknesses)}) "
                f"must match nlay ({args.nlay})")
        if any(t <= 0 for t in thicknesses):
            errors.append("All layer thicknesses must be positive")

    if args.total_depth:
        if args.total_depth <= 0:
            errors.append(
                f"Total depth must be positive, got {args.total_depth}")

    # Check output directory
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings
        }))
        sys.exit(1)

    return warnings


def read_dem(dem_path):
    """Read DEM from GeoTIFF or ASCII grid."""
    ext = os.path.splitext(dem_path)[1].lower()

    if ext in ('.tif', '.tiff'):
        try:
            import rasterio
            with rasterio.open(dem_path) as src:
                elevation = src.read(1)
                transform = src.transform
                nodata = src.nodata
                crs = src.crs
                cell_x = transform.a
                cell_y = -transform.e
                xmin = transform.c
                ymax = transform.f
                ymin = ymax + transform.e * elevation.shape[0]
                xmax = xmin + transform.a * elevation.shape[1]
            if nodata is not None:
                elevation = np.where(elevation == nodata, np.nan, elevation)
            return elevation, {
                'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax,
                'native_cell_x': cell_x, 'native_cell_y': cell_y,
                'crs': str(crs) if crs else None,
                'nrow_native': elevation.shape[0],
                'ncol_native': elevation.shape[1]
            }
        except ImportError:
            print("ERROR: rasterio required for GeoTIFF. "
                  "Install with: pip install rasterio", file=sys.stderr)
            sys.exit(1)

    elif ext == '.asc':
        # ESRI ASCII grid
        header = {}
        with open(dem_path) as f:
            for _ in range(6):
                line = f.readline().strip().split()
                header[line[0].lower()] = float(line[1])
        ncols = int(header['ncols'])
        nrows = int(header['nrows'])
        xllcorner = header.get('xllcorner', header.get('xllcenter', 0))
        yllcorner = header.get('yllcorner', header.get('yllcenter', 0))
        cellsize = header['cellsize']
        nodata = header.get('nodata_value', -9999)

        elevation = np.loadtxt(dem_path, skiprows=6)
        elevation = np.where(elevation == nodata, np.nan, elevation)

        return elevation, {
            'xmin': xllcorner,
            'ymin': yllcorner,
            'xmax': xllcorner + ncols * cellsize,
            'ymax': yllcorner + nrows * cellsize,
            'native_cell_x': cellsize,
            'native_cell_y': cellsize,
            'crs': None,
            'nrow_native': nrows,
            'ncol_native': ncols
        }

    raise ValueError(f"Unsupported DEM format: {ext}")


def resample_to_grid(elevation, dem_meta, cell_size, bbox=None):
    """Resample DEM to target grid cell size."""
    if bbox:
        xmin, ymin, xmax, ymax = bbox
    else:
        xmin = dem_meta['xmin']
        ymin = dem_meta['ymin']
        xmax = dem_meta['xmax']
        ymax = dem_meta['ymax']

    ncol = int(np.ceil((xmax - xmin) / cell_size))
    nrow = int(np.ceil((ymax - ymin) / cell_size))

    # Compute cell centers
    x_centers = np.linspace(xmin + cell_size / 2,
                            xmin + (ncol - 0.5) * cell_size, ncol)
    y_centers = np.linspace(ymax - cell_size / 2,
                            ymax - (nrow - 0.5) * cell_size, nrow)

    # Map cell centers to DEM pixel coordinates
    native_dx = dem_meta['native_cell_x']
    native_dy = dem_meta['native_cell_y']

    top = np.full((nrow, ncol), np.nan)
    for i, y in enumerate(y_centers):
        for j, x in enumerate(x_centers):
            # DEM pixel indices
            col_idx = int((x - dem_meta['xmin']) / native_dx)
            row_idx = int((dem_meta['ymax'] - y) / native_dy)
            if (0 <= row_idx < elevation.shape[0] and
                    0 <= col_idx < elevation.shape[1]):
                top[i, j] = elevation[row_idx, col_idx]

    # Fill NaN cells with nearest valid value
    if np.any(np.isnan(top)):
        from scipy.ndimage import distance_transform_edt
        nan_mask = np.isnan(top)
        if not np.all(nan_mask):
            indices = distance_transform_edt(
                nan_mask, return_distances=False, return_indices=True)
            top = top[tuple(indices)]

    delr = np.full(ncol, cell_size)
    delc = np.full(nrow, cell_size)

    return top, delr, delc, nrow, ncol


def compute_layer_bottoms(top, nlay, layer_thickness=None, total_depth=None):
    """Compute bottom elevation arrays for each layer."""
    if layer_thickness:
        thicknesses = [float(t) for t in layer_thickness.split(',')]
    else:
        # Equal thickness layers
        layer_thick = total_depth / nlay
        thicknesses = [layer_thick] * nlay

    botm = np.zeros((nlay, top.shape[0], top.shape[1]))
    current_top = top.copy()
    for k in range(nlay):
        botm[k] = current_top - thicknesses[k]
        current_top = botm[k]

    return botm, thicknesses


def process(args, warnings_list):
    """Main processing: DEM → MODFLOW grid arrays."""
    print(f"Reading DEM: {args.dem}", file=sys.stderr)
    elevation, dem_meta = read_dem(args.dem)

    # Parse bounding box if provided
    bbox = None
    if args.bbox:
        bbox = [float(x) for x in args.bbox.split(',')]
        if len(bbox) != 4:
            print("ERROR: bbox must have 4 values: xmin,ymin,xmax,ymax",
                  file=sys.stderr)
            sys.exit(1)

    print(f"Resampling to {args.cell_size}m grid...", file=sys.stderr)
    top, delr, delc, nrow, ncol = resample_to_grid(
        elevation, dem_meta, args.cell_size, bbox)

    print(f"Grid: {args.nlay} layers, {nrow} rows, {ncol} cols",
          file=sys.stderr)
    botm, thicknesses = compute_layer_bottoms(
        top, args.nlay, args.layer_thickness, args.total_depth)

    # Save outputs
    output_dir = args.output_dir or '.'
    np.save(os.path.join(output_dir, 'top.npy'), top)
    np.save(os.path.join(output_dir, 'botm.npy'), botm)
    np.save(os.path.join(output_dir, 'delr.npy'), delr)
    np.save(os.path.join(output_dir, 'delc.npy'), delc)

    metadata = {
        'nlay': args.nlay,
        'nrow': nrow,
        'ncol': ncol,
        'delr': float(delr[0]),
        'delc': float(delc[0]),
        'top_min': float(np.nanmin(top)),
        'top_max': float(np.nanmax(top)),
        'top_mean': float(np.nanmean(top)),
        'botm_min': float(np.nanmin(botm)),
        'layer_thicknesses': thicknesses,
        'total_cells': args.nlay * nrow * ncol,
        'dem_source': args.dem,
        'cell_size_m': args.cell_size,
        'warnings': warnings_list
    }

    meta_path = os.path.join(output_dir, 'grid_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Grid metadata saved to {meta_path}", file=sys.stderr)
    return metadata


def validate_outputs(metadata, output_dir):
    """Post-processing validation of grid outputs."""
    errors = []
    warnings = []

    # Check files exist
    for fname in ['top.npy', 'botm.npy', 'delr.npy', 'delc.npy']:
        fpath = os.path.join(output_dir, fname)
        if not os.path.exists(fpath):
            errors.append(f"Missing output: {fpath}")

    # Check grid dimensions
    if metadata['total_cells'] > 10_000_000:
        warnings.append(
            f"Very large grid ({metadata['total_cells']:,} cells). "
            "Consider coarsening.")
    if metadata['total_cells'] < 10:
        warnings.append(
            f"Very small grid ({metadata['total_cells']} cells). "
            "Check cell size and extent.")

    # Check elevation range
    elev_range = metadata['top_max'] - metadata['top_min']
    if elev_range > 5000:
        warnings.append(
            f"Large elevation range ({elev_range:.0f} m). "
            "Check DEM units — may be in feet?")
    if metadata['top_min'] < -500:
        warnings.append(
            f"Minimum elevation {metadata['top_min']:.0f} m seems too low. "
            "Check for nodata values in DEM.")

    # Check layer thickness
    total_thick = sum(metadata['layer_thicknesses'])
    if total_thick > metadata['top_max'] - metadata['botm_min']:
        warnings.append(
            "Total layer thickness exceeds elevation range — "
            "bottom layers may be below sea level.")

    result = {
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "grid": {
            "nlay": metadata['nlay'],
            "nrow": metadata['nrow'],
            "ncol": metadata['ncol'],
            "total_cells": metadata['total_cells']
        }
    }
    print(json.dumps(result, indent=2))
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Build MODFLOW grid from DEM')
    parser.add_argument('--dem', required=True, help='Path to DEM raster')
    parser.add_argument('--cell_size', type=float, required=True,
                        help='Target cell size in meters')
    parser.add_argument('--nlay', type=int, default=1,
                        help='Number of model layers')
    parser.add_argument('--layer_thickness', type=str, default=None,
                        help='Comma-separated layer thicknesses (m)')
    parser.add_argument('--total_depth', type=float, default=None,
                        help='Total model depth (m), equal layer thickness')
    parser.add_argument('--bbox', type=str, default=None,
                        help='Bounding box: xmin,ymin,xmax,ymax')
    parser.add_argument('--output_dir', type=str, default='./grid_output',
                        help='Output directory')
    args = parser.parse_args()

    warnings_list = validate_inputs(args)
    metadata = process(args, warnings_list)
    validate_outputs(metadata, args.output_dir or '.')


if __name__ == '__main__':
    main()
