#!/usr/bin/env python3
"""
convert_forcing.py — Convert global reanalysis forcing to TopoFlow meteorology input.

Supported sources:
  - ERA5  (hourly, units: K, kg/m²/s, Pa, J/m², m/s)
  - CMFD  (3-hourly, units: °C, mm/3hr, %, W/m², m/s)
  - MSWX  (daily, units: °C, mm/day, %, W/m², m/s)

Output:
  Text time-series files for TopoFlow meteorology component:
    *_rain_rates.txt   (mm/hr)
    *_T_air.txt        (°C)
    *_RH.txt           (fraction 0–1)
    *_wind.txt         (m/s)
    *_p_atm.txt        (mbar)
    *_Qsw.txt          (W/m²)

CRITICAL UNIT TRAPS:
  - ERA5 precipitation is kg/m²/s → multiply by 3600 to get mm/hr
  - ERA5 temperature is Kelvin → subtract 273.15 for °C
  - CMFD precipitation is mm/3hr → divide by 3 for mm/hr
  - MSWX precipitation is mm/day → divide by 24 for mm/hr
  - TopoFlow cfg expects rain in mm/hr; it converts internally to m/s
  - Do NOT pre-convert rain to m/s — the model does this automatically
  - Relative humidity must be fraction 0–1, not percentage 0–100

Usage:
  python convert_forcing.py \\
    --source era5 \\
    --input_dir /path/to/era5/netcdf/ \\
    --lat 41.17 --lon -95.62 \\
    --start 1967-06-20 --end 1967-06-21 \\
    --output_dir ./met_input/ \\
    --site_prefix Treynor
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
ERA5_PRECIP_TO_MMHR = 3600.0      # kg/m²/s → mm/hr  (water density ≈ 1000)
CMFD_PRECIP_TO_MMHR = 1.0 / 3.0   # mm/3hr → mm/hr
MSWX_PRECIP_TO_MMHR = 1.0 / 24.0  # mm/day → mm/hr
PA_TO_MBAR = 0.01                  # Pa → mbar


def validate_inputs(source, input_dir, lat, lon, start, end, output_dir):
    """Validate all inputs before processing.

    Returns
    -------
    errors : list[str]
        List of validation error messages.  Empty means OK.
    warnings : list[str]
        Non-fatal issues.
    """
    errors = []
    warnings = []

    # Source type
    valid_sources = {"era5", "cmfd", "mswx", "custom"}
    if source not in valid_sources:
        errors.append(f"Unknown source '{source}'. Valid: {valid_sources}")

    # Input directory
    if not os.path.isdir(input_dir):
        errors.append(f"Input directory does not exist: {input_dir}")

    # Coordinates
    if not (-90 <= lat <= 90):
        errors.append(f"Latitude {lat} out of range [-90, 90]")
    if not (-180 <= lon <= 180):
        errors.append(f"Longitude {lon} out of range [-180, 180]")

    # Date ordering
    if start >= end:
        errors.append(f"Start date {start} must be before end date {end}")

    # Output directory — create if needed
    os.makedirs(output_dir, exist_ok=True)

    return errors, warnings


def read_era5_at_point(input_dir, lat, lon, start, end):
    """Read ERA5 NetCDF files and extract nearest-pixel time series.

    Returns dict with keys: time, P_mmhr, T_air_C, RH_frac, wind_ms,
    p_atm_mbar, Qsw_Wm2.
    """
    try:
        import netCDF4 as nc
    except ImportError:
        raise RuntimeError("netCDF4 required for ERA5 reading. pip install netCDF4")

    nc_files = sorted(Path(input_dir).glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No .nc files found in {input_dir}")

    # Accumulate arrays
    times, precip, t_air, rh, wind, pressure, sw_rad = [], [], [], [], [], [], []

    for fp in nc_files:
        ds = nc.Dataset(str(fp), "r")

        # Find nearest grid cell
        lats = ds.variables.get("latitude", ds.variables.get("lat"))[:]
        lons = ds.variables.get("longitude", ds.variables.get("lon"))[:]
        ilat = int(np.argmin(np.abs(lats - lat)))
        ilon = int(np.argmin(np.abs(lons - lon)))

        time_var = ds.variables.get("time", ds.variables.get("valid_time"))
        n_times = len(time_var)

        for t_idx in range(n_times):
            # Precipitation: tp in kg/m²/s → mm/hr
            if "tp" in ds.variables:
                p_val = float(ds.variables["tp"][t_idx, ilat, ilon])
                precip.append(p_val * ERA5_PRECIP_TO_MMHR)
            elif "mtpr" in ds.variables:
                p_val = float(ds.variables["mtpr"][t_idx, ilat, ilon])
                precip.append(p_val * ERA5_PRECIP_TO_MMHR)
            else:
                precip.append(0.0)

            # Temperature: t2m in K → °C
            if "t2m" in ds.variables:
                t_val = float(ds.variables["t2m"][t_idx, ilat, ilon])
                t_air.append(t_val - KELVIN_OFFSET)
            else:
                t_air.append(20.0)

            # Relative humidity: compute from dewpoint if needed
            if "r" in ds.variables:
                rh_val = float(ds.variables["r"][t_idx, ilat, ilon])
                # ERA5 RH can be 0-100%; convert to fraction
                if rh_val > 1.5:
                    rh_val /= 100.0
                rh.append(np.clip(rh_val, 0.0, 1.0))
            elif "d2m" in ds.variables and "t2m" in ds.variables:
                td = float(ds.variables["d2m"][t_idx, ilat, ilon]) - KELVIN_OFFSET
                ta = t_air[-1]
                rh_val = _rh_from_dewpoint(ta, td)
                rh.append(np.clip(rh_val, 0.0, 1.0))
            else:
                rh.append(0.5)

            # Wind speed
            u10 = float(ds.variables.get("u10", ds.variables.get("wind", [0]))[t_idx, ilat, ilon]) if "u10" in ds.variables else 2.0
            v10 = float(ds.variables["v10"][t_idx, ilat, ilon]) if "v10" in ds.variables else 0.0
            wind.append(np.sqrt(u10**2 + v10**2))

            # Pressure: sp in Pa → mbar
            if "sp" in ds.variables:
                pressure.append(float(ds.variables["sp"][t_idx, ilat, ilon]) * PA_TO_MBAR)
            else:
                pressure.append(1013.25)

            # Shortwave radiation
            if "ssrd" in ds.variables:
                sw_rad.append(max(0.0, float(ds.variables["ssrd"][t_idx, ilat, ilon])))
            elif "ssr" in ds.variables:
                sw_rad.append(max(0.0, float(ds.variables["ssr"][t_idx, ilat, ilon])))
            else:
                sw_rad.append(200.0)

        ds.close()

    return {
        "P_mmhr": np.array(precip),
        "T_air_C": np.array(t_air),
        "RH_frac": np.array(rh),
        "wind_ms": np.array(wind),
        "p_atm_mbar": np.array(pressure),
        "Qsw_Wm2": np.array(sw_rad),
    }


def read_cmfd_at_point(input_dir, lat, lon, start, end):
    """Read CMFD 3-hourly forcing and convert to TopoFlow units."""
    try:
        import netCDF4 as nc
    except ImportError:
        raise RuntimeError("netCDF4 required. pip install netCDF4")

    nc_files = sorted(Path(input_dir).glob("*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No .nc files in {input_dir}")

    precip, t_air, rh, wind, pressure, sw_rad = [], [], [], [], [], []

    for fp in nc_files:
        ds = nc.Dataset(str(fp), "r")
        lats = ds.variables["lat"][:]
        lons = ds.variables["lon"][:]
        ilat = int(np.argmin(np.abs(lats - lat)))
        ilon = int(np.argmin(np.abs(lons - lon)))

        n = ds.dimensions["time"].size
        for t in range(n):
            if "prec" in ds.variables:
                precip.append(float(ds.variables["prec"][t, ilat, ilon]) * CMFD_PRECIP_TO_MMHR)
            if "temp" in ds.variables:
                t_air.append(float(ds.variables["temp"][t, ilat, ilon]))
            if "shum" in ds.variables:
                rh.append(np.clip(float(ds.variables["shum"][t, ilat, ilon]), 0, 1))
            if "wind" in ds.variables:
                wind.append(float(ds.variables["wind"][t, ilat, ilon]))
            if "pres" in ds.variables:
                pressure.append(float(ds.variables["pres"][t, ilat, ilon]) * PA_TO_MBAR)
            if "srad" in ds.variables:
                sw_rad.append(max(0, float(ds.variables["srad"][t, ilat, ilon])))
        ds.close()

    return {
        "P_mmhr": np.array(precip) if precip else np.array([0.0]),
        "T_air_C": np.array(t_air) if t_air else np.array([20.0]),
        "RH_frac": np.array(rh) if rh else np.array([0.5]),
        "wind_ms": np.array(wind) if wind else np.array([2.0]),
        "p_atm_mbar": np.array(pressure) if pressure else np.array([1013.25]),
        "Qsw_Wm2": np.array(sw_rad) if sw_rad else np.array([200.0]),
    }


def _rh_from_dewpoint(t_air_c, t_dew_c):
    """Compute RH fraction from air temp and dewpoint using Tetens formula."""
    es = 6.112 * np.exp(17.67 * t_air_c / (t_air_c + 243.5))
    ea = 6.112 * np.exp(17.67 * t_dew_c / (t_dew_c + 243.5))
    return ea / es if es > 0 else 0.5


def process(source, input_dir, lat, lon, start, end, output_dir, site_prefix):
    """Read forcing, convert units, write TopoFlow time-series files.

    Returns
    -------
    result : dict
        Status, file paths, and conversion summary.
    """
    readers = {
        "era5": read_era5_at_point,
        "cmfd": read_cmfd_at_point,
    }

    if source not in readers:
        return {"status": "error", "message": f"Reader for '{source}' not implemented"}

    data = readers[source](input_dir, lat, lon, start, end)

    # Write each variable to a text file
    files_written = {}
    var_map = {
        "P_mmhr": f"{site_prefix}_rain_rates.txt",
        "T_air_C": f"{site_prefix}_T_air.txt",
        "RH_frac": f"{site_prefix}_RH.txt",
        "wind_ms": f"{site_prefix}_wind.txt",
        "p_atm_mbar": f"{site_prefix}_p_atm.txt",
        "Qsw_Wm2": f"{site_prefix}_Qsw.txt",
    }

    for var_key, filename in var_map.items():
        filepath = os.path.join(output_dir, filename)
        arr = data[var_key]
        np.savetxt(filepath, arr, fmt="%.6f")
        files_written[var_key] = filepath

    return {
        "status": "success",
        "source": source,
        "n_timesteps": len(data["P_mmhr"]),
        "files": files_written,
        "unit_summary": {
            "P": "mm/hr (TopoFlow cfg expects mm/hr)",
            "T_air": "°C",
            "RH": "fraction 0-1",
            "wind": "m/s",
            "p_atm": "mbar",
            "Qsw": "W/m²",
        },
    }


def validate_outputs(output_dir, site_prefix):
    """Post-process validation of written files.

    Returns
    -------
    errors : list[str]
    warnings : list[str]
    """
    errors = []
    warnings = []

    # Check rain rates
    rain_file = os.path.join(output_dir, f"{site_prefix}_rain_rates.txt")
    if os.path.exists(rain_file):
        rain = np.loadtxt(rain_file)
        if rain.max() > 500:
            warnings.append(
                f"Max rain rate = {rain.max():.1f} mm/hr — suspiciously high. "
                "Check unit conversion."
            )
        if rain.max() < 0.001 and rain.sum() > 0:
            warnings.append(
                "Rain rates near zero — may have been pre-converted to m/s. "
                "TopoFlow expects mm/hr in config."
            )
        if np.any(rain < 0):
            errors.append("Negative rain rates found — data corruption.")
    else:
        errors.append(f"Rain file not created: {rain_file}")

    # Check temperature
    t_file = os.path.join(output_dir, f"{site_prefix}_T_air.txt")
    if os.path.exists(t_file):
        t_air = np.loadtxt(t_file)
        if t_air.mean() > 100:
            errors.append(
                f"Mean temperature = {t_air.mean():.1f} °C — "
                "likely still in Kelvin. Subtract 273.15."
            )

    # Check RH
    rh_file = os.path.join(output_dir, f"{site_prefix}_RH.txt")
    if os.path.exists(rh_file):
        rh = np.loadtxt(rh_file)
        if rh.max() > 1.0:
            warnings.append(
                f"Max RH = {rh.max():.2f} — values > 1 suggest percentage "
                "not fraction. TopoFlow needs 0-1 fraction."
            )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert global reanalysis forcing to TopoFlow format"
    )
    parser.add_argument("--source", required=True, choices=["era5", "cmfd", "mswx", "custom"])
    parser.add_argument("--input_dir", required=True, help="Directory with source NetCDF files")
    parser.add_argument("--lat", required=True, type=float, help="Target latitude")
    parser.add_argument("--lon", required=True, type=float, help="Target longitude")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--site_prefix", default="Site", help="Prefix for output files")

    args = parser.parse_args()

    # Validate inputs
    errors, warnings = validate_inputs(
        args.source, args.input_dir, args.lat, args.lon, args.start, args.end, args.output_dir
    )
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    # Process
    result = process(
        args.source, args.input_dir, args.lat, args.lon,
        args.start, args.end, args.output_dir, args.site_prefix
    )

    # Validate outputs
    out_errors, out_warnings = validate_outputs(args.output_dir, args.site_prefix)
    result["output_warnings"] = out_warnings
    if out_errors:
        result["output_errors"] = out_errors
        result["status"] = "error"

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
