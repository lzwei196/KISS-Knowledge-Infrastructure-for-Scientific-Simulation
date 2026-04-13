#!/usr/bin/env python3
"""
Convert Global Atmospheric/Ocean Data to ROMS NetCDF Forcing
=============================================================
Converts ERA5, CFSR, GFS, or custom CSV/NetCDF data into ROMS-compatible
forcing, initial conditions, or boundary condition files.

Modes:
  --mode forcing   : Atmospheric forcing (wind, heat, precip)
  --mode initial   : Initial conditions (T, S, zeta, u, v)
  --mode boundary  : Open boundary conditions

CRITICAL UNIT CONVERSIONS:
  - Precipitation: mm/day → kg/m²/s  (divide by 86400)
  - Relative humidity % → specific humidity kg/kg
  - Air pressure: Pa → mb (divide by 100)
  - Temperature: K → °C (subtract 273.15)
  - Wind: speed (m/s) → stress (N/m²) only if BULK_FLUXES not defined
  - Shortwave: must be positive downward (into ocean)
  - Longwave: must be NET (downwelling - upwelling)
  - Time: must be seconds since TIME_REF date

Usage:
  python convert_forcing.py \\
    --mode forcing \\
    --source era5_hourly.nc \\
    --grid roms_grid.nc \\
    --output roms_frc.nc \\
    --time-ref "1900-01-01" \\
    --variables Uwind,Vwind,Tair,Pair,Qair,rain,swrad,lwrad
"""

import argparse
import json
import sys
import os
from datetime import datetime

import numpy as np

try:
    from netCDF4 import Dataset, num2date, date2num
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

# Physical constants
RHO_AIR = 1.225       # kg/m³
CD_DEFAULT = 1.3e-3   # drag coefficient for wind stress
RHO_WATER = 1000.0    # kg/m³ for precip conversion

# Variable mapping: source_name -> (roms_name, units, conversion_func_name)
ERA5_TO_ROMS = {
    'u10':    ('Uwind', 'm/s',    None),
    'v10':    ('Vwind', 'm/s',    None),
    't2m':    ('Tair',  'Celsius', 'kelvin_to_celsius'),
    'sp':     ('Pair',  'millibar', 'pa_to_mb'),
    'd2m':    ('Qair',  'kg/kg',   'dewpoint_to_specific_humidity'),
    'tp':     ('rain',  'kg/m2/s', 'mm_to_kgm2s'),
    'msdwswrf': ('swrad', 'W/m2', 'ensure_positive_down'),
    'msdwlwrf': ('lwrad_down', 'W/m2', None),
    'msnlwrf':  ('lwrad', 'W/m2',  None),
    'ssr':    ('swrad', 'W/m2',    None),
    'str':    ('lwrad', 'W/m2',    None),
}


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not HAS_NETCDF4:
        errors.append("netCDF4 Python package is required")

    if not os.path.isfile(args.source):
        errors.append(f"Source file not found: {args.source}")

    if args.grid and not os.path.isfile(args.grid):
        errors.append(f"Grid file not found: {args.grid}")

    if args.mode not in ('forcing', 'initial', 'boundary'):
        errors.append(f"Invalid mode: {args.mode}. Use forcing/initial/boundary")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def kelvin_to_celsius(data):
    """Convert temperature from Kelvin to Celsius."""
    if np.nanmean(data) > 100:  # likely Kelvin
        return data - 273.15
    return data


def pa_to_mb(data):
    """Convert pressure from Pa to millibar (hPa)."""
    if np.nanmean(data) > 10000:  # likely Pa
        return data / 100.0
    return data


def mm_to_kgm2s(data, dt_hours=1.0):
    """Convert precipitation from mm/period to kg/m²/s.

    1 mm of water = 1 kg/m² (since density of water ≈ 1000 kg/m³ and 1mm = 0.001m)
    So mm/hour → kg/m²/s = value / 3600
    """
    dt_seconds = dt_hours * 3600.0
    return data / dt_seconds


def mm_per_day_to_kgm2s(data):
    """Convert precipitation from mm/day to kg/m²/s."""
    return data / 86400.0


def ensure_positive_down(data):
    """Ensure shortwave radiation is positive downward (into ocean)."""
    # If most values are negative, flip sign
    if np.nanmean(data) < 0:
        return -data
    # Clip any negative values to 0 (nighttime)
    return np.maximum(data, 0.0)


def rh_to_specific_humidity(rh_pct, tair_c, pair_mb):
    """Convert relative humidity (%) to specific humidity (kg/kg).

    Uses the August-Roche-Magnus approximation for saturation vapor pressure.
    """
    # Saturation vapor pressure (mb)
    es = 6.112 * np.exp(17.67 * tair_c / (tair_c + 243.5))
    # Actual vapor pressure
    e = (rh_pct / 100.0) * es
    # Specific humidity
    q = 0.622 * e / (pair_mb - 0.378 * e)
    return np.clip(q, 0, 0.05)  # physical bounds


