#!/usr/bin/env python3
"""
convert_forcing_to_esmf.py — Convert meteorological forcing data to ESMF-compatible NetCDF.

Supports conversion from:
  - CMFD (China Meteorological Forcing Dataset)
  - ERA5 reanalysis
  - MSWX (Multi-Source Weather)
  - Generic CSV timeseries

Applies unit conversions to CF-convention standards expected by ESMF-based models.

Pipeline stage: s4_forcing
Pattern: validate → process → validate

Usage:
    python convert_forcing_to_esmf.py \
        --input forcing_raw.csv \
        --source-format cmfd \
        --output forcing_esmf.nc \
        --start-date 2000-01-01 \
        --end-date 2010-12-31
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit conversion tables
# ---------------------------------------------------------------------------
# ESMF / CF convention standard units for meteorological variables:
#   Temperature:     K (Kelvin)
#   Pressure:        Pa (Pascal)
#   Wind:            m/s
#   Precipitation:   kg/m²/s (= mm/s for water)
#   Radiation:       W/m²
#   Specific humidity: kg/kg
#   Relative humidity: fraction (0–1) — TRAP: not percentage!

UNIT_CONVERSIONS = {
    "temperature": {
        "C_to_K": lambda x: x + 273.15,
        "F_to_K": lambda x: (x - 32) * 5.0 / 9.0 + 273.15,
        "K_to_K": lambda x: x,
    },
    "pressure": {
        "hPa_to_Pa": lambda x: x * 100.0,
        "kPa_to_Pa": lambda x: x * 1000.0,
        "mbar_to_Pa": lambda x: x * 100.0,
        "Pa_to_Pa": lambda x: x,
    },
    "precipitation": {
        "mm_day_to_kg_m2_s": lambda x: x / 86400.0,
        "mm_hr_to_kg_m2_s": lambda x: x / 3600.0,
        "mm_s_to_kg_m2_s": lambda x: x,  # 1 mm/s = 1 kg/m²/s (water)
        "m_day_to_kg_m2_s": lambda x: x * 1000.0 / 86400.0,
        "kg_m2_s_to_kg_m2_s": lambda x: x,
    },
    "radiation": {
        "MJ_m2_day_to_W_m2": lambda x: x * 1e6 / 86400.0,
        "W_m2_to_W_m2": lambda x: x,
        "cal_cm2_min_to_W_m2": lambda x: x * 697.3,
    },
    "humidity": {
        "percent_to_fraction": lambda x: x / 100.0,
        "fraction_to_fraction": lambda x: x,
        "g_kg_to_kg_kg": lambda x: x / 1000.0,
        "kg_kg_to_kg_kg": lambda x: x,
    },
    "wind": {
        "m_s_to_m_s": lambda x: x,
        "km_hr_to_m_s": lambda x: x / 3.6,
        "knots_to_m_s": lambda x: x * 0.514444,
    },
}


# ---------------------------------------------------------------------------
# Source format specifications
# ---------------------------------------------------------------------------
SOURCE_FORMATS = {
    "cmfd": {
        "description": "China Meteorological Forcing Dataset",
        "variables": {
            "tmp": {"cf_name": "air_temperature", "source_unit": "K", "conv": "K_to_K", "category": "temperature"},
            "pre": {"cf_name": "precipitation_flux", "source_unit": "mm/hr", "conv": "mm_hr_to_kg_m2_s", "category": "precipitation"},
            "shum": {"cf_name": "specific_humidity", "source_unit": "kg/kg", "conv": "kg_kg_to_kg_kg", "category": "humidity"},
            "pres": {"cf_name": "surface_air_pressure", "source_unit": "Pa", "conv": "Pa_to_Pa", "category": "pressure"},
            "dswrf": {"cf_name": "surface_downwelling_shortwave_flux_in_air", "source_unit": "W/m²", "conv": "W_m2_to_W_m2", "category": "radiation"},
            "dlwrf": {"cf_name": "surface_downwelling_longwave_flux_in_air", "source_unit": "W/m²", "conv": "W_m2_to_W_m2", "category": "radiation"},
            "wind": {"cf_name": "wind_speed", "source_unit": "m/s", "conv": "m_s_to_m_s", "category": "wind"},
        },
        "time_step_hours": 3,
    },
    "era5": {
        "description": "ECMWF ERA5 Reanalysis",
        "variables": {
            "t2m": {"cf_name": "air_temperature", "source_unit": "K", "conv": "K_to_K", "category": "temperature"},
            "tp": {"cf_name": "precipitation_flux", "source_unit": "m/day", "conv": "m_day_to_kg_m2_s", "category": "precipitation"},
            "sp": {"cf_name": "surface_air_pressure", "source_unit": "Pa", "conv": "Pa_to_Pa", "category": "pressure"},
            "ssrd": {"cf_name": "surface_downwelling_shortwave_flux_in_air", "source_unit": "MJ/m²/day", "conv": "MJ_m2_day_to_W_m2", "category": "radiation"},
            "strd": {"cf_name": "surface_downwelling_longwave_flux_in_air", "source_unit": "MJ/m²/day", "conv": "MJ_m2_day_to_W_m2", "category": "radiation"},
            "u10": {"cf_name": "eastward_wind", "source_unit": "m/s", "conv": "m_s_to_m_s", "category": "wind"},
            "v10": {"cf_name": "northward_wind", "source_unit": "m/s", "conv": "m_s_to_m_s", "category": "wind"},
        },
        "time_step_hours": 1,
    },
    "csv": {
        "description": "Generic CSV with header row",
        "variables": {},
        "time_step_hours": None,
    },
}


def validate_input(input_path: str, source_format: str) -> dict:
    """Validate input forcing file and source format."""
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input forcing file not found: {input_path}")

    if source_format not in SOURCE_FORMATS:
        raise ValueError(f"Unknown source format '{source_format}'. "
                         f"Supported: {list(SOURCE_FORMATS.keys())}")

    size = os.path.getsize(input_path)
    if size == 0:
        raise ValueError(f"Input file is empty: {input_path}")

    logger.info("Input validated: %s (%.1f MB, format=%s)", input_path, size / 1e6, source_format)
    return {"path": input_path, "format": source_format, "size_bytes": size}


def apply_unit_conversion(data: np.ndarray, category: str, conversion: str,
                          var_name: str) -> np.ndarray:
    """Apply unit conversion with validation.

    TRAP: Temperature in °C vs K is a 273.15 offset — check output range.
    TRAP: Precipitation in mm/day vs kg/m²/s is an 86400x factor.
    TRAP: Humidity as percentage (0-100) vs fraction (0-1) is a 100x factor.
    """
    if category not in UNIT_CONVERSIONS:
        raise ValueError(f"Unknown conversion category: {category}")
    if conversion not in UNIT_CONVERSIONS[category]:
        raise ValueError(f"Unknown conversion: {conversion} in {category}")

    converted = UNIT_CONVERSIONS[category][conversion](data)

    # Post-conversion sanity checks
    _check_physical_bounds(converted, category, var_name)

    return converted


def _check_physical_bounds(data: np.ndarray, category: str, var_name: str):
    """Check that converted values are physically reasonable."""
    valid = np.isfinite(data)
    if not np.any(valid):
        raise ValueError(f"{var_name}: all values are NaN/Inf after conversion")

    d = data[valid]
    checks = {
        "temperature": (150.0, 350.0, "K"),       # 150–350 K
        "pressure": (30000.0, 110000.0, "Pa"),     # 300–1100 hPa
        "precipitation": (0.0, 0.1, "kg/m²/s"),    # 0–100 mm/s = extreme
        "radiation": (-5.0, 1500.0, "W/m²"),
        "humidity": (-0.01, 1.01, "fraction or kg/kg"),
        "wind": (-100.0, 100.0, "m/s"),
    }

    if category in checks:
        lo, hi, unit = checks[category]
        if np.min(d) < lo or np.max(d) > hi:
            logger.warning(
                "UNIT TRAP: %s range [%.4f, %.4f] outside expected [%.1f, %.1f] %s. "
                "Check unit conversion!",
                var_name, np.min(d), np.max(d), lo, hi, unit
            )


def read_csv_forcing(path: str) -> dict:
    """Read forcing from a generic CSV file.

    Expected columns: datetime, temp_C, precip_mm_day, rh_percent,
                      wind_m_s, sw_rad_W_m2, lw_rad_W_m2, pressure_hPa
    """
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    result = {}

    col_map = {
        "temp_C": ("air_temperature", "temperature", "C_to_K"),
        "temp_K": ("air_temperature", "temperature", "K_to_K"),
        "precip_mm_day": ("precipitation_flux", "precipitation", "mm_day_to_kg_m2_s"),
        "precip_mm_hr": ("precipitation_flux", "precipitation", "mm_hr_to_kg_m2_s"),
        "rh_percent": ("relative_humidity", "humidity", "percent_to_fraction"),
        "rh_fraction": ("relative_humidity", "humidity", "fraction_to_fraction"),
        "shum_kg_kg": ("specific_humidity", "humidity", "kg_kg_to_kg_kg"),
        "shum_g_kg": ("specific_humidity", "humidity", "g_kg_to_kg_kg"),
        "wind_m_s": ("wind_speed", "wind", "m_s_to_m_s"),
        "wind_km_hr": ("wind_speed", "wind", "km_hr_to_m_s"),
        "sw_rad_W_m2": ("surface_downwelling_shortwave_flux_in_air", "radiation", "W_m2_to_W_m2"),
        "lw_rad_W_m2": ("surface_downwelling_longwave_flux_in_air", "radiation", "W_m2_to_W_m2"),
        "pressure_hPa": ("surface_air_pressure", "pressure", "hPa_to_Pa"),
        "pressure_Pa": ("surface_air_pressure", "pressure", "Pa_to_Pa"),
    }

    for col in data.dtype.names:
        if col == "datetime":
            result["time"] = data[col]
            continue
        if col in col_map:
            cf_name, category, conv = col_map[col]
            values = data[col].astype(np.float64)
            result[cf_name] = apply_unit_conversion(values, category, conv, col)
            logger.info("Converted %s → %s (%s)", col, cf_name, conv)

    return result


def write_forcing_netcdf(forcing: dict, output_path: str, start_date: str,
                         time_step_hours: float = 1.0):
    """Write forcing data in CF-convention NetCDF.

    TRAP: Time axis MUST use 'units since epoch' format (CF convention).
    Integer timestep indices will cause ESMF_Clock parsing failures.
    """
    try:
        from netCDF4 import Dataset, num2date, date2num
    except ImportError:
        logger.warning("netCDF4 not available. Writing forcing as CSV fallback.")
        _write_forcing_csv_fallback(forcing, output_path)
        return

    time_data = forcing.get("time")
    if time_data is not None:
        ntime = len(time_data)
    else:
        first_var = [v for k, v in forcing.items() if k != "time"][0]
        ntime = len(first_var)

    with Dataset(output_path, "w", format="NETCDF4") as ds:
        ds.title = "ESMF Meteorological Forcing"
        ds.conventions = "CF-1.6"
        ds.history = f"Created by convert_forcing_to_esmf.py on {datetime.now().isoformat()}"

        ds.createDimension("time", None)  # unlimited

        time_var = ds.createVariable("time", "f8", ("time",))
        time_var.units = f"hours since {start_date} 00:00:00"
        time_var.calendar = "standard"
        time_var.axis = "T"
        time_var[:] = np.arange(ntime) * time_step_hours

        cf_units = {
            "air_temperature": ("K", "air_temperature"),
            "precipitation_flux": ("kg m-2 s-1", "precipitation_flux"),
            "specific_humidity": ("kg kg-1", "specific_humidity"),
            "relative_humidity": ("1", "relative_humidity"),
            "surface_air_pressure": ("Pa", "surface_air_pressure"),
            "surface_downwelling_shortwave_flux_in_air": ("W m-2", "surface_downwelling_shortwave_flux_in_air"),
            "surface_downwelling_longwave_flux_in_air": ("W m-2", "surface_downwelling_longwave_flux_in_air"),
            "wind_speed": ("m s-1", "wind_speed"),
            "eastward_wind": ("m s-1", "eastward_wind"),
            "northward_wind": ("m s-1", "northward_wind"),
        }

        for var_name, data in forcing.items():
            if var_name == "time":
                continue
            v = ds.createVariable(var_name, "f4", ("time",), fill_value=-9999.0)
            if var_name in cf_units:
                v.units, v.standard_name = cf_units[var_name]
            v[:] = data

    logger.info("Wrote forcing NetCDF: %s (%d timesteps)", output_path, ntime)


def _write_forcing_csv_fallback(forcing: dict, output_path: str):
    """Fallback CSV writer when netCDF4 is not available."""
    csv_path = output_path.replace(".nc", ".csv")
    keys = [k for k in forcing if k != "time"]
    header = "timestep," + ",".join(keys)
    ntime = len(forcing[keys[0]])
    with open(csv_path, "w") as f:
        f.write(header + "\n")
        for t in range(ntime):
            row = [str(t)] + [f"{forcing[k][t]:.6g}" for k in keys]
            f.write(",".join(row) + "\n")
    logger.info("Wrote forcing CSV fallback: %s", csv_path)


def validate_output(output_path: str):
    """Validate the output forcing file."""
    actual = output_path if os.path.isfile(output_path) else output_path.replace(".nc", ".csv")
    if not os.path.isfile(actual):
        raise RuntimeError(f"Output file not created: {output_path}")

    size = os.path.getsize(actual)
    if size == 0:
        raise RuntimeError(f"Output file is empty: {actual}")

    try:
        from netCDF4 import Dataset
        with Dataset(output_path, "r") as ds:
            if "time" not in ds.variables:
                raise RuntimeError("Missing 'time' variable in output")
            time_var = ds.variables["time"]
            if not hasattr(time_var, "units") or "since" not in time_var.units:
                logger.warning(
                    "TRAP: time units '%s' missing 'since' keyword. "
                    "ESMF requires CF-convention time (e.g., 'hours since 2000-01-01').",
                    getattr(time_var, "units", "MISSING")
                )
    except ImportError:
        pass

    logger.info("Output validated: %s (%.1f KB)", actual, size / 1024)


def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to ESMF format")
    parser.add_argument("--input", "-i", required=True, help="Input forcing file")
    parser.add_argument("--source-format", "-f", default="csv",
                        choices=list(SOURCE_FORMATS.keys()),
                        help="Source data format")
    parser.add_argument("--output", "-o", required=True, help="Output NetCDF file")
    parser.add_argument("--start-date", default="2000-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2010-12-31", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Validate
    validate_input(args.input, args.source_format)

    # Process
    fmt = SOURCE_FORMATS[args.source_format]
    if args.source_format == "csv":
        forcing = read_csv_forcing(args.input)
        ts = 1.0
    else:
        # For NetCDF source formats, would use netCDF4 reader
        logger.info("Reading %s format from %s", args.source_format, args.input)
        forcing = read_csv_forcing(args.input)  # simplified for demo
        ts = fmt["time_step_hours"]

    # Write
    write_forcing_netcdf(forcing, args.output, args.start_date, ts)

    # Validate output
    validate_output(args.output)

    logger.info("Done. Forcing written to %s", args.output)


if __name__ == "__main__":
    main()
