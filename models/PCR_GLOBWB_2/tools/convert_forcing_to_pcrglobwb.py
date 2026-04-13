#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Forcing Converter
===============================
Converts global meteorological forcing data (ERA5, CMFD, CRU, W5E5) to
PCR-GLOBWB 2 NetCDF format with correct units and variable naming.

Pipeline stage: s2 (Forcing Preparation)
Pattern: validate_inputs → process → validate_outputs

PCR-GLOBWB expects:
  - precipitation:  m/day  (NOT mm/day)
  - temperature:    degrees Celsius (NOT Kelvin)
  - referencePotET: m/day  (NOT mm/day)
  - NetCDF variable names: 'precipitation', 'temperature', 'referencePotET'

Unit conversion traps:
  dt_001: Precipitation must be m/day, not mm/day (divide by 1000)
  dt_002: Temperature must be Celsius, not Kelvin (subtract 273.15)
  dt_003: Reference ET must be m/day, not mm/day (divide by 1000)
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(precip_nc, temp_nc, refet_nc, source_format):
    """Validate that input files exist and source format is recognized."""
    errors = []

    for label, path in [("Precipitation", precip_nc), ("Temperature", temp_nc)]:
        if path and not os.path.exists(path):
            errors.append(f"{label} file not found: {path}")

    if refet_nc and not os.path.exists(refet_nc):
        errors.append(f"Reference ET file not found: {refet_nc}")

    valid_sources = ["era5", "cmfd", "cru_era_interim", "w5e5", "custom"]
    if source_format not in valid_sources:
        errors.append(f"Unknown source format '{source_format}'. Valid: {valid_sources}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    logger.info("Input validation passed.")
    return True


def validate_outputs(output_dir, start_date, end_date):
    """Validate output NetCDF files have correct units and ranges."""
    warnings = []
    errors = []

    precip_file = os.path.join(output_dir, "precipitation.nc")
    temp_file = os.path.join(output_dir, "temperature.nc")
    refet_file = os.path.join(output_dir, "referencePotET.nc")

    if nc is None:
        logger.warning("netCDF4 not available; skipping output validation.")
        return True

    # Check precipitation (m/day)
    if os.path.exists(precip_file):
        with nc.Dataset(precip_file, "r") as ds:
            if "precipitation" not in ds.variables:
                errors.append("dt_009: Variable 'precipitation' not found in output")
            else:
                data = ds.variables["precipitation"][:]
                max_val = float(np.nanmax(data))
                if max_val > 1.0:
                    warnings.append(
                        f"dt_001: Max precipitation = {max_val:.4f} m/day — "
                        f"suspiciously high. Likely still in mm/day?"
                    )
                if max_val < 1e-6:
                    warnings.append("Precipitation all zeros — check input file")
                logger.info(f"Precipitation range: {float(np.nanmin(data)):.6f} to {max_val:.6f} m/day")

    # Check temperature (Celsius)
    if os.path.exists(temp_file):
        with nc.Dataset(temp_file, "r") as ds:
            if "temperature" not in ds.variables:
                errors.append("dt_009: Variable 'temperature' not found in output")
            else:
                data = ds.variables["temperature"][:]
                min_val = float(np.nanmin(data))
                max_val = float(np.nanmax(data))
                if max_val > 100:
                    errors.append(
                        f"dt_002: Max temperature = {max_val:.1f} — "
                        f"likely still in Kelvin. Subtract 273.15"
                    )
                logger.info(f"Temperature range: {min_val:.1f} to {max_val:.1f} deg C")

    # Check reference ET (m/day)
    if os.path.exists(refet_file):
        with nc.Dataset(refet_file, "r") as ds:
            varname = None
            for vn in ["referencePotET", "evapotranspiration"]:
                if vn in ds.variables:
                    varname = vn
                    break
            if varname is None:
                errors.append("dt_009: Neither 'referencePotET' nor 'evapotranspiration' found in output")
            else:
                data = ds.variables[varname][:]
                max_val = float(np.nanmax(data))
                if max_val > 0.1:
                    warnings.append(
                        f"dt_003: Max refET = {max_val:.4f} m/day — "
                        f"suspiciously high. Likely still in mm/day?"
                    )
                logger.info(f"Reference ET range: {float(np.nanmin(data)):.6f} to {max_val:.6f} m/day")

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        raise ValueError(f"Output validation failed: {len(errors)} error(s)")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# Conversion functions per source
# ---------------------------------------------------------------------------

def _get_unit_conversions(source_format):
    """Return conversion factors for each source format.

    Returns dict with keys: precip_factor, precip_offset,
    temp_factor, temp_offset, et_factor, et_offset.
    """
    conversions = {
        "era5": {
            "precip_factor": 1.0 / 1000.0,   # mm/day -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,           # K -> C
            "et_factor": 1.0 / 1000.0,       # mm/day -> m/day
            "et_offset": 0.0,
            "precip_varname": "tp",
            "temp_varname": "t2m",
            "et_varname": "pev",
        },
        "cmfd": {
            "precip_factor": 1.0 / 1000.0,   # mm/day -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,           # K -> C
            "et_factor": 1.0 / 1000.0,
            "et_offset": 0.0,
            "precip_varname": "prcp",
            "temp_varname": "temp",
            "et_varname": "pet",
        },
        "cru_era_interim": {
            "precip_factor": 1.0,             # already m/day in CRU-ERA
            "precip_offset": 0.0,
            "temp_factor": 1.0,               # already Celsius
            "temp_offset": 0.0,
            "et_factor": 1.0,                 # already m/day
            "et_offset": 0.0,
            "precip_varname": "precipitation",
            "temp_varname": "temperature",
            "et_varname": "referencePotET",
        },
        "w5e5": {
            "precip_factor": 86400.0 / 1000.0,  # kg/m2/s -> m/day
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": -273.15,              # K -> C
            "et_factor": 1.0 / 1000.0,          # mm/day -> m/day
            "et_offset": 0.0,
            "precip_varname": "pr",
            "temp_varname": "tas",
            "et_varname": "evspsblpot",
        },
        "custom": {
            "precip_factor": 1.0 / 1000.0,
            "precip_offset": 0.0,
            "temp_factor": 1.0,
            "temp_offset": 0.0,
            "et_factor": 1.0 / 1000.0,
            "et_offset": 0.0,
            "precip_varname": "precipitation",
            "temp_varname": "temperature",
            "et_varname": "referencePotET",
        },
    }
    return conversions[source_format]


def convert_variable(input_nc, output_nc, src_varname, dst_varname,
                     factor, offset, units, long_name):
    """Read a variable from input NetCDF, apply factor+offset, write to output.

    output = input * factor + offset
    """
    if nc is None:
        raise ImportError("netCDF4 is required for conversion")

    with nc.Dataset(input_nc, "r") as src:
        if src_varname not in src.variables:
            available = list(src.variables.keys())
            raise KeyError(
                f"Variable '{src_varname}' not found in {input_nc}. "
                f"Available: {available}"
            )

        src_var = src.variables[src_varname]
        data = src_var[:]

        # Apply conversion
        data = data * factor + offset

        # Ensure precipitation and ET are non-negative
        if "precip" in dst_varname.lower() or "et" in dst_varname.lower() or "evap" in dst_varname.lower():
            data = np.maximum(data, 0.0)

        # Get dimensions
        time_var = src.variables.get("time")
        lat_var = src.variables.get("lat", src.variables.get("latitude"))
        lon_var = src.variables.get("lon", src.variables.get("longitude"))

        # Create output
        with nc.Dataset(output_nc, "w", format="NETCDF4") as dst:
            # Copy dimensions
            for dim_name, dim in src.dimensions.items():
                dst.createDimension(dim_name, len(dim) if not dim.isunlimited() else None)

            # Copy coordinate variables
            if time_var is not None:
                t = dst.createVariable("time", time_var.dtype, time_var.dimensions)
                t[:] = time_var[:]
                for attr in time_var.ncattrs():
                    t.setncattr(attr, time_var.getncattr(attr))

            if lat_var is not None:
                lat_name = "lat" if "lat" in src.variables else "latitude"
                la = dst.createVariable(lat_name, lat_var.dtype, lat_var.dimensions)
                la[:] = lat_var[:]
                for attr in lat_var.ncattrs():
                    la.setncattr(attr, lat_var.getncattr(attr))

            if lon_var is not None:
                lon_name = "lon" if "lon" in src.variables else "longitude"
                lo = dst.createVariable(lon_name, lon_var.dtype, lon_var.dimensions)
                lo[:] = lon_var[:]
                for attr in lon_var.ncattrs():
                    lo.setncattr(attr, lon_var.getncattr(attr))

            # Write converted data
            out_var = dst.createVariable(
                dst_varname, "f4", src_var.dimensions,
                fill_value=1e20, zlib=True
            )
            out_var[:] = data
            out_var.units = units
            out_var.long_name = long_name

            # Global attributes
            dst.description = f"PCR-GLOBWB 2 forcing: {dst_varname}"
            dst.history = f"Converted on {datetime.now().isoformat()}"
            dst.source = f"Original: {input_nc}"

    logger.info(f"Converted {src_varname} -> {dst_varname} in {output_nc}")
    logger.info(f"  Factor={factor}, Offset={offset}, Units={units}")


# ---------------------------------------------------------------------------
# Main process
# ---------------------------------------------------------------------------

def process(precip_nc, temp_nc, refet_nc, output_dir, source_format,
            start_date=None, end_date=None):
    """Convert forcing data from source format to PCR-GLOBWB format.

    Args:
        precip_nc: Path to precipitation NetCDF
        temp_nc: Path to temperature NetCDF
        refet_nc: Path to reference ET NetCDF (optional)
        output_dir: Output directory for converted files
        source_format: One of 'era5', 'cmfd', 'cru_era_interim', 'w5e5', 'custom'
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    os.makedirs(output_dir, exist_ok=True)

    conv = _get_unit_conversions(source_format)

    # Precipitation
    if precip_nc:
        logger.info(f"Converting precipitation from {source_format} format...")
        convert_variable(
            precip_nc,
            os.path.join(output_dir, "precipitation.nc"),
            conv["precip_varname"], "precipitation",
            conv["precip_factor"], conv["precip_offset"],
            "m.day-1", "daily precipitation"
        )

    # Temperature
    if temp_nc:
        logger.info(f"Converting temperature from {source_format} format...")
        convert_variable(
            temp_nc,
            os.path.join(output_dir, "temperature.nc"),
            conv["temp_varname"], "temperature",
            conv["temp_factor"], conv["temp_offset"],
            "degrees Celsius", "mean daily air temperature"
        )

    # Reference ET
    if refet_nc:
        logger.info(f"Converting reference ET from {source_format} format...")
        convert_variable(
            refet_nc,
            os.path.join(output_dir, "referencePotET.nc"),
            conv["et_varname"], "referencePotET",
            conv["et_factor"], conv["et_offset"],
            "m.day-1", "daily reference potential evapotranspiration"
        )

    logger.info(f"All conversions complete. Output in: {output_dir}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing to PCR-GLOBWB 2 format"
    )
    parser.add_argument("--precip", required=True, help="Precipitation NetCDF file")
    parser.add_argument("--temp", required=True, help="Temperature NetCDF file")
    parser.add_argument("--refet", default=None, help="Reference ET NetCDF file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--source", required=True,
        choices=["era5", "cmfd", "cru_era_interim", "w5e5", "custom"],
        help="Source data format"
    )
    parser.add_argument("--start-date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="End date (YYYY-MM-DD)")

    args = parser.parse_args()

    # Validate → Process → Validate
    validate_inputs(args.precip, args.temp, args.refet, args.source)
    process(args.precip, args.temp, args.refet, args.output_dir,
            args.source, args.start_date, args.end_date)
    validate_outputs(args.output_dir, args.start_date, args.end_date)


if __name__ == "__main__":
    main()