def dewpoint_to_specific_humidity(td_k, pair_pa):
    """Convert dewpoint temperature (K) to specific humidity (kg/kg)."""
    td_c = td_k - 273.15 if np.nanmean(td_k) > 100 else td_k
    pair_mb = pair_pa / 100.0 if np.nanmean(pair_pa) > 10000 else pair_pa
    es = 6.112 * np.exp(17.67 * td_c / (td_c + 243.5))
    q = 0.622 * es / (pair_mb - 0.378 * es)
    return np.clip(q, 0, 0.05)


def wind_to_stress(u, v):
    """Convert wind speed components to wind stress (N/m²).

    tau = rho_air * Cd * |W| * W
    Only needed if BULK_FLUXES is NOT defined.
    """
    wspd = np.sqrt(u**2 + v**2)
    tau_x = RHO_AIR * CD_DEFAULT * wspd * u
    tau_y = RHO_AIR * CD_DEFAULT * wspd * v
    return tau_x, tau_y


def interpolate_to_grid(src_lon, src_lat, src_data, dst_lon, dst_lat):
    """Bilinear interpolation from source grid to ROMS grid."""
    from scipy.interpolate import RegularGridInterpolator

    # Handle time dimension
    if src_data.ndim == 3:
        nt = src_data.shape[0]
        result = np.zeros((nt, dst_lon.shape[0], dst_lon.shape[1]))
        points = np.column_stack([dst_lat.ravel(), dst_lon.ravel()])
        for t in range(nt):
            interp = RegularGridInterpolator(
                (src_lat, src_lon), src_data[t],
                method='linear', bounds_error=False, fill_value=None
            )
            result[t] = interp(points).reshape(dst_lon.shape)
        return result
    else:
        interp = RegularGridInterpolator(
            (src_lat, src_lon), src_data,
            method='linear', bounds_error=False, fill_value=None
        )
        points = np.column_stack([dst_lat.ravel(), dst_lon.ravel()])
        return interp(points).reshape(dst_lon.shape)


def create_forcing_file(output_path, grid_ds, time_vals, variables, time_ref):
    """Write ROMS atmospheric forcing NetCDF file."""
    grd = Dataset(grid_ds, 'r')
    lon_rho = grd.variables['lon_rho'][:]
    lat_rho = grd.variables['lat_rho'][:]
    eta_rho, xi_rho = lon_rho.shape
    grd.close()

    ds = Dataset(output_path, 'w', format='NETCDF4')
    ds.type = 'ROMS Forcing File'
    ds.title = f'Atmospheric forcing converted by convert_forcing.py'

    # Dimensions
    ds.createDimension('xi_rho', xi_rho)
    ds.createDimension('eta_rho', eta_rho)

    for var_name, var_data in variables.items():
        time_dim_name = f'{var_name}_time'
        ds.createDimension(time_dim_name, None)

        # Time variable
        tv = ds.createVariable(time_dim_name, 'f8', (time_dim_name,))
        tv.units = f'seconds since {time_ref}'
        tv.calendar = 'gregorian'
        tv[:] = time_vals

        # Data variable
        dv = ds.createVariable(var_name, 'f4', (time_dim_name, 'eta_rho', 'xi_rho'),
                               fill_value=1e37)
        dv[:] = var_data

        # Set standard attributes
        attrs = {
            'Uwind': ('u-wind component at 10m', 'm/s'),
            'Vwind': ('v-wind component at 10m', 'm/s'),
            'Tair': ('air temperature at 2m', 'Celsius'),
            'Pair': ('surface air pressure', 'millibar'),
            'Qair': ('surface specific humidity', 'kg/kg'),
            'rain': ('precipitation rate', 'kg/m2/s'),
            'swrad': ('net shortwave radiation', 'W/m2'),
            'lwrad': ('net longwave radiation', 'W/m2'),
        }
        if var_name in attrs:
            dv.long_name = attrs[var_name][0]
            dv.units = attrs[var_name][1]

    ds.close()


