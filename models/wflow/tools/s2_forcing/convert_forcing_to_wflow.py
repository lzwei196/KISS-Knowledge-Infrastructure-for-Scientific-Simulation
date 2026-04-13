#!/usr/bin/env python3
"""
convert_forcing_to_wflow.py — Convert CMFD/MSWX forcing to wflow NetCDF format.

wflow requires a single NetCDF forcing file with dimensions (time, y, x) and
variables: precip (mm/timestep), temp (degC), pet (mm/timestep).

This tool reads HydroCraft's pre-processed VIC forcing files (ASCII per cell)
or raw CMFD/MSWX NetCDF and converts them to wflow format.

CRITICAL UNIT CONVERSIONS:
  - Temperature: Kelvin -> Celsius (subtract 273.15)
  - Precipitation: mm/s or mm/3hr -> mm/day (multiply accordingly)
  - PET: calculated from T, radiation, wind, humidity using Hargreaves or
    Penman-Monteith. wflow can also compute PET internally if individual
    variables are provided.

Usage:
    python convert_forcing_to_wflow.py \
      --forcing_dir /path/to/vic/forcing/forcing_final \
      --grid_nc /path/to/basin_grid.nc \
      --start_year 2000 --end_year 2010 \
      --output /path/to/wflow_project/forcing.nc

    python convert_forcing_to_wflow.py \
      --cmfd_dir /path/to/CMFD \
      --grid_nc /path/to/basin_grid.nc \
      --start_year 2000 --end_year 2010 \
      --output /path/to/wflow_project/forcing.nc
"""

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

import numpy as np


def read_cmfd_forcing_direct(forcing_dir, grid_path, start_year, end_year):
    """Read CMFD 3-hourly NetCDF directly from Prec/, Temp/, SRad/ subdirectories.

    Returns: times, lats, lons, precip(mm/day), temp(degC), pet(mm/day)
    """
    import xarray as xr
    import math

    forcing_dir = Path(forcing_dir)

    # Get grid coordinates from staticmaps or grid_nc
    if grid_path:
        ds_grid = xr.open_dataset(grid_path)
        if 'lat' in ds_grid.dims:
            lats = ds_grid['lat'].values
            lons = ds_grid['lon'].values
        elif 'y' in ds_grid.dims:
            lats = ds_grid['y'].values
            lons = ds_grid['x'].values
        else:
            lats = ds_grid[list(ds_grid.dims)[0]].values
            lons = ds_grid[list(ds_grid.dims)[1]].values
        ds_grid.close()
    else:
        raise ValueError("grid_path required for CMFD direct read")

    ny, nx = len(lats), len(lons)
    cmfd_vars = {
        'Prec': ('prec', 'sum'),     # mm/3hr -> sum to mm/day
        'Temp': ('temp', 'mean'),     # K -> mean then -273.15
        'SRad': ('srad', 'mean'),     # W/m2 -> mean
    }

    from datetime import datetime, timedelta
    all_dates = []
    all_precip = []
    all_temp = []
    all_srad = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            data_month = {}
            for subdir, (pattern, agg) in cmfd_vars.items():
                sd = forcing_dir / subdir
                nc_files = sorted(sd.glob(f"*{year}{month:02d}*")) if sd.exists() else []
                if not nc_files:
                    nc_files = sorted(forcing_dir.glob(f"*{pattern}*{year}{month:02d}*"))
                if nc_files:
                    ds = xr.open_dataset(nc_files[0])
                    dvar = [v for v in ds.data_vars if pattern in v.lower()] or list(ds.data_vars)
                    raw = ds[dvar[0]].values  # (time, lat, lon)
                    grid_lats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                    grid_lons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                    # Nearest-neighbor to target grid
                    extracted = np.zeros((raw.shape[0], ny, nx))
                    for j in range(ny):
                        for i in range(nx):
                            li = int(np.argmin(np.abs(grid_lats - lats[j])))
                            lo = int(np.argmin(np.abs(grid_lons - lons[i])))
                            extracted[:, j, i] = raw[:, li, lo]
                    data_month[subdir] = (extracted, agg)
                    ds.close()

            if 'Prec' not in data_month:
                continue

            n_days = data_month['Prec'][0].shape[0] // 8
            for d in range(n_days):
                s, e = d * 8, (d + 1) * 8
                all_dates.append(datetime(year, month, 1) + timedelta(days=d))
                p = data_month['Prec'][0][s:e]
                all_precip.append(np.sum(p, axis=0))  # sum mm/3hr -> mm/day
                if 'Temp' in data_month:
                    t = data_month['Temp'][0][s:e]
                    all_temp.append(np.mean(t, axis=0) - 273.15)  # K -> C
                else:
                    all_temp.append(np.full((ny, nx), 15.0))
                if 'SRad' in data_month:
                    sr = data_month['SRad'][0][s:e]
                    # Compute Hargreaves PET: 0.0023 * Ra * (T+17.8) * sqrt(DTR)
                    t_mean = np.mean(data_month['Temp'][0][s:e], axis=0) - 273.15 if 'Temp' in data_month else 15.0
                    ra_mj = np.mean(sr, axis=0) * 0.0864  # W/m2 -> MJ/m2/d
                    dtr = 10.0  # assumed diurnal range
                    pet_day = np.maximum(0, 0.0023 * ra_mj * (t_mean + 17.8) * math.sqrt(dtr))
                    all_pet.append(pet_day)

        print(f"  Year {year} processed", file=sys.stderr)

    # Handle pet list
    try:
        all_pet
    except NameError:
        all_pet = [np.full((ny, nx), 2.0) for _ in all_dates]

    times = np.array(all_dates, dtype='datetime64[D]')
    precip = np.stack(all_precip)
    temp = np.stack(all_temp)
    pet = np.stack(all_pet) if all_pet else np.full_like(precip, 2.0)

    return times, lats, lons, precip, temp, pet


