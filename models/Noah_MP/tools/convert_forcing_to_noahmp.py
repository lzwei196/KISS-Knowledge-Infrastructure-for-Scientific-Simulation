#!/usr/bin/env python3
"""
convert_forcing_to_noahmp.py — Stage s4: Meteorological Forcing Converter

Converts global reanalysis / gridded forcing data (CMFD, MSWX, ERA5, NASA POWER)
to Noah-MP HRLDAS LDASIN NetCDF format with proper unit conversions.

Pattern: validate_inputs → process → validate_outputs

Noah-MP HRLDAS expected forcing variables and units:
  T2D      — 2-m air temperature [K]
  Q2D      — 2-m specific humidity [kg/kg]
  U2D      — 10-m U-wind component [m/s]
  V2D      — 10-m V-wind component [m/s]
  PSFC     — Surface pressure [Pa]
  SWDOWN   — Downward shortwave radiation [W/m²]
  LWDOWN   — Downward longwave radiation [W/m²]
  RAINRATE — Precipitation rate [mm/s] (= kg/m²/s)

Output file naming: YYYYMMDDHH.LDASIN_DOMAIN1
"""

import os
import sys
import json
import argparse
import numpy as np
from datetime import datetime, timedelta

try:
    import netCDF4 as nc
except ImportError:
    nc = None

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
PA_PER_HPA = 100.0
MM_PER_S_FROM_MM_PER_HR = 1.0 / 3600.0
MM_PER_S_FROM_MM_PER_DAY = 1.0 / 86400.0
MM_PER_S_FROM_M_PER_HR = 1000.0 / 3600.0

# Physical limits for validation
LIMITS = {
    "T2D":      {"min": 180.0, "max": 340.0, "unit": "K"},
    "Q2D":      {"min": 0.0,   "max": 0.06,  "unit": "kg/kg"},
    "U2D":      {"min": -75.0, "max": 75.0,  "unit": "m/s"},
    "V2D":      {"min": -75.0, "max": 75.0,  "unit": "m/s"},
    "PSFC":     {"min": 40000, "max": 110000, "unit": "Pa"},
    "SWDOWN":   {"min": 0.0,   "max": 1400.0, "unit": "W/m2"},
    "LWDOWN":   {"min": 40.0,  "max": 600.0,  "unit": "W/m2"},
    "RAINRATE": {"min": 0.0,   "max": 0.1,    "unit": "mm/s"},
}


