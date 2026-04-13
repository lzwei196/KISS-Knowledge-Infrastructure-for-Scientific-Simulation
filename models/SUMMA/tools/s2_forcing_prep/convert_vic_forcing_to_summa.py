#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      convert_vic_forcing_to_summa
Stage:        s2_forcing_prep
Description:  Convert VIC ASCII forcing files (or raw CMFD/MSWX NetCDF) to
              SUMMA NetCDF forcing format.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  VIC precip (mm/timestep) -> SUMMA pptrate (kg/m2/s)
    - 3-hourly VIC: divide by 10800  (NOT 86400 -- see VIC CRITICAL_FIX)
    - Hourly VIC:   divide by 3600
    - 1 mm water = 1 kg/m2
  VIC temp (C)             -> SUMMA airtemp (K): add 273.15
  VIC pressure (kPa)       -> SUMMA airpres (Pa): multiply by 1000
  VIC specific humidity (kg/kg) -> SUMMA spechum (g/g): same value
    (kg/kg = g/g numerically, but verify units are mass ratio not mixing ratio)
  VIC shortwave (W/m2)     -> SUMMA SWRadAtm (W/m2): no conversion
  VIC longwave (W/m2)      -> SUMMA LWRadAtm (W/m2): no conversion
  VIC wind speed (m/s)     -> SUMMA windspd (m/s): no conversion

VIC forcing column order (7 columns):
  0: PREC (mm/timestep)
  1: TMAX (C) or T (C)
  2: TMIN (C)
  3: WIND (m/s)
  4: SHORTWAVE (W/m2)
  5: LONGWAVE (W/m2)
  6: PRESSURE (kPa)
  7: VP/QAIR (kPa or kg/kg)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIC_FORCING_DIR = ""
ATTRIBUTES_NC = ""
OUTPUT_DIR = ""
START_YEAR = 2000
END_YEAR = 2010
DATA_STEP = 10800        # seconds: 10800=3-hourly, 3600=hourly
VIC_FORCING_PREFIX = ""  # e.g., "basin_0.25deg_"
VIC_STEPS_PER_DAY = 8    # 8 for 3-hourly, 24 for hourly

