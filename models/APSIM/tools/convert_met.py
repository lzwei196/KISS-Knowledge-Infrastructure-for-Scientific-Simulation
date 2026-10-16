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
      --csv-maxt-col tmax --csv-mint-col tmin --csv-rain-col tp \\
      --csv-radn-units W/m2 --csv-temp-units K --csv-rain-units m/day

Units are never guessed from the size of the values: NetCDF inputs use each
variable's `units` attribute (missing/unknown -> stop); CSV inputs have no
unit metadata, so --csv-radn-units, --csv-temp-units and --csv-rain-units are
REQUIRED for CSV.
"""

import argparse
import json
import os
import sys
import math
from datetime import datetime, timedelta

import numpy as np
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
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


# Rainfall below this (mm/day) is not a tiny rounding/packing artefact: it is
# a missing-value marker (e.g. -9999) or bad data. It must NOT become a dry
# day; it becomes NaN so the required-column check stops the tool.
RAIN_NEG_TOL_MM = -0.05   # values in (-0.05, 0) print as 0.0 at 0.1 mm anyway


def _rain_mm(v):
    """Daily rain (mm) -> value for the .met file; bad negatives -> NaN."""
    v = float(v)
    if v != v:                      # NaN stays NaN (caught in process)
        return v
    if v < 0:
        return 0.0 if v > RAIN_NEG_TOL_MM else float("nan")
    return v


def read_netcdf_era5(filepath, lat, lon, start, end):
    """Read ERA5 NetCDF data and convert units."""
    ds = xr.open_dataset(filepath)

    # Find nearest grid point. Longitude is picked by CIRCULAR distance, so
    # the file's convention (0..360 or -180..180) does not matter and the
    # wrap point is handled (e.g. -0.1 on a 0..359.75 grid -> 0, not 359.75).
    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        ds.close()
        raise SystemExit(f"ERROR: {filepath}: needs 'latitude' and 'longitude' "
                         f"coordinates. Nothing written.")
    lon_vals = np.asarray(ds["longitude"].values, dtype=float)
    lon_q = float(lon)
    circ = np.abs(((lon_vals - lon_q) + 180.0) % 360.0 - 180.0)
    ds_point = ds.sel(latitude=lat, method="nearest").isel(longitude=int(np.nanargmin(circ)))
    # The chosen cell must really be near the site (not an edge cell of a
    # grid that does not cover it).
    lat_sel = float(ds_point["latitude"].values)
    lon_sel = float(ds_point["longitude"].values)
    dlon = abs(((lon_sel - lon_q) + 180.0) % 360.0 - 180.0)
    def _step(v):
        v = np.unique(np.asarray(v, dtype=float))
        return float(np.min(np.diff(v))) if v.size > 1 else None
    lat_step, lon_step = _step(ds["latitude"].values), _step(ds["longitude"].values)
    if ((lat_step is not None and abs(lat_sel - lat) > lat_step) or
            (lon_step is not None and dlon > lon_step) or
            (lat_step is None and abs(lat_sel - lat) > 0.5) or
            (lon_step is None and dlon > 0.5)):
        ds.close()
        raise SystemExit(f"ERROR: {filepath}: nearest cell ({lat_sel}, {lon_sel}) is "
                         f"not near the site ({lat}, {lon}); the file does not cover "
                         f"it. Nothing written.")

    # The time step is checked on the WHOLE time axis, before any date
    # filter: after slicing, a single remaining hourly step would look like a
    # "daily" record. Accumulations ('J m-2', 'm') are per time step, so the
    # file must be daily. Gaps (whole-day steps > 1 day) are allowed here and
    # caught for the requested period by the completeness check in process().
    all_times = pd.DatetimeIndex(ds_point.time.values)
    if len(all_times) < 2:
        ds.close()
        raise SystemExit(f"ERROR: {filepath}: only {len(all_times)} time stamp(s); the "
                         f"daily time step cannot be checked. Nothing written.")
    steps = np.unique(np.diff(all_times.values).astype("timedelta64[s]").astype(np.int64))
    if steps.min() <= 0 or np.any(steps % 86400 != 0) or int(steps.min()) != 86400:
        ds.close()
        raise SystemExit(f"ERROR: {filepath}: time step is not one day "
                         f"({steps[:5]} s); APSIM .met is daily. Nothing written.")

    # Time filtering
    if start or end:
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

    data, units = {}, {}
    for src_var, tgt_var in var_map.items():
        if src_var in ds_point:
            data[tgt_var] = ds_point[src_var].values
            u = ds_point[src_var].attrs.get("units")
            if u is None:
                ds.close()
                raise SystemExit(f"ERROR: {filepath}: variable '{src_var}' has no units "
                                 f"attribute; units are not guessed. Nothing written.")
            units[tgt_var] = (src_var, " ".join(str(u).replace("**", "").split()))

    times = pd.DatetimeIndex(ds_point.time.values)
    ds.close()

    # Units come from each variable's own `units` attribute (never from the
    # size of the values). The daily time step was checked above on the
    # whole (unfiltered) time axis.

    def factor(tgt, table):
        src, u = units[tgt]
        if u not in table:
            raise SystemExit(f"ERROR: {filepath}: {src} units {u!r} are not known "
                             f"(known: {sorted(table)}); nothing converted or written.")
        return table[u]

    RADN = {"J m-2": 1e-6, "J m-2 day-1": 1e-6, "J m-2 d-1": 1e-6,
            "MJ m-2": 1.0, "MJ m-2 day-1": 1.0, "MJ m-2 d-1": 1.0,
            "W m-2": 0.0864, "W/m2": 0.0864}
    TOFF = {"K": -273.15, "degC": 0.0, "degree_Celsius": 0.0, "C": 0.0}
    RAIN = {"m": 1000.0, "m day-1": 1000.0, "m d-1": 1000.0, "mm": 1.0,
            "mm day-1": 1.0, "mm d-1": 1.0, "kg m-2": 1.0,
            "kg m-2 s-1": 86400.0, "mm s-1": 86400.0}
    f_radn = factor("radn", RADN) if "radn" in data else None
    o_maxt = factor("maxt", TOFF) if "maxt" in data else None
    o_mint = factor("mint", TOFF) if "mint" in data else None
    f_rain = factor("rain", RAIN) if "rain" in data else None
    o_td = factor("vp_src", TOFF) if "vp_src" in data else None

    # Unit conversions
    records = []
    for i, t in enumerate(times):
        row = {"year": t.year, "day": t.dayofyear}

        if "radn" in data:
            row["radn"] = round(float(data["radn"][i]) * f_radn, 1)
        if "maxt" in data:
            row["maxt"] = round(float(data["maxt"][i]) + o_maxt, 1)
        if "mint" in data:
            row["mint"] = round(float(data["mint"][i]) + o_mint, 1)

        if "rain" in data:
            row["rain"] = round(_rain_mm(float(data["rain"][i]) * f_rain), 1)

        # Vapor pressure from dewpoint: hPa
        if "vp_src" in data:
            td = float(data["vp_src"][i]) + o_td
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
                           forcing_dir=args.forcing_dir,
                           period=(args.start, args.end))

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
        rec["rain"] = round(_rain_mm(precip[i]), 1)  # bad negative -> NaN
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


# Declared CSV units (--csv-*-units) -> APSIM units (MJ/m2/day, degC, mm/day)
CSV_RADN_UNITS = {"MJ/m2/day": 1.0, "W/m2": 0.0864, "J/m2/day": 1e-6}
CSV_TEMP_UNITS = {"C": 0.0, "K": -273.15}
CSV_RAIN_UNITS = {"mm/day": 1.0, "m/day": 1000.0}


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

    # A CSV carries no unit metadata, so the units must be given on the
    # command line (no guessing from the size of the values).
    need = {"--csv-radn-units": args.csv_radn_units,
            "--csv-temp-units": args.csv_temp_units,
            "--csv-rain-units": args.csv_rain_units}
    missing = [k for k, v in need.items() if v is None]
    if missing:
        raise SystemExit(f"ERROR: CSV input has no unit metadata; give {missing} "
                         f"explicitly. Nothing written.")
    f_radn = CSV_RADN_UNITS[args.csv_radn_units]
    o_temp = CSV_TEMP_UNITS[args.csv_temp_units]
    f_rain = CSV_RAIN_UNITS[args.csv_rain_units]

    records = []
    for _, row in df.iterrows():
        dt = pd.Timestamp(row[date_col])
        rec = {"year": dt.year, "day": dt.dayofyear}

        for src, tgt in col_map.items():
            if src in row:
                val = float(row[src])
                if tgt == "radn":
                    val = val * f_radn
                elif tgt in ("maxt", "mint"):
                    val = val + o_temp
                elif tgt == "rain":
                    val = _rain_mm(val * f_rain)   # -9999 etc. -> NaN
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

    # Keep only the days inside --start/--end (each bound on its own). Not
    # every reader filters (CSV never does; NetCDF only on the bounds given),
    # so the filter is done once here, before any check.
    def _rec_day(r):
        return datetime(int(r["year"]), 1, 1) + timedelta(days=int(r["day"]) - 1)
    lo = datetime.strptime(args.start[:10], "%Y-%m-%d") if args.start else None
    hi = datetime.strptime(args.end[:10], "%Y-%m-%d") if args.end else None
    if lo is not None and hi is not None and lo > hi:
        raise SystemExit(f"ERROR: --start {args.start} is after --end {args.end}; "
                         f"nothing written.")
    records = [r for r in records
               if (lo is None or _rec_day(r) >= lo) and (hi is None or _rec_day(r) <= hi)]

    # Every required APSIM column must hold a real value on every day; a
    # missing one stops the tool (nothing is filled in, nothing is written).
    if not records:
        raise SystemExit("ERROR: no weather records in the requested period; "
                         "nothing written.")

    def _real(r, k):
        v = r.get(k)
        try:
            return v is not None and math.isfinite(float(v))
        except (TypeError, ValueError):
            return False

    for k in ("year", "day", "radn", "maxt", "mint", "rain"):
        bad = [r for r in records if not _real(r, k)]
        if bad:
            first = ", ".join(f"{r.get('year')}/{r.get('day')}" for r in bad[:5])
            raise SystemExit(
                f"ERROR: required APSIM column '{k}' is missing or invalid (NaN, or rain below "
                f"{RAIN_NEG_TOL_MM} mm such as a -9999 marker) on {len(bad)} of "
                f"{len(records)} days (first year/day: {first}). Nothing is filled "
                f"in; nothing written.")

    # The days themselves must be complete: one record per day, in order,
    # from --start (or the first record) to --end (or the last record). A
    # missing day is not a missing value, so the check above cannot see it.
    rec_days = [_rec_day(r) for r in records]
    d0 = datetime.strptime(args.start[:10], "%Y-%m-%d") if args.start else rec_days[0]
    d1 = datetime.strptime(args.end[:10], "%Y-%m-%d") if args.end else rec_days[-1]
    want_days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    if rec_days != want_days:
        have = set(rec_days)
        lost = [d for d in want_days if d not in have]
        raise SystemExit(
            f"ERROR: daily records are not complete in {d0:%Y-%m-%d}..{d1:%Y-%m-%d}: "
            f"{len(records)} records for {len(want_days)} days, {len(lost)} missing "
            f"(first: {', '.join(f'{d:%Y-%m-%d}' for d in lost[:5])}), "
            f"{len(rec_days) - len(set(rec_days))} duplicated. Nothing is filled "
            f"in; nothing written.")

    # Compute tav and amp
    maxt_vals = [r["maxt"] for r in records]
    mint_vals = [r["mint"] for r in records]
    doy_vals = [r["day"] for r in records]
    tav, amp = compute_tav_amp(maxt_vals, mint_vals, doy=doy_vals)

    # Optional columns (APSIM works without them) are written only when EVERY
    # day has a real value; a partly missing optional column is left out with
    # a warning, never filled.
    dropped_optional = {}
    present = {}
    for k in ("pan", "vp", "wind"):
        n_real = sum(1 for r in records if _real(r, k))
        present[k] = n_real == len(records)
        if 0 < n_real < len(records):
            dropped_optional[k] = len(records) - n_real
            print(f"WARNING: optional column '{k}' is missing on "
                  f"{len(records) - n_real} of {len(records)} days; the column is "
                  f"left out of the .met file (not filled).", file=sys.stderr)
    has_pan, has_vp, has_wind = present["pan"], present["vp"], present["wind"]

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
            f"{rec['year']:8d}",
            f"{rec['day']:4d}",
            f"{rec['radn']:8.1f}",
            f"{rec['maxt']:8.1f}",
            f"{rec['mint']:8.1f}",
            f"{rec['rain']:8.1f}",
        ]
        if has_pan:
            vals.append(f"{rec['pan']:8.1f}")
        if has_vp:
            vals.append(f"{rec['vp']:8.1f}")
        if has_wind:
            vals.append(f"{rec['wind']:8.1f}")
        lines.append("  ".join(vals))

    return {
        "status": "ok",
        "content": "\n".join(lines),
        "n_records": len(records),
        "date_range": f"{records[0]['year']}/{records[0]['day']} - {records[-1]['year']}/{records[-1]['day']}",
        "tav": tav,
        "amp": amp,
        "columns": cols,
        "optional_columns_left_out": dropped_optional,
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
    # CSV has no unit metadata: these are REQUIRED for CSV input (no default
    # and no guessing from the values)
    parser.add_argument("--csv-radn-units", choices=sorted(CSV_RADN_UNITS), default=None,
                        help="units of the CSV radiation column (required for CSV)")
    parser.add_argument("--csv-temp-units", choices=sorted(CSV_TEMP_UNITS), default=None,
                        help="units of the CSV maxt/mint columns (required for CSV)")
    parser.add_argument("--csv-rain-units", choices=sorted(CSV_RAIN_UNITS), default=None,
                        help="units of the CSV rain column, daily totals (required for CSV)")

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
