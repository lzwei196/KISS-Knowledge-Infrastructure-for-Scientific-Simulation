#!/usr/bin/env python3
"""
convert_forcing_to_clm.py — Convert atmospheric forcing data to CLM5 DATM format.

Reads reanalysis or station forcing data (ERA5, GSWP3, CRUJRA, CMFD, or generic
CSV/NetCDF) and writes DATM-compatible NetCDF streams for CLM5.

CRITICAL UNIT CONVERSIONS:
  - Precipitation: input mm/day or mm/hr → output kg/m²/s (divide by 86400 or 3600)
  - Temperature: input °C → output K (add 273.15)
  - Specific humidity: input RH% → output kg/kg via Tetens equation
  - Wind speed: may need height correction from 10m to reference height
  - Longwave: must be downward (positive), NOT net or upward

CLM5 DATM streams expect each forcing variable in separate NetCDF files or
combined files with specific variable names:
  - TBOT (K), QBOT (kg/kg), WIND (m/s), PRECTmms (mm/s = kg/m²/s),
    FSDS (W/m²), FLDS (W/m²), PSRF (Pa)

Usage:
    python convert_forcing_to_clm.py --source era5 --input /path/to/data.nc \\
        --output /path/to/datm/ --start-year 2000 --end-year 2010
    python convert_forcing_to_clm.py --source csv --input /path/to/station.csv \\
        --output /path/to/datm/ --lat 40.0 --lon 116.0
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np

try:
    import xarray as xr
except ImportError:
    xr = None

try:
    import pandas as pd
except ImportError:
    pd = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
SECONDS_PER_DAY = 86400.0
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_3HR = 10800.0

# Expected CLM5 DATM variable names
CLM_VARS = {
    "temperature": "TBOT",       # K
    "specific_humidity": "QBOT", # kg/kg
    "wind_speed": "WIND",        # m/s
    "precipitation": "PRECTmms", # mm/s = kg/m2/s
    "shortwave": "FSDS",         # W/m2
    "longwave": "FLDS",          # W/m2
    "pressure": "PSRF",          # Pa
}

# Source-specific variable mappings
SOURCE_MAPS = {
    "era5": {
        "t2m": "temperature",
        "d2m": "dewpoint",
        "tp": "precipitation",
        "ssrd": "shortwave",
        "strd": "longwave",
        "sp": "pressure",
        "u10": "u_wind",
        "v10": "v_wind",
    },
    "gswp3": {
        "Tair": "temperature",
        "Qair": "specific_humidity",
        "Wind": "wind_speed",
        "Precip": "precipitation",
        "SWdown": "shortwave",
        "LWdown": "longwave",
        "PSurf": "pressure",
    },
    "crujra": {
        "tmp": "temperature",
        "spfh": "specific_humidity",
        "ugrd": "u_wind",
        "vgrd": "v_wind",
        "pre": "precipitation",
        "dswrf": "shortwave",
        "dlwrf": "longwave",
        "pres": "pressure",
    },
    "csv": {
        "temperature": "temperature",
        "humidity": "specific_humidity",
        "wind_speed": "wind_speed",
        "precipitation": "precipitation",
        "shortwave": "shortwave",
        "longwave": "longwave",
        "pressure": "pressure",
    },
}


def validate_inputs(args):
    """Validate input arguments and data availability."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input path does not exist: {args.input}")

    if args.source not in SOURCE_MAPS:
        errors.append(
            f"Unknown source '{args.source}'. "
            f"Supported: {', '.join(SOURCE_MAPS.keys())}"
        )

    if args.start_year and args.end_year:
        if args.start_year > args.end_year:
            errors.append("start-year must be <= end-year")

    if args.source == "csv":
        if args.lat is None or args.lon is None:
            errors.append("--lat and --lon required for CSV source")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def celsius_to_kelvin(t_c):
    """Convert temperature from Celsius to Kelvin."""
    return t_c + KELVIN_OFFSET


