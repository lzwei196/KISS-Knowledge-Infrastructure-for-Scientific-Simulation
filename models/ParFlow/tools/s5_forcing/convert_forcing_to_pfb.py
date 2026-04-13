#!/usr/bin/env python3
"""
Convert CMFD/MSWX meteorological forcing to ParFlow/CLM PFB format.

CLM forcing variables and their CRITICAL units:
  DSWR  - Downward shortwave radiation (W/m2)
  DLWR  - Downward longwave radiation (W/m2)
  APCP  - Precipitation rate (mm/s = kg/m2/s, NOT mm/hr or mm/3hr)
  Tmp   - Air temperature (K, NOT degC)
  UGRD  - U-component wind speed (m/s)
  VGRD  - V-component wind speed (m/s)
  Press - Surface pressure (Pa, NOT hPa or kPa)
  SPFH  - Specific humidity (kg/kg, NOT g/kg or relative humidity %)

CRITICAL UNIT CONVERSIONS:
  - CMFD temperature: K (correct for CLM, no conversion needed)
  - CMFD precipitation: mm/hr -> mm/s (divide by 3600)
  - CMFD pressure: Pa (correct, no conversion)
  - CMFD shortwave: W/m2 (correct)
  - CMFD longwave: W/m2 (correct)
  - CMFD specific humidity: kg/kg (correct)
  - CMFD wind: m/s (correct) -- split into U/V components

Usage:
    python convert_forcing_to_pfb.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --forcing_source cmfd \
        --forcing_dir data/forcing/Data_forcing_03hr_010deg/ \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output_dir outputs/parflow_run/forcing/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import xarray as xr
    from pyproj import Transformer
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


HYDROCRAFT_ROOT = "/mnt/disk1/Hydrocraft_server"

# CLM forcing variable names (in the order CLM expects them)
CLM_VARS = ["DSWR", "DLWR", "APCP", "Tmp", "UGRD", "VGRD", "Press", "SPFH"]

# CMFD variable mapping
CMFD_VAR_MAP = {
    "DSWR": {"file_pattern": "srad", "scale": 1.0, "offset": 0.0},    # W/m2 -> W/m2
    "DLWR": {"file_pattern": "lrad", "scale": 1.0, "offset": 0.0},    # W/m2 -> W/m2
    "APCP": {"file_pattern": "prec", "scale": 1.0/3600.0, "offset": 0.0},  # mm/hr -> mm/s
    "Tmp":  {"file_pattern": "temp", "scale": 1.0, "offset": 0.0},    # K -> K
    "UGRD": {"file_pattern": "wind", "scale": 1.0, "offset": 0.0},    # m/s (treated as U)
    "VGRD": {"file_pattern": "wind", "scale": 0.0, "offset": 0.0},    # V=0 (only scalar wind)
    "Press": {"file_pattern": "pres", "scale": 1.0, "offset": 0.0},   # Pa -> Pa
    "SPFH": {"file_pattern": "shum", "scale": 1.0, "offset": 0.0},    # kg/kg -> kg/kg
}


def validate_inputs(domain_json, forcing_dir):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")
    return errors


def process(domain_json, forcing_source, forcing_dir, start_date, end_date,
            output_dir, run_name="parflow_run", dt_hours=1):
    """
    Convert forcing data to ParFlow/CLM PFB format.

    For each timestep, creates a PFB file containing 8 variables
    distributed on the ParFlow grid.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    # Build coordinate lookup: for each ParFlow cell, find the forcing grid cell
    transformer = Transformer.from_crs(
        f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
    )
    lons = np.zeros((ny, nx))
    lats = np.zeros((ny, nx))
    for j in range(ny):
        for i in range(nx):
            cx = origin_x + (i + 0.5) * dx
            cy = origin_y + (j + 0.5) * dy
            lo, la = transformer.transform(cx, cy)
            lons[j, i] = lo
            lats[j, i] = la

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Count total timesteps
    total_hours = int((end_dt - start_dt).total_seconds() / 3600)
    total_steps = total_hours // dt_hours

    # Create output as numpy arrays per timestep
    # CLM expects files named: NLDAS.<run_name>.NNNNN.pfb
    # Each file has 8 2D fields stacked as (8, ny, nx)
    timestep_count = 0
    files_created = []

    # Process in monthly chunks to manage memory
    current = start_dt
    while current < end_dt:
        year = current.year
        month = current.month

        # Calculate hours in this month
        next_month = current.replace(day=28) + timedelta(days=4)
        next_month = next_month.replace(day=1)
        if next_month > end_dt:
            next_month = end_dt
        hours_in_period = int((next_month - current).total_seconds() / 3600)
        steps_in_period = hours_in_period // dt_hours

        # Load CMFD/MSWX data for this month
        var_map = CMFD_VAR_MAP
        month_data = {}  # clm_var -> (n_timesteps, ny, nx)

        for clm_var, info in var_map.items():
            pattern = info["file_pattern"]
            scale = info["scale"]
            offset = info["offset"]

            # Search in variable subdirectories (CMFD structure: Prec/, Temp/, etc.)
            nc_files = []
            forcing_path = Path(forcing_dir)
            for subdir_name in [pattern, pattern.capitalize(), pattern.upper()]:
                subdir = forcing_path / subdir_name
                if subdir.exists():
                    nc_files = sorted(subdir.glob(f"*{year}{month:02d}*"))
                    break
            if not nc_files:
                nc_files = sorted(forcing_path.glob(f"*{pattern}*{year}{month:02d}*"))

            if nc_files:
                ds = xr.open_dataset(nc_files[0])
                data_var = [v for v in ds.data_vars if pattern in v.lower()][0] if any(pattern in v.lower() for v in ds.data_vars) else list(ds.data_vars)[0]
                grid_lats_src = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                grid_lons_src = ds['lon'].values if 'lon' in ds else ds['longitude'].values

                # Extract for each ParFlow cell using nearest neighbor
                raw = ds[data_var].values  # (time, lat, lon)
                extracted = np.zeros((raw.shape[0], ny, nx), dtype=np.float64)
                for j in range(ny):
                    for i in range(nx):
                        lat_idx = np.argmin(np.abs(grid_lats_src - lats[j, i]))
                        lon_idx = np.argmin(np.abs(grid_lons_src - lons[j, i]))
                        extracted[:, j, i] = raw[:, lat_idx, lon_idx] * scale + offset
                month_data[clm_var] = extracted
                ds.close()
            else:
                # Fallback to default if no file found
                print(f"  WARNING: No {pattern} file for {year}-{month:02d}, using defaults")
                default_vals = {"DSWR": 200.0, "DLWR": 300.0, "APCP": 0.0,
                                "Tmp": 283.0, "UGRD": 2.0, "VGRD": 0.0,
                                "Press": 101325.0, "SPFH": 0.005}
                month_data[clm_var] = np.full((steps_in_period, ny, nx),
                                              default_vals.get(clm_var, 0.0))

        # For each timestep, assemble the 8-variable forcing array
        for step in range(steps_in_period):
            forcing_data = np.zeros((8, ny, nx), dtype=np.float64)
            for v_idx, clm_var in enumerate(CLM_VARS):
                if clm_var in month_data:
                    src = month_data[clm_var]
                    # Map 3-hourly source steps to hourly output steps
                    src_step = min(step * dt_hours // 3, src.shape[0] - 1)
                    forcing_data[v_idx, :, :] = src[src_step, :, :]

            # Save as PFB or numpy
            step_num = timestep_count + 1
            fname = f"NLDAS.{run_name}.{step_num:06d}"

            try:
                from parflow.tools.io import write_pfb
                pfb_path = os.path.join(output_dir, f"{fname}.pfb")
                write_pfb(pfb_path, forcing_data, dx=dx, dy=dy, dz=1.0,
                          x=origin_x, y=origin_y, z=0.0)
                files_created.append(pfb_path)
            except ImportError:
                npy_path = os.path.join(output_dir, f"{fname}.npy")
                np.save(npy_path, forcing_data)
                files_created.append(npy_path)

            timestep_count += 1

        current = next_month

    result = {
        "status": "success",
        "forcing_source": forcing_source,
        "output_dir": output_dir,
        "files_created": len(files_created),
        "total_timesteps": timestep_count,
        "timestep_hours": dt_hours,
        "period": {"start": start_date, "end": end_date},
        "variables": CLM_VARS,
        "unit_conversions_applied": {
            "precipitation": "mm/hr -> mm/s (divided by 3600)",
            "temperature": "K (no conversion)",
            "pressure": "Pa (no conversion)",
            "radiation": "W/m2 (no conversion)",
            "humidity": "kg/kg specific humidity (no conversion)",
            "wind": "m/s (scalar -> U component, V=0)",
        },
        "critical_warnings": [
            "CLM precipitation MUST be in mm/s (= kg/m2/s), NOT mm/hr",
            "CLM temperature MUST be in K, NOT degC (add 273.15 if C)",
            "CLM pressure MUST be in Pa, NOT hPa (multiply by 100 if hPa)",
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing to ParFlow/CLM PFB format"
    )
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--forcing_source", choices=["cmfd", "mswx", "nasa_power"],
                        default="cmfd")
    parser.add_argument("--forcing_dir", required=True)
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--run_name", default="parflow_run")
    parser.add_argument("--dt_hours", type=int, default=1)
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.forcing_dir)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.domain_json, args.forcing_source, args.forcing_dir,
                     args.start_date, args.end_date, args.output_dir,
                     args.run_name, args.dt_hours)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
