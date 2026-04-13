#!/usr/bin/env python3
"""
parse_lpjml_output.py — Parse LPJmL binary output files to CSV.

Reads LPJmL raw binary (.bin) or CLM output files and extracts data
as CSV time series. Supports grid-based extraction, spatial averaging,
and yield unit conversion (gC/m2 -> t DM/ha).

Usage:
    python parse_lpjml_output.py --input output/pft_harvest.pft.bin \
        --grid output/grid.bin --output harvest.csv \
        --variable pft_harvestc --cell 27410 \
        --convert_yield

    python parse_lpjml_output.py --input output/mnpp.bin \
        --grid output/grid.bin --output npp.csv \
        --variable npp --firstyear 1901 --lastyear 2019 \
        --timestep monthly

Pattern: validate -> process -> validate
"""

import argparse
import csv
import json
import struct
import sys
import os
import numpy as np


# Default output variable metadata
OUTPUT_METADATA = {
    "npp": {"unit": "gC/m2/month", "timestep": "monthly", "nbands": 1},
    "gpp": {"unit": "gC/m2/month", "timestep": "monthly", "nbands": 1},
    "rh": {"unit": "gC/m2/month", "timestep": "monthly", "nbands": 1},
    "runoff": {"unit": "mm/month", "timestep": "monthly", "nbands": 1},
    "discharge": {"unit": "hm3/day", "timestep": "monthly", "nbands": 1},
    "evap": {"unit": "mm/month", "timestep": "monthly", "nbands": 1},
    "transp": {"unit": "mm/month", "timestep": "monthly", "nbands": 1},
    "harvestc": {"unit": "gC/m2/yr", "timestep": "annual", "nbands": 1},
    "pft_harvestc": {"unit": "gC/m2/yr", "timestep": "annual", "nbands": 32},
    "vegc": {"unit": "gC/m2", "timestep": "annual", "nbands": 1},
    "soilc": {"unit": "gC/m2", "timestep": "annual", "nbands": 1},
    "firec": {"unit": "gC/m2/yr", "timestep": "annual", "nbands": 1},
    "sdate": {"unit": "DOY", "timestep": "annual", "nbands": 24},
    "hdate": {"unit": "DOY", "timestep": "annual", "nbands": 24},
    "irrig": {"unit": "mm/month", "timestep": "monthly", "nbands": 1},
}

# CFT names corresponding to band indices in pft_harvest
CFT_NAMES = [
    "temperate_cereals_rf", "rice_rf", "maize_rf", "tropical_cereals_rf",
    "pulses_rf", "temperate_roots_rf", "tropical_roots_rf",
    "oil_sunflower_rf", "oil_soybean_rf", "oil_groundnut_rf",
    "oil_rapeseed_rf", "sugarcane_rf", "others_rf", "grassland_rf",
    "biomass_grass_rf", "biomass_tree_rf",
    "temperate_cereals_ir", "rice_ir", "maize_ir", "tropical_cereals_ir",
    "pulses_ir", "temperate_roots_ir", "tropical_roots_ir",
    "oil_sunflower_ir", "oil_soybean_ir", "oil_groundnut_ir",
    "oil_rapeseed_ir", "sugarcane_ir", "others_ir", "grassland_ir",
    "biomass_grass_ir", "biomass_tree_ir",
]

# Carbon fraction in dry biomass
BIOMASS2C = 0.45


def read_grid_file(grid_path):
    """Read LPJmL grid file (short or float coordinates)."""
    with open(grid_path, "rb") as f:
        data = f.read()

    # Try to detect header
    if data[:7] in [b"LPJGRID", b"LPJCLIM"]:
        # Has header - skip it (basic CLM header is 43 bytes for v3)
        header_size = 7 + 4 * 7 + 4 * 2 + 4 + 4 + 4  # 59 bytes for CLM v3
        offset = header_size
    else:
        offset = 0

    remaining = data[offset:]

    # Try short format (default): pairs of (lon, lat) as int16 * 0.01
    n_coords = len(remaining) // 4  # 2 shorts = 4 bytes per cell
    if n_coords > 0:
        coords = np.frombuffer(remaining[:n_coords * 4], dtype=np.int16)
        coords = coords.reshape(-1, 2) * 0.01
        return coords  # (ncell, 2) -> lon, lat

    return np.array([])


