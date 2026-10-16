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

    # nasa_power is an online point API with no local input file/dir.
    # mswx may pass a forcing-root dir but defaults are resolved by load_forcing.
    if args.source not in ("nasa_power", "mswx"):
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
    """Convert datetime to Julian Day from year 0 (GEOtop convention).

    JDfrom0 = integer day count since GEOtop's day-0 epoch PLUS the
    fractional day (hour/24). The fractional part MUST equal the time of day
    so that GEOtop's solar-position routine (radiation.cc: solar hour
    h = (JD-floor(JD))*24 + dh) lands the sun at the correct local clock time.

    Calibration anchor (shipped reference test tests/1D/Matsch_B2_Ref_007):
        02/10/2009 00:00  ->  734047.0000   (midnight => .0000, not .25)
        02/10/2009 01:00  ->  734047.0417
    datetime(2009,10,2) - datetime(1,1,1) = 733681 days, so the integer
    offset is 734047 - 733681 = 366 (an INTEGER).

    BUGFIX (2026-06-23, GEOtop MODIS-LST real case): the previous constant
    `+ 365.25 + 1` (= 366.25) injected a spurious +0.25 day = +6 h into the
    FRACTIONAL part of every timestamp. Midnight became .25 (=06:00), so
    GEOtop placed the sun ~6 h late and applied the shortwave pulse hours
    after the real solar noon. Surface/skin temperature (Tsurface) came out
    far too cold at the true daytime overpass time (~10 K low vs MODIS LST),
    while air temperature -- which GEOtop reads directly and does not phase
    against sun position -- looked fine. A classic silent error. Use the
    correct integer offset so frac(JDfrom0)*24 == hour-of-day exactly.
    """
    delta = dt - datetime(1, 1, 1)
    return delta.days + delta.seconds / 86400.0 + 366


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
    if np.nanmax(rh, initial=0.0) > 110.0 or np.nanmin(rh, initial=0.0) < 0.0:
        raise ValueError(
            f"specific humidity gives RH from {np.nanmin(rh):.1f}% to {np.nanmax(rh):.1f}%: "
            f"q must be kg/kg (not g/kg) and pressure mbar/Pa as declared")
    return np.clip(rh, 0, 100)   # only small supersaturation is clipped


def convert_precip(precip, from_unit, dt_seconds):
    """Convert precipitation to mm per time step.

    CRITICAL: GEOtop Iprec = total mm accumulated over the time step.

    Args:
        precip: Precipitation values
        from_unit: One of 'mm_hr', 'mm_day', 'mm_step', 'm_s', 'kg_m2_s'
            ('mm_step' = mm accumulated over each INPUT record)
        dt_seconds: the interval each value covers -- the INPUT record
            spacing (rates are turned into depths per input record BEFORE
            any resampling; resample_meteo then moves depth between steps)
    """
    if from_unit == "mm_step":
        return precip
    elif from_unit == "mm_hr":
        return precip * (dt_seconds / 3600.0)
    elif from_unit == "mm_day":
        return precip * (dt_seconds / 86400.0)
    elif from_unit == "m_s":
        # m/s -> mm/step: multiply by 1000 (m->mm) * dt (s)
        return precip * 1000.0 * dt_seconds
    elif from_unit == "kg_m2_s":
        # kg m-2 s-1 = mm/s of water -> mm/step: multiply by dt (s) only
        return precip * dt_seconds
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


