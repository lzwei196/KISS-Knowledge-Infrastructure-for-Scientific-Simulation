#!/usr/bin/env python3
"""
convert_met_to_glm.py — Convert CMFD/MSWX/NASA POWER forcing to GLM meteorological CSV.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Rain: CMFD/MSWX give mm/3hr. GLM wants m/day. Conversion: mm/3hr * 8 / 1000
  - RelHum: CMFD/MSWX give specific humidity (kg/kg) + pressure (Pa) -> VP (kPa).
    GLM wants RH in % (0-100).
    Formula: RH = 100 * VP / (0.6108 * exp(17.27*T/(T+237.3)))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
  - ShortWave: Clip to >= 0 (interpolation can produce negative at night)
  - Snow: Partition from rain when T < snow_threshold (default 0 degC)

GLM CSV format:
  time,ShortWave,LongWave,AirTemp,RelHum,WindSpeed,Rain,Snow
  YYYY-MM-DD HH:MM:SS,W/m2,W/m2,degC,%,m/s,m/day,m/day

Usage:
    python convert_met_to_glm.py \
        --forcing_dir /path/to/cmfd_or_mswx \
        --lat 40.48 --lon 116.97 \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output bcs/met_hourly.csv

    python convert_met_to_glm.py \
        --vic_forcing_dir /path/to/vic/forcing/forcing_final \
        --lat 40.48 --lon 116.97 \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output bcs/met_hourly.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
# NOTE: do NOT add the auto_dissect copy of ki_tools_common to sys.path here.
# That copy carries a stale _load_nasa_power that reads only the near-zero
# WS2M wind (~0.05 m/s -> no lake mixing -> runaway surface warming), and the
# path-based finder would shadow the canonical editable-installed package.
# The canonical pip-installed ki_tools_common (models/ki_tools_common) has the
# WS10M-preferring fix (see feedback_nasa_power_wind_height) and ships units,
# humidity and load_forcing, so it resolves correctly with no path edits.
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius
from ki_tools_common.humidity import saturation_vapor_pressure


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if (getattr(args, "forcing_source", None) != "nasa_power"
            and args.forcing_dir is None and args.vic_forcing_dir is None):
        errors.append("Must provide --forcing_source nasa_power, or "
                      "--forcing_dir (CMFD/MSWX), or --vic_forcing_dir "
                      "(VIC forcing files)")

    if args.forcing_dir and not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if args.vic_forcing_dir and not os.path.isdir(args.vic_forcing_dir):
        errors.append(f"VIC forcing directory not found: {args.vic_forcing_dir}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon < -180 or args.lon > 180:
        errors.append(f"--lon must be between -180 and 180, got {args.lon}")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Invalid date format: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def vp_to_rh(vp_kpa, temp_c):
    """
    Convert vapor pressure (kPa) to relative humidity (%).

    Uses the Tetens formula for saturation vapor pressure:
    VP_sat = 0.6108 * exp(17.27 * T / (T + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    RH = 100 * VP / VP_sat

    CRITICAL: Result must be 0-100 (percentage), NOT 0-1 (fraction).
    """
    vp_sat = 0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    rh = 100.0 * vp_kpa / vp_sat
    # Clip to physical range
    rh = np.clip(rh, 0.0, 100.0)
    return rh


def precip_mm_3hr_to_m_day(precip_mm_3hr):
    """
    Convert precipitation from mm/3hr to m/day.

    CMFD/MSWX: mm per 3-hour timestep
    GLM: meters per day

    Conversion: mm/3hr * (24/3) / 1000 = mm/3hr * 8 / 1000
    i.e., multiply rate by 8 (to get mm/day) then divide by 1000 (to get m/day)

    CRITICAL: Using mm/day instead of m/day causes lake to flood (1000x too much rain).
    """
    return precip_mm_3hr * 8.0 / 1000.0


def partition_rain_snow(precip_m_day, temp_c, snow_threshold=0.0):
    """
    Partition total precipitation into rain and snow based on air temperature.

    Below snow_threshold: all snow
    Above snow_threshold + 2: all rain
    Between: linear interpolation
    """
    rain = np.where(temp_c > snow_threshold + 2.0, precip_m_day,
                    np.where(temp_c < snow_threshold, 0.0,
                             precip_m_day * (temp_c - snow_threshold) / 2.0))
    snow = precip_m_day - rain
    return np.maximum(rain, 0.0), np.maximum(snow, 0.0)


def read_vic_forcing(vic_forcing_dir, lat, lon, start_date, end_date,
                     snow_threshold=0.0):
    """
    Read VIC ASCII forcing files and convert to GLM format.

    VIC forcing file columns as read below (7 variables; the order was
    checked on real files when this tool was written: col 3 is 0 at night,
    col 4 ~230 W/m2 all day):
    0: AIR_TEMP (degC)
    1: PREC (mm per time step)
    2: PRESSURE (kPa)
    3: SWDOWN (W/m2)
    4: LWDOWN (W/m2)
    5: VP (kPa)
    6: WIND (m/s)

    The file has no dates. Its first row is taken as start_date 00:00, so the
    file must hold exactly start_date..end_date at one of 24, 8, 4 or 1 rows a
    day; any other row count stops (no guess of the step).
    Returns (df, step_seconds); df has Rain and Snow split at snow_threshold.
    """
    # Find the closest VIC forcing file
    import glob
    pattern = os.path.join(vic_forcing_dir, f"*_{lat:.4f}_{lon:.4f}")
    files = glob.glob(pattern)
    if not files:
        # Try with different precision
        pattern = os.path.join(vic_forcing_dir, f"*_{lat:.2f}*_{lon:.2f}*")
        files = glob.glob(pattern)
    if not files:
        # Search all files and find closest
        all_files = glob.glob(os.path.join(vic_forcing_dir, "*"))
        best_dist = float('inf')
        best_file = None
        for f in all_files:
            basename = os.path.basename(f)
            parts = basename.split('_')
            try:
                flat = float(parts[-2])
                flon = float(parts[-1])
                dist = (flat - lat) ** 2 + (flon - lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_file = f
            except (ValueError, IndexError):
                continue
        if best_file:
            files = [best_file]

    if not files:
        print(json.dumps({"status": "error",
                          "errors": [f"No VIC forcing file found near {lat}, {lon}"]}))
        sys.exit(1)

    forcing_file = files[0]
    print(f"Reading VIC forcing from {forcing_file}", file=sys.stderr)

    data = np.loadtxt(forcing_file, ndmin=2)
    if data.shape[1] < 7:
        _fail(f"{forcing_file}: {data.shape[1]} columns, the VIC forcing format "
              f"read here needs 7 (AIR_TEMP PREC PRESSURE SWDOWN LWDOWN VP WIND)")

    # Time step from the row count: the file must hold exactly the requested
    # days at a whole number of rows per day (exact match, so an hourly file
    # is never read as 3-hourly and a longer file is never cut by guess).
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    n_days = (end_dt - start_dt).days + 1
    n_rows = data.shape[0]
    steps_per_day = next((k for k in (24, 8, 4, 1) if n_rows == n_days * k), None)
    if steps_per_day is None:
        _fail(f"{forcing_file}: {n_rows} rows do not match {n_days} days "
              f"({start_date}..{end_date}) at 24, 8, 4 or 1 rows a day. The file "
              f"has no dates, so it must hold exactly the requested period; "
              f"nothing is cut or filled")

    dt_hours = 24 / steps_per_day

    # Every source value must be a real number BEFORE any clip (vp_to_rh clips
    # to 0-100 and SW is clipped at 0, which would hide inf/NaN/-inf).
    raw = data[:, :7]
    if not np.isfinite(raw).all():
        names = ["AIR_TEMP", "PREC", "PRESSURE", "SWDOWN", "LWDOWN", "VP", "WIND"]
        badc = {names[j]: int((~np.isfinite(raw[:, j])).sum()) for j in range(7)
                if not np.isfinite(raw[:, j]).all()}
        _fail(f"{forcing_file}: non-finite values (nan/inf) in {badc}; "
              f"nothing is filled in")

    # Build time index
    times = [start_dt + timedelta(hours=i * dt_hours)
             for i in range(data.shape[0])]

    # Extract variables (VIC 7-column format: AIR_TEMP, PREC, PRESSURE, SWDOWN, LWDOWN, VP, WIND)
    # Verified empirically: col3=SWDOWN (0 at night, >100 daytime), col4=LWDOWN (~230 constant)
    temp_c = data[:, 0]      # degC
    precip_mm = data[:, 1]   # mm/timestep
    pressure = data[:, 2]    # kPa
    sw = data[:, 3]          # W/m2 (SWDOWN - zero at night)
    lw = data[:, 4]          # W/m2 (LWDOWN - ~200-400 constant)
    vp = data[:, 5]          # kPa
    wind = data[:, 6]        # m/s

    # Convert units
    # Precip: mm/timestep -> m/day
    precip_m_day = precip_mm * (24.0 / dt_hours) / 1000.0
    rh = vp_to_rh(vp, temp_c)
    sw = np.maximum(sw, 0.0)  # CRITICAL: clip negative SW
    rain, snow = partition_rain_snow(precip_m_day, temp_c, snow_threshold)

    df = pd.DataFrame({
        'time': times,
        'ShortWave': sw,
        'LongWave': lw,
        'AirTemp': temp_c,
        'RelHum': rh,
        'WindSpeed': wind,
        'Rain': rain,
        'Snow': snow,
    })

    return df, int(round(dt_hours * 3600))


def _fail(message):
    """Stop with the tool's error JSON (no output file, never 'success')."""
    print(json.dumps({"status": "error", "errors": [message]}))
    sys.exit(1)


# Units the shared loader's sub-daily conversion is written for, per source and
# variable (folder, NetCDF variable, units attribute). The source files' own
# `units` attribute is checked against these before any value is used, so a
# store in other units stops instead of being converted wrongly.
_SUBDAILY_UNITS = {
    "cmfd": {
        "temp": ("Temp", "temp", "K"),
        "prec": ("Prec", "prec", "kg m-2 s-1"),
        "srad": ("SRad", "srad", "W m-2"),
        "lrad": ("LRad", "lrad", "W m-2"),
        "wind": ("Wind", "wind", "m s-1"),
        "shum": ("SHum", "shum", "kg kg-1"),
        "pres": ("Pres", "pres", "Pa"),
    },
    "mswx": {
        "temp": ("Tair", "air_temperature", "degree_Celsius"),
        "prec": ("P", "precipitation", "mm 3h-1"),
        "srad": ("SWd", "downward_shortwave_radiation", "W m-2"),
        "lrad": ("LWd", "downward_longwave_radiation", "W m-2"),
        "wind": ("wind", "wind_speed", "m s-1"),
        "shum": ("spechum", "specific_humidity", "kg kg-1"),
        "pres": ("Pres", "surface_pressure", "Pa"),
    },
}


def _check_source_units(source, forcing_dir, start_dt, end_dt):
    """Stop unless every file the loader will read for start..end carries the
    units attribute the loader's conversion is written for."""
    import glob
    import netCDF4
    if source == "cmfd":
        months, d = [], datetime(start_dt.year, start_dt.month, 1)
        while d <= end_dt:
            months.append("%d%02d" % (d.year, d.month))
            d = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)
        stamps = months
    else:
        stamps = [str(y) for y in range(start_dt.year, end_dt.year + 1)]
    for key, (folder, var, want) in _SUBDAILY_UNITS[source].items():
        for st in stamps:
            files = sorted(glob.glob(os.path.join(forcing_dir, folder, f"*_{st}.nc")))
            if not files:
                _fail(f"{source}: no {folder}/*_{st}.nc under {forcing_dir}; "
                      f"nothing is filled in")
            try:
                with netCDF4.Dataset(files[0]) as ds:
                    if var not in ds.variables:
                        _fail(f"{files[0]}: no variable '{var}'")
                    got = getattr(ds.variables[var], "units", None)
                    # The shared loader indexes [:, lat_i, lon_i] by position:
                    # only (time, lat, lon) is safe to hand to it.
                    dims = tuple(ds.variables[var].dimensions)
                    if dims != ("time", "lat", "lon"):
                        _fail(f"{files[0]}: {var} dimensions {dims}; the shared loader "
                              f"reads (time, lat, lon) by position, nothing converted")
                    if "time" in ds.variables:
                        _check_time_meta(ds.variables["time"], files[0])
                    # The shared loader opens with xarray, which masks only a
                    # DECLARED _FillValue (and missing_value), not netCDF's
                    # default fill of an unwritten cell, and does not apply
                    # valid_min/max/range. Real CMFD declares _FillValue (and
                    # missing_value) and no valid_* attributes, so require
                    # _FillValue and refuse valid_* rather than ignore them.
                    catts = set(ds.variables[var].ncattrs())
                    if "_FillValue" not in catts:
                        _fail(f"{files[0]}: {var} declares no _FillValue, so unwritten "
                              f"cells could not be told from data; nothing converted")
                    vr = catts & {"valid_min", "valid_max", "valid_range"}
                    if vr:
                        _fail(f"{files[0]}: {var} declares {sorted(vr)}, which the shared "
                              f"loader does not apply; nothing converted")
                    for cv in ("lat", "lon", "time"):
                        if cv not in ds.variables or \
                                tuple(ds.variables[cv].dimensions) != (cv,):
                            _fail(f"{files[0]}: coordinate '{cv}' missing or not 1-D on "
                                  f"its own dimension; nothing converted")
                        # Read with netCDF4's masking on: a masked (fill) or
                        # non-finite coordinate would win the shared loader's
                        # argmin and pick a wrong cell / step. Stop instead.
                        cvals = np.ma.asarray(ds.variables[cv][:]).astype(float)
                        nbad = int(np.ma.count_masked(cvals)) + \
                            int((~np.isfinite(cvals.filled(0.0))).sum())
                        if nbad:
                            _fail(f"{files[0]}: coordinate '{cv}' has {nbad} missing or "
                                  f"non-finite values; nothing converted")
                        if any(a in ds.variables[cv].ncattrs()
                               for a in ("scale_factor", "add_offset")):
                            _fail(f"{files[0]}: coordinate '{cv}' is packed; not "
                                  f"handled, nothing converted")
            except OSError as e:
                _fail(f"{files[0]}: cannot be read ({e})")
            if got != want:
                _fail(f"{files[0]}: {var} units are {got!r}, the conversion is "
                      f"written for {want!r}; unknown units, nothing converted")


# MSWX annual file name prefix per variable folder (wind/Wind_YYYY.nc).
_MSWX_PREFIX = {"Tair": "Tair", "P": "P", "SWd": "SWd", "LWd": "LWd",
                "wind": "Wind", "spechum": "spechum", "Pres": "Pres"}
_MSWX_STEP_S = 10800          # MSWX is 3-hourly


def _nc_attrs(v):
    """A netCDF4 variable's attributes as a dict."""
    return {k: v.getncattr(k) for k in v.ncattrs()}


_OK_CALENDARS = ("standard", "gregorian", "proleptic_gregorian")
_TIME_BASE_RE = None


def _check_time_meta(tvar, fpath):
    """Stop unless the time variable uses a calendar and an origin these
    dates are decoded for: calendar absent or standard / gregorian /
    proleptic_gregorian (a noleap or 360_day axis would put values on the
    wrong day), and units '<days|hours|minutes|seconds> since Y-M-D[ H:M[:S]]'
    with no time-zone offset, or an explicit zero one (Z, UTC, +00:00, +0).
    Returns (seconds per unit, origin as datetime). Used for MSWX (decoded
    here) and CMFD (checked before the shared loader decodes it)."""
    import re
    global _TIME_BASE_RE
    if _TIME_BASE_RE is None:
        _TIME_BASE_RE = re.compile(
            r"^(\d{1,4})-(\d{1,2})-(\d{1,2})"
            r"(?:[T ](\d{1,2}):(\d{1,2})(?::(\d{1,2}(?:\.\d*)?))?)?"
            r"\s*(Z|UTC|GMT|[+-]0{1,2}(?::?00)?)?$", re.IGNORECASE)
    att = {k: tvar.getncattr(k) for k in tvar.ncattrs()}
    cal = att.get("calendar", None)
    if cal is not None:
        cal = cal.decode() if isinstance(cal, bytes) else str(cal)
        if cal.strip().lower() not in _OK_CALENDARS:
            _fail(f"{fpath}: time calendar {cal!r} is not handled (only "
                  f"{', '.join(_OK_CALENDARS)}); dates would be wrong, nothing converted")
    units = att.get("units", "")
    units = units.decode() if isinstance(units, bytes) else str(units)
    word, _, base = units.partition(" since ")
    sec = {"days": 86400.0, "hours": 3600.0, "minutes": 60.0,
           "seconds": 1.0}.get(word.strip().lower())
    m = _TIME_BASE_RE.match(base.strip())
    if sec is None or m is None:
        _fail(f"{fpath}: time units {units!r} not handled (need '<days|hours|minutes|"
              f"seconds> since Y-M-D[ H:M[:S]]' with no time-zone offset); nothing converted")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    ss = float(m.group(6) or 0)
    try:
        t0 = datetime(y, mo, d) + timedelta(hours=hh, minutes=mm, seconds=ss)
    except ValueError:
        _fail(f"{fpath}: time origin {base!r} is not a real date; nothing converted")
    return sec, t0


def _mswx_time_seconds(tvar, fpath):
    """The file's own time axis as datetime64[s]. Calendar and origin are
    checked by _check_time_meta first; the numbers are then turned into dates
    by netCDF4.num2date with the file's own calendar (calendar-aware: a
    'standard' axis with an origin before 1582-10-15 uses the Julian part
    correctly), never by plain arithmetic."""
    import netCDF4
    _check_time_meta(tvar, fpath)
    att = {k: tvar.getncattr(k) for k in tvar.ncattrs()}
    cal = att.get("calendar", "standard")
    cal = (cal.decode() if isinstance(cal, bytes) else str(cal)).strip().lower()
    units = att["units"]
    units = units.decode() if isinstance(units, bytes) else str(units)
    raw = np.ma.masked_invalid(np.ma.asarray(tvar[:], dtype=np.float64))
    if np.ma.count_masked(raw):
        _fail(f"{fpath}: {int(np.ma.count_masked(raw))} time values are missing; "
              f"dates cannot be read")
    try:
        # cftime objects carry the calendar's own year/month/day/time fields;
        # building the date from those fields keeps a mixed Julian/Gregorian
        # 'standard' origin (e.g. 1500-01-01) right for modern dates.
        dts = netCDF4.num2date(raw.filled(), units, calendar=cal,
                               only_use_cftime_datetimes=True)
        dts = np.atleast_1d(dts)
        py = [datetime(x.year, x.month, x.day, x.hour, x.minute, x.second,
                       x.microsecond) for x in dts]
    except (ValueError, TypeError, OverflowError) as e:
        _fail(f"{fpath}: time cannot be decoded as real dates ({e}); nothing converted")
    if any(x < datetime(1582, 10, 15) for x in py):
        _fail(f"{fpath}: time values before 1582-10-15 (Julian part of the "
              f"'{cal}' calendar) are not handled; nothing converted")
    us = np.asarray(py, dtype="datetime64[us]").astype("int64")
    s_round = np.round(us / 1e6)
    if us.size and np.abs(us / 1e6 - s_round).max() > 1.0:
        _fail(f"{fpath}: time values are not on whole seconds; dates cannot be read")
    return s_round.astype("int64").astype("datetime64[s]")


def _read_mswx_window(forcing_dir, lat, lon, start_dt, end_dt):
    """MSWX 3-hourly values at the nearest cell for start_date 00:00 ..
    end_date 21:00, read straight from the annual files.

    Why not ki_tools_common.load_hourly_forcing: that loader checks the WHOLE
    annual file (2920/2928 steps) before it applies period=, so the current,
    part-filled year (e.g. Tair_2026.nc stops in March) fails even for a
    January request. Here every variable's own time axis must carry each
    requested 3-hour step exactly once, with no gap, repeat or shift INSIDE
    the requested stretch; steps after it may be absent. The units attribute
    must be the one the conversion is written for, the -9999 _FillValue
    becomes NaN (and then stops in _require). Nearest cell as in
    ki_tools_common (xarray sel method='nearest' on the file's lat/lon).
    Returns the same keys as load_hourly_forcing (temp_c degC, precip_mm mm
    per 3 h, srad/lrad W/m2, wind m/s, shum kg/kg, pres Pa)."""
    # netCDF4 (a declared GLM/ki_tools_common dependency, the same library
    # the CMFD units check uses) is imported before xarray, so its HDF5 copy
    # is the one loaded (see ki_tools_common.load_forcing._open_nc). xarray is
    # only used for the in-memory nearest-cell lookup, never to open a file.
    import netCDF4
    import xarray as xr
    step = np.timedelta64(_MSWX_STEP_S, "s")
    w0 = np.datetime64(start_dt, "s")
    w1 = np.datetime64(end_dt + timedelta(days=1), "s")          # exclusive
    want = np.arange(w0, w1, step)
    out_key = {"temp": "temp_c", "prec": "precip_mm", "srad": "srad_wm2",
               "lrad": "lrad_wm2", "wind": "wind_ms", "shum": "shum_kgkg",
               "pres": "pres_pa"}
    vals = {k: [] for k in out_key}
    for year in range(start_dt.year, end_dt.year + 1):
        y0 = max(w0, np.datetime64(f"{year}-01-01T00:00:00"))
        y1 = min(w1, np.datetime64(f"{year + 1}-01-01T00:00:00"))
        ywant = np.arange(y0, y1, step)
        for key, (folder, var, unit_want) in _SUBDAILY_UNITS["mswx"].items():
            fpath = os.path.join(forcing_dir, folder, f"{_MSWX_PREFIX[folder]}_{year}.nc")
            if not os.path.isfile(fpath):
                _fail(f"mswx: {fpath} not found; nothing is filled in")
            try:
                with netCDF4.Dataset(fpath, "r") as ds:
                    # netCDF4's own CF masking stays ON: _FillValue, missing_value,
                    # valid_min/max/range AND the default netCDF fill value of an
                    # unwritten cell all become masked -> NaN below. Scaling is
                    # off (packed data is refused instead of unpacked).
                    ds.set_auto_mask(True)
                    ds.set_auto_scale(False)
                    f = ds.variables
                    if var not in f or "time" not in f or "lat" not in f or "lon" not in f:
                        _fail(f"{fpath}: needs variables time, lat, lon and '{var}'")
                    dv = f[var]
                    dva = _nc_attrs(dv)
                    got = dva.get("units", None)
                    got = got.decode() if isinstance(got, bytes) else got
                    if got != unit_want:
                        _fail(f"{fpath}: {var} units are {got!r}, the conversion is "
                              f"written for {unit_want!r}; unknown units, nothing converted")
                    for a in ("scale_factor", "add_offset"):
                        if a in dva:
                            _fail(f"{fpath}: {var} is packed ({a}); not handled, "
                                  f"nothing converted")
                        for cv in ("time", "lat", "lon"):
                            if a in f[cv].ncattrs():
                                _fail(f"{fpath}: coordinate '{cv}' is packed ({a}); "
                                      f"not handled, nothing converted")
                    # Values are read by position, so the dimension NAMES must be
                    # (time, lat, lon) and each coordinate 1-D on its own dim;
                    # any other order would pick another place silently.
                    if tuple(dv.dimensions) != ("time", "lat", "lon") or \
                            tuple(f["time"].dimensions) != ("time",) or \
                            tuple(f["lat"].dimensions) != ("lat",) or \
                            tuple(f["lon"].dimensions) != ("lon",):
                        _fail(f"{fpath}: {var} dimensions {tuple(dv.dimensions)} (time "
                              f"{tuple(f['time'].dimensions)}, lat {tuple(f['lat'].dimensions)}, "
                              f"lon {tuple(f['lon'].dimensions)}); only (time, lat, lon) is "
                              f"read here, nothing converted")
                    t = _mswx_time_seconds(f["time"], fpath)
                    if dv.ndim != 3 or dv.shape[0] != t.size:
                        _fail(f"{fpath}: {var} shape {dv.shape} does not match "
                              f"{t.size} time steps")
                    idx = np.flatnonzero((t >= y0) & (t < y1))
                    if idx.size != ywant.size or not np.array_equal(t[idx], ywant) \
                            or (idx.size and idx[-1] - idx[0] + 1 != idx.size):
                        have = set(t[idx].tolist())
                        lost = [str(x) for x in ywant if x.tolist() not in have]
                        _fail(f"mswx {fpath}: the requested {y0}..{y1 - step} needs "
                              f"{ywant.size} steps every 3 h; the file has {idx.size} "
                              f"there (file ends {t[-1] if t.size else '-'}; "
                              f"{len(lost)} missing, first: {', '.join(lost[:3]) or '-'}; "
                              f"or a repeated/shifted step). Nothing is cut or filled")
                    glat = np.ma.asarray(f["lat"][:]).astype(float).filled(np.nan)
                    glon = np.ma.asarray(f["lon"][:]).astype(float).filled(np.nan)
                    if not (np.isfinite(glat).all() and np.isfinite(glon).all()):
                        _fail(f"{fpath}: lat/lon coordinates have missing values; "
                              f"nothing converted")
                    r = int(xr.DataArray(np.arange(glat.size), coords={"lat": glat},
                                         dims="lat").sel(lat=lat, method="nearest").values)
                    c = int(xr.DataArray(np.arange(glon.size), coords={"lon": glon},
                                         dims="lon").sel(lon=lon, method="nearest").values)
                    a = np.ma.asarray(dv[int(idx[0]):int(idx[-1]) + 1, r, c]) \
                        .astype(float).filled(np.nan) if idx.size else np.zeros(0)
                    # Every CF way of marking a missing value becomes NaN here
                    # (then stops in _require), BEFORE rain is clipped at 0,
                    # so a sentinel can never turn into dry weather.
                    for att in ("_FillValue", "missing_value"):
                        mv = dva.get(att, None)
                        if mv is not None:
                            a[np.isin(a, np.asarray(mv, dtype=float).ravel())] = np.nan
                    lo = dva.get("valid_min", None)
                    hi = dva.get("valid_max", None)
                    if "valid_range" in dva:
                        lo, hi = np.asarray(dva["valid_range"], dtype=float).ravel()[:2]
                    if lo is not None:
                        a[a < float(np.asarray(lo).ravel()[0])] = np.nan
                    if hi is not None:
                        a[a > float(np.asarray(hi).ravel()[0])] = np.nan
            except OSError as e:
                _fail(f"{fpath}: cannot be read ({e})")
            vals[key].append(a)
    out = {out_key[k]: np.concatenate(v) for k, v in vals.items()}
    # Only FINITE small negatives become 0 (as in the shared loader); NaN and
    # +/-inf stay as they are and stop in _require, never becoming dry weather.
    pr = out["precip_mm"]
    out["precip_mm"] = np.where(np.isfinite(pr) & (pr < 0), 0.0, pr)
    out["dates"] = want
    out["timestep_seconds"] = _MSWX_STEP_S
    return out


def read_cmfd_mswx_at_point(forcing_dir, lat, lon, start_date, end_date,
                            snow_threshold=0.0):
    """Read CMFD or MSWX 3-hourly forcing at a point.

    CMFD (monthly files): through the SHARED loader
    ki_tools_common.load_forcing.load_hourly_forcing (as the other KIs do). It
    reads only the months of the period, takes the dates from each file's own
    time axis, and stops on a missing folder/file, an uneven time axis or any
    missing value in start_date 00:00 .. end_date 24:00. Its unit conversion
    (K -> degC, kg m-2 s-1 * 10800 s -> mm per step) is checked first against
    the files' own `units` attributes (_check_source_units).
    MSWX (annual files, the current year only part-filled): _read_mswx_window,
    which checks completeness only inside the requested stretch.
    Returned units: temp_c degC, precip_mm mm per step, shum kg/kg, pres Pa,
    radiation W/m2, wind m/s. Returns (df, step_seconds).
    """
    from ki_tools_common.load_forcing import load_hourly_forcing

    if not forcing_dir:
        _fail("--forcing_dir is required for CMFD/MSWX (the folder holding the "
              "variable folders)")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # Which store: same path rule the tool always used (MSWX lives in .../msxw)
    low = str(forcing_dir).lower()
    source = "mswx" if ("msxw" in low or "mswx" in low) else "cmfd"
    if source == "mswx":
        d = _read_mswx_window(forcing_dir, lat, lon, start_dt, end_dt)
    else:
        _check_source_units(source, forcing_dir, start_dt, end_dt)
        try:
            d = load_hourly_forcing(source, lat, lon, start_dt.year, end_dt.year,
                                    forcing_dir=forcing_dir,
                                    period=(start_dt.date(), end_dt.date()))
        except (ValueError, FileNotFoundError, OSError) as e:
            _fail(f"{source} could not give {start_date}..{end_date} at ({lat}, {lon}): "
                  f"{type(e).__name__}: {e}")

    times = pd.to_datetime(np.asarray(d["dates"]).astype("datetime64[s]"))
    keep = (times >= pd.Timestamp(start_dt)) & \
           (times < pd.Timestamp(end_dt) + pd.Timedelta(days=1))
    times = times[keep]
    ts = int(d["timestep_seconds"])
    n = len(times)

    def _require(key):
        a = np.asarray(d.get(key), dtype=float)[keep] if d.get(key) is not None else None
        if a is None or a.shape != (n,):
            _fail(f"{source}: '{key}' missing from the loaded series; nothing is filled in")
        if not np.isfinite(a).all():
            _fail(f"{source}: '{key}' has {int((~np.isfinite(a)).sum())} missing values "
                  f"in {start_date}..{end_date}; nothing is filled in")
        return a

    temp_c = _require("temp_c")                       # degC
    sw = np.maximum(_require("srad_wm2"), 0.0)
    lw = _require("lrad_wm2")
    precip_m_day = _require("precip_mm") * (86400.0 / ts) / 1000.0   # mm/step -> m/day
    wind = _require("wind_ms")
    shum = _require("shum_kgkg")
    sp_kpa = _require("pres_pa") / 1000.0                            # Pa -> kPa
    # Specific humidity to VP: VP = q * P / (0.622 + 0.378 * q)
    vp = shum * sp_kpa / (0.622 + 0.378 * shum)
    rh_raw = 100.0 * vp / (0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3)))
    n_super = int((rh_raw > 100.0).sum())
    if n_super:
        print(f"NOTE: {n_super} of {n} steps are above 100 % RH (max "
              f"{rh_raw.max():.1f} %) and are set to 100 % by vp_to_rh",
              file=sys.stderr)
    rh = vp_to_rh(vp, temp_c)

    rain, snow = partition_rain_snow(precip_m_day, temp_c, snow_threshold)

    df = pd.DataFrame({
        'time': times,
        'ShortWave': sw,
        'LongWave': lw,
        'AirTemp': temp_c,
        'RelHum': rh,
        'WindSpeed': wind,
        'Rain': rain,
        'Snow': snow,
    })
    print(f"{source} 3-hourly forcing "
          f"({'MSWX annual files' if source == 'mswx' else 'load_hourly_forcing'}): {n} steps at "
          f"{lat:.3f},{lon:.3f}; rain total {float(_require('precip_mm').sum()):.1f} mm",
          file=sys.stderr)
    return df, ts


