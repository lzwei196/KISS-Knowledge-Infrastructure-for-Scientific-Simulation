#!/usr/bin/env python3
"""
convert_met.py — Convert global gridded forcing data to APSIM .met format.

Reads daily or sub-daily weather data from NetCDF (ERA5, CMFD, MSWX) or CSV
and writes an APSIM-compatible .met file with correct units and header.

CRITICAL UNIT CONVERSIONS:
  - Radiation: W/m² (instantaneous) → MJ/m²/day  (multiply by 0.0864)
  - Temperature: K → °C  (subtract 273.15)
  - Vapor pressure: kPa → hPa  (multiply by 10)
  - Rainfall: mm/3hr (CMFD) → mm/day  (sum 8 intervals)
  - Rainfall: m/day (some ERA5) → mm/day  (multiply by 1000)

APSIM .met format:
  Header: [weather.met.weather] section with latitude, longitude, tav, amp
  Columns: year  day  radn  maxt  mint  rain  [optional: pan vp wind co2]
  Units line: ()  ()  (MJ/m^2)  (oC)  (oC)  (mm)  ...

Usage:
  python convert_met.py --input forcing.nc --output site.met \\
      --lat -27.18 --lon 151.26 --station "Dalby" \\
      --source era5  --start 1990-01-01 --end 2020-12-31

  python convert_met.py --input forcing.csv --output site.met \\
      --lat -27.18 --lon 151.26 --station "Dalby" \\
      --source csv --csv-date-col date --csv-radn-col ssrd \\
      --csv-maxt-col tmax --csv-mint-col tmin --csv-rain-col tp
"""

import argparse
import json
import os
import sys
import math
from datetime import datetime, timedelta

import numpy as np
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.humidity import saturation_vapor_pressure
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import xarray as xr
except ImportError:
    xr = None


def validate_inputs(args):
    """Validate input arguments. Exit with JSON error on failure."""
    errors = []

    # API-backed sources (nasa_power / cmfd_lf / mswx_lf) load via
    # ki_tools_common.load_forcing and do not require a local --input file.
    api_sources = ("nasa_power", "cmfd_lf", "mswx_lf")
    if args.source not in api_sources:
        if not args.input or not os.path.isfile(args.input):
            errors.append(f"Input file not found: {args.input}")

    if args.lat is None or not (-90 <= args.lat <= 90):
        errors.append(f"Latitude must be between -90 and 90, got: {args.lat}")

    if args.lon is None or not (-180 <= args.lon <= 360):
        errors.append(f"Longitude must be between -180 and 360, got: {args.lon}")

    if args.source not in ("era5", "cmfd", "mswx", "csv", "auto") + api_sources:
        errors.append(f"Unknown source: {args.source}. Use era5, cmfd, mswx, csv, auto, "
                      f"nasa_power, cmfd_lf, or mswx_lf")

    if args.source in api_sources and (args.start is None or args.end is None):
        errors.append(f"Source '{args.source}' requires --start and --end (YYYY-MM-DD).")

    if args.source == "csv" and pd is None:
        errors.append("pandas is required for CSV input. Install with: pip install pandas")

    if args.source in ("era5", "cmfd", "mswx") and xr is None:
        errors.append("xarray is required for NetCDF input. Install with: pip install xarray netCDF4")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def compute_tav_amp(maxt, mint, doy=None):
    """Compute annual average temperature (tav) and amplitude (amp).

    tav = mean of all daily mean temperatures
    amp = (mean of hottest calendar month) - (mean of coldest calendar month),
          per the APSIM .met specification.

    The previous implementation sliced the *whole* (possibly multi-year) record
    into 12 equal blocks. For a multi-year record each block spans all seasons,
    so the inter-block spread collapses toward zero (e.g. amp=2.3 instead of 17).
    That distorts the CERES soil-temperature model (diagnostic dt_002). When the
    day-of-year (`doy`) is supplied we build a true monthly climatology instead.
    """
    mean_t = (np.array(maxt, dtype=float) + np.array(mint, dtype=float)) / 2.0
    tav = float(np.nanmean(mean_t))

    monthly_means = None
    if doy is not None and len(doy) == len(mean_t):
        # Map day-of-year -> calendar month (non-leap boundaries; climatology only)
        month_end = [31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 366]
        doy_arr = np.array(doy, dtype=int)
        months = np.ones(len(doy_arr), dtype=int)
        for m, end in enumerate(month_end, start=1):
            months[doy_arr <= end] = np.where(months[doy_arr <= end] > 1,
                                              months[doy_arr <= end], m)
        # Simpler robust assignment
        months = np.searchsorted(month_end, doy_arr, side="left") + 1
        months = np.clip(months, 1, 12)
        mm = []
        for m in range(1, 13):
            sel = mean_t[months == m]
            if sel.size:
                mm.append(float(np.nanmean(sel)))
        if len(mm) >= 2:
            monthly_means = mm

    if monthly_means is not None:
        amp = float(max(monthly_means) - min(monthly_means))
    elif len(mean_t) >= 360:
        # Fallback (no doy): assume a single contiguous year, 30-day blocks
        chunk = len(mean_t) // 12
        blocks = [np.nanmean(mean_t[i * chunk:(i + 1) * chunk]) for i in range(12)]
        amp = float(max(blocks) - min(blocks))
    else:
        amp = float(np.nanmax(mean_t) - np.nanmin(mean_t)) * 0.5

    return round(tav, 2), round(amp, 2)