def validate_inputs(args):
    """Validate forcing data sources."""
    errors = []

    if not args.forcing_dir and not args.cmfd_dir and not args.mswx_dir:
        errors.append(
            "Must provide --forcing_dir (VIC ASCII), --cmfd_dir, or --mswx_dir"
        )

    if args.forcing_dir and not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if not args.grid_nc and not args.staticmaps_nc:
        errors.append("Must provide --grid_nc or --staticmaps_nc for grid definition")

    grid_path = args.grid_nc or args.staticmaps_nc
    if grid_path and not os.path.exists(grid_path):
        errors.append(f"Grid file not found: {grid_path}")

    if args.start_year >= args.end_year:
        errors.append(
            f"start_year ({args.start_year}) must be < end_year ({args.end_year})"
        )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def read_vic_forcing_files(forcing_dir, grid_nc, start_year, end_year):
    """Read VIC-format ASCII forcing files and convert to wflow arrays.

    VIC forcing files are per-cell ASCII files with columns:
    PREC  TMAX  TMIN  WIND  SHORTWAVE  LONGWAVE  VP  PRESSURE
    (or similar, depending on the HydroCraft forcing pipeline)
    """
    import xarray as xr
    import pandas as pd

    # Read grid to get cell coordinates
    ds_grid = xr.open_dataset(grid_nc)
    if "lat" in ds_grid and "lon" in ds_grid:
        lats = ds_grid["lat"].values
        lons = ds_grid["lon"].values
    elif "y" in ds_grid.dims and "x" in ds_grid.dims:
        lats = ds_grid["y"].values
        lons = ds_grid["x"].values
    else:
        raise ValueError(f"Cannot determine grid coordinates from {grid_nc}")

    # Determine grid dimensions
    if lats.ndim == 1 and lons.ndim == 1:
        ny, nx = len(lats), len(lons)
    else:
        ny, nx = lats.shape

    # Generate time coordinate
    start_date = pd.Timestamp(f"{start_year}-01-01")
    end_date = pd.Timestamp(f"{end_year}-12-31")
    times = pd.date_range(start_date, end_date, freq="D")
    nt = len(times)

    # Initialize arrays
    precip = np.full((nt, ny, nx), np.nan, dtype=np.float32)
    temp = np.full((nt, ny, nx), np.nan, dtype=np.float32)
    pet = np.full((nt, ny, nx), np.nan, dtype=np.float32)

    # Find forcing files - try multiple naming patterns
    forcing_files = sorted(glob.glob(os.path.join(forcing_dir, "forcing_*")))
    if not forcing_files:
        # Try HydroCraft pattern: {basin}_{res}deg_{lat}_{lon}
        forcing_files = sorted(glob.glob(os.path.join(forcing_dir, "*_*deg_*")))
    if not forcing_files:
        forcing_files = sorted(glob.glob(os.path.join(forcing_dir, "*_forcing_*")))
    if not forcing_files:
        forcing_files = sorted(glob.glob(os.path.join(forcing_dir, "*.txt")))

    print(f"  Found {len(forcing_files)} forcing files", file=sys.stderr)

    for fpath in forcing_files:
        # Parse lat/lon from filename
        fname = os.path.basename(fpath)
        parts = fname.split("_")
        flat = flon = None

        # Try HydroCraft pattern: {basin}_{res}deg_{lat}_{lon}
        # e.g., bengbu_0.25deg_31.1250_115.6250
        if len(parts) >= 4 and "deg" in parts[1]:
            try:
                flat = float(parts[2])
                flon = float(parts[3])
            except (ValueError, IndexError):
                pass

        # Try standard patterns: forcing_{lat}_{lon}, data_{lat}_{lon}
        if flat is None:
            cleaned = fname.replace("forcing_", "").replace("data_", "")
            cparts = cleaned.split("_")
            try:
                flat = float(cparts[-2]) if len(cparts) >= 2 else float(cparts[0])
                flon = float(cparts[-1]) if len(cparts) >= 2 else float(cparts[1])
            except (ValueError, IndexError):
                pass

        if flat is None or flon is None:
            print(f"  WARNING: Cannot parse coordinates from {fname}", file=sys.stderr)
            continue

        # Find grid indices
        if lats.ndim == 1:
            j = np.argmin(np.abs(lats - flat))
            i = np.argmin(np.abs(lons - flon))
        else:
            dists = (lats - flat) ** 2 + (lons - flon) ** 2
            j, i = np.unravel_index(dists.argmin(), dists.shape)

        # Read forcing data
        try:
            data = np.loadtxt(fpath)
        except Exception as e:
            print(f"  WARNING: Cannot read {fname}: {e}", file=sys.stderr)
            continue

        # Determine if data is sub-daily or daily
        # VIC forcing columns: AIR_TEMP(0) PREC(1) PRESSURE(2) SWDOWN(3) LWDOWN(4) VP(5) WIND(6)
        # HydroCraft 3-hourly: 8 timesteps/day
        # Heuristic: if nrows > nt * 2, data is sub-daily
        nrows_total = data.shape[0]
        if nrows_total > nt * 1.5:
            # Sub-daily data: aggregate to daily
            steps_per_day = round(nrows_total / nt)
            if steps_per_day < 1:
                steps_per_day = 1
            usable_days = min(nrows_total // steps_per_day, nt)
            daily_data = data[:usable_days * steps_per_day].reshape(usable_days, steps_per_day, -1)

            # Col 0: AIR_TEMP (degC) -> daily mean
            temp[:usable_days, j, i] = daily_data[:, :, 0].mean(axis=1)

            # Col 1: PREC (mm/timestep) -> daily sum
            precip[:usable_days, j, i] = daily_data[:, :, 1].sum(axis=1)

            # For PET: use daily Tmax/Tmin from sub-daily T
            tmax = daily_data[:, :, 0].max(axis=1)
            tmin = daily_data[:, :, 0].min(axis=1)
        else:
            # Daily data
            nrows = min(nrows_total, nt)

            if data.shape[1] >= 3:
                precip[:nrows, j, i] = data[:nrows, 1]  # PREC
                temp[:nrows, j, i] = data[:nrows, 0]    # AIR_TEMP
                tmax = data[:nrows, 0]  # Only have mean T for daily
                tmin = data[:nrows, 0]
            usable_days = nrows

        if data.shape[1] >= 3 and usable_days > 0:

            # PET: Hargreaves estimate from Tmax, Tmin, and day of year
            # PET = 0.0023 * Ra * (T + 17.78) * sqrt(Tmax - Tmin)
            doy = np.array([t.timetuple().tm_yday for t in times[:usable_days]])
            lat_rad = np.radians(flat)
            # Extraterrestrial radiation (Ra) approximation (MJ/m2/day)
            dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * doy / 365.0)
            delta = 0.4093 * np.sin(2.0 * np.pi * doy / 365.0 - 1.39)
            ws = np.arccos(-np.tan(lat_rad) * np.tan(delta))
            ws = np.clip(ws, 0.0, np.pi)
            ra = (
                24.0
                * 60.0
                / np.pi
                * 0.0820
                * dr
                * (
                    ws * np.sin(lat_rad) * np.sin(delta)
                    + np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
                )
            )
            ra = np.maximum(ra, 0.0)

            t_range = np.maximum(tmax - tmin, 0.1)
            t_mean = (tmax + tmin) / 2.0
            # Hargreaves PET in mm/day
            pet_val = 0.0023 * ra * (t_mean + 17.78) * np.sqrt(t_range) / 2.45
            pet_val = np.maximum(pet_val, 0.0)
            pet[:usable_days, j, i] = pet_val

    return times, lats if lats.ndim == 1 else lats[:, 0], \
           lons if lons.ndim == 1 else lons[0, :], precip, temp, pet