def validate_inputs(input_path, grid_path=None):
    """Pre-processing validation."""
    errors = []

    if not os.path.exists(input_path):
        errors.append(f"Input file not found: {input_path}")

    if grid_path and not os.path.exists(grid_path):
        errors.append(f"Grid file not found: {grid_path}")

    return errors


def read_metafile(input_path):
    """Try to read JSON metafile for output variable."""
    meta_path = input_path + ".json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    # Try replacing extension
    base = os.path.splitext(input_path)[0]
    meta_path = base + ".json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                return json.load(f)
        except Exception:
            pass

    return None


def read_raw_output(input_path, ncell, nbands, nstep, nyear, dtype=np.float32):
    """Read raw binary output file."""
    with open(input_path, "rb") as f:
        data = f.read()

    # Check for header
    offset = 0
    if data[:7] in [b"LPJCLIM", b"LPJGRID", b"LPJSOIL"]:
        offset = 7 + 4 * 7 + 4 * 2 + 4 + 4 + 4  # CLM v3 header

    remaining = data[offset:]
    expected_size = ncell * nbands * nstep * nyear * dtype().itemsize

    if len(remaining) < expected_size:
        # Try with float32
        arr = np.frombuffer(remaining, dtype=dtype)
    else:
        arr = np.frombuffer(remaining[:expected_size], dtype=dtype)

    total_steps = nstep * nyear
    if len(arr) >= ncell * nbands * total_steps:
        return arr.reshape(total_steps, ncell, nbands)
    elif len(arr) >= ncell * total_steps:
        return arr.reshape(total_steps, ncell, 1)
    else:
        return arr.reshape(-1, ncell) if len(arr) % ncell == 0 else arr


def gc_to_yield(gc_m2):
    """Convert gC/m2 to t DM/ha."""
    return gc_m2 / BIOMASS2C * 0.01


def validate_outputs(data, variable):
    """Post-processing validation of extracted data."""
    warnings = []

    if np.all(data == 0):
        warnings.append(f"WARNING: All values are zero for {variable}.")

    if np.any(np.isnan(data)):
        nan_frac = np.isnan(data).sum() / data.size * 100
        warnings.append(f"WARNING: {nan_frac:.1f}% NaN values in {variable}.")

    if np.any(np.isinf(data)):
        warnings.append(f"WARNING: Infinite values found in {variable}.")

    return warnings


