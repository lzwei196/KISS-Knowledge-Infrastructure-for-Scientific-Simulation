"""
MARRMoT Forcing Converter
=========================
Convert global meteorological data (ERA5, CMFD, MSWX, generic CSV/NetCDF)
into the 3-column climate array required by MARRMoT: [P, Ep, T].

Units:
  - Precipitation (P): mm/d
  - Potential evapotranspiration (Ep): mm/d
  - Temperature (T): deg C

CRITICAL: MARRMoT expects [P, Ep, T] column order, NOT [P, T, Ep].
  Swapping columns is a silent error (dt_011).

CRITICAL: MARRMoT does NOT compute PET internally. If your source only
  has radiation or Tmin/Tmax, you must compute PET externally first
  (Hargreaves or Penman-Monteith). Passing radiation as PET is dt_004.

Usage:
  python convert_forcing.py --input era5_daily.nc --format era5 \
    --lat 35.5 --lon 117.3 --start 2000-01-01 --end 2010-12-31 \
    --output forcing.csv

  python convert_forcing.py --input local_data.csv --format csv \
    --p-col precip_mm_d --ep-col pet_mm_d --t-col temp_c \
    --output forcing.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import xarray as xr
except ImportError:
    xr = None


# ── Unit conversion constants ────────────────────────────────────────
KG_M2_S_TO_MM_D = 86400.0       # kg/m2/s -> mm/d  (ERA5 precip)
M_D_TO_MM_D = 1000.0            # m/d -> mm/d
K_TO_C = -273.15                 # K -> deg C
LATENT_HEAT_VAPORISATION = 2.45  # MJ/kg (approx at 20C)
MJ_M2_D_TO_MM_D = 1.0 / LATENT_HEAT_VAPORISATION  # radiation to ET equiv


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.format not in ("era5", "cmfd", "mswx", "csv", "generic"):
        errors.append(f"Unknown format: {args.format}. "
                       "Use era5, cmfd, mswx, csv, or generic.")

    if args.format in ("era5", "cmfd", "mswx"):
        if args.lat is None or args.lon is None:
            errors.append("--lat and --lon required for gridded formats.")
        if args.lat is not None and not (-90 <= args.lat <= 90):
            errors.append(f"Latitude out of range: {args.lat}")
        if args.lon is not None and not (-180 <= args.lon <= 360):
            errors.append(f"Longitude out of range: {args.lon}")

    if args.start and args.end:
        try:
            s = datetime.strptime(args.start, "%Y-%m-%d")
            e = datetime.strptime(args.end, "%Y-%m-%d")
            if s >= e:
                errors.append("--start must be before --end")
        except ValueError as exc:
            errors.append(f"Date parse error: {exc}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}),
              file=sys.stdout)
        sys.exit(1)


def hargreaves_pet(tmin, tmax, tmean, doy, lat_rad):
    """
    Compute Hargreaves PET estimate (mm/d).

    Parameters
    ----------
    tmin, tmax, tmean : array-like, deg C
    doy : array-like, day of year (1-366)
    lat_rad : float, latitude in radians

    Returns
    -------
    pet : ndarray, mm/d
    """
    # Solar declination
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.4093 * np.sin(2 * np.pi * doy / 365 - 1.39)

    # Sunset hour angle
    ws = np.arccos(-np.tan(lat_rad) * np.tan(delta))

    # Extra-terrestrial radiation (MJ/m2/d)
    Gsc = 0.0820  # solar constant
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )

    # Hargreaves equation
    tdiff = np.maximum(tmax - tmin, 0.0)
    pet = 0.0023 * Ra * np.sqrt(tdiff) * (tmean + 17.8) * MJ_M2_D_TO_MM_D
    return np.maximum(pet, 0.0)


def convert_era5(input_path, lat, lon, start, end):
    """Convert ERA5 daily NetCDF to MARRMoT forcing."""
    if xr is None:
        print(json.dumps({"status": "error",
                          "errors": ["xarray required for ERA5 conversion"]}))
        sys.exit(1)

    ds = xr.open_dataset(input_path)
    # Select nearest grid cell
    ds = ds.sel(latitude=lat, longitude=lon, method="nearest")

    if start and end:
        ds = ds.sel(time=slice(start, end))

    times = pd.DatetimeIndex(ds.time.values)

    # Precipitation: ERA5 tp is m/d or kg/m2/s depending on product
    if "tp" in ds:
        p_raw = ds["tp"].values
        # Detect units: if max < 1, likely m/d
        if np.nanmax(p_raw) < 1.0:
            precip = p_raw * M_D_TO_MM_D
            print("Converted precip from m/d to mm/d", file=sys.stderr)
        else:
            precip = p_raw * KG_M2_S_TO_MM_D
            print("Converted precip from kg/m2/s to mm/d", file=sys.stderr)
    else:
        raise KeyError("No precipitation variable found (expected 'tp')")

    # Temperature: ERA5 t2m is in K
    if "t2m" in ds:
        temp = ds["t2m"].values + K_TO_C
        print("Converted temperature from K to deg C", file=sys.stderr)
    elif "T2M" in ds:
        temp = ds["T2M"].values + K_TO_C
    else:
        raise KeyError("No temperature variable found (expected 't2m')")

    # PET: compute via Hargreaves if Tmin/Tmax available, else use provided
    if "pet" in ds or "pev" in ds:
        varname = "pet" if "pet" in ds else "pev"
        pet_raw = ds[varname].values
        # ERA5 PET is negative (energy leaving surface) and in m/d
        pet = np.abs(pet_raw) * M_D_TO_MM_D
        print(f"Converted PET from {varname} (m/d) to mm/d", file=sys.stderr)
    else:
        # Estimate PET from temperature using Hargreaves
        lat_rad = np.radians(lat)
        doy = times.dayofyear.values
        # Approximate Tmin/Tmax as T +/- 5 C (rough estimate)
        tmin = temp - 5.0
        tmax = temp + 5.0
        pet = hargreaves_pet(tmin, tmax, temp, doy, lat_rad)
        print("Estimated PET using Hargreaves (no PET in source)",
              file=sys.stderr)

    ds.close()
    return times, precip, pet, temp


def convert_csv(input_path, p_col, ep_col, t_col, date_col, start, end):
    """Convert generic CSV to MARRMoT forcing."""
    if pd is None:
        print(json.dumps({"status": "error",
                          "errors": ["pandas required for CSV conversion"]}))
        sys.exit(1)

    df = pd.read_csv(input_path, parse_dates=[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    if start:
        df = df[df[date_col] >= start]
    if end:
        df = df[df[date_col] <= end]

    times = pd.DatetimeIndex(df[date_col].values)
    precip = df[p_col].values.astype(float)
    pet = df[ep_col].values.astype(float)
    temp = df[t_col].values.astype(float)

    return times, precip, pet, temp


def process(args):
    """Main processing: convert forcing data."""
    if args.format == "era5":
        times, precip, pet, temp = convert_era5(
            args.input, args.lat, args.lon, args.start, args.end)
    elif args.format in ("csv", "generic"):
        times, precip, pet, temp = convert_csv(
            args.input, args.p_col, args.ep_col, args.t_col,
            args.date_col, args.start, args.end)
    else:
        # CMFD/MSWX: similar to ERA5 but with different variable names
        # For now, treat as ERA5 with auto-detection
        times, precip, pet, temp = convert_era5(
            args.input, args.lat, args.lon, args.start, args.end)

    result = {
        "status": "success",
        "n_timesteps": len(times),
        "start_date": str(times[0].date()),
        "end_date": str(times[-1].date()),
        "precip_mean_mm_d": float(np.nanmean(precip)),
        "precip_total_mm": float(np.nansum(precip)),
        "pet_mean_mm_d": float(np.nanmean(pet)),
        "temp_mean_c": float(np.nanmean(temp)),
        "warnings": [],
    }

    # Sanity checks on values
    if np.nanmean(precip) > 50:
        result["warnings"].append(
            "Mean precip > 50 mm/d -- possible unit error (dt_001/dt_002)")
    if np.nanmean(precip) < 0.01:
        result["warnings"].append(
            "Mean precip < 0.01 mm/d -- check if units are m/d (dt_003)")
    if np.nanmean(temp) > 100:
        result["warnings"].append(
            "Mean temp > 100 -- likely Kelvin, subtract 273.15 (dt_006)")
    if np.any(pet < 0):
        result["warnings"].append(
            "Negative PET values found -- check sign convention")
    if np.nanmean(pet) > 20:
        result["warnings"].append(
            "Mean PET > 20 mm/d -- possible radiation input (dt_004)")

    # Write CSV output: columns are P, Ep, T (MARRMoT order!)
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    header = "# MARRMoT forcing file\n"
    header += "# Columns: date, P(mm/d), Ep(mm/d), T(degC)\n"
    header += "# Generated by convert_forcing.py\n"
    header += f"# Period: {result['start_date']} to {result['end_date']}\n"

    with open(output_path, "w") as f:
        f.write(header)
        f.write("date,P_mm_d,Ep_mm_d,T_degC\n")
        for i in range(len(times)):
            f.write(f"{times[i].strftime('%Y-%m-%d')},"
                    f"{precip[i]:.4f},{pet[i]:.4f},{temp[i]:.4f}\n")

    result["output_file"] = output_path
    print(f"Wrote {len(times)} timesteps to {output_path}", file=sys.stderr)
    return result


def validate_outputs(result):
    """Validate output data quality."""
    warnings = result.get("warnings", [])

    if result["n_timesteps"] < 365:
        warnings.append("Less than 1 year of data -- consider longer period")

    if result["precip_total_mm"] < 100:
        warnings.append("Total precip < 100 mm -- unusually dry, check units")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to MARRMoT forcing format")
    parser.add_argument("--input", required=True,
                        help="Input file (NetCDF or CSV)")
    parser.add_argument("--format", default="csv",
                        choices=["era5", "cmfd", "mswx", "csv", "generic"],
                        help="Input data format")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude for gridded data extraction")
    parser.add_argument("--lon", type=float, default=None,
                        help="Longitude for gridded data extraction")
    parser.add_argument("--start", default=None,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--p-col", default="P_mm_d",
                        help="Precipitation column name (CSV format)")
    parser.add_argument("--ep-col", default="Ep_mm_d",
                        help="PET column name (CSV format)")
    parser.add_argument("--t-col", default="T_degC",
                        help="Temperature column name (CSV format)")
    parser.add_argument("--date-col", default="date",
                        help="Date column name (CSV format)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
