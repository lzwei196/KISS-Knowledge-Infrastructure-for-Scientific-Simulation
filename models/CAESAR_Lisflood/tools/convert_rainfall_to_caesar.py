#!/usr/bin/env python3
"""
Convert precipitation forcing data to HAIL-CAESAR rainfall input format.

Supports:
  - CSV with datetime + precipitation column
  - NetCDF (ERA5, CMFD) with tp/precip variable
  - Raw text with one value per line

Output: headerless space-delimited text file with rainfall rates in mm/hr.

Unit conversions handled:
  - m/s  -> mm/hr  (multiply by 3.6e6)
  - mm/day -> mm/hr (divide by 24)
  - kg/m2/s -> mm/hr (multiply by 3600, assuming water density = 1000 kg/m3)
  - m/timestep -> mm/hr (multiply by 1000 / (timestep_hours))

Usage:
    python convert_rainfall_to_caesar.py \\
        --input precip.csv \\
        --output rainfall.txt \\
        --source_units mm/day \\
        --timestep_min 60 \\
        --num_zones 1
"""

import argparse
import sys
import os
import numpy as np
from pathlib import Path


def validate_input(input_path: str) -> None:
    """Validate that input file exists and is readable."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if os.path.getsize(input_path) == 0:
        raise ValueError(f"Input file is empty: {input_path}")


def convert_units(values: np.ndarray, source_units: str) -> np.ndarray:
    """Convert precipitation values from source units to mm/hr.

    HAIL-CAESAR expects rainfall as instantaneous rate in mm/hr,
    regardless of the rain_data_time_step setting in the parameter file.
    """
    conversions = {
        "mm/hr": 1.0,
        "mm/h": 1.0,
        "mm/day": 1.0 / 24.0,
        "mm/d": 1.0 / 24.0,
        "m/s": 3.6e6,
        "kg/m2/s": 3600.0,
        "kg/(m2*s)": 3600.0,
        "m/hr": 1000.0,
        "m/h": 1000.0,
        "cm/hr": 10.0,
        "cm/h": 10.0,
        "in/hr": 25.4,
    }

    unit_key = source_units.lower().strip()
    if unit_key not in conversions:
        raise ValueError(
            f"Unknown source units: '{source_units}'. "
            f"Supported: {list(conversions.keys())}"
        )

    factor = conversions[unit_key]
    converted = values * factor

    # Sanity check
    if np.any(converted < 0):
        n_neg = np.sum(converted < 0)
        print(f"WARNING: {n_neg} negative rainfall values found. Setting to 0.")
        converted = np.clip(converted, 0, None)

    if np.any(converted > 500):
        n_extreme = np.sum(converted > 500)
        print(
            f"WARNING: {n_extreme} values exceed 500 mm/hr "
            f"(max={converted.max():.1f}). Check units!"
        )

    return converted


def read_csv(input_path: str, precip_col: str = None, num_zones: int = 1) -> np.ndarray:
    """Read precipitation from CSV file.

    Returns array of shape (n_timesteps, num_zones).
    """
    import csv

    with open(input_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader)

    # Try to find precipitation column
    if precip_col:
        col_names = [precip_col]
    else:
        precip_keywords = ["precip", "rainfall", "rain", "tp", "pr", "prcp", "ppt"]
        col_names = [
            h for h in header
            if any(kw in h.lower() for kw in precip_keywords)
        ]

    if not col_names:
        # If only 2 columns, assume second is precip
        if len(header) == 2:
            col_names = [header[1]]
        else:
            raise ValueError(
                f"Cannot identify precipitation column in: {header}. "
                f"Use --precip_col to specify."
            )

    try:
        import pandas as pd
        df = pd.read_csv(input_path)
        if num_zones == 1:
            values = df[col_names[0]].values.astype(float)
            return values.reshape(-1, 1)
        else:
            # Multiple rainfall zones
            return df[col_names[:num_zones]].values.astype(float)
    except ImportError:
        # Fallback without pandas
        data = np.genfromtxt(input_path, delimiter=",", skip_header=1)
        if data.ndim == 1:
            return data.reshape(-1, 1)
        # Assume last column(s) are precip
        return data[:, -num_zones:]


def read_netcdf(input_path: str, lat: float = None, lon: float = None) -> np.ndarray:
    """Read precipitation from NetCDF file (ERA5, CMFD, etc.)."""
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for NetCDF input: pip install xarray netCDF4")

    ds = xr.open_dataset(input_path)

    # Find precipitation variable
    precip_vars = ["tp", "precip", "precipitation", "pr", "rain", "prcp", "PREC"]
    var_name = None
    for v in precip_vars:
        if v in ds.data_vars:
            var_name = v
            break

    if var_name is None:
        raise ValueError(
            f"No precipitation variable found in {input_path}. "
            f"Variables: {list(ds.data_vars)}"
        )

    da = ds[var_name]

    # Extract point if lat/lon given
    if lat is not None and lon is not None:
        da = da.sel(lat=lat, lon=lon, method="nearest")
    else:
        # Spatial mean
        spatial_dims = [d for d in da.dims if d not in ["time", "Time"]]
        if spatial_dims:
            da = da.mean(dim=spatial_dims)

    values = da.values.flatten().astype(float)
    ds.close()
    return values.reshape(-1, 1)


def read_text(input_path: str, num_zones: int = 1) -> np.ndarray:
    """Read plain text rainfall file (existing CAESAR format or simple list)."""
    data = np.loadtxt(input_path)
    if data.ndim == 1:
        return data.reshape(-1, 1)
    if num_zones > 1:
        return data[:, :num_zones]
    return data[:, :1] if data.ndim == 2 else data.reshape(-1, 1)


def resample_to_timestep(
    values: np.ndarray,
    source_timestep_min: float,
    target_timestep_min: float
) -> np.ndarray:
    """Resample rainfall data to target timestep.

    For downsampling (source > target): repeat values.
    For upsampling (source < target): aggregate (mean of rates).
    """
    if abs(source_timestep_min - target_timestep_min) < 0.01:
        return values

    n_steps, n_zones = values.shape
    ratio = source_timestep_min / target_timestep_min

    if ratio > 1:
        # Downsample: repeat each source step
        repeats = int(round(ratio))
        result = np.repeat(values, repeats, axis=0)
    else:
        # Upsample: aggregate
        block = int(round(1.0 / ratio))
        n_new = n_steps // block
        result = np.zeros((n_new, n_zones))
        for i in range(n_new):
            result[i] = values[i * block:(i + 1) * block].mean(axis=0)

    return result


def write_caesar_rainfall(output_path: str, data: np.ndarray) -> None:
    """Write rainfall in HAIL-CAESAR format: headerless, space-delimited, mm/hr."""
    n_steps, n_zones = data.shape

    with open(output_path, "w") as f:
        for i in range(n_steps):
            line = " ".join(f"{data[i, z]:.4f}" for z in range(n_zones))
            f.write(line + "\n")

    print(f"Written {n_steps} timesteps x {n_zones} zones to {output_path}")


def validate_output(output_path: str, expected_steps: int = None) -> None:
    """Validate the output file was written correctly."""
    if not os.path.isfile(output_path):
        raise RuntimeError(f"Output file was not created: {output_path}")

    data = np.loadtxt(output_path)
    if data.size == 0:
        raise RuntimeError("Output file is empty")

    if data.ndim == 1:
        data = data.reshape(-1, 1)

    n_steps = data.shape[0]
    print(f"Validation: {n_steps} timesteps, "
          f"min={data.min():.4f}, max={data.max():.4f}, mean={data.mean():.4f} mm/hr")

    if np.any(data < 0):
        raise RuntimeError("Output contains negative values!")

    if np.all(data == 0):
        print("WARNING: All rainfall values are zero. Check input data and units.")

    if expected_steps and n_steps != expected_steps:
        print(f"WARNING: Expected {expected_steps} steps but got {n_steps}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert precipitation data to HAIL-CAESAR rainfall format"
    )
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output", required=True, help="Output rainfall text file")
    parser.add_argument(
        "--source_units", default="mm/hr",
        help="Units of source data (mm/hr, mm/day, m/s, kg/m2/s)"
    )
    parser.add_argument(
        "--source_format", default="auto",
        help="Input format: auto, csv, netcdf, text"
    )
    parser.add_argument("--timestep_min", type=float, default=60,
                        help="Target timestep in minutes (must match rain_data_time_step)")
    parser.add_argument("--source_timestep_min", type=float, default=None,
                        help="Source data timestep in minutes (auto-detected if possible)")
    parser.add_argument("--num_zones", type=int, default=1,
                        help="Number of hydroindex rainfall zones")
    parser.add_argument("--precip_col", default=None,
                        help="Column name for precipitation (CSV only)")
    parser.add_argument("--lat", type=float, default=None, help="Latitude (NetCDF point extraction)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude (NetCDF point extraction)")

    args = parser.parse_args()

    # Step 1: Validate input
    validate_input(args.input)

    # Step 2: Read data
    fmt = args.source_format.lower()
    if fmt == "auto":
        ext = Path(args.input).suffix.lower()
        if ext in (".nc", ".nc4", ".netcdf"):
            fmt = "netcdf"
        elif ext in (".csv",):
            fmt = "csv"
        else:
            fmt = "text"

    print(f"Reading {fmt} format from {args.input}")

    if fmt == "netcdf":
        raw_data = read_netcdf(args.input, args.lat, args.lon)
    elif fmt == "csv":
        raw_data = read_csv(args.input, args.precip_col, args.num_zones)
    else:
        raw_data = read_text(args.input, args.num_zones)

    print(f"Read {raw_data.shape[0]} timesteps, {raw_data.shape[1]} zone(s)")

    # Step 3: Convert units
    converted = convert_units(raw_data, args.source_units)

    # Step 4: Resample if needed
    if args.source_timestep_min and args.source_timestep_min != args.timestep_min:
        converted = resample_to_timestep(
            converted, args.source_timestep_min, args.timestep_min
        )
        print(f"Resampled to {converted.shape[0]} timesteps at {args.timestep_min} min")

    # Step 5: Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    write_caesar_rainfall(args.output, converted)

    # Step 6: Validate output
    validate_output(args.output)

    print("Done.")


if __name__ == "__main__":
    main()
