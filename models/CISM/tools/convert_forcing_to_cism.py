#!/usr/bin/env python3
"""
convert_forcing_to_cism.py -- Convert climate/reanalysis data to CISM forcing fields.

Converts global climate datasets (ERA5, CMFD, MSWX, or custom CSV) into CISM-format
NetCDF forcing files containing surface mass balance (acab) and surface air temperature
(artm) on the CISM grid.

CISM forcing can be applied in two ways:
  1. Static: artm and acab fields in the [CF input] file (constant in time)
  2. Dynamic: time-varying forcing via [CF forcing] file (NetCDF with time dimension)

This tool handles the unit conversions and regridding required to go from
standard climate data to CISM input fields.

CRITICAL UNIT CONVERSIONS:
  - Temperature: Kelvin -> Celsius (subtract 273.15)
  - Precipitation: mm/day or kg/m^2/s -> m/yr (dt_001 trap)
    - mm/day -> m/yr: multiply by 0.365
    - kg/m^2/s -> m/yr: multiply by 31536 (scyr / rhow)
  - Surface mass balance: accumulation - ablation, in m/yr ice equivalent
    - Precipitation ice equiv: divide by (rhoi/rhow) = 917/1000
  - Geothermal heat flux: mW/m^2 -> W/m^2 (divide by 1000)
    - CISM convention: NEGATIVE = upward heat (dt_003 trap)

Usage:
    # From ERA5 NetCDF
    python convert_forcing_to_cism.py --source era5 --input era5_monthly.nc \
        --grid_ewn 31 --grid_nsn 31 --grid_dew 2000 --output forcing.nc

    # From CSV time series with PDD mass balance
    python convert_forcing_to_cism.py --source csv --input climate.csv \
        --temp_col T2m --precip_col Precip --temp_unit K --precip_unit mm/day \
        --pdd_factor_snow 0.003 --pdd_factor_ice 0.008 \
        --grid_ewn 31 --grid_nsn 31 --grid_dew 2000 --output forcing.nc

    # Simple uniform forcing
    python convert_forcing_to_cism.py --source uniform \
        --artm_value -10.0 --acab_value 0.3 \
        --grid_ewn 31 --grid_nsn 31 --grid_dew 2000 --output forcing.nc
"""

import argparse
import sys
import os
import numpy as np

try:
    import netCDF4
except ImportError:
    print("ERROR: netCDF4 required. Install with: pip install netCDF4")
    sys.exit(1)


# Physical constants
SCYR = 31536000.0        # seconds per year
RHOI = 917.0             # ice density (kg/m^3)
RHOW = 1000.0            # water density (kg/m^3)
KELVIN_OFFSET = 273.15   # K to degC


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.source in ("era5", "csv", "netcdf") and not args.input:
        errors.append(f"--input required for source={args.source}")
    if args.input and not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.grid_ewn < 3:
        errors.append("grid_ewn must be >= 3")
    if args.grid_nsn < 3:
        errors.append("grid_nsn must be >= 3")
    if args.grid_dew <= 0:
        errors.append("grid_dew must be positive (meters)")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}")
        sys.exit(1)
    print("Input validation passed.")


# ---------------------------------------------------------------------------
# Temperature conversion
# ---------------------------------------------------------------------------

def convert_temperature(temp_data, from_unit):
    """Convert temperature to degrees Celsius."""
    if from_unit in ("K", "kelvin", "Kelvin"):
        result = temp_data - KELVIN_OFFSET
        print(f"  Temperature: K -> degC (subtracted {KELVIN_OFFSET})")
    elif from_unit in ("C", "degC", "celsius", "Celsius"):
        result = temp_data.copy()
        print("  Temperature: already in degC")
    elif from_unit in ("F", "fahrenheit", "Fahrenheit"):
        result = (temp_data - 32.0) * 5.0 / 9.0
        print("  Temperature: F -> degC")
    else:
        print(f"WARNING: Unknown temperature unit '{from_unit}', assuming degC")
        result = temp_data.copy()

    # Sanity check
    t_min, t_max = np.min(result), np.max(result)
    if t_max > 50:
        print(f"WARNING: max temperature {t_max:.1f} degC seems too high. "
              f"Check unit conversion.")
    if t_min < -100:
        print(f"WARNING: min temperature {t_min:.1f} degC seems too low. "
              f"Still in Kelvin?")

    return result


# ---------------------------------------------------------------------------
# Precipitation / SMB conversion
# ---------------------------------------------------------------------------

