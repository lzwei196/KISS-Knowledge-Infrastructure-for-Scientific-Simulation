#!/usr/bin/env python3
"""
convert_climate_forcing.py — Convert global reanalysis climate data to PISM forcing format.

Converts atmospheric forcing data (temperature, precipitation) from common reanalysis
products (ERA5, NCEP, CRU) into PISM-compatible NetCDF forcing files. Handles the
critical unit conversions that cause silent model failures:

  - Temperature: °C → kelvin (add 273.15)
  - Precipitation: m w.e./year → kg m^-2 year^-1 (multiply by 1000)
  - Precipitation: mm/day → kg m^-2 year^-1 (multiply by 365.25)

Usage:
    python convert_climate_forcing.py \\
        --input era5_monthly.nc \\
        --output pism_climate_forcing.nc \\
        --temp-var t2m --precip-var tp \\
        --temp-units celsius --precip-units "m_we/year" \\
        --calendar 365_day \\
        [--output-json result.json]
"""

import argparse
import json
import os
import sys

try:
    import numpy as np
    from netCDF4 import Dataset
except ImportError as e:
    print(json.dumps({
        "status": "error",
        "errors": [f"Missing dependency: {e}. Install with: pip install numpy netCDF4"]
    }))
    sys.exit(1)


TEMP_CONVERSIONS = {
    "kelvin":    lambda x: x,
    "celsius":   lambda x: x + 273.15,
    "fahrenheit": lambda x: (x - 32) * 5.0 / 9.0 + 273.15,
}

PRECIP_CONVERSIONS = {
    "kg_m-2_year-1": lambda x: x,
    "m_we/year":     lambda x: x * 1000.0,
    "mm/day":        lambda x: x * 365.25,
    "mm/month":      lambda x: x * 12.0,
    "m/s":           lambda x: x * 1000.0 * 86400.0 * 365.25,
    "kg_m-2_s-1":    lambda x: x * 86400.0 * 365.25,
}


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        try:
            ds = Dataset(args.input, "r")
            if args.temp_var and args.temp_var not in ds.variables:
                errors.append(f"Temperature variable '{args.temp_var}' not found in input. "
                              f"Available: {list(ds.variables.keys())}")
            if args.precip_var and args.precip_var not in ds.variables:
                errors.append(f"Precipitation variable '{args.precip_var}' not found in input. "
                              f"Available: {list(ds.variables.keys())}")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot open input file: {e}")

    if args.temp_units not in TEMP_CONVERSIONS:
        errors.append(f"Unknown temperature units: '{args.temp_units}'. "
                      f"Supported: {list(TEMP_CONVERSIONS.keys())}")

    if args.precip_units not in PRECIP_CONVERSIONS:
        errors.append(f"Unknown precipitation units: '{args.precip_units}'. "
                      f"Supported: {list(PRECIP_CONVERSIONS.keys())}")

    valid_calendars = ["365_day", "360_day", "standard", "gregorian",
                       "proleptic_gregorian", "noleap", "julian"]
    if args.calendar not in valid_calendars:
        errors.append(f"Invalid calendar: '{args.calendar}'. Supported: {valid_calendars}")

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)


