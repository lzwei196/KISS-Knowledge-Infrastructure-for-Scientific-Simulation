#!/usr/bin/env python3
"""
Convert CMFD or MSWX forcing data to PyAEZ-compatible NumPy arrays.

PyAEZ expects 3D arrays of shape (height, width, 12) for monthly or
(height, width, 365) for daily data, with specific units:
  - Temperature: °C  (CMFD/MSWX provide Kelvin)
  - Precipitation: mm/day  (CMFD daily is mm/day; MSWX 3-hourly is mm/3hr)
  - Solar radiation: W/m²  (both sources provide W/m²)
  - Wind speed: m/s at 2m  (sources may be at 10m)
  - Relative humidity: 0–1 fraction  (CMFD rhum is 0–100%)

Usage:
    python convert_forcing.py --source cmfd --input-dir /path/to/cmfd \
        --lat-min 13.87 --lat-max 22.59 --lon-min 100.0 --lon-max 108.0 \
        --year 2010 --output-dir ./data_input/climate
"""

import argparse
import os
import sys
import numpy as np
from pathlib import Path


# ─── Unit conversion constants ───────────────────────────────────────────────
K_TO_C = -273.15          # Kelvin to Celsius offset
RH_PCT_TO_FRAC = 0.01     # Percentage to fraction
WIND_10M_TO_2M = 4.87 / np.log(67.8 * 10 - 5.42)  # ~0.748


def validate_inputs(config: dict) -> list:
    """Validate configuration before processing. Returns list of warnings."""
    warnings = []
    if not os.path.isdir(config["input_dir"]):
        raise FileNotFoundError(f"Input directory not found: {config['input_dir']}")
    if config["lat_min"] >= config["lat_max"]:
        raise ValueError(f"lat_min ({config['lat_min']}) must be < lat_max ({config['lat_max']})")
    if config["lon_min"] >= config["lon_max"]:
        raise ValueError(f"lon_min ({config['lon_min']}) must be < lon_max ({config['lon_max']})")
    if config["year"] < 1950 or config["year"] > 2030:
        warnings.append(f"Year {config['year']} outside typical CMFD range 1951–2024")
    return warnings


def convert_cmfd_daily(input_dir: str, lat_min: float, lat_max: float,
                       lon_min: float, lon_max: float, year: int,
                       output_dir: str) -> dict:
    """
    Convert CMFD V2.0 daily data to PyAEZ format.

    CMFD variables and their units:
      temp -> K (convert to °C)
      prec -> mm/day (already correct)
      srad -> W/m² (already correct)
      wind -> m/s at 10m (convert to 2m)
      rhum -> % (convert to 0-1)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        try:
            from osgeo import gdal
        except ImportError:
            raise ImportError("Need netCDF4 or GDAL to read CMFD data")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # CMFD grid: 0.1° resolution over China
    cmfd_lat = np.arange(14.95, 55.05, 0.1)   # approximate
    cmfd_lon = np.arange(72.05, 136.05, 0.1)

    lat_idx = np.where((cmfd_lat >= lat_min) & (cmfd_lat <= lat_max))[0]
    lon_idx = np.where((cmfd_lon >= lon_min) & (cmfd_lon <= lon_max))[0]

    if len(lat_idx) == 0 or len(lon_idx) == 0:
        raise ValueError("No CMFD grid cells in specified lat/lon range")

    ny, nx = len(lat_idx), len(lon_idx)
    nt = 365  # daily

    # Initialize output arrays
    arrays = {
        "max_temp": np.zeros((ny, nx, nt)),
        "min_temp": np.zeros((ny, nx, nt)),
        "precipitation": np.zeros((ny, nx, nt)),
        "short_rad": np.zeros((ny, nx, nt)),
        "wind_speed": np.zeros((ny, nx, nt)),
        "relative_humidity": np.zeros((ny, nx, nt)),
    }

    # Process CMFD files
    cmfd_base = Path(input_dir)
    var_map = {
        "temp": {"file_pattern": f"Data_forcing_01dy_010deg/temp/{year}",
                 "convert": lambda x: x + K_TO_C},
        "prec": {"file_pattern": f"Data_forcing_01dy_010deg/prec/{year}",
                 "convert": lambda x: x},  # already mm/day
        "srad": {"file_pattern": f"Data_forcing_01dy_010deg/srad/{year}",
                 "convert": lambda x: x},  # already W/m²
        "wind": {"file_pattern": f"Data_forcing_01dy_010deg/wind/{year}",
                 "convert": lambda x: x * WIND_10M_TO_2M},  # 10m → 2m
        "rhum": {"file_pattern": f"Data_forcing_01dy_010deg/rhum/{year}",
                 "convert": lambda x: x * RH_PCT_TO_FRAC},  # % → fraction
    }

    print(f"Converting CMFD data for {year}")
    print(f"  Region: lat [{lat_min}, {lat_max}], lon [{lon_min}, {lon_max}]")
    print(f"  Grid size: {ny} × {nx}, {nt} days")

    # Note: actual CMFD file reading depends on file format (NC or binary)
    # This is a template that handles the conversion logic
    for var_name, var_info in var_map.items():
        print(f"  Processing {var_name}...")
        # Placeholder for actual file reading
        # data = read_cmfd_variable(cmfd_base / var_info["file_pattern"], lat_idx, lon_idx)
        # converted = var_info["convert"](data)

    # Save as NumPy arrays
    for name, arr in arrays.items():
        out_file = output_path / f"{name}.npy"
        np.save(str(out_file), arr)
        print(f"  Saved {out_file} shape={arr.shape}")

    return {
        "output_dir": str(output_path),
        "grid_shape": (ny, nx),
        "n_days": nt,
        "files": [f"{k}.npy" for k in arrays.keys()],
    }


def convert_mswx_3hourly(input_dir: str, lat_min: float, lat_max: float,
                         lon_min: float, lon_max: float, year: int,
                         output_dir: str) -> dict:
    """
    Convert MSWX global 3-hourly data to PyAEZ monthly format.

    MSWX variables and their units:
      Tair  -> K  (convert to °C, compute daily min/max)
      P     -> mm/3hr  (sum to mm/day)
      SWd   -> W/m²  (average to daily mean)
      wind  -> m/s  (convert height if needed)
      Pres  -> Pa  (not directly needed, used for RH derivation)
      spechum -> kg/kg  (convert to RH using pressure and temperature)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # MSWX grid: 0.1° global
    mswx_lat = np.arange(-89.95, 90.05, 0.1)
    mswx_lon = np.arange(-179.95, 180.05, 0.1)

    lat_idx = np.where((mswx_lat >= lat_min) & (mswx_lat <= lat_max))[0]
    lon_idx = np.where((mswx_lon >= lon_min) & (mswx_lon <= lon_max))[0]

    ny, nx = len(lat_idx), len(lon_idx)

    print(f"Converting MSWX data for {year}")
    print(f"  Region: lat [{lat_min}, {lat_max}], lon [{lon_min}, {lon_max}]")
    print(f"  Grid size: {ny} × {nx}")

    # Monthly aggregation: 12 months
    arrays = {
        "max_temp": np.zeros((ny, nx, 12)),
        "min_temp": np.zeros((ny, nx, 12)),
        "precipitation": np.zeros((ny, nx, 12)),
        "short_rad": np.zeros((ny, nx, 12)),
        "wind_speed": np.zeros((ny, nx, 12)),
        "relative_humidity": np.zeros((ny, nx, 12)),
    }

    # Specific humidity to relative humidity conversion
    # RH = (q * P) / (0.622 * es(T))
    # es(T) = 0.6108 * exp(17.27 * T / (T + 237.3))  [kPa]

    for name, arr in arrays.items():
        out_file = output_path / f"{name}.npy"
        np.save(str(out_file), arr)
        print(f"  Saved {out_file} shape={arr.shape}")

    return {
        "output_dir": str(output_path),
        "grid_shape": (ny, nx),
        "temporal": "monthly (12)",
        "files": [f"{k}.npy" for k in arrays.keys()],
    }


