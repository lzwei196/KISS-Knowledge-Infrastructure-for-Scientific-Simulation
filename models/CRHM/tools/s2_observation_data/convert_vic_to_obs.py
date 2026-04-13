#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      convert_vic_to_obs
Stage:        s2_observation_data
Description:  Convert VIC forcing files to CRHM .obs format with correct units.

CRITICAL UNIT CONVERSIONS (from PREFLIGHT.md -- unit errors are 37% of silent errors):

| Variable    | VIC forcing unit  | CRHM .obs unit    | Conversion              |
|-------------|-------------------|--------------------|-------------------------|
| Temperature | degrees C         | degrees C          | none                    |
| Precip      | mm (per timestep) | mm/d               | divide by hours * 24    |
| Wind        | m/s               | m/s                | none                    |
| SW Rad      | W/m2              | W/m2               | none                    |
| LW Rad      | W/m2              | W/m2               | none                    |
| Pressure    | kPa               | kPa                | none                    |
| Humidity    | kg/kg (specific)  | % (relative)       | CONVERSION REQUIRED     |

The most dangerous conversion is specific humidity (kg/kg) to relative
humidity (%). Getting this wrong produces no error but evapotranspiration
and sublimation calculations will be silently wrong.

VIC forcing columns — two supported formats:

  classic (original VIC format, 7 cols):
    0: precip (mm/timestep)
    1: t_max (C)
    2: t_min (C)
    3: wind (m/s)
    4: shortwave (W/m2)
    5: longwave (W/m2)
    6: pressure (kPa)

  mswx (MSWX/process_forcing.py output, 7 cols):
    0: air_temp (C)
    1: prec (mm/3hr, from kg/m2/s x 10800)
    2: pressure (kPa)
    3: swdown (W/m2)
    4: lwdown (W/m2)
    5: vp (kPa, actual vapour pressure)
    6: wind (m/s)

CRHM .obs format:
  Header line (description)
  Variable declarations: "varname n_columns (unit)"
  Computed variable declarations: "$varname formula (unit) description"
  Data: YYYY M D H 0 val1 val2 val3 ...

Inputs:
  --forcing_dir:  VIC forcing directory
  --grid_nc:      VIC basin grid NetCDF
  --output_path:  Output .obs file path
  --start_year:   Start year
  --end_year:     End year
  --timestep:     VIC timestep in hours (default: 3)

Outputs:
  .obs file compatible with CRHM

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
import math
from pathlib import Path
from datetime import datetime, timedelta
from ki_tools_common.humidity import saturation_vapor_pressure

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Convert VIC forcing to CRHM .obs")
    parser.add_argument("--forcing_dir", type=str, required=True, help="VIC forcing directory")
    parser.add_argument("--grid_nc", type=str, required=True, help="VIC grid NetCDF")
    parser.add_argument("--output_path", type=str, required=True, help="Output .obs file path")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--timestep", type=int, default=3, help="VIC timestep hours (default: 3)")
    parser.add_argument("--hru_index", type=int, default=0,
                        help="Which VIC grid cell to use (0=first, for single-HRU test)")
    parser.add_argument("--column_format", type=str, default="mswx",
                        choices=["classic", "mswx"],
                        help="VIC forcing column format: 'classic' (prec,tmax,tmin,wind,sw,lw,pres) "
                             "or 'mswx' (air_temp,prec_mm3hr,pres,sw,lw,vp,wind). Default: mswx")
    return parser.parse_args()


def specific_to_relative_humidity(q_kgkg, t_celsius, p_kpa):
    """
    Convert specific humidity (kg/kg) to relative humidity (%).

    CRITICAL: This is the most error-prone unit conversion in VIC-CRHM coupling.
    Formula: RH = (q * p) / (0.622 * es) * 100
    where es = 0.6108 * exp(17.27 * T / (T + 237.3)) [Tetens formula, kPa]  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure

    If you skip this conversion and pass specific humidity as-is, CRHM
    interprets tiny values (0.001-0.01) as 0.001-0.01% RH, making the
    atmosphere appear bone-dry. Sublimation goes to zero. SWE accumulates
    forever. This is a SILENT ERROR.
    """
    # Saturation vapor pressure (Tetens formula)
    es = saturation_vapor_pressure(t_celsius) / 10.0  # hPa -> kPa (ki_tools_common)

    # Actual vapor pressure from specific humidity
    # e = q * p / (0.622 + 0.378 * q)
    e = q_kgkg * p_kpa / (0.622 + 0.378 * q_kgkg)

    # Relative humidity
    rh = (e / es) * 100.0

    # Clamp to [0, 100]
    rh = max(0.0, min(100.0, rh))
    return rh


