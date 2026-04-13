#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      convert_forcing_to_mhm
Stage:        s4_forcing
Description:  Convert CMFD or MSWX forcing data to mHM-compatible NetCDF format.

mHM expects meteorological forcing as NetCDF files with:
  - Dimensions: (time, lat, lon) -- using CF conventions
  - One directory per variable: pre/, tavg/, pet/ (or tmin/, tmax/ for Hargreaves)
  - One file per year per variable (e.g., pre_2005.nc)
  - Daily timestep
  - Time encoding: "days since YYYY-01-01"

UNIT CONVERSIONS (CRITICAL -- silent errors if wrong):
  CMFD:
    - Precipitation: mm/3hr -> mm/day (sum 8 timesteps)
    - Temperature: Kelvin -> degrees Celsius (subtract 273.15)
  MSWX:
    - Precipitation: mm/3hr -> mm/day (sum 8 timesteps)
    - Temperature: already in Celsius
  Both:
    - PET: if pre-computed, must be in mm/day

Inputs:
  - CONFIG_PATH: config.json from s0
  - DOMAIN_INFO_PATH: domain_info.json from s1
  - FORCING_SOURCE_DIR: path to CMFD or MSWX raw data
  - PET_METHOD: 0 (input PET), 1 (Hargreaves needs tmin/tmax)

Outputs:
  - NetCDF files in input/meteo/pre/, input/meteo/tavg/, etc.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

try:
    import xarray as xr
    import rasterio
    from rasterio.transform import from_bounds
except ImportError as e:
    print(f"ERROR: Required: xarray, rasterio. {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
FORCING_SOURCE_DIR = ""
PET_METHOD = 0  # 0=input PET, 1=Hargreaves

# CMFD variable mapping
CMFD_VAR_MAP = {
    "pre": {"file_pattern": "prec_CMFD_V0106_B-01_01hr_010deg_{year}{month:02d}.nc",
            "var_name": "prec", "unit_conv": "sum_3hr_to_daily", "temp_offset": 0},
    "tavg": {"file_pattern": "temp_CMFD_V0106_B-01_01hr_010deg_{year}{month:02d}.nc",
             "var_name": "temp", "unit_conv": "K_to_C_daily_mean", "temp_offset": -273.15},
}

# MSWX variable mapping
MSWX_VAR_MAP = {
    "pre": {"file_pattern": "P3h_MSWX_{year}.nc",
            "var_name": "precipitation", "unit_conv": "sum_3hr_to_daily"},
    "tavg": {"file_pattern": "Temp_MSWX_{year}.nc",
             "var_name": "air_temperature", "unit_conv": "mean_3hr_to_daily"},
}

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Convert forcing to mHM format")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--forcing_dir", required=True)
    parser.add_argument("--pet_method", type=int, default=0)
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    FORCING_SOURCE_DIR = args.forcing_dir
    PET_METHOD = args.pet_method

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def clip_and_aggregate(ds, var_name, bounds, cellsize, agg_method="sum"):
    """Clip a dataset to domain bounds and aggregate sub-daily to daily."""
    minx, miny, maxx, maxy = bounds

    # Find lat/lon dimension names
    lat_name = None
    lon_name = None
    for dim in ds.dims:
        if dim.lower() in ('lat', 'latitude', 'y'):
            lat_name = dim
        elif dim.lower() in ('lon', 'longitude', 'x'):
            lon_name = dim

    if lat_name is None or lon_name is None:
        # Try coordinate names
        for coord in ds.coords:
            if coord.lower() in ('lat', 'latitude'):
                lat_name = coord
            elif coord.lower() in ('lon', 'longitude'):
                lon_name = coord

    if lat_name is None or lon_name is None:
        raise ValueError(f"Cannot find lat/lon dimensions. Dims: {list(ds.dims)}, Coords: {list(ds.coords)}")

    # Clip spatially with buffer
    buf = cellsize * 2
    lat_sel = (ds[lat_name] >= miny - buf) & (ds[lat_name] <= maxy + buf)
    lon_sel = (ds[lon_name] >= minx - buf) & (ds[lon_name] <= maxx + buf)
    ds_clip = ds.where(lat_sel & lon_sel, drop=True)

    if var_name in ds_clip:
        var = ds_clip[var_name]
    else:
        # Try first data variable
        var = ds_clip[list(ds_clip.data_vars)[0]]

    # Aggregate to daily
    if 'time' in var.dims and len(var.time) > 366:
        if agg_method == "sum":
            var_daily = var.resample(time="1D").sum(dim="time")
        elif agg_method == "mean":
            var_daily = var.resample(time="1D").mean(dim="time")
        else:
            var_daily = var
    else:
        var_daily = var

    return var_daily


