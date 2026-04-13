#!/usr/bin/env python3
"""
convert_forcing_to_clm.py — Convert NetCDF/CSV climate forcing data to LPJmL CLM binary format.

CRITICAL UNIT CONVERSIONS:
  - Temperature: Must be in deg C (not Kelvin). Subtract 273.15 if from CMIP/ERA.
  - Precipitation: Must be mm/day (daily) or mm/month (monthly).
    CMIP gives kg/m2/s → multiply by 86400 for mm/day.
  - Shortwave radiation: Must be W/m2 (positive downward).
  - LW net radiation: LWnet = LWdown - LWup (W/m2).
  - Wind speed: Must be m/s.
  - Specific humidity: Must be kg/kg (not g/kg).

CLM binary format:
  Header: name(30 bytes), version(int), order(int), firstyear(int),
          nyear(int), firstcell(int), ncell(int), nbands(int),
          cellsize_lon(float), cellsize_lat(float), datatype(int), scalar(float)
  Data: ncell * nbands values per year, type depends on datatype field.

Usage:
    python convert_forcing_to_clm.py \\
        --input /path/to/forcing.nc \\
        --variable tas \\
        --output /path/to/temp.clm \\
        --start_year 1901 --end_year 2019 \\
        --grid_file /path/to/grid.bin \\
        --timestep daily \\
        --unit_conversion K_to_C

    python convert_forcing_to_clm.py \\
        --input /path/to/pr.nc \\
        --variable pr \\
        --output /path/to/prec.clm \\
        --start_year 1901 --end_year 2019 \\
        --grid_file /path/to/grid.bin \\
        --timestep daily \\
        --unit_conversion kgm2s_to_mmday
"""

import argparse
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

# CLM header constants
CLM_HEADER_SIZE_V2 = 43  # bytes
CLM_HEADER_NAME_LEN = 30
CLM_VERSION = 3
CLM_ORDER_LITTLE = 1
CLM_ORDER_BIG = 2

# Data type mapping
CLM_BYTE = 0
CLM_SHORT = 1
CLM_INT = 2
CLM_FLOAT = 3
CLM_DOUBLE = 4

DTYPE_MAP = {
    CLM_BYTE: np.uint8,
    CLM_SHORT: np.int16,
    CLM_INT: np.int32,
    CLM_FLOAT: np.float32,
    CLM_DOUBLE: np.float64,
}

# Unit conversion functions
UNIT_CONVERSIONS = {
    "K_to_C": lambda x: x - 273.15,
    "kgm2s_to_mmday": lambda x: x * 86400.0,
    "kgm2s_to_mmmonth": lambda x: x * 86400.0 * 30.4375,
    "gkg_to_kgkg": lambda x: x / 1000.0,
    "none": lambda x: x,
    "Pa_to_ppm": lambda x: x * 10.0,  # ppm = Pa / 0.1
}


def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.grid_file and not os.path.isfile(args.grid_file):
        errors.append(f"Grid file not found: {args.grid_file}")

    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")

    if args.unit_conversion not in UNIT_CONVERSIONS:
        errors.append(f"Unknown unit conversion: {args.unit_conversion}. "
                      f"Available: {list(UNIT_CONVERSIONS.keys())}")

    if args.timestep not in ("daily", "monthly"):
        errors.append(f"timestep must be 'daily' or 'monthly', got '{args.timestep}'")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def read_grid_file(grid_path):
    """Read LPJmL grid file (CLM format with short*100 coordinates)."""
    with open(grid_path, "rb") as f:
        # Read v2 header
        name = f.read(CLM_HEADER_NAME_LEN).decode("ascii", errors="ignore").rstrip("\x00")
        header = struct.unpack("<iiiiiii", f.read(28))
        version, order, firstyear, nyear, firstcell, ncell, nbands = header

        if version >= 3:
            extra = struct.unpack("<ffif", f.read(16))
            cellsize_lon, cellsize_lat, datatype, scalar = extra
        else:
            cellsize_lon = cellsize_lat = 0.5
            datatype = CLM_SHORT
            scalar = 0.01

        # Read grid data
        dtype = DTYPE_MAP.get(datatype, np.int16)
        data = np.fromfile(f, dtype=dtype, count=ncell * 2)
        coords = data.reshape(ncell, 2).astype(np.float64) * scalar

    return coords, ncell


