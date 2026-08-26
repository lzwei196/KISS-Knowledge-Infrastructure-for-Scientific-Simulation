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
NASA_POWER_PARAMS = "T2M,PRECTOTCORR,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,WS2M,QV2M,PS"
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
                       variables=None):
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

    Returns:
        dict with keys: dates, precip_mm, temp_mean_c, temp_max_c,
                        temp_min_c, srad_wm2, wind_ms, shum_kgkg, pres_pa
             (and lrad_wm2 when available)
    """
    source = source.lower().strip()
    if source == "cmfd":
        return _load_cmfd(lat, lon, start_year, end_year, forcing_dir)
    elif source == "mswx":
        return _load_mswx(lat, lon, start_year, end_year, forcing_dir,
                          variables=variables)
    elif source == "nasa_power":
        return _load_nasa_power(lat, lon, start_year, end_year)
    elif source == "gswp3":
        return _load_gswp3(lat, lon, start_year, end_year, forcing_dir)
    else:
        raise ValueError(f"Unknown source '{source}'. Choose from: cmfd, mswx, nasa_power, gswp3")


def load_daily_forcing_points(source, latlons, start_year, end_year,
                              forcing_dir=None, variables=None):
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

    Returns:
        list of forcing dicts, in the same order as ``latlons``; each has the
        same keys as ``load_daily_forcing``.
    """
    latlons = [(float(a), float(b)) for a, b in latlons]
    src = source.lower().strip()
    if src == "cmfd" and len(latlons) > 1:
        return _load_cmfd_points(latlons, start_year, end_year, forcing_dir)
    if src == "mswx":
        # MSWX annual files are gzip-chunked one GLOBAL slab per timestep, so a
        # per-point loop would decompress the whole file once per point.
        return _load_mswx_points(latlons, start_year, end_year, forcing_dir,
                                 variables=variables)
    return [load_daily_forcing(source, la, lo, start_year, end_year, forcing_dir,
                               variables=variables)
            for la, lo in latlons]