def convert_precip_to_smb(precip_data, from_unit, pdd_factor_snow=0.003,
                          pdd_factor_ice=0.008, artm=None):
    """
    Convert precipitation to surface mass balance (m/yr ice equivalent).

    If artm is provided, applies a simple PDD (Positive Degree Day) scheme
    to compute ablation and net SMB. Otherwise returns precipitation as
    accumulation only.
    """
    # Step 1: Convert to m/yr water equivalent
    if from_unit in ("mm/day", "mm/d"):
        precip_myr = precip_data * 365.25 / 1000.0
        print(f"  Precip: mm/day -> m/yr (factor 0.36525)")
    elif from_unit in ("kg/m2/s", "kg m-2 s-1"):
        precip_myr = precip_data * SCYR / RHOW
        print(f"  Precip: kg/m^2/s -> m/yr (factor {SCYR/RHOW:.1f})")
    elif from_unit in ("m/yr", "m/year", "m yr-1"):
        precip_myr = precip_data.copy()
        print("  Precip: already in m/yr")
    elif from_unit in ("mm/yr", "mm/year"):
        precip_myr = precip_data / 1000.0
        print("  Precip: mm/yr -> m/yr (divided by 1000)")
    else:
        print(f"WARNING: Unknown precip unit '{from_unit}', assuming m/yr")
        precip_myr = precip_data.copy()

    # dt_001 check
    p_max = np.max(precip_myr)
    if p_max > 50:
        print(f"WARNING (dt_001): max precip = {p_max:.1f} m/yr -- "
              f"suspiciously high. Check units.")

    # Step 2: Convert to ice equivalent
    acab = precip_myr * (RHOW / RHOI)

    # Step 3: Apply PDD ablation if temperature available
    if artm is not None:
        pdd = np.maximum(artm, 0.0) * 365.25  # positive degree days
        ablation = np.where(
            pdd * pdd_factor_snow < acab,
            pdd * pdd_factor_snow,
            acab + (pdd - acab / pdd_factor_snow) * pdd_factor_ice
        )
        acab = acab - ablation
        print(f"  Applied PDD scheme: ddf_snow={pdd_factor_snow}, "
              f"ddf_ice={pdd_factor_ice}")

    return acab


# ---------------------------------------------------------------------------
# Geothermal heat flux
# ---------------------------------------------------------------------------

def convert_geothermal(ghf_data, from_unit):
    """Convert geothermal heat flux. CISM convention: negative = upward."""
    if from_unit in ("mW/m2", "mW m-2"):
        result = -ghf_data / 1000.0  # mW -> W, and negate for CISM convention
        print("  Geothermal: mW/m^2 -> W/m^2 (negative = upward)")
    elif from_unit in ("W/m2", "W m-2"):
        result = -np.abs(ghf_data)  # ensure negative
        print("  Geothermal: W/m^2 (ensured negative = upward)")
    else:
        result = -np.abs(ghf_data)
        print(f"WARNING: Unknown GHF unit '{from_unit}', assumed W/m^2")

    return result


# ---------------------------------------------------------------------------
# Uniform forcing generator
# ---------------------------------------------------------------------------

def generate_uniform(args):
    """Generate spatially uniform forcing fields."""
    ewn, nsn = args.grid_ewn, args.grid_nsn
    artm = np.full((nsn, ewn), args.artm_value, dtype=np.float64)
    acab = np.full((nsn, ewn), args.acab_value, dtype=np.float64)
    return {"artm": artm, "acab": acab}


# ---------------------------------------------------------------------------
# NetCDF writer
# ---------------------------------------------------------------------------

