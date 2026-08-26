#!/usr/bin/env python3
"""
Convert NASA POWER hourly cache data to EPIC .DLY daily weather format.

Pipeline: NASA POWER cache → aggregate to daily → unit conversion → .DLY file
Pattern:  validate inputs → process → validate outputs

Supports:
  - NASA POWER hourly cache (pre-cached at KISSPATH_ROOT/.../nasa_power_cache/hourly/)
  - Generic CSV with columns: date, tmax_C, tmin_C, srad_MJm2d, prcp_mm, rh_frac, ws_ms
"""

import os
import sys
import glob
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# EPIC DLY format specification
# ---------------------------------------------------------------------------
DLY_COLUMNS = ["year", "month", "day", "srad", "tmax", "tmin", "prcp", "rh", "ws"]
DLY_FMT = "%6d%4d%4d%6.2f%6.2f%6.2f%6.2f%6.2f%6.2f"
DLY_READ_WIDTHS = [6, 4, 4, 6, 6, 6, 6, 6, 6]

# Unit expectations:
#   srad: MJ/m2/day
#   tmax, tmin: deg C
#   prcp: mm/day
#   rh: fraction (0-1)
#   ws: m/s


def validate_inputs(data: pd.DataFrame, source: str) -> list:
    """Validate raw input data before conversion."""
    errors = []

    if data.empty:
        errors.append(f"ERROR: Input data from {source} is empty")
        return errors

    required_vars = {
        "nasa_power": ["T2M", "T2M_MAX", "T2M_MIN", "ALLSKY_SFC_SW_DWN",
                        "PRECTOTCORR", "RH2M", "WS2M"],
        "csv": ["date", "tmax_C", "tmin_C", "srad_MJm2d", "prcp_mm",
                "rh_frac", "ws_ms"],
    }

    if source in required_vars:
        missing = [v for v in required_vars[source] if v not in data.columns]
        if missing:
            errors.append(f"ERROR: Missing columns: {missing}")

    # Check for excessive NaN
    nan_pct = data.isna().mean().max()
    if nan_pct > 0.1:
        errors.append(f"WARNING: {nan_pct:.1%} NaN in input — may need gap-filling")

    return errors


def convert_nasa_power_to_daily(hourly_dir: str, lat: float, lon: float,
                                 start_year: int, end_year: int) -> pd.DataFrame:
    """
    Read NASA POWER hourly cache and aggregate to daily values.

    NASA POWER units:
        T2M, T2M_MAX, T2M_MIN: deg C (no conversion needed)
        ALLSKY_SFC_SW_DWN: MJ/m2/day (no conversion needed for daily)
        PRECTOTCORR: mm/hour → sum to mm/day
        RH2M: % → divide by 100 to get fraction
        WS2M: m/s (no conversion needed)
    """
    # Find matching cache file by lat/lon
    cache_pattern = os.path.join(hourly_dir, f"*_{lat:.2f}_{lon:.2f}*.csv")
    cache_files = glob.glob(cache_pattern)

    if not cache_files:
        # Try with rounded coordinates
        cache_pattern = os.path.join(hourly_dir, f"*_{lat:.1f}*_{lon:.1f}*.csv")
        cache_files = glob.glob(cache_pattern)

    if not cache_files:
        raise FileNotFoundError(
            f"No NASA POWER cache found for ({lat}, {lon}) in {hourly_dir}"
        )

    frames = []
    for f in sorted(cache_files):
        df = pd.read_csv(f, parse_dates=["datetime"])
        frames.append(df)

    hourly = pd.concat(frames, ignore_index=True)
    hourly["date"] = hourly["datetime"].dt.date

    # Aggregate to daily
    daily = hourly.groupby("date").agg(
        tmax=("T2M_MAX", "max"),        # deg C
        tmin=("T2M_MIN", "min"),         # deg C
        srad=("ALLSKY_SFC_SW_DWN", "mean"),  # MJ/m2/day (daily mean of hourly)
        prcp=("PRECTOTCORR", "sum"),     # mm/hr → mm/day
        rh=("RH2M", "mean"),            # % → needs /100
        ws=("WS2M", "mean"),            # m/s
    ).reset_index()

    # UNIT CONVERSIONS
    # RH: NASA POWER gives percentage (0-100), EPIC needs fraction (0-1)
    daily["rh"] = daily["rh"] / 100.0
    daily["rh"] = daily["rh"].clip(0.0, 1.0)

    # Filter by year range
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily[
        (daily["date"].dt.year >= start_year) &
        (daily["date"].dt.year <= end_year)
    ]

    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month
    daily["day"] = daily["date"].dt.day

    return daily[DLY_COLUMNS]


def convert_csv_to_daily(csv_path: str) -> pd.DataFrame:
    """
    Convert a generic CSV to EPIC daily format.

    Expected CSV columns:
        date, tmax_C, tmin_C, srad_MJm2d, prcp_mm, rh_frac, ws_ms
    """
    df = pd.read_csv(csv_path, parse_dates=["date"])

    daily = pd.DataFrame({
        "year": df["date"].dt.year,
        "month": df["date"].dt.month,
        "day": df["date"].dt.day,
        "srad": df["srad_MJm2d"],
        "tmax": df["tmax_C"],
        "tmin": df["tmin_C"],
        "prcp": df["prcp_mm"],
        "rh": df["rh_frac"],
        "ws": df["ws_ms"],
    })

    return daily