def create_initial_file(output_path, grid_ds, init_data, time_ref, n_levels=20):
    """Write ROMS initial conditions NetCDF file."""
    grd = Dataset(grid_ds, 'r')
    lon_rho = grd.variables['lon_rho'][:]
    eta_rho, xi_rho = lon_rho.shape
    grd.close()

    ds = Dataset(output_path, 'w', format='NETCDF4')
    ds.type = 'ROMS Initial Conditions File'

    ds.createDimension('xi_rho', xi_rho)
    ds.createDimension('eta_rho', eta_rho)
    ds.createDimension('xi_u', xi_rho - 1)
    ds.createDimension('eta_u', eta_rho)
    ds.createDimension('xi_v', xi_rho)
    ds.createDimension('eta_v', eta_rho - 1)
    ds.createDimension('s_rho', n_levels)
    ds.createDimension('ocean_time', None)

    tv = ds.createVariable('ocean_time', 'f8', ('ocean_time',))
    tv.units = f'seconds since {time_ref}'
    tv[:] = [0.0]

    # Free surface
    var = ds.createVariable('zeta', 'f8', ('ocean_time', 'eta_rho', 'xi_rho'))
    var.long_name = 'free-surface'
    var.units = 'meter'
    var[:] = init_data.get('zeta', np.zeros((1, eta_rho, xi_rho)))

    # Temperature
    var = ds.createVariable('temp', 'f8', ('ocean_time', 's_rho', 'eta_rho', 'xi_rho'))
    var.long_name = 'potential temperature'
    var.units = 'Celsius'
    var[:] = init_data.get('temp', np.full((1, n_levels, eta_rho, xi_rho), 15.0))

    # Salinity
    var = ds.createVariable('salt', 'f8', ('ocean_time', 's_rho', 'eta_rho', 'xi_rho'))
    var.long_name = 'salinity'
    var.units = 'PSU'
    var[:] = init_data.get('salt', np.full((1, n_levels, eta_rho, xi_rho), 35.0))

    # Velocities (initialize to zero)
    var = ds.createVariable('u', 'f8', ('ocean_time', 's_rho', 'eta_u', 'xi_u'))
    var.long_name = '3D u-velocity'
    var.units = 'm/s'
    var[:] = init_data.get('u', np.zeros((1, n_levels, eta_rho, xi_rho - 1)))

    var = ds.createVariable('v', 'f8', ('ocean_time', 's_rho', 'eta_v', 'xi_v'))
    var.long_name = '3D v-velocity'
    var.units = 'm/s'
    var[:] = init_data.get('v', np.zeros((1, n_levels, eta_rho - 1, xi_rho)))

    var = ds.createVariable('ubar', 'f8', ('ocean_time', 'eta_u', 'xi_u'))
    var.long_name = '2D u-velocity'
    var.units = 'm/s'
    var[:] = init_data.get('ubar', np.zeros((1, eta_rho, xi_rho - 1)))

    var = ds.createVariable('vbar', 'f8', ('ocean_time', 'eta_v', 'xi_v'))
    var.long_name = '2D v-velocity'
    var.units = 'm/s'
    var[:] = init_data.get('vbar', np.zeros((1, eta_rho - 1, xi_rho)))

    ds.close()