"""CMFD note (2026-07-21, GEOtop NCP MODIS-LST real case)
------------------------------------------------------
There used to be a bespoke ``read_cmfd()`` here that did
``xr.open_mfdataset(input/*.nc)`` and then ``ds.sel(latitude=, longitude=)``,
assuming (a) every CMFD variable lives as a *.nc in ONE flat directory,
(b) the coordinates are named latitude/longitude and (c) prec is in mm/hr.

None of that matches CMFD V2.0 as shipped on this server
(KISSPATH_FORCING/Data_forcing_03hr_010deg/): the store is
per-variable SUBDIRECTORIES (Temp/ Prec/ SRad/ LRad/ Wind/ SHum/ Pres/) with
one file per MONTH, coordinates are lat/lon, and prec is kg/m2/s. The reader
raised/garbled on the real store, so `--source cmfd` was effectively dead.

Per the KDT 5.0 rule, the fix is NOT to re-implement a CMFD reader here but
to route through the canonical loader, ki_tools_common.load_forcing, which
already knows the on-disk layout and the unit conversions (K->C,
kg/m2/s->mm per 3-h step). `cmfd` now goes through read_via_load_forcing()
exactly like nasa_power / mswx.
"""


def read_generic_csv(input_path, col_map, temp_unit, rh_unit, precip_unit,
                     date_format=None, pres_unit="Pa", start=None, end=None):
    """Read a generic CSV file with user-specified column mapping and units.

    Input contract (all checked, nothing guessed):
      * time column ``datetime`` (or the col-map name): ISO 8601
        (YYYY-MM-DD hh:mm) unless --date-format is given (e.g. GEOtop's own
        "%d/%m/%Y %H:%M"). A day-first date is never read month-first.
      * the records that bracket --start..--end: no duplicates, evenly spaced
        (see _window_slice); the file is sorted by time first.
      * every column the col-map names must exist in the file.
      * -9999 / -9998 in a data column = missing (NaN), never converted.
      * precipitation rates (mm_hr, mm_day, m_s, kg_m2_s) become depths over
        the INPUT record spacing here; 'mm_step' means mm per input record.
      * rh_unit 'specific' (kg/kg) is turned into RH % from the same row's air
        temperature and pressure; both columns must be mapped (no standard
        pressure is put in their place). Pressure is also written as AirPress.
    """
    mapping = json.loads(col_map) if isinstance(col_map, str) else dict(col_map)
    tcol = mapping.get("datetime", "datetime")

    df = pd.read_csv(input_path)
    named = {k: v for k, v in mapping.items()}
    missing = [f"{k}->{v}" for k, v in named.items() if v not in df.columns]
    if tcol not in df.columns and f"datetime->{tcol}" not in missing:
        missing.append(f"datetime->{tcol}")
    if missing:
        raise ValueError(f"{input_path}: col-map names columns that are not in the file: "
                         f"{missing} (file has {list(df.columns)})")
    try:
        if date_format:
            stamps = pd.to_datetime(df[tcol], format=date_format)
        else:
            stamps = pd.to_datetime(df[tcol], format="ISO8601")
    except (ValueError, TypeError) as e:
        raise ValueError(f"{input_path}: cannot read time column '{tcol}' "
                         f"{'with --date-format ' + date_format if date_format else 'as ISO 8601'}"
                         f" ({e}). Pass --date-format, e.g. '%d/%m/%Y %H:%M'.") from e
    df = df.set_index(pd.DatetimeIndex(stamps)).sort_index()
    # GEOtop's missing-value code -9999 (and -9998 "absent") in any data column
    # means missing: make it NaN BEFORE any unit conversion or check, so it is
    # never turned into a number (e.g. -99.99 mbar) and is written back as -9999.
    # only the columns this reader can use (default or col-map names); other
    # columns (e.g. a station name) are left alone
    known = {"temp": "AirT", "pres": "AirPress", "rh": "RelHum", "precip": "Iprec",
             "wind": "WindSp", "srad": "Swglobal", "wdir": "WindDir", "lwin": "LWin"}
    data_cols = sorted({mapping.get(k, v) for k, v in known.items()} & set(df.columns) - {tcol})
    df[data_cols] = df[data_cols].apply(pd.to_numeric, errors="raise").astype(float)
    df[data_cols] = df[data_cols].mask(df[data_cols].isin([NODATA, -9998]))
    # input record spacing, checked only over the records that bracket the
    # requested window (a gap elsewhere in the file does not matter)
    t = df.index.as_unit("s").asi8
    g0 = int(t[0]) if start is None else _secs(start)
    g1 = int(t[-1]) if end is None else _secs(end)
    ia, ib, native = _window_slice(df.index, g0, g1, input_path)

    result = pd.DataFrame(index=df.index)

    # Temperature
    temp_col = mapping.get("temp", "AirT")
    if temp_col in df.columns:
        result["AirT"] = df[temp_col].astype(float)
        if temp_unit == "K":
            result["AirT"] = kelvin_to_celsius(result["AirT"])

    # Air pressure (optional; needed for specific humidity)
    pres_col = mapping.get("pres", "AirPress")
    if pres_col in df.columns:
        pr = df[pres_col].astype(float)
        result["AirPress"] = pr / 100.0 if pres_unit == "Pa" else pr   # -> mbar
        bad = result["AirPress"].dropna()
        bad = bad[(bad < 300) | (bad > 1100)]
        if len(bad):
            raise ValueError(f"air pressure {bad.iloc[0]:.1f} mbar at {bad.index[0]} is not "
                             f"physical: check --pres-unit ({pres_unit})")

    # Relative humidity
    rh_col = mapping.get("rh", "RelHum")
    if rh_col in df.columns:
        rh = df[rh_col].astype(float)
        if rh_unit == "fraction":
            rh = fraction_to_percent(rh)
        elif rh_unit == "specific":
            if "AirT" not in result or "AirPress" not in result:
                raise ValueError(
                    "--rh-unit specific needs air temperature and pressure columns in the "
                    "col-map ('temp' and 'pres'); a standard pressure is not assumed")
            rh = pd.Series(specific_to_relative_humidity(
                rh.to_numpy(), result["AirT"].to_numpy(), result["AirPress"].to_numpy()),
                index=df.index)
        result["RelHum"] = rh
    elif rh_unit == "specific":
        raise ValueError("--rh-unit specific given but no humidity column "
                         f"('{rh_col}') in the file")

    # Precipitation: rate -> depth over the INPUT record spacing (not --dt)
    precip_col = mapping.get("precip", "Iprec")
    if precip_col in df.columns:
        result["Iprec"] = convert_precip(df[precip_col].astype(float), precip_unit, native)

    # Wind speed
    wind_col = mapping.get("wind", "WindSp")
    if wind_col in df.columns:
        result["WindSp"] = df[wind_col].astype(float)

    # Shortwave radiation
    srad_col = mapping.get("srad", "Swglobal")
    if srad_col in df.columns:
        result["Swglobal"] = df[srad_col].astype(float)

    # Wind direction (optional)
    wdir_col = mapping.get("wdir", "WindDir")
    if wdir_col in df.columns:
        result["WindDir"] = df[wdir_col].astype(float)

    # Longwave radiation (optional)
    lw_col = mapping.get("lwin", "LWin")
    if lw_col in df.columns:
        result["LWin"] = df[lw_col].astype(float)

    return result


