#!/usr/bin/env python3
"""convert_vic_runoff.py — Convert VIC flux output to mizuRoute runoff NetCDF input.

Takes VIC ASCII flux files (one per grid cell) and creates a single NetCDF file
with gridded runoff (RUNOFF + BASEFLOW) that mizuRoute can read with spatial remapping.

CRITICAL UNIT CONVERSION:
  VIC flux output reports RUNOFF and BASEFLOW in mm/timestep (depth per model timestep).
  mizuRoute expects runoff rate in mm/s.
  Conversion: runoff_mm_s = (RUNOFF + BASEFLOW) / timestep_seconds

  For daily VIC output:     divide by 86400
  For 3-hourly VIC output:  divide by 10800

  Getting this wrong produces discharge that is 8x or 24x too high/low with NO error message.
  This is the #1 silent error risk in VIC-mizuRoute coupling (dt_m003).

Usage:
    python convert_vic_runoff.py \\
        --vic_result_dir outputs/<run>/vic_result \\
        --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \\
        --output outputs/<run>/mizuroute_input/runoff.nc \\
        --start_year 2000 --end_year 2010 \\
        --vic_timestep daily
"""
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import netCDF4 as nc
import glob


def validate_inputs(args):
    """Validate all input files exist and parameters are sensible."""
    errors = []

    if not os.path.isdir(args.vic_result_dir):
        errors.append(f"VIC result directory not found: {args.vic_result_dir}")

    if not os.path.isfile(args.grid_nc):
        errors.append(f"Grid NetCDF not found: {args.grid_nc}")

    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")

    valid_timesteps = ['daily', '3hourly', 'hourly']
    if args.vic_timestep not in valid_timesteps:
        errors.append(f"vic_timestep must be one of {valid_timesteps}, got: {args.vic_timestep}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def get_timestep_seconds(vic_timestep):
    """Return the number of seconds per VIC output timestep."""
    mapping = {
        'daily': 86400,
        '3hourly': 10800,
        'hourly': 3600,
    }
    return mapping[vic_timestep]


def read_vic_grid(grid_nc_path):
    """Read VIC grid definition from basin_grid.nc."""
    with nc.Dataset(grid_nc_path, 'r') as ds:
        # Try lat/lon first, then y/x (HydroCraft convention)
        if 'lat' in ds.variables:
            lats = ds.variables['lat'][:]
            lons = ds.variables['lon'][:]
        elif 'y' in ds.variables:
            lats = ds.variables['y'][:]
            lons = ds.variables['x'][:]
        else:
            raise KeyError(f"Grid file has no lat/lon or y/x variables. Found: {list(ds.variables.keys())}")

        # Get unique sorted lat/lon values for the 2D grid
        if lats.ndim == 1 and lons.ndim == 1:
            lat_unique = np.sort(np.unique(lats))[::-1]  # descending for north-up
            lon_unique = np.sort(np.unique(lons))
        else:
            lat_unique = np.sort(np.unique(lats))[::-1]
            lon_unique = np.sort(np.unique(lons))

    return lat_unique, lon_unique


def find_vic_flux_files(vic_result_dir, lat_values, lon_values):
    """Find VIC flux output files and map them to grid positions.

    VIC flux files are named like: fluxes_<lat>_<lon> or similar patterns.
    """
    flux_files = {}

    # Try different naming patterns
    patterns = [
        'fluxes_*',
        '*_fluxes_*',
        'flux_*',
    ]

    all_files = []
    for pattern in patterns:
        matches = glob.glob(os.path.join(vic_result_dir, pattern))
        if matches:
            all_files = matches
            break

    if not all_files:
        # Try listing all files
        all_files = [os.path.join(vic_result_dir, f) for f in os.listdir(vic_result_dir)
                     if os.path.isfile(os.path.join(vic_result_dir, f))]

    for fpath in all_files:
        fname = os.path.basename(fpath)
        # Strip common extensions
        fname_noext = fname
        for ext in ['.txt', '.csv', '.dat', '.asc']:
            if fname_noext.endswith(ext):
                fname_noext = fname_noext[:-len(ext)]
                break
        # Extract lat/lon from filename
        # Common patterns: fluxes_40.1250_116.6250, huaihe_fluxes_32.8750_116.8750.txt
        parts = fname_noext.replace('fluxes_', '').replace('flux_', '').split('_')

        # Find two consecutive parts that look like lat/lon
        for i in range(len(parts) - 1):
            try:
                lat = float(parts[i])
                lon = float(parts[i + 1])
                if -90 <= lat <= 90 and -180 <= lon <= 360:
                    flux_files[(lat, lon)] = fpath
                    break
            except ValueError:
                continue

    return flux_files


def read_vic_flux_file(filepath, start_year, end_year, vic_timestep):
    """Read a VIC flux file and extract RUNOFF + BASEFLOW.

    Supports multiple VIC output formats:
    - Raw 22-column VIC format (with header lines starting with # and YEAR)
      Column order: YEAR MONTH DAY OUT_PREC OUT_RAINF OUT_SNOWF OUT_AIR_TEMP
      OUT_SWDOWN OUT_LWDOWN OUT_PRESSURE OUT_WIND OUT_DENSITY OUT_REL_HUMID
      OUT_QAIR OUT_VP OUT_VPD OUT_RUNOFF(16) OUT_BASEFLOW(17) OUT_EVAP OUT_SWE ...
    - Preprocessed 7-column: YEAR MONTH DAY PREC EVAP RUNOFF BASEFLOW
      (HydroCraft convention: runoff=col5, baseflow=col6)
    - Standard 7-column: YEAR MONTH DAY RUNOFF BASEFLOW EVAP SWE
    """
    # Count comment lines (lines starting with # or non-numeric first field)
    skip_rows = 0
    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                skip_rows += 1
                continue
            # Skip lines starting with #
            if stripped.startswith('#'):
                skip_rows += 1
                continue
            # Skip header lines like "YEAR MONTH DAY ..."
            try:
                float(stripped.split()[0])
                break  # First numeric line
            except ValueError:
                skip_rows += 1
                continue

    data = np.loadtxt(filepath, skiprows=skip_rows)

    if data.ndim == 1:
        data = data.reshape(1, -1)

    ncols = data.shape[1]

    # Determine column indices based on format
    year_col, month_col, day_col = 0, 1, 2

    if ncols >= 20:
        # Raw VIC 22-column output
        # OUT_RUNOFF is column 16 (0-indexed), OUT_BASEFLOW is column 17
        runoff_col, baseflow_col = 16, 17
    elif ncols == 7:
        # Preprocessed VIC format (HydroCraft convention):
        # Year Month Day PREC EVAP RUNOFF BASEFLOW
        runoff_col, baseflow_col = 5, 6
    elif ncols >= 5:
        # Minimal format: Year Month Day RUNOFF BASEFLOW
        runoff_col, baseflow_col = 3, 4
    else:
        raise ValueError(f"Unexpected number of columns ({ncols}) in {filepath}")

    # Filter by year range
    years = data[:, year_col].astype(int)
    mask = (years >= start_year) & (years <= end_year)
    data = data[mask]

    if len(data) == 0:
        raise ValueError(f"No data in year range {start_year}-{end_year} in {filepath}")

    # Extract total runoff (surface + subsurface)
    total_runoff = data[:, runoff_col] + data[:, baseflow_col]

    # Build date array
    dates = []
    for row in data:
        y, m, d = int(row[year_col]), int(row[month_col]), int(row[day_col])
        dates.append(datetime(y, m, d))

    return np.array(dates), total_runoff


def process(args):
    """Main processing: read VIC flux files, create mizuRoute input NetCDF."""

    print(f"Reading grid from {args.grid_nc}...")
    lat_values, lon_values = read_vic_grid(args.grid_nc)
    nlat = len(lat_values)
    nlon = len(lon_values)
    print(f"  Grid: {nlat} lats x {nlon} lons = {nlat * nlon} cells")

    print(f"Scanning VIC flux files in {args.vic_result_dir}...")
    flux_files = find_vic_flux_files(args.vic_result_dir, lat_values, lon_values)
    print(f"  Found {len(flux_files)} flux files")

    if len(flux_files) == 0:
        raise RuntimeError(f"No VIC flux files found in {args.vic_result_dir}")

    # Read one file to get time dimension
    sample_file = list(flux_files.values())[0]
    sample_dates, sample_runoff = read_vic_flux_file(
        sample_file, args.start_year, args.end_year, args.vic_timestep
    )
    ntime = len(sample_dates)
    print(f"  Time steps: {ntime} ({sample_dates[0].date()} to {sample_dates[-1].date()})")

    # Unit conversion factor
    timestep_seconds = get_timestep_seconds(args.vic_timestep)
    print(f"  VIC timestep: {args.vic_timestep} ({timestep_seconds} seconds)")
    print(f"  Unit conversion: mm/timestep -> mm/s (divide by {timestep_seconds})")

    # Initialize 3D runoff array (time, lat, lon)
    runoff_grid = np.full((ntime, nlat, nlon), -9999.0, dtype=np.float64)

    # Fill grid from flux files
    cells_found = 0
    cells_missing = 0

    for (lat, lon), fpath in flux_files.items():
        # Find grid indices
        lat_idx = np.argmin(np.abs(lat_values - lat))
        lon_idx = np.argmin(np.abs(lon_values - lon))

        # Check tolerance
        if abs(lat_values[lat_idx] - lat) > 0.01 or abs(lon_values[lon_idx] - lon) > 0.01:
            print(f"  WARNING: Flux file ({lat},{lon}) doesn't match grid, skipping")
            cells_missing += 1
            continue

        try:
            dates, runoff = read_vic_flux_file(fpath, args.start_year, args.end_year, args.vic_timestep)

            if len(runoff) != ntime:
                print(f"  WARNING: {fpath} has {len(runoff)} timesteps, expected {ntime}, skipping")
                cells_missing += 1
                continue

            # CRITICAL: Convert mm/timestep to mm/s
            runoff_mm_s = runoff / timestep_seconds

            runoff_grid[:, lat_idx, lon_idx] = runoff_mm_s
            cells_found += 1
        except Exception as e:
            print(f"  WARNING: Error reading {fpath}: {e}")
            cells_missing += 1

    print(f"  Grid cells filled: {cells_found}/{len(flux_files)}")
    if cells_missing > 0:
        print(f"  Grid cells missing: {cells_missing}")

    # Create output directory
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # Write NetCDF
    print(f"Writing output to {args.output}...")
    ref_date = datetime(args.start_year, 1, 1)
    time_values = np.array([(d - ref_date).total_seconds() / 86400.0 for d in sample_dates])

    with nc.Dataset(args.output, 'w', format='NETCDF4') as ds:
        # Dimensions
        ds.createDimension('time', None)  # unlimited
        ds.createDimension('lat', nlat)
        ds.createDimension('lon', nlon)

        # Time variable
        time_var = ds.createVariable('time', 'f8', ('time',))
        time_var.units = f'days since {ref_date.strftime("%Y-%m-%d")} 00:00:00'
        time_var.calendar = 'standard'
        time_var.long_name = 'time'
        time_var[:] = time_values

        # Lat/Lon
        lat_var = ds.createVariable('lat', 'f8', ('lat',))
        lat_var.units = 'degrees_north'
        lat_var.long_name = 'latitude'
        lat_var[:] = lat_values

        lon_var = ds.createVariable('lon', 'f8', ('lon',))
        lon_var.units = 'degrees_east'
        lon_var.long_name = 'longitude'
        lon_var[:] = lon_values

        # Runoff variable
        ro_var = ds.createVariable('RUNOFF', 'f4', ('time', 'lat', 'lon'),
                                   fill_value=-9999.0, zlib=True, complevel=4)
        ro_var.units = 'mm/s'
        ro_var.long_name = 'Total runoff (surface + subsurface) converted from VIC'
        ro_var.source_model = 'VIC 5.1.0'
        ro_var.conversion = f'VIC mm/{args.vic_timestep} divided by {timestep_seconds} seconds'
        ro_var[:] = runoff_grid

        # Global attributes
        ds.title = 'mizuRoute runoff input from VIC'
        ds.source = 'VIC 5.1.0 flux output -> convert_vic_runoff.py'
        ds.history = f'Created {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
        ds.conventions = 'CF-1.6'
        ds.start_year = args.start_year
        ds.end_year = args.end_year

    return {
        'output_file': args.output,
        'grid_shape': [nlat, nlon],
        'time_steps': ntime,
        'cells_filled': cells_found,
        'cells_missing': cells_missing,
        'unit_conversion': f'mm/{args.vic_timestep} -> mm/s (/{timestep_seconds})',
        'period': f'{args.start_year}-{args.end_year}',
    }


def validate_outputs(result):
    """Validate the output file was created correctly."""
    errors = []

    if not os.path.isfile(result['output_file']):
        errors.append(f"Output file not created: {result['output_file']}")
        return errors

    with nc.Dataset(result['output_file'], 'r') as ds:
        if 'RUNOFF' not in ds.variables:
            errors.append("RUNOFF variable missing from output")
        if 'time' not in ds.variables:
            errors.append("time variable missing from output")

        ro = ds.variables['RUNOFF']
        if ro.units != 'mm/s':
            errors.append(f"RUNOFF units should be 'mm/s', got '{ro.units}'")

        data = ro[:]
        valid_data = data[data != -9999.0]
        if len(valid_data) == 0:
            errors.append("RUNOFF contains no valid data")
        elif np.any(valid_data < 0):
            errors.append("RUNOFF contains negative values (physically impossible)")
        elif np.max(valid_data) > 1.0:
            errors.append(f"RUNOFF max = {np.max(valid_data):.4f} mm/s seems too high "
                         f"(>1 mm/s = 86.4 mm/day). Check unit conversion!")

    return errors


def main():
    parser = argparse.ArgumentParser(description='Convert VIC flux output to mizuRoute runoff NetCDF')
    parser.add_argument('--vic_result_dir', required=True, help='Directory with VIC flux files')
    parser.add_argument('--grid_nc', required=True, help='Basin grid NetCDF (basin_grid.nc)')
    parser.add_argument('--output', required=True, help='Output NetCDF file path')
    parser.add_argument('--start_year', type=int, required=True, help='Start year')
    parser.add_argument('--end_year', type=int, required=True, help='End year')
    parser.add_argument('--vic_timestep', default='daily',
                       choices=['daily', '3hourly', 'hourly'],
                       help='VIC output timestep (default: daily)')

    args = parser.parse_args()

    if not validate_inputs(args):
        sys.exit(1)

    try:
        result = process(args)

        errors = validate_outputs(result)
        if errors:
            for e in errors:
                print(f"OUTPUT VALIDATION ERROR: {e}", file=sys.stderr)
            sys.exit(3)

        print(json.dumps(result, indent=2))
        print("\nSUCCESS: VIC runoff converted to mizuRoute input format")

    except Exception as e:
        print(f"PROCESSING ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
