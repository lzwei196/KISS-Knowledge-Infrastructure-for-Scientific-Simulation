#!/usr/bin/env python3
"""
convert_climate_to_clm.py — Convert NetCDF climate forcing to LPJmL CLM binary format.

Converts global gridded climate data (GSWP3-W5E5, CRU, ISIMIP, ERA5)
to the CLM binary format required by LPJmL. Handles unit conversions
for temperature (K->degC), precipitation (kg/m2/s->mm/day),
radiation (J/m2->W/m2), and wind speed.

Usage:
    python convert_climate_to_clm.py --input temp.nc --variable tas \
        --output temp.clm --clm_id 1 --unit_from K --unit_to degC \
        --firstyear 1901 --lastyear 2019

Pattern: validate -> process -> validate
"""

import argparse
import struct
import sys
import os
import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

# CLM header constants
CLM_HEADER_ID = b"LPJCLIM"
CLM_VERSION = 3

# Unit conversion registry: (source_unit, target_unit) -> function
UNIT_CONVERSIONS = {
    ("K", "degC"): lambda x: x - 273.15,
    ("degC", "degC"): lambda x: x,
    ("kg/m2/s", "mm/day"): lambda x: x * 86400.0,
    ("mm/day", "mm/day"): lambda x: x,
    ("mm/month", "mm/month"): lambda x: x,
    ("J/m2/day", "W/m2"): lambda x: x / 86400.0,
    ("W/m2", "W/m2"): lambda x: x,
    ("km/h", "m/s"): lambda x: x / 3.6,
    ("m/s", "m/s"): lambda x: x,
    ("g/kg", "kg/kg"): lambda x: x / 1000.0,
    ("kg/kg", "kg/kg"): lambda x: x,
    ("mol/mol", "ppm"): lambda x: x * 1e6,
    ("ppm", "ppm"): lambda x: x,
}

# Physical range checks for validated climate variables
VALID_RANGES = {
    "temp": (-90.0, 60.0),       # degC
    "prec": (0.0, 500.0),        # mm/day
    "swdown": (0.0, 500.0),      # W/m2
    "lwnet": (-200.0, 100.0),    # W/m2
    "wind": (0.0, 50.0),         # m/s
    "tmin": (-90.0, 55.0),       # degC
    "tmax": (-80.0, 60.0),       # degC
    "humid": (0.0, 0.05),        # kg/kg
}


def validate_inputs(input_path, variable):
    """Pre-processing validation: check file exists and variable is present."""
    errors = []
    if not os.path.exists(input_path):
        errors.append(f"Input file not found: {input_path}")
        return errors

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")
        return errors

    try:
        ds = nc.Dataset(input_path, "r")
        if variable not in ds.variables:
            available = list(ds.variables.keys())
            errors.append(
                f"Variable '{variable}' not found in {input_path}. "
                f"Available: {available}"
            )
        ds.close()
    except Exception as e:
        errors.append(f"Cannot open NetCDF file: {e}")

    return errors


def write_clm_header(f, clm_id, firstyear, nyear, firstcell, ncell,
                     nbands, cellsize_lon=0.5, cellsize_lat=0.5,
                     datatype=1, scalar=1.0, nstep=12):
    """Write CLM version 3 binary header."""
    # Header: 7-byte ID string + header fields
    f.write(CLM_HEADER_ID)
    # version, order, firstyear, nyear, firstcell, ncell, nbands
    f.write(struct.pack("<i", CLM_VERSION))
    f.write(struct.pack("<i", 1))  # order: cell-index
    f.write(struct.pack("<i", firstyear))
    f.write(struct.pack("<i", nyear))
    f.write(struct.pack("<i", firstcell))
    f.write(struct.pack("<i", ncell))
    f.write(struct.pack("<i", nbands))
    f.write(struct.pack("<f", cellsize_lon))
    f.write(struct.pack("<f", cellsize_lat))
    f.write(struct.pack("<i", datatype))  # 1=short
    f.write(struct.pack("<f", scalar))
    f.write(struct.pack("<i", nstep))


def convert_units(data, unit_from, unit_to):
    """Apply unit conversion using the registry."""
    key = (unit_from, unit_to)
    if key not in UNIT_CONVERSIONS:
        raise ValueError(
            f"Unknown unit conversion: {unit_from} -> {unit_to}. "
            f"Supported: {list(UNIT_CONVERSIONS.keys())}"
        )
    return UNIT_CONVERSIONS[key](data)


