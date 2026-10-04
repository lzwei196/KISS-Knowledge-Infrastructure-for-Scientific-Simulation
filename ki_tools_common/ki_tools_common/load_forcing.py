#!/usr/bin/env python3
"""
load_forcing.py — Unified loader for CMFD, MSWX, and NASA POWER forcing data.

Wraps all 3 data sources behind a single interface so that adapters can switch
between them with a --source flag without any other code changes.

All sources return the same standardised dict with keys:
    dates, precip_mm, temp_mean_c, temp_max_c, temp_min_c,
    srad_wm2, wind_ms, shum_kgkg, pres_pa

Usage:
    from ki_tools_common.load_forcing import load_daily_forcing
    data = load_daily_forcing('cmfd', lat, lon, start_year, end_year, forcing_dir=...)
    data = load_daily_forcing('nasa_power', lat, lon, start_year, end_year)
"""

import os
import re
import warnings
from datetime import datetime, timedelta

import numpy as np

# Default paths
CMFD_DIR = "KISSPATH_FORCING/Data_forcing_03hr_010deg"
MSWX_DIR = "KISSPATH_FORCING"
# GSWP3-W5E5 (ISIMIP3a obsclim), decadal global 0.5deg DAILY netCDF, 1901-2019.
GSWP3_DIR = "KISSPATH_OUTPUTS/papers/cold_soil_warming/snow_depth_validation/forcing_ensemble/raw/gswp3_w5e5"
GSWP3_DECADES = [(1971, 1980), (1981, 1990), (1991, 2000), (2001, 2010), (2011, 2019)]

# NASA POWER API
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
# WS10M is requested alongside WS2M for the SAME reason the daily endpoint does
# (see the WS10M block in _load_nasa_power): POWER's WS2M is derived with a fixed
# surface-roughness assumption and goes anomalously low (annual means well under
# 1 m/s) over forested/rough cells, which starves turbulent exchange in any
# surface-energy-balance model. The hourly loader used to request WS2M only,
# silently handing those near-zero winds to callers.
NASA_POWER_PARAMS = "T2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,WS2M,WS10M,QV2M,PS"
# Daily endpoint (used by load_daily_forcing). NASA POWER DAILY data starts at
# 1981-01-01 (vs HOURLY which only starts 2001-01-01), so the daily loader MUST
# use this endpoint to honor the documented 1981+ coverage. It also returns
# native daily Tmin/Tmax + one bounded request per year (no hourly aggregation).
# Daily radiation is kW-hr/m^2/day -> W/m^2 via *1000/24.
NASA_POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_DAILY_PARAMS = (
    "T2M,T2M_MIN,T2M_MAX,PRECTOTCORR,"
    "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,WS2M,WS10M,QV2M,PS"
)


def load_daily_forcing(source, lat, lon, start_year, end_year, forcing_dir=None,
                       variables=None, on_missing="raise", period=None):
    """Load daily forcing from CMFD, MSWX, or NASA POWER.

    Args:
        source: 'cmfd', 'mswx', or 'nasa_power'
        lat, lon: location (degrees)
        start_year, end_year: period (inclusive)
        forcing_dir: root directory for cmfd/mswx; optional for nasa_power
        variables: optional subset of source variables to actually READ
            (MSWX only; keys P/Tair/SWd/LWd/Wind/spechum/Pres). Unread
            variables come back as NaN. Use it when a model needs only
            precipitation and temperature — MSWX annual files are one gzip
            slab per timestep, so each variable skipped saves a whole-year
            decompression (~5 min). Ignored by the other sources.

            For every source, variables= also tells the completeness check
            what the caller needs: a variable not listed is not checked (and
            may hold NaN); one listed (or every one, when variables is None)
            must be complete.
        on_missing: "raise" (default) stops with a message naming the variable
            and the first missing dates when any requested day is absent, or
            when a variable has a gap. "nan" returns the gaps as NaN for a
            caller that checks them itself. Missing values are NEVER replaced
            (no 0 mm rain, no mean for an extreme, no other wind height).
        period: optional (start, end) dates, end included, inside the years:
            only this stretch must be complete (for part-year runs).

    Returns:
        dict with keys: dates, precip_mm, temp_mean_c, temp_max_c,
                        temp_min_c, srad_wm2, wind_ms, shum_kgkg, pres_pa
             (and lrad_wm2 when available). A variable the source does not
             give, or that was not requested, is NaN for every day.
    """
    _check_on_missing(on_missing)
    skip = _not_requested(source, variables)      # validates the keys up front
    source = source.lower().strip()
    if source == "cmfd":
        out = _load_cmfd(lat, lon, start_year, end_year, forcing_dir)
    elif source == "mswx":
        out = _load_mswx(lat, lon, start_year, end_year, forcing_dir,
                         variables=variables)
    elif source == "nasa_power":
        out = _load_nasa_power(lat, lon, start_year, end_year)
    elif source == "gswp3":
        out = _load_gswp3(lat, lon, start_year, end_year, forcing_dir)
    else:
        raise ValueError(f"Unknown source '{source}'. Choose from: cmfd, mswx, nasa_power, gswp3")
    if on_missing == "raise":
        _require_complete_daily(out, source, start_year, end_year, f"({lat}, {lon})",
                                skip, period)
    return out


def load_daily_forcing_points(source, latlons, start_year, end_year,
                              forcing_dir=None, variables=None, on_missing="raise",
                              period=None):
    """Load daily forcing at SEVERAL points, returning one dict per point.

    Equivalent to calling ``load_daily_forcing`` once per point, but for the
    CMFD 3-hourly store it reads each monthly NetCDF ONCE and extracts all the
    points from that single decompression pass. The 3-hourly files are chunked
    across the full (lat, lon) slab, so a "single column" read still inflates
    the whole file: the per-point cost is ~214 s/station-year and scales with
    the number of stations, not with the number of values wanted. Sharing the
    pass makes an N-station basin cost about the same as one station.

    Args:
        source: 'cmfd', 'mswx', 'nasa_power', or 'gswp3'
        latlons: sequence of (lat, lon) pairs
        start_year, end_year: period (inclusive)
        forcing_dir: root directory for cmfd/mswx

        on_missing, period: as in ``load_daily_forcing``; applied to every point.

    Returns:
        list of forcing dicts, in the same order as ``latlons``; each has the
        same keys as ``load_daily_forcing``.
    """
    _check_on_missing(on_missing)
    skip = _not_requested(source, variables)
    latlons = [(float(a), float(b)) for a, b in latlons]
    src = source.lower().strip()
    if src == "cmfd" and len(latlons) > 1:
        res = _load_cmfd_points(latlons, start_year, end_year, forcing_dir)
    elif src == "mswx":
        # MSWX annual files are gzip-chunked one GLOBAL slab per timestep, so a
        # per-point loop would decompress the whole file once per point.
        res = _load_mswx_points(latlons, start_year, end_year, forcing_dir,
                                variables=variables)
    else:
        return [load_daily_forcing(source, la, lo, start_year, end_year, forcing_dir,
                                   variables=variables, on_missing=on_missing,
                                   period=period)
                for la, lo in latlons]
    if on_missing == "raise":
        for (la, lo), o in zip(latlons, res):
            _require_complete_daily(o, src, start_year, end_year, f"({la}, {lo})",
                                    skip, period)
    return res


_ON_MISSING = ("raise", "nan")
# variables= keys (MSWX naming, used for every source) -> output names.
_VARIABLE_KEYS = ("P", "Tair", "SWd", "LWd", "Wind", "spechum", "Pres")
_DAILY_NAMES = {
    "P": ("precip_mm",), "Tair": ("temp_mean_c", "temp_max_c", "temp_min_c"),
    "SWd": ("srad_wm2",), "LWd": ("lrad_wm2",), "Wind": ("wind_ms", "wind2_ms"),
    "spechum": ("shum_kgkg",), "Pres": ("pres_pa",),
}
_SUBDAILY_NAMES = {
    "P": ("precip_mm", "prec_kgm2s"), "Tair": ("temp_c",),
    "SWd": ("srad_wm2",), "LWd": ("lrad_wm2",), "Wind": ("wind_ms", "wind2_ms"),
    "spechum": ("shum_kgkg",), "Pres": ("pres_pa",),
}


def _not_requested(source, variables, names=_DAILY_NAMES):
    """Output names the caller said it does not need (variables=). These are
    returned as read (NaN where missing, or throughout if not read) and are not
    checked; every variable the caller needs must be complete."""
    if variables is None:
        return ()
    want = set(variables)
    unknown = want - set(_VARIABLE_KEYS)
    if unknown:
        # Callers written before this check pass their own names (SWAP:
        # "tmin", "prcp", ...). Earlier loaders ignored them. We cannot tell
        # what such a caller needs, so NOTHING is excluded: every variable is
        # checked. Unknown names can only make the check stricter.
        warnings.warn(f"variables: keys {sorted(unknown)} are not {_VARIABLE_KEYS}; "
                      f"every variable is checked for completeness")
        return ()
    return tuple(n for k, ns in names.items() if k not in want for n in ns)


def _period_bounds(period, start_year, end_year, as_steps=False):
    """[first, stop) of the stretch that must be complete: the whole years by
    default, or the explicit period=(start, end), end inclusive, which must lie
    inside the years asked for."""
    unit = "s" if as_steps else "D"
    first = np.datetime64(f"{start_year}-01-01", unit)
    stop = np.datetime64(f"{end_year + 1}-01-01", unit)
    if period is None:
        return first, stop
    a = np.datetime64(str(period[0])[:10], "D").astype(f"datetime64[{unit}]")
    b = (np.datetime64(str(period[1])[:10], "D") + np.timedelta64(1, "D")).astype(f"datetime64[{unit}]")
    if not (first <= a < b <= stop):
        raise ValueError(f"period {period} must lie inside {start_year}-{end_year}")
    return a, b


def _samples_per_day(times):
    """Samples per day from the store's own time step (3-hourly -> 8,
    daily -> 1), so a store that is short on EVERY day is still caught."""
    t = np.asarray(times, dtype="datetime64[s]").astype("int64")
    if t.size < 2:
        return 1
    d = np.diff(np.sort(t))
    d = d[d > 0]
    vals, cnt = np.unique(d, return_counts=True)
    step = int(vals[np.argmax(cnt)])
    if step <= 0 or 86400 % step:
        raise ValueError(f"time step {step} s does not divide a day; cannot aggregate")
    return 86400 // step