def dewpoint_to_specific_humidity(td_k, p_pa):
    """Convert dewpoint temperature (K) and pressure (Pa) to specific humidity (kg/kg).

    Uses the Tetens formula for saturation vapor pressure:
        es = 611.2 * exp(17.67 * (T - 273.15) / (T - 29.65))
        q = 0.622 * es / (p - 0.378 * es)
    """
    td_c = td_k - KELVIN_OFFSET
    es = 611.2 * np.exp(17.67 * td_c / (td_c + 243.5))
    q = 0.622 * es / (p_pa - 0.378 * es)
    return np.clip(q, 0.0, 0.06)


def rh_to_specific_humidity(rh_pct, t_k, p_pa):
    """Convert relative humidity (%) to specific humidity (kg/kg).

    Uses the Tetens formula for saturation vapor pressure.
    """
    t_c = t_k - KELVIN_OFFSET
    es = 611.2 * np.exp(17.67 * t_c / (t_c + 243.5))
    e = (rh_pct / 100.0) * es
    q = 0.622 * e / (p_pa - 0.378 * e)
    return np.clip(q, 0.0, 0.06)


def compute_wind_speed(u, v):
    """Compute wind speed from u and v components."""
    return np.sqrt(u**2 + v**2)


def convert_precip(precip, source, timestep_seconds):
    """Convert precipitation to kg/m2/s.

    Different sources provide precipitation in different units:
      - ERA5: m/timestep (accumulated) → need / timestep_seconds * 1000
      - GSWP3: kg/m2/s (already correct)
      - CRUJRA: mm/6hr → / 21600
      - CSV: mm/day → / 86400
    """
    if source == "era5":
        # ERA5 total precipitation is in meters accumulated per timestep
        return precip * 1000.0 / timestep_seconds
    elif source == "gswp3":
        # Already in kg/m2/s
        return precip
    elif source == "crujra":
        # mm per 6 hours
        return precip / (6.0 * SECONDS_PER_HOUR)
    elif source == "csv":
        # Assume mm/day
        return precip / SECONDS_PER_DAY
    else:
        warnings.warn(f"Unknown source {source}, assuming precip in mm/day")
        return precip / SECONDS_PER_DAY


def convert_shortwave(sw, source, timestep_seconds):
    """Convert shortwave radiation to W/m2.

    ERA5 provides accumulated J/m2 per timestep; others provide W/m2.
    """
    if source == "era5":
        return sw / timestep_seconds
    return sw


def convert_longwave(lw, source, timestep_seconds):
    """Convert longwave radiation to downward W/m2.

    ERA5 provides accumulated J/m2 per timestep; others provide W/m2.
    CRITICAL: Must be DOWNWARD longwave, not net or upward.
    """
    if source == "era5":
        return lw / timestep_seconds
    return lw


def process_era5(ds, args):
    """Process ERA5 NetCDF dataset to CLM5 DATM variables."""
    result = {}
    vmap = SOURCE_MAPS["era5"]

    # Determine timestep
    times = ds["time"].values
    if len(times) > 1:
        dt_ns = np.diff(times[:2])[0]
        timestep_s = float(dt_ns) / 1e9
    else:
        timestep_s = SECONDS_PER_HOUR  # default 1hr for ERA5

    # Temperature (ERA5: K already)
    if "t2m" in ds:
        t_k = ds["t2m"].values
        if np.nanmean(t_k) < 200:
            # Likely Celsius
            t_k = celsius_to_kelvin(t_k)
        result["TBOT"] = t_k

    # Humidity from dewpoint
    if "d2m" in ds and "sp" in ds:
        td_k = ds["d2m"].values
        p_pa = ds["sp"].values
        if np.nanmean(td_k) < 200:
            td_k = celsius_to_kelvin(td_k)
        result["QBOT"] = dewpoint_to_specific_humidity(td_k, p_pa)

    # Wind speed from u, v components
    if "u10" in ds and "v10" in ds:
        result["WIND"] = compute_wind_speed(
            ds["u10"].values, ds["v10"].values
        )

    # Precipitation
    if "tp" in ds:
        result["PRECTmms"] = convert_precip(
            ds["tp"].values, "era5", timestep_s
        )

    # Radiation
    if "ssrd" in ds:
        result["FSDS"] = convert_shortwave(
            ds["ssrd"].values, "era5", timestep_s
        )
    if "strd" in ds:
        result["FLDS"] = convert_longwave(
            ds["strd"].values, "era5", timestep_s
        )

    # Pressure
    if "sp" in ds:
        result["PSRF"] = ds["sp"].values

    return result, times