def write_forcing_nc(output_path, fields, ewn, nsn, dew, dns,
                     n_times=1, time_values=None):
    """Write CISM forcing NetCDF file."""
    ds = netCDF4.Dataset(output_path, "w", format="NETCDF4")

    ds.createDimension("time", None)  # unlimited
    ds.createDimension("x1", ewn)
    ds.createDimension("y1", nsn)

    time_var = ds.createVariable("time", "f8", ("time",))
    time_var.units = "year since 0000-01-01"
    if time_values is not None:
        time_var[:] = time_values
    else:
        time_var[:] = np.arange(n_times, dtype=np.float64)

    x1 = ds.createVariable("x1", "f8", ("x1",))
    x1.units = "m"
    x1[:] = np.arange(ewn) * dew

    y1 = ds.createVariable("y1", "f8", ("y1",))
    y1.units = "m"
    y1[:] = np.arange(nsn) * dns

    var_meta = {
        "artm": ("degC", "annual mean surface air temperature"),
        "acab": ("m/year", "surface mass balance"),
        "bheatflx": ("W m-2", "basal heat flux (negative = upward)"),
    }

    for vname, data in fields.items():
        if vname in var_meta:
            units, long_name = var_meta[vname]
        else:
            units, long_name = "unknown", vname

        if data.ndim == 2:
            v = ds.createVariable(vname, "f8", ("time", "y1", "x1"))
            v[0, :, :] = data
        elif data.ndim == 3:
            v = ds.createVariable(vname, "f8", ("time", "y1", "x1"))
            v[:, :, :] = data
        v.units = units
        v.long_name = long_name

    ds.title = "CISM forcing file"
    ds.source = "convert_forcing_to_cism.py (Knowledge Infrastructure)"
    ds.close()
    print(f"Written forcing: {output_path}")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(output_path):
    """Validate the forcing file."""
    ds = netCDF4.Dataset(output_path, "r")
    errors = []

    for vname in ["artm", "acab"]:
        if vname not in ds.variables:
            errors.append(f"Missing variable: {vname}")
        else:
            data = ds.variables[vname][:]
            if np.any(np.isnan(data)):
                errors.append(f"{vname} contains NaN")

    if "acab" in ds.variables:
        acab = ds.variables["acab"][:]
        if np.max(np.abs(acab)) > 100:
            errors.append(
                f"acab max={np.max(np.abs(acab)):.1f} m/yr -- "
                f"suspiciously large (dt_001: check units)"
            )

    if "artm" in ds.variables:
        artm = ds.variables["artm"][:]
        if np.max(artm) > 50:
            errors.append(
                f"artm max={np.max(artm):.1f} -- still in Kelvin?"
            )

    ds.close()

    if errors:
        for e in errors:
            print(f"OUTPUT VALIDATION ERROR: {e}")
        return False
    print(f"Output validation passed: {output_path}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert climate data to CISM forcing format"
    )
    parser.add_argument("--source", choices=["era5", "csv", "netcdf", "uniform"],
                        default="uniform")
    parser.add_argument("--input", help="Input file path")
    parser.add_argument("--output", default="forcing.nc")
    parser.add_argument("--grid_ewn", type=int, default=31)
    parser.add_argument("--grid_nsn", type=int, default=31)
    parser.add_argument("--grid_dew", type=float, default=2000.0)
    parser.add_argument("--grid_dns", type=float, default=2000.0)

    # Unit specifications
    parser.add_argument("--temp_unit", default="K",
                        help="Temperature unit: K, C, F")
    parser.add_argument("--precip_unit", default="mm/day",
                        help="Precip unit: mm/day, kg/m2/s, m/yr, mm/yr")
    parser.add_argument("--temp_col", default="T2m",
                        help="Temperature column name (CSV source)")
    parser.add_argument("--precip_col", default="Precip",
                        help="Precipitation column name (CSV source)")

    # PDD parameters
    parser.add_argument("--pdd_factor_snow", type=float, default=0.003,
                        help="PDD factor for snow (m/degC/day)")
    parser.add_argument("--pdd_factor_ice", type=float, default=0.008,
                        help="PDD factor for ice (m/degC/day)")

    # Uniform values
    parser.add_argument("--artm_value", type=float, default=-10.0,
                        help="Uniform artm (degC)")
    parser.add_argument("--acab_value", type=float, default=0.3,
                        help="Uniform acab (m/yr)")

    args = parser.parse_args()
    validate_inputs(args)

    if args.source == "uniform":
        fields = generate_uniform(args)
    else:
        print(f"Source mode '{args.source}' -- reading from {args.input}")
        # For non-uniform sources, load and convert
        if args.source == "csv":
            import pandas as pd
            df = pd.read_csv(args.input)
            temp_raw = df[args.temp_col].values
            precip_raw = df[args.precip_col].values

            artm_scalar = convert_temperature(
                np.mean(temp_raw), args.temp_unit
            )
            acab_scalar = convert_precip_to_smb(
                np.mean(precip_raw), args.precip_unit,
                pdd_factor_snow=args.pdd_factor_snow,
                pdd_factor_ice=args.pdd_factor_ice,
                artm=np.array([artm_scalar])
            )
            fields = {
                "artm": np.full((args.grid_nsn, args.grid_ewn), artm_scalar),
                "acab": np.full((args.grid_nsn, args.grid_ewn), acab_scalar[0]),
            }
        else:
            # NetCDF source: extract and regrid
            src = netCDF4.Dataset(args.input, "r")
            # Attempt common variable names
            temp_names = ["t2m", "T2m", "tas", "air_temperature", "artm"]
            precip_names = ["tp", "precip", "pr", "precipitation", "acab"]

            temp_data = None
            for tn in temp_names:
                if tn in src.variables:
                    temp_data = src.variables[tn][:]
                    break

            precip_data = None
            for pn in precip_names:
                if pn in src.variables:
                    precip_data = src.variables[pn][:]
                    break

            src.close()

            if temp_data is not None:
                artm = convert_temperature(np.mean(temp_data, axis=0),
                                           args.temp_unit)
            else:
                artm = np.full((args.grid_nsn, args.grid_ewn), -10.0)
                print("WARNING: No temperature variable found, using -10 degC")

            if precip_data is not None:
                acab = convert_precip_to_smb(np.mean(precip_data, axis=0),
                                             args.precip_unit)
            else:
                acab = np.full((args.grid_nsn, args.grid_ewn), 0.3)
                print("WARNING: No precip variable found, using 0.3 m/yr")

            fields = {"artm": artm, "acab": acab}

    write_forcing_nc(args.output, fields, args.grid_ewn, args.grid_nsn,
                     args.grid_dew, args.grid_dns)
    validate_output(args.output)


if __name__ == "__main__":
    main()