_DAILY_CORE = ("precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c")
_DAILY_OTHER = ("srad_wm2", "lrad_wm2", "wind_ms", "wind2_ms", "shum_kgkg", "pres_pa")


def _check_on_missing(on_missing):
    if on_missing not in _ON_MISSING:
        raise ValueError(f"on_missing must be one of {_ON_MISSING}, got {on_missing!r}")


def _gap_message(name, dates, bad, where, source):
    idx = np.flatnonzero(bad)
    first = ", ".join(str(dates[i])[:10] for i in idx[:5])
    return (f"{source} at {where}: {name} is missing on {idx.size} of {len(bad)} "
            f"days (first: {first}). Missing values are not filled. Choose another "
            f"source or period, or pass on_missing='nan' and handle the gaps yourself.")


def _require_complete_daily(out, source, start_year, end_year, where, not_requested=(),
                            period=None):
    """Stop unless every day of the checked stretch (whole years, or period=)
    is present once and no needed variable has a gap there. Variables the caller
    said it does not need (``not_requested``) are not checked."""
    dates = np.asarray([np.datetime64(str(d)[:10]) for d in out["dates"]])
    if len(set(dates.tolist())) != dates.size:
        raise ValueError(f"{source} at {where}: duplicate dates. Nothing is filled in.")
    a0, a1 = _period_bounds(period, start_year, end_year)
    want = np.arange(a0, a1, np.timedelta64(1, "D"))
    have = set(dates.tolist())
    lost = [str(d) for d in want if d.tolist() not in have]
    if lost:
        hint = "" if period is not None else (
            " If you need only part of these years, pass period=(start, end).")
        raise ValueError(
            f"{source} at {where}: {len(lost)} of {want.size} days in {a0}..{a1 - 1} "
            f"are absent from the source (first: {', '.join(lost[:5])}). "
            f"Nothing is filled in.{hint}")
    sel = (dates >= a0) & (dates < a1)
    for name in _DAILY_CORE + _DAILY_OTHER:
        if name not in out:
            continue
        if name in not_requested:
            continue                     # the caller said it does not need it
        a = np.asarray(out[name], dtype=float)[sel]
        bad = ~np.isfinite(a)
        if bad.any():
            raise ValueError(_gap_message(name, dates[sel], bad, where, source))


