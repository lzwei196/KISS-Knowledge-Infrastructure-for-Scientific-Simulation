#!/usr/bin/env python3
"""
convert_soil_to_aquifer.py — Convert HWSD soil data to MODFLOW aquifer properties.

Maps soil texture classes from the Harmonized World Soil Database (HWSD) to
hydraulic conductivity (K), specific storage (Ss), and specific yield (Sy)
values suitable for MODFLOW's NPF (MF6) or LPF (MF2005) packages.

Input:
  - HWSD raster or soil texture map (GeoTIFF with USDA texture class codes)
  - Grid metadata (from build_grid_from_dem.py)
  - Optional: custom K/Ss/Sy lookup table (JSON)

Output:
  - K array (nlay, nrow, ncol) in m/day
  - Ss array (nlay, nrow, ncol) in 1/m
  - Sy array (nlay, nrow, ncol) dimensionless
  - JSON metadata with statistics and warnings

Unit Conversions (critical):
  - K: HWSD gives qualitative classes → lookup table provides m/day values
  - Ss: Typical range 1e-6 to 1e-4 (1/m) for confined aquifers
  - Sy: Typical range 0.01 to 0.35 (dimensionless)
  - K values from literature are often in cm/s → multiply by 864 to get m/day
  - K values in m/s → multiply by 86400 to get m/day

Usage:
    python convert_soil_to_aquifer.py --hwsd path/to/hwsd.tif \\
        --grid_meta path/to/grid_metadata.json --output_dir ./aquifer_props
    python convert_soil_to_aquifer.py --hwsd path/to/soil_texture.tif \\
        --grid_meta grid_metadata.json --custom_lookup my_k_table.json
"""

import argparse
import json
import os
import sys

import numpy as np

# USDA Soil Texture Class → Aquifer Properties lookup
# K in m/day, Ss in 1/m, Sy dimensionless
# Sources: Freeze & Cherry (1979), Domenico & Schwartz (1998), Rawls et al. (1982)
TEXTURE_LOOKUP = {
    # code: (name, K_m_per_day, Ss_per_m, Sy)
    1:  ("sand",              8.64,   1e-5,  0.30),
    2:  ("loamy_sand",        5.04,   2e-5,  0.28),
    3:  ("sandy_loam",        1.22,   3e-5,  0.25),
    4:  ("silt_loam",         0.264,  5e-5,  0.20),
    5:  ("silt",              0.168,  5e-5,  0.18),
    6:  ("loam",              0.504,  4e-5,  0.22),
    7:  ("sandy_clay_loam",   0.432,  6e-5,  0.18),
    8:  ("silty_clay_loam",   0.120,  8e-5,  0.15),
    9:  ("clay_loam",         0.192,  7e-5,  0.16),
    10: ("sandy_clay",        0.168,  8e-5,  0.14),
    11: ("silty_clay",        0.096,  1e-4,  0.12),
    12: ("clay",              0.048,  1e-4,  0.10),
    13: ("organic",           1.44,   3e-5,  0.35),
    14: ("gravel",            86.4,   5e-6,  0.25),
    15: ("rock",              0.001,  1e-6,  0.02),
    0:  ("nodata",            1.0,    3e-5,  0.20),  # default
}


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []
    warnings = []

    if not os.path.exists(args.hwsd):
        errors.append(f"HWSD raster not found: {args.hwsd}")

    if not os.path.exists(args.grid_meta):
        errors.append(f"Grid metadata not found: {args.grid_meta}")
    else:
        with open(args.grid_meta) as f:
            meta = json.load(f)
        required_keys = ['nlay', 'nrow', 'ncol']
        for k in required_keys:
            if k not in meta:
                errors.append(f"Missing key '{k}' in grid metadata")

    if args.custom_lookup:
        if not os.path.exists(args.custom_lookup):
            errors.append(
                f"Custom lookup table not found: {args.custom_lookup}")

    if args.k_multiplier and args.k_multiplier <= 0:
        errors.append("K multiplier must be positive")

    os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings
        }))
        sys.exit(1)

    return warnings