# VIC column order — TWO common conventions:
# "hydrocraft" (default): AIR_TEMP, PREC, PRESSURE, SWDOWN, LWDOWN, VP, WIND (7 cols)
#   This is what HydroCraft's forcing_1d.py / process_forcing.py produce.
# "classic":              PREC, TMAX, TMIN, WIND, SW, LW, PRESSURE, QAIR (8 cols)
#   This is what some older VIC setups and the VIC documentation describe.
VIC_COLUMN_ORDER = "hydrocraft"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Convert VIC forcing to SUMMA format")
    parser.add_argument("--vic_forcing_dir", required=True)
    parser.add_argument("--attributes_nc", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--data_step", type=int, default=10800)
    parser.add_argument("--vic_prefix", default="")
    parser.add_argument("--steps_per_day", type=int, default=8)
    parser.add_argument("--column_order", default="hydrocraft",
                        choices=["hydrocraft", "classic"],
                        help="VIC forcing column order: 'hydrocraft' (AIR_TEMP,PREC,PRES,SW,LW,VP,WIND) "
                             "or 'classic' (PREC,TMAX,TMIN,WIND,SW,LW,PRES,QAIR)")
    args = parser.parse_args()
    VIC_FORCING_DIR = args.vic_forcing_dir
    ATTRIBUTES_NC = args.attributes_nc
    OUTPUT_DIR = args.output_dir
    START_YEAR = args.start_year
    END_YEAR = args.end_year
    VIC_COLUMN_ORDER = args.column_order
    DATA_STEP = args.data_step
    VIC_FORCING_PREFIX = args.vic_prefix
    VIC_STEPS_PER_DAY = args.steps_per_day


def validate_inputs():
    errors = []
    if not VIC_FORCING_DIR or not Path(VIC_FORCING_DIR).exists():
        errors.append(f"VIC forcing directory not found: {VIC_FORCING_DIR}")
    if not ATTRIBUTES_NC or not Path(ATTRIBUTES_NC).exists():
        errors.append(f"Attributes NetCDF not found: {ATTRIBUTES_NC}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if START_YEAR > END_YEAR:
        errors.append(f"START_YEAR ({START_YEAR}) > END_YEAR ({END_YEAR})")
    if DATA_STEP not in (3600, 10800):
        errors.append(f"DATA_STEP must be 3600 or 10800, got {DATA_STEP}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_files):
    errors = []
    for f in output_files:
        if not Path(f).exists():
            errors.append(f"Expected output not created: {f}")
        else:
            try:
                from netCDF4 import Dataset
                ds = Dataset(f, 'r')
                required = ['pptrate', 'airtemp', 'SWRadAtm', 'LWRadAtm',
                            'windspd', 'airpres', 'spechum']
                for var in required:
                    if var not in ds.variables:
                        errors.append(f"Missing variable {var} in {f}")
                # Check units
                if ds.variables['pptrate'].units != 'kg m-2 s-1':
                    errors.append(f"pptrate units should be 'kg m-2 s-1', got '{ds.variables['pptrate'].units}'")
                if ds.variables['airtemp'].units != 'K':
                    errors.append(f"airtemp units should be 'K', got '{ds.variables['airtemp'].units}'")
                if ds.variables['airpres'].units != 'Pa':
                    errors.append(f"airpres units should be 'Pa', got '{ds.variables['airpres'].units}'")
                ds.close()
            except Exception as e:
                errors.append(f"Cannot read {f}: {e}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Convert VIC forcing files to SUMMA NetCDF format."""
    from netCDF4 import Dataset, num2date, date2num

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Read attributes to get HRU info
    logger.info(f"Reading attributes: {ATTRIBUTES_NC}")
    attr_ds = Dataset(ATTRIBUTES_NC, 'r')
    hru_ids = attr_ds.variables['hruId'][:]
    lats = attr_ds.variables['latitude'][:]
    lons = attr_ds.variables['longitude'][:]
    n_hru = len(hru_ids)
    attr_ds.close()
    logger.info(f"Found {n_hru} HRUs")

    # Find VIC forcing files -- they are named like "prefix_lat_lon"
    vic_dir = Path(VIC_FORCING_DIR)
    vic_files = sorted(vic_dir.glob(f"{VIC_FORCING_PREFIX}*"))
    if not vic_files:
        # Try without prefix
        vic_files = sorted(f for f in vic_dir.iterdir()
                           if f.is_file() and not f.name.startswith('.'))
    logger.info(f"Found {len(vic_files)} VIC forcing files")

    if not vic_files:
        logger.error("No VIC forcing files found")
        sys.exit(2)

    # Map HRUs to VIC forcing files by lat/lon matching
    hru_to_file = {}
    for i in range(n_hru):
        lat_str = f"{lats[i]:.4f}"
        lon_str = f"{lons[i]:.4f}"
        # VIC naming convention: prefix_lat_lon
        matching = [f for f in vic_files if lat_str in f.name and lon_str in f.name]
        if matching:
            hru_to_file[i] = matching[0]
        else:
            # Try rounding
            lat_r = f"{round(lats[i], 4):.4f}"
            lon_r = f"{round(lons[i], 4):.4f}"
            matching = [f for f in vic_files if lat_r in f.name and lon_r in f.name]
            if matching:
                hru_to_file[i] = matching[0]
            else:
                logger.warning(f"No forcing file for HRU {hru_ids[i]} at ({lats[i]}, {lons[i]})")

    if not hru_to_file:
        logger.error("Could not match any HRU to VIC forcing files")
        sys.exit(2)

    # Process year by year
    output_files = []
    for year in range(START_YEAR, END_YEAR + 1):
        logger.info(f"Processing year {year}")

        # Determine number of time steps
        from calendar import isleap
        n_days = 366 if isleap(year) else 365
        n_steps = n_days * VIC_STEPS_PER_DAY

        # Create time array
        ref_time = datetime(year, 1, 1, 0, 0)
        time_values = np.array([i * DATA_STEP for i in range(n_steps)], dtype=np.float64)

        # Initialize arrays
        pptrate = np.full((n_steps, n_hru), 0.0, dtype=np.float64)
        airtemp = np.full((n_steps, n_hru), 273.15, dtype=np.float64)
        swrad = np.full((n_steps, n_hru), 0.0, dtype=np.float64)
        lwrad = np.full((n_steps, n_hru), 300.0, dtype=np.float64)
        windspd = np.full((n_steps, n_hru), 1.0, dtype=np.float64)
        airpres = np.full((n_steps, n_hru), 101325.0, dtype=np.float64)
        spechum = np.full((n_steps, n_hru), 0.005, dtype=np.float64)

        # Read VIC forcing for each HRU
        for hru_idx, vic_file in hru_to_file.items():
            try:
                data = np.loadtxt(vic_file)
                # Find rows for this year
                # VIC forcing has columns: PREC TMAX TMIN WIND SW LW PRESSURE QAIR
                # or fewer columns depending on configuration
                year_start = (year - START_YEAR) * n_days * VIC_STEPS_PER_DAY
                year_end = year_start + n_steps

                if year_end > len(data):
                    logger.warning(f"VIC file {vic_file.name} has only {len(data)} rows, "
                                   f"expected {year_end}")
                    year_end = min(year_end, len(data))
                    actual_steps = year_end - year_start
                else:
                    actual_steps = n_steps

                if year_start >= len(data):
                    logger.warning(f"Year {year} data not found in {vic_file.name}")
                    continue

                chunk = data[year_start:year_end]
                ncols = chunk.shape[1] if chunk.ndim > 1 else 1

                # CRITICAL: Column mapping depends on VIC configuration
                if VIC_COLUMN_ORDER == "hydrocraft":
                    # HydroCraft standard: AIR_TEMP(°C), PREC(mm/3hr), PRESSURE(kPa),
                    #                      SWDOWN(W/m²), LWDOWN(W/m²), VP(kPa), WIND(m/s)
                    # This is what forcing_1d.py + process_forcing.py produce.
                    airtemp[:actual_steps, hru_idx] = chunk[:, 0] + 273.15
                    pptrate[:actual_steps, hru_idx] = chunk[:, 1] / DATA_STEP
                    pres_pa = chunk[:, 2] * 1000.0  # kPa → Pa
                    airpres[:actual_steps, hru_idx] = pres_pa
                    swrad[:actual_steps, hru_idx] = np.maximum(chunk[:, 3], 0.0)
                    lwrad[:actual_steps, hru_idx] = np.maximum(chunk[:, 4], 0.0)
                    # VP (kPa) → specific humidity (kg/kg)
                    # q = 0.622 * e / (P - 0.378 * e), where e=VP and P are in same units
                    vp_pa = chunk[:, 5] * 1000.0  # kPa → Pa
                    spechum[:actual_steps, hru_idx] = np.maximum(
                        0.622 * vp_pa / (pres_pa - 0.378 * vp_pa), 1e-6)
                    if ncols >= 7:
                        windspd[:actual_steps, hru_idx] = np.maximum(chunk[:, 6], 0.1)
                else:
                    # Classic VIC 8-column: PREC(mm/ts), TMAX(°C), TMIN(°C), WIND(m/s),
                    #                       SW(W/m²), LW(W/m²), PRESSURE(kPa), QAIR(kg/kg)
                    pptrate[:actual_steps, hru_idx] = chunk[:, 0] / DATA_STEP
                    if ncols >= 3:
                        airtemp[:actual_steps, hru_idx] = celsius_to_kelvin((chunk[:, 1] + chunk[:, 2]) / 2)
                    elif ncols >= 2:
                        airtemp[:actual_steps, hru_idx] = chunk[:, 1] + 273.15
                    if ncols >= 4:
                        windspd[:actual_steps, hru_idx] = np.maximum(chunk[:, 3], 0.1)
                    if ncols >= 5:
                        swrad[:actual_steps, hru_idx] = np.maximum(chunk[:, 4], 0.0)
                    if ncols >= 6:
                        lwrad[:actual_steps, hru_idx] = np.maximum(chunk[:, 5], 0.0)
                    if ncols >= 7:
                        airpres[:actual_steps, hru_idx] = chunk[:, 6] * 1000.0
                    if ncols >= 8:
                        spechum[:actual_steps, hru_idx] = np.maximum(chunk[:, 7], 1e-6)

            except Exception as e:
                logger.warning(f"Error reading {vic_file.name}: {e}")

        # Write output NetCDF
        out_file = os.path.join(OUTPUT_DIR, f"forcing_{year}.nc")
        ds = Dataset(out_file, 'w', format='NETCDF4')

        # Dimensions
        ds.createDimension('time', None)  # unlimited
        ds.createDimension('hru', n_hru)

        # Time
        time_var = ds.createVariable('time', 'f8', ('time',))
        time_var.units = f'seconds since {year}-01-01 00:00'
        time_var.calendar = 'standard'
        time_var[:] = time_values

        # Data step
        ds_var = ds.createVariable('data_step', 'f8')
        ds_var[:] = DATA_STEP

        # HRU ID
        hru_var = ds.createVariable('hruId', 'i8', ('hru',))
        hru_var[:] = hru_ids

        # Forcing variables
        def create_var(name, data, units, long_name):
            v = ds.createVariable(name, 'f8', ('time', 'hru'), fill_value=-9999.0)
            v.units = units
            v.long_name = long_name
            v[:] = data
            return v

        create_var('pptrate', pptrate, 'kg m-2 s-1', 'Precipitation rate')
        create_var('airtemp', airtemp, 'K', 'Air temperature at measurement height')
        create_var('SWRadAtm', swrad, 'W m-2', 'Downward shortwave radiation at the upper boundary')
        create_var('LWRadAtm', lwrad, 'W m-2', 'Downward longwave radiation at the upper boundary')
        create_var('windspd', windspd, 'm s-1', 'Wind speed at measurement height')
        create_var('airpres', airpres, 'Pa', 'Air pressure at measurement height')
        create_var('spechum', spechum, 'g g-1', 'Specific humidity at measurement height')

        ds.history = f"Converted from VIC forcing by convert_vic_forcing_to_summa.py"
        ds.close()

        output_files.append(out_file)
        logger.info(f"  Written: {out_file} ({n_steps} timesteps x {n_hru} HRUs)")

    # Write forcing file list
    forcing_list = os.path.join(OUTPUT_DIR, "forcingFileList.txt")
    with open(forcing_list, 'w') as f:
        for of in output_files:
            f.write(f"'{os.path.basename(of)}'\n")
    logger.info(f"Forcing file list: {forcing_list}")

    print(json.dumps({
        "status": "success",
        "n_years": len(output_files),
        "n_hru": n_hru,
        "outputs": output_files,
        "forcing_list": forcing_list
    }))

    return output_files


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_files = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_files)
    sys.exit(0)