def _require_complete_hourly(out, source, where, start_year, end_year, not_requested=(),
                             period=None):
    """Sub-daily counterpart: every step of the checked stretch (whole years,
    or period=) present, evenly spaced, and no gap in any variable there. Only
    a variable the caller said it does not need may be NaN on every step."""
    dates = np.asarray([np.datetime64(d, "s") for d in out["dates"]], dtype="datetime64[s]")
    step = np.timedelta64(int(out["timestep_seconds"]), "s")
    first, stop = _period_bounds(period, start_year, end_year, as_steps=True)
    sel = (dates >= first) & (dates < stop)
    d = dates[sel]
    n_want = int((stop - first) // step)
    if d.size != n_want or d[0] != first or d[-1] != stop - step \
            or not np.all(np.diff(d) == step):
        hint = "" if period is not None else (
            " If you need only part of these years, pass period=(start, end).")
        raise ValueError(
            f"{source} at {where}: {d.size} steps from {d[0] if d.size else '-'} to "
            f"{d[-1] if d.size else '-'}; {first}..{stop - step} needs {n_want} evenly "
            f"spaced steps of {step}. Nothing is filled in.{hint}")
    for name in ("precip_mm", "prec_kgm2s", "temp_c", "srad_wm2", "lrad_wm2", "wind_ms",
                 "wind2_ms", "shum_kgkg", "pres_pa"):
        if name not in out:
            continue
        if name in not_requested:
            continue                     # the caller said it does not need it
        a = np.asarray(out[name], dtype=float)[sel]
        bad = ~np.isfinite(a)
        if bad.any():
            raise ValueError(_gap_message(name, d, bad, where, source))


def _strict_daily(t, p, other, nsub, nsub_expected):
    """Daily values from the sub-daily samples of ONE day. Any missing sample
    (or a day short of samples) makes that day's value NaN; nothing is
    averaged around a gap and missing rain never becomes 0."""
    t = np.asarray(t, dtype=float)
    p = np.asarray(p, dtype=float)
    short = nsub != nsub_expected
    def full(a):
        return (not short) and a.size > 0 and bool(np.all(np.isfinite(a)))
    if full(t):
        tm, tx, tn = float(np.mean(t)), float(np.max(t)), float(np.min(t))
    else:
        tm = tx = tn = float("nan")
    if full(p):
        # CMFD prec is a rate (kg m-2 s-1); tiny negative values from the
        # product's processing are clipped, a missing value is not.
        pr = max(0.0, float(np.mean(p)) * 86400.0)
    else:
        pr = float("nan")
    oth = {}
    for k, a in other.items():
        a = np.asarray(a, dtype=float)
        oth[k] = float(np.mean(a)) if full(a) else float("nan")
    return tm, tx, tn, pr, oth


def load_hourly_forcing(source, lat, lon, start_year, end_year, forcing_dir=None,
                        on_missing="raise", variables=None, period=None):
    """Load sub-daily forcing from CMFD, MSWX, or NASA POWER.

    For models that need sub-daily timesteps (SUMMA, SHAW, WRF-Hydro, VIC hourly).
    Returns the same dict structure as load_daily_forcing but with sub-daily timestamps.

    Args:
        source: 'cmfd', 'mswx', or 'nasa_power'
        lat, lon: location (degrees)
        start_year, end_year: period (inclusive)
        forcing_dir: root directory for cmfd/mswx; optional for nasa_power

    Returns:
        dict with keys: dates, precip_mm, temp_c, srad_wm2, lrad_wm2,
                        wind_ms, shum_kgkg, pres_pa, timestep_seconds
        - CMFD/MSWX: 3-hourly (timestep_seconds=10800)
        - NASA POWER: hourly (timestep_seconds=3600)
        - precip_mm is mm per timestep (NOT rate)
        - temp_c is instantaneous (no min/max aggregation)
        on_missing: "raise" (default) stops on a missing or uneven step or a
            gap in any variable; "nan" returns gaps as NaN. Never filled.
        variables, period: as in ``load_daily_forcing`` (variables here only
            tells the check what the caller needs; everything is still read).
    """
    _check_on_missing(on_missing)
    skip = _not_requested(source, variables, _SUBDAILY_NAMES)
    source = source.lower().strip()
    if source == "nasa_power":
        out = _load_nasa_power_hourly(lat, lon, start_year, end_year)
    elif source in ("cmfd", "mswx"):
        out = _load_subdaily_netcdf(source, lat, lon, start_year, end_year, forcing_dir)
    else:
        raise ValueError(f"Unknown source '{source}'. Choose from: cmfd, mswx, nasa_power")
    if on_missing == "raise":
        _require_complete_hourly(out, source, f"({lat}, {lon})", start_year, end_year,
                                 skip, period)
    return out


def _open_nc(path):
    """Open a NetCDF file whichever HDF5 library the process loaded first.

    python_env holds two copies of the HDF5 library: one inside the netCDF4
    wheel and one inside the h5py wheel. The copy loaded first is the only one
    that can open a file afterwards. A tool that imports xarray alone gets
    h5py's copy (xarray's backend scan imports h5netcdf), so the default
    netCDF4 engine fails with "OSError: [Errno -101] NetCDF: HDF error"; a tool
    that imported netCDF4 first gets the opposite, and engine="h5netcdf" fails
    in H5DSget_num_scales. Trying h5netcdf and then the default engine opens
    the file in both cases. Measured 2026-10-02 on CMFD and MSWX files.

    Raises OSError naming both failures when neither engine opens the file.
    """
    import xarray as xr
    errors = []
    for eng in ("h5netcdf", None):
        try:
            return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
        except Exception as exc:
            errors.append("%s engine: %s: %s"
                          % (eng or "default", type(exc).__name__, exc))
    raise OSError("Cannot open NetCDF file %s (%s)" % (path, "; ".join(errors)))


def _load_subdaily_netcdf(source, lat, lon, start_year, end_year, forcing_dir):
    """Load CMFD or MSWX 3-hourly data without daily aggregation."""
    try:
        import xarray  # noqa: F401  (availability check; _open_nc does the opening)
    except ImportError:
        raise ImportError("xarray required for sub-daily loading. pip install xarray")

    if end_year < start_year:
        raise ValueError("sub-daily %s: start_year %s is after end_year %s"
                         % (source, start_year, end_year))
    fdir = forcing_dir or (CMFD_DIR if source == "cmfd" else MSWX_DIR)
    if not os.path.isdir(fdir):
        raise FileNotFoundError(f"{source.upper()} directory not found: {fdir}")

    # CMFD subdirectory/variable mapping
    if source == "cmfd":
        var_map = {
            "temp": ("Temp", "temp"),
            "prec": ("Prec", "prec"),
            "srad": ("SRad", "srad"),
            "lrad": ("LRad", "lrad"),
            "wind": ("Wind", "wind"),
            "shum": ("SHum", "shum"),
            "pres": ("Pres", "pres"),
        }
        ts_seconds = 10800  # 3-hourly
    else:
        var_map = {
            "temp": ("Tair", "Tair"),
            "prec": ("P", "P"),
            "srad": ("SWd", "SWd"),
            "lrad": ("LWd", "LWd"),
            "wind": ("wind", "Wind"),
            "shum": ("spechum", "spechum"),
            "pres": ("Pres", "Pres"),
        }
        ts_seconds = 10800

    import glob as globmod
    all_dates = []
    all_vars = {k: [] for k in var_map}

    if source == "mswx":
        # MSWX ships ANNUAL files (e.g. Tair/Tair_1980.nc), NOT monthly. Read the
        # whole year per variable, select the nearest point, and use the file's
        # own `time` coordinate for timestamps. (The monthly-glob path below is
        # CMFD-specific and matches nothing for MSWX -> previously returned 0 steps.)
        import pandas as _pd
        for year in range(start_year, end_year + 1):
            year_data = {}
            time_vals = None
            for var_key, (subdir, prefix) in var_map.items():
                fpath = os.path.join(fdir, subdir, f"{prefix}_{year}.nc")
                if not os.path.isfile(fpath):
                    raise FileNotFoundError(f"MSWX file not found: {fpath}")
                _mswx_check_time(fpath, year)      # every variable, not only the first
                ds = _open_nc(fpath)
                dvar = list(ds.data_vars)
                lat_dim = "lat" if "lat" in ds.dims else "latitude"
                lon_dim = "lon" if "lon" in ds.dims else "longitude"
                year_data[var_key] = ds[dvar[0]].sel(
                    **{lat_dim: lat, lon_dim: lon}, method="nearest"
                ).values
                if time_vals is None and "time" in ds:
                    time_vals = ds["time"].values
                ds.close()
            n_steps = len(year_data["temp"])
            # A part-filled year (2026 today) has a different number of steps
            # per variable; padding the short ones with NaN hid that.
            short = {k: len(v) for k, v in year_data.items() if len(v) != n_steps}
            if short:
                raise ValueError(
                    "MSWX sub-daily %d: variables differ in length (temp %d steps; "
                    "%s). The year is not complete for every variable."
                    % (year, n_steps, ", ".join("%s %d" % kv for kv in sorted(short.items()))))
            for i in range(n_steps):
                if time_vals is not None:
                    all_dates.append(_pd.Timestamp(time_vals[i]).to_pydatetime())
                else:
                    all_dates.append(datetime(year, 1, 1) + timedelta(hours=3 * i))
                for var_key in var_map:
                    v = year_data.get(var_key)
                    all_vars[var_key].append(float(v[i]) if v is not None and i < len(v) else np.nan)
        # MSWX units: Tair already degC, P already mm/3hr, Pres already Pa.
        return {
            "dates": np.array(all_dates, dtype="datetime64[s]"),
            "precip_mm": np.maximum(np.array(all_vars["prec"]), 0),
            "temp_c": np.array(all_vars["temp"]),
            "srad_wm2": np.array(all_vars["srad"]),
            "lrad_wm2": np.array(all_vars["lrad"]),
            "wind_ms": np.array(all_vars["wind"]),
            "shum_kgkg": np.array(all_vars["shum"]),
            "pres_pa": np.array(all_vars["pres"]),
            "timestep_seconds": ts_seconds,
        }

    # Find every monthly file first, so a wrong folder or a year outside the
    # store stops here with the missing names instead of returning an empty or
    # gap-filled series (an empty one used to surface two tools later as
    # "zero-size array to reduction operation").
    missing_dirs = [sub for sub, _ in var_map.values()
                    if not os.path.isdir(os.path.join(fdir, sub))]
    if missing_dirs:
        raise FileNotFoundError(
            "CMFD sub-daily: %s has no %s folder(s). forcing_dir must be the "
            "folder that directly holds Temp/, Prec/, SRad/, LRad/, Wind/, "
            "SHum/ and Pres/." % (fdir, ", ".join(missing_dirs)))
    month_files, missing = {}, []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            for var_key, (subdir, prefix) in var_map.items():
                files = sorted(globmod.glob(
                    os.path.join(fdir, subdir, "*_%d%02d.nc" % (year, month))))
                if files:
                    month_files[(year, month, var_key)] = files[0]
                else:
                    missing.append("%s/*_%d%02d.nc" % (subdir, year, month))
    if missing:
        raise FileNotFoundError(
            "CMFD sub-daily: %d of %d monthly files not found under %s for "
            "%d-%d (first: %s). Nothing was loaded."
            % (len(missing), len(missing) + len(month_files), fdir,
               start_year, end_year, ", ".join(missing[:4])))

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            month_data, month_times = {}, {}
            for var_key, (subdir, prefix) in var_map.items():
                fpath = month_files[(year, month, var_key)]
                ds = _open_nc(fpath)
                dvar = prefix if prefix in ds.data_vars else list(ds.data_vars)[0]
                lats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                lons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                li = int(np.argmin(np.abs(lats - lat)))
                lo = int(np.argmin(np.abs(lons - lon)))
                month_data[var_key] = ds[dvar][:, li, lo].values
                month_times[var_key] = (np.asarray(ds["time"].values)
                                        if "time" in ds.variables else None)
                ds.close()

            # The file's own time coordinate must be every 3 h from the first of
            # the month to its last step, for EVERY variable; dates are taken
            # from it, never generated from the record position.
            nd = (datetime(year + (month == 12), month % 12 + 1, 1) - datetime(year, month, 1)).days
            want = (np.datetime64(f"{year}-{month:02d}-01T00:00:00")
                    + np.arange(nd * 8) * np.timedelta64(ts_seconds, "s"))
            for var_key in var_map:
                _same_axis(want, month_times[var_key],
                           "CMFD sub-daily %d-%02d %s (%s)" % (
                               year, month, var_key, month_files[(year, month, var_key)]))
                if len(month_data[var_key]) != want.size:
                    raise ValueError("CMFD sub-daily %d-%02d: %s has %d values for %d times"
                                     % (year, month, var_key, len(month_data[var_key]), want.size))
            for i in range(want.size):
                all_dates.append(want[i].astype("datetime64[s]").astype(datetime))
                for var_key in var_map:
                    all_vars[var_key].append(float(month_data[var_key][i]))

    # Unit conversions
    temp = np.array(all_vars["temp"])
    if source == "cmfd":
        temp = temp - 273.15  # K → °C
    prec = np.array(all_vars["prec"])
    if source == "cmfd":
        prec = prec * ts_seconds  # kg/m²/s → mm per timestep

    return {
        "dates": np.array(all_dates, dtype="datetime64[s]"),
        "precip_mm": np.maximum(prec, 0),
        "temp_c": temp,
        "srad_wm2": np.array(all_vars["srad"]),
        "lrad_wm2": np.array(all_vars["lrad"]),
        "wind_ms": np.array(all_vars["wind"]),
        "shum_kgkg": np.array(all_vars["shum"]),
        "pres_pa": np.array(all_vars["pres"]),
        "timestep_seconds": ts_seconds,
    }


# Divisor that turns one hourly PRECTOTCORR value into mm fallen in that hour,
# keyed by the unit the response itself declares.
#
# The hourly API changed. Until at least 2026-06 each hourly value was a mm/day
# RATE (a .obs built here on 2026-06-08 for 51.1722 N, -115.5718 E starts
# 2005-01-01 with 0.045, 0.050, 0.033 mm = raw 1.08, 1.20, 0.79 divided by 24).
# On 2026-10-02 (API v2.10.2) the same hours come back as 0.05, 0.05, 0.03, the
# response labels them "mm/hour", and the January 2005 sum of the hourly values
# (66.42) equals the daily product's sum (66.24). Dividing those by 24 gave a
# precipitation total 24 times too small (41 mm in two years at 49.17 N,
# 125.23 E) with no error anywhere.
_NASA_POWER_HOURLY_PRECIP_DIVISOR = {
    "mm/hour": 1.0, "mm/hr": 1.0, "mm/h": 1.0, "mm hour-1": 1.0,
    "mm/day": 24.0, "mm day-1": 24.0,
}


def _nasa_power_hourly_precip_divisor(data, year):
    """Divisor for hourly PRECTOTCORR, from the units the response declares.

    Fails closed: a missing or unknown unit raises instead of guessing, because
    a wrong guess is a silent factor of 24 in precipitation.
    """
    units = str((data.get("parameters") or {}).get("PRECTOTCORR", {}).get("units", ""))
    key = " ".join(units.strip().lower().split())
    if key not in _NASA_POWER_HOURLY_PRECIP_DIVISOR:
        raise RuntimeError(
            f"NASA POWER hourly {year}: PRECTOTCORR units are {units!r}; expected "
            f"one of {sorted(_NASA_POWER_HOURLY_PRECIP_DIVISOR)}. Refusing to guess "
            f"between mm/hour and a mm/day rate (a factor of 24).")
    return _NASA_POWER_HOURLY_PRECIP_DIVISOR[key], units


def _nasa_power_check_hourly_against_daily(session, lat, lon, year, hourly_sum_mm):
    """Compare one year's hourly precipitation total with the daily product.

    The unit label is trusted for the conversion; this is the check that the
    label and the values still agree. It raises when the two totals differ by
    more than a factor of 2 (a unit error is a factor of 24). If the daily
    request itself fails the check is skipped with a warning.
    """
    try:
        resp = session.get(NASA_POWER_DAILY_URL, params={
            "start": f"{year}0101", "end": f"{year}1231",
            "latitude": lat, "longitude": lon, "community": "RE",
            "parameters": "PRECTOTCORR", "format": "JSON", "header": "false",
        }, timeout=120)
        resp.raise_for_status()
        daily = resp.json()["properties"]["parameter"]["PRECTOTCORR"]
        daily_sum = float(sum(v for v in daily.values() if v is not None and v > -900))
    except Exception as exc:  # network / format trouble: do not block the load
        warnings.warn(f"NASA POWER {year}: could not cross-check hourly precipitation "
                      f"against the daily product ({exc}); units label trusted.")
        return None
    if daily_sum < 5.0 or not np.isfinite(hourly_sum_mm):
        return None  # too dry to judge a ratio
    ratio = hourly_sum_mm / daily_sum
    if not (0.5 <= ratio <= 2.0):
        raise RuntimeError(
            f"NASA POWER {year} at ({lat}, {lon}): hourly precipitation sums to "
            f"{hourly_sum_mm:.1f} mm but the daily product sums to {daily_sum:.1f} mm "
            f"(ratio {ratio:.3f}). The hourly unit label and the values disagree; "
            f"refusing to return precipitation that is off by this factor.")
    return ratio


def _load_nasa_power_hourly(lat, lon, start_year, end_year):
    """Load NASA POWER hourly data WITHOUT daily aggregation."""
    try:
        import requests
    except ImportError:
        raise ImportError("requests required for NASA POWER. pip install requests")

    all_dates, all_temp, all_prec, all_srad = [], [], [], []
    all_lrad, all_wind, all_shum, all_pres = [], [], [], []
    all_wind2 = []

    for year in range(start_year, end_year + 1):
        params = {
            "start": f"{year}0101", "end": f"{year}1231",
            "latitude": lat, "longitude": lon,
            "community": "RE", "parameters": NASA_POWER_PARAMS,
            "format": "JSON", "header": "false", "time-standard": "UTC",
        }
        print(f"  Fetching NASA POWER hourly {year} for ({lat}, {lon})...", flush=True)
        session = requests.Session()
        session.trust_env = False
        resp = session.get(NASA_POWER_URL, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        if "properties" not in data or "parameter" not in data["properties"]:
            raise RuntimeError(f"NASA POWER API error for {year}")

        pd = data["properties"]["parameter"]
        t2m = pd.get("T2M", {})
        prec = pd.get("PRECTOTCORR", {})
        prec_div, prec_units = _nasa_power_hourly_precip_divisor(data, year)
        _year_start = len(all_prec)
        swd = pd.get("ALLSKY_SFC_SW_DWN", {})
        lwd = pd.get("ALLSKY_SFC_LW_DWN", {})
        ws = pd.get("WS2M", {})
        ws10 = pd.get("WS10M", {})
        qv = pd.get("QV2M", {})
        ps = pd.get("PS", {})

        _fill = -999.0
        for key in sorted(t2m.keys()):
            dt = datetime.strptime(key, "%Y%m%d%H")
            all_dates.append(dt)

            def _v(src, k):
                v = src.get(k, _fill)
                return float(v) if v != _fill and v is not None else np.nan

            all_temp.append(_v(t2m, key))
            # mm fallen in this hour; the divisor follows the declared unit
            # (see _NASA_POWER_HOURLY_PRECIP_DIVISOR)
            _pv = _v(prec, key) / prec_div
            all_prec.append(max(0.0, _pv) if np.isfinite(_pv) else np.nan)
            all_srad.append(_v(swd, key))  # Already W/m²
            all_lrad.append(_v(lwd, key))
            # wind_ms is the 10 m anemometer wind, exactly as the daily loader
            # does. A missing 10 m value stays missing; the 2 m wind is a
            # different quantity and is returned only as wind2_ms.
            all_wind2.append(_v(ws, key))
            all_wind.append(_v(ws10, key))
            all_shum.append(_v(qv, key) / 1000.0)  # g/kg → kg/kg
            all_pres.append(_v(ps, key) * 1000.0)   # kPa → Pa

        if year == start_year:
            # one extra small request per load: do the label and the values agree?
            _ratio = _nasa_power_check_hourly_against_daily(
                session, lat, lon, year, float(np.nansum(all_prec[_year_start:])))
            print(f"  NASA POWER hourly PRECTOTCORR units: {prec_units} (divisor "
                  f"{prec_div:g}); hourly/daily total {year}: "
                  f"{'not checked' if _ratio is None else f'{_ratio:.3f}'}", flush=True)

    # wind_height_m tells a caller which measurement height `wind_ms` is at, so
    # models that need it (FSM2 zU, SUMMA mHeight, ...) do not have to guess.
    wind_height = 10.0

    return {
        "dates": np.array(all_dates, dtype="datetime64[s]"),
        "precip_mm": np.array(all_prec, dtype=np.float64),
        "temp_c": np.array(all_temp, dtype=np.float64),
        "srad_wm2": np.array(all_srad, dtype=np.float64),
        "lrad_wm2": np.array(all_lrad, dtype=np.float64),
        "wind_ms": np.array(all_wind, dtype=np.float64),
        "wind2_ms": np.array(all_wind2, dtype=np.float64),
        "wind_height_m": wind_height,
        "shum_kgkg": np.array(all_shum, dtype=np.float64),
        "pres_pa": np.array(all_pres, dtype=np.float64),
        "timestep_seconds": 3600,
    }


# ---------------------------------------------------------------------------
# CMFD
# ---------------------------------------------------------------------------
def _load_cmfd(lat, lon, start_year, end_year, forcing_dir):
    """Load CMFD data at a point, aggregate to daily.

    Handles two on-disk layouts transparently:
      (A) legacy 3-hourly subdir layout:
          {forcing_dir}/{VarName}/{varname}_CMFD_*_{YYYYMM}.nc  (monthly files)
      (B) CMFD V0200 flat layout (current primary, Data_forcing_01dy_010deg and
          Data_forcing_03hr_010deg):
          {forcing_dir}/{varname}_CMFD_V0200_*_{YYYYMM}-{YYYYMM}.nc
          (one flat file per variable per YEAR, no subdirs)

    Variables: temp (K), prec (kg/m²/s), srad (W/m²), wind (m/s),
               shum (kg/kg), pres (Pa).

    The V0200 NetCDF files only open with the h5netcdf engine on this stack
    (the bundled netCDF4 build raises 'NetCDF: HDF error'); we try h5netcdf
    first and fall back to the default engine for the legacy layout.

    AREAL (basin-mean) MODE: ``lat`` and ``lon`` may be equal-length sequences
    of catchment grid-cell centres instead of scalars. Every returned series is
    then the cos(latitude)-weighted areal mean over those cells — exactly what a
    lumped conceptual model (HBV, GR4J, HBV-light, TOPMODEL) needs as input.
    Sampling a single outlet pixel for a large basin is a physical error, not a
    convenience shortcut. In areal mode the full (time, lat, lon) slab is read
    once per variable-year and indexed in memory, which is far cheaper than
    N_points separate chunked point reads.
    """
    import glob
    import xarray as xr

    lat_arr = np.atleast_1d(np.asarray(lat, dtype=float))
    lon_arr = np.atleast_1d(np.asarray(lon, dtype=float))
    if lat_arr.size != lon_arr.size:
        raise ValueError(f"lat/lon length mismatch: {lat_arr.size} vs {lon_arr.size}")
    areal = lat_arr.size > 1

    nodata_cells = set()

    def _areal_mean(da, lats, lons):
        """cos(lat)-weighted mean over the requested cells.

        A cell with no value at ANY step of the file (outside the CMFD land
        grid) is left out and counted in ``cmfd_cells_without_data``. A cell
        missing at only SOME steps makes those steps NaN: the other cells are
        not allowed to stand in for it."""
        lis = np.abs(lats[None, :] - lat_arr[:, None]).argmin(axis=1)
        los = np.abs(lons[None, :] - lon_arr[:, None]).argmin(axis=1)
        full = np.asarray(da.values)                       # (time, lat, lon)
        pts = full[:, lis, los].astype(float)              # (time, npoints)
        w = np.cos(np.radians(np.asarray(lats, dtype=float)[lis]))
        never = ~np.isfinite(pts).any(axis=0)
        nodata_cells.update(int(i) for i in np.flatnonzero(never))
        use = ~never
        if not use.any():
            return np.full(pts.shape[0], np.nan)
        pu, wu = pts[:, use], w[use]
        return (pu * wu[None, :]).sum(axis=1) / wu.sum()   # NaN if any used cell is NaN

    fdir = forcing_dir or CMFD_DIR
    if not os.path.isdir(fdir):
        raise FileNotFoundError(f"CMFD directory not found: {fdir}")

    var_map = {
        "temp": ("Temp", "temp"),
        "prec": ("Prec", "prec"),
        "srad": ("SRad", "srad"),
        "lrad": ("LRad", "lrad"),
        "wind": ("Wind", "wind"),
        "shum": ("SHum", "shum"),
        "pres": ("Pres", "pres"),
    }

    def _open(path):
        for eng in ("h5netcdf", None):
            try:
                return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
            except Exception:
                continue
        return xr.open_dataset(path)

    def _find_files(key, subdir, year):
        # The year token MUST be anchored to the YYYYMM stamp at the end of the
        # filename. A bare f"*{year}*.nc" also matches the year as a SUBSTRING of
        # another stamp: '*2003*' matches '..._202003.nc' (Mar 2020), so asking
        # for 2003 silently concatenated 31 days of 2020 data onto the series
        # (396 days in a 365-day year). This corrupted every year 2001-2012
        # whenever the 2020 monthly files were present. Anchor on '_YYYYMM'.
        #
        # (A) legacy/3-hourly subdir monthly layout: <var>_..._YYYYMM.nc
        files = sorted(glob.glob(os.path.join(fdir, subdir, f"*_{year}[01][0-9].nc")))
        if files:
            return files
        # (B) V0200 flat layout: one file per variable per year, <var>_..._YYYYMM-YYYYMM.nc
        files = sorted(glob.glob(
            os.path.join(fdir, f"{key}_*_{year}[01][0-9]-{year}[01][0-9].nc")))
        if files:
            return files
        # (C) last resort: unanchored, but filter to stamps that really are this year
        cand = sorted(glob.glob(os.path.join(fdir, f"{key}_*{year}*.nc")))
        return [f for f in cand
                if re.search(rf"_{year}(?:[01][0-9])?(?:[-_.]|$)", os.path.basename(f))]

    all_dates, out = [], {k: [] for k in (
        "precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c",
        "srad_wm2", "lrad_wm2", "wind_ms", "shum_kgkg", "pres_pa",
    )}

    for year in range(start_year, end_year + 1):
        year_series, year_times = {}, None
        for key, (subdir, vname) in var_map.items():
            files = _find_files(key, subdir, year)
            if not files:
                continue
            arrs, tlist = [], []
            for fp in files:
                ds = _open(fp)
                actual_var = vname
                if actual_var not in ds.data_vars:
                    cand = [v for v in ds.data_vars if vname in v.lower()]
                    if not cand:
                        ds.close()
                        continue
                    actual_var = cand[0]
                # Coordinate names vary: lat/lon, latitude/longitude, or y/x
                # (the Huai CMFD 03hr tiles label dims y[lat]/x[lon]).
                lat_name = next((c for c in ("lat", "latitude", "y") if c in ds.coords), None)
                lon_name = next((c for c in ("lon", "longitude", "x") if c in ds.coords), None)
                if lat_name is None or lon_name is None:
                    ds.close()
                    continue
                lats = ds[lat_name].values
                lons = ds[lon_name].values
                if areal:
                    arrs.append(_areal_mean(ds[actual_var], lats, lons))
                else:
                    li = int(np.argmin(np.abs(lats - lat)))
                    lo = int(np.argmin(np.abs(lons - lon)))
                    arrs.append(ds[actual_var][:, li, lo].values.astype(float))
                if "time" in ds.variables:
                    tlist.append(np.asarray(ds["time"].values))
                ds.close()
            if not arrs:
                continue
            year_series[key] = np.concatenate(arrs)
            t_key = np.concatenate(tlist) if len(tlist) == len(arrs) else None
            if t_key is None or len(t_key) != year_series[key].shape[0]:
                raise ValueError(f"CMFD {key} {year}: time coordinate missing or not matching "
                                 f"its data; the calendar cannot be verified")
            if year_times is None:
                year_times = t_key
            else:
                _same_axis(year_times, t_key, f"CMFD {key} {year}")

        if "temp" not in year_series or year_times is None:
            continue
        _check_regular_year(year_times, year, f"CMFD {year}")

        times = np.asarray(year_times, dtype="datetime64[s]")
        days_np = times.astype("datetime64[D]")
        udays, counts = np.unique(days_np, return_counts=True)
        nsub_expected = _samples_per_day(times)            # 8 for 3-hourly, 1 for daily
        _other = (("srad", "srad_wm2"), ("lrad", "lrad_wm2"), ("wind", "wind_ms"),
                  ("shum", "shum_kgkg"), ("pres", "pres_pa"))
        for day, nsub in zip(udays, counts):
            sel = days_np == day
            t = year_series["temp"][sel] - 273.15
            p = year_series["prec"][sel] if "prec" in year_series else np.array([])
            oth = {ok: year_series[rk][sel] for rk, ok in _other if rk in year_series}
            tm, tx, tn, pr, ov = _strict_daily(t, p, oth, int(nsub), nsub_expected)
            all_dates.append(day)
            out["temp_mean_c"].append(tm)
            out["temp_max_c"].append(tx)
            out["temp_min_c"].append(tn)
            out["precip_mm"].append(pr)
            for _rk, ok in _other:
                out[ok].append(ov.get(ok, float("nan")))

    if not all_dates:
        raise FileNotFoundError(
            f"No CMFD data loaded from {fdir} for {start_year}-{end_year} at ({lat}, {lon})."
        )

    # Guard: every returned day must fall inside the requested years and appear
    # exactly once. Catches file-glob leakage (a stamp from another year) before
    # it silently reaches a model's forcing file.
    _yrs = np.asarray([int(str(d)[:4]) for d in all_dates])
    if _yrs.min() < start_year or _yrs.max() > end_year:
        bad = sorted({int(y) for y in _yrs if y < start_year or y > end_year})
        raise ValueError(
            f"CMFD loader returned days outside {start_year}-{end_year}: {bad}. "
            "A monthly file from another year matched the year glob."
        )
    if len(set(map(str, all_dates))) != len(all_dates):
        raise ValueError("CMFD loader returned duplicate dates (overlapping files).")

    from datetime import datetime as dt
    dates_py = [
        dt.utcfromtimestamp(int(d.astype("datetime64[s]").astype("int64")))
        for d in all_dates
    ]
    res = {"dates": dates_py, **{k: list(v) for k, v in out.items()}}
    if areal:
        res["cmfd_cells_without_data"] = len(nodata_cells)
        res["cmfd_cells_requested"] = int(lat_arr.size)
    return res


def _load_cmfd_points(latlons, start_year, end_year, forcing_dir):
    """Read CMFD once per file and extract every requested point from it.

    Same aggregation rules as `_load_cmfd` (K->C, kg/m2/s->mm/day, daily
    max/min from the sub-daily samples), but amortised over N points.
    """
    import glob
    import xarray as xr

    fdir = forcing_dir or CMFD_DIR
    if not os.path.isdir(fdir):
        raise FileNotFoundError(f"CMFD directory not found: {fdir}")

    lat_arr = np.asarray([p[0] for p in latlons], dtype=float)
    lon_arr = np.asarray([p[1] for p in latlons], dtype=float)
    npts = lat_arr.size

    var_map = {
        "temp": ("Temp", "temp"), "prec": ("Prec", "prec"),
        "srad": ("SRad", "srad"), "lrad": ("LRad", "lrad"),
        "wind": ("Wind", "wind"),
        "shum": ("SHum", "shum"), "pres": ("Pres", "pres"),
    }

    def _open(path):
        for eng in ("h5netcdf", None):
            try:
                return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
            except Exception:
                continue
        return xr.open_dataset(path)

    def _find_files(key, subdir, year):
        files = sorted(glob.glob(os.path.join(fdir, subdir, f"*_{year}[01][0-9].nc")))
        if files:
            return files
        files = sorted(glob.glob(
            os.path.join(fdir, f"{key}_*_{year}[01][0-9]-{year}[01][0-9].nc")))
        if files:
            return files
        cand = sorted(glob.glob(os.path.join(fdir, f"{key}_*{year}*.nc")))
        return [f for f in cand
                if re.search(rf"_{year}(?:[01][0-9])?(?:[-_.]|$)", os.path.basename(f))]

    keys = ("precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c",
            "srad_wm2", "lrad_wm2", "wind_ms", "shum_kgkg", "pres_pa")
    all_dates = []
    out = [{k: [] for k in keys} for _ in range(npts)]

    for year in range(start_year, end_year + 1):
        year_series, year_times = {}, None
        for key, (subdir, vname) in var_map.items():
            files = _find_files(key, subdir, year)
            if not files:
                continue
            arrs, tlist = [], []
            for fp in files:
                ds = _open(fp)
                actual_var = vname
                if actual_var not in ds.data_vars:
                    cand = [v for v in ds.data_vars if vname in v.lower()]
                    if not cand:
                        ds.close()
                        continue
                    actual_var = cand[0]
                lat_name = next((c for c in ("lat", "latitude", "y") if c in ds.coords), None)
                lon_name = next((c for c in ("lon", "longitude", "x") if c in ds.coords), None)
                if lat_name is None or lon_name is None:
                    ds.close()
                    continue
                lats, lons = ds[lat_name].values, ds[lon_name].values
                lis = np.abs(lats[None, :] - lat_arr[:, None]).argmin(axis=1)
                los = np.abs(lons[None, :] - lon_arr[:, None]).argmin(axis=1)
                full = np.asarray(ds[actual_var].values)      # one decompression
                arrs.append(full[:, lis, los].astype(float))  # (time, npts)
                if "time" in ds.variables:
                    tlist.append(np.asarray(ds["time"].values))
                ds.close()
            if not arrs:
                continue
            year_series[key] = np.concatenate(arrs, axis=0)
            t_key = np.concatenate(tlist) if len(tlist) == len(arrs) else None
            if t_key is None or len(t_key) != year_series[key].shape[0]:
                raise ValueError(f"CMFD {key} {year}: time coordinate missing or not matching "
                                 f"its data; the calendar cannot be verified")
            if year_times is None:
                year_times = t_key
            else:
                _same_axis(year_times, t_key, f"CMFD {key} {year}")

        if "temp" not in year_series or year_times is None:
            continue
        _check_regular_year(year_times, year, f"CMFD {year}")

        days_np = np.asarray(year_times, dtype="datetime64[s]").astype("datetime64[D]")
        udays, counts = np.unique(days_np, return_counts=True)
        nsub_expected = _samples_per_day(year_times)
        _other = (("srad", "srad_wm2"), ("lrad", "lrad_wm2"), ("wind", "wind_ms"),
                  ("shum", "shum_kgkg"), ("pres", "pres_pa"))
        for day, nsub in zip(udays, counts):
            sel = days_np == day
            all_dates.append(day)
            t = year_series["temp"][sel] - 273.15         # (nsub, npts)
            p = year_series["prec"][sel] if "prec" in year_series else None
            for j in range(npts):
                oth = {ok: year_series[rk][sel][:, j] for rk, ok in _other
                       if rk in year_series}
                tm, tx, tn, pr, ov = _strict_daily(
                    t[:, j], p[:, j] if p is not None else np.array([]), oth,
                    int(nsub), nsub_expected)
                out[j]["temp_mean_c"].append(tm)
                out[j]["temp_max_c"].append(tx)
                out[j]["temp_min_c"].append(tn)
                out[j]["precip_mm"].append(pr)
                for _rk, ok in _other:
                    out[j][ok].append(ov.get(ok, float("nan")))

    if not all_dates:
        raise FileNotFoundError(
            f"No CMFD data loaded from {fdir} for {start_year}-{end_year}.")
    _yrs = np.asarray([int(str(d)[:4]) for d in all_dates])
    if _yrs.min() < start_year or _yrs.max() > end_year:
        raise ValueError(f"CMFD loader returned days outside {start_year}-{end_year}.")
    if len(set(map(str, all_dates))) != len(all_dates):
        raise ValueError("CMFD loader returned duplicate dates (overlapping files).")

    from datetime import datetime as dt
    dates_py = [dt.utcfromtimestamp(int(d.astype("datetime64[s]").astype("int64")))
                for d in all_dates]
    return [{"dates": dates_py, **{k: list(v) for k, v in o.items()}} for o in out]


# ---------------------------------------------------------------------------
# MSWX
# ---------------------------------------------------------------------------
# (subdir, file prefix) for each standardised MSWX key.
_MSWX_VAR_MAP = {
    "P":       ("P",       "P"),
    "Tair":    ("Tair",    "Tair"),
    "SWd":     ("SWd",     "SWd"),
    "LWd":     ("LWd",     "LWd"),
    "Wind":    ("wind",    "Wind"),
    "spechum": ("spechum", "spechum"),
    "Pres":    ("Pres",    "Pres"),
}


def _mswx_read_box(task):
    """Read one (variable, year) 3-hourly bounding box. Runs in a subprocess.

    The MSWX annual files are chunked (1, 1800, 3600) with gzip, i.e. one
    compressed GLOBAL slab per timestep. Any spatial subset therefore costs a
    full decompression of that timestep. Reading the whole year's bounding box
    in ONE pass is the only way to amortise it -- a per-point loop pays the
    same ~76 GB decompression once per point.
    """
    import h5py
    fpath, vname, r0, r1, c0, c1 = task
    with h5py.File(fpath, "r") as f:
        dset = f[vname]
        arr = dset[:, r0:r1, c0:c1].astype(np.float32)
        fill = dset.fillvalue
    if fill is not None:
        arr[arr == fill] = np.nan
    return arr


def _same_axis(ref, other, label):
    """Every variable must carry the same time axis as the reference one; values
    are lined up by position, so a repeated, missing or shifted step in any one
    variable file would otherwise put its values on the wrong times."""
    if other is None:
        raise ValueError(f"{label}: no time coordinate; its calendar cannot be verified")
    a = np.asarray(ref).astype("datetime64[s]")
    b = np.asarray(other).astype("datetime64[s]")
    if a.shape != b.shape or not np.array_equal(a, b):
        n = min(a.size, b.size)
        k = np.flatnonzero(a[:n] != b[:n])
        where = f"first difference at {a[k[0]]} vs {b[k[0]]}" if k.size else \
            f"{b.size} steps vs {a.size}"
        raise ValueError(f"{label}: time axis differs from the reference variable "
                         f"({where}). Values are not shifted or filled.")


def _check_regular_year(times, year, label):
    """The reference time axis of a CMFD year must start at {year}-01-01 00:00
    and go up in exactly equal steps that divide a day. It may end early (a
    store that stops part-way through the year; the calendar check decides if
    that matters), but a repeated, missing or shifted step stops here: a day
    with a repeated step can still hold the expected number of records."""
    t = np.asarray(times).astype("datetime64[s]")
    if t.size == 0 or t[0] != np.datetime64(f"{year}-01-01T00:00:00"):
        raise ValueError(f"{label}: time axis starts at {t[0] if t.size else '-'}, "
                         f"not {year}-01-01 00:00")
    if t.size > 1:
        d = np.diff(t).astype("int64")
        step = int(d[0])
        if step <= 0 or 86400 % step or not np.all(d == step):
            k = int(np.flatnonzero(d != step)[0]) if np.any(d != step) else 0
            raise ValueError(f"{label}: time steps are not equal after {t[k]} "
                             f"(next {t[k + 1]}). Values are not shifted or filled.")
        last = np.datetime64(f"{year + 1}-01-01T00:00:00") - np.timedelta64(step, "s")
        if t[-1] > last:
            raise ValueError(f"{label}: time axis runs past {year} ({t[-1]})")


def _mswx_check_time(fpath, year):
    """The file's own time axis must be every 3 hours from {year}-01-01 00:00
    to the last step of the year, with no repeat and no gap. A step count alone
    is not enough: MSWX 1979 has exactly 2920 steps but a repeated step and a
    gap; 2011 has a repeated step. Nothing is cut or filled."""
    import h5py
    with h5py.File(fpath, "r") as f:
        if "time" not in f:
            raise ValueError(f"MSWX {fpath}: no time variable; the calendar cannot be verified")
        v = np.asarray(f["time"][:], dtype=np.float64)
        units = f["time"].attrs.get("units", b"")
    units = units.decode() if isinstance(units, bytes) else str(units)
    word, _, base = units.partition(" since ")
    scale = {"days": 1.0, "hours": 1.0 / 24.0, "minutes": 1.0 / 1440.0,
             "seconds": 1.0 / 86400.0}.get(word.strip().lower())
    if scale is None or not base:
        raise ValueError(f"MSWX {fpath}: time units {units!r} not understood")
    b = base.strip().split()
    ymd = [int(x) for x in b[0].split("-")]
    hms = [float(x) for x in (b[1].split(":") if len(b) > 1 else ["0"])] + [0.0, 0.0]
    t0 = datetime(ymd[0], ymd[1], ymd[2]) + timedelta(hours=hms[0], minutes=hms[1], seconds=hms[2])
    days = v * scale
    ndays = (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days
    want = ((datetime(year, 1, 1) - t0).total_seconds() / 86400.0
            + np.arange(ndays * 8) * 0.125)
    if days.size != want.size or not np.allclose(days, want, rtol=0, atol=1e-6):
        n = min(days.size, want.size)
        bad = np.flatnonzero(~np.isclose(days[:n], want[:n], rtol=0, atol=1e-6))
        first = (t0 + timedelta(days=float(days[bad[0]]))) if bad.size else None
        raise ValueError(
            f"MSWX {year} ({os.path.basename(fpath)}): time axis has {days.size} steps, "
            f"expected {want.size} every 3 h from {year}-01-01 00:00"
            + (f"; first wrong step {first:%Y-%m-%d %H:%M}" if first else "")
            + ". A faulty year file is not cut or filled.")


def _mswx_grid(fdir, year):
    """Return (lat, lon) coordinate vectors of the MSWX grid."""
    import h5py
    fpath = os.path.join(fdir, "P", f"P_{year}.nc")
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"MSWX file not found: {fpath}")
    with h5py.File(fpath, "r") as f:
        return np.asarray(f["lat"][:]), np.asarray(f["lon"][:])


def _mswx_varname(fpath):
    """First non-coordinate variable in an MSWX annual file."""
    import h5py
    with h5py.File(fpath, "r") as f:
        for k, v in f.items():
            if k in ("lat", "lon", "time"):
                continue
            if getattr(v, "shape", None) and len(v.shape) == 3:
                return k
    raise ValueError(f"No 3-D data variable in {fpath}")


def load_mswx_year_box(forcing_dir, year, var_subdir, lats, lons):
    """Read one MSWX (variable, year) over the bounding box of a 2-D cell grid
    in ONE decompression pass, nearest-neighbor mapped onto the cells.

    The annual MSWX files are gzip-chunked one GLOBAL slab per timestep, so
    any spatial subset costs a full-file decompression; reading the whole
    year's box at once is the only efficient access (same rationale as
    _load_mswx_points). Added 2026-08-23 for gridded consumers (ParFlow/CLM
    forcing conversion) so model KIs stop reimplementing this read.

    Parameters: lats/lons are equal-shape 2-D arrays of cell-center
    coordinates. Returns (arr, units): arr float32 with shape
    (n_source_steps,) + lats.shape in NATIVE store units (caller converts;
    3-hourly store => 2920/2928 steps), units = the file's own units attr.
    Raises on a missing file or NaN cells -- no silent fill.
    """
    import h5py
    lats = np.asarray(lats)
    lons = np.asarray(lons)
    fpath = os.path.join(forcing_dir, var_subdir, f"{var_subdir}_{year}.nc")
    if not os.path.isfile(fpath):
        raise FileNotFoundError(f"MSWX source missing: {fpath}")
    vname = _mswx_varname(fpath)
    _mswx_check_time(fpath, year)
    with h5py.File(fpath, "r") as f:
        units = f[vname].attrs.get("units", b"")
        units = units.decode() if isinstance(units, bytes) else str(units)
    glat, glon = _mswx_grid(forcing_dir, year)
    r_idx = np.abs(glat[None, :] - lats.ravel()[:, None]).argmin(axis=1)
    c_idx = np.abs(glon[None, :] - lons.ravel()[:, None]).argmin(axis=1)
    r0, r1 = int(r_idx.min()), int(r_idx.max()) + 1
    c0, c1 = int(c_idx.min()), int(c_idx.max()) + 1
    box = _mswx_read_box((fpath, vname, r0, r1, c0, c1))
    ndays = (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days
    if box.shape[0] != ndays * 8:
        raise ValueError(f"MSWX {var_subdir} {year}: {box.shape[0]} data steps, "
                         f"expected {ndays * 8}; not cut or filled")
    ext = box[:, r_idx - r0, c_idx - c0].reshape((box.shape[0],) + lats.shape)
    if np.isnan(ext).any():
        raise ValueError(
            f"MSWX {var_subdir} {year}: {int(np.isnan(ext).sum())} NaN cells "
            "after extraction -- domain touches fill-value cells; refusing silent fill")
    return ext, units


def _load_mswx_points(latlons, start_year, end_year, forcing_dir=None,
                      variables=None):
    """Load daily MSWX forcing at MANY points in one decompression pass.

    Semantically identical to calling ``_load_mswx`` once per point, but reads
    each (variable, year) file ONCE over the bounding box of all requested
    points instead of once per point. Mirrors ``_load_cmfd_points``.

    netCDF/HDF5 is not thread-safe, so the per-variable reads are fanned out
    across PROCESSES, never threads.

    ``variables`` optionally restricts which MSWX variables are actually READ
    (keys of ``_MSWX_VAR_MAP``: P, Tair, SWd, LWd, Wind, spechum, Pres).  Every
    output key is still present, but an unread variable is returned as NaN.
    This matters a lot: the annual files are gzip-chunked ONE GLOBAL SLAB PER
    TIMESTEP, so each (variable, year) costs a full ~76 GB decompression
    (~5 min for P, more for Tair) no matter how few cells are wanted.  A
    rainfall-runoff model that only needs precipitation and temperature (e.g.
    PyTOPKAPI with Hargreaves ET) therefore runs 4x faster by passing
    ``variables=("P", "Tair")``.  ``P`` is always read — it defines the time
    axis.

    Returns a list of forcing dicts, in the same order as ``latlons``.
    """
    from concurrent.futures import ProcessPoolExecutor

    fdir = forcing_dir or MSWX_DIR
    if not os.path.isdir(fdir):
        raise FileNotFoundError(f"MSWX directory not found: {fdir}")

    latlons = [(float(a), float(b)) for a, b in latlons]
    npts = len(latlons)
    req_lat = np.array([a for a, _ in latlons])
    req_lon = np.array([b for _, b in latlons])

    import xarray as xr

    glat, glon = _mswx_grid(fdir, start_year)
    # Nearest global index for every requested point. Resolved through xarray's
    # own selection so this batched path lands on EXACTLY the same cells as the
    # reference single-point `_load_mswx` (which uses `.sel(method='nearest')`).
    # A plain argmin disagrees with it for points near a cell boundary, because
    # the float32 grid spacing is not exactly 0.1 deg.
    ri = xr.DataArray(np.arange(glat.size), coords={"lat": glat}, dims="lat") \
           .sel(lat=req_lat, method="nearest").values
    ci = xr.DataArray(np.arange(glon.size), coords={"lon": glon}, dims="lon") \
           .sel(lon=req_lon, method="nearest").values
    r0, r1 = int(ri.min()), int(ri.max()) + 1
    c0, c1 = int(ci.min()), int(ci.max()) + 1
    rr, cc = ri - r0, ci - c0          # indices within the bounding box

    out = [{k: [] for k in ("precip_mm", "temp_mean_c", "temp_max_c",
                            "temp_min_c", "srad_wm2", "lrad_wm2",
                            "wind_ms", "shum_kgkg", "pres_pa")}
           for _ in range(npts)]
    all_dates = []

    if variables is None:
        keys = list(_MSWX_VAR_MAP)
    else:
        want = {str(v) for v in variables}
        keys = [k for k in _MSWX_VAR_MAP if k in want]
        if "P" not in keys:                     # P defines the time axis
            keys.insert(0, "P")

    # One (variable, year) read costs a full-year decompression, so run several
    # concurrently -- but each task materialises a (nsteps, nbox_lat, nbox_lon)
    # float32 box, so cap the concurrency by MEMORY, not by core count. A
    # single-point request has a 1x1 box (12 kB/task) and runs all-out; a
    # basin-wide box falls back to one year at a time, exactly as before.
    per_task_bytes = 2928.0 * (r1 - r0) * (c1 - c0) * 4.0
    n_conc = int(min(8, max(1, 1.5e9 // max(per_task_bytes, 1.0))))
    years_per_batch = max(1, n_conc // len(keys))
    years = list(range(start_year, end_year + 1))

    for b0 in range(0, len(years), years_per_batch):
        batch = years[b0:b0 + years_per_batch]
        tasks, tkeys = [], []
        for year in batch:
            for key in keys:
                subdir, prefix = _MSWX_VAR_MAP[key]
                fpath = os.path.join(fdir, subdir, f"{prefix}_{year}.nc")
                if not os.path.isfile(fpath):
                    raise FileNotFoundError(f"MSWX file not found: {fpath}")
                _mswx_check_time(fpath, year)
                tasks.append((fpath, _mswx_varname(fpath), r0, r1, c0, c1))
                tkeys.append((year, key))

        with ProcessPoolExecutor(max_workers=min(n_conc, len(tasks))) as ex:
            boxes = dict(zip(tkeys, ex.map(_mswx_read_box, tasks)))

        for year in batch:
            # (nsteps, nbox_lat, nbox_lon) -> (nsteps, npts)
            pts = {k: boxes.pop((year, k))[:, rr, cc] for k in keys}

            nsteps = next(iter(pts.values())).shape[0]
            ndays = (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days
            if nsteps != ndays * 8:          # MSWX is 3-hourly: 8 steps/day
                raise ValueError(
                    f"MSWX {year} has {nsteps} time steps, expected {ndays * 8} "
                    f"(8 per day). A short or faulty year file is not cut or filled.")
            sl = slice(0, ndays * 8)

            def _daily(key, how, _pts=pts, _nd=ndays, _sl=sl):
                if key not in _pts:             # not requested -> NaN column
                    return np.full((_nd, npts), np.nan, dtype=np.float64)
                a = _pts[key][_sl].reshape(_nd, 8, npts)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return how(a, axis=1)

            # np.sum / np.mean / np.max / np.min keep NaN: one missing 3-hour
            # step makes the day missing (never 0 mm, never a partial mean).
            p_d = _daily("P", np.sum)            # MSWX P is mm/3hr -> sum
            t_d = _daily("Tair", np.mean)
            tmax = _daily("Tair", np.max)
            tmin = _daily("Tair", np.min)
            sw_d = _daily("SWd", np.mean)
            lw_d = _daily("LWd", np.mean)
            wd_d = _daily("Wind", np.mean)
            sh_d = _daily("spechum", np.mean)
            pr_d = _daily("Pres", np.mean)
            del pts

            for d in range(ndays):
                all_dates.append((datetime(year, 1, 1) + timedelta(days=d))
                                 .strftime("%Y-%m-%d"))
            for i in range(npts):
                out[i]["precip_mm"].extend(p_d[:, i])
                out[i]["temp_mean_c"].extend(t_d[:, i])
                out[i]["temp_max_c"].extend(tmax[:, i])
                out[i]["temp_min_c"].extend(tmin[:, i])
                out[i]["srad_wm2"].extend(sw_d[:, i])
                out[i]["lrad_wm2"].extend(lw_d[:, i])
                out[i]["wind_ms"].extend(wd_d[:, i])
                out[i]["shum_kgkg"].extend(sh_d[:, i])
                out[i]["pres_pa"].extend(pr_d[:, i])

    dates_np = np.array([np.datetime64(d) for d in all_dates])
    return [{"dates": dates_np,
             **{k: np.asarray(v, dtype=np.float64) for k, v in o.items()}}
            for o in out]


def _load_mswx(lat, lon, start_year, end_year, forcing_dir, variables=None):
    """Load daily MSWX forcing at ONE point from the annual NetCDF files.

    MSWX directory layout:
        P/P_YYYY.nc          — precipitation (mm/3hr)
        Tair/Tair_YYYY.nc    — temperature (already deg C)
        SWd/SWd_YYYY.nc      — shortwave downward (W/m2)
        LWd/LWd_YYYY.nc      — longwave downward (W/m2)
        wind/Wind_YYYY.nc     — wind speed (m/s)
        spechum/spechum_YYYY.nc — specific humidity (kg/kg)
        Pres/Pres_YYYY.nc    — surface pressure (Pa)

    Delegates to the batched reader with a single point. That path reads each
    (variable, year) file exactly ONCE in a worker process; the previous
    single-point implementation opened every file serially in-process AND
    re-read the whole Tair file a second time just to recover Tmax/Tmin,
    which doubled the cost of the largest variable (Tair_1980.nc is 9.6 GB)
    for no information gain. Same nearest-cell selection, same output keys.

    ``variables`` optionally restricts which MSWX variables are read; unread
    ones come back as NaN. See ``_load_mswx_points``.
    """
    return _load_mswx_points([(lat, lon)], start_year, end_year, forcing_dir,
                             variables=variables)[0]


# ---------------------------------------------------------------------------
# NASA POWER
# ---------------------------------------------------------------------------
def _load_nasa_power(lat, lon, start_year, end_year):
    """Fetch DAILY data from the NASA POWER daily endpoint.

    Uses the temporal/daily/point endpoint (NOT hourly). Rationale (verified
    2026-06-08): NASA POWER HOURLY data only starts 2001-01-01 and the hourly
    endpoint returns HTTP 422 for any earlier start, whereas DAILY data goes
    back to 1981-01-01 — which is the coverage the SKILL/recipe documents. The
    daily endpoint is also one bounded request per year with no hourly
    aggregation, and returns native daily Tmin/Tmax.

    DAILY-ENDPOINT UNIT SUMMARY (from API metadata header, verified 2026-06-08):
      - PRECTOTCORR: mm/day — daily total directly (no aggregation).
      - T2M / T2M_MIN / T2M_MAX: deg C.
      - ALLSKY_SFC_SW_DWN: kW-hr/m^2/day -> W/m^2 via *1000/24 (=*41.667).
      - ALLSKY_SFC_LW_DWN: kW-hr/m^2/day -> W/m^2 via *1000/24.
      - PS: kPa -> *1000 for Pa.
      - QV2M: g/kg -> /1000 for kg/kg.
      - WS2M: m/s at 2 m.
    Fill value for missing daily values is -999.
    """
    # kW-hr/m^2/day -> W/m^2 (energy per day / seconds per day, *1000 Wh->Wh)
    _KWHD_TO_WM2 = 1000.0 / 24.0
    try:
        import requests
    except ImportError:
        raise ImportError("requests required for NASA POWER. pip install requests")

    all_dates = []
    all_precip = []
    all_tmean = []
    all_tmax = []
    all_tmin = []
    all_srad = []
    all_lrad = []
    all_wind = []
    all_wind2 = []
    all_shum = []
    all_pres = []

    _fill_val = -999.0  # NASA POWER fill value

    def _val(src, k, fill=_fill_val):
        v = src.get(k, fill)
        return float(v) if v not in (fill, None) else np.nan

    # One bounded daily request per year (1981+).
    for year in range(start_year, end_year + 1):
        params = {
            "start": f"{year}0101",
            "end": f"{year}1231",
            "latitude": lat,
            "longitude": lon,
            "community": "RE",
            "parameters": NASA_POWER_DAILY_PARAMS,
            "format": "JSON",
            "header": "false",
        }

        print(f"  Fetching NASA POWER (daily) {year} for ({lat}, {lon})...", flush=True)
        # Bypass env proxies (HTTPS_PROXY/ALL_PROXY) which break the TLS handshake
        # to power.larc.nasa.gov on this host. Matches the hourly loader (dt_015).
        session = requests.Session()
        session.trust_env = False
        resp = session.get(NASA_POWER_DAILY_URL, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        if "properties" not in data or "parameter" not in data["properties"]:
            raise RuntimeError(
                f"NASA POWER API returned unexpected format for {year}. "
                f"Check coverage/dates. Response keys: {list(data.keys())}"
            )

        params_data = data["properties"]["parameter"]

        # Daily data keyed by "YYYYMMDD" strings.
        t2m_d = params_data.get("T2M", {})
        tmin_d = params_data.get("T2M_MIN", {})
        tmax_d = params_data.get("T2M_MAX", {})
        prec_d = params_data.get("PRECTOTCORR", {})
        swd_d = params_data.get("ALLSKY_SFC_SW_DWN", {})
        lwd_d = params_data.get("ALLSKY_SFC_LW_DWN", {})
        ws_d = params_data.get("WS2M", {})
        ws10_d = params_data.get("WS10M", {})
        qv_d = params_data.get("QV2M", {})
        ps_d = params_data.get("PS", {})

        for day_key in sorted(t2m_d.keys()):
            dt = datetime.strptime(day_key, "%Y%m%d")
            all_dates.append(dt.strftime("%Y-%m-%d"))

            tmean = _val(t2m_d, day_key)
            tmin = _val(tmin_d, day_key)
            tmax = _val(tmax_d, day_key)
            all_tmean.append(tmean)
            all_tmin.append(tmin)            # missing stays missing (no Tmean stand-in)
            all_tmax.append(tmax)

            _pv = _val(prec_d, day_key)
            all_precip.append(max(0.0, _pv) if np.isfinite(_pv) else np.nan)
            # kW-hr/m^2/day -> W/m^2
            all_srad.append(_val(swd_d, day_key) * _KWHD_TO_WM2)
            all_lrad.append(_val(lwd_d, day_key) * _KWHD_TO_WM2)
            # GLM (and most surface models) expect wind at the 10 m anemometer
            # height, so wind_ms is WS10M (wind_height_m = 10). A missing 10 m
            # value stays missing: the 2 m wind is a different quantity and is
            # NOT mixed in day by day. WS2M is returned separately as wind2_ms.
            all_wind.append(_val(ws10_d, day_key))
            all_wind2.append(_val(ws_d, day_key))
            all_shum.append(_val(qv_d, day_key) / 1000.0)   # g/kg -> kg/kg
            all_pres.append(_val(ps_d, day_key) * 1000.0)   # kPa -> Pa

    dates_np = np.array([np.datetime64(d) for d in all_dates])
    srad_arr = np.array(all_srad, dtype=np.float64)

    # Sanity check: radiation should be in W/m² (daily mean ~50-300)
    srad_mean = float(np.nanmean(srad_arr))
    if srad_mean < 5.0 and srad_mean > 0:
        warnings.warn(
            f"NASA POWER: mean shortwave = {srad_mean:.2f} W/m², suspiciously low. "
            f"Daily ALLSKY_SFC_SW_DWN is kW-hr/m²/day; loader applies *1000/24 "
            f"to W/m². A low value suggests a units regression."
        )

    return {
        "dates": dates_np,
        "precip_mm": np.array(all_precip, dtype=np.float64),
        "temp_mean_c": np.array(all_tmean, dtype=np.float64),
        "temp_max_c": np.array(all_tmax, dtype=np.float64),
        "temp_min_c": np.array(all_tmin, dtype=np.float64),
        "srad_wm2": srad_arr,
        "lrad_wm2": np.array(all_lrad, dtype=np.float64),
        "wind_ms": np.array(all_wind, dtype=np.float64),
        "wind2_ms": np.array(all_wind2, dtype=np.float64),
        "wind_height_m": 10.0,
        "shum_kgkg": np.array(all_shum, dtype=np.float64),
        "pres_pa": np.array(all_pres, dtype=np.float64),
    }


def _load_gswp3(lat, lon, start_year, end_year, forcing_dir):
    """Load GSWP3-W5E5 (ISIMIP3a obsclim) daily forcing from decadal global netCDF (0.5deg, 1901-2019).
    Vars: tasmax/tasmin (K), huss (kg/kg), ps (Pa), sfcwind (m/s), pr (kg/m2/s), rsds (W/m2)."""
    import xarray as xr
    fdir = forcing_dir or GSWP3_DIR
    if not os.path.isdir(fdir):
        raise FileNotFoundError(f"GSWP3 directory not found: {fdir}")
    varmap = ["tasmax", "tasmin", "huss", "ps", "sfcwind", "pr", "rsds"]
    decs = [(a, b) for (a, b) in GSWP3_DECADES if not (b < start_year or a > end_year)]
    if not decs:
        raise ValueError(f"GSWP3 covers 1901-2019; requested {start_year}-{end_year} out of range")
    acc = {v: [] for v in varmap}
    dates = []
    for (y0, y1) in decs:
        per = {}
        t = None
        for v in varmap:
            fp = os.path.join(fdir, f"gswp3-w5e5_obsclim_{v}_global_daily_{y0}_{y1}.nc")
            if not os.path.isfile(fp):
                raise FileNotFoundError(f"GSWP3 file not found: {fp}")
            ds = xr.open_dataset(fp)
            lat_dim = "lat" if "lat" in ds.dims else "latitude"
            lon_dim = "lon" if "lon" in ds.dims else "longitude"
            sel_lon = (lon % 360) if (float(ds[lon_dim].min()) >= 0 and lon < 0) else lon
            da = ds[v].sel(**{lat_dim: lat, lon_dim: sel_lon}, method="nearest")
            per[v] = da.values
            tv = da["time"].values if "time" in da.coords else None
            if v == "tasmax":
                t = tv
            else:
                _same_axis(t, tv, f"GSWP3 {v} {y0}-{y1}")
            ds.close()
        yrs = np.array([int(str(tt)[:4]) for tt in t])
        m = (yrs >= start_year) & (yrs <= end_year)
        for v in varmap:
            acc[v].append(per[v][m])
        dates.extend([np.datetime64(str(tt)[:10]) for tt in t[m]])
    cat = {v: (np.concatenate(acc[v]) if acc[v] else np.array([])) for v in varmap}
    tmax = cat["tasmax"] - 273.15
    tmin = cat["tasmin"] - 273.15
    return {
        "dates": np.array(dates),
        "precip_mm": cat["pr"] * 86400.0,
        "temp_mean_c": (tmax + tmin) / 2.0,
        "temp_max_c": tmax,
        "temp_min_c": tmin,
        "srad_wm2": cat["rsds"],
        "wind_ms": cat["sfcwind"],
        "shum_kgkg": cat["huss"],
        "pres_pa": cat["ps"],
    }


def load_subdaily_forcing_points(source, latlons, start_year, end_year, forcing_dir=None,
                                 on_missing="raise", variables=None, period=None):
    """Multi-point loader returning NATIVE sub-daily samples (no daily collapse).

    _load_cmfd_points() reads each monthly CMFD file once, extracts every requested
    point from that single decompression, then averages the 8 sub-daily samples into
    one daily value. That collapse destroys precipitation intensity and the diurnal
    radiation cycle, which SUMMA needs (dag boundary.temporal='hourly', 3600-10800 s).
    This keeps the sub-daily axis; file discovery and point extraction are identical.

    Returns one dict per point, in RAW store units:
        dates            list[datetime], one per sub-daily step
        timestep_seconds int (10800 for CMFD 3-hourly)
        temp_c           degC        (store is K)
        prec_kgm2s       kg m-2 s-1  (store is ALREADY a rate -- do NOT divide)
        srad_wm2, lrad_wm2  W m-2
        wind_ms          m s-1
        shum_kgkg        kg/kg
        pres_pa          Pa

    on_missing, variables, period: as in ``load_hourly_forcing``, applied to
    every point. A variable file absent from the store, a missing month or a
    missing value stops the loader by default; nothing is filled in.
    """
    _check_on_missing(on_missing)
    skip = _not_requested(source, variables, _SUBDAILY_NAMES)
    if str(source).lower() != "cmfd":
        raise NotImplementedError(
            "load_subdaily_forcing_points supports source='cmfd' only, got %r" % (source,))
    res = _load_cmfd_points_subdaily(latlons, start_year, end_year, forcing_dir)
    if on_missing == "raise":
        for (la, lo), o in zip(latlons, res):
            _require_complete_hourly(o, "cmfd", f"({float(la)}, {float(lo)})",
                                     start_year, end_year, skip, period)
    return res


def _load_cmfd_points_subdaily(latlons, start_year, end_year, forcing_dir):
    import glob
    import xarray as xr
    from datetime import datetime as _dt

    fdir = forcing_dir or CMFD_DIR
    if not os.path.isdir(fdir):
        raise FileNotFoundError("CMFD directory not found: %s" % fdir)

    lat_arr = np.asarray([p[0] for p in latlons], dtype=float)
    lon_arr = np.asarray([p[1] for p in latlons], dtype=float)
    npts = lat_arr.size

    var_map = {
        "temp": ("Temp", "temp"), "prec": ("Prec", "prec"),
        "srad": ("SRad", "srad"), "lrad": ("LRad", "lrad"),
        "wind": ("Wind", "wind"),
        "shum": ("SHum", "shum"), "pres": ("Pres", "pres"),
    }
    raw2out = {"prec": "prec_kgm2s", "srad": "srad_wm2", "lrad": "lrad_wm2",
               "wind": "wind_ms", "shum": "shum_kgkg", "pres": "pres_pa"}
    keys = ("temp_c",) + tuple(raw2out.values())

    def _open(path):
        for eng in ("h5netcdf", None):
            try:
                return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
            except Exception:
                continue
        return xr.open_dataset(path)

    def _find_files(key, subdir, year):
        files = sorted(glob.glob(os.path.join(fdir, subdir, "*_%d[01][0-9].nc" % year)))
        if files:
            return files
        files = sorted(glob.glob(
            os.path.join(fdir, "%s_*_%d[01][0-9]-%d[01][0-9].nc" % (key, year, year))))
        if files:
            return files
        cand = sorted(glob.glob(os.path.join(fdir, "%s_*%d*.nc" % (key, year))))
        return [f for f in cand
                if re.search(r"_%d(?:[01][0-9])?(?:[-_.]|$)" % year, os.path.basename(f))]

    all_times, out = [], [{k: [] for k in keys} for _ in range(npts)]

    for year in range(start_year, end_year + 1):
        year_series, year_times = {}, None
        for key, (subdir, vname) in var_map.items():
            files = _find_files(key, subdir, year)
            if not files:
                continue
            arrs, tlist = [], []
            for fp in files:
                ds = _open(fp)
                actual_var = vname
                if actual_var not in ds.data_vars:
                    cand = [v for v in ds.data_vars if vname in v.lower()]
                    if not cand:
                        ds.close()
                        continue
                    actual_var = cand[0]
                lat_name = next((c for c in ("lat", "latitude", "y") if c in ds.coords), None)
                lon_name = next((c for c in ("lon", "longitude", "x") if c in ds.coords), None)
                if lat_name is None or lon_name is None:
                    ds.close()
                    continue
                lats, lons = ds[lat_name].values, ds[lon_name].values
                lis = np.abs(lats[None, :] - lat_arr[:, None]).argmin(axis=1)
                los = np.abs(lons[None, :] - lon_arr[:, None]).argmin(axis=1)
                full = np.asarray(ds[actual_var].values)      # one decompression
                arrs.append(full[:, lis, los].astype(float))  # (time, npts)
                if "time" in ds.variables:
                    tlist.append(np.asarray(ds["time"].values))
                ds.close()
            if not arrs:
                continue
            year_series[key] = np.concatenate(arrs, axis=0)
            t_key = np.concatenate(tlist) if len(tlist) == len(arrs) else None
            if t_key is None or len(t_key) != year_series[key].shape[0]:
                raise ValueError(f"CMFD {key} {year}: time coordinate missing or not matching "
                                 f"its data; the calendar cannot be verified")
            if year_times is None:
                year_times = t_key
            else:
                _same_axis(year_times, t_key, f"CMFD {key} {year}")

        if "temp" not in year_series or year_times is None:
            continue
        _check_regular_year(year_times, year, f"CMFD {year}")
        nT = year_series["temp"].shape[0]
        for k, v in year_series.items():
            if v.shape[0] != nT:
                raise ValueError("CMFD sub-daily: %s has %d steps, temp has %d"
                                 % (k, v.shape[0], nT))
        if len(year_times) != nT:
            raise ValueError("CMFD sub-daily: time has %d steps, temp has %d"
                             % (len(year_times), nT))
        all_times.append(np.asarray(year_times, dtype="datetime64[s]"))
        for j in range(npts):
            out[j]["temp_c"].append(year_series["temp"][:, j] - 273.15)
            for raw_key, out_key in raw2out.items():
                if raw_key in year_series:
                    out[j][out_key].append(year_series[raw_key][:, j])
                else:
                    out[j][out_key].append(np.full(nT, np.nan))

    if not all_times:
        raise FileNotFoundError("No sub-daily CMFD data loaded from %s for %d-%d."
                                % (fdir, start_year, end_year))
    times = np.concatenate(all_times)
    dsec = np.diff(times.astype("int64"))
    if dsec.size and (dsec <= 0).any():
        raise ValueError("CMFD sub-daily loader returned non-monotonic times.")
    steps = np.unique(dsec)
    if steps.size != 1:
        raise ValueError("CMFD sub-daily loader: non-uniform timestep %s" % steps[:5])
    ts_seconds = int(steps[0])
    dates_py = [_dt.utcfromtimestamp(int(t.astype("int64"))) for t in times]
    return [{"dates": dates_py, "timestep_seconds": ts_seconds,
             **{k: np.concatenate(v) for k, v in o.items()}} for o in out]