def read_nasa_power_forcing(lat, lon, start_date, end_date, snow_threshold=0.0):
    """Read NASA POWER daily forcing via ki_tools_common.load_forcing and
    convert to GLM met format.

    NASA POWER is the SKILL-endorsed point forcing for lakes OUTSIDE the
    on-disk CMFD (China) / MSWX NetCDF coverage (e.g. North-American
    reservoirs). load_daily_forcing("nasa_power", ...) returns native daily
    arrays: srad_wm2, lrad_wm2, temp_mean_c, wind_ms (WS10M preferred over
    the often near-zero WS2M), shum_kgkg, pres_pa, precip_mm (mm/day).
    Returns (df, 86400): one record per day.
    """
    from ki_tools_common.load_forcing import load_daily_forcing

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    try:
        data = load_daily_forcing("nasa_power", lat, lon,
                                  start_dt.year, end_dt.year,
                                  period=(start_dt.date(), end_dt.date()))
    except (ValueError, OSError, RuntimeError) as e:
        _fail(f"nasa_power could not give {start_date}..{end_date} at ({lat}, {lon}): "
              f"{type(e).__name__}: {e}")

    dates = pd.to_datetime(data["dates"])
    n = len(dates)
    if data.get("lrad_wm2") is None:
        _fail("NASA POWER gave no longwave (lrad_wm2); GLM needs LongWave and "
              "nothing is filled in")
    # Every value used, inside the requested days, must be a real number
    # BEFORE any clip (SW at 0, RH to 0-100 would hide inf/NaN).
    insel = np.asarray((dates >= start_dt) & (dates <= end_dt))
    for key in ("temp_mean_c", "srad_wm2", "lrad_wm2", "wind_ms", "precip_mm",
                "shum_kgkg", "pres_pa"):
        if data.get(key) is None:
            _fail(f"NASA POWER gave no '{key}'; nothing is filled in")
        a = np.asarray(data[key], dtype=float)
        if a.shape != (n,):
            _fail(f"NASA POWER '{key}' has shape {a.shape}, dates {n}")
        if not np.isfinite(a[insel]).all():
            _fail(f"NASA POWER '{key}' has {int((~np.isfinite(a[insel])).sum())} "
                  f"non-finite values in {start_date}..{end_date}; nothing is filled in")
    temp_c = np.asarray(data["temp_mean_c"], dtype=float)
    sw = np.maximum(np.asarray(data["srad_wm2"], dtype=float), 0.0)
    lw = np.asarray(data["lrad_wm2"], dtype=float)
    wind = np.asarray(data["wind_ms"], dtype=float)
    precip_mm_day = np.asarray(data["precip_mm"], dtype=float)  # NASA: mm/day
    precip_m_day = precip_mm_day / 1000.0                       # mm/day -> m/day

    # specific humidity (kg/kg) + surface pressure (Pa) -> vapour pressure (kPa)
    shum = np.asarray(data["shum_kgkg"], dtype=float)
    sp_kpa = np.asarray(data["pres_pa"], dtype=float) / 1000.0
    vp_kpa = shum * sp_kpa / (0.622 + 0.378 * shum)
    rh = vp_to_rh(vp_kpa, temp_c)

    rain, snow = partition_rain_snow(precip_m_day, temp_c, snow_threshold)

    df = pd.DataFrame({
        'time': dates,
        'ShortWave': sw,
        'LongWave': lw,
        'AirTemp': temp_c,
        'RelHum': rh,
        'WindSpeed': wind,
        'Rain': rain,
        'Snow': snow,
    })
    mask = (df['time'] >= start_dt) & (df['time'] <= end_dt)
    df = df[mask].reset_index(drop=True)
    print(f"NASA POWER daily forcing: {len(df)} days at "
          f"{lat:.3f},{lon:.3f}", file=sys.stderr)
    return df, 86400