def write_mhm_forcing_nc(data, lats, lons, times, var_name, output_path, units="mm/day"):
    """Write mHM-compatible forcing NetCDF file."""
    # Sort lats descending (north to south) as mHM expects
    if len(lats) > 1 and lats[0] < lats[-1]:
        lats = lats[::-1]
        data = data[:, ::-1, :]

    ds = xr.Dataset(
        {var_name: (["time", "lat", "lon"], data.astype(np.float32))},
        coords={
            "time": times,
            "lat": lats.astype(np.float64),
            "lon": lons.astype(np.float64),
        },
    )
    ds[var_name].attrs["units"] = units
    ds[var_name].attrs["long_name"] = var_name
    ds.time.encoding["units"] = f"days since {pd.Timestamp(times[0]).year}-01-01"
    ds.time.encoding["calendar"] = "standard"

    ds.to_netcdf(output_path)
    logger.info(f"Written: {output_path} ({len(times)} timesteps)")


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if not FORCING_SOURCE_DIR or not Path(FORCING_SOURCE_DIR).exists():
        errors.append(f"Forcing source dir not found: {FORCING_SOURCE_DIR}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))

    start_year = config["start_year"]
    end_year = config["end_year"]
    forcing_dataset = config["forcing_dataset"]
    bounds = domain_info["bounds"]
    cs = domain_info["header_L0"]["cellsize"]
    output_base = Path(config["output_dir"]) / "input" / "meteo"

    # Determine variables to process
    # CRITICAL: mHM always needs tavg (for temperature-dependent processes).
    # For Hargreaves PET (method 1), also need tmin/tmax.
    if PET_METHOD == 0:
        variables = ["pre", "tavg", "pet"]
    elif PET_METHOD == 1:
        variables = ["pre", "tavg", "tmin", "tmax"]  # tavg computed from (tmin+tmax)/2 if not available
    else:
        variables = ["pre", "tavg"]

    n_files = 0
    source_dir = Path(FORCING_SOURCE_DIR)

    for var in variables:
        out_dir = output_base / var
        out_dir.mkdir(parents=True, exist_ok=True)

        for year in range(start_year, end_year + 1):
            logger.info(f"Processing {var} for {year}...")

            # Find source files
            if forcing_dataset == "CMFD":
                # CMFD has monthly files in per-variable subdirectories
                # Map mHM variable names to CMFD file prefixes
                cmfd_var_map = {
                    "pre": "prec", "tavg": "temp", "tmin": "temp", "tmax": "temp",
                    "pet": "temp",  # compute from temp if needed
                }
                cmfd_prefix = cmfd_var_map.get(var, var)
                yearly_data = []
                yearly_times = []
                for month in range(1, 13):
                    # Use variable-specific pattern to avoid matching all 8 CMFD vars
                    files = sorted(source_dir.glob(f"**/{cmfd_prefix}*{year}{month:02d}*.nc"))
                    if not files:
                        # Fallback: try generic but that risks matching wrong vars
                        files = sorted(source_dir.glob(f"**/*{year}{month:02d}*.nc"))
                        if len(files) > 1:
                            # Filter to keep only the right variable
                            files = [f for f in files if cmfd_prefix in f.name.lower()]

                    for fp in files:
                        try:
                            ds = xr.open_dataset(fp)
                            clipped = clip_and_aggregate(
                                ds, list(ds.data_vars)[0], bounds, cs,
                                "sum" if var == "pre" else "mean"
                            )
                            yearly_data.append(clipped)
                        except Exception as e:
                            logger.warning(f"Skip {fp}: {e}")

                if yearly_data:
                    combined = xr.concat(yearly_data, dim="time")

                    # Apply unit conversions BEFORE aggregation
                    if var in ["tavg", "tmin", "tmax"] and forcing_dataset == "CMFD":
                        combined = combined - 273.15  # K -> C
                        logger.info(f"  Converted K -> C for {var}")
                    if var == "pre" and forcing_dataset == "CMFD":
                        # CMFD precip is in kg/m2/s (= mm/s). Multiply by 10800
                        # (seconds per 3hr period) to get mm/3hr per timestep
                        combined = combined * 10800.0
                        logger.info(f"  Converted kg/m2/s -> mm/3hr (×10800)")

                    # Aggregate sub-daily to daily
                    if 'time' in combined.dims and len(combined.time) > 366:
                        if var == "pre":
                            combined = combined.resample(time="1D").sum(dim="time")
                        elif var == "tmin":
                            combined = combined.resample(time="1D").min(dim="time")
                        elif var == "tmax":
                            combined = combined.resample(time="1D").max(dim="time")
                        else:  # tavg
                            combined = combined.resample(time="1D").mean(dim="time")
                        logger.info(f"  Aggregated to daily: {len(combined.time)} timesteps")

                    data = combined.values
                    lats = combined.lat.values if 'lat' in combined.coords else combined.latitude.values
                    lons = combined.lon.values if 'lon' in combined.coords else combined.longitude.values
                    times = combined.time.values

                    out_file = out_dir / f"{var}_{year}.nc"
                    write_mhm_forcing_nc(
                        data, lats, lons,
                        [np.datetime64(t) for t in times],
                        var, str(out_file),
                        "mm/day" if var == "pre" else "degC"
                    )
                    n_files += 1

            elif forcing_dataset == "MSWX":
                # MSWX has yearly files
                if var == "pre":
                    pattern = f"P3h*{year}*.nc"
                elif var == "tavg":
                    pattern = f"Temp*{year}*.nc"
                elif var == "tmin":
                    pattern = f"Tmin*{year}*.nc"
                elif var == "tmax":
                    pattern = f"Tmax*{year}*.nc"
                else:
                    pattern = f"*{var}*{year}*.nc"

                files = sorted(source_dir.glob(f"**/{pattern}"))
                if files:
                    ds = xr.open_dataset(files[0])
                    clipped = clip_and_aggregate(
                        ds, list(ds.data_vars)[0], bounds, cs,
                        "sum" if var == "pre" else "mean"
                    )
                    data = clipped.values
                    lats = clipped.lat.values if 'lat' in clipped.coords else clipped.latitude.values
                    lons = clipped.lon.values if 'lon' in clipped.coords else clipped.longitude.values
                    times = clipped.time.values

                    out_file = out_dir / f"{var}_{year}.nc"
                    write_mhm_forcing_nc(
                        data, lats, lons,
                        [np.datetime64(t) for t in times],
                        var, str(out_file),
                        "mm/day" if var == "pre" else "degC"
                    )
                    n_files += 1
                else:
                    logger.warning(f"No MSWX files found for {var} {year}: {pattern}")

    # Generate header.txt for each variable directory
    # CRITICAL: mHM computes L2 (forcing level) grid from L0 extent and forcing cellsize.
    # The header.txt must match EXACTLY what mHM expects.
    # mHM's L2: ncols_L2 = ceil(ncols_L0 * cs_L0 / cs_forcing) + 1
    #            nrows_L2 = ceil(nrows_L0 * cs_L0 / cs_forcing) + 1
    #            xll_L2 = floor(xll_L0 / cs_forcing) * cs_forcing
    #            yll_L2 = floor(yll_L0 / cs_forcing) * cs_forcing
    import math
    h0 = domain_info["header_L0"]
    cs_f = 0.1  # CMFD/MSWX native resolution
    xll_L2 = math.floor(h0["xllcorner"] / cs_f) * cs_f
    yll_L2 = math.floor(h0["yllcorner"] / cs_f) * cs_f
    xur_L0 = h0["xllcorner"] + h0["ncols"] * h0["cellsize"]
    yur_L0 = h0["yllcorner"] + h0["nrows"] * h0["cellsize"]
    ncols_L2 = int(math.ceil((xur_L0 - xll_L2) / cs_f))
    nrows_L2 = int(math.ceil((yur_L0 - yll_L2) / cs_f))

    for var in variables:
        header_path = output_base / var / "header.txt"
        with open(header_path, "w") as f:
            f.write(f"ncols         {ncols_L2}\n")
            f.write(f"nrows         {nrows_L2}\n")
            f.write(f"xllcorner     {xll_L2:.6f}\n")
            f.write(f"yllcorner     {yll_L2:.6f}\n")
            f.write(f"cellsize      {cs_f}\n")
            f.write(f"NODATA_value  -9999\n")
        logger.info(f"  header.txt for {var}: {ncols_L2}x{nrows_L2}, xll={xll_L2:.2f}, yll={yll_L2:.2f}")

    result = {
        "status": "success",
        "forcing_dir": str(output_base),
        "n_files": n_files,
        "variables": variables,
        "period": f"{start_year}-{end_year}",
        "L2_grid": {"ncols": ncols_L2, "nrows": nrows_L2, "xll": xll_L2, "yll": yll_L2, "cs": cs_f},
    }
    print(json.dumps(result, indent=2))
    return str(output_base)


def validate_outputs(output_path):
    meteo_dir = Path(output_path)
    # Check at least pre directory exists with files
    pre_dir = meteo_dir / "pre"
    if not pre_dir.exists() or not list(pre_dir.glob("*.nc")):
        logger.error(f"No precipitation files in {pre_dir}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