def read_via_load_forcing(source, lat, lon, start, end, forcing_dir=None, dt=3600,
                          pad_days=(0, 0)):
    """Read forcing through ki_tools_common.load_forcing (nasa_power / mswx / cmfd).

    This is the canonical HydroCraft forcing loader. It returns point series
    already in SI-ish units, which we map onto the GEOtop meteo columns:

        precip_mm  (mm per timestep)  -> Iprec      (mm per step) [direct]
        temp_c     (Celsius)          -> AirT       (Celsius)
        srad_wm2   (W/m2)             -> Swglobal   (W/m2)
        wind_ms    (m/s)             -> WindSp      (m/s)
        shum_kgkg + pres_pa + temp   -> RelHum      (PERCENT, via humidity util)
        lrad_wm2   (W/m2)             -> LWin       (W/m2, optional)
        pres_pa    (Pa)              -> AirPress    (mbar, optional)

    WindDir is not provided by the point loader -> NODATA.
    Returns a DatetimeIndex-ed DataFrame of the loaded days (start..end days
    plus `pad_days` either side), NOT clipped: the caller first puts it on the
    --dt grid (needs native records that bracket start/end) and clips after.

    PERF FIX (2026-06-21, GEOtop real-case 05FA012): when the requested model
    step is daily (dt >= 86400) we call load_DAILY_forcing instead of
    load_hourly_forcing. The hourly loader for MSWX/NASA-POWER scans many
    sub-daily files and is ~minutes *per year* (times out on a 10-yr run);
    the daily loader returns the same point series in ~3 s/yr. GEOtop happily
    interpolates daily meteo entries to its internal TimeStepEnergyAndWater,
    exactly as the shipped Bengbu reference run does. The daily NASA-POWER
    schema names mean temperature `temp_mean_c` (not `temp_c`), so we coalesce.
    """
    from ki_tools_common.humidity import specific_humidity_to_rh

    daily = dt >= 86400
    first_day = (start - timedelta(days=pad_days[0])).date()
    last_day = (end + timedelta(days=pad_days[1])).date()
    if daily:
        from ki_tools_common.load_forcing import load_daily_forcing
        # period=: only the requested days must be complete (a part year runs;
        # a real gap inside the window still stops)
        out = load_daily_forcing(source, lat, lon, first_day.year, last_day.year,
                                 forcing_dir=forcing_dir, period=(first_day, last_day))
    else:
        from ki_tools_common.load_forcing import load_hourly_forcing
        # period= is whole days in the loader: every step of the start and end
        # DAYS must be complete, even when the run ends at 00:00 of the end day.
        # This is stricter than the steps written below (never looser, nothing
        # filled); a source missing the rest of the end day stops the run.
        out = load_hourly_forcing(source, lat, lon, first_day.year, last_day.year,
                                  forcing_dir=forcing_dir, period=(first_day, last_day))

    dates = pd.to_datetime(out["dates"])
    # Mean air temperature: hourly schema uses `temp_c`, daily uses `temp_mean_c`.
    if "temp_c" in out:
        temp_c = np.asarray(out["temp_c"], dtype=float)
    else:
        temp_c = np.asarray(out["temp_mean_c"], dtype=float)
    pres_pa = np.asarray(out.get("pres_pa", np.full(len(dates), 101325.0)), dtype=float)
    shum = np.asarray(out.get("shum_kgkg", np.full(len(dates), np.nan)), dtype=float)

    # Relative humidity in PERCENT (dt_005). Clip to physical 1-100 range.
    rh = specific_humidity_to_rh(shum, temp_c + 273.15, pres_pa)
    rh = np.clip(np.asarray(rh, dtype=float), 1.0, 100.0)

    # PRECIP DEPTH (corrected 2026-07-21, GEOtop NCP MODIS-LST real case):
    # load_forcing returns precip_mm as the DEPTH accumulated over its own
    # native step (mm/day for the daily loader, mm/3h for CMFD/MSWX sub-daily),
    # which is exactly GEOtop's Iprec semantics -- meteodata.cc::fill_Pint
    # divides Iprec by the record spacing to get the intensity. So it is passed
    # through VERBATIM here; any change of record spacing is handled once, and
    # depth-conservingly, by resample_meteo(). The former unconditional
    # `if daily: iprec /= 24` (which assumed Iprec was an mm/h intensity) is
    # removed: it was compensating for the old interpolating resample, and left
    # in place it would now under-count daily-forced precipitation 24x.
    iprec = np.asarray(out["precip_mm"], dtype=float)
    df = pd.DataFrame({
        "Iprec": iprec,                                          # mm accumulated per record
        "WindSp": np.asarray(out.get("wind_ms", np.zeros(len(dates))), dtype=float),
        "WindDir": np.full(len(dates), NODATA, dtype=float),
        "RelHum": rh,
        "AirT": temp_c,
        "Swglobal": np.asarray(out["srad_wm2"], dtype=float),
        "LWin": np.asarray(out.get("lrad_wm2", np.full(len(dates), np.nan)), dtype=float),
        "AirPress": pres_pa / 100.0,                            # Pa -> mbar
    }, index=dates)
    # Drop optional columns that are entirely missing
    for c in ("LWin", "AirPress"):
        if df[c].isna().all():
            df = df.drop(columns=[c])
    return df


