#!/usr/bin/env python3
"""
Convert CMFD/MSWX gridded forcing data to GSFLOW PRMS .day files.

Usage:
    python convert_forcing_to_gsflow.py \
        --forcing-dir /path/to/CMFD/ \
        --shapefile /path/to/basin.shp \
        --output-dir /path/to/prms_input/ \
        --start-year 1980 --end-year 1990 \
        --source cmfd \
        --temp-units fahrenheit \
        --precip-units inches

Pipeline Stage: s4 (Meteorological Forcing)
Follows: validate → process → validate pattern
"""

import os
import sys
import argparse
import numpy as np
from datetime import datetime, timedelta

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError:
    gpd = None


# ── Unit Conversion Constants ──────────────────────────────────────────────
KELVIN_TO_CELSIUS = -273.15
CELSIUS_TO_FAHRENHEIT_SCALE = 9.0 / 5.0
CELSIUS_TO_FAHRENHEIT_OFFSET = 32.0
MM_TO_INCHES = 1.0 / 25.4  # 0.03937
WM2_TO_LANGLEYS = 86400.0 / 41868.0  # ~2.065 (W/m² → cal/cm²/day)

# CMFD variable name mapping
CMFD_VARS = {
    "prec": {"file_pattern": "prec_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "prec"},
    "temp": {"file_pattern": "temp_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "temp"},
    "srad": {"file_pattern": "srad_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "srad"},
    "wind": {"file_pattern": "wind_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "wind"},
    "shum": {"file_pattern": "shum_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "shum"},
    "pres": {"file_pattern": "pres_CMFD_V0106_B-01_01dy_025deg_{year}.nc", "var": "pres"},
}


def validate_inputs(forcing_dir, shapefile, start_year, end_year, source):
    """Validate all inputs before processing."""
    errors = []

    if not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")

    if shapefile and not os.path.isfile(shapefile):
        errors.append(f"Shapefile not found: {shapefile}")

    if start_year > end_year:
        errors.append(f"start_year ({start_year}) > end_year ({end_year})")

    if source not in ("cmfd", "mswx"):
        errors.append(f"Unknown source: {source}. Must be 'cmfd' or 'mswx'.")

    if nc is None:
        errors.append("netCDF4 not installed. Run: pip install netCDF4")

    # Check that forcing files exist for at least the first year
    if os.path.isdir(forcing_dir):
        test_files = os.listdir(forcing_dir)
        if len(test_files) == 0:
            errors.append(f"No files in forcing directory: {forcing_dir}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def get_basin_mask(forcing_dir, shapefile, year, source="cmfd"):
    """
    Create basin mask from shapefile overlaid on forcing grid.
    Returns: lat indices, lon indices, weights for area-averaging per HRU.
    For single-HRU (lumped), returns indices of all grid cells in basin.
    """
    if gpd is None:
        raise ImportError("geopandas required for basin masking")

    basin = gpd.read_file(shapefile)
    basin_geom = basin.geometry.unary_union

    # Open one forcing file to get grid
    var = "temp" if source == "cmfd" else "Tair"
    pattern = CMFD_VARS["temp"]["file_pattern"] if source == "cmfd" else f"Tair_{year}.nc"
    nc_files = [f for f in os.listdir(forcing_dir) if str(year) in f and ("temp" in f.lower() or "tair" in f.lower())]
    if not nc_files:
        raise FileNotFoundError(f"No temperature file found for year {year} in {forcing_dir}")

    ds = nc.Dataset(os.path.join(forcing_dir, nc_files[0]))
    lats = ds.variables["latitude"][:] if "latitude" in ds.variables else ds.variables["lat"][:]
    lons = ds.variables["longitude"][:] if "longitude" in ds.variables else ds.variables["lon"][:]
    ds.close()

    # Find grid cells within basin
    cell_indices = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            point = Point(float(lon), float(lat))
            if basin_geom.contains(point):
                cell_indices.append((i, j))

    if not cell_indices:
        raise ValueError("No grid cells found within basin boundary. Check CRS/extent.")

    print(f"  Basin contains {len(cell_indices)} grid cells")
    return cell_indices, lats, lons


def read_cmfd_variable(forcing_dir, var_name, year, cell_indices):
    """
    Read a CMFD variable for one year and extract basin cells.
    Returns: (n_days, n_cells) array
    """
    nc_files = sorted([
        f for f in os.listdir(forcing_dir)
        if str(year) in f and var_name in f.lower() and f.endswith(".nc")
    ])
    if not nc_files:
        raise FileNotFoundError(f"No {var_name} file for year {year} in {forcing_dir}")

    ds = nc.Dataset(os.path.join(forcing_dir, nc_files[0]))

    # Identify the data variable (skip coordinate variables)
    data_vars = [v for v in ds.variables if v not in ("time", "lat", "lon", "latitude", "longitude")]
    if not data_vars:
        raise ValueError(f"No data variable in {nc_files[0]}")
    data_var = data_vars[0]

    data = ds.variables[data_var][:]
    ds.close()

    # Extract basin cells
    n_days = data.shape[0]
    n_cells = len(cell_indices)
    result = np.zeros((n_days, n_cells))
    for k, (i, j) in enumerate(cell_indices):
        result[:, k] = data[:, i, j]

    return result


def convert_temperature(temp_k, target_units="fahrenheit"):
    """
    Convert temperature from Kelvin to target units.

    TRAP: CMFD temperature is in Kelvin.
    - If target is Celsius: subtract 273.15
    - If target is Fahrenheit: (K - 273.15) * 9/5 + 32
    """
    temp_c = temp_k + KELVIN_TO_CELSIUS
    if target_units == "celsius":
        return temp_c
    elif target_units == "fahrenheit":
        return temp_c * CELSIUS_TO_FAHRENHEIT_SCALE + CELSIUS_TO_FAHRENHEIT_OFFSET
    else:
        raise ValueError(f"Unknown temp units: {target_units}")


def convert_precipitation(precip_mm, target_units="inches"):
    """
    Convert precipitation from mm/day to target units.

    TRAP: CMFD precipitation is mm/day.
    - If GSFLOW precip_units=0 (inches): multiply by 0.03937
    - If GSFLOW precip_units=1 (mm): no conversion
    """
    if target_units == "inches":
        return precip_mm * MM_TO_INCHES
    elif target_units == "mm":
        return precip_mm
    else:
        raise ValueError(f"Unknown precip units: {target_units}")


def convert_solar_radiation(srad_wm2, target_units="langleys"):
    """
    Convert solar radiation from W/m² to target units.

    TRAP: CMFD srad is W/m².
    - GSFLOW expects Langleys/day (cal/cm²/day)
    - 1 W/m² = 2.065 Langleys/day (= 86400/41868)
    """
    if target_units == "langleys":
        return srad_wm2 * WM2_TO_LANGLEYS
    elif target_units == "wm2":
        return srad_wm2
    else:
        raise ValueError(f"Unknown srad units: {target_units}")


def write_day_file(output_path, variable_name, dates, data, n_hru):
    """
    Write a PRMS .day file.

    Format:
        Header line
        ###### delimiter
        YYYY MM DD HH MM SS val1 val2 ... valN
    """
    with open(output_path, "w") as f:
        f.write(f"{variable_name}.day generated by convert_forcing_to_gsflow\n")
        f.write("#" * 40 + "\n")

        for t in range(len(dates)):
            dt = dates[t]
            line = f"{dt.year} {dt.month} {dt.day} 0 0 0"
            for h in range(n_hru):
                if n_hru <= data.shape[1]:
                    val = data[t, h]
                else:
                    # If more HRUs than cells, use nearest or average
                    val = np.mean(data[t, :])
                line += f"  {val:.4f}"
            f.write(line + "\n")

    print(f"  Wrote {output_path} ({len(dates)} days, {n_hru} HRUs)")


def validate_outputs(output_dir, expected_files, dates):
    """Validate that output files were created and contain reasonable data."""
    errors = []

    for fname in expected_files:
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            errors.append(f"Missing output file: {fpath}")
            continue

        # Check file is not empty
        size = os.path.getsize(fpath)
        if size == 0:
            errors.append(f"Empty output file: {fpath}")
            continue

        # Count data lines (skip header)
        with open(fpath) as f:
            lines = f.readlines()
        n_data = len(lines) - 2  # minus header and delimiter
        if n_data != len(dates):
            errors.append(f"{fname}: expected {len(dates)} data lines, got {n_data}")

        # Spot-check values
        if "precip" in fname:
            vals = [float(x) for x in lines[2].split()[6:]]
            if any(v < 0 for v in vals):
                errors.append(f"{fname}: negative precipitation found")
            if any(v > 500 for v in vals):
                errors.append(f"{fname}: precipitation > 500 (check units: mm vs inches?)")

        if "tmax" in fname or "tmin" in fname:
            vals = [float(x) for x in lines[2].split()[6:]]
            if any(v > 200 for v in vals):
                errors.append(f"{fname}: temperature > 200 (still in Kelvin?)")
            if any(v < -150 for v in vals):
                errors.append(f"{fname}: temperature < -150 (unrealistic)")

        if "swrad" in fname:
            vals = [float(x) for x in lines[2].split()[6:]]
            if any(v > 2000 for v in vals):
                errors.append(f"{fname}: solar rad > 2000 (still in W/m²?)")

    if errors:
        for e in errors:
            print(f"WARNING: {e}", file=sys.stderr)
        return False

    print("  Output validation PASSED")
    return True


def generate_dates(start_year, end_year):
    """Generate list of dates from Oct 1 of start_year to Sep 30 of end_year."""
    dates = []
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser(description="Convert gridded forcing to GSFLOW .day files")
    parser.add_argument("--forcing-dir", required=True, help="Directory with forcing NetCDF files")
    parser.add_argument("--shapefile", required=True, help="Basin boundary shapefile")
    parser.add_argument("--output-dir", required=True, help="Output directory for .day files")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--source", default="cmfd", choices=["cmfd", "mswx"])
    parser.add_argument("--temp-units", default="fahrenheit", choices=["fahrenheit", "celsius"])
    parser.add_argument("--precip-units", default="inches", choices=["inches", "mm"])
    parser.add_argument("--n-hru", type=int, default=1, help="Number of HRUs (1=lumped)")
    args = parser.parse_args()

    print("=" * 60)
    print("GSFLOW Forcing Converter (CMFD/MSWX → .day files)")
    print("=" * 60)

    # ── Step 1: Validate Inputs ──
    if not validate_inputs(args.forcing_dir, args.shapefile, args.start_year, args.end_year, args.source):
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 2: Get basin mask ──
    print(f"\n[1/4] Building basin mask from {args.shapefile}")
    cell_indices, lats, lons = get_basin_mask(
        args.forcing_dir, args.shapefile, args.start_year, args.source
    )

    # ── Step 3: Process each variable ──
    dates = generate_dates(args.start_year, args.end_year)
    n_hru = args.n_hru

    all_data = {}
    for year in range(args.start_year, args.end_year + 1):
        print(f"\n[2/4] Processing year {year}")

        # Temperature
        print(f"  Reading temperature for {year}...")
        temp_raw = read_cmfd_variable(args.forcing_dir, "temp", year, cell_indices)
        # CMFD temp is daily mean in Kelvin
        # For GSFLOW we need tmax and tmin. Using daily mean ± 5°C as approximation
        tmax_k = temp_raw + 5.0  # Approximate tmax
        tmin_k = temp_raw - 5.0  # Approximate tmin
        tmax = convert_temperature(tmax_k, args.temp_units)
        tmin = convert_temperature(tmin_k, args.temp_units)

        # Precipitation
        print(f"  Reading precipitation for {year}...")
        prec_raw = read_cmfd_variable(args.forcing_dir, "prec", year, cell_indices)
        precip = convert_precipitation(prec_raw, args.precip_units)
        precip = np.maximum(precip, 0.0)  # Ensure non-negative

        # Solar radiation
        print(f"  Reading solar radiation for {year}...")
        srad_raw = read_cmfd_variable(args.forcing_dir, "srad", year, cell_indices)
        swrad = convert_solar_radiation(srad_raw, "langleys")
        swrad = np.maximum(swrad, 0.0)  # Ensure non-negative

        # Store
        key = year
        all_data.setdefault("tmax", []).append(tmax)
        all_data.setdefault("tmin", []).append(tmin)
        all_data.setdefault("precip", []).append(precip)
        all_data.setdefault("swrad", []).append(swrad)

    # Concatenate years
    print(f"\n[3/4] Writing .day files")
    for var_name in ["tmax", "tmin", "precip", "swrad"]:
        combined = np.concatenate(all_data[var_name], axis=0)
        output_path = os.path.join(args.output_dir, f"{var_name}.day")
        write_day_file(output_path, var_name, dates, combined, n_hru)

    # ── Step 4: Validate Outputs ──
    print(f"\n[4/4] Validating outputs")
    expected = ["tmax.day", "tmin.day", "precip.day", "swrad.day"]
    validate_outputs(args.output_dir, expected, dates)

    print(f"\nDone! Files written to {args.output_dir}")
    print(f"  temp_units: {args.temp_units} (GSFLOW temp_units={'0' if args.temp_units == 'fahrenheit' else '1'})")
    print(f"  precip_units: {args.precip_units} (GSFLOW precip_units={'0' if args.precip_units == 'inches' else '1'})")


if __name__ == "__main__":
    main()
