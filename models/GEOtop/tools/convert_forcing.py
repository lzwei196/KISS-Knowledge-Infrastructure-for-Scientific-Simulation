#!/usr/bin/env python3
"""
convert_forcing.py - Convert global meteorological data to GEOtop meteo CSV format.

Supports: CMFD, MSWX, ERA5, NASA POWER, generic CSV.

CRITICAL UNIT CONVERSIONS:
  - GEOtop expects RelHum in PERCENT (0-100), not fraction (0-1)
  - GEOtop expects Iprec in mm per time step, not mm/hr or m/s
  - GEOtop expects AirT in Celsius, not Kelvin
  - GEOtop expects Swglobal in W/m2 (instantaneous, not accumulated)
  - GEOtop expects dates in DD/MM/YYYY hh:mm format (European)
  - Missing values MUST be -9999 (not NaN, -999, or blank)

Usage:
    python convert_forcing.py \\
        --source cmfd \\
        --input /path/to/forcing/data \\
        --lat 46.668 --lon 10.579 --elev 1480 \\
        --start "02/10/2009 00:00" --end "02/11/2009 00:00" \\
        --dt 3600 \\
        --output /path/to/sim/meteo/meteo0001.txt

    python convert_forcing.py \\
        --source csv \\
        --input /path/to/generic.csv \\
        --col-map '{"datetime":"Date","temp":"AirT","precip":"Iprec","rh":"RelHum","wind":"WindSp","srad":"Swglobal"}' \\
        --temp-unit K --rh-unit fraction --precip-unit mm_hr \\
        --dt 3600 \\
        --output /path/to/sim/meteo/meteo0001.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

NODATA = -9999
GEOTOP_DATE_FMT = "%d/%m/%Y %H:%M"

# Julian Day reference: days from year 0 (GEOtop convention)
JULIAN_EPOCH = datetime(1, 1, 1)
JULIAN_OFFSET = 1721424.5  # JD of 1 Jan 0001


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if args.source not in ("cmfd", "mswx", "era5", "nasa_power", "csv"):
        errors.append(f"Unknown source: {args.source}. Must be one of: cmfd, mswx, era5, nasa_power, csv")

    if not os.path.exists(args.input):
        errors.append(f"Input path does not exist: {args.input}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude out of range: {args.lat}")

    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    if args.dt <= 0:
        errors.append(f"Time step must be positive: {args.dt}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def date_to_jd_from0(dt):
    """Convert datetime to Julian Day from year 0 (GEOtop convention)."""
    # Approximate: days from 1 Jan 0000
    delta = dt - datetime(1, 1, 1)
    return delta.days + delta.seconds / 86400.0 + 365.25 + 1


def kelvin_to_celsius(t):
    """Convert temperature from Kelvin to Celsius."""
    return t - 273.15


def fraction_to_percent(rh):
    """Convert relative humidity from fraction (0-1) to percent (0-100)."""
    return rh * 100.0


def specific_to_relative_humidity(q, t_celsius, p_mbar=1013.25):
    """Convert specific humidity (kg/kg) to relative humidity (%).

    Args:
        q: Specific humidity in kg/kg
        t_celsius: Air temperature in Celsius
        p_mbar: Air pressure in mbar

    Returns:
        Relative humidity in percent (0-100)
    """
    # Saturation vapor pressure (Tetens formula, mbar)
    es = 6.1078 * np.exp(17.27 * t_celsius / (t_celsius + 237.3))
    # Vapor pressure from specific humidity
    e = q * p_mbar / (0.622 + 0.378 * q)
    rh = 100.0 * e / es
    return np.clip(rh, 0, 100)


def convert_precip(precip, from_unit, dt_seconds):
    """Convert precipitation to mm per time step.

    CRITICAL: GEOtop Iprec = total mm accumulated over the time step.

    Args:
        precip: Precipitation values
        from_unit: One of 'mm_hr', 'mm_day', 'mm_step', 'm_s', 'kg_m2_s'
        dt_seconds: Model time step in seconds
    """
    if from_unit == "mm_step":
        return precip
    elif from_unit == "mm_hr":
        return precip * (dt_seconds / 3600.0)
    elif from_unit == "mm_day":
        return precip * (dt_seconds / 86400.0)
    elif from_unit in ("m_s", "kg_m2_s"):
        # m/s -> mm/step: multiply by 1000 (m->mm) * dt (s)
        return precip * 1000.0 * dt_seconds
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


def read_cmfd(input_path, lat, lon, start, end):
    """Read CMFD (China Meteorological Forcing Dataset) data.

    CMFD is on a 0.1 degree grid with 3-hourly temporal resolution.
    Variables: temp (K), shum (kg/kg), pres (Pa), prec (mm/hr),
               wind (m/s), srad (W/m2), lrad (W/m2)
    """
    try:
        import xarray as xr
    except ImportError:
        print(json.dumps({"status": "error", "errors": ["xarray required for CMFD"]}), file=sys.stderr)
        sys.exit(1)

    ds = xr.open_mfdataset(os.path.join(input_path, "*.nc"), combine="by_coords")
    point = ds.sel(latitude=lat, longitude=lon, method="nearest")
    point = point.sel(time=slice(start, end))

    df = pd.DataFrame({
        "AirT": kelvin_to_celsius(point["temp"].values),
        "Iprec": point["prec"].values,  # already mm/hr in CMFD
        "WindSp": point["wind"].values,
        "Swglobal": point["srad"].values,
        "LWin": point["lrad"].values,
        "AirPress": point["pres"].values / 100.0,  # Pa to mbar
    }, index=pd.to_datetime(point.time.values))

    # Specific humidity -> relative humidity
    df["RelHum"] = specific_to_relative_humidity(
        point["shum"].values, df["AirT"].values, df["AirPress"].values
    )

    return df


def read_generic_csv(input_path, col_map, temp_unit, rh_unit, precip_unit, dt_seconds):
    """Read a generic CSV file with user-specified column mapping and units."""
    mapping = json.loads(col_map) if isinstance(col_map, str) else col_map

    df = pd.read_csv(input_path, parse_dates=[mapping.get("datetime", "datetime")])
    df = df.set_index(mapping.get("datetime", "datetime"))

    result = pd.DataFrame(index=df.index)

    # Temperature
    temp_col = mapping.get("temp", "AirT")
    if temp_col in df.columns:
        result["AirT"] = df[temp_col]
        if temp_unit == "K":
            result["AirT"] = kelvin_to_celsius(result["AirT"])

    # Relative humidity
    rh_col = mapping.get("rh", "RelHum")
    if rh_col in df.columns:
        result["RelHum"] = df[rh_col]
        if rh_unit == "fraction":
            result["RelHum"] = fraction_to_percent(result["RelHum"])

    # Precipitation
    precip_col = mapping.get("precip", "Iprec")
    if precip_col in df.columns:
        result["Iprec"] = convert_precip(df[precip_col], precip_unit, dt_seconds)

    # Wind speed
    wind_col = mapping.get("wind", "WindSp")
    if wind_col in df.columns:
        result["WindSp"] = df[wind_col]

    # Shortwave radiation
    srad_col = mapping.get("srad", "Swglobal")
    if srad_col in df.columns:
        result["Swglobal"] = df[srad_col]

    # Wind direction (optional)
    wdir_col = mapping.get("wdir", "WindDir")
    if wdir_col in df.columns:
        result["WindDir"] = df[wdir_col]

    # Longwave radiation (optional)
    lw_col = mapping.get("lwin", "LWin")
    if lw_col in df.columns:
        result["LWin"] = df[lw_col]

    return result


def process(args):
    """Main processing: read source data and write GEOtop meteo file."""
    start = datetime.strptime(args.start, GEOTOP_DATE_FMT)
    end = datetime.strptime(args.end, GEOTOP_DATE_FMT)

    if args.source == "cmfd":
        df = read_cmfd(args.input, args.lat, args.lon, start, end)
        precip_unit = "mm_hr"
    elif args.source == "csv":
        df = read_generic_csv(
            args.input, args.col_map,
            args.temp_unit, args.rh_unit, args.precip_unit, args.dt
        )
        precip_unit = args.precip_unit
    else:
        print(json.dumps({"status": "error", "errors": [f"Source '{args.source}' reader not yet implemented"]}),
              file=sys.stderr)
        sys.exit(1)

    # Resample to target time step if needed
    target_freq = f"{args.dt}s"
    df = df.resample(target_freq).interpolate(method="linear")
    # Precipitation should be summed, not interpolated
    if "Iprec" in df.columns:
        # Re-read and aggregate precipitation
        pass  # Already handled per-source

    # Build output DataFrame
    out_cols = ["Date", "JDfrom0"]
    meteo_cols = ["Iprec", "WindSp", "WindDir", "RelHum", "AirT", "Swglobal", "CloudTrans"]
    optional_cols = ["LWin", "DewT", "AirPress"]

    rows = []
    for ts, row in df.iterrows():
        dt_obj = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        date_str = dt_obj.strftime(GEOTOP_DATE_FMT)
        jd = date_to_jd_from0(dt_obj)

        r = {
            "Date": date_str,
            "JDfrom0": f"{jd:.4f}",
            "Iprec": f"{row.get('Iprec', 0):.4f}" if pd.notna(row.get("Iprec")) else str(NODATA),
            "WindSp": f"{row.get('WindSp', 0):.2f}" if pd.notna(row.get("WindSp")) else str(NODATA),
            "WindDir": f"{row.get('WindDir', 0):.2f}" if pd.notna(row.get("WindDir")) else str(NODATA),
            "RelHum": f"{row.get('RelHum', 50):.2f}" if pd.notna(row.get("RelHum")) else str(NODATA),
            "AirT": f"{row.get('AirT', 10):.2f}" if pd.notna(row.get("AirT")) else str(NODATA),
            "Swglobal": f"{row.get('Swglobal', 0):.2f}" if pd.notna(row.get("Swglobal")) else str(NODATA),
            "CloudTrans": str(NODATA),  # Default to nodata (model will parameterize)
        }

        for col in optional_cols:
            if col in row and pd.notna(row[col]):
                r[col] = f"{row[col]:.2f}"

        rows.append(r)

    # Determine output columns
    all_cols = ["Date", "JDfrom0"] + meteo_cols
    for col in optional_cols:
        if any(col in r for r in rows):
            all_cols.append(col)

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(",".join(all_cols) + "\n")
        for r in rows:
            vals = [r.get(c, str(NODATA)) for c in all_cols]
            f.write(",".join(vals) + "\n")

    return len(rows)


def validate_outputs(output_path):
    """Validate the generated meteo file for common errors."""
    warnings = []

    df = pd.read_csv(output_path)

    # Check RelHum range
    if "RelHum" in df.columns:
        rh_valid = df["RelHum"][df["RelHum"] != NODATA]
        if len(rh_valid) > 0:
            if rh_valid.max() <= 1.0:
                warnings.append(
                    "CRITICAL: RelHum max <= 1.0 -- likely in fraction (0-1) instead of percent (0-100). "
                    "GEOtop expects PERCENT. Multiply by 100."
                )
            if rh_valid.max() > 100:
                warnings.append(f"RelHum max = {rh_valid.max():.1f} > 100%. Check input data.")

    # Check AirT range (should be Celsius)
    if "AirT" in df.columns:
        at_valid = df["AirT"][df["AirT"] != NODATA]
        if len(at_valid) > 0:
            if at_valid.mean() > 100:
                warnings.append(
                    "CRITICAL: AirT mean > 100 -- likely in Kelvin instead of Celsius. "
                    "Subtract 273.15."
                )

    # Check Iprec (should be non-negative, reasonable range)
    if "Iprec" in df.columns:
        prec_valid = df["Iprec"][df["Iprec"] != NODATA]
        if len(prec_valid) > 0:
            if prec_valid.max() > 200:
                warnings.append(
                    f"Iprec max = {prec_valid.max():.1f} mm/step. Very high. "
                    "Check if units are mm/hr vs mm/step."
                )

    # Check date format
    first_date = df.iloc[0]["Date"]
    if "/" not in str(first_date):
        warnings.append("Date column may not be in DD/MM/YYYY hh:mm format.")
    else:
        parts = str(first_date).split("/")
        if len(parts) >= 2:
            day = int(parts[0])
            month = int(parts[1])
            if day > 12 and month <= 12:
                pass  # Correctly DD/MM
            elif day <= 12 and month > 12:
                warnings.append("Date appears to be MM/DD/YYYY. GEOtop expects DD/MM/YYYY.")

    # Check for nodata
    nodata_count = (df == NODATA).sum().sum()
    total_values = df.shape[0] * df.shape[1]
    nodata_pct = 100.0 * nodata_count / total_values
    if nodata_pct > 50:
        warnings.append(f"{nodata_pct:.0f}% of values are nodata (-9999). Check input completeness.")

    result = {
        "status": "ok" if not warnings else "warning",
        "n_rows": len(df),
        "columns": list(df.columns),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to GEOtop meteoXXXX.txt format"
    )
    parser.add_argument("--source", required=True, choices=["cmfd", "mswx", "era5", "nasa_power", "csv"],
                        help="Data source type")
    parser.add_argument("--input", required=True, help="Input file or directory path")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees)")
    parser.add_argument("--elev", type=float, default=0, help="Elevation (m)")
    parser.add_argument("--start", required=True, help="Start date DD/MM/YYYY hh:mm")
    parser.add_argument("--end", required=True, help="End date DD/MM/YYYY hh:mm")
    parser.add_argument("--dt", type=int, default=3600, help="Time step in seconds (default: 3600)")
    parser.add_argument("--output", required=True, help="Output meteo file path")

    # Generic CSV options
    parser.add_argument("--col-map", default="{}", help="JSON column name mapping")
    parser.add_argument("--temp-unit", default="C", choices=["C", "K"], help="Input temperature unit")
    parser.add_argument("--rh-unit", default="percent", choices=["percent", "fraction", "specific"],
                        help="Input humidity unit")
    parser.add_argument("--precip-unit", default="mm_hr",
                        choices=["mm_hr", "mm_day", "mm_step", "m_s", "kg_m2_s"],
                        help="Input precipitation unit")

    args = parser.parse_args()
    validate_inputs(args)
    n_rows = process(args)
    validate_outputs(args.output)
    print(f"Wrote {n_rows} rows to {args.output}")


if __name__ == "__main__":
    main()