def write_clm_header(f, name, firstyear, nyear, ncell, nbands,
                     cellsize_lon=0.5, cellsize_lat=0.5,
                     datatype=CLM_FLOAT, scalar=1.0):
    """Write CLM v3 header to binary file."""
    # Name field (30 bytes, null-padded)
    name_bytes = name.encode("ascii")[:CLM_HEADER_NAME_LEN]
    name_bytes = name_bytes.ljust(CLM_HEADER_NAME_LEN, b"\x00")
    f.write(name_bytes)

    # Header fields
    f.write(struct.pack("<i", CLM_VERSION))       # version
    f.write(struct.pack("<i", CLM_ORDER_LITTLE))  # byte order
    f.write(struct.pack("<i", firstyear))         # firstyear
    f.write(struct.pack("<i", nyear))             # nyear
    f.write(struct.pack("<i", 0))                 # firstcell
    f.write(struct.pack("<i", ncell))             # ncell
    f.write(struct.pack("<i", nbands))            # nbands
    # v3 extra fields
    f.write(struct.pack("<f", cellsize_lon))      # cellsize_lon
    f.write(struct.pack("<f", cellsize_lat))      # cellsize_lat
    f.write(struct.pack("<i", datatype))          # datatype
    f.write(struct.pack("<f", scalar))            # scalar


def convert_netcdf_to_clm(input_path, variable, output_path, grid_file,
                          start_year, end_year, timestep, unit_conversion):
    """Convert NetCDF climate file to CLM binary format."""
    try:
        import netCDF4 as nc
    except ImportError:
        try:
            import xarray as xr
            return convert_netcdf_xarray(input_path, variable, output_path,
                                         grid_file, start_year, end_year,
                                         timestep, unit_conversion)
        except ImportError:
            print(json.dumps({"status": "error",
                              "errors": ["Neither netCDF4 nor xarray installed"]}))
            sys.exit(1)

    # Read grid
    coords, ncell = read_grid_file(grid_file)
    lons = coords[:, 0]
    lats = coords[:, 1]

    # Open NetCDF
    ds = nc.Dataset(input_path, "r")
    nc_var = ds.variables[variable]
    nc_lons = ds.variables.get("lon", ds.variables.get("longitude"))
    nc_lats = ds.variables.get("lat", ds.variables.get("latitude"))

    nc_lon_vals = nc_lons[:].astype(np.float64)
    nc_lat_vals = nc_lats[:].astype(np.float64)

    # Find nearest grid indices for each LPJmL cell
    cell_indices = []
    for i in range(ncell):
        lon_idx = np.argmin(np.abs(nc_lon_vals - lons[i]))
        lat_idx = np.argmin(np.abs(nc_lat_vals - lats[i]))
        cell_indices.append((lat_idx, lon_idx))

    # Determine nbands
    nbands = 365 if timestep == "daily" else 12
    nyear = end_year - start_year + 1
    convert_fn = UNIT_CONVERSIONS[unit_conversion]

    # Write CLM file
    with open(output_path, "wb") as f:
        write_clm_header(f, f"LPJCLM_{variable}", start_year, nyear,
                         ncell, nbands, datatype=CLM_FLOAT)

        time_idx = 0
        for year_offset in range(nyear):
            year_data = np.zeros((ncell, nbands), dtype=np.float32)
            for band in range(nbands):
                if time_idx < nc_var.shape[0]:
                    for ci, (lat_idx, lon_idx) in enumerate(cell_indices):
                        val = float(nc_var[time_idx, lat_idx, lon_idx])
                        year_data[ci, band] = convert_fn(val)
                    time_idx += 1

            # Write cell-major order
            year_data.tofile(f)

    ds.close()

    # Validate output
    validate_clm_output(output_path, variable, unit_conversion, ncell, nyear, nbands)

    return {"status": "success", "output": output_path,
            "ncell": ncell, "nyear": nyear, "nbands": nbands}