def process_gswp3(ds, args):
    """Process GSWP3 NetCDF dataset — already in correct units."""
    result = {}
    vmap = SOURCE_MAPS["gswp3"]

    times = ds["time"].values

    for src_var, internal_name in vmap.items():
        if src_var in ds:
            clm_name = CLM_VARS.get(internal_name)
            if clm_name:
                result[clm_name] = ds[src_var].values

    # Temperature check
    if "TBOT" in result and np.nanmean(result["TBOT"]) < 200:
        result["TBOT"] = celsius_to_kelvin(result["TBOT"])

    return result, times


def process_csv(filepath, args):
    """Process CSV station data to CLM5 DATM variables.

    Expected columns: datetime, temperature(C), humidity(%), wind_speed(m/s),
    precipitation(mm/day), shortwave(W/m2), longwave(W/m2), pressure(Pa)
    """
    df = pd.read_csv(filepath, parse_dates=["datetime"])

    result = {}
    times = df["datetime"].values

    # Temperature: C → K
    if "temperature" in df.columns:
        t_vals = df["temperature"].values
        if np.nanmean(t_vals) < 100:  # Celsius
            result["TBOT"] = celsius_to_kelvin(t_vals)
        else:
            result["TBOT"] = t_vals

    # Pressure
    p_pa = df["pressure"].values if "pressure" in df.columns else np.full(len(df), 101325.0)
    result["PSRF"] = p_pa

    # Humidity: RH% → specific humidity
    if "humidity" in df.columns:
        rh = df["humidity"].values
        t_k = result.get("TBOT", np.full(len(df), 288.0))
        result["QBOT"] = rh_to_specific_humidity(rh, t_k, p_pa)

    # Wind
    if "wind_speed" in df.columns:
        result["WIND"] = df["wind_speed"].values

    # Precipitation: mm/day → kg/m2/s
    if "precipitation" in df.columns:
        result["PRECTmms"] = convert_precip(
            df["precipitation"].values, "csv", SECONDS_PER_DAY
        )

    # Radiation
    if "shortwave" in df.columns:
        result["FSDS"] = np.maximum(df["shortwave"].values, 0.0)
    if "longwave" in df.columns:
        result["FLDS"] = df["longwave"].values

    return result, times


def process(args):
    """Main processing: read source data, convert, write DATM NetCDF."""
    if args.source in ("era5", "gswp3", "crujra"):
        if xr is None:
            print(json.dumps({
                "status": "error",
                "errors": ["xarray required for NetCDF processing"]
            }))
            sys.exit(1)
        ds = xr.open_dataset(args.input)

        if args.source == "era5":
            data, times = process_era5(ds, args)
        elif args.source == "gswp3":
            data, times = process_gswp3(ds, args)
        else:
            data, times = process_gswp3(ds, args)  # CRUJRA similar structure

        ds.close()

    elif args.source == "csv":
        if pd is None:
            print(json.dumps({
                "status": "error",
                "errors": ["pandas required for CSV processing"]
            }))
            sys.exit(1)
        data, times = process_csv(args.input, args)

    else:
        print(json.dumps({
            "status": "error",
            "errors": [f"Source {args.source} not implemented"]
        }))
        sys.exit(1)

    return data, times