def validate_outputs(data, var_type, unit_to):
    """Post-processing validation: check output values are in physical range."""
    warnings = []

    if var_type in VALID_RANGES:
        vmin, vmax = VALID_RANGES[var_type]
        actual_min = float(np.nanmin(data))
        actual_max = float(np.nanmax(data))

        if actual_min < vmin - 10:
            warnings.append(
                f"WARNING: {var_type} min={actual_min:.2f} below physical "
                f"limit {vmin}. Check unit conversion ({unit_to})."
            )
        if actual_max > vmax + 10:
            warnings.append(
                f"WARNING: {var_type} max={actual_max:.2f} above physical "
                f"limit {vmax}. Check unit conversion ({unit_to})."
            )

    nan_count = int(np.isnan(data).sum())
    if nan_count > 0:
        warnings.append(f"WARNING: {nan_count} NaN values in output data.")

    return warnings


def process(input_path, variable, output_path, clm_id,
            unit_from, unit_to, firstyear, lastyear,
            var_type=None, scalar=1.0, nstep=12):
    """Main conversion: NetCDF -> CLM binary with unit conversion."""

    # Step 1: Validate inputs
    errors = validate_inputs(input_path, variable)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Step 2: Read NetCDF data
    ds = nc.Dataset(input_path, "r")
    var_data = ds.variables[variable]

    # Determine dimensions
    dims = var_data.dimensions
    shape = var_data.shape
    print(f"Input shape: {shape}, dims: {dims}")

    # Extract time, lat, lon dimensions
    time_dim = [d for d in dims if "time" in d.lower()][0] if any("time" in d.lower() for d in dims) else dims[0]
    ntime = ds.dimensions[time_dim].size

    # Assume last two dims are lat, lon
    nlat = shape[-2]
    nlon = shape[-1]
    ncell = nlat * nlon

    nyear = lastyear - firstyear + 1
    nbands = nstep  # monthly=12, daily=365

    print(f"Converting {variable}: {ntime} timesteps, {ncell} cells")
    print(f"Unit conversion: {unit_from} -> {unit_to}")

    # Step 3: Process data with unit conversion
    data = var_data[:].reshape(ntime, -1)  # (time, cells)

    # Handle masked arrays
    if hasattr(data, "filled"):
        data = data.filled(np.nan)

    data = data.astype(np.float64)
    data = convert_units(data, unit_from, unit_to)

    # Replace NaN with -9999
    data = np.where(np.isnan(data), -9999.0, data)

    # Step 4: Validate outputs
    if var_type is None:
        var_type = variable
    warnings = validate_outputs(data, var_type, unit_to)
    for w in warnings:
        print(w, file=sys.stderr)

    # Step 5: Write CLM binary
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        write_clm_header(
            f, clm_id, firstyear, nyear,
            firstcell=0, ncell=ncell, nbands=1,
            datatype=3,  # float
            scalar=scalar, nstep=nstep
        )
        data.astype(np.float32).tofile(f)

    print(f"Written: {output_path} ({os.path.getsize(output_path)} bytes)")
    print(f"  Cells: {ncell}, Years: {nyear}, Steps/year: {nstep}")

    ds.close()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert NetCDF climate data to LPJmL CLM binary format"
    )
    parser.add_argument("--input", required=True, help="Input NetCDF file")
    parser.add_argument("--variable", required=True, help="NetCDF variable name")
    parser.add_argument("--output", required=True, help="Output CLM file path")
    parser.add_argument("--clm_id", type=int, default=1, help="CLM variable ID")
    parser.add_argument("--unit_from", default="degC", help="Source unit")
    parser.add_argument("--unit_to", default="degC", help="Target LPJmL unit")
    parser.add_argument("--var_type", default=None, help="Variable type for range check")
    parser.add_argument("--firstyear", type=int, default=1901, help="First year")
    parser.add_argument("--lastyear", type=int, default=2019, help="Last year")
    parser.add_argument("--scalar", type=float, default=1.0, help="Scale factor")
    parser.add_argument("--nstep", type=int, default=12,
                        help="Time steps per year (12=monthly, 365=daily)")

    args = parser.parse_args()

    success = process(
        input_path=args.input,
        variable=args.variable,
        output_path=args.output,
        clm_id=args.clm_id,
        unit_from=args.unit_from,
        unit_to=args.unit_to,
        var_type=args.var_type,
        firstyear=args.firstyear,
        lastyear=args.lastyear,
        scalar=args.scalar,
        nstep=args.nstep,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