def convert_netcdf_xarray(input_path, variable, output_path, grid_file,
                          start_year, end_year, timestep, unit_conversion):
    """Fallback: use xarray for NetCDF conversion."""
    import xarray as xr

    coords, ncell = read_grid_file(grid_file)
    ds = xr.open_dataset(input_path)

    nbands = 365 if timestep == "daily" else 12
    nyear = end_year - start_year + 1
    convert_fn = UNIT_CONVERSIONS[unit_conversion]

    with open(output_path, "wb") as f:
        write_clm_header(f, f"LPJCLM_{variable}", start_year, nyear,
                         ncell, nbands, datatype=CLM_FLOAT)

        for year in range(start_year, end_year + 1):
            year_slice = ds[variable].sel(time=str(year))
            year_data = np.zeros((ncell, nbands), dtype=np.float32)

            for ci in range(ncell):
                vals = year_slice.sel(
                    lon=coords[ci, 0], lat=coords[ci, 1],
                    method="nearest"
                ).values
                n = min(len(vals), nbands)
                year_data[ci, :n] = convert_fn(vals[:n]).astype(np.float32)

            year_data.tofile(f)

    ds.close()
    validate_clm_output(output_path, variable, unit_conversion, ncell, nyear, nbands)

    return {"status": "success", "output": output_path,
            "ncell": ncell, "nyear": nyear, "nbands": nbands}


def validate_clm_output(output_path, variable, unit_conversion, ncell, nyear, nbands):
    """Validate the generated CLM file for physical reasonableness."""
    with open(output_path, "rb") as f:
        # Skip header
        f.read(CLM_HEADER_NAME_LEN + 28 + 16)  # v3 header
        data = np.fromfile(f, dtype=np.float32)

    expected_size = ncell * nbands * nyear
    if data.size != expected_size:
        print(json.dumps({"status": "warning",
                          "message": f"Data size {data.size} != expected {expected_size}"}))

    # Physical range checks
    checks = {
        "tas": {"min": -80.0, "max": 60.0, "desc": "Temperature (deg C)"},
        "pr": {"min": 0.0, "max": 500.0, "desc": "Precipitation (mm/day)"},
        "rsds": {"min": 0.0, "max": 500.0, "desc": "Shortwave radiation (W/m2)"},
        "sfcwind": {"min": 0.0, "max": 50.0, "desc": "Wind speed (m/s)"},
        "huss": {"min": 0.0, "max": 0.04, "desc": "Specific humidity (kg/kg)"},
    }

    var_key = variable.lower()
    if var_key in checks:
        c = checks[var_key]
        valid_data = data[~np.isnan(data)]
        if len(valid_data) > 0:
            dmin, dmax = valid_data.min(), valid_data.max()
            if dmin < c["min"] - 10 or dmax > c["max"] + 10:
                print(json.dumps({
                    "status": "warning",
                    "message": f"{c['desc']}: range [{dmin:.2f}, {dmax:.2f}] "
                               f"outside expected [{c['min']}, {c['max']}]. "
                               f"Check unit conversion '{unit_conversion}'."
                }))
            else:
                print(json.dumps({
                    "status": "ok",
                    "message": f"{c['desc']}: range [{dmin:.2f}, {dmax:.2f}] OK"
                }))


def main():
    parser = argparse.ArgumentParser(
        description="Convert NetCDF climate forcing to LPJmL CLM binary format")
    parser.add_argument("--input", required=True, help="Input NetCDF file path")
    parser.add_argument("--variable", required=True, help="NetCDF variable name")
    parser.add_argument("--output", required=True, help="Output CLM file path")
    parser.add_argument("--grid_file", required=True, help="LPJmL grid file (grid.bin)")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--timestep", default="daily",
                        choices=["daily", "monthly"])
    parser.add_argument("--unit_conversion", default="none",
                        choices=list(UNIT_CONVERSIONS.keys()))

    args = parser.parse_args()

    # Step 1: Validate
    validate_inputs(args)

    # Step 2: Process
    result = convert_netcdf_to_clm(
        args.input, args.variable, args.output, args.grid_file,
        args.start_year, args.end_year, args.timestep, args.unit_conversion
    )

    # Step 3: Report
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