def validate_inputs(args):
    """Validate all input arguments and data availability."""
    errors = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory does not exist: {args.input_dir}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude out of range: {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.strptime(args.end_date, "%Y-%m-%d")
        if end <= start:
            errors.append("end_date must be after start_date")
    except ValueError as e:
        errors.append(f"Date parsing error: {e}")

    if args.timestep not in [3600, 10800, 21600, 86400]:
        errors.append(f"Unusual timestep {args.timestep}s; expected 3600/10800/21600/86400")

    # The HRLDAS driver builds LDASIN filenames as YYYYMMDDHH (10 chars, no minutes)
    # -- see module_NoahMP_hrldas_driver.F, NoahmpIO%inflnm construction.  Sub-hourly
    # forcing therefore CANNOT be addressed by this build; half-hourly sources
    # (e.g. FLUXNET2015 *_HH) must be aggregated to hourly first (the fluxnet
    # reader below does this).
    if args.timestep < 3600:
        errors.append(
            f"timestep={args.timestep}s is sub-hourly, but HRLDAS LDASIN filenames carry "
            "no minutes field (YYYYMMDDHH) — aggregate the source to >=3600 s")

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")

    if errors:
        print("INPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    return {"start": start, "end": end}


def detect_source_format(input_dir):
    """Detect forcing data source format from file patterns."""
    files = os.listdir(input_dir)

    # CMFD: temp_YYYY.nc, prec_YYYY.nc, etc.
    if any("temp_" in f and f.endswith(".nc") for f in files):
        return "cmfd"
    # ERA5: era5_YYYY_MM.nc or single file
    if any("era5" in f.lower() for f in files):
        return "era5"
    # MSWX: mswx_Temp_YYYY.nc etc.
    if any("mswx" in f.lower() for f in files):
        return "mswx"
    # FLUXNET2015 site directory: FULLSET_HR.csv / FULLSET_HH.csv
    # (or the original FLX_<SITE>_FLUXNET2015_FULLSET_H{R,H}_*.csv names)
    if any(("FULLSET_HR" in f or "FULLSET_HH" in f) and f.endswith(".csv") for f in files):
        return "fluxnet"
    # Generic NetCDF with standard names
    if any(f.endswith(".nc") for f in files):
        return "generic_nc"
    # CSV fallback
    if any(f.endswith(".csv") for f in files):
        return "csv"

    return "unknown"


# Units are taken from what the source DECLARES (the NetCDF `units`
# attribute, or the documented output units of the shared loader / FLUXNET
# reader), never guessed from the size of the values. An unknown or missing
# unit stops the tool.
def _norm_units(u):
    return " ".join(str(u).replace("**", "").split()) if u is not None else None


T_OFFSET = {"K": 0.0, "degC": KELVIN_OFFSET, "C": KELVIN_OFFSET,
            "degree_Celsius": KELVIN_OFFSET, "deg C": KELVIN_OFFSET,
            "celsius": KELVIN_OFFSET}
Q_FACTOR = {"kg kg-1": 1.0, "kg/kg": 1.0, "1": 1.0, "g kg-1": 1e-3, "g/kg": 1e-3}
RH_UNITS = ("%", "percent")
P_FACTOR = {"Pa": 1.0, "hPa": PA_PER_HPA, "mbar": PA_PER_HPA, "mb": PA_PER_HPA,
            "kPa": 1000.0}
# precipitation RATES -> mm/s
PR_RATE = {"kg m-2 s-1": 1.0, "mm s-1": 1.0, "mm/s": 1.0,
           "mm hr-1": MM_PER_S_FROM_MM_PER_HR, "mm h-1": MM_PER_S_FROM_MM_PER_HR,
           "mm/hr": MM_PER_S_FROM_MM_PER_HR, "mm/h": MM_PER_S_FROM_MM_PER_HR,
           "mm day-1": MM_PER_S_FROM_MM_PER_DAY, "mm d-1": MM_PER_S_FROM_MM_PER_DAY,
           "mm/day": MM_PER_S_FROM_MM_PER_DAY}
# precipitation ACCUMULATED over one source step -> mm per step
PR_ACCUM = {"m": 1000.0, "mm": 1.0, "kg m-2": 1.0}
FLUX_UNITS = ("W m-2", "W/m2", "W m^-2")
WIND_UNITS = ("m s-1", "m/s")


def _unknown(var, units, known):
    raise ValueError(f"{var}: declared units {units!r} are not known "
                     f"(known: {sorted(known)}); nothing is converted or written")


def convert_temperature(temp_raw, units):
    """Convert temperature to Kelvin from its declared units."""
    u = _norm_units(units)
    if u not in T_OFFSET:
        _unknown("T2D", units, T_OFFSET)
    return np.asarray(temp_raw, dtype=float) + T_OFFSET[u]


def convert_humidity(q_raw, units, temp_k, psfc_pa):
    """Convert humidity to specific humidity [kg/kg] from its declared units."""
    u = _norm_units(units)
    q_raw = np.asarray(q_raw, dtype=float)
    if u in RH_UNITS:
        rh = q_raw
        # Compute saturation vapor pressure (Tetens formula)
        temp_c = temp_k - KELVIN_OFFSET
        es = 611.2 * np.exp(17.67 * temp_c / (temp_c + 243.5))  # Pa
        e = rh / 100.0 * es
        q = 0.622 * e / (psfc_pa - 0.378 * e)
        return np.clip(q, 0.0, 0.06)
    if u not in Q_FACTOR:
        _unknown("Q2D", units, list(Q_FACTOR) + list(RH_UNITS))
    return q_raw * Q_FACTOR[u]


def convert_pressure(p_raw, units):
    """Convert pressure to Pa from its declared units."""
    u = _norm_units(units)
    if u not in P_FACTOR:
        _unknown("PSFC", units, P_FACTOR)
    return np.asarray(p_raw, dtype=float) * P_FACTOR[u]


def convert_precipitation(precip_raw, units, accum_s):
    """Convert precipitation to mm/s from its declared units.

    An accumulation ('m', 'mm', 'kg m-2') is divided by its ACCUMULATION
    PERIOD (`accum_s`, seconds; scalar or one value per record). That period
    is a property of the product (time bounds or --precip_accum_hours), NOT the spacing between the records read: ERA5
    hourly `tp` stays a 1-hour total even when only every 3rd hour is kept
    (ECMWF, "ERA5: understanding accumulations"). Unknown period -> stop."""
    u = _norm_units(units)
    pr = np.asarray(precip_raw, dtype=float)
    if u in PR_RATE:
        return pr * PR_RATE[u]
    if u in PR_ACCUM:
        if accum_s is None:
            raise ValueError(
                f"RAINRATE: units {units!r} are an accumulation, but the source "
                f"gives no accumulation period (no time bounds; a CF "
                f"cell_methods interval is the original sample spacing, not the "
                f"period of the sum). The spacing of the "
                f"records is NOT used for this. State it with --precip_accum_hours "
                f"(ERA5 hourly single levels: 1 h, ending at the stamp; ERA5-Land "
                f"tp is accumulated since 00 UTC and must be de-accumulated first)")
        a = np.asarray(accum_s, dtype=float)
        if not np.all(np.isfinite(a)) or np.any(a <= 0):
            raise ValueError(f"RAINRATE: accumulation period must be > 0 s, got {accum_s!r}")
        return pr * PR_ACCUM[u] / a
    _unknown("RAINRATE", units, list(PR_RATE) + list(PR_ACCUM))


def _to_dt(t):
    """Any datetime-like (python/cftime/pandas) -> python datetime, keeping
    minutes and seconds (they decide the LDASIN file name check)."""
    return datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)


def _nearest(coord, target, is_lon, path, name):
    """Index of the grid cell nearest `target` on a 1-D coordinate. Longitude
    is compared on a circle (so -100 finds 260). A point farther than half a
    grid spacing from every cell (outside the grid) stops the tool."""
    c = np.ma.filled(np.ma.asarray(coord, dtype=float), np.nan)
    if c.ndim != 1 or c.size == 0 or not np.all(np.isfinite(c)):
        raise ValueError(f"{path}: coordinate '{name}' must be 1-D and finite "
                         f"(shape {c.shape}); curvilinear grids are not read")
    d = c - target
    if is_lon:
        d = (d + 180.0) % 360.0 - 180.0
    i = int(np.argmin(np.abs(d)))
    if c.size > 1:
        sp = np.abs(np.diff(c))
        if is_lon:
            sp = np.minimum(sp, 360.0 - sp)
        half = 0.5 * float(np.max(sp)) + 1e-6
        if abs(d[i]) > half:
            raise ValueError(f"{path}: point {name}={target} is {abs(d[i]):.4f} deg from "
                             f"the nearest cell ({c[i]}); it is outside this grid")
    return i


def _nc_time_axis(ds, tname, path):
    """(list of datetimes, per-record duration seconds or None) for a time
    coordinate. Duration comes only from its CF `bounds` variable."""
    if tname not in ds.variables:
        raise ValueError(f"{path}: no coordinate variable for time dimension '{tname}'")
    tv = ds.variables[tname]
    tunits = getattr(tv, "units", None)
    if not tunits or "since" not in str(tunits):
        raise ValueError(f"{path}: time coordinate '{tname}' has no 'X since T' units")
    cal = str(getattr(tv, "calendar", "standard")).lower()
    # HRLDAS runs on the real (Gregorian) calendar and LDASIN names are real
    # dates. A model calendar (noleap, 360_day, julian, ...) has days the real
    # calendar does not have, or lacks real days, and its bounds would turn into
    # wrong durations after conversion; it is not converted here.
    if cal not in ("standard", "gregorian", "proleptic_gregorian"):
        raise ValueError(f"{path}: time calendar {cal!r} is not the real (Gregorian) "
                         f"calendar HRLDAS uses; convert the source to it first")
    traw = np.ma.filled(np.ma.asarray(tv[:], dtype=float), np.nan)
    if not np.all(np.isfinite(traw)):
        raise ValueError(f"{path}: time coordinate '{tname}' has missing values")
    times = [_to_dt(t) for t in nc.num2date(traw, tunits, calendar=cal,
                                            only_use_cftime_datetimes=False)]
    dur = None
    bname = getattr(tv, "bounds", None)
    if bname:
        if bname not in ds.variables:
            raise ValueError(f"{path}: time bounds variable '{bname}' named but absent")
        b = np.ma.filled(np.ma.asarray(ds.variables[bname][:], dtype=float), np.nan)
        if b.shape != (len(times), 2) or not np.all(np.isfinite(b)):
            raise ValueError(f"{path}: time bounds '{bname}' shape {b.shape} / missing values")
        b0 = nc.num2date(b[:, 0], tunits, calendar=cal, only_use_cftime_datetimes=False)
        b1 = nc.num2date(b[:, 1], tunits, calendar=cal, only_use_cftime_datetimes=False)
        dur = np.array([(_to_dt(y) - _to_dt(x)).total_seconds() for x, y in zip(b0, b1)])
    return times, dur


def _nc_point_series(ds, vname, lat, lon, path, idx_cache):
    """Read one variable at the point: (times, float values with every netCDF
    mask -> NaN, units, accumulation seconds or None). The variable must be
    (time, lat, lon) or (time,); any other layout stops the tool (an extra
    level/ensemble axis would otherwise be indexed as lat/lon)."""
    v = ds.variables[vname]
    dims = v.dimensions
    latn = next((n for n in ("lat", "latitude") if n in ds.variables), None)
    lonn = next((n for n in ("lon", "longitude") if n in ds.variables), None)
    if len(dims) == 3:
        if latn is None or lonn is None or dims[1] != ds.variables[latn].dimensions[0] \
                or dims[2] != ds.variables[lonn].dimensions[0]:
            raise ValueError(f"{path}: '{vname}' dims {dims} are not (time, lat, lon)")
        if "ij" not in idx_cache:
            idx_cache["ij"] = (_nearest(ds.variables[latn][:], lat, False, path, latn),
                               _nearest(ds.variables[lonn][:], lon, True, path, lonn))
        ilat, ilon = idx_cache["ij"]
        vals = v[:, ilat, ilon]
    elif len(dims) == 1:
        vals = v[:]
    else:
        raise ValueError(f"{path}: '{vname}' dims {dims} are not (time, lat, lon) or (time,)")
    # netCDF4 masks _FillValue / missing_value / valid_range; np.concatenate
    # would drop that mask, so masked points become NaN HERE (then the
    # missing-value check stops the tool instead of e.g. -9999 rain -> 0).
    vals = np.ma.filled(np.ma.asarray(vals, dtype=float), np.nan)
    times, dur = _nc_time_axis(ds, dims[0], path)
    if vals.shape != (len(times),):
        raise ValueError(f"{path}: '{vname}' has {vals.shape} values for {len(times)} times")
    # The accumulation period comes ONLY from the time bounds. A CF
    # cell_methods "time: sum (interval: N)" gives the spacing of the ORIGINAL
    # samples that were summed (CF 1.12 section 7.3.2), not the period of the
    # sum, so it is not used.
    return times, vals, _nc_units(ds, vname, path), dur


def _assemble(series, path_hint):
    """series: {target: [(times, vals, units, dur), ...]} over files.
    Each variable is concatenated and sorted on ITS OWN times; then every
    variable must have exactly the same time axis (no variable is laid on
    another's dates). Returns times, data, units, accum_s (for RAINRATE)."""
    data, units, axes, accum = {}, {}, {}, None
    for k, parts in series.items():
        us = {p[2] for p in parts}
        if len(us) != 1:
            raise ValueError(f"{path_hint}: {k} units differ between files: {sorted(us)}")
        units[k] = us.pop()
        t = np.array([np.datetime64(x, "s") for p in parts for x in p[0]], dtype="datetime64[s]")
        v = np.concatenate([p[1] for p in parts])
        o = np.argsort(t, kind="stable")
        t, v = t[o], v[o]
        if (np.diff(t).astype(int) <= 0).any():
            i = int(np.flatnonzero(np.diff(t).astype(int) <= 0)[0])
            raise ValueError(f"{path_hint}: {k} has a duplicated time stamp {t[i + 1]} "
                             f"(overlapping files?)")
        axes[k], data[k] = t, v
        if k == "RAINRATE":
            ds_ = [p[3] for p in parts]
            if any(d is not None for d in ds_):
                if any(d is None for d in ds_):
                    raise ValueError(f"{path_hint}: RAINRATE accumulation period is given "
                                     f"in some files but not others")
                accum = np.concatenate(ds_)[o]
    ref_k = next(iter(axes))
    for k, t in axes.items():
        if t.shape != axes[ref_k].shape or not (t == axes[ref_k]).all():
            diff = np.setxor1d(t, axes[ref_k])
            raise ValueError(f"{path_hint}: time axis of {k} ({t.size} stamps) differs from "
                             f"{ref_k} ({axes[ref_k].size}); first differing stamps "
                             f"{[str(x) for x in diff[:3]]}. Variables are not shifted or "
                             f"matched by position; nothing is written")
    times = [x.astype(datetime) for x in axes[ref_k]]
    return times, data, units, accum


def _check_plain_units(var, units, allowed):
    if _norm_units(units) not in allowed:
        _unknown(var, units, allowed)


def _nc_units(ds, name, path):
    v = ds.variables[name]
    u = getattr(v, "units", None)
    if u is None:
        raise ValueError(f"{path}: variable '{name}' has no units attribute; "
                         f"units are not guessed")
    return str(u)


def read_cmfd_at_point(input_dir, lat, lon, start, end):
    """Read CMFD forcing data at a single lat/lon point.

    CMFD ships one file set per variable (temp_*.nc, shum_*.nc, ...), each
    (time, lat, lon) with its own time axis and `units`. Each variable keeps
    its OWN times; _assemble then requires all of them to be the same axis."""
    import glob

    variables = {
        "temp": "T2D", "shum": "Q2D", "wind": "WIND",
        "pres": "PSFC", "srad": "SWDOWN", "lrad": "LWDOWN", "prec": "RAINRATE"
    }
    series = {}
    for cmfd_var, noahmp_var in variables.items():
        pattern = os.path.join(input_dir, f"{cmfd_var}_*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No CMFD files found for {cmfd_var}: {pattern}")
        for fpath in files:
            with nc.Dataset(fpath, 'r') as ds:
                if cmfd_var in ds.variables:
                    var_name = cmfd_var
                else:
                    cands = [v for v in ds.variables if ds.variables[v].ndim == 3]
                    if len(cands) != 1:
                        raise ValueError(f"{fpath}: no variable '{cmfd_var}' and "
                                         f"{len(cands)} other (time,lat,lon) variables "
                                         f"{cands}; cannot tell which one is {cmfd_var}")
                    var_name = cands[0]
                series.setdefault(noahmp_var, []).append(
                    _nc_point_series(ds, var_name, lat, lon, fpath, {}))

    times, data, units, accum = _assemble(series, input_dir)
    # CMFD wind is scalar speed; split equally into U and V
    wind = data.pop("WIND")
    data["U2D"] = wind / np.sqrt(2.0)
    data["V2D"] = wind / np.sqrt(2.0)
    units["U2D"] = units["V2D"] = units.pop("WIND")
    data["_units"] = units
    data["_accum_s"] = accum
    return times, data


def read_mswx_at_point(input_dir, lat, lon, start, end):
    """Read MSWX forcing at a single point via ki_tools_common.load_forcing.

    MSWX ships per-variable ANNUAL files in subdirectories on disk
    (P/, Tair/, SWd/, LWd/, wind/, spechum/, Pres/); the generic
    single-directory NetCDF reader cannot parse that layout, so this branch
    delegates to load_daily_forcing which handles the subdir layout and the
    3-hourly -> daily aggregation. It returns native units that the existing
    convert_* helpers then normalise:
      temp_mean_c (degC), shum_kgkg (kg/kg), pres_pa (Pa),
      srad_wm2 / lrad_wm2 (W/m2), wind_ms (scalar m/s), precip_mm (mm/day).
    """
    from ki_tools_common.load_forcing import (load_daily_forcing,
                                              load_daily_forcing_points, MSWX_DIR)
    fdir = input_dir if (input_dir and os.path.isdir(input_dir)) else MSWX_DIR
    # MSWX annual files are gzip-chunked one GLOBAL slab per 3-hourly timestep, so
    # the single-point xarray path decompresses the whole world once per variable
    # SEQUENTIALLY (minutes per variable-year). Route through the multi-point box
    # reader (len>1 -> _load_mswx_points), which reads a tiny bounding box via h5py
    # and fans the 7 variables across processes -> ~7x faster. A duplicated point
    # keeps the single-column contract; we take result[0].
    # Only start..end is written (see the ts < start / ts > end cut in main),
    # so only those days must be complete in the source.
    period = (start, end)
    try:
        f = load_daily_forcing_points("mswx", [(lat, lon), (lat, lon)],
                                      start.year, end.year, forcing_dir=fdir,
                                      period=period)[0]
    except (ValueError, FileNotFoundError):
        # The loader's own stop (missing files / days / gaps, bad period):
        # the single-point path reads the same data, so do not hide it.
        raise
    except Exception as e:
        print(f"  MSWX box reader failed ({e}); falling back to single-point path",
              file=sys.stderr)
        f = load_daily_forcing("mswx", lat, lon, start.year, end.year, forcing_dir=fdir,
                               period=period)
    # the shared loader's dates may be str, numpy.datetime64 or datetime
    import pandas as pd
    dates = [pd.Timestamp(d).to_pydatetime() for d in f["dates"]]
    n = len(dates)

    def arr(key):
        v = f.get(key)
        if v is None:
            raise ValueError(f"MSWX forcing has no '{key}'; nothing is filled in. "
                             f"Keys given: {sorted(f)}")
        a = np.asarray(v, dtype=float)
        if a.shape != (n,):
            raise ValueError(f"MSWX '{key}': {a.shape} values for {n} days")
        return a

    wind = arr("wind_ms")
    raw = {
        "T2D":      arr("temp_mean_c"),   # degC -> convert_temperature adds 273.15
        "Q2D":      arr("shum_kgkg"),     # already kg/kg
        "U2D":      wind / np.sqrt(2.0),  # MSWX wind is scalar speed; split evenly
        "V2D":      wind / np.sqrt(2.0),
        "PSFC":     arr("pres_pa"),       # already Pa
        "SWDOWN":   arr("srad_wm2"),
        "LWDOWN":   arr("lrad_wm2"),
        "RAINRATE": arr("precip_mm"),     # mm/day -> convert_precipitation(mswx) /86400
        # documented output units of load_daily_forcing (see its docstring)
        "_units": {"T2D": "degC", "Q2D": "kg kg-1", "U2D": "m s-1", "V2D": "m s-1",
                   "PSFC": "Pa", "SWDOWN": "W m-2", "LWDOWN": "W m-2",
                   "RAINRATE": "mm day-1"},
    }
    return dates, raw


# ---------------------------------------------------------------------------
# FLUXNET2015 eddy-covariance tower forcing (site-level, in-situ)
# ---------------------------------------------------------------------------
# Driving Noah-MP with the tower's OWN meteorology is the standard protocol for
# evaluating column LE/HFX against eddy-covariance LE (Ingwersen 2015, Gao 2015,
# PLUMBER).  It removes reanalysis forcing error from the verdict, which is what
# makes the LE comparison a statement about the MODEL rather than about MSWX.
#
# FLUXNET2015 FULLSET columns used (all *_F are gap-filled, so no holes):
#   TA_F    degC        -> T2D      (K)
#   SW_IN_F W/m2        -> SWDOWN
#   LW_IN_F W/m2        -> LWDOWN   (LW_IN_JSB_F fallback where LW was not measured)
#   VPD_F   hPa         -> Q2D      (kg/kg, via RH and ki_tools_common.humidity)
#   PA_F    kPa         -> PSFC     (Pa)
#   WS_F    m/s         -> U2D      (V2D = 0; Noah-MP only uses sqrt(u^2+v^2))
#   P_F     mm/interval -> RAINRATE (mm/s)
#
# *** TIMEZONE TRAP (dt_019) ***
# FLUXNET timestamps are LOCAL STANDARD TIME (no DST).  HRLDAS computes the
# solar hour angle as  TLOCTIM = UTC_hour + longitude/15  (CALC_DECLIN in
# module_NoahMP_hrldas_driver.F), i.e. it assumes the LDASIN timestamp is UTC.
# Feeding local-time-stamped forcing therefore puts COSZ out of phase with
# SWDOWN by the site's UTC offset (up to ~12 h): the model computes canopy
# radiation, albedo and stomatal response for the wrong time of day and LE is
# structurally wrong even with perfect forcing.  --utc_offset is REQUIRED.
FLUXNET_COLS = {
    "TA":  ["TA_F", "TA_F_MDS", "TA_ERA"],
    "SW":  ["SW_IN_F", "SW_IN_F_MDS", "SW_IN_ERA"],
    "LW":  ["LW_IN_F", "LW_IN_F_MDS", "LW_IN_JSB_F", "LW_IN_ERA"],
    "VPD": ["VPD_F", "VPD_F_MDS", "VPD_ERA"],
    "PA":  ["PA_F", "PA_ERA"],
    "WS":  ["WS_F", "WS_ERA"],
    "P":   ["P_F", "P_ERA"],
}
FLUXNET_MISSING = -9999.0


def _fluxnet_pick(df, candidates, label):
    for c in candidates:
        if c in df.columns and np.isfinite(df[c].to_numpy(dtype=float)).any():
            return c
    raise KeyError(f"FLUXNET file has none of {candidates} for {label}")


def read_fluxnet_at_point(input_dir, start, end, utc_offset):
    """Read FLUXNET2015 FULLSET tower meteorology as Noah-MP forcing.

    Args:
        input_dir:  a FLUXNET2015 site directory containing FULLSET_HR.csv or
                    FULLSET_HH.csv (hourly / half-hourly FULLSET product).
        start, end: datetimes bounding the wanted UTC period.
        utc_offset: the site's UTC_OFFSET (hours) from the FLUXNET BADM/BIF
                    metadata.  MUST be supplied -- see the TIMEZONE TRAP above.

    Returns:
        (times_utc, raw_dict) with RAINRATE in mm/s, PSFC in Pa, Q2D in kg/kg,
        T2D in degC (convert_temperature promotes it to K).
    """
    import glob
    import pandas as pd
    from ki_tools_common.humidity import saturation_vapor_pressure, rh_to_specific_humidity

    if utc_offset is None:
        raise ValueError(
            "--utc_offset is REQUIRED for --source fluxnet: FLUXNET timestamps are "
            "local standard time but HRLDAS interprets LDASIN timestamps as UTC "
            "(CALC_DECLIN: TLOCTIM = hour + lon/15).  See dt_019.")

    cands = (sorted(glob.glob(os.path.join(input_dir, "*FULLSET_HR*.csv"))) or
             sorted(glob.glob(os.path.join(input_dir, "*FULLSET_HH*.csv"))))
    if not cands:
        raise FileNotFoundError(f"No FLUXNET2015 FULLSET_HR/HH csv in {input_dir}")
    path = cands[0]
    print(f"  FLUXNET file: {os.path.basename(path)}")

    df = pd.read_csv(path)
    if "TIMESTAMP_START" not in df.columns:
        raise KeyError(f"{path} has no TIMESTAMP_START column")
    ts = pd.to_datetime(df["TIMESTAMP_START"].astype("int64").astype(str), format="%Y%m%d%H%M")
    df = df.replace(FLUXNET_MISSING, np.nan)
    df.index = ts

    if not ts.is_monotonic_increasing or ts.duplicated().any():
        raise ValueError(f"{path}: TIMESTAMP_START is not strictly increasing")
    # P_F is mm per RECORD INTERVAL = TIMESTAMP_START..TIMESTAMP_END (FLUXNET2015
    # data format); take that interval from the file, not from record spacing.
    if "TIMESTAMP_END" not in df.columns:
        raise KeyError(f"{path} has no TIMESTAMP_END column; the precipitation "
                       f"interval cannot be read")
    te = pd.to_datetime(df["TIMESTAMP_END"].astype("int64").astype(str), format="%Y%m%d%H%M")
    ivals = np.unique((te.to_numpy() - ts.to_numpy()) // np.timedelta64(1, "s")).astype(int)
    if len(ivals) != 1 or ivals[0] not in (1800, 3600):
        raise ValueError(f"{path}: record intervals {sorted(ivals)[:5]} s; expected one "
                         f"constant 1800 (HH) or 3600 (HR)")
    dt_s = int(ivals[0])
    print(f"  native interval: {dt_s} s ({len(df)} records, "
          f"{ts.iloc[0]} .. {ts.iloc[-1]} local standard time)")

    cols = {k: _fluxnet_pick(df, v, k) for k, v in FLUXNET_COLS.items()}
    print("  columns: " + ", ".join(f"{k}={v}" for k, v in cols.items()))

    sub = pd.DataFrame({k: df[c].astype(float) for k, c in cols.items()})

    # HRLDAS LDASIN filenames carry no minutes -> aggregate sub-hourly to hourly.
    # Precipitation is an accumulation (sum); everything else is a state/flux (mean).
    if dt_s < 3600:
        grp = sub.groupby(sub.index.floor("h"))
        agg = grp.mean()
        agg["P"] = grp["P"].sum()
        n_per_hour = grp.size()
        # an hour with a missing record or a missing value stays missing (NaN),
        # never averaged/summed over the remaining records; the check below stops
        full = grp.count().eq(3600 // dt_s)
        agg = agg.where(full)
        agg = agg[n_per_hour == (3600 // dt_s)]   # drop incomplete hours
        sub = agg
        dt_s = 3600
        print(f"  aggregated to hourly: {len(sub)} records")

    # ---- local standard time -> UTC (dt_019) ----
    sub.index = sub.index - timedelta(hours=float(utc_offset))
    print(f"  shifted local standard time -> UTC by {-float(utc_offset):+g} h; "
          f"UTC range {sub.index[0]} .. {sub.index[-1]}")

    sub = sub[(sub.index >= start) & (sub.index <= end)]
    if len(sub) == 0:
        raise ValueError(f"No FLUXNET records inside {start} .. {end} after UTC shift")
    # Residual gaps (*_ERA fallbacks, dropped hours) are NOT filled: every step
    # of start..end must be present and every value real, or the tool stops.
    # same clock phase as the data (a fractional UTC offset shifts it), but
    # starting at the first step on/after start, so a leading gap is caught
    step = pd.Timedelta(seconds=dt_s)
    phase = (sub.index[0] - pd.Timestamp(start)) % step
    want = pd.date_range(pd.Timestamp(start) + phase, end, freq=step)
    lost = want.difference(sub.index)
    if len(lost):
        raise ValueError(
            f"FLUXNET: {len(lost)} of {len(want)} steps in {start} .. {end} (UTC) are "
            f"absent or incomplete (first: {', '.join(str(x) for x in lost[:5])}). "
            f"Nothing is filled in.")
    for k in sub.columns:
        bad = sub[k].isna()
        if bad.any():
            raise ValueError(
                f"FLUXNET {k} ({cols[k]}): {int(bad.sum())} missing values in "
                f"{start} .. {end} (first: "
                f"{', '.join(str(x) for x in sub.index[bad.to_numpy()][:5])}). "
                f"Nothing is filled in.")

    ta_c = sub["TA"].to_numpy(float)
    pa_pa = sub["PA"].to_numpy(float) * 1000.0            # kPa -> Pa
    vpd_hpa = np.clip(sub["VPD"].to_numpy(float), 0.0, None)
    es_hpa = saturation_vapor_pressure(ta_c)
    rh = np.clip(100.0 * (1.0 - vpd_hpa / np.maximum(es_hpa, 1e-6)), 1.0, 100.0)
    q = rh_to_specific_humidity(rh, ta_c + KELVIN_OFFSET, pa_pa)

    raw = {
        "T2D":      ta_c,                                  # degC
        "Q2D":      np.asarray(q, dtype=float),            # kg/kg
        "U2D":      sub["WS"].to_numpy(float),             # scalar speed on U
        "V2D":      np.zeros(len(sub)),
        "PSFC":     pa_pa,                                 # Pa
        "SWDOWN":   np.clip(sub["SW"].to_numpy(float), 0.0, None),
        "LWDOWN":   sub["LW"].to_numpy(float),
        "RAINRATE": np.clip(sub["P"].to_numpy(float), 0.0, None) / float(dt_s),  # mm/s
        # units after this reader's own conversions (FLUXNET2015 *_F: TA degC,
        # PA kPa -> Pa above, P mm per interval -> mm/s above, SW/LW W m-2, WS m s-1)
        "_units": {"T2D": "degC", "Q2D": "kg kg-1", "U2D": "m s-1", "V2D": "m s-1",
                   "PSFC": "Pa", "SWDOWN": "W m-2", "LWDOWN": "W m-2",
                   "RAINRATE": "mm s-1"},
    }
    times = [t.to_pydatetime() for t in sub.index]
    return times, raw


def read_generic_nc_at_point(input_dir, lat, lon, start, end):
    """Read generic NetCDF forcing data (one or more files, any split by time
    and/or by variable). Every mapped variable is read as (time, lat, lon) or
    (time,) with its own file's time axis (the variable's first dimension,
    e.g. 'time' or ERA5's 'valid_time'); see _nc_point_series / _assemble."""
    import glob
    files = sorted(glob.glob(os.path.join(input_dir, "*.nc")))
    if not files:
        raise FileNotFoundError(f"No NetCDF files in {input_dir}")

    # Map common variable names to Noah-MP names
    name_map = {
        "t2m": "T2D", "T2M": "T2D", "tmp": "T2D", "TMP": "T2D", "T2D": "T2D",
        "q2m": "Q2D", "Q2M": "Q2D", "SPFH": "Q2D", "Q2D": "Q2D",
        "u10": "U2D", "U10M": "U2D", "UGRD": "U2D", "U2D": "U2D",
        "v10": "V2D", "V10M": "V2D", "VGRD": "V2D", "V2D": "V2D",
        "sp": "PSFC", "PS": "PSFC", "PRES": "PSFC", "PSFC": "PSFC",
        "ssrd": "SWDOWN", "DSWRF": "SWDOWN", "SWDOWN": "SWDOWN",
        "strd": "LWDOWN", "DLWRF": "LWDOWN", "LWDOWN": "LWDOWN",
        "tp": "RAINRATE", "APCP": "RAINRATE", "RAINRATE": "RAINRATE",
    }

    series = {}
    for fpath in files:
        with nc.Dataset(fpath, 'r') as ds:
            found = {}
            for vn in ds.variables:
                if vn in name_map:
                    tgt = name_map[vn]
                    if tgt in found:
                        raise ValueError(f"{fpath}: both '{found[tgt]}' and '{vn}' map to "
                                         f"{tgt}; cannot tell which one to use")
                    found[tgt] = vn
            cache = {}
            for tgt, vn in found.items():
                series.setdefault(tgt, []).append(
                    _nc_point_series(ds, vn, lat, lon, fpath, cache))

    if not series:
        return None, {}
    times, data, units, accum = _assemble(series, input_dir)
    data["_units"] = units
    data["_accum_s"] = accum
    return times, data


def write_ldasin(output_dir, timestamp, data_dict, lat, lon):
    """Write a single LDASIN NetCDF file for one timestep."""
    fname = timestamp.strftime("%Y%m%d%H") + ".LDASIN_DOMAIN1"
    fpath = os.path.join(output_dir, fname)

    with nc.Dataset(fpath, 'w', format='NETCDF4') as ds:
        ds.createDimension('Time', 1)
        ds.createDimension('south_north', 1)
        ds.createDimension('west_east', 1)

        for varname, value in data_dict.items():
            var = ds.createVariable(varname, 'f4', ('Time', 'south_north', 'west_east'))
            var[0, 0, 0] = float(value)
            if varname in LIMITS:
                var.units = LIMITS[varname]["unit"]

    return fpath


def process(args, context):
    """Main processing: read, convert, write LDASIN files."""
    start = context["start"]
    end = context["end"]
    os.makedirs(args.output_dir, exist_ok=True)

    # Honour an explicit --source; fall back to auto-detection.
    if getattr(args, "source", "auto") and args.source.lower() != "auto":
        source = args.source.lower()
    else:
        source = detect_source_format(args.input_dir)
    print(f"Source format: {source}")

    # Read raw data (a reader's own stop is printed as one clear error, exit 1)
    try:
        if source == "cmfd":
            times, raw = read_cmfd_at_point(args.input_dir, args.lat, args.lon, start, end)
        elif source == "mswx":
            times, raw = read_mswx_at_point(args.input_dir, args.lat, args.lon, start, end)
        elif source == "fluxnet":
            times, raw = read_fluxnet_at_point(args.input_dir, start, end,
                                               getattr(args, "utc_offset", None))
        else:
            times, raw = read_generic_nc_at_point(args.input_dir, args.lat, args.lon,
                                                  start, end)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"ERROR: {e}; no LDASIN file is written.", file=sys.stderr)
        sys.exit(1)

    if times is None or len(times) == 0:
        print("ERROR: No forcing data found in specified period", file=sys.stderr)
        sys.exit(1)

    VARS = ("T2D", "PSFC", "Q2D", "U2D", "V2D", "SWDOWN", "LWDOWN", "RAINRATE")
    times = [_to_dt(t) for t in times]

    def stop(msg):
        print(f"ERROR: {msg}; nothing is filled in and no LDASIN file is written.",
              file=sys.stderr)
        sys.exit(1)

    # Every LDASIN field must come from the source: a missing field, or a
    # missing value inside start..end, stops the tool (nothing is filled in).
    in_window = np.array([start <= t <= end for t in times], dtype=bool)
    missing = [k for k in VARS if raw.get(k) is None]
    if missing:
        stop(f"source '{source}' gives no {missing} at this point")
    for k in VARS:
        a = np.asarray(raw[k], dtype=float)
        if a.shape != (len(times),):
            stop(f"{k}: {a.shape} values for {len(times)} time steps")
        nbad = int((~np.isfinite(a[in_window])).sum())
        if nbad:
            stop(f"{k}: {nbad} missing values in {start:%Y-%m-%d}..{end:%Y-%m-%d}")

    # Units come from what each reader DECLARES
    units = raw.get("_units") or {}
    no_units = [k for k in VARS if not units.get(k)]
    if no_units:
        stop(f"source '{source}' declares no units for {no_units}; units are not guessed")

    # ---- time axis ----
    # The cadence is NOT guessed from the records inside the window (a gap
    # there would make an hourly series look 2-hourly). The expected cadence is
    # --timestep (= the HRLDAS FORCING_TIMESTEP these files are read with), and
    # the WHOLE axis the reader returned must not be finer or coarser than it.
    # Then every step of start..end on that grid must be present.
    step = int(args.timestep)
    tt = np.asarray([np.datetime64(t, "s") for t in times], dtype="datetime64[s]")
    d_all = np.diff(tt).astype(int)
    if (d_all <= 0).any():
        i = int(np.flatnonzero(d_all <= 0)[0])
        stop(f"source time axis is duplicated or out of order at {tt[i + 1]}")
    if d_all.size:
        if int(d_all.min()) < step:
            stop(f"source has records {int(d_all.min())} s apart, finer than --timestep "
                 f"{step} s; this tool does not aggregate (sub-step records would be "
                 f"dropped or overwrite each other)")
        if int(d_all.min()) > step:
            stop(f"source records are at least {int(d_all.min())} s apart, coarser than "
                 f"--timestep {step} s")
    t0 = np.datetime64(start, "s")
    phase = int((tt[0] - t0).astype(int)) % step
    want = np.arange(t0 + np.timedelta64(phase, "s"), np.datetime64(end, "s") + 1,
                     np.timedelta64(step, "s"))
    win = tt[in_window]
    if want.size == 0 or win.size != want.size or not (win == want).all():
        lost = np.setdiff1d(want, win)
        extra = np.setdiff1d(win, want)
        stop(f"{lost.size} of {want.size} time steps of {step} s are absent in "
             f"{start}..{end} (first: {', '.join(str(x) for x in lost[:5])}); "
             f"{extra.size} stamps are off the grid")
    # HRLDAS LDASIN names are YYYYMMDDHH (no minutes). The step is a whole
    # number of hours (validate_inputs) and the grid check above puts every
    # stamp on one clock phase, so two stamps can never share a name. A source
    # whose stamps carry minutes (CMFD V2 daily is stamped 10:30) is written
    # under the whole hour; the values are not changed and the shift is
    # printed and stored in forcing_summary.json.
    off = sorted({(t.minute, t.second) for t, w in zip(times, in_window)
                  if w and (t.minute or t.second)})
    stamp_shift = None
    if off:
        if len(off) != 1:
            stop(f"stamps carry different minute offsets {off[:3]}")
        stamp_shift = f"-{off[0][0]:02d}:{off[0][1]:02d} (mm:ss)"
        print(f"  NOTE: source stamps are at HH:{off[0][0]:02d}:{off[0][1]:02d}; LDASIN file "
              f"names have no minutes, so each file is named by its whole hour (label "
              f"moved back by {off[0][0]} min {off[0][1]} s; values unchanged)")
    args._stamp_shift = stamp_shift

    # ---- precipitation accumulation period (only used for accumulated units) ----
    accum = raw.get("_accum_s")
    cli_h = getattr(args, "precip_accum_hours", None)
    if cli_h is not None:
        cli_s = float(cli_h) * 3600.0
        if accum is not None and not np.allclose(np.asarray(accum)[in_window], cli_s):
            stop(f"--precip_accum_hours {cli_h} disagrees with the source's own "
                 f"accumulation period {sorted(set(np.asarray(accum)[in_window].tolist()))[:3]} s")
        accum = cli_s if accum is None else accum
    try:
        _check_plain_units("U2D", units["U2D"], WIND_UNITS)
        _check_plain_units("V2D", units["V2D"], WIND_UNITS)
        _check_plain_units("SWDOWN", units["SWDOWN"], FLUX_UNITS)
        _check_plain_units("LWDOWN", units["LWDOWN"], FLUX_UNITS)
        converted = {}
        converted["T2D"] = convert_temperature(raw["T2D"], units["T2D"])
        converted["PSFC"] = convert_pressure(raw["PSFC"], units["PSFC"])
        converted["Q2D"] = convert_humidity(
            raw["Q2D"], units["Q2D"],
            converted["T2D"], converted["PSFC"]
        )
        converted["U2D"] = np.asarray(raw["U2D"], dtype=float)
        converted["V2D"] = np.asarray(raw["V2D"], dtype=float)
        converted["SWDOWN"] = np.clip(np.asarray(raw["SWDOWN"], dtype=float), 0.0, None)
        converted["LWDOWN"] = np.asarray(raw["LWDOWN"], dtype=float)
        acc_w = None
        if accum is not None and np.ndim(accum):
            acc_w = np.asarray(accum, dtype=float)
            acc_w = np.where(in_window, acc_w, 1.0)   # outside the window: never written
        converted["RAINRATE"] = np.clip(
            convert_precipitation(raw["RAINRATE"], units["RAINRATE"],
                                  acc_w if acc_w is not None else accum),
            0.0, None
        )
    except ValueError as e:
        stop(str(e))
    print("Declared units used: " + ", ".join(f"{k}={units[k]}" for k in sorted(units)))
    if _norm_units(units["RAINRATE"]) in PR_ACCUM:
        a_s = np.asarray(accum, dtype=float)
        a_s = a_s[in_window] if a_s.ndim else a_s
        print(f"  RAINRATE = accumulation / its own period ({sorted(set(np.atleast_1d(a_s).tolist()))[:3]} s)")
        if np.any(np.atleast_1d(a_s) < step):
            print(f"  NOTE: the precipitation accumulation period is shorter than the "
                  f"{step} s step; each written rate is that sampled period's rate, not "
                  f"the mean over the whole step")

    # Write LDASIN files
    n_warnings = 0
    written = []
    for i, ts in enumerate(times):
        if not in_window[i]:
            continue

        step_data = {}
        for varname in LIMITS:
            val = float(converted[varname][i])
            lim = LIMITS[varname]
            if val < lim["min"] or val > lim["max"]:
                n_warnings += 1
                if n_warnings <= 10:
                    print(f"  WARNING: {varname}={val:.4f} outside [{lim['min']}, {lim['max']}] "
                          f"at {ts}")
            step_data[varname] = val

        written.append(write_ldasin(args.output_dir, ts, step_data, args.lat, args.lon))

    return written, n_warnings, source


def validate_outputs(output_dir, written):
    """Validate the LDASIN files THIS run wrote: one distinct file per written
    step, all present, all fields in the first and last file, and no other
    LDASIN file in the folder (HRLDAS would read a stale one)."""
    errors = []

    if len(written) == 0:
        errors.append("No LDASIN files were written")
    names = {os.path.basename(f) for f in written}
    if len(names) != len(written):
        errors.append(f"{len(written)} steps written to only {len(names)} distinct files "
                      f"(some overwrote others)")
    absent = [f for f in written if not os.path.isfile(f)]
    if absent:
        errors.append(f"{len(absent)} written files are missing (first: {absent[0]})")
    others = sorted(f for f in os.listdir(output_dir)
                    if f.endswith(".LDASIN_DOMAIN1") and f not in names)
    if others:
        errors.append(f"{len(others)} other LDASIN files in {output_dir} not from this run "
                      f"(first: {others[0]}); remove them")

    for fpath in sorted(set(written[:1] + written[-1:])):
        if not os.path.isfile(fpath):
            continue
        with nc.Dataset(fpath, 'r') as ds:
            for varname in ["T2D", "Q2D", "U2D", "V2D", "PSFC", "SWDOWN", "LWDOWN", "RAINRATE"]:
                if varname not in ds.variables:
                    errors.append(f"Missing variable {varname} in {fpath}")

    if errors:
        print("OUTPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to Noah-MP HRLDAS LDASIN format"
    )
    parser.add_argument("--input_dir", required=True, help="Input forcing data directory")
    parser.add_argument("--output_dir", required=True, help="Output LDASIN directory")
    parser.add_argument("--lat", type=float, required=True, help="Latitude of point")
    parser.add_argument("--lon", type=float, required=True, help="Longitude of point")
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--timestep", type=int, default=3600,
                        help="Forcing timestep in seconds = HRLDAS FORCING_TIMESTEP; the "
                             "source records must be exactly this far apart (default: 3600)")
    parser.add_argument("--source", default="auto",
                        help="Source format: cmfd/era5/mswx/fluxnet/generic_nc/auto (default: auto)")
    parser.add_argument("--utc_offset", type=float, default=None,
                        help="Site UTC offset in hours (REQUIRED for --source fluxnet). "
                             "FLUXNET timestamps are local standard time; HRLDAS reads "
                             "LDASIN timestamps as UTC (dt_019).")
    parser.add_argument("--precip_accum_hours", type=float, default=None,
                        help="Accumulation period (hours) of an ACCUMULATED precipitation "
                             "field (units m / mm / kg m-2) when the files carry no time "
                             "bounds. ERA5 hourly single levels: 1.")

    args = parser.parse_args()

    print("=" * 60)
    print("Noah-MP Forcing Converter")
    print("=" * 60)

    context = validate_inputs(args)
    print(f"  Input:  {args.input_dir}")
    print(f"  Output: {args.output_dir}")
    print(f"  Point:  ({args.lat}, {args.lon})")
    print(f"  Period: {args.start_date} to {args.end_date}")
    print(f"  Timestep: {args.timestep}s")

    written, n_warnings, source = process(args, context)
    print(f"\nWrote {len(written)} LDASIN files ({n_warnings} warnings)")

    ok = validate_outputs(args.output_dir, written)
    print("OUTPUT VALIDATION: PASSED" if ok else "OUTPUT VALIDATION: FAILED")

    # Write summary JSON
    summary = {
        "tool": "convert_forcing_to_noahmp",
        "n_files": len(written),
        "n_warnings": n_warnings,
        "output_dir": args.output_dir,
        "source_format": source,
        "validation": "passed" if ok else "failed",
        "stamp_label_shift": getattr(args, "_stamp_shift", None),
    }
    summary_path = os.path.join(args.output_dir, "forcing_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {summary_path}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