def read_soil_raster(hwsd_path):
    """Read soil texture class raster."""
    ext = os.path.splitext(hwsd_path)[1].lower()

    if ext in ('.tif', '.tiff'):
        try:
            import rasterio
            with rasterio.open(hwsd_path) as src:
                data = src.read(1)
                transform = src.transform
                nodata = src.nodata
            if nodata is not None:
                data = np.where(data == nodata, 0, data)
            return data.astype(int), {
                'xmin': transform.c,
                'ymax': transform.f,
                'dx': transform.a,
                'dy': -transform.e,
                'nrow': data.shape[0],
                'ncol': data.shape[1]
            }
        except ImportError:
            print("ERROR: rasterio required. Install: pip install rasterio",
                  file=sys.stderr)
            sys.exit(1)

    elif ext == '.asc':
        header = {}
        with open(hwsd_path) as f:
            for _ in range(6):
                parts = f.readline().strip().split()
                header[parts[0].lower()] = float(parts[1])
        data = np.loadtxt(hwsd_path, skiprows=6).astype(int)
        nodata = int(header.get('nodata_value', -9999))
        data = np.where(data == nodata, 0, data)
        return data, {
            'xmin': header.get('xllcorner', 0),
            'ymax': header.get('yllcorner', 0) + data.shape[0] * header['cellsize'],
            'dx': header['cellsize'],
            'dy': header['cellsize'],
            'nrow': data.shape[0],
            'ncol': data.shape[1]
        }

    raise ValueError(f"Unsupported format: {ext}")


def resample_soil_to_grid(soil_data, soil_meta, grid_meta, cell_size):
    """Resample soil texture to model grid using nearest-neighbor."""
    nrow = grid_meta['nrow']
    ncol = grid_meta['ncol']
    texture_grid = np.zeros((nrow, ncol), dtype=int)

    for i in range(nrow):
        for j in range(ncol):
            # Model cell center coordinates
            x = grid_meta.get('xmin', 0) + (j + 0.5) * cell_size
            y = grid_meta.get('ymax', soil_meta['ymax']) - (i + 0.5) * cell_size

            # Soil raster pixel
            col_idx = int((x - soil_meta['xmin']) / soil_meta['dx'])
            row_idx = int((soil_meta['ymax'] - y) / soil_meta['dy'])

            if (0 <= row_idx < soil_meta['nrow'] and
                    0 <= col_idx < soil_meta['ncol']):
                texture_grid[i, j] = soil_data[row_idx, col_idx]

    return texture_grid


def texture_to_properties(texture_grid, nlay, lookup, k_multiplier=1.0,
                          depth_decay=True):
    """Convert texture class grid to K, Ss, Sy arrays."""
    nrow, ncol = texture_grid.shape
    k_array = np.zeros((nlay, nrow, ncol))
    ss_array = np.zeros((nlay, nrow, ncol))
    sy_array = np.zeros((nlay, nrow, ncol))

    for i in range(nrow):
        for j in range(ncol):
            code = texture_grid[i, j]
            if code not in lookup:
                code = 0  # default
            _, k, ss, sy = lookup[code]

            for lay in range(nlay):
                # Apply depth decay: K decreases with depth
                if depth_decay and lay > 0:
                    decay_factor = 0.5 ** lay  # halve K per layer
                    k_array[lay, i, j] = k * decay_factor * k_multiplier
                else:
                    k_array[lay, i, j] = k * k_multiplier

                ss_array[lay, i, j] = ss
                sy_array[lay, i, j] = sy if lay == 0 else sy * 0.5

    return k_array, ss_array, sy_array