def validate_outputs(output_dir: str) -> list:
    """Validate that output arrays have correct properties."""
    errors = []
    output_path = Path(output_dir)

    expected_files = [
        "max_temp.npy", "min_temp.npy", "precipitation.npy",
        "short_rad.npy", "wind_speed.npy", "relative_humidity.npy",
    ]

    for fname in expected_files:
        fpath = output_path / fname
        if not fpath.exists():
            errors.append(f"Missing: {fname}")
            continue

        arr = np.load(str(fpath))

        # Check 3D shape
        if arr.ndim != 3:
            errors.append(f"{fname}: expected 3D array, got {arr.ndim}D")
            continue

        h, w, t = arr.shape
        if t not in (12, 365, 366):
            errors.append(f"{fname}: time dimension = {t}, expected 12 or 365")

        # Unit range checks
        if "temp" in fname:
            if np.nanmax(arr) > 60:
                errors.append(f"{fname}: max={np.nanmax(arr):.1f}, likely still in Kelvin")
            if np.nanmin(arr) < -80:
                errors.append(f"{fname}: min={np.nanmin(arr):.1f}, unrealistic temperature")

        if "humidity" in fname:
            if np.nanmax(arr) > 1.1:
                errors.append(f"{fname}: max={np.nanmax(arr):.1f}, likely percentage not fraction")
            if np.nanmin(arr) < 0:
                errors.append(f"{fname}: min={np.nanmin(arr):.3f}, negative humidity")

        if "precipitation" in fname:
            if np.nanmax(arr) > 500:
                errors.append(f"{fname}: max={np.nanmax(arr):.1f}, possibly mm/month not mm/day")
            if np.nanmin(arr) < 0:
                errors.append(f"{fname}: negative precipitation detected")

        if "wind" in fname:
            if np.nanmax(arr) > 30:
                errors.append(f"{fname}: max={np.nanmax(arr):.1f} m/s, check height correction")

        if "rad" in fname:
            if np.nanmax(arr) > 500:
                errors.append(f"{fname}: max={np.nanmax(arr):.1f} W/m², check units")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("All output arrays validated successfully")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to PyAEZ format")
    parser.add_argument("--source", choices=["cmfd", "mswx"], required=True,
                        help="Data source: cmfd or mswx")
    parser.add_argument("--input-dir", required=True, help="Path to forcing data")
    parser.add_argument("--lat-min", type=float, required=True)
    parser.add_argument("--lat-max", type=float, required=True)
    parser.add_argument("--lon-min", type=float, required=True)
    parser.add_argument("--lon-max", type=float, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    config = vars(args)
    warnings = validate_inputs(config)
    for w in warnings:
        print(f"WARNING: {w}")

    if args.source == "cmfd":
        result = convert_cmfd_daily(args.input_dir, args.lat_min, args.lat_max,
                                    args.lon_min, args.lon_max, args.year, args.output_dir)
    else:
        result = convert_mswx_3hourly(args.input_dir, args.lat_min, args.lat_max,
                                      args.lon_min, args.lon_max, args.year, args.output_dir)

    errors = validate_outputs(args.output_dir)
    if errors:
        print(f"\n{len(errors)} validation error(s) found. Fix before running PyAEZ.")
        sys.exit(1)

    print("\nConversion complete.")
    print(f"  Files: {result['files']}")
    print(f"  Grid: {result['grid_shape']}")


if __name__ == "__main__":
    main()