def read_netcdf_era5(filepath, lat, lon, start, end):
    """Read ERA5 NetCDF data and convert units."""
    ds = xr.open_dataset(filepath)

    # Find nearest grid point
    ds_point = ds.sel(latitude=lat, longitude=lon, method="nearest")

    # Time filtering
    if start:
        ds_point = ds_point.sel(time=slice(start, end))

    # Variable name mapping (ERA5 conventions)
    var_map = {
        "ssrd": "radn",   # Surface solar radiation downwards (J/m²/day)
        "mx2t": "maxt",   # Max 2m temperature (K)
        "mn2t": "mint",   # Min 2m temperature (K)
        "tp": "rain",     # Total precipitation (m/day)
        "d2m": "vp_src",  # Dewpoint temperature (K)
    }

    # Alternative names
    alt_names = {
        "t2m_max": "maxt", "t2m_min": "mint", "tmax": "maxt", "tmin": "mint",
        "precip": "rain", "rainfall": "rain", "srad": "radn", "swdown": "radn",
    }
    var_map.update(alt_names)

    data = {}
    for src_var, tgt_var in var_map.items():
        if src_var in ds_point:
            data[tgt_var] = ds_point[src_var].values

    times = pd.DatetimeIndex(ds_point.time.values)
    ds.close()

    # Unit conversions
    records = []
    for i, t in enumerate(times):
        row = {"year": t.year, "day": t.dayofyear}

        # Radiation: J/m²/day → MJ/m²/day (÷1e6) or W/m² → MJ/m²/day (×0.0864)
        if "radn" in data:
            val = float(data["radn"][i])
            if val > 50:  # Likely W/m² or J/m²/day
                if val > 1000:  # J/m²/day
                    row["radn"] = round(val / 1e6, 1)
                else:  # W/m²
                    row["radn"] = round(val * 0.0864, 1)
            else:
                row["radn"] = round(val, 1)

        # Temperature: K → °C
        if "maxt" in data:
            val = float(data["maxt"][i])
            row["maxt"] = round(kelvin_to_celsius(val) if val > 100 else val, 1)
        if "mint" in data:
            val = float(data["mint"][i])
            row["mint"] = round(kelvin_to_celsius(val) if val > 100 else val, 1)

        # Rainfall: m → mm
        if "rain" in data:
            val = float(data["rain"][i])
            row["rain"] = round(val * 1000 if val < 1 else val, 1)
            row["rain"] = max(0, row["rain"])

        # Vapor pressure from dewpoint: hPa
        if "vp_src" in data:
            td = float(data["vp_src"][i])
            if td > 100:
                td -= 273.15
            row["vp"] = round(float(saturation_vapor_pressure(td)), 1)

        records.append(row)

    return records