def process(args):
    """Read forcing data and convert to GLM format."""
    thr = args.snow_threshold
    if getattr(args, "forcing_source", None) == "nasa_power":
        df, step_s = read_nasa_power_forcing(args.lat, args.lon,
                                             args.start_date, args.end_date, thr)
    elif args.vic_forcing_dir:
        df, step_s = read_vic_forcing(args.vic_forcing_dir, args.lat, args.lon,
                                      args.start_date, args.end_date, thr)
    else:
        df, step_s = read_cmfd_mswx_at_point(args.forcing_dir, args.lat, args.lon,
                                             args.start_date, args.end_date, thr)

    # The time axis must be the complete grid from start_date 00:00 to the
    # last step of end_date at the SOURCE's known step (NASA POWER daily
    # 86400 s, CMFD/MSWX 10800 s, VIC from its row count): no missing stamp
    # (not a NaN, so the value checks cannot see it), no duplicate, in order.
    # A single record is fine when it is the whole grid (one NASA POWER day).
    tidx = pd.DatetimeIndex(pd.to_datetime(df['time']))
    if len(tidx) == 0:
        _fail(f"no forcing step in {args.start_date}..{args.end_date}")
    if step_s <= 0 or 86400 % step_s:
        _fail(f"forcing step {step_s} s does not divide a day")
    step = pd.Timedelta(seconds=int(step_s))
    g0 = pd.Timestamp(args.start_date)
    g1 = pd.Timestamp(args.end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    want = pd.date_range(g0, g1, freq=step)
    if len(tidx) != len(want) or not (tidx == want).all():
        lost = want.difference(tidx)
        _fail(f"forcing time axis not complete at step {step} in "
              f"{args.start_date}..{args.end_date}: {len(lost)} of {len(want)} steps "
              f"missing (first: {', '.join(str(x) for x in lost[:5])}), "
              f"{len(tidx.difference(want))} off the grid; nothing is filled in")

    # Apply wind height correction if needed
    if args.wind_height != 10.0:
        # Log-law correction: U_10 = U_z * ln(10/z0) / ln(z/z0)
        z0 = 0.001  # roughness for water surface
        correction = np.log(10.0 / z0) / np.log(args.wind_height / z0)
        df['WindSpeed'] = df['WindSpeed'] * correction
        print(f"Wind height correction: {args.wind_height}m -> 10m, "
              f"factor={correction:.3f}", file=sys.stderr)

    # Format time column
    df['time'] = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')

    return df


def validate_outputs(df, args):
    """Validate the output meteorological data."""
    warnings = []

    # A missing value in the met file is a failure, not a warning: stop, write
    # nothing, never report success.
    nan_counts = df.isna().sum()
    bad = {c: int(nan_counts[c]) for c in nan_counts.index if nan_counts[c] > 0}
    if bad:
        _fail(f"missing values in the GLM met columns {bad}; nothing is filled in "
              f"and no file is written")
    # +/-inf is not a value either (e.g. 'inf' in a VIC ASCII file).
    num = [c for c in df.columns if c != 'time']
    inf = {c: int((~np.isfinite(df[c].to_numpy(dtype=float))).sum()) for c in num}
    inf = {c: k for c, k in inf.items() if k}
    if inf:
        _fail(f"non-finite (inf) values in the GLM met columns {inf}; nothing written")

    # Check ranges
    sw_max = df['ShortWave'].max()
    if sw_max > 1361:
        warnings.append(
            f"ShortWave max={sw_max:.1f} exceeds solar constant (1361 W/m2)")
    if df['ShortWave'].min() < 0:
        warnings.append(f"ShortWave has negative values (min={df['ShortWave'].min():.1f})")

    # Hard unit checks: a failure here stops the tool (no 'CRITICAL warning
    # then success').
    rh_max = df['RelHum'].max()
    rh_min = df['RelHum'].min()
    # RelHum is computed in this tool as 100 * VP / VPsat, so it is percent by
    # construction; a very dry period (e.g. 0.5 % at 40 degC) is real and is
    # only warned about. Temperature in K is caught by the AirTemp check below.
    if rh_max <= 1.0:
        warnings.append(f"RelHum max={rh_max:.3f} % over the whole period — very dry, "
                        f"check the humidity source")
    # 0 % comes only from VP <= 0 (clipped by vp_to_rh): not physical, stop.
    if rh_min <= 0 or rh_max > 100.0:
        _fail(f"RelHum range {rh_min:.2f}..{rh_max:.2f} % is not physical (0-100]; "
              f"vapour pressure <= 0 in the source; nothing written")
    t_min, t_max = df['AirTemp'].min(), df['AirTemp'].max()
    if t_min < -90.0 or t_max > 60.0:
        _fail(f"AirTemp range {t_min:.1f}..{t_max:.1f} is not degC (Kelvin?); "
              f"nothing written")

    # Rain is a RATE in m/day, so one intense short step is large (150 mm in
    # 3 h = 1.2 m/day). A size limit cannot prove a unit error; the units are
    # checked at the source instead (CMFD/MSWX units attributes, NASA POWER
    # in the shared loader, VIC mm per step by format). Only warn here.
    rain_max = (df['Rain'] + df['Snow']).max()
    if rain_max > 0.5:
        warnings.append(
            f"Rain+Snow max={rain_max:.4f} m/day ({rain_max*1000:.1f} mm/day as a "
            f"rate) — very high, check the source")
    if (df['Rain'] < 0).any() or (df['Snow'] < 0).any():
        _fail("negative Rain/Snow in the GLM met columns; nothing written")

    temp_range = df['AirTemp'].max() - df['AirTemp'].min()
    if temp_range < 5:
        warnings.append(f"Temperature range only {temp_range:.1f} degC — check data")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to GLM meteorological CSV format")
    parser.add_argument("--forcing_dir", type=str,
                        help="CMFD or MSWX forcing directory")
    parser.add_argument("--forcing_source", type=str, default=None,
                        choices=["nasa_power"],
                        help="Point forcing source loaded via "
                             "ki_tools_common.load_forcing (nasa_power). "
                             "Use for lakes outside on-disk CMFD/MSWX coverage.")
    parser.add_argument("--vic_forcing_dir", type=str,
                        help="VIC ASCII forcing files directory")
    parser.add_argument("--lat", type=float, required=True,
                        help="Lake latitude")
    parser.add_argument("--lon", type=float, required=True,
                        help="Lake longitude")
    parser.add_argument("--start_date", type=str, required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--wind_height", type=float, default=10.0,
                        help="Measurement height for wind speed (m, default: 10)")
    parser.add_argument("--snow_threshold", type=float, default=0.0,
                        help="Temperature threshold for rain/snow partition (degC)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    args = parser.parse_args()

    validate_inputs(args)
    df = process(args)
    warnings = validate_outputs(df, args)

    # Write output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    df.to_csv(args.output, index=False, float_format='%.4f')

    n_records = len(df)
    date_range = f"{df['time'].iloc[0]} to {df['time'].iloc[-1]}"

    result = {
        "status": "success",
        "output_file": args.output,
        "num_records": n_records,
        "date_range": date_range,
        "columns": list(df.columns),
        "warnings": warnings,
        "unit_summary": {
            "ShortWave": "W/m2",
            "LongWave": "W/m2",
            "AirTemp": "degC",
            "RelHum": "% (0-100)",
            "WindSpeed": "m/s (10m height)",
            "Rain": "m/day",
            "Snow": "m/day",
        }
    }

    print(json.dumps(result, indent=2), file=sys.stderr)
    print(f"GLM meteorological forcing written to {args.output} "
          f"({n_records} records)", file=sys.stderr)


if __name__ == "__main__":
    main()