def load_hourly_forcing(source, lat, lon, start_year, end_year, forcing_dir=None):
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
    """
    source = source.lower().strip()
    if source == "nasa_power":
        return _load_nasa_power_hourly(lat, lon, start_year, end_year)
    elif source in ("cmfd", "mswx"):
        return _load_subdaily_netcdf(source, lat, lon, start_year, end_year, forcing_dir)
    else:
        raise ValueError(f"Unknown source '{source}'. Choose from: cmfd, mswx, nasa_power")


def _load_subdaily_netcdf(source, lat, lon, start_year, end_year, forcing_dir):
    """Load CMFD or MSWX 3-hourly data without daily aggregation."""
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for sub-daily loading. pip install xarray")

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
                ds = xr.open_dataset(fpath)
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

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            month_data = {}
            for var_key, (subdir, prefix) in var_map.items():
                pattern = os.path.join(fdir, subdir, f"*{year}{month:02d}*")
                files = sorted(globmod.glob(pattern))
                if not files:
                    continue
                ds = xr.open_dataset(files[0])
                dvar = list(ds.data_vars)
                lats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                lons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                li = int(np.argmin(np.abs(lats - lat)))
                lo = int(np.argmin(np.abs(lons - lon)))
                month_data[var_key] = ds[dvar[0]][:, li, lo].values
                if var_key == "temp" and len(all_dates) == 0 or True:
                    # Build timestamps
                    if 'time' in ds:
                        pass  # We'll generate from year/month/step
                ds.close()

            if "temp" not in month_data:
                continue

            n_steps = len(month_data["temp"])
            for i in range(n_steps):
                day = i // 8
                hour = (i % 8) * 3
                try:
                    dt = datetime(year, month, 1) + timedelta(days=day, hours=hour)
                except ValueError:
                    break
                all_dates.append(dt)

                for var_key in var_map:
                    if var_key in month_data and i < len(month_data[var_key]):
                        all_vars[var_key].append(float(month_data[var_key][i]))
                    else:
                        all_vars[var_key].append(np.nan)

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


def _load_nasa_power_hourly(lat, lon, start_year, end_year):
    """Load NASA POWER hourly data WITHOUT daily aggregation."""
    try:
        import requests
    except ImportError:
        raise ImportError("requests required for NASA POWER. pip install requests")

    all_dates, all_temp, all_prec, all_srad = [], [], [], []
    all_lrad, all_wind, all_shum, all_pres = [], [], [], []

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
        swd = pd.get("ALLSKY_SFC_SW_DWN", {})
        lwd = pd.get("ALLSKY_SFC_LW_DWN", {})
        ws = pd.get("WS2M", {})
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
            # PRECTOTCORR is mm/day rate → mm per hour = rate / 24
            all_prec.append(max(0, _v(prec, key) / 24.0))
            all_srad.append(_v(swd, key))  # Already W/m²
            all_lrad.append(_v(lwd, key))
            all_wind.append(_v(ws, key))
            all_shum.append(_v(qv, key) / 1000.0)  # g/kg → kg/kg
            all_pres.append(_v(ps, key) * 1000.0)   # kPa → Pa

    return {
        "dates": np.array(all_dates, dtype="datetime64[s]"),
        "precip_mm": np.array(all_prec, dtype=np.float64),
        "temp_c": np.array(all_temp, dtype=np.float64),
        "srad_wm2": np.array(all_srad, dtype=np.float64),
        "lrad_wm2": np.array(all_lrad, dtype=np.float64),
        "wind_ms": np.array(all_wind, dtype=np.float64),
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

    def _areal_mean(da, lats, lons):
        """cos(lat)-weighted mean over the requested cells, NaN-safe."""
        lis = np.abs(lats[None, :] - lat_arr[:, None]).argmin(axis=1)
        los = np.abs(lons[None, :] - lon_arr[:, None]).argmin(axis=1)
        full = np.asarray(da.values)                       # (time, lat, lon)
        pts = full[:, lis, los].astype(float)              # (time, npoints)
        w = np.cos(np.radians(np.asarray(lats, dtype=float)[lis]))
        valid = np.isfinite(pts)
        wm = np.where(valid, w[None, :], 0.0)
        num = np.nansum(np.where(valid, pts, 0.0) * wm, axis=1)
        den = wm.sum(axis=1)
        return np.where(den > 0, num / np.maximum(den, 1e-12), np.nan)

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
            if year_times is None and tlist:
                year_times = np.concatenate(tlist)

        if "temp" not in year_series or year_times is None:
            continue

        times = np.asarray(year_times, dtype="datetime64[s]")
        days_np = times.astype("datetime64[D]")
        for day in np.unique(days_np):
            sel = days_np == day
            t = year_series["temp"][sel] - 273.15
            p = year_series["prec"][sel]
            all_dates.append(day)
            out["temp_mean_c"].append(float(np.nanmean(t)))
            out["temp_max_c"].append(float(np.nanmax(t)))
            out["temp_min_c"].append(float(np.nanmin(t)))
            out["precip_mm"].append(max(0.0, float(np.nanmean(p)) * 86400.0))
            for raw_key, out_key in (
                ("srad", "srad_wm2"), ("lrad", "lrad_wm2"), ("wind", "wind_ms"),
                ("shum", "shum_kgkg"), ("pres", "pres_pa"),
            ):
                if raw_key in year_series:
                    out[out_key].append(float(np.nanmean(year_series[raw_key][sel])))
                else:
                    out[out_key].append(float("nan"))

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
    return {"dates": dates_py, **{k: list(v) for k, v in out.items()}}


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
            if year_times is None and tlist:
                year_times = np.concatenate(tlist)

        if "temp" not in year_series or year_times is None:
            continue

        days_np = np.asarray(year_times, dtype="datetime64[s]").astype("datetime64[D]")
        for day in np.unique(days_np):
            sel = days_np == day
            all_dates.append(day)
            t = year_series["temp"][sel] - 273.15         # (nsub, npts)
            p = year_series["prec"][sel]
            for j in range(npts):
                out[j]["temp_mean_c"].append(float(np.nanmean(t[:, j])))
                out[j]["temp_max_c"].append(float(np.nanmax(t[:, j])))
                out[j]["temp_min_c"].append(float(np.nanmin(t[:, j])))
                out[j]["precip_mm"].append(max(0.0, float(np.nanmean(p[:, j])) * 86400.0))
                for raw_key, out_key in (("srad", "srad_wm2"), ("lrad", "lrad_wm2"),
                                         ("wind", "wind_ms"),
                                         ("shum", "shum_kgkg"), ("pres", "pres_pa")):
                    if raw_key in year_series:
                        out[j][out_key].append(float(np.nanmean(year_series[raw_key][sel][:, j])))
                    else:
                        out[j][out_key].append(float("nan"))

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
                tasks.append((fpath, _mswx_varname(fpath), r0, r1, c0, c1))
                tkeys.append((year, key))

        with ProcessPoolExecutor(max_workers=min(n_conc, len(tasks))) as ex:
            boxes = dict(zip(tkeys, ex.map(_mswx_read_box, tasks)))

        for year in batch:
            # (nsteps, nbox_lat, nbox_lon) -> (nsteps, npts)
            pts = {k: boxes.pop((year, k))[:, rr, cc] for k in keys}

            nsteps = pts["P"].shape[0]
            ndays = nsteps // 8                 # MSWX is 3-hourly: 8 steps/day
            sl = slice(0, ndays * 8)

            def _daily(key, how, _pts=pts, _nd=ndays, _sl=sl):
                if key not in _pts:             # not requested -> NaN column
                    return np.full((_nd, npts), np.nan, dtype=np.float64)
                a = _pts[key][_sl].reshape(_nd, 8, npts)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return how(a, axis=1)

            p_d = _daily("P", np.nansum)         # MSWX P is mm/3hr -> sum
            t_d = _daily("Tair", np.nanmean)
            tmax = _daily("Tair", np.nanmax)
            tmin = _daily("Tair", np.nanmin)
            sw_d = _daily("SWd", np.nanmean)
            lw_d = _daily("LWd", np.nanmean)
            wd_d = _daily("Wind", np.nanmean)
            sh_d = _daily("spechum", np.nanmean)
            pr_d = _daily("Pres", np.nanmean)
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
            all_tmin.append(tmin if not np.isnan(tmin) else tmean)
            all_tmax.append(tmax if not np.isnan(tmax) else tmean)

            all_precip.append(max(0.0, _val(prec_d, day_key)))
            # kW-hr/m^2/day -> W/m^2
            all_srad.append(_val(swd_d, day_key) * _KWHD_TO_WM2)
            all_lrad.append(_val(lwd_d, day_key) * _KWHD_TO_WM2)
            # GLM (and most surface models) expect wind at the 10 m anemometer
            # height; prefer WS10M and fall back to WS2M only when 10 m is
            # missing. WS2M can be anomalously low (near-zero) over some grid
            # cells, which starves convective/evaporative cooling in lake models.
            w10 = _val(ws10_d, day_key)
            all_wind.append(w10 if not np.isnan(w10) else _val(ws_d, day_key))
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
            if v == "tasmax":
                t = da["time"].values
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


def load_subdaily_forcing_points(source, latlons, start_year, end_year, forcing_dir=None):
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
    """
    if str(source).lower() != "cmfd":
        raise NotImplementedError(
            "load_subdaily_forcing_points supports source='cmfd' only, got %r" % (source,))
    return _load_cmfd_points_subdaily(latlons, start_year, end_year, forcing_dir)


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
            if year_times is None and tlist:
                year_times = np.concatenate(tlist)

        if "temp" not in year_series or year_times is None:
            continue
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