def read_load_forcing(args):
    """Read daily forcing via ki_tools_common.load_forcing (NASA POWER / CMFD / MSWX).

    This is the SKILL-documented loader path. Returns APSIM .met records with
    radn already converted to MJ/m^2/day (load_forcing returns srad in W/m^2).
    vp (hPa) is derived from specific humidity + pressure when available.
    """
    from ki_tools_common.load_forcing import load_daily_forcing

    src_map = {"nasa_power": "nasa_power", "cmfd_lf": "cmfd", "mswx_lf": "mswx"}
    lf_source = src_map[args.source]

    start_year = int(args.start[:4])
    end_year = int(args.end[:4])
    d = load_daily_forcing(lf_source, args.lat, args.lon, start_year, end_year,
                           forcing_dir=args.forcing_dir)

    # Normalize dates to python datetime (load_forcing may return numpy datetime64)
    raw_dates = d["dates"]
    dates = []
    for x in raw_dates:
        if isinstance(x, np.datetime64):
            dates.append(datetime.utcfromtimestamp(
                (x - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "s")))
        elif hasattr(x, "year"):
            dates.append(x)
        else:
            dates.append(datetime.strptime(str(x)[:10], "%Y-%m-%d"))
    precip = d["precip_mm"]
    tmax = d["temp_max_c"]
    tmin = d["temp_min_c"]
    srad = d.get("srad_wm2")
    shum = d.get("shum_kgkg")
    pres = d.get("pres_pa")
    wind = d.get("wind_ms")

    records = []
    for i, dt in enumerate(dates):
        # Filter to exact start/end day bounds
        ds = dt.strftime("%Y-%m-%d")
        if ds < args.start or ds > args.end:
            continue
        rec = {"year": dt.year, "day": dt.timetuple().tm_yday}
        # Radiation: W/m^2 (daily mean) -> MJ/m^2/day
        if srad is not None and not (srad[i] != srad[i]):  # not NaN
            rec["radn"] = round(float(srad[i]) * 0.0864, 1)
        rec["maxt"] = round(float(tmax[i]), 1)
        rec["mint"] = round(float(tmin[i]), 1)
        rec["rain"] = round(max(0.0, float(precip[i])), 1)
        # Vapour pressure (hPa) from specific humidity + pressure: e = q*p/(0.622+0.378q)
        if shum is not None and pres is not None:
            q = float(shum[i]); p = float(pres[i])
            if q == q and p == p and q > 0:
                e_pa = q * p / (0.622 + 0.378 * q)
                rec["vp"] = round(e_pa / 100.0, 1)  # Pa -> hPa
        if wind is not None and wind[i] == wind[i]:
            rec["wind"] = round(float(wind[i]), 1)
        records.append(rec)

    return records


def read_csv_input(filepath, args):
    """Read CSV input with user-specified column mappings."""
    df = pd.read_csv(filepath, parse_dates=[args.csv_date_col or "date"])

    date_col = args.csv_date_col or "date"
    col_map = {
        args.csv_radn_col or "radn": "radn",
        args.csv_maxt_col or "maxt": "maxt",
        args.csv_mint_col or "mint": "mint",
        args.csv_rain_col or "rain": "rain",
    }

    records = []
    for _, row in df.iterrows():
        dt = pd.Timestamp(row[date_col])
        rec = {"year": dt.year, "day": dt.dayofyear}

        for src, tgt in col_map.items():
            if src in row:
                val = float(row[src])
                # Auto-detect and convert units
                if tgt == "radn" and val > 50:
                    val = val * 0.0864  # W/m² → MJ/m²/day
                elif tgt in ("maxt", "mint") and val > 100:
                    val -= 273.15  # K → °C
                elif tgt == "rain" and val < 0:
                    val = 0.0
                rec[tgt] = round(val, 1)

        records.append(rec)

    return records