def validate_outputs(data):
    """Validate converted forcing data for physical reasonableness."""
    warnings_list = []

    if "TBOT" in data:
        t = data["TBOT"]
        if np.any(np.isfinite(t)):
            t_mean = np.nanmean(t)
            if t_mean < 200:
                warnings_list.append(
                    f"Mean temperature {t_mean:.1f} K seems too low — "
                    "check if Celsius was not converted"
                )
            if t_mean > 350:
                warnings_list.append(
                    f"Mean temperature {t_mean:.1f} K seems too high"
                )

    if "QBOT" in data:
        q = data["QBOT"]
        if np.any(np.isfinite(q)):
            q_max = np.nanmax(q)
            if q_max > 0.05:
                warnings_list.append(
                    f"Max specific humidity {q_max:.4f} kg/kg > 0.05 — "
                    "check if RH was used instead of q"
                )

    if "PRECTmms" in data:
        p = data["PRECTmms"]
        if np.any(np.isfinite(p)):
            p_max = np.nanmax(p)
            if p_max > 0.1:
                warnings_list.append(
                    f"Max precip rate {p_max:.4f} kg/m2/s > 0.1 — "
                    "check unit conversion (should be mm/s)"
                )
            if np.any(p < 0):
                warnings_list.append("Negative precipitation values detected")

    if "FSDS" in data:
        sw = data["FSDS"]
        if np.any(np.isfinite(sw)):
            if np.any(sw < 0):
                warnings_list.append("Negative shortwave radiation detected")
            if np.nanmax(sw) > 1500:
                warnings_list.append(
                    f"Max shortwave {np.nanmax(sw):.0f} W/m2 > 1500"
                )

    if "FLDS" in data:
        lw = data["FLDS"]
        if np.any(np.isfinite(lw)):
            lw_mean = np.nanmean(lw)
            if lw_mean < 50 or lw_mean > 600:
                warnings_list.append(
                    f"Mean longwave {lw_mean:.0f} W/m2 outside 50-600 range"
                )

    return warnings_list


def write_datm_netcdf(data, times, output_dir, lat=None, lon=None):
    """Write DATM-compatible NetCDF files."""
    if xr is None:
        # Fallback: write CSV summary
        csv_path = os.path.join(output_dir, "forcing_summary.csv")
        rows = []
        n = len(times) if hasattr(times, '__len__') else 0
        for i in range(min(n, 10)):
            row = {"time": str(times[i])}
            for var_name, values in data.items():
                if hasattr(values, '__len__') and len(values) > i:
                    row[var_name] = float(values[i])
            rows.append(row)
        if pd is not None:
            pd.DataFrame(rows).to_csv(csv_path, index=False)
        return csv_path

    os.makedirs(output_dir, exist_ok=True)

    lat_val = lat if lat is not None else 0.0
    lon_val = lon if lon is not None else 0.0

    for var_name, values in data.items():
        if values is None:
            continue

        # Flatten spatial dims if needed
        if values.ndim > 1:
            values = values.reshape(len(times), -1)[:, 0]

        ds_out = xr.Dataset(
            {
                var_name: xr.DataArray(
                    values.reshape(-1, 1, 1),
                    dims=["time", "lat", "lon"],
                    attrs={"units": _get_units(var_name)},
                )
            },
            coords={
                "time": times,
                "lat": [lat_val],
                "lon": [lon_val],
            },
        )

        fname = f"clmforc.{var_name}.nc"
        fpath = os.path.join(output_dir, fname)
        ds_out.to_netcdf(fpath)

    return output_dir


def _get_units(var_name):
    """Return CF-convention units for CLM5 DATM variables."""
    units_map = {
        "TBOT": "K",
        "QBOT": "kg/kg",
        "WIND": "m/s",
        "PRECTmms": "mm/s",
        "FSDS": "W/m2",
        "FLDS": "W/m2",
        "PSRF": "Pa",
    }
    return units_map.get(var_name, "unknown")


def main():
    parser = argparse.ArgumentParser(
        description="Convert atmospheric forcing data to CLM5 DATM format"
    )
    parser.add_argument(
        "--source", type=str, required=True,
        choices=["era5", "gswp3", "crujra", "csv"],
        help="Forcing data source type"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Input file or directory path"
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Output directory for DATM NetCDF files"
    )
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--lat", type=float, default=None, help="Latitude")
    parser.add_argument("--lon", type=float, default=None, help="Longitude")

    args = parser.parse_args()

    validate_inputs(args)
    data, times = process(args)
    warnings_list = validate_outputs(data)

    os.makedirs(args.output, exist_ok=True)
    output_path = write_datm_netcdf(
        data, times, args.output, lat=args.lat, lon=args.lon
    )

    result = {
        "status": "success",
        "source": args.source,
        "output_dir": args.output,
        "variables_converted": list(data.keys()),
        "n_timesteps": len(times) if hasattr(times, '__len__') else 0,
        "warnings": warnings_list,
    }

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