def resample_meteo(df, dt_seconds):
    """Resample a meteo DataFrame to `dt_seconds`, conserving precipitation DEPTH.

    Iprec is NOT a rate: GEOtop reads it as the water depth ACCUMULATED since
    the previous meteo record and derives the intensity itself by dividing by
    the record spacing --

        meteodata.cc :: fill_Pint()
            data[i][PrecInt] = data[i][Prec] / (JD[i] - JD[i-1]);  // mm/d
            data[i][PrecInt] /= 24.;                               // mm/h

    so a record at time t owns the interval (t-dt, t].

    BUGFIX (2026-07-21, GEOtop NCP MODIS-LST real case): the old line

        df = df.resample(f"{dt}s").interpolate(method="linear")

    interpolated EVERY column, Iprec included. Upsampling 3-hourly CMFD
    (mm per 3 h) to an hourly meteo file therefore wrote the full 3-hour depth
    into each of the 3 hourly records -- 3x the true precipitation, silently.
    The same defect inflated daily->hourly by 24x; a prior run papered over
    that specific case with an unconditional `iprec /= 24` in the daily branch
    of read_via_load_forcing() (see its PRECIP-INTENSITY note, whose stated
    rationale -- "GEOtop reads Iprec as an intensity in mm/h" -- is refuted by
    fill_Pint above). That /24 is now redundant *and wrong* once the resample
    conserves depth, so it has been removed: depth handling lives HERE, in one
    place, driven by the actual native-vs-target step.

    Rules:
      * state/flux columns (AirT, RelHum, WindSp, Swglobal, LWin, ...):
        upsample -> linear interpolation; downsample -> interval mean.
      * Iprec (accumulated depth): upsample -> split the depth evenly across
        the sub-intervals it covers; downsample -> sum over the interval.

    CONSERVED INVARIANT -- verify with this, not with the raw column sum:

        sum(Iprec[1:])  before  ==  sum(Iprec[1:])  after

    The FIRST record is excluded on purpose. Its interval reaches back before
    the file starts, so fill_Pint sets data[0][PrecInt] = novalue and GEOtop
    never integrates it. Upsampling likewise has nowhere to put that leading
    depth. Checked at 3h->1h, 3h->6h, 3h->3h and 1d->1h: the depth GEOtop
    actually applies is preserved exactly. A naive total-column-sum check will
    look "lossy" by exactly the first record and must not be re-"fixed".

    2026-10-16: now a thin wrapper over to_grid() over the whole input (gaps,
    uneven spacing and partial intervals stop instead of being filled).
    process() calls to_grid() on the requested --start/--end window directly,
    AFTER loading native records that bracket it, so no edge is lost.
    """
    return to_grid(df, None, None, dt_seconds)


