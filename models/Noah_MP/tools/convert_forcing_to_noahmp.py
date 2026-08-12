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


def convert_temperature(temp_raw, source):
    """Convert temperature to Kelvin."""
    if source in ("cmfd", "mswx", "fluxnet"):
        # CMFD/MSWX/FLUXNET: Celsius -> Kelvin
        if np.nanmax(temp_raw) < 100:  # likely Celsius
            return temp_raw + KELVIN_OFFSET
    if np.nanmin(temp_raw) > 150:  # already Kelvin
        return temp_raw
    return temp_raw + KELVIN_OFFSET


def convert_humidity(q_raw, temp_k, psfc_pa, source):
    """Convert humidity to specific humidity [kg/kg]."""
    if np.nanmax(q_raw) > 1.0:
        # Likely relative humidity (0-100%)
        rh = q_raw
        # Compute saturation vapor pressure (Tetens formula)
        temp_c = temp_k - KELVIN_OFFSET
        es = 611.2 * np.exp(17.67 * temp_c / (temp_c + 243.5))  # Pa
        e = rh / 100.0 * es
        q = 0.622 * e / (psfc_pa - 0.378 * e)
        return np.clip(q, 0.0, 0.06)
    elif np.nanmax(q_raw) > 0.06:
        # Likely g/kg -> kg/kg
        return q_raw / 1000.0
    return q_raw  # Already kg/kg


def convert_pressure(p_raw, source):
    """Convert pressure to Pa.

    NOTE (fixed 2026-08-02): the kPa test MUST be evaluated before the hPa test.
    Previously `if max < 2000: return p*100` came first, so kPa input (~100 kPa)
    was multiplied by 100 -> ~10 100 Pa, and the `< 200` kPa branch was dead
    code.  That is a 10x air-density error in every turbulent-flux calculation;
    it only trips a PSFC range WARNING (LIMITS floor 40 000 Pa) and the LDASIN
    file is still written.  dt_005.
    """
    if source == "fluxnet":
        return p_raw  # already converted to Pa by the FLUXNET reader
    pmax = np.nanmax(p_raw)
    if pmax < 200:
        return p_raw * 1000.0     # kPa -> Pa
    if pmax < 2000:
        return p_raw * PA_PER_HPA  # hPa/mbar -> Pa
    return p_raw  # Already Pa


def convert_precipitation(precip_raw, source, timestep_s):
    """Convert precipitation to mm/s."""
    if source == "fluxnet":
        # Already mm/s: the FLUXNET reader divides the per-interval accumulation
        # (P_F, mm/timestep) by its own interval length, which is the ONLY place
        # that length is known (HH sites are 1800 s, HR sites 3600 s).
        return precip_raw
    if source == "cmfd":
        # CMFD V2.0 (Data_forcing_*deg) stores prec as kg m-2 s-1 (== mm/s) already;
        # older CMFD V1 distributions store mm/hr. Discriminate by magnitude:
        # mm/s values are ~1e-5..5e-3 (max ~0.005), mm/hr values are ~0..50.
        if np.nanmax(precip_raw) <= 0.1:
            return precip_raw  # already mm/s (kg/m2/s)
        # CMFD V1: mm/hr -> mm/s
        return precip_raw * MM_PER_S_FROM_MM_PER_HR
    elif source == "era5":
        # ERA5: m accumulated per hour -> mm/s
        return precip_raw * MM_PER_S_FROM_M_PER_HR
    elif source == "mswx":
        # MSWX daily via ki_tools_common.load_forcing is mm/day -> mm/s
        return precip_raw * MM_PER_S_FROM_MM_PER_DAY
    elif np.nanmax(precip_raw) > 0.5 and timestep_s >= 86400:
        # Likely mm/day
        return precip_raw * MM_PER_S_FROM_MM_PER_DAY
    elif np.nanmax(precip_raw) > 0.5:
        # Likely mm/hr
        return precip_raw * MM_PER_S_FROM_MM_PER_HR
    return precip_raw  # Already mm/s