def process(input_path, grid_path, output_path, variable,
            cell=None, firstyear=1901, lastyear=2019,
            timestep="monthly", nbands=None, convert_yield=False,
            lat=None, lon=None):
    """Main processing: read binary -> extract -> CSV."""

    # Step 1: Validate inputs
    errors = validate_inputs(input_path, grid_path)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Read grid
    if grid_path:
        grid = read_grid_file(grid_path)
        ncell = len(grid)
        print(f"Grid: {ncell} cells")
    else:
        # Estimate from file size
        file_size = os.path.getsize(input_path)
        ncell = 67420  # default global 0.5-degree grid
        print(f"No grid file, assuming {ncell} cells")

    # Determine metadata
    meta = read_metafile(input_path)
    if meta:
        print(f"Metafile found: {json.dumps(meta, indent=2)[:200]}")

    if variable in OUTPUT_METADATA and nbands is None:
        nbands = OUTPUT_METADATA[variable]["nbands"]
        if timestep == "auto":
            timestep = OUTPUT_METADATA[variable]["timestep"]

    if nbands is None:
        nbands = 1

    nstep = 12 if timestep == "monthly" else 1 if timestep == "annual" else 365
    nyear = lastyear - firstyear + 1

    # Find cell index by lat/lon
    if cell is None and lat is not None and lon is not None and grid_path:
        distances = np.sqrt((grid[:, 0] - lon)**2 + (grid[:, 1] - lat)**2)
        cell = int(np.argmin(distances))
        print(f"Nearest cell to ({lat}, {lon}): index {cell}, "
              f"coords ({grid[cell, 0]:.2f}, {grid[cell, 1]:.2f})")

    # Step 2: Read data
    print(f"Reading {input_path}: {nyear} years, {nstep} steps/year, "
          f"{nbands} bands, {ncell} cells")

    try:
        data = read_raw_output(input_path, ncell, nbands, nstep, nyear)
    except Exception as e:
        print(f"ERROR reading data: {e}", file=sys.stderr)
        # Try alternative dtypes
        for dt in [np.float32, np.int16, np.int32]:
            try:
                data = read_raw_output(input_path, ncell, nbands, nstep, nyear, dtype=dt)
                print(f"Successfully read with dtype={dt}")
                if dt in [np.int16, np.int32]:
                    data = data.astype(np.float32)
                break
            except Exception:
                continue
        else:
            return False

    print(f"Data shape: {data.shape}")

    # Step 3: Extract for specific cell or global mean
    if cell is not None:
        if data.ndim == 3:
            extracted = data[:, cell, :]
        else:
            extracted = data[:, cell] if data.ndim == 2 else data
        print(f"Extracted cell {cell}")
    else:
        # Global mean
        if data.ndim == 3:
            extracted = np.nanmean(data, axis=1)
        else:
            extracted = np.nanmean(data, axis=1) if data.ndim == 2 else data
        print("Computing global mean")

    # Convert yield if requested
    if convert_yield:
        extracted = gc_to_yield(extracted)
        print("Converted gC/m2 -> t DM/ha")

    # Step 4: Validate
    warnings = validate_outputs(extracted, variable)
    for w in warnings:
        print(w, file=sys.stderr)

    # Step 5: Write CSV
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        if nbands > 1 and nbands <= len(CFT_NAMES):
            header = ["year"]
            if timestep == "monthly":
                header.append("month")
            header.extend(CFT_NAMES[:nbands])
        else:
            header = ["year"]
            if timestep == "monthly":
                header.append("month")
            header.append(variable)

        writer.writerow(header)

        # Data rows
        idx = 0
        for year in range(firstyear, lastyear + 1):
            for step in range(nstep):
                if idx >= len(extracted):
                    break
                row = [year]
                if timestep == "monthly":
                    row.append(step + 1)
                if extracted.ndim == 1:
                    row.append(f"{extracted[idx]:.6f}")
                else:
                    row.extend([f"{v:.6f}" for v in extracted[idx]])
                writer.writerow(row)
                idx += 1

    print(f"Written: {output_path} ({idx} rows)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Parse LPJmL binary output files to CSV"
    )
    parser.add_argument("--input", required=True, help="Input binary file")
    parser.add_argument("--grid", default=None, help="Grid binary file")
    parser.add_argument("--output", required=True, help="Output CSV file")
    parser.add_argument("--variable", required=True, help="Variable name")
    parser.add_argument("--cell", type=int, default=None, help="Cell index to extract")
    parser.add_argument("--lat", type=float, default=None, help="Latitude for cell lookup")
    parser.add_argument("--lon", type=float, default=None, help="Longitude for cell lookup")
    parser.add_argument("--firstyear", type=int, default=1901, help="First year")
    parser.add_argument("--lastyear", type=int, default=2019, help="Last year")
    parser.add_argument("--timestep", default="monthly",
                        choices=["monthly", "annual", "daily", "auto"],
                        help="Output timestep")
    parser.add_argument("--nbands", type=int, default=None, help="Number of bands")
    parser.add_argument("--convert_yield", action="store_true",
                        help="Convert gC/m2 to t DM/ha")

    args = parser.parse_args()

    success = process(
        input_path=args.input,
        grid_path=args.grid,
        output_path=args.output,
        variable=args.variable,
        cell=args.cell,
        firstyear=args.firstyear,
        lastyear=args.lastyear,
        timestep=args.timestep,
        nbands=args.nbands,
        convert_yield=args.convert_yield,
        lat=args.lat,
        lon=args.lon,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