def process(args):
    """Convert forcing data to wflow NetCDF format."""
    import xarray as xr

    start_time = time.time()

    print(f"Converting forcing data to wflow format...", file=sys.stderr)
    print(f"  Period: {args.start_year}-{args.end_year}", file=sys.stderr)

    grid_path = args.grid_nc or args.staticmaps_nc

    if args.forcing_dir:
        # Try VIC ASCII first, then CMFD NetCDF from subdirectories
        forcing_dir = Path(args.forcing_dir)
        vic_files = list(forcing_dir.glob("*_*.*_*.*"))  # VIC naming pattern
        cmfd_subdirs = any((forcing_dir / d).exists() for d in ['Prec', 'Temp', 'SRad'])

        if vic_files and not cmfd_subdirs:
            times, lats, lons, precip, temp, pet = read_vic_forcing_files(
                args.forcing_dir, grid_path, args.start_year, args.end_year
            )
        else:
            # Read CMFD NetCDF directly from Prec/, Temp/, SRad/ subdirectories
            print("  Reading CMFD NetCDF from subdirectories...", file=sys.stderr)
            times, lats, lons, precip, temp, pet = read_cmfd_forcing_direct(
                args.forcing_dir, grid_path, args.start_year, args.end_year
            )
    else:
        raise ValueError("--forcing_dir is required")

    # Check for NaN coverage
    valid_cells = np.isfinite(precip[0]).sum()
    total_cells = (precip[0] != 0).sum()
    print(f"  Valid cells: {valid_cells}", file=sys.stderr)

    # Replace NaN with 0 for precip and pet, with mean for temp
    precip = np.nan_to_num(precip, nan=0.0)
    pet = np.nan_to_num(pet, nan=0.0)
    temp_mean = np.nanmean(temp)
    temp = np.nan_to_num(temp, nan=temp_mean)

    # Create wflow forcing NetCDF
    ds = xr.Dataset(
        {
            "precip": (
                ["time", "y", "x"],
                precip,
                {
                    "units": "mm",
                    "long_name": "Precipitation",
                    "standard_name": "atmosphere_water__precipitation_volume_flux",
                    "description": "Total precipitation per day",
                },
            ),
            "temp": (
                ["time", "y", "x"],
                temp,
                {
                    "units": "degC",
                    "long_name": "Air temperature",
                    "standard_name": "atmosphere_air__temperature",
                    "description": "Mean daily air temperature (Celsius)",
                },
            ),
            "pet": (
                ["time", "y", "x"],
                pet,
                {
                    "units": "mm",
                    "long_name": "Potential evapotranspiration",
                    "standard_name": "land_surface_water__potential_evaporation_volume_flux",
                    "description": "PET per day (Hargreaves method)",
                },
            ),
        },
        coords={
            "time": times,
            "y": lats,
            "x": lons,
        },
    )

    ds.attrs["Conventions"] = "CF-1.6"
    ds.attrs["title"] = "wflow forcing data converted from HydroCraft"
    ds.attrs["source"] = f"Converted from {args.forcing_dir or args.cmfd_dir or args.mswx_dir}"
    ds.attrs["timestep_seconds"] = 86400

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    ds.to_netcdf(args.output, encoding={
        "precip": {"dtype": "float32", "zlib": True, "complevel": 4},
        "temp": {"dtype": "float32", "zlib": True, "complevel": 4},
        "pet": {"dtype": "float32", "zlib": True, "complevel": 4},
    })

    elapsed = time.time() - start_time

    return {
        "status": "success",
        "output_path": args.output,
        "size_mb": round(os.path.getsize(args.output) / 1e6, 1),
        "time_steps": len(times),
        "grid_shape": f"{len(lats)} x {len(lons)}",
        "variables": ["precip (mm/day)", "temp (degC)", "pet (mm/day)"],
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD/MSWX/VIC forcing to wflow NetCDF format"
    )
    parser.add_argument("--forcing_dir", type=str, default="",
                        help="VIC ASCII forcing directory")
    parser.add_argument("--cmfd_dir", type=str, default="",
                        help="Raw CMFD NetCDF directory")
    parser.add_argument("--mswx_dir", type=str, default="",
                        help="Raw MSWX NetCDF directory")
    parser.add_argument("--grid_nc", type=str, default="",
                        help="Basin grid NetCDF (from VIC pipeline)")
    parser.add_argument("--staticmaps_nc", type=str, default="",
                        help="wflow staticmaps.nc (alternative to grid_nc)")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