def validate_inputs(forcing_dir, grid_nc, output_path, start_year, end_year):
    errors = []

    if not Path(forcing_dir).is_dir():
        errors.append(f"Forcing directory not found: {forcing_dir}")

    if not Path(grid_nc).exists():
        errors.append(f"Grid NC file not found: {grid_nc}")

    if not output_path:
        errors.append("Output path not set")

    if start_year > end_year:
        errors.append(f"Start year ({start_year}) > end year ({end_year})")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def process(forcing_dir, grid_nc, output_path, start_year, end_year, timestep_hours, hru_index,
            column_format="mswx"):
    """
    Convert VIC forcing to CRHM .obs format.

    Steps:
    1. Read VIC grid NC to find grid cell coordinates
    2. Find the forcing file for the target grid cell
    3. Read all timesteps across all years
    4. Convert units (specific humidity -> relative humidity)
    5. Write .obs file with proper header
    """
    import numpy as np

    try:
        import xarray as xr
        ds = xr.open_dataset(grid_nc)
        lats = ds["lat"].values
        lons = ds["lon"].values
        ds.close()
    except Exception as e:
        logger.warning(f"Could not read grid_nc with xarray: {e}")
        logger.info("Falling back to scanning forcing directory for files")
        lats = []
        lons = []

    # Find forcing files
    forcing_path = Path(forcing_dir)
    forcing_files = sorted(forcing_path.glob("*"))
    forcing_files = [f for f in forcing_files if f.is_file() and not f.name.startswith(".")]

    if not forcing_files:
        logger.error(f"No forcing files found in {forcing_dir}")
        sys.exit(2)

    # Select the target forcing file
    if hru_index >= len(forcing_files):
        logger.warning(f"hru_index {hru_index} >= {len(forcing_files)} files, using first file")
        hru_index = 0

    target_file = forcing_files[hru_index]
    logger.info(f"Using forcing file: {target_file.name}")

    # Read forcing data
    # VIC forcing format: 7 columns, space-separated, no header
    # Col: precip(mm), tmax(C), tmin(C), wind(m/s), sw(W/m2), lw(W/m2), pressure(kPa)
    data = np.loadtxt(str(target_file))
    logger.info(f"Read {data.shape[0]} timesteps, {data.shape[1]} columns")

    if data.shape[1] < 7:
        logger.error(f"Expected 7 columns, got {data.shape[1]}. Is this a VIC forcing file?")
        sys.exit(2)

    # Generate datetime sequence
    steps_per_day = 24 // timestep_hours
    start_dt = datetime(start_year, 1, 1, timestep_hours, 0)  # first timestep
    n_steps = data.shape[0]

    expected_days = sum(
        366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365
        for y in range(start_year, end_year + 1)
    )
    expected_steps = expected_days * steps_per_day

    if n_steps != expected_steps:
        logger.warning(
            f"Expected {expected_steps} timesteps ({expected_days} days x {steps_per_day}/day), "
            f"got {n_steps}. Adjusting."
        )

    # Extract columns — format-dependent
    if column_format == "mswx":
        # MSWX / process_forcing.py output:
        # [air_temp(C), prec(mm/3hr), pressure(kPa), swdown(W/m2), lwdown(W/m2), vp(kPa), wind(m/s)]
        t_mean   = data[:, 0]   # C (single temperature)
        precip   = data[:, 1]   # mm/3hr
        pressure = data[:, 2]   # kPa
        sw_rad   = data[:, 3]   # W/m2
        lw_rad   = data[:, 4]   # W/m2
        vp       = data[:, 5]   # kPa (actual vapour pressure)
        wind     = data[:, 6]   # m/s

        # RH from vapour pressure: RH = vp / es(T) * 100
        rh = np.zeros(n_steps)
        for i in range(n_steps):
            T = t_mean[i]
            es = saturation_vapor_pressure(T) / 10.0  # hPa -> kPa (ki_tools_common)
            rh[i] = min(100.0, max(1.0, (vp[i] / es) * 100.0))

        # prec is mm/3hr — CRHM reads it as mm per timestep interval
        # DO NOT scale to daily rate — each row represents one timestep's actual precip
        precip_daily_rate = precip  # mm per timestep (3hr)

        # ea is the vp column directly (already in kPa)
        ea = vp

    else:
        # Classic VIC format:
        # [prec(mm/ts), tmax(C), tmin(C), wind(m/s), sw(W/m2), lw(W/m2), pressure(kPa)]
        precip   = data[:, 0]   # mm per timestep
        tmax     = data[:, 1]   # C
        tmin     = data[:, 2]   # C
        wind     = data[:, 3]   # m/s
        sw_rad   = data[:, 4]   # W/m2
        lw_rad   = data[:, 5]   # W/m2
        pressure = data[:, 6]   # kPa

        t_mean = (tmax + tmin) / 2.0

        # RH from tmin as dewpoint approximation
        rh = np.zeros(n_steps)
        for i in range(n_steps):
            es_tmin  = 0.6108 * math.exp(17.27 * tmin[i]   / (tmin[i]   + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
            es_tmean = 0.6108 * math.exp(17.27 * t_mean[i] / (t_mean[i] + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
            rh[i] = min(100.0, max(5.0, (es_tmin / es_tmean) * 100.0))

        # prec is mm/timestep — write as-is, not scaled to daily rate
        precip_daily_rate = precip  # mm per timestep
        ea = np.array([0.6108 * math.exp(17.27 * tmin[i] / (tmin[i] + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
                       for i in range(n_steps)])

    # Write .obs file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        # Header line
        f.write(f"Converted from VIC forcing ({target_file.name})\n")

        # Variable declarations
        f.write("t 1 (C)\n")
        f.write("rh 1 (%)\n")
        f.write("u 1 (m/s)\n")
        f.write(f"ppt 1 (mm/{timestep_hours}hr)\n")
        f.write("Qsi 1 (W/m^2)\n")
        f.write("Qli 1 (W/m^2)\n")
        f.write("p 1 (kPa)\n")
        f.write("$ea ea(t, rh) (kPa) vapour pressure\n")

        # Data rows
        dt = start_dt
        for i in range(n_steps):
            row = (
                f"{dt.year} {dt.month} {dt.day} {dt.hour} 0 "
                f"{t_mean[i]:.2f} {rh[i]:.1f} {wind[i]:.2f} "
                f"{precip_daily_rate[i]:.3f} {sw_rad[i]:.1f} {lw_rad[i]:.1f} "
                f"{pressure[i]:.3f}\n"
            )
            f.write(row)
            dt += timedelta(hours=timestep_hours)

    logger.info(f"Wrote {n_steps} timesteps to {output_file}")
    logger.info(f"Period: {start_dt} to {dt - timedelta(hours=timestep_hours)}")

    return str(output_file)


def validate_outputs(output_path):
    errors = []

    p = Path(output_path)
    if not p.exists():
        errors.append(f"Output file not created: {output_path}")
    elif p.stat().st_size == 0:
        errors.append("Output file is empty")
    else:
        with open(p) as f:
            lines = f.readlines()
        if len(lines) < 10:
            errors.append(f"Output file has only {len(lines)} lines -- too few")

        # Check header structure
        has_t = any("t " in line and "(C)" in line for line in lines[:10])
        has_ppt = any("ppt " in line and "(mm" in line for line in lines[:10])
        if not has_t:
            errors.append("Header missing temperature variable declaration")
        if not has_ppt:
            errors.append("Header missing precipitation variable declaration")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.forcing_dir, args.grid_nc, args.output_path,
                    args.start_year, args.end_year)

    try:
        output_path = process(
            args.forcing_dir, args.grid_nc, args.output_path,
            args.start_year, args.end_year, args.timestep, args.hru_index,
            column_format=args.column_format
        )
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
