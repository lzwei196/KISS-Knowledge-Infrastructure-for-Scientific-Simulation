#!/usr/bin/env python3
"""
convert_forcing_to_elm.py — Convert atmospheric forcing data to ELM/DATM format.

Converts ERA5, GSWP3, or generic CSV/NetCDF forcing data into the NetCDF format
required by ELM's DATM (data atmosphere) component.

Required input variables and their ELM units:
  - Air temperature:       TBOT    [K]       (NOT °C)
  - Precipitation:         PRECTmms [mm/s]   (NOT mm/day, mm/hr, m/day)
  - Specific humidity:     SHUM    [kg/kg]   (NOT %, NOT g/kg)
  - Downwelling shortwave: FSDS    [W/m²]    (total, direct+diffuse)
  - Downwelling longwave:  FLDS    [W/m²]
  - Wind speed:            WIND    [m/s]
  - Surface pressure:      PSRF    [Pa]      (NOT hPa, NOT kPa)

CRITICAL: Unit errors in forcing data are the #1 cause of silent failures in
          land surface models. This tool performs automatic detection and
          conversion of common unit systems.

Usage:
    python convert_forcing_to_elm.py --input forcing.csv --output elm_forcing.nc \\
        --start 2000-01-01 --end 2000-12-31 --lat 40.0 --lon 117.0

    python convert_forcing_to_elm.py --input era5_data.nc --output elm_forcing.nc \\
        --format era5 --start 2000-01-01 --end 2000-12-31
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import netCDF4 as nc4
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TFRZ = 273.15          # Freezing point (K)
SEC_PER_HOUR = 3600.0
SEC_PER_DAY = 86400.0
PA_PER_HPA = 100.0
PA_PER_KPA = 1000.0

# Physically reasonable ranges for ELM forcing variables
VALID_RANGES = {
    "TBOT":     (180.0, 340.0,   "K"),       # Temperature
    "PRECTmms": (0.0,   0.1,     "mm/s"),    # Precipitation (0.1 mm/s = 360 mm/hr extreme)
    "SHUM":     (0.0,   0.06,    "kg/kg"),   # Specific humidity
    "FSDS":     (0.0,   1400.0,  "W/m²"),    # Shortwave radiation
    "FLDS":     (50.0,  600.0,   "W/m²"),    # Longwave radiation
    "WIND":     (0.0,   75.0,    "m/s"),      # Wind speed
    "PSRF":     (30000, 110000,  "Pa"),       # Surface pressure
}

# Common ERA5 variable name mappings
ERA5_MAPPING = {
    "t2m":   "TBOT",
    "tp":    "PRECTmms",
    "d2m":   "SHUM",       # Dewpoint → needs conversion
    "ssrd":  "FSDS",
    "strd":  "FLDS",
    "u10":   "WIND_U",
    "v10":   "WIND_V",
    "sp":    "PSRF",
}


# ---------------------------------------------------------------------------
# Unit detection and conversion
# ---------------------------------------------------------------------------
def detect_temperature_units(temp_arr):
    """Detect whether temperature is in K or °C.

    CRITICAL (dt_001): ELM requires K. Passing °C causes the model to compute
    with values ~273 K too low, resulting in unrealistic energy balance,
    perpetual snow/ice, and often model crashes.
    """
    median_val = np.nanmedian(temp_arr)
    if -80 < median_val < 70:
        return "celsius"
    elif 180 < median_val < 340:
        return "kelvin"
    else:
        return "unknown"


def detect_precip_units(precip_arr, timestep_seconds):
    """Detect precipitation units: mm/s, mm/hr, mm/day, or m/day.

    CRITICAL (dt_002): ELM expects mm/s. Using mm/day introduces a 86400x
    scaling error → either massive flooding or near-zero precipitation.
    """
    max_val = np.nanmax(precip_arr)
    mean_val = np.nanmean(precip_arr[precip_arr > 0]) if np.any(precip_arr > 0) else 0

    if max_val > 10 and mean_val > 1:
        return "mm_per_day"   # Typical ERA5 daily totals: 0-50 mm/day
    elif max_val > 0.5 and mean_val > 0.05:
        return "mm_per_hour"  # Hourly: 0-20 mm/hr
    elif max_val < 0.1:
        return "mm_per_second"  # Already correct
    elif max_val < 0.001:
        return "m_per_day"    # Rare but dangerous
    else:
        return "mm_per_second"  # Assume correct if ambiguous


def detect_humidity_units(q_arr):
    """Detect humidity: kg/kg, g/kg, or relative humidity (%).

    CRITICAL (dt_003): ELM expects specific humidity in kg/kg. Using RH (0-100)
    instead causes the model to compute wildly wrong latent heat fluxes.
    """
    max_val = np.nanmax(q_arr)
    if max_val > 1.0 and max_val <= 100.0:
        return "relative_humidity_percent"
    elif max_val > 0.1 and max_val <= 1.0:
        return "relative_humidity_fraction"
    elif max_val > 0.06:
        return "g_per_kg"
    else:
        return "kg_per_kg"


def detect_pressure_units(p_arr):
    """Detect pressure: Pa, hPa, or kPa.

    CRITICAL (dt_004): ELM expects Pa. Using hPa (100x smaller) causes wrong
    air density computation → bad turbulent flux calculations.
    """
    median_val = np.nanmedian(p_arr)
    if 800 < median_val < 1100:
        return "hPa"
    elif 80 < median_val < 115:
        return "kPa"
    elif 30000 < median_val < 110000:
        return "Pa"
    else:
        return "unknown"


def celsius_to_kelvin(temp_c):
    """Convert °C to K."""
    return temp_c + TFRZ


def precip_to_mm_per_s(precip, source_unit, timestep_seconds=None):
    """Convert precipitation to mm/s."""
    if source_unit == "mm_per_day":
        return precip / SEC_PER_DAY
    elif source_unit == "mm_per_hour":
        return precip / SEC_PER_HOUR
    elif source_unit == "m_per_day":
        return precip * 1000.0 / SEC_PER_DAY
    elif source_unit == "mm_per_second":
        return precip
    else:
        return precip


def rh_to_specific_humidity(rh, temp_k, pressure_pa):
    """Convert relative humidity to specific humidity (kg/kg).

    Uses the August-Roche-Magnus formula for saturation vapor pressure.
    """
    temp_c = temp_k - TFRZ
    # Saturation vapor pressure (Pa)
    e_sat = 610.94 * np.exp(17.625 * temp_c / (temp_c + 243.04))

    if np.nanmax(rh) > 1.5:
        rh_frac = rh / 100.0  # Convert from % to fraction
    else:
        rh_frac = rh

    rh_frac = np.clip(rh_frac, 0.0, 1.0)
    e = rh_frac * e_sat
    # Specific humidity
    q = 0.622 * e / (pressure_pa - 0.378 * e)
    return np.clip(q, 0.0, 0.06)


def dewpoint_to_specific_humidity(td_k, pressure_pa):
    """Convert dewpoint temperature (K) to specific humidity (kg/kg)."""
    td_c = td_k - TFRZ
    e = 610.94 * np.exp(17.625 * td_c / (td_c + 243.04))
    q = 0.622 * e / (pressure_pa - 0.378 * e)
    return np.clip(q, 0.0, 0.06)


def pressure_to_pa(p, source_unit):
    """Convert pressure to Pa."""
    if source_unit == "hPa":
        return p * PA_PER_HPA
    elif source_unit == "kPa":
        return p * PA_PER_KPA
    else:
        return p


def wind_components_to_speed(u, v):
    """Convert u, v wind components to speed magnitude."""
    return np.sqrt(u**2 + v**2)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate all command-line arguments before processing."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.format not in ("csv", "era5", "netcdf", "auto"):
        errors.append(f"Unsupported format: {args.format}")

    try:
        datetime.strptime(args.start, "%Y-%m-%d")
        datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        errors.append("Dates must be in YYYY-MM-DD format")

    if args.lat is not None and not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if args.lon is not None and not (-360 <= args.lon <= 360):
        errors.append(f"Longitude out of range: {args.lon}")

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)


def validate_outputs(data_dict, warnings):
    """Post-processing validation of converted data.

    Checks all variables against physically reasonable ranges.
    """
    for varname, (vmin, vmax, unit) in VALID_RANGES.items():
        if varname in data_dict:
            arr = data_dict[varname]
            actual_min = float(np.nanmin(arr))
            actual_max = float(np.nanmax(arr))

            if actual_min < vmin or actual_max > vmax:
                warnings.append(
                    f"{varname}: range [{actual_min:.4f}, {actual_max:.4f}] "
                    f"outside expected [{vmin}, {vmax}] {unit}"
                )

            nan_frac = float(np.isnan(arr).sum()) / len(arr)
            if nan_frac > 0.1:
                warnings.append(
                    f"{varname}: {nan_frac*100:.1f}% NaN values"
                )

    return warnings


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def read_csv_forcing(filepath):
    """Read forcing from CSV file.

    Expected columns: time, tair, precip, humidity, swdown, lwdown, wind, pressure
    """
    df = pd.read_csv(filepath, parse_dates=["time"])
    df = df.set_index("time").sort_index()
    return df


def read_era5_netcdf(filepath):
    """Read ERA5 NetCDF forcing data."""
    if not HAS_NETCDF:
        raise ImportError("netCDF4 required for NetCDF input. pip install netCDF4")

    ds = nc4.Dataset(filepath, "r")
    data = {}
    times = nc4.num2date(ds.variables["time"][:], ds.variables["time"].units)

    for era5_name, elm_name in ERA5_MAPPING.items():
        if era5_name in ds.variables:
            data[elm_name] = np.array(ds.variables[era5_name][:]).flatten()

    ds.close()
    data["time"] = pd.DatetimeIndex(times)
    return data


def write_elm_netcdf(output_path, data_dict, times, lat, lon):
    """Write forcing data in DATM-compatible NetCDF format."""
    if not HAS_NETCDF:
        raise ImportError("netCDF4 required for NetCDF output. pip install netCDF4")

    ds = nc4.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("time", None)  # Unlimited
    ds.createDimension("lat", 1)
    ds.createDimension("lon", 1)
    ds.createDimension("scalar", 1)

    # Time variable
    time_var = ds.createVariable("time", "f8", ("time",))
    time_var.units = f"days since {times[0].strftime('%Y-%m-%d')} 00:00:00"
    time_var.calendar = "noleap"
    ref_date = times[0]
    time_var[:] = np.array([(t - ref_date).total_seconds() / SEC_PER_DAY
                            for t in times])

    # Coordinate variables
    lat_var = ds.createVariable("LATIXY", "f8", ("lat", "lon"))
    lat_var.units = "degrees_north"
    lat_var[:] = lat

    lon_var = ds.createVariable("LONGXY", "f8", ("lat", "lon"))
    lon_var.units = "degrees_east"
    lon_var[:] = lon if lon >= 0 else lon + 360.0

    # Edge variables required by DATM
    for edge_name in ["EDGEN", "EDGES", "EDGEE", "EDGEW"]:
        edge_var = ds.createVariable(edge_name, "f8", ("scalar",))
        if "N" in edge_name:
            edge_var[:] = lat + 0.5
        elif "S" in edge_name:
            edge_var[:] = lat - 0.5
        elif "E" in edge_name:
            edge_var[:] = (lon + 0.5) if lon >= 0 else (lon + 360.5)
        else:
            edge_var[:] = (lon - 0.5) if lon >= 0 else (lon + 359.5)

    # Forcing variables
    elm_vars = {
        "TBOT":     ("f4", "K",     "temperature at the lowest atm level"),
        "PRECTmms": ("f4", "mm/s",  "total precipitation"),
        "SHUM":     ("f4", "kg/kg", "specific humidity at the lowest atm level"),
        "FSDS":     ("f4", "W/m2",  "total incident shortwave radiation"),
        "FLDS":     ("f4", "W/m2",  "incident longwave radiation"),
        "WIND":     ("f4", "m/s",   "wind speed at the lowest atm level"),
        "PSRF":     ("f4", "Pa",    "surface pressure"),
    }

    for varname, (dtype, units, long_name) in elm_vars.items():
        if varname in data_dict:
            var = ds.createVariable(varname, dtype, ("time", "lat", "lon"),
                                    fill_value=-9999.0)
            var.units = units
            var.long_name = long_name
            var[:, 0, 0] = data_dict[varname]

    # Global attributes
    ds.title = "ELM/DATM forcing data"
    ds.conventions = "CF-1.6"
    ds.history = f"Created {datetime.now().isoformat()} by convert_forcing_to_elm.py"
    ds.source = "Converted from external forcing dataset"

    ds.close()


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Main conversion pipeline: read → detect units → convert → validate → write."""
    warnings = []
    conversions = {}

    # --- Read input ---
    if args.format == "csv" or (args.format == "auto" and args.input.endswith(".csv")):
        df = read_csv_forcing(args.input)
        col_map = {
            "tair": "TBOT", "precip": "PRECTmms", "humidity": "SHUM",
            "swdown": "FSDS", "lwdown": "FLDS", "wind": "WIND",
            "pressure": "PSRF",
        }
        data = {}
        for csv_col, elm_name in col_map.items():
            if csv_col in df.columns:
                data[elm_name] = df[csv_col].values
        times = df.index

    elif args.format == "era5" or (args.format == "auto" and args.input.endswith(".nc")):
        raw = read_era5_netcdf(args.input)
        times = raw.pop("time")
        data = raw
    else:
        return {"status": "error", "errors": [f"Cannot auto-detect format for {args.input}"]}

    # --- Detect and convert units ---

    # Temperature
    if "TBOT" in data:
        t_unit = detect_temperature_units(data["TBOT"])
        if t_unit == "celsius":
            data["TBOT"] = celsius_to_kelvin(data["TBOT"])
            conversions["TBOT"] = "°C → K (+273.15)"
            warnings.append("Temperature detected as °C, converted to K (dt_001)")

    # Pressure (convert before humidity, since q depends on P)
    if "PSRF" in data:
        p_unit = detect_pressure_units(data["PSRF"])
        if p_unit != "Pa":
            data["PSRF"] = pressure_to_pa(data["PSRF"], p_unit)
            conversions["PSRF"] = f"{p_unit} → Pa"
            warnings.append(f"Pressure detected as {p_unit}, converted to Pa (dt_004)")

    # Humidity
    if "SHUM" in data:
        q_unit = detect_humidity_units(data["SHUM"])
        if q_unit in ("relative_humidity_percent", "relative_humidity_fraction"):
            if "TBOT" in data and "PSRF" in data:
                data["SHUM"] = rh_to_specific_humidity(
                    data["SHUM"], data["TBOT"], data["PSRF"]
                )
                conversions["SHUM"] = f"{q_unit} → kg/kg"
                warnings.append(f"Humidity detected as {q_unit}, converted to kg/kg (dt_003)")
            else:
                warnings.append("Cannot convert RH without temperature and pressure")
        elif q_unit == "g_per_kg":
            data["SHUM"] = data["SHUM"] / 1000.0
            conversions["SHUM"] = "g/kg → kg/kg"

    # Dewpoint (ERA5) → specific humidity
    if "SHUM" not in data and "d2m" in data:
        if "PSRF" in data:
            data["SHUM"] = dewpoint_to_specific_humidity(data["d2m"], data["PSRF"])
            conversions["SHUM"] = "dewpoint K → kg/kg"
        else:
            warnings.append("Cannot convert dewpoint without pressure")

    # Precipitation
    if "PRECTmms" in data:
        # Estimate timestep from time array
        if len(times) > 1:
            dt_sec = (times[1] - times[0]).total_seconds()
        else:
            dt_sec = 3600.0
        p_unit = detect_precip_units(data["PRECTmms"], dt_sec)
        if p_unit != "mm_per_second":
            data["PRECTmms"] = precip_to_mm_per_s(data["PRECTmms"], p_unit)
            conversions["PRECTmms"] = f"{p_unit} → mm/s"
            warnings.append(f"Precipitation detected as {p_unit}, converted to mm/s (dt_002)")

    # Wind components → speed
    if "WIND" not in data and "WIND_U" in data and "WIND_V" in data:
        data["WIND"] = wind_components_to_speed(data["WIND_U"], data["WIND_V"])
        conversions["WIND"] = "u,v components → speed"
        del data["WIND_U"]
        del data["WIND_V"]

    # Ensure precipitation is non-negative
    if "PRECTmms" in data:
        data["PRECTmms"] = np.clip(data["PRECTmms"], 0.0, None)

    # --- Validate output ranges ---
    warnings = validate_outputs(data, warnings)

    # --- Write output ---
    lat = args.lat if args.lat is not None else 0.0
    lon = args.lon if args.lon is not None else 0.0

    if args.output.endswith(".nc"):
        write_elm_netcdf(args.output, data, times, lat, lon)
    else:
        # Write CSV fallback
        out_df = pd.DataFrame(data)
        out_df.index = times[:len(out_df)]
        out_df.to_csv(args.output)

    # --- Build result ---
    result = {
        "status": "success",
        "output_file": args.output,
        "n_timesteps": len(times),
        "start": str(times[0]),
        "end": str(times[-1]),
        "variables_written": list(data.keys()),
        "unit_conversions": conversions,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert atmospheric forcing data to ELM/DATM format"
    )
    parser.add_argument("--input", required=True, help="Input forcing file (CSV or NetCDF)")
    parser.add_argument("--output", required=True, help="Output NetCDF file path")
    parser.add_argument("--format", default="auto",
                        choices=["csv", "era5", "netcdf", "auto"],
                        help="Input format (default: auto-detect)")
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--lat", type=float, default=None, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude (degrees)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))

    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
