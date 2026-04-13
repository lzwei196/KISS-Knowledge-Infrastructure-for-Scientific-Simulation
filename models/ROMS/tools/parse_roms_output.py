#!/usr/bin/env python3
"""
Parse ROMS NetCDF Output
=========================
Extracts time series, profiles, and cross-sections from ROMS history,
average, and station output files. Exports to CSV or JSON.

Modes:
  --mode timeseries  : Extract variable time series at a point/area
  --mode profile     : Extract vertical profiles at a location
  --mode section     : Extract cross-section along a transect
  --mode surface     : Extract 2D surface field at a time step
  --mode statistics  : Compute domain-wide statistics (min, max, mean, std)

Inputs:
  --input    : ROMS NetCDF output file (history, average, or station)
  --variable : Variable name(s) to extract (comma-separated)
  --lon      : Longitude for point extraction
  --lat      : Latitude for point extraction
  --level    : Vertical level index (0=bottom, N-1=surface)
  --time-idx : Time index (or 'all')

Output:
  --output   : Output file path (.csv or .json)
  --format   : Output format (csv, json)

Usage:
  # Time series of SST at a point
  python parse_roms_output.py \\
    --input roms_his.nc --variable temp --mode timeseries \\
    --lon -74.0 --lat 39.0 --level -1 --output sst_timeseries.csv

  # Vertical temperature profile
  python parse_roms_output.py \\
    --input roms_his.nc --variable temp --mode profile \\
    --lon -74.0 --lat 39.0 --time-idx -1 --output temp_profile.csv

  # Domain statistics
  python parse_roms_output.py \\
    --input roms_his.nc --variable temp,salt,zeta --mode statistics \\
    --output domain_stats.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    from netCDF4 import Dataset, num2date
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not HAS_NETCDF4:
        errors.append("netCDF4 Python package is required")

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.mode not in ('timeseries', 'profile', 'section', 'surface', 'statistics'):
        errors.append(f"Invalid mode: {args.mode}")

    if args.mode in ('timeseries', 'profile') and (args.lon is None or args.lat is None):
        errors.append(f"Mode '{args.mode}' requires --lon and --lat")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def find_nearest_point(lon_rho, lat_rho, target_lon, target_lat):
    """Find nearest grid point to target coordinates."""
    dist = np.sqrt((lon_rho - target_lon)**2 + (lat_rho - target_lat)**2)
    j, i = np.unravel_index(dist.argmin(), dist.shape)
    return int(j), int(i)


def get_time_array(ds):
    """Extract time array and convert to datetime."""
    for tname in ['ocean_time', 'time', 'scrum_time']:
        if tname in ds.variables:
            tv = ds.variables[tname]
            if hasattr(tv, 'units'):
                try:
                    times = num2date(tv[:], tv.units)
                    return times, tv[:]
                except Exception:
                    pass
            return None, tv[:]
    return None, None


def compute_depths(ds, j, i, time_idx=0):
    """Compute actual depths at a grid point from S-coordinates.

    Uses Vtransform and stretching parameters from the file or defaults.
    """
    h = ds.variables['h'][j, i] if 'h' in ds.variables else 100.0

    if 'zeta' in ds.variables:
        zeta = ds.variables['zeta'][time_idx, j, i]
    else:
        zeta = 0.0

    if 'Cs_r' in ds.variables:
        Cs_r = ds.variables['Cs_r'][:]
    elif 's_rho' in ds.variables:
        Cs_r = ds.variables['s_rho'][:]
    else:
        N = ds.dimensions.get('s_rho', ds.dimensions.get('N', None))
        if N:
            Cs_r = np.linspace(-1, 0, len(N))
        else:
            return None

    # Vtransform 2 (default/modern)
    hc = float(ds.variables['hc'][:]) if 'hc' in ds.variables else 200.0

    N = len(Cs_r)
    z = np.zeros(N)
    for k in range(N):
        z0 = (hc * Cs_r[k] + h * Cs_r[k]) / (hc + h)
        z[k] = zeta + (zeta + h) * z0

    return z


def extract_timeseries(ds, var_name, j, i, level=-1):
    """Extract time series of a variable at a grid point."""
    var = ds.variables[var_name]
    ndim = var.ndim

    if ndim == 3:  # (time, eta, xi) — 2D variable like zeta
        data = var[:, j, i]
    elif ndim == 4:  # (time, s_rho, eta, xi) — 3D variable
        data = var[:, level, j, i]
    elif ndim == 2:  # (eta, xi) — single snapshot
        data = np.array([var[j, i]])
    else:
        data = var[:]

    return data


def extract_profile(ds, var_name, j, i, time_idx=-1):
    """Extract vertical profile at a grid point."""
    var = ds.variables[var_name]
    if var.ndim == 4:
        profile = var[time_idx, :, j, i]
    elif var.ndim == 3:
        profile = np.array([var[time_idx, j, i]])
    else:
        profile = var[:]
    return profile


def extract_surface(ds, var_name, time_idx=-1, level=-1):
    """Extract 2D surface field."""
    var = ds.variables[var_name]
    if var.ndim == 4:
        field = var[time_idx, level, :, :]
    elif var.ndim == 3:
        field = var[time_idx, :, :]
    elif var.ndim == 2:
        field = var[:, :]
    else:
        field = var[:]
    return field


def compute_statistics(ds, var_names):
    """Compute domain-wide statistics for each variable."""
    stats = {}
    for var_name in var_names:
        if var_name not in ds.variables:
            stats[var_name] = {"error": "variable not found"}
            continue

        var = ds.variables[var_name]
        data = var[:]

        # Handle masked arrays
        if hasattr(data, 'compressed'):
            flat = data.compressed()
        else:
            flat = data[~np.isnan(data)] if np.any(np.isnan(data)) else data.ravel()

        if len(flat) == 0:
            stats[var_name] = {"error": "all values masked or NaN"}
            continue

        stats[var_name] = {
            "min": float(np.min(flat)),
            "max": float(np.max(flat)),
            "mean": float(np.mean(flat)),
            "std": float(np.std(flat)),
            "units": getattr(var, 'units', 'unknown'),
            "shape": list(var.shape),
            "has_nan": bool(np.any(np.isnan(data))) if not hasattr(data, 'mask') else bool(np.any(data.mask)),
        }

    return stats


def write_csv(output_path, columns, data_dict):
    """Write data to CSV file."""
    import csv
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        n_rows = len(next(iter(data_dict.values())))
        for i in range(n_rows):
            row = [data_dict[col][i] if i < len(data_dict[col]) else '' for col in columns]
            writer.writerow(row)


def validate_output(output_path, mode):
    """Validate the generated output file."""
    errors = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return errors

    size = os.path.getsize(output_path)
    if size == 0:
        errors.append("Output file is empty")

    if output_path.endswith('.csv'):
        with open(output_path, 'r') as f:
            lines = f.readlines()
        if len(lines) < 2:
            errors.append(f"CSV has only {len(lines)} lines (expected header + data)")

    return errors


def main():
    parser = argparse.ArgumentParser(description='Parse ROMS NetCDF output')
    parser.add_argument('--input', required=True, help='ROMS output NetCDF file')
    parser.add_argument('--variable', required=True,
                        help='Variable name(s), comma-separated')
    parser.add_argument('--mode', required=True,
                        choices=['timeseries', 'profile', 'section', 'surface', 'statistics'],
                        help='Extraction mode')
    parser.add_argument('--lon', type=float, default=None,
                        help='Target longitude')
    parser.add_argument('--lat', type=float, default=None,
                        help='Target latitude')
    parser.add_argument('--level', type=int, default=-1,
                        help='Vertical level index (default: -1 = surface)')
    parser.add_argument('--time-idx', type=str, default='all',
                        help='Time index or "all"')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--format', default='csv', choices=['csv', 'json'],
                        help='Output format')

    args = parser.parse_args()
    validate_inputs(args)

    ds = Dataset(args.input, 'r')
    var_names = [v.strip() for v in args.variable.split(',')]
    times_dt, times_raw = get_time_array(ds)

    # Find grid point
    j, i = None, None
    if args.lon is not None and args.lat is not None:
        if 'lon_rho' in ds.variables:
            lon_rho = ds.variables['lon_rho'][:]
            lat_rho = ds.variables['lat_rho'][:]
        else:
            # Station file may use different naming
            for ln in ['lon_rho', 'longitude', 'lon']:
                if ln in ds.variables:
                    lon_rho = ds.variables[ln][:]
                    break
            for ln in ['lat_rho', 'latitude', 'lat']:
                if ln in ds.variables:
                    lat_rho = ds.variables[ln][:]
                    break

        j, i = find_nearest_point(lon_rho, lat_rho, args.lon, args.lat)
        print(f"Nearest grid point: j={j}, i={i} "
              f"(lon={lon_rho[j,i]:.4f}, lat={lat_rho[j,i]:.4f})")

    if args.mode == 'timeseries':
        data_dict = {}
        if times_dt is not None:
            data_dict['time'] = [str(t) for t in times_dt]
        elif times_raw is not None:
            data_dict['time_seconds'] = list(times_raw.astype(float))

        for var_name in var_names:
            ts = extract_timeseries(ds, var_name, j, i, level=args.level)
            data_dict[var_name] = list(ts.astype(float))

        if args.format == 'csv':
            write_csv(args.output, list(data_dict.keys()), data_dict)
        else:
            with open(args.output, 'w') as f:
                json.dump(data_dict, f, indent=2, default=str)

    elif args.mode == 'profile':
        tidx = -1 if args.time_idx == 'all' else int(args.time_idx)
        data_dict = {}

        depths = compute_depths(ds, j, i, time_idx=tidx)
        if depths is not None:
            data_dict['depth_m'] = list(depths.astype(float))

        for var_name in var_names:
            profile = extract_profile(ds, var_name, j, i, time_idx=tidx)
            data_dict[var_name] = list(profile.astype(float))

        if args.format == 'csv':
            write_csv(args.output, list(data_dict.keys()), data_dict)
        else:
            with open(args.output, 'w') as f:
                json.dump(data_dict, f, indent=2)

    elif args.mode == 'surface':
        tidx = -1 if args.time_idx == 'all' else int(args.time_idx)
        result = {}
        for var_name in var_names:
            field = extract_surface(ds, var_name, time_idx=tidx, level=args.level)
            result[var_name] = {
                "shape": list(field.shape),
                "min": float(np.nanmin(field)),
                "max": float(np.nanmax(field)),
                "mean": float(np.nanmean(field)),
            }
            # For CSV output, flatten
            if args.format == 'csv':
                data_dict = {}
                ny, nx = field.shape
                data_dict['j'] = [jj for jj in range(ny) for _ in range(nx)]
                data_dict['i'] = [ii for _ in range(ny) for ii in range(nx)]
                data_dict[var_name] = list(field.ravel().astype(float))
                write_csv(args.output, list(data_dict.keys()), data_dict)
                break

        if args.format == 'json':
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)

    elif args.mode == 'statistics':
        stats = compute_statistics(ds, var_names)
        if args.format == 'json':
            with open(args.output, 'w') as f:
                json.dump(stats, f, indent=2)
        else:
            # CSV format for statistics
            data_dict = {
                'variable': [],
                'min': [], 'max': [], 'mean': [], 'std': [], 'units': []
            }
            for var_name, s in stats.items():
                if 'error' in s:
                    continue
                data_dict['variable'].append(var_name)
                data_dict['min'].append(s['min'])
                data_dict['max'].append(s['max'])
                data_dict['mean'].append(s['mean'])
                data_dict['std'].append(s['std'])
                data_dict['units'].append(s['units'])
            write_csv(args.output, list(data_dict.keys()), data_dict)

    ds.close()

    # Validate output
    errors = validate_output(args.output, args.mode)
    result_summary = {
        "status": "error" if errors else "success",
        "output": args.output,
        "mode": args.mode,
        "variables": var_names,
        "errors": errors
    }
    print(json.dumps(result_summary, indent=2))


if __name__ == '__main__':
    main()