def read_cmfd_at_point(input_dir, lat, lon, start, end):
    """Read CMFD forcing data at a single lat/lon point."""
    import glob

    variables = {
        "temp": "T2D", "shum": "Q2D", "wind": "WIND",
        "pres": "PSFC", "srad": "SWDOWN", "lrad": "LWDOWN", "prec": "RAINRATE"
    }
    data = {}
    times = None

    for cmfd_var, noahmp_var in variables.items():
        pattern = os.path.join(input_dir, f"{cmfd_var}_*.nc")
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"No CMFD files found for {cmfd_var}: {pattern}")

        all_vals = []
        all_times = []
        for fpath in files:
            with nc.Dataset(fpath, 'r') as ds:
                lats = ds.variables['lat'][:]
                lons = ds.variables['lon'][:]
                ilat = int(np.argmin(np.abs(lats - lat)))
                ilon = int(np.argmin(np.abs(lons - lon)))
                var_name = [v for v in ds.variables if v not in ('lat', 'lon', 'time')][0]
                vals = ds.variables[var_name][:, ilat, ilon]
                t = nc.num2date(ds.variables['time'][:],
                                ds.variables['time'].units,
                                only_use_cftime_datetimes=False)
                all_vals.append(vals)
                all_times.append(t)

        data[noahmp_var] = np.concatenate(all_vals)
        if times is None:
            times = np.concatenate(all_times)

    # CMFD wind is scalar speed; split equally into U and V
    if "WIND" in data:
        wind = data.pop("WIND")
        data["U2D"] = wind / np.sqrt(2.0)
        data["V2D"] = wind / np.sqrt(2.0)

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
    try:
        f = load_daily_forcing_points("mswx", [(lat, lon), (lat, lon)],
                                      start.year, end.year, forcing_dir=fdir)[0]
    except Exception as e:
        print(f"  MSWX box reader failed ({e}); falling back to single-point path",
              file=sys.stderr)
        f = load_daily_forcing("mswx", lat, lon, start.year, end.year, forcing_dir=fdir)
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in f["dates"]]
    n = len(dates)

    def arr(key, default):
        v = f.get(key)
        return np.asarray(v, dtype=float) if v is not None else np.full(n, default)

    wind = arr("wind_ms", 1.0)
    raw = {
        "T2D":      arr("temp_mean_c", 10.0),   # degC -> convert_temperature adds 273.15
        "Q2D":      arr("shum_kgkg", 0.005),    # already kg/kg
        "U2D":      wind / np.sqrt(2.0),        # MSWX wind is scalar speed; split evenly
        "V2D":      wind / np.sqrt(2.0),
        "PSFC":     arr("pres_pa", 101325.0),   # already Pa
        "SWDOWN":   arr("srad_wm2", 0.0),
        "LWDOWN":   arr("lrad_wm2", 300.0),
        "RAINRATE": arr("precip_mm", 0.0),      # mm/day -> convert_precipitation(mswx) /86400
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

    dt_s = int((ts.iloc[1] - ts.iloc[0]).total_seconds())
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
        agg = agg[n_per_hour == (3600 // dt_s)]   # drop incomplete hours
        sub = agg
        dt_s = 3600
        print(f"  aggregated to hourly: {len(sub)} records")

    # Fill residual gaps (the *_F products are gap-filled, but *_ERA fallbacks
    # or dropped hours can still leave holes).
    n_gap = int(sub.isna().sum().sum())
    sub = sub.interpolate(limit_direction="both")
    if n_gap:
        print(f"  interpolated {n_gap} missing values across {len(sub.columns)} variables")

    # ---- local standard time -> UTC (dt_019) ----
    sub.index = sub.index - timedelta(hours=float(utc_offset))
    print(f"  shifted local standard time -> UTC by {-float(utc_offset):+g} h; "
          f"UTC range {sub.index[0]} .. {sub.index[-1]}")

    sub = sub[(sub.index >= start) & (sub.index <= end)]
    if len(sub) == 0:
        raise ValueError(f"No FLUXNET records inside {start} .. {end} after UTC shift")

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
    }
    times = [t.to_pydatetime() for t in sub.index]
    return times, raw


def read_generic_nc_at_point(input_dir, lat, lon, start, end):
    """Read generic NetCDF forcing data."""
    import glob
    files = sorted(glob.glob(os.path.join(input_dir, "*.nc")))
    if not files:
        raise FileNotFoundError(f"No NetCDF files in {input_dir}")

    # Try reading the first file to detect variable names
    with nc.Dataset(files[0], 'r') as ds:
        var_names = list(ds.variables.keys())

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

    data = {}
    times = None

    for fpath in files:
        with nc.Dataset(fpath, 'r') as ds:
            lats = ds.variables.get('lat', ds.variables.get('latitude', None))
            lons = ds.variables.get('lon', ds.variables.get('longitude', None))
            if lats is None or lons is None:
                continue
            lats = lats[:]
            lons = lons[:]
            ilat = int(np.argmin(np.abs(lats - lat)))
            ilon = int(np.argmin(np.abs(lons - lon)))

            for vn in ds.variables:
                if vn in name_map:
                    target = name_map[vn]
                    vals = ds.variables[vn][:, ilat, ilon] if ds.variables[vn].ndim >= 3 \
                        else ds.variables[vn][:]
                    if target not in data:
                        data[target] = []
                    data[target].append(vals)

            if times is None and 'time' in ds.variables:
                times = nc.num2date(ds.variables['time'][:],
                                    ds.variables['time'].units,
                                    only_use_cftime_datetimes=False)

    for k in data:
        data[k] = np.concatenate(data[k]) if isinstance(data[k], list) else data[k]

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

    # Read raw data
    if source == "cmfd":
        times, raw = read_cmfd_at_point(args.input_dir, args.lat, args.lon, start, end)
    elif source == "mswx":
        times, raw = read_mswx_at_point(args.input_dir, args.lat, args.lon, start, end)
    elif source == "fluxnet":
        times, raw = read_fluxnet_at_point(args.input_dir, start, end,
                                           getattr(args, "utc_offset", None))
    else:
        times, raw = read_generic_nc_at_point(args.input_dir, args.lat, args.lon, start, end)

    if times is None or len(times) == 0:
        print("ERROR: No forcing data found in specified period", file=sys.stderr)
        sys.exit(1)

    # Apply unit conversions
    converted = {}
    converted["T2D"] = convert_temperature(raw.get("T2D", np.full(len(times), 280.0)), source)
    converted["PSFC"] = convert_pressure(raw.get("PSFC", np.full(len(times), 101325.0)), source)
    converted["Q2D"] = convert_humidity(
        raw.get("Q2D", np.full(len(times), 0.005)),
        converted["T2D"], converted["PSFC"], source
    )
    converted["U2D"] = raw.get("U2D", np.full(len(times), 0.0))
    converted["V2D"] = raw.get("V2D", np.full(len(times), 0.0))
    converted["SWDOWN"] = np.clip(raw.get("SWDOWN", np.full(len(times), 0.0)), 0.0, None)
    converted["LWDOWN"] = raw.get("LWDOWN", np.full(len(times), 300.0))
    converted["RAINRATE"] = np.clip(
        convert_precipitation(raw.get("RAINRATE", np.full(len(times), 0.0)), source, args.timestep),
        0.0, None
    )

    # Write LDASIN files
    n_written = 0
    n_warnings = 0
    for i, t in enumerate(times):
        ts = t if isinstance(t, datetime) else datetime(t.year, t.month, t.day, t.hour)
        if ts < start or ts > end:
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

        write_ldasin(args.output_dir, ts, step_data, args.lat, args.lon)
        n_written += 1

    return n_written, n_warnings


def validate_outputs(output_dir, n_written):
    """Validate output LDASIN files were created correctly."""
    errors = []

    files = [f for f in os.listdir(output_dir) if f.endswith(".LDASIN_DOMAIN1")]
    if len(files) == 0:
        errors.append("No LDASIN files were written")
    elif len(files) != n_written:
        errors.append(f"Expected {n_written} files, found {len(files)}")

    # Spot-check first file
    if files:
        fpath = os.path.join(output_dir, sorted(files)[0])
        with nc.Dataset(fpath, 'r') as ds:
            for varname in ["T2D", "Q2D", "U2D", "V2D", "PSFC", "SWDOWN", "LWDOWN", "RAINRATE"]:
                if varname not in ds.variables:
                    errors.append(f"Missing variable {varname} in {fpath}")

    if errors:
        print("OUTPUT VALIDATION WARNINGS:", file=sys.stderr)
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
                        help="Output timestep in seconds (default: 3600)")
    parser.add_argument("--source", default="auto",
                        help="Source format: cmfd/era5/mswx/fluxnet/generic_nc/auto (default: auto)")
    parser.add_argument("--utc_offset", type=float, default=None,
                        help="Site UTC offset in hours (REQUIRED for --source fluxnet). "
                             "FLUXNET timestamps are local standard time; HRLDAS reads "
                             "LDASIN timestamps as UTC (dt_019).")

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

    n_written, n_warnings = process(args, context)
    print(f"\nWrote {n_written} LDASIN files ({n_warnings} warnings)")

    ok = validate_outputs(args.output_dir, n_written)
    if ok:
        print("OUTPUT VALIDATION: PASSED")
    else:
        print("OUTPUT VALIDATION: WARNINGS (check messages above)")

    # Write summary JSON
    summary = {
        "tool": "convert_forcing_to_noahmp",
        "n_files": n_written,
        "n_warnings": n_warnings,
        "output_dir": args.output_dir,
        "source_format": detect_source_format(args.input_dir),
        "validation": "passed" if ok else "warnings",
    }
    summary_path = os.path.join(args.output_dir, "forcing_summary.json")
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