def process(args):
    """Convert climate data to PISM format."""
    src = Dataset(args.input, "r")
    warnings = []

    # Detect dimensions
    time_dim = None
    x_dim = None
    y_dim = None
    for dname in src.dimensions:
        dl = dname.lower()
        if dl in ("time", "t"):
            time_dim = dname
        elif dl in ("x", "rlon", "lon", "longitude"):
            x_dim = dname
        elif dl in ("y", "rlat", "lat", "latitude"):
            y_dim = dname

    if time_dim is None:
        warnings.append("No time dimension found; creating single-time-step output")
    if x_dim is None or y_dim is None:
        # Try to find spatial dims from variable
        for vname in [args.temp_var, args.precip_var]:
            if vname and vname in src.variables:
                dims = src.variables[vname].dimensions
                if len(dims) >= 2:
                    if y_dim is None:
                        y_dim = dims[-2]
                    if x_dim is None:
                        x_dim = dims[-1]

    # Create output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    dst = Dataset(args.output, "w", format="NETCDF4")

    # Copy dimensions
    for dname in src.dimensions:
        size = len(src.dimensions[dname])
        is_unlimited = src.dimensions[dname].isunlimited()
        dst.createDimension(dname, None if is_unlimited else size)

    # Copy coordinate variables
    for vname in src.variables:
        if vname in [args.temp_var, args.precip_var]:
            continue
        v = src.variables[vname]
        if len(v.dimensions) <= 1:
            out_v = dst.createVariable(vname, v.datatype, v.dimensions)
            out_v[:] = v[:]
            for attr in v.ncattrs():
                out_v.setncattr(attr, v.getncattr(attr))

    # Ensure time has correct calendar
    if time_dim and time_dim in dst.variables:
        dst.variables[time_dim].setncattr("calendar", args.calendar)

    # Convert temperature
    converted_vars = []
    if args.temp_var and args.temp_var in src.variables:
        src_temp = src.variables[args.temp_var]
        converter = TEMP_CONVERSIONS[args.temp_units]
        temp_data = converter(np.array(src_temp[:], dtype=np.float64))

        # Validate converted values
        if np.any(temp_data < 100):
            warnings.append(f"WARNING: Converted temperature has values < 100 K "
                            f"(min={temp_data.min():.1f}). "
                            f"Likely still in Celsius — check --temp-units.")
        if np.any(temp_data > 350):
            warnings.append(f"WARNING: Converted temperature has values > 350 K "
                            f"(max={temp_data.max():.1f}). "
                            f"Possible double-conversion from Celsius.")

        out_name = "air_temp"
        out_v = dst.createVariable(out_name, "f8", src_temp.dimensions,
                                   fill_value=1e20)
        out_v[:] = temp_data
        out_v.units = "kelvin"
        out_v.long_name = "near-surface air temperature"
        out_v.standard_name = "air_temperature"
        converted_vars.append(out_name)

    # Convert precipitation
    if args.precip_var and args.precip_var in src.variables:
        src_precip = src.variables[args.precip_var]
        converter = PRECIP_CONVERSIONS[args.precip_units]
        precip_data = converter(np.array(src_precip[:], dtype=np.float64))

        # Validate converted values
        if np.any(precip_data < 0):
            warnings.append("WARNING: Negative precipitation values found. "
                            "Clipping to zero.")
            precip_data = np.maximum(precip_data, 0)
        if np.any(precip_data > 50000):
            warnings.append(f"WARNING: Precipitation exceeds 50000 kg m^-2 year^-1 "
                            f"(max={precip_data.max():.1f}). Check units.")

        out_name = "precipitation"
        out_v = dst.createVariable(out_name, "f8", src_precip.dimensions,
                                   fill_value=1e20)
        out_v[:] = precip_data
        out_v.units = "kg m^-2 year^-1"
        out_v.long_name = "mean annual precipitation rate"
        converted_vars.append(out_name)

    # Global attributes
    dst.setncattr("Conventions", "CF-1.6")
    dst.setncattr("history", f"Created by convert_climate_forcing.py from {args.input}")

    src.close()
    dst.close()

    return {
        "status": "success",
        "output_file": args.output,
        "converted_variables": converted_vars,
        "temp_conversion": f"{args.temp_units} → kelvin",
        "precip_conversion": f"{args.precip_units} → kg m^-2 year^-1",
        "warnings": warnings,
    }


def validate_outputs(result):
    """Verify the output file is valid PISM forcing."""
    if result["status"] != "success":
        return result

    output_file = result["output_file"]
    post_errors = []

    try:
        ds = Dataset(output_file, "r")

        if "air_temp" in ds.variables:
            temp = ds.variables["air_temp"]
            if hasattr(temp, "units") and temp.units != "kelvin":
                post_errors.append(f"air_temp units = '{temp.units}', expected 'kelvin'")
            vals = temp[:]
            if np.nanmin(vals) < 100:
                post_errors.append(f"air_temp min = {np.nanmin(vals):.1f} K — likely wrong units")

        if "precipitation" in ds.variables:
            precip = ds.variables["precipitation"]
            if hasattr(precip, "units") and precip.units != "kg m^-2 year^-1":
                post_errors.append(f"precipitation units = '{precip.units}', "
                                   f"expected 'kg m^-2 year^-1'")

        ds.close()
    except Exception as e:
        post_errors.append(f"Cannot validate output: {e}")

    if post_errors:
        result["warnings"].extend(post_errors)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert climate data to PISM forcing format"
    )
    parser.add_argument("--input", required=True, help="Input NetCDF file")
    parser.add_argument("--output", required=True, help="Output PISM forcing file")
    parser.add_argument("--temp-var", default=None, help="Temperature variable name")
    parser.add_argument("--precip-var", default=None, help="Precipitation variable name")
    parser.add_argument("--temp-units", default="celsius",
                        choices=list(TEMP_CONVERSIONS.keys()),
                        help="Input temperature units")
    parser.add_argument("--precip-units", default="m_we/year",
                        choices=list(PRECIP_CONVERSIONS.keys()),
                        help="Input precipitation units")
    parser.add_argument("--calendar", default="365_day",
                        help="Calendar for time axis")
    parser.add_argument("--output-json", default=None,
                        help="Write result JSON to file")

    args = parser.parse_args()

    if not args.temp_var and not args.precip_var:
        print(json.dumps({
            "status": "error",
            "errors": ["At least one of --temp-var or --precip-var must be specified"]
        }))
        sys.exit(1)

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