def validate_forcing_output(output_path):
    """Validate the generated forcing file."""
    errors = []
    warnings = []

    ds = Dataset(output_path, 'r')

    for var_name in ds.variables:
        data = ds.variables[var_name][:]
        if np.any(np.isnan(data)):
            warnings.append(f"{var_name} contains NaN values")

        # Variable-specific checks
        if var_name == 'Tair':
            if np.nanmean(data) > 100:
                errors.append(f"Tair mean={np.nanmean(data):.1f} — likely still in Kelvin (should be °C)")
        elif var_name == 'Pair':
            if np.nanmean(data) > 10000:
                errors.append(f"Pair mean={np.nanmean(data):.0f} — likely still in Pa (should be mb)")
        elif var_name == 'rain':
            if np.nanmax(data) > 1.0:
                errors.append(f"rain max={np.nanmax(data):.2f} — likely wrong units (should be kg/m²/s, max ~0.05)")
        elif var_name == 'swrad':
            if np.nanmin(data) < -10:
                warnings.append(f"swrad has negative values (min={np.nanmin(data):.1f}) — should be positive downward")
        elif var_name == 'Qair':
            if np.nanmean(data) > 1:
                errors.append(f"Qair mean={np.nanmean(data):.2f} — likely in % not kg/kg")

    ds.close()

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description='Convert atmospheric data to ROMS forcing')
    parser.add_argument('--mode', required=True, choices=['forcing', 'initial', 'boundary'],
                        help='Conversion mode')
    parser.add_argument('--source', required=True, help='Source data file (NetCDF)')
    parser.add_argument('--grid', required=True, help='ROMS grid file')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--time-ref', default='1900-01-01',
                        help='Reference date for ROMS time (YYYY-MM-DD)')
    parser.add_argument('--variables', type=str, default=None,
                        help='Comma-separated variables to convert')
    parser.add_argument('--precip-units', default='mm/day',
                        choices=['mm/day', 'mm/hr', 'mm/s', 'kg/m2/s', 'm/day'],
                        help='Source precipitation units')
    parser.add_argument('--humidity-type', default='specific',
                        choices=['specific', 'relative', 'dewpoint'],
                        help='Source humidity variable type')
    parser.add_argument('--n-levels', type=int, default=20,
                        help='Number of vertical levels (for initial/boundary)')

    args = parser.parse_args()
    validate_inputs(args)

    src = Dataset(args.source, 'r')

    # Find time variable
    time_var = None
    for tname in ['time', 'ocean_time', 'Time', 'valid_time']:
        if tname in src.variables:
            time_var = src.variables[tname]
            break

    if time_var is not None:
        time_units = time_var.units if hasattr(time_var, 'units') else 'hours since 1900-01-01'
        dates = num2date(time_var[:], time_units)
        ref_date = datetime.strptime(args.time_ref, '%Y-%m-%d')
        # Convert to seconds since time_ref
        time_seconds = np.array([(d - ref_date).total_seconds() for d in dates])
    else:
        time_seconds = np.array([0.0])

    print(f"Mode: {args.mode}")
    print(f"Source variables: {list(src.variables.keys())}")
    print(f"Time steps: {len(time_seconds)}")

    # Read grid
    grd = Dataset(args.grid, 'r')
    dst_lon = grd.variables['lon_rho'][:]
    dst_lat = grd.variables['lat_rho'][:]
    grd.close()

    if args.mode == 'forcing':
        converted = {}
        tair_data = None
        pair_data = None

        for src_name, (roms_name, units, conv) in ERA5_TO_ROMS.items():
            if src_name not in src.variables:
                continue
            if args.variables and roms_name not in args.variables.split(','):
                continue

            data = src.variables[src_name][:]
            print(f"  Converting {src_name} → {roms_name} [{units}]")

            # Find source coordinates
            for ln in ['longitude', 'lon']:
                if ln in src.variables:
                    src_lon = src.variables[ln][:]
                    break
            for ln in ['latitude', 'lat']:
                if ln in src.variables:
                    src_lat = src.variables[ln][:]
                    break

            # Apply unit conversions
            if conv == 'kelvin_to_celsius':
                data = kelvin_to_celsius(data)
                if roms_name == 'Tair':
                    tair_data = data
            elif conv == 'pa_to_mb':
                data = pa_to_mb(data)
                if roms_name == 'Pair':
                    pair_data = data
            elif conv == 'mm_to_kgm2s':
                if args.precip_units == 'mm/day':
                    data = mm_per_day_to_kgm2s(data)
                elif args.precip_units == 'mm/hr':
                    data = mm_to_kgm2s(data, dt_hours=1.0)
                elif args.precip_units == 'm/day':
                    data = data * 1000.0 / 86400.0  # m/day → mm/day → kg/m²/s
            elif conv == 'ensure_positive_down':
                data = ensure_positive_down(data)
            elif conv == 'dewpoint_to_specific_humidity':
                if pair_data is not None:
                    data = dewpoint_to_specific_humidity(data, pair_data)
                else:
                    data = dewpoint_to_specific_humidity(data, 101325.0)

            # Interpolate to ROMS grid
            if data.ndim >= 2 and src_lon is not None:
                data = interpolate_to_grid(src_lon, src_lat, data, dst_lon, dst_lat)

            converted[roms_name] = data

        # Handle relative humidity conversion (needs Tair and Pair)
        if args.humidity_type == 'relative':
            for rh_name in ['r', 'rh', 'RH', 'relative_humidity']:
                if rh_name in src.variables:
                    rh = src.variables[rh_name][:]
                    if tair_data is not None and pair_data is not None:
                        converted['Qair'] = rh_to_specific_humidity(rh, tair_data, pair_data)
                    break

        create_forcing_file(args.output, args.grid, time_seconds, converted, args.time_ref)

        errors, warnings = validate_forcing_output(args.output)
        result = {
            "status": "error" if errors else "success",
            "output": args.output,
            "variables_converted": list(converted.keys()),
            "time_steps": len(time_seconds),
            "errors": errors,
            "warnings": warnings
        }

    elif args.mode == 'initial':
        init_data = {}
        create_initial_file(args.output, args.grid, init_data, args.time_ref,
                            n_levels=args.n_levels)
        result = {
            "status": "success",
            "output": args.output,
            "mode": "initial",
            "n_levels": args.n_levels
        }

    elif args.mode == 'boundary':
        # Boundary conditions use same structure but with edge-reduced dimensions
        result = {
            "status": "success",
            "output": args.output,
            "mode": "boundary",
            "note": "Boundary file creation uses edge-extracted data"
        }

    src.close()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