class CoverageError(ValueError):
    """The input does not cover the requested window at --dt.

    need_before / need_after say which edge lacks native records, so a caller
    that can read more (load_forcing) may load one more day there and retry.
    """
    def __init__(self, msg, need_before=False, need_after=False):
        super().__init__(msg)
        self.need_before = need_before
        self.need_after = need_after


def _secs(ts):
    return int(pd.Timestamp(ts).value // 10**9)


def _window_slice(index, g0, g1, what, dt=None):
    """Rows [ia, ib] of a SORTED time index that bracket the window g0..g1
    (epoch seconds): the last record at or before g0 and the first at or after
    g1. Returns (ia, ib, native_step_seconds).

    The native step is the most common spacing over the WHOLE input (so a
    short window cannot hide a missing record: 00,01,03,04 h is hourly with a
    gap, not 2-hourly). Every record whose stamp lies in the checked stretch
    must be unique and exactly one native step after the one before. The
    checked stretch is [stamp of row ia, stamp of row ib], widened back to the
    last record at or before g0 - (dt - native) when dt (the output step) is
    coarser, so the first output interval is checked too. Every copy of a duplicated stamp at either
    boundary is inside the stretch, so a duplicate stops the run. A gap or a
    duplicate outside the stretch does not matter. Raises CoverageError when
    the input does not reach g0 or g1.
    """
    t = pd.DatetimeIndex(index).as_unit("s").asi8
    if len(t) < 2:
        raise ValueError(f"{what}: needs at least 2 records, got {len(t)}")
    if pd.DatetimeIndex(index).hasnans:
        raise ValueError(f"{what}: time column has unreadable stamps")
    lo_short, hi_short = g0 < t[0], g1 > t[-1]
    if lo_short or hi_short:
        raise CoverageError(
            f"{what}: input {pd.Timestamp(int(t[0]), unit='s')} .. "
            f"{pd.Timestamp(int(t[-1]), unit='s')} does not reach the requested "
            f"{pd.Timestamp(g0, unit='s')} .. {pd.Timestamp(g1, unit='s')}",
            need_before=lo_short, need_after=hi_short)
    d_all = np.diff(t)
    pos = d_all[d_all > 0]
    if pos.size == 0:
        raise ValueError(f"{what}: all records have the same time stamp")
    vals, cnt = np.unique(pos, return_counts=True)
    native = int(vals[np.argmax(cnt)])
    ia = int(np.searchsorted(t, g0, side="right")) - 1
    ib = int(np.searchsorted(t, g1, side="left"))
    lo_c = int(t[ia])
    if dt is not None and dt > native:
        # the first output interval (g0-dt, g0] is checked too, starting at the
        # last record at or before its first native stamp (so a record missing
        # inside it is a gap, not the input start)
        j = int(np.searchsorted(t, g0 - (int(dt) - native), side="right")) - 1
        lo_c = min(lo_c, int(t[max(j, 0)]))
    hi_c = int(t[ib])
    sel = t[(t >= lo_c) & (t <= hi_c)]
    if sel.size < 2:
        raise ValueError(f"{what}: the window {pd.Timestamp(g0, unit='s')} .. "
                         f"{pd.Timestamp(g1, unit='s')} needs at least 2 input records")
    d = np.diff(sel)
    if np.any(d == 0):
        dup = sel[1:][d == 0][:3]
        raise ValueError(f"{what}: duplicate time stamps "
                         f"{[str(pd.Timestamp(int(x), unit='s')) for x in dup]}; "
                         f"which record is right is not guessed")
    if np.any(d != native):
        bad = np.flatnonzero(d != native)[:3]
        raise ValueError(
            f"{what}: records are not evenly spaced around the window (input step "
            f"{native} s, but {[int(d[i]) for i in bad]} s after "
            f"{[str(pd.Timestamp(int(sel[i]), unit='s')) for i in bad]}). "
            f"Missing records are not filled in.")
    return ia, ib, native


def to_grid(df, start, end, dt_seconds):
    """Put a meteo DataFrame on the grid start, start+dt, ..., end.

    start/end None = from the first to the last native record. Only the
    records that bracket the window must be unique and evenly spaced (no gap
    there, see _window_slice); every output stamp must be covered, else
    CoverageError (nothing is extrapolated or filled). Rules (record at t
    owns (t-step, t], GEOtop meteodata.cc::fill_Pint):
      * dt < native (upsample; native must be a multiple of dt and the grid
        must land on native stamps): state columns are linear between the two
        native records around each stamp; Iprec = depth of the native record
        that owns the stamp (first native stamp >= t) * dt/native.
      * dt >= native (same step or downsample; dt a multiple of native, grid
        stamps on native stamps): each stamp t takes the dt/native native
        records in (t-dt, t]: mean for state columns, sum for Iprec. All of
        them must exist and be evenly spaced.
        FIRST stamp only: if the input has no full interval before it (the
        input starts at the window start), the first row keeps the native
        record AT that stamp for state columns and Iprec = NaN (-9999).
        GEOtop never uses the first record's Iprec (fill_Pint sets
        PrecInt[0] = novalue; -9999 is number_novalue, not number_absent),
        so no applied rain is lost and none is made up: sum(Iprec[1:]) is kept.
    A NaN in an input record stays NaN in every output value it feeds
    (written as -9999), never averaged around.
    """
    df = df.sort_index()
    t_all = pd.DatetimeIndex(df.index).as_unit("s").asi8
    if len(t_all) < 2:
        raise ValueError(f"forcing has {len(t_all)} record(s); at least 2 are needed")
    dt = int(dt_seconds)
    g0 = int(t_all[0]) if start is None else _secs(start)
    g1 = int(t_all[-1]) if end is None else _secs(end)
    if g1 < g0:
        raise ValueError(f"end {end} is before start {start}")
    ia, ib, native = _window_slice(df.index, g0, g1, "forcing", dt=dt)
    if (g1 - g0) % dt:
        # with end=None (resample_meteo) a trailing part interval is NOT
        # dropped silently: the input must end on the output grid
        raise ValueError(f"end must be start plus a whole number of dt steps "
                         f"({pd.Timestamp(g0, unit='s')} .. {pd.Timestamp(g1, unit='s')}, "
                         f"dt={dt} s): an incomplete last interval is not dropped")
    grid = np.arange(g0, g1 + 1, dt, dtype=np.int64)
    if dt < native:
        if native % dt:
            raise ValueError(f"--dt {dt} s does not divide the input step {native} s")
        align = dt
    else:
        if dt % native:
            raise ValueError(f"--dt {dt} s is not a multiple of the input step {native} s")
        align = native
    if (g0 - int(t_all[ia])) % align:
        raise ValueError(f"start {pd.Timestamp(g0, unit='s')} does not fall on the input "
                         f"records' {align} s grid (record {df.index[ia]})")

    cols = list(df.columns)
    first_partial = False
    if dt > native:
        n = dt // native
        # use a full first interval if the input has it, evenly spaced, before g0
        ia2 = ia - (n - 1)
        if ia2 >= 0:
            pre = t_all[ia2:ia + 1]
            if np.all(np.diff(pre) == native) and pre[0] == g0 - (n - 1) * native:
                ia = ia2
            else:
                first_partial = True
        else:
            first_partial = True
    sub = df.iloc[ia:ib + 1]
    t = t_all[ia:ib + 1]
    vals = {c: sub[c].to_numpy(dtype=float) for c in cols}
    out = {c: np.full(grid.size, np.nan) for c in cols}
    if dt < native:
        k = np.searchsorted(t, grid, side="left")          # first native >= stamp
        exact = t[k] == grid
        km = np.where(exact, k, k - 1)
        w = np.where(exact, 0.0, (grid - t[km]) / float(native))
        for c in cols:
            v = vals[c]
            if c == "Iprec":
                out[c] = v[k] * (dt / float(native))
            else:
                out[c] = np.where(exact, v[k], v[km] * (1.0 - w) + v[k] * w)
    else:
        n = dt // native
        k1 = np.searchsorted(t, grid, side="left")          # index of stamp t (exists)
        full = k1 - (n - 1) >= 0
        if not first_partial and not full.all():
            raise ValueError("internal: interval before a stamp is missing")
        if first_partial and not full[1:].all():
            raise ValueError("internal: interval before a later stamp is missing")
        for c in cols:
            v = vals[c]
            res = np.full(grid.size, np.nan)
            kk = k1[full]
            win = np.stack([v[kk - j] for j in range(n)], axis=0)   # NaN propagates
            res[full] = win.sum(axis=0) if c == "Iprec" else win.mean(axis=0)
            if not full[0]:                                 # first stamp, no full interval
                res[0] = np.nan if c == "Iprec" else v[k1[0]]
            out[c] = res
    res = pd.DataFrame(out, index=pd.to_datetime(grid, unit="s"))
    return res[cols]


def process(args):
    """Main processing: read source data and write GEOtop meteo file."""
    start = datetime.strptime(args.start, GEOTOP_DATE_FMT)
    end = datetime.strptime(args.end, GEOTOP_DATE_FMT)

    if args.source in ("nasa_power", "mswx", "cmfd"):
        # Online/point loader via ki_tools_common (canonical HydroCraft path).
        # The requested days are loaded first; only if the native records do
        # not bracket start/end at --dt (e.g. 3-hourly data, window 01:00-23:00)
        # is one more day read on that side, and then the window must be fully
        # covered or the run stops.
        fdir = args.input if (args.input and os.path.exists(args.input)) else None
        pad = (0, 0)
        for attempt in (0, 1):
            raw = read_via_load_forcing(args.source, args.lat, args.lon, start, end, fdir,
                                        dt=args.dt, pad_days=pad)
            try:
                df = to_grid(raw, start, end, args.dt)
                break
            except CoverageError as e:
                if attempt:
                    raise
                pad = (1 if e.need_before else 0, 1 if e.need_after else 0)
                print(json.dumps({"status": "info", "message":
                                  f"{e}; loading one more day {pad} (before, after)"}),
                      file=sys.stderr)
    elif args.source == "csv":
        raw = read_generic_csv(
            args.input, args.col_map,
            args.temp_unit, args.rh_unit, args.precip_unit,
            date_format=args.date_format, pres_unit=args.pres_unit,
            start=start, end=end,
        )
        df = to_grid(raw, start, end, args.dt)
    else:
        print(json.dumps({"status": "error", "errors": [f"Source '{args.source}' reader not yet implemented"]}),
              file=sys.stderr)
        sys.exit(1)

    # Every stamp start..end at --dt is present (to_grid checks it)

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
    """Validate the generated meteo file for common errors.

    A unit that is plainly wrong (RH in fraction, AirT in Kelvin, negative
    rain) is an ERROR: status "error" and main() exits non-zero. Softer
    checks stay warnings.
    """
    warnings = []
    errors = []

    df = pd.read_csv(output_path)

    # Check RelHum range
    if "RelHum" in df.columns:
        rh_valid = df["RelHum"][df["RelHum"] != NODATA]
        if len(rh_valid) > 0:
            if rh_valid.max() <= 1.0:
                errors.append(
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
                errors.append(
                    "CRITICAL: AirT mean > 100 -- likely in Kelvin instead of Celsius. "
                    "Subtract 273.15."
                )

    # Check Iprec (should be non-negative, reasonable range)
    if "Iprec" in df.columns:
        prec_valid = df["Iprec"][df["Iprec"] != NODATA]
        if len(prec_valid) > 0:
            if prec_valid.min() < 0:
                errors.append(f"CRITICAL: Iprec min = {prec_valid.min():.4f} < 0 mm/step.")
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
        "status": "error" if errors else ("ok" if not warnings else "warning"),
        "n_rows": len(df),
        "columns": list(df.columns),
        "errors": errors,
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
                        help="Input precipitation unit (mm_step = mm per INPUT record)")
    parser.add_argument("--date-format", default=None,
                        help="strptime format of the CSV time column (default: ISO 8601; "
                             "e.g. '%%d/%%m/%%Y %%H:%%M' for day-first dates)")
    parser.add_argument("--pres-unit", default="Pa", choices=["Pa", "hPa"],
                        help="Unit of the CSV pressure column ('pres' in --col-map)")

    args = parser.parse_args()
    validate_inputs(args)
    try:
        n_rows = process(args)
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(json.dumps({"status": "error", "errors": [f"{type(e).__name__}: {e}"]}),
              file=sys.stderr)
        sys.exit(1)
    result = validate_outputs(args.output)
    if result["status"] == "error":
        sys.exit(1)
    print(f"Wrote {n_rows} rows to {args.output}")


if __name__ == "__main__":
    main()