def process(args, warnings_list):
    """Main processing: soil data → aquifer property arrays."""
    with open(args.grid_meta) as f:
        grid_meta = json.load(f)

    nlay = grid_meta['nlay']
    nrow = grid_meta['nrow']
    ncol = grid_meta['ncol']
    cell_size = grid_meta.get('delr', grid_meta.get('cell_size_m', 250))

    # Load lookup table
    lookup = TEXTURE_LOOKUP.copy()
    if args.custom_lookup:
        with open(args.custom_lookup) as f:
            custom = json.load(f)
        for code_str, props in custom.items():
            code = int(code_str)
            lookup[code] = (props['name'], props['K'], props['Ss'], props['Sy'])

    # Read and resample soil data
    print(f"Reading soil data: {args.hwsd}", file=sys.stderr)
    soil_data, soil_meta = read_soil_raster(args.hwsd)

    print(f"Resampling to model grid ({nrow}x{ncol})...", file=sys.stderr)
    texture_grid = resample_soil_to_grid(
        soil_data, soil_meta, grid_meta, cell_size)

    # Convert to properties
    k_multiplier = args.k_multiplier if args.k_multiplier else 1.0
    k_array, ss_array, sy_array = texture_to_properties(
        texture_grid, nlay, lookup, k_multiplier,
        depth_decay=not args.no_depth_decay)

    # Save arrays
    np.save(os.path.join(args.output_dir, 'hk.npy'), k_array)
    np.save(os.path.join(args.output_dir, 'ss.npy'), ss_array)
    np.save(os.path.join(args.output_dir, 'sy.npy'), sy_array)
    np.save(os.path.join(args.output_dir, 'texture_grid.npy'), texture_grid)

    # Statistics
    unique_textures, counts = np.unique(texture_grid, return_counts=True)
    texture_stats = {}
    for code, count in zip(unique_textures, counts):
        name = lookup.get(int(code), ("unknown",))[0]
        texture_stats[name] = int(count)

    metadata = {
        'nlay': nlay, 'nrow': nrow, 'ncol': ncol,
        'K_range_m_per_day': [float(np.min(k_array)), float(np.max(k_array))],
        'K_mean_m_per_day': float(np.mean(k_array)),
        'Ss_range_per_m': [float(np.min(ss_array)), float(np.max(ss_array))],
        'Sy_range': [float(np.min(sy_array)), float(np.max(sy_array))],
        'texture_distribution': texture_stats,
        'k_multiplier': k_multiplier,
        'depth_decay': not args.no_depth_decay,
        'warnings': warnings_list
    }

    meta_path = os.path.join(args.output_dir, 'aquifer_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Aquifer properties saved to {args.output_dir}", file=sys.stderr)
    return metadata


def validate_outputs(metadata, output_dir):
    """Post-processing validation of aquifer property arrays."""
    errors = []
    warnings = []

    # Check files exist
    for fname in ['hk.npy', 'ss.npy', 'sy.npy']:
        if not os.path.exists(os.path.join(output_dir, fname)):
            errors.append(f"Missing: {fname}")

    # Physical range checks
    k_range = metadata['K_range_m_per_day']
    if k_range[0] <= 0:
        errors.append(f"K has zero/negative values (min={k_range[0]})")
    if k_range[1] > 1000:
        warnings.append(
            f"K max = {k_range[1]} m/day — check units. "
            "Typical aquifer K < 100 m/day except gravel.")
    if k_range[1] < 0.001:
        warnings.append(
            f"K max = {k_range[1]} m/day — very low. "
            "May be in cm/s (multiply by 864)?")

    ss_range = metadata['Ss_range_per_m']
    if ss_range[0] < 0:
        errors.append("Specific storage has negative values")
    if ss_range[1] > 0.01:
        warnings.append(
            f"Ss max = {ss_range[1]} 1/m — unusually high. "
            "Typical: 1e-6 to 1e-4")

    sy_range = metadata['Sy_range']
    if sy_range[0] < 0 or sy_range[1] > 0.5:
        errors.append(
            f"Sy out of physical range [0, 0.5]: "
            f"[{sy_range[0]}, {sy_range[1]}]")

    result = {
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "K_stats": {
            "min": k_range[0], "max": k_range[1],
            "mean": metadata['K_mean_m_per_day']
        }
    }
    print(json.dumps(result, indent=2))
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Convert HWSD soil data to MODFLOW aquifer properties')
    parser.add_argument('--hwsd', required=True,
                        help='Path to HWSD soil texture raster')
    parser.add_argument('--grid_meta', required=True,
                        help='Path to grid_metadata.json from build_grid_from_dem')
    parser.add_argument('--custom_lookup', default=None,
                        help='Custom K/Ss/Sy lookup table (JSON)')
    parser.add_argument('--k_multiplier', type=float, default=1.0,
                        help='Multiplier for all K values (calibration)')
    parser.add_argument('--no_depth_decay', action='store_true',
                        help='Disable K depth decay between layers')
    parser.add_argument('--output_dir', default='./aquifer_props',
                        help='Output directory')
    args = parser.parse_args()

    warnings_list = validate_inputs(args)
    metadata = process(args, warnings_list)
    validate_outputs(metadata, args.output_dir)


if __name__ == '__main__':
    main()