def validate_outputs(daily: pd.DataFrame) -> list:
    """Validate converted daily data before writing DLY file."""
    errors = []

    # Solar radiation: should be 0-50 MJ/m2/day
    if daily["srad"].max() > 50:
        errors.append(
            f"WARNING: Max srad={daily['srad'].max():.1f} MJ/m2/day > 50. "
            f"Check if units are W/m2 (need * 0.0864) or include dayl conversion."
        )
    if daily["srad"].min() < 0:
        errors.append("WARNING: Negative srad values. Clipping to 0.")

    # Temperature: should be -60 to 60 degC
    if daily["tmax"].max() > 60:
        errors.append(
            f"WARNING: Max tmax={daily['tmax'].max():.1f} — "
            f"check if data is in Kelvin (need - 273.15)"
        )
    if daily["tmin"].min() < -60:
        errors.append(
            f"WARNING: Min tmin={daily['tmin'].min():.1f} — "
            f"check if data is in Kelvin"
        )

    # Precipitation: should be 0-500 mm/day
    if daily["prcp"].max() > 500:
        errors.append(
            f"WARNING: Max prcp={daily['prcp'].max():.1f} mm/day — "
            f"check aggregation (sum not mean for hourly→daily)"
        )
    if daily["prcp"].min() < 0:
        errors.append("WARNING: Negative precipitation. Clipping to 0.")

    # Relative humidity: EPIC expects 0-1 fraction
    if daily["rh"].max() > 1.05:
        errors.append(
            f"WARNING: Max rh={daily['rh'].max():.2f} > 1.0 — "
            f"data may be in % (need / 100)"
        )
    if daily["rh"].max() > 100:
        errors.append(
            f"ERROR: Max rh={daily['rh'].max():.1f} — "
            f"values appear to be in % not fraction. Dividing by 100."
        )

    # Wind speed: should be 0-50 m/s
    if daily["ws"].max() > 50:
        errors.append(f"WARNING: Max wind={daily['ws'].max():.1f} m/s > 50")

    return errors


def write_dly(daily: pd.DataFrame, output_path: str,
              station_name: str = "STATION", station_id: str = "0000",
              state: str = "XX", county: str = "UNKNOWN",
              lat: float = 0.0, lon: float = 0.0, elev: float = 0.0):
    """Write EPIC .DLY file in fixed-width Fortran format."""
    lines = []
    for _, row in daily.iterrows():
        line = DLY_FMT % (
            int(row["year"]), int(row["month"]), int(row["day"]),
            row["srad"], row["tmax"], row["tmin"],
            row["prcp"], row["rh"], row["ws"]
        )
        lines.append(line)

    # Last line metadata (appended to last data line)
    last_row = daily.iloc[-1]
    meta = (
        f"            STATION = {station_name}   "
        f"STA ID = {station_id}  STATE = {state}  CO = {county}  "
        f"            LAT = {lat:8.3f}   LONG = {lon:9.3f}  "
        f"ELEV = {elev:8.1f}  "
        f"Y-M-D {int(last_row['year'])} {int(last_row['month'])} {int(last_row['day'])}"
    )
    lines[-1] = lines[-1] + meta

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {len(lines)} days to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert weather data to EPIC .DLY format"
    )
    parser.add_argument("--source", choices=["nasa_power", "csv"],
                        required=True, help="Data source type")
    parser.add_argument("--input", required=True,
                        help="Input directory (nasa_power) or CSV file path")
    parser.add_argument("--output", required=True,
                        help="Output .DLY file path")
    parser.add_argument("--lat", type=float, default=0.0,
                        help="Station latitude")
    parser.add_argument("--lon", type=float, default=0.0,
                        help="Station longitude")
    parser.add_argument("--elev", type=float, default=0.0,
                        help="Station elevation (m)")
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=2020)
    parser.add_argument("--station-name", default="STATION")

    args = parser.parse_args()

    # Step 1: Read and convert
    if args.source == "nasa_power":
        daily = convert_nasa_power_to_daily(
            args.input, args.lat, args.lon,
            args.start_year, args.end_year
        )
    elif args.source == "csv":
        daily = convert_csv_to_daily(args.input)

    # Step 2: Validate inputs
    input_errors = validate_inputs(daily, args.source)
    for e in input_errors:
        print(e)

    # Step 3: Clip and fix
    daily["srad"] = daily["srad"].clip(lower=0.0)
    daily["prcp"] = daily["prcp"].clip(lower=0.0)
    daily["rh"] = daily["rh"].clip(0.0, 1.0)

    # Auto-fix: if RH looks like percentage, convert
    if daily["rh"].max() > 1.5:
        print("AUTO-FIX: RH appears to be in %, dividing by 100")
        daily["rh"] = daily["rh"] / 100.0
        daily["rh"] = daily["rh"].clip(0.0, 1.0)

    # Step 4: Validate outputs
    output_errors = validate_outputs(daily)
    for e in output_errors:
        print(e)

    if any("ERROR" in e for e in output_errors):
        print("FATAL: Output validation failed. Aborting.")
        sys.exit(1)

    # Step 5: Write DLY
    write_dly(
        daily, args.output,
        station_name=args.station_name,
        lat=args.lat, lon=args.lon, elev=args.elev
    )


if __name__ == "__main__":
    main()