def process(args):
    """Main processing: read input data and build met file content."""
    if args.source in ("nasa_power", "cmfd_lf", "mswx_lf"):
        records = read_load_forcing(args)
    elif args.source in ("era5", "cmfd", "mswx"):
        records = read_netcdf_era5(args.input, args.lat, args.lon,
                                   args.start, args.end)
    elif args.source == "csv":
        records = read_csv_input(args.input, args)
    else:
        # Auto-detect from extension
        if args.input.endswith(".nc") or args.input.endswith(".nc4"):
            records = read_netcdf_era5(args.input, args.lat, args.lon,
                                       args.start, args.end)
        else:
            records = read_csv_input(args.input, args)

    # Compute tav and amp
    maxt_vals = [r.get("maxt", 20) for r in records]
    mint_vals = [r.get("mint", 10) for r in records]
    doy_vals = [r.get("day", 1) for r in records]
    tav, amp = compute_tav_amp(maxt_vals, mint_vals, doy=doy_vals)

    # Determine which optional columns are present
    has_vp = any("vp" in r for r in records)
    has_pan = any("pan" in r for r in records)
    has_wind = any("wind" in r for r in records)

    # Build header
    lines = []
    lines.append("[weather.met.weather]")
    lines.append(f"!station name = {args.station or 'Unknown'}")
    lines.append(f"latitude = {args.lat:.2f}  (DECIMAL DEGREES)")
    lines.append(f"longitude = {args.lon:.2f}  (DECIMAL DEGREES)")
    lines.append(f"tav = {tav:6.2f} (oC) ! annual average ambient temperature")
    lines.append(f"amp = {amp:6.2f} (oC) ! annual amplitude in mean monthly temperature")
    lines.append("")

    # Column headers and units
    cols = ["year", "day", "radn", "maxt", "mint", "rain"]
    units = ["()", "()", "(MJ/m^2)", "(oC)", "(oC)", "(mm)"]
    if has_pan:
        cols.append("pan")
        units.append("(mm)")
    if has_vp:
        cols.append("vp")
        units.append("(hPa)")
    if has_wind:
        cols.append("wind")
        units.append("(m/s)")

    lines.append("  ".join(f"{c:>8}" for c in cols))
    lines.append("  ".join(f"{u:>8}" for u in units))

    # Data rows
    for rec in records:
        vals = [
            f"{rec.get('year', 1900):8d}",
            f"{rec.get('day', 1):4d}",
            f"{rec.get('radn', 0.0):8.1f}",
            f"{rec.get('maxt', 20.0):8.1f}",
            f"{rec.get('mint', 10.0):8.1f}",
            f"{rec.get('rain', 0.0):8.1f}",
        ]
        if has_pan:
            vals.append(f"{rec.get('pan', 0.0):8.1f}")
        if has_vp:
            vals.append(f"{rec.get('vp', 10.0):8.1f}")
        if has_wind:
            vals.append(f"{rec.get('wind', 2.0):8.1f}")
        lines.append("  ".join(vals))

    return {
        "status": "ok",
        "content": "\n".join(lines),
        "n_records": len(records),
        "date_range": f"{records[0]['year']}/{records[0]['day']} - {records[-1]['year']}/{records[-1]['day']}",
        "tav": tav,
        "amp": amp,
        "columns": cols,
    }


def validate_outputs(result):
    """Validate output quality. Return warnings list."""
    warnings = []

    if result["n_records"] == 0:
        warnings.append("No records produced — check input data and date range")

    if result["tav"] < -30 or result["tav"] > 45:
        warnings.append(f"tav={result['tav']}°C is outside typical range (-30 to 45)")

    if result["amp"] < 0 or result["amp"] > 40:
        warnings.append(f"amp={result['amp']}°C is outside typical range (0 to 40)")

    # Check for radiation range issues in content
    content_lines = result["content"].split("\n")
    data_start = False
    radn_issues = 0
    for line in content_lines:
        if line.strip().startswith("()"):
            data_start = True
            continue
        if data_start and line.strip():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    radn = float(parts[2])
                    if radn > 40:
                        radn_issues += 1
                    elif radn < 0:
                        radn_issues += 1
                except ValueError:
                    pass

    if radn_issues > 0:
        warnings.append(
            f"{radn_issues} days with radiation outside 0-40 MJ/m²/day range. "
            "Check that radiation was converted from W/m² correctly (×0.0864)"
        )

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to APSIM .met format"
    )
    parser.add_argument("--input", required=False, default=None,
                        help="Input file (NetCDF or CSV). Not needed for API sources "
                             "nasa_power/cmfd_lf/mswx_lf.")
    parser.add_argument("--output", required=True, help="Output .met file path")
    parser.add_argument("--forcing-dir", type=str, default=None,
                        help="Root dir for cmfd_lf/mswx_lf load_forcing sources")
    parser.add_argument("--lat", type=float, required=True, help="Site latitude (decimal degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Site longitude (decimal degrees)")
    parser.add_argument("--station", type=str, default="Unknown", help="Station name")
    parser.add_argument("--source", type=str, default="auto",
                        help="Data source: era5, cmfd, mswx, csv, auto")
    parser.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD)")
    # CSV column mapping
    parser.add_argument("--csv-date-col", type=str, default="date")
    parser.add_argument("--csv-radn-col", type=str, default="radn")
    parser.add_argument("--csv-maxt-col", type=str, default="maxt")
    parser.add_argument("--csv-mint-col", type=str, default="mint")
    parser.add_argument("--csv-rain-col", type=str, default="rain")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Write .met file
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(result["content"])

    # Print summary (without full content)
    summary = {k: v for k, v in result.items() if k != "content"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
