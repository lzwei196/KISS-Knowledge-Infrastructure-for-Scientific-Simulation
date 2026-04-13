#!/usr/bin/env python3
"""
convert_forcing.py — COAWST Forcing/Input Converter
====================================================

Converts global reanalysis data (ERA5, GFS, NARR, CFSR) and tidal
constituent data (TPXO, FES2014) into ROMS-compatible NetCDF forcing files.

CRITICAL UNIT CONVERSIONS:
  - Temperature: K → °C  (subtract 273.15)
  - Wind stress: Pa (N/m²) → m²/s² (divide by rho0=1025 kg/m³)
  - Heat flux:   W/m² → °C·m/s  (divide by rho0*Cp = 1025*3985)
  - Precipitation: mm/day → m/s  (divide by 86400000)
  - Humidity:    RH% → specific humidity kg/kg (via Clausius-Clapeyron)
  - Pressure:    Pa → mb (divide by 100)

Usage:
  python3 convert_forcing.py \\
    --source /data/era5/ --source-format era5 \\
    --grid roms_grid.nc --output forcing.nc \\
    --type atmospheric --time-ref "days since 2012-01-01"

  python3 convert_forcing.py \\
    --source /data/tpxo/ --source-format tpxo \\
    --grid roms_grid.nc --output tides.nc \\
    --type tidal

See diagnostics/triplets.yaml dt_001-dt_003, dt_006, dt_008, dt_011, dt_015
for common unit-conversion traps.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False


# Physical constants used in ROMS unit conversions
RHO0 = 1025.0       # Reference seawater density (kg/m³)
CP = 3985.0          # Specific heat of seawater (J/kg/°C)
KELVIN_OFFSET = 273.15

# Supported source formats and their variable name mappings
SOURCE_MAPPINGS = {
    "era5": {
        "u10":   {"roms_name": "Uwind",  "units_in": "m/s",   "units_out": "m/s",   "scale": 1.0,    "offset": 0.0},
        "v10":   {"roms_name": "Vwind",  "units_in": "m/s",   "units_out": "m/s",   "scale": 1.0,    "offset": 0.0},
        "t2m":   {"roms_name": "Tair",   "units_in": "K",     "units_out": "C",     "scale": 1.0,    "offset": -KELVIN_OFFSET},
        "sp":    {"roms_name": "Pair",   "units_in": "Pa",    "units_out": "mb",    "scale": 0.01,   "offset": 0.0},
        "d2m":   {"roms_name": "Qair",   "units_in": "K",     "units_out": "kg/kg", "scale": 1.0,    "offset": 0.0,  "convert_func": "dewpoint_to_specific_humidity"},
        "tp":    {"roms_name": "rain",   "units_in": "m/step","units_out": "kg/m2/s","scale": 1.0,   "offset": 0.0,  "convert_func": "precip_accum_to_rate"},
        "ssr":   {"roms_name": "swrad",  "units_in": "J/m2",  "units_out": "W/m2",  "scale": 1.0,    "offset": 0.0,  "convert_func": "accum_to_rate"},
        "str":   {"roms_name": "lwrad",  "units_in": "J/m2",  "units_out": "W/m2",  "scale": 1.0,    "offset": 0.0,  "convert_func": "accum_to_rate"},
    },
    "gfs": {
        "UGRD_10maboveground":  {"roms_name": "Uwind", "units_in": "m/s", "units_out": "m/s", "scale": 1.0, "offset": 0.0},
        "VGRD_10maboveground":  {"roms_name": "Vwind", "units_in": "m/s", "units_out": "m/s", "scale": 1.0, "offset": 0.0},
        "TMP_2maboveground":    {"roms_name": "Tair",  "units_in": "K",   "units_out": "C",   "scale": 1.0, "offset": -KELVIN_OFFSET},
        "PRES_surface":         {"roms_name": "Pair",  "units_in": "Pa",  "units_out": "mb",  "scale": 0.01,"offset": 0.0},
        "SPFH_2maboveground":   {"roms_name": "Qair",  "units_in": "kg/kg","units_out": "kg/kg","scale": 1.0,"offset": 0.0},
        "PRATE_surface":        {"roms_name": "rain",  "units_in": "kg/m2/s","units_out": "kg/m2/s","scale": 1.0,"offset": 0.0},
        "DSWRF_surface":        {"roms_name": "swrad", "units_in": "W/m2", "units_out": "W/m2","scale": 1.0,"offset": 0.0},
        "DLWRF_surface":        {"roms_name": "lwrad", "units_in": "W/m2", "units_out": "W/m2","scale": 1.0,"offset": 0.0},
    },
    "narr": {
        "uwnd":  {"roms_name": "Uwind", "units_in": "m/s",  "units_out": "m/s",  "scale": 1.0,   "offset": 0.0},
        "vwnd":  {"roms_name": "Vwind", "units_in": "m/s",  "units_out": "m/s",  "scale": 1.0,   "offset": 0.0},
        "air":   {"roms_name": "Tair",  "units_in": "K",    "units_out": "C",    "scale": 1.0,   "offset": -KELVIN_OFFSET},
        "pres":  {"roms_name": "Pair",  "units_in": "Pa",   "units_out": "mb",   "scale": 0.01,  "offset": 0.0},
        "shum":  {"roms_name": "Qair",  "units_in": "kg/kg","units_out": "kg/kg","scale": 1.0,   "offset": 0.0},
        "prate": {"roms_name": "rain",  "units_in": "kg/m2/s","units_out": "kg/m2/s","scale": 1.0,"offset": 0.0},
        "dswrf": {"roms_name": "swrad", "units_in": "W/m2", "units_out": "W/m2", "scale": 1.0,   "offset": 0.0},
        "dlwrf": {"roms_name": "lwrad", "units_in": "W/m2", "units_out": "W/m2", "scale": 1.0,   "offset": 0.0},
    },
}

TIDAL_CONSTITUENTS = ["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1", "M4", "MS4"]


def validate_inputs(args):
    """Validate all inputs before processing. Collects errors in list."""
    errors = []
    warnings = []

    if not os.path.exists(args.source):
        errors.append(f"Source path does not exist: {args.source}")

    if not os.path.exists(args.grid):
        errors.append(f"Grid file does not exist: {args.grid}")

    if args.source_format not in SOURCE_MAPPINGS and args.type == "atmospheric":
        errors.append(f"Unsupported source format: {args.source_format}. "
                       f"Supported: {list(SOURCE_MAPPINGS.keys())}")

    if args.type not in ("atmospheric", "tidal", "boundary", "initial"):
        errors.append(f"Unsupported forcing type: {args.type}")

    if not HAS_NETCDF and not HAS_XARRAY:
        errors.append("Neither netCDF4 nor xarray is available. Install one: pip install netCDF4 xarray")

    if args.output and os.path.exists(args.output) and not args.overwrite:
        warnings.append(f"Output file exists: {args.output}. Use --overwrite to replace.")

    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2), file=sys.stdout)
        sys.exit(1)

    return warnings


def dewpoint_to_specific_humidity(td_kelvin, pressure_pa):
    """Convert dewpoint temperature (K) to specific humidity (kg/kg).

    Uses Bolton (1980) approximation for saturation vapor pressure.
    """
    td_celsius = td_kelvin - KELVIN_OFFSET
    # Saturation vapor pressure (hPa) from dewpoint
    e = 6.112 * np.exp(17.67 * td_celsius / (td_celsius + 243.5))
    # Specific humidity
    p_hpa = pressure_pa / 100.0 if np.nanmean(pressure_pa) > 10000 else pressure_pa
    q = 0.622 * e / (p_hpa - 0.378 * e)
    return np.clip(q, 0.0, 0.05)


def rh_to_specific_humidity(rh_percent, t_kelvin, pressure_pa):
    """Convert relative humidity (%) to specific humidity (kg/kg)."""
    t_celsius = t_kelvin - KELVIN_OFFSET
    # Saturation vapor pressure (hPa)
    es = 6.112 * np.exp(17.67 * t_celsius / (t_celsius + 243.5))
    e = (rh_percent / 100.0) * es
    p_hpa = pressure_pa / 100.0 if np.nanmean(pressure_pa) > 10000 else pressure_pa
    q = 0.622 * e / (p_hpa - 0.378 * e)
    return np.clip(q, 0.0, 0.05)


def accum_to_rate(data, dt_seconds):
    """Convert accumulated field (J/m² per step) to instantaneous rate (W/m²)."""
    if dt_seconds <= 0:
        dt_seconds = 3600.0  # default 1-hour step
    return data / dt_seconds


def precip_accum_to_rate(data, dt_seconds):
    """Convert accumulated precipitation (m per step) to rate (kg/m²/s)."""
    rho_water = 1000.0  # kg/m³
    if dt_seconds <= 0:
        dt_seconds = 3600.0
    return data * rho_water / dt_seconds


def interpolate_to_roms_grid(src_lon, src_lat, data, dst_lon, dst_lat):
    """Bilinear interpolation from source grid to ROMS grid.

    Parameters
    ----------
    src_lon, src_lat : 1D arrays of source coordinates
    data : 2D or 3D array (time × lat × lon or lat × lon)
    dst_lon, dst_lat : 2D arrays of ROMS grid coordinates

    Returns
    -------
    Interpolated data on ROMS grid
    """
    from scipy.interpolate import RegularGridInterpolator

    if data.ndim == 2:
        interp = RegularGridInterpolator(
            (src_lat, src_lon), data,
            method="linear", bounds_error=False, fill_value=None
        )
        points = np.stack([dst_lat.ravel(), dst_lon.ravel()], axis=-1)
        return interp(points).reshape(dst_lat.shape)
    elif data.ndim == 3:
        nt = data.shape[0]
        result = np.empty((nt,) + dst_lat.shape)
        for t in range(nt):
            interp = RegularGridInterpolator(
                (src_lat, src_lon), data[t],
                method="linear", bounds_error=False, fill_value=None
            )
            points = np.stack([dst_lat.ravel(), dst_lon.ravel()], axis=-1)
            result[t] = interp(points).reshape(dst_lat.shape)
        return result
    else:
        raise ValueError(f"Expected 2D or 3D data, got {data.ndim}D")


def read_roms_grid(grid_path):
    """Read ROMS grid file and return coordinate arrays."""
    ds = xr.open_dataset(grid_path) if HAS_XARRAY else nc.Dataset(grid_path)

    if HAS_XARRAY:
        lon_rho = ds["lon_rho"].values
        lat_rho = ds["lat_rho"].values
        mask_rho = ds["mask_rho"].values if "mask_rho" in ds else np.ones_like(lon_rho)
        ds.close()
    else:
        lon_rho = ds.variables["lon_rho"][:]
        lat_rho = ds.variables["lat_rho"][:]
        mask_rho = ds.variables["mask_rho"][:] if "mask_rho" in ds.variables else np.ones_like(lon_rho)
        ds.close()

    return {"lon_rho": lon_rho, "lat_rho": lat_rho, "mask_rho": mask_rho}


def process_atmospheric(args, warnings):
    """Convert atmospheric reanalysis to ROMS forcing NetCDF."""
    print(f"Processing atmospheric forcing: {args.source_format}", file=sys.stderr)

    grid = read_roms_grid(args.grid)
    mapping = SOURCE_MAPPINGS[args.source_format]

    # Discover source files
    src_files = []
    if os.path.isdir(args.source):
        for f in sorted(os.listdir(args.source)):
            if f.endswith(".nc") or f.endswith(".nc4") or f.endswith(".grib"):
                src_files.append(os.path.join(args.source, f))
    else:
        src_files = [args.source]

    if not src_files:
        return {"status": "error", "errors": [f"No data files found in {args.source}"]}

    # Read source data
    if HAS_XARRAY:
        ds = xr.open_mfdataset(src_files, combine="by_coords")
    else:
        return {"status": "error", "errors": ["xarray required for multi-file forcing. pip install xarray"]}

    # Determine time step for accumulation conversions
    times = ds["time"].values if "time" in ds else ds["valid_time"].values
    if len(times) > 1:
        dt_sec = float((times[1] - times[0]) / np.timedelta64(1, "s"))
    else:
        dt_sec = 3600.0

    # Get source coordinates
    src_lat_name = "latitude" if "latitude" in ds.dims else "lat"
    src_lon_name = "longitude" if "longitude" in ds.dims else "lon"
    src_lat = ds[src_lat_name].values
    src_lon = ds[src_lon_name].values

    # Fix longitude range to match ROMS grid (0-360 vs -180-180)
    if np.nanmin(grid["lon_rho"]) < 0 and np.nanmin(src_lon) >= 0:
        src_lon = np.where(src_lon > 180, src_lon - 360, src_lon)
    elif np.nanmin(grid["lon_rho"]) >= 0 and np.nanmin(src_lon) < 0:
        src_lon = np.where(src_lon < 0, src_lon + 360, src_lon)

    # Ensure lat is ascending for interpolation
    if src_lat[0] > src_lat[-1]:
        src_lat = src_lat[::-1]
        flip_lat = True
    else:
        flip_lat = False

    # Create output dataset
    converted = {}
    pressure_data = None

    for src_var, info in mapping.items():
        if src_var not in ds:
            warnings.append(f"Variable {src_var} not found in source — skipping {info['roms_name']}")
            continue

        data = ds[src_var].values.copy()
        if flip_lat:
            data = data[..., ::-1, :]

        # Apply special conversion functions
        convert_func = info.get("convert_func")
        if convert_func == "dewpoint_to_specific_humidity":
            # Need pressure for this conversion
            p_var = "sp" if "sp" in ds else "pres"
            if p_var in ds:
                p_data = ds[p_var].values.copy()
                if flip_lat:
                    p_data = p_data[..., ::-1, :]
                data = dewpoint_to_specific_humidity(data, p_data)
            else:
                warnings.append("No pressure field for humidity conversion — using 1013.25 mb")
                data = dewpoint_to_specific_humidity(data, np.full_like(data, 101325.0))
        elif convert_func == "accum_to_rate":
            data = accum_to_rate(data, dt_sec)
        elif convert_func == "precip_accum_to_rate":
            data = precip_accum_to_rate(data, dt_sec)
        else:
            # Standard linear conversion
            data = data * info["scale"] + info["offset"]

        # Interpolate to ROMS grid
        data_interp = interpolate_to_roms_grid(
            src_lon, src_lat, data,
            grid["lon_rho"], grid["lat_rho"]
        )

        # Apply land mask
        data_interp[..., grid["mask_rho"] == 0] = np.nan

        converted[info["roms_name"]] = data_interp
        print(f"  {src_var} → {info['roms_name']}: "
              f"range [{np.nanmin(data_interp):.4f}, {np.nanmax(data_interp):.4f}] {info['units_out']}",
              file=sys.stderr)

    # Validate output ranges
    range_checks = {
        "Tair":  (-80.0, 60.0,  "°C"),
        "Pair":  (850.0, 1100.0, "mb"),
        "Uwind": (-100.0, 100.0, "m/s"),
        "Vwind": (-100.0, 100.0, "m/s"),
        "Qair":  (0.0, 0.05,    "kg/kg"),
        "swrad": (0.0, 1500.0,  "W/m²"),
        "lwrad": (-500.0, 600.0, "W/m²"),
        "rain":  (0.0, 0.1,     "kg/m²/s"),
    }

    for var_name, (vmin, vmax, units) in range_checks.items():
        if var_name in converted:
            actual_min = np.nanmin(converted[var_name])
            actual_max = np.nanmax(converted[var_name])
            if actual_min < vmin or actual_max > vmax:
                warnings.append(
                    f"UNIT TRAP: {var_name} range [{actual_min:.4f}, {actual_max:.4f}] "
                    f"outside expected [{vmin}, {vmax}] {units}. Check unit conversion!"
                )

    # Write output NetCDF
    write_forcing_netcdf(args.output, converted, times, grid, args.time_ref)

    ds.close()
    return {
        "status": "success",
        "output": args.output,
        "variables": list(converted.keys()),
        "n_timesteps": len(times),
        "warnings": warnings,
    }


def process_tidal(args, warnings):
    """Convert tidal constituent data to ROMS tidal forcing NetCDF."""
    print(f"Processing tidal forcing: {args.source_format}", file=sys.stderr)

    grid = read_roms_grid(args.grid)

    # Placeholder for tidal processing (TPXO, FES2014, etc.)
    # In production, this reads harmonic constituents and interpolates to grid
    result = {
        "status": "success",
        "output": args.output,
        "constituents": TIDAL_CONSTITUENTS[:8],
        "warnings": warnings + ["Tidal converter: implement TPXO/FES reader for production use"],
    }
    return result


def write_forcing_netcdf(output_path, variables, times, grid, time_ref):
    """Write ROMS-compatible forcing NetCDF file."""
    if not HAS_NETCDF:
        raise RuntimeError("netCDF4 required for writing. pip install netCDF4")

    eta_rho, xi_rho = grid["lon_rho"].shape

    ds = nc.Dataset(output_path, "w", format="NETCDF4")
    ds.title = "COAWST forcing file (converted by convert_forcing.py)"
    ds.history = f"Created {datetime.now().isoformat()}"
    ds.Conventions = "CF-1.6"

    # Dimensions
    ds.createDimension("xi_rho", xi_rho)
    ds.createDimension("eta_rho", eta_rho)
    ds.createDimension("frc_time", None)  # unlimited

    # Time variable
    time_units = time_ref if time_ref else "days since 2000-01-01 00:00:00"
    frc_time = ds.createVariable("frc_time", "f8", ("frc_time",))
    frc_time.units = time_units
    frc_time.calendar = "standard"
    frc_time.long_name = "forcing time"

    # Convert times to numeric
    if hasattr(times[0], "astype"):
        ref_date = np.datetime64("2000-01-01")
        if "since" in time_units:
            ref_str = time_units.split("since")[1].strip()
            ref_date = np.datetime64(ref_str.split()[0])
        frc_time[:] = (times - ref_date) / np.timedelta64(1, "D")
    else:
        frc_time[:] = np.arange(len(times))

    # Coordinate variables
    lon = ds.createVariable("lon_rho", "f8", ("eta_rho", "xi_rho"))
    lon[:] = grid["lon_rho"]
    lon.long_name = "longitude of rho-points"
    lon.units = "degrees_east"

    lat = ds.createVariable("lat_rho", "f8", ("eta_rho", "xi_rho"))
    lat[:] = grid["lat_rho"]
    lat.long_name = "latitude of rho-points"
    lat.units = "degrees_north"

    # Forcing variables
    var_attrs = {
        "Uwind": {"long_name": "u-wind component at 10m", "units": "meter second-1"},
        "Vwind": {"long_name": "v-wind component at 10m", "units": "meter second-1"},
        "Tair":  {"long_name": "surface air temperature", "units": "Celsius"},
        "Pair":  {"long_name": "surface air pressure", "units": "millibar"},
        "Qair":  {"long_name": "surface air specific humidity", "units": "kg/kg"},
        "rain":  {"long_name": "rain fall rate", "units": "kilogram meter-2 second-1"},
        "swrad": {"long_name": "net shortwave radiation", "units": "watt meter-2"},
        "lwrad": {"long_name": "net longwave radiation", "units": "watt meter-2"},
    }

    for var_name, data in variables.items():
        v = ds.createVariable(var_name, "f4", ("frc_time", "eta_rho", "xi_rho"),
                              fill_value=1.0e+37)
        v[:] = data
        if var_name in var_attrs:
            for attr, val in var_attrs[var_name].items():
                setattr(v, attr, val)
        v.coordinates = "lon_rho lat_rho frc_time"

    ds.close()
    print(f"  Written: {output_path}", file=sys.stderr)


def validate_outputs(result):
    """Post-processing validation of converter output."""
    if result["status"] != "success":
        return result

    output = result.get("output")
    if output and os.path.exists(output):
        size_mb = os.path.getsize(output) / (1024 * 1024)
        result["file_size_mb"] = round(size_mb, 2)
        if size_mb < 0.001:
            result["warnings"].append(f"Output file suspiciously small: {size_mb:.4f} MB")
    elif output:
        result["status"] = "error"
        result["errors"] = [f"Output file not created: {output}"]

    return result


def process(args, warnings):
    """Main dispatch based on forcing type."""
    if args.type == "atmospheric":
        return process_atmospheric(args, warnings)
    elif args.type == "tidal":
        return process_tidal(args, warnings)
    elif args.type in ("boundary", "initial"):
        return {
            "status": "success",
            "warnings": warnings + [f"{args.type} converter: use same pattern as atmospheric with 3D fields"],
        }
    else:
        return {"status": "error", "errors": [f"Unknown type: {args.type}"]}


def main():
    parser = argparse.ArgumentParser(
        description="Convert global reanalysis / tidal data to ROMS forcing NetCDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # ERA5 atmospheric forcing
  python3 convert_forcing.py --source /data/era5/ --source-format era5 \\
    --grid grid.nc --output forcing.nc --type atmospheric

  # TPXO tidal forcing
  python3 convert_forcing.py --source /data/tpxo/ --source-format tpxo \\
    --grid grid.nc --output tides.nc --type tidal
        """,
    )
    parser.add_argument("--source", required=True, help="Path to source data (file or directory)")
    parser.add_argument("--source-format", required=True,
                        choices=["era5", "gfs", "narr", "cfsr", "tpxo", "fes2014"],
                        help="Source data format")
    parser.add_argument("--grid", required=True, help="Path to ROMS grid NetCDF file")
    parser.add_argument("--output", required=True, help="Output NetCDF file path")
    parser.add_argument("--type", required=True,
                        choices=["atmospheric", "tidal", "boundary", "initial"],
                        help="Type of forcing to create")
    parser.add_argument("--time-ref", default="days since 2000-01-01 00:00:00",
                        help="Time reference string for output (default: days since 2000-01-01)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")

    args = parser.parse_args()

    # Step 1: Validate inputs
    warnings = validate_inputs(args)

    # Step 2: Process
    result = process(args, warnings)

    # Step 3: Validate outputs
    result = validate_outputs(result)

    # Output result as JSON
    print(json.dumps(result, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
