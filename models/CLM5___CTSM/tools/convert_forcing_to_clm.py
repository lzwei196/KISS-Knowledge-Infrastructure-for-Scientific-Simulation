#!/usr/bin/env python3
"""
convert_forcing_to_clm.py — Convert atmospheric forcing data to CLM5 DATM format.

Reads reanalysis or station forcing data (ERA5, GSWP3, CRUJRA, CMFD, or generic
CSV/NetCDF) and writes DATM-compatible NetCDF streams for CLM5.

CRITICAL UNIT CONVERSIONS:
  - Precipitation: input mm/day or mm/hr → output kg/m²/s (divide by 86400 or 3600)
  - Temperature: input °C → output K (add 273.15)
  - Specific humidity: input RH% → output kg/kg via Tetens equation
  - Wind speed: may need height correction from 10m to reference height
  - Longwave: must be downward (positive), NOT net or upward

CLM5 DATM streams expect each forcing variable in separate NetCDF files or
combined files with specific variable names:
  - TBOT (K), QBOT (kg/kg), WIND (m/s), PRECTmms (mm/s = kg/m²/s),
    FSDS (W/m²), FLDS (W/m²), PSRF (Pa)

TWO OUTPUT LAYOUTS (--datm-layout)
----------------------------------
``legacy``  (default, unchanged): one NetCDF per variable, ``clmforc.<VAR>.nc``.
            Convenient for inspection, but DATM CANNOT READ IT — no CIME stream
            template matches that layout.

``clm1pt``  The layout the CLM1PT / CLM_USRDAT stream actually reads:
            one file per month named ``YYYY-MM.nc`` under
            ``$DIN_LOC_ROOT_CLMFORC/$CLM_USRDAT_NAME/CLM1PT_data/``, each
            holding every forcing variable plus LONGXY/LATIXY/EDGE*.
            Verified against cime/src/components/data_comps_mct/datm/
            cime_config/namelist_definition_datm.xml:
              strm_datdir  = $DIN_LOC_ROOT_CLMFORC/$CLM_USRDAT_NAME/CLM1PT_data
              strm_datfil  = %ym.nc
              strm_datvar  = ZBOT z / TBOT tbot / RH rh / WIND wind /
                             PRECTmms precn / FSDS swdn / PSRF pbot / FLDS lwdn

  *** TRAP (dt_018): the CLM1PT stream reads humidity as ``RH`` in PERCENT,
      NOT as ``QBOT`` in kg/kg.  A file that carries QBOT only makes DATM abort
      with "ERROR: (shr_dmodel_readstrm) cannot find field rh".  dt_004 in
      triplets.yaml describes the *global* DATM streams; the single-point
      stream is the exception. ***

Usage:
    python convert_forcing_to_clm.py --source era5 --input /path/to/data.nc \\
        --output /path/to/datm/ --start-year 2000 --end-year 2010
    python convert_forcing_to_clm.py --source csv --input /path/to/station.csv \\
        --output /path/to/datm/ --lat 40.0 --lon 116.0
    python convert_forcing_to_clm.py --source fluxnet \\
        --input .../fluxnet/sites/US-MMS/FULLSET_HR.csv \\
        --output $DIN_LOC_ROOT/atm/datm7/US-MMS/CLM1PT_data \\
        --datm-layout clm1pt --lat 39.3232 --lon -86.4131 \\
        --zbot 30.0 --elevation 275 --start-year 1999 --end-year 2014
"""

import argparse
import calendar
import json
import os
import sys
import warnings

import numpy as np

try:
    import xarray as xr
except ImportError:
    xr = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import netCDF4 as nc4
except ImportError:
    nc4 = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
SECONDS_PER_DAY = 86400.0
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_3HR = 10800.0

# Expected CLM5 DATM variable names
CLM_VARS = {
    "temperature": "TBOT",       # K
    "specific_humidity": "QBOT", # kg/kg
    "wind_speed": "WIND",        # m/s
    "precipitation": "PRECTmms", # mm/s = kg/m2/s
    "shortwave": "FSDS",         # W/m2
    "longwave": "FLDS",          # W/m2
    "pressure": "PSRF",          # Pa
}

# Source-specific variable mappings
SOURCE_MAPS = {
    "era5": {
        "t2m": "temperature",
        "d2m": "dewpoint",
        "tp": "precipitation",
        "ssrd": "shortwave",
        "strd": "longwave",
        "sp": "pressure",
        "u10": "u_wind",
        "v10": "v_wind",
    },
    "gswp3": {
        "Tair": "temperature",
        "Qair": "specific_humidity",
        "Wind": "wind_speed",
        "Precip": "precipitation",
        "SWdown": "shortwave",
        "LWdown": "longwave",
        "PSurf": "pressure",
    },
    "crujra": {
        "tmp": "temperature",
        "spfh": "specific_humidity",
        "ugrd": "u_wind",
        "vgrd": "v_wind",
        "pre": "precipitation",
        "dswrf": "shortwave",
        "dlwrf": "longwave",
        "pres": "pressure",
    },
    "csv": {
        "temperature": "temperature",
        "humidity": "specific_humidity",
        "wind_speed": "wind_speed",
        "precipitation": "precipitation",
        "shortwave": "shortwave",
        "longwave": "longwave",
        "pressure": "pressure",
    },
    # FLUXNET2015 FULLSET half-hourly (HH) / hourly (HR) files.  The "_F"
    # suffix marks the gap-filled variables (MDS gap-filling + ERA-Interim
    # downscaled fill) — those are the only ones continuous enough to drive a
    # land model.  Pastorello et al. 2020, Sci. Data 7:225, Table 3.
    "fluxnet": {
        "TA_F": "temperature",        # degC
        "SW_IN_F": "shortwave",       # W/m2
        "LW_IN_F": "longwave",        # W/m2
        "VPD_F": "vpd",               # hPa
        "PA_F": "pressure",           # kPa
        "P_F": "precipitation",       # mm per timestep
        "WS_F": "wind_speed",         # m/s
    },
}

# Per-variable fallbacks when a site does not report the primary column.
FLUXNET_FALLBACKS = {
    "LW_IN_F": ["LW_IN_JSB_F", "LW_IN_F_MDS", "LW_IN_ERA"],
    "TA_F": ["TA_F_MDS", "TA_ERA"],
    "SW_IN_F": ["SW_IN_F_MDS", "SW_IN_ERA"],
    "VPD_F": ["VPD_F_MDS", "VPD_ERA"],
    "PA_F": ["PA", "PA_ERA"],
    "P_F": ["P", "P_ERA"],
    "WS_F": ["WS", "WS_ERA"],
}

FLUXNET_MISSING = -9999.0


def validate_inputs(args):
    """Validate input arguments and data availability."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input path does not exist: {args.input}")

    if args.source not in SOURCE_MAPS:
        errors.append(
            f"Unknown source '{args.source}'. "
            f"Supported: {', '.join(SOURCE_MAPS.keys())}"
        )

    if args.start_year and args.end_year:
        if args.start_year > args.end_year:
            errors.append("start-year must be <= end-year")

    if args.source in ("csv", "fluxnet"):
        if args.lat is None or args.lon is None:
            errors.append(f"--lat and --lon required for {args.source} source")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def celsius_to_kelvin(t_c):
    """Convert temperature from Celsius to Kelvin."""
    return t_c + KELVIN_OFFSET


def dewpoint_to_specific_humidity(td_k, p_pa):
    """Convert dewpoint temperature (K) and pressure (Pa) to specific humidity (kg/kg).

    Uses the Tetens formula for saturation vapor pressure:
        es = 611.2 * exp(17.67 * (T - 273.15) / (T - 29.65))
        q = 0.622 * es / (p - 0.378 * es)
    """
    td_c = td_k - KELVIN_OFFSET
    es = 611.2 * np.exp(17.67 * td_c / (td_c + 243.5))
    q = 0.622 * es / (p_pa - 0.378 * es)
    return np.clip(q, 0.0, 0.06)


def rh_to_specific_humidity(rh_pct, t_k, p_pa):
    """Convert relative humidity (%) to specific humidity (kg/kg).

    Uses the Tetens formula for saturation vapor pressure.
    """
    t_c = t_k - KELVIN_OFFSET
    es = 611.2 * np.exp(17.67 * t_c / (t_c + 243.5))
    e = (rh_pct / 100.0) * es
    q = 0.622 * e / (p_pa - 0.378 * e)
    return np.clip(q, 0.0, 0.06)


def compute_wind_speed(u, v):
    """Compute wind speed from u and v components."""
    return np.sqrt(u**2 + v**2)


def convert_precip(precip, source, timestep_seconds):
    """Convert precipitation to kg/m2/s.

    Different sources provide precipitation in different units:
      - ERA5: m/timestep (accumulated) → need / timestep_seconds * 1000
      - GSWP3: kg/m2/s (already correct)
      - CRUJRA: mm/6hr → / 21600
      - CSV: mm/day → / 86400
    """
    if source == "era5":
        # ERA5 total precipitation is in meters accumulated per timestep
        return precip * 1000.0 / timestep_seconds
    elif source == "gswp3":
        # Already in kg/m2/s
        return precip
    elif source == "crujra":
        # mm per 6 hours
        return precip / (6.0 * SECONDS_PER_HOUR)
    elif source == "csv":
        # Assume mm/day
        return precip / SECONDS_PER_DAY
    else:
        warnings.warn(f"Unknown source {source}, assuming precip in mm/day")
        return precip / SECONDS_PER_DAY


def convert_shortwave(sw, source, timestep_seconds):
    """Convert shortwave radiation to W/m2.

    ERA5 provides accumulated J/m2 per timestep; others provide W/m2.
    """
    if source == "era5":
        return sw / timestep_seconds
    return sw


def convert_longwave(lw, source, timestep_seconds):
    """Convert longwave radiation to downward W/m2.

    ERA5 provides accumulated J/m2 per timestep; others provide W/m2.
    CRITICAL: Must be DOWNWARD longwave, not net or upward.
    """
    if source == "era5":
        return lw / timestep_seconds
    return lw


def process_era5(ds, args):
    """Process ERA5 NetCDF dataset to CLM5 DATM variables."""
    result = {}
    vmap = SOURCE_MAPS["era5"]

    # Determine timestep
    times = ds["time"].values
    if len(times) > 1:
        dt_ns = np.diff(times[:2])[0]
        timestep_s = float(dt_ns) / 1e9
    else:
        timestep_s = SECONDS_PER_HOUR  # default 1hr for ERA5

    # Temperature (ERA5: K already)
    if "t2m" in ds:
        t_k = ds["t2m"].values
        if np.nanmean(t_k) < 200:
            # Likely Celsius
            t_k = celsius_to_kelvin(t_k)
        result["TBOT"] = t_k

    # Humidity from dewpoint
    if "d2m" in ds and "sp" in ds:
        td_k = ds["d2m"].values
        p_pa = ds["sp"].values
        if np.nanmean(td_k) < 200:
            td_k = celsius_to_kelvin(td_k)
        result["QBOT"] = dewpoint_to_specific_humidity(td_k, p_pa)

    # Wind speed from u, v components
    if "u10" in ds and "v10" in ds:
        result["WIND"] = compute_wind_speed(
            ds["u10"].values, ds["v10"].values
        )

    # Precipitation
    if "tp" in ds:
        result["PRECTmms"] = convert_precip(
            ds["tp"].values, "era5", timestep_s
        )

    # Radiation
    if "ssrd" in ds:
        result["FSDS"] = convert_shortwave(
            ds["ssrd"].values, "era5", timestep_s
        )
    if "strd" in ds:
        result["FLDS"] = convert_longwave(
            ds["strd"].values, "era5", timestep_s
        )

    # Pressure
    if "sp" in ds:
        result["PSRF"] = ds["sp"].values

    return result, times


def process_gswp3(ds, args):
    """Process GSWP3 NetCDF dataset — already in correct units."""
    result = {}
    vmap = SOURCE_MAPS["gswp3"]

    times = ds["time"].values

    for src_var, internal_name in vmap.items():
        if src_var in ds:
            clm_name = CLM_VARS.get(internal_name)
            if clm_name:
                result[clm_name] = ds[src_var].values

    # Temperature check
    if "TBOT" in result and np.nanmean(result["TBOT"]) < 200:
        result["TBOT"] = celsius_to_kelvin(result["TBOT"])

    return result, times


def process_csv(filepath, args):
    """Process CSV station data to CLM5 DATM variables.

    Expected columns: datetime, temperature(C), humidity(%), wind_speed(m/s),
    precipitation(mm/day), shortwave(W/m2), longwave(W/m2), pressure(Pa)
    """
    df = pd.read_csv(filepath, parse_dates=["datetime"])

    result = {}
    times = df["datetime"].values

    # Temperature: C → K
    if "temperature" in df.columns:
        t_vals = df["temperature"].values
        if np.nanmean(t_vals) < 100:  # Celsius
            result["TBOT"] = celsius_to_kelvin(t_vals)
        else:
            result["TBOT"] = t_vals

    # Pressure
    p_pa = df["pressure"].values if "pressure" in df.columns else np.full(len(df), 101325.0)
    result["PSRF"] = p_pa

    # Humidity: RH% → specific humidity
    if "humidity" in df.columns:
        rh = df["humidity"].values
        t_k = result.get("TBOT", np.full(len(df), 288.0))
        result["QBOT"] = rh_to_specific_humidity(rh, t_k, p_pa)

    # Wind
    if "wind_speed" in df.columns:
        result["WIND"] = df["wind_speed"].values

    # Precipitation: mm/day → kg/m2/s
    if "precipitation" in df.columns:
        result["PRECTmms"] = convert_precip(
            df["precipitation"].values, "csv", SECONDS_PER_DAY
        )

    # Radiation
    if "shortwave" in df.columns:
        result["FSDS"] = np.maximum(df["shortwave"].values, 0.0)
    if "longwave" in df.columns:
        result["FLDS"] = df["longwave"].values

    return result, times


def vpd_to_rh(vpd_hpa, t_k):
    """Convert vapour-pressure deficit (hPa) + air temperature (K) to RH (%).

    es via Tetens (same formulation as rh_to_specific_humidity), then
        RH = 100 * (es - VPD) / es
    RH is clipped to [1, 100]: CLM's DATM converts RH back to specific
    humidity, and RH <= 0 produces a negative q that aborts the run.
    """
    t_c = t_k - KELVIN_OFFSET
    es_pa = 611.2 * np.exp(17.67 * t_c / (t_c + 243.5))
    vpd_pa = vpd_hpa * 100.0
    rh = 100.0 * (es_pa - vpd_pa) / es_pa
    return np.clip(rh, 1.0, 100.0)


def barometric_pressure(elev_m):
    """US standard atmosphere pressure (Pa) at elevation (m)."""
    return 101325.0 * (1.0 - 2.25577e-5 * elev_m) ** 5.25588


def process_fluxnet(filepath, args):
    """Read a FLUXNET2015 FULLSET HH/HR file into CLM5 DATM variables.

    Returns (data, times, meta).  ``data`` carries BOTH the RH (%) needed by
    the CLM1PT stream and QBOT (kg/kg) for the generic DATM streams, so either
    layout can be written from one pass.
    """
    wanted = list(SOURCE_MAPS["fluxnet"].keys())
    header = pd.read_csv(filepath, nrows=0).columns.tolist()

    resolved, missing = {}, []
    for col in wanted:
        if col in header:
            resolved[col] = col
            continue
        alt = next((c for c in FLUXNET_FALLBACKS.get(col, []) if c in header), None)
        if alt:
            resolved[col] = alt
        else:
            missing.append(col)

    usecols = ["TIMESTAMP_START", "TIMESTAMP_END"] + list(resolved.values())
    df = pd.read_csv(filepath, usecols=usecols)
    df = df.replace(FLUXNET_MISSING, np.nan)

    t_start = pd.to_datetime(df["TIMESTAMP_START"].astype(np.int64).astype(str),
                             format="%Y%m%d%H%M")
    t_end = pd.to_datetime(df["TIMESTAMP_END"].astype(np.int64).astype(str),
                           format="%Y%m%d%H%M")
    dt_seconds = float((t_end - t_start).dt.total_seconds().median())
    # FLUXNET values are interval MEANS; stamp them at the interval midpoint so
    # DATM's nearest-neighbour time interpolation picks the right hour.
    times = t_start + pd.to_timedelta(dt_seconds / 2.0, unit="s")

    if args.start_year is not None:
        keep = times.dt.year >= args.start_year
        df, times = df[keep.values], times[keep.values]
    if args.end_year is not None:
        keep = times.dt.year <= args.end_year
        df, times = df[keep.values], times[keep.values]

    # dt_007: CLM runs a noleap (365-day) calendar. Feb 29 must be dropped from
    # the forcing, otherwise the stream time axis drifts by one day per leap
    # year relative to the model calendar.
    n_before = len(times)
    leapmask = ~((times.dt.month == 2) & (times.dt.day == 29))
    df, times = df[leapmask.values], times[leapmask.values]
    n_leap_dropped = n_before - len(times)

    def col(name):
        src = resolved.get(name)
        return df[src].to_numpy(dtype=float) if src else None

    n = len(times)
    t_c = col("TA_F")
    if t_c is None:
        raise ValueError("FLUXNET file has no usable air-temperature column")
    tbot = celsius_to_kelvin(t_c)

    pa_kpa = col("PA_F")
    if pa_kpa is None or np.all(np.isnan(pa_kpa)):
        if args.elevation is None:
            raise ValueError(
                "No pressure column (PA_F/PA/PA_ERA) in the FLUXNET file; "
                "pass --elevation so a barometric estimate can be used"
            )
        psrf = np.full(n, barometric_pressure(args.elevation))
    else:
        psrf = pa_kpa * 1000.0  # kPa -> Pa

    vpd = col("VPD_F")
    if vpd is None:
        raise ValueError("FLUXNET file has no usable VPD column for humidity")
    rh = vpd_to_rh(vpd, tbot)

    precip_step = col("P_F")
    if precip_step is None:
        raise ValueError("FLUXNET file has no usable precipitation column")
    # P_F is the accumulation over ONE timestep (mm), not a rate.
    prect = precip_step / dt_seconds

    data = {
        "TBOT": tbot,
        "PSRF": psrf,
        "RH": rh,
        "QBOT": rh_to_specific_humidity(rh, tbot, psrf),
        "WIND": col("WS_F"),
        "PRECTmms": prect,
        "FSDS": np.maximum(col("SW_IN_F"), 0.0),
        "FLDS": col("LW_IN_F"),
        "ZBOT": np.full(n, float(args.zbot)),
    }

    # Any residual gaps (rare in the _F columns) are linearly interpolated so
    # DATM never sees a NaN — a NaN in the forcing propagates silently into
    # soil moisture and shows up only as a crash days later.
    gap_report = {}
    for k, v in list(data.items()):
        if v is None:
            raise ValueError(f"FLUXNET file is missing the source column for {k}")
        nan_n = int(np.count_nonzero(~np.isfinite(v)))
        if nan_n:
            s = pd.Series(v).interpolate(limit_direction="both")
            data[k] = s.to_numpy()
            gap_report[k] = nan_n

    meta = {
        "columns_used": resolved,
        "columns_missing": missing,
        "timestep_seconds": dt_seconds,
        "n_records": n,
        "leap_day_records_dropped": n_leap_dropped,
        "residual_gaps_interpolated": gap_report,
    }
    return data, times.to_numpy(), meta


def process(args):
    """Main processing: read source data, convert, write DATM NetCDF."""
    if args.source == "fluxnet":
        if pd is None:
            print(json.dumps({
                "status": "error",
                "errors": ["pandas required for FLUXNET processing"]
            }))
            sys.exit(1)
        data, times, meta = process_fluxnet(args.input, args)
        return data, times, meta

    if args.source in ("era5", "gswp3", "crujra"):
        if xr is None:
            print(json.dumps({
                "status": "error",
                "errors": ["xarray required for NetCDF processing"]
            }))
            sys.exit(1)
        ds = xr.open_dataset(args.input)

        if args.source == "era5":
            data, times = process_era5(ds, args)
        elif args.source == "gswp3":
            data, times = process_gswp3(ds, args)
        else:
            data, times = process_gswp3(ds, args)  # CRUJRA similar structure

        ds.close()

    elif args.source == "csv":
        if pd is None:
            print(json.dumps({
                "status": "error",
                "errors": ["pandas required for CSV processing"]
            }))
            sys.exit(1)
        data, times = process_csv(args.input, args)

    else:
        print(json.dumps({
            "status": "error",
            "errors": [f"Source {args.source} not implemented"]
        }))
        sys.exit(1)

    return data, times, {}


def validate_outputs(data):
    """Validate converted forcing data for physical reasonableness."""
    warnings_list = []

    if "TBOT" in data:
        t = data["TBOT"]
        if np.any(np.isfinite(t)):
            t_mean = np.nanmean(t)
            if t_mean < 200:
                warnings_list.append(
                    f"Mean temperature {t_mean:.1f} K seems too low — "
                    "check if Celsius was not converted"
                )
            if t_mean > 350:
                warnings_list.append(
                    f"Mean temperature {t_mean:.1f} K seems too high"
                )

    if "QBOT" in data:
        q = data["QBOT"]
        if np.any(np.isfinite(q)):
            q_max = np.nanmax(q)
            if q_max > 0.05:
                warnings_list.append(
                    f"Max specific humidity {q_max:.4f} kg/kg > 0.05 — "
                    "check if RH was used instead of q"
                )

    if "PRECTmms" in data:
        p = data["PRECTmms"]
        if np.any(np.isfinite(p)):
            p_max = np.nanmax(p)
            if p_max > 0.1:
                warnings_list.append(
                    f"Max precip rate {p_max:.4f} kg/m2/s > 0.1 — "
                    "check unit conversion (should be mm/s)"
                )
            if np.any(p < 0):
                warnings_list.append("Negative precipitation values detected")

    if "FSDS" in data:
        sw = data["FSDS"]
        if np.any(np.isfinite(sw)):
            if np.any(sw < 0):
                warnings_list.append("Negative shortwave radiation detected")
            if np.nanmax(sw) > 1500:
                warnings_list.append(
                    f"Max shortwave {np.nanmax(sw):.0f} W/m2 > 1500"
                )

    if "FLDS" in data:
        lw = data["FLDS"]
        if np.any(np.isfinite(lw)):
            lw_mean = np.nanmean(lw)
            if lw_mean < 50 or lw_mean > 600:
                warnings_list.append(
                    f"Mean longwave {lw_mean:.0f} W/m2 outside 50-600 range"
                )

    return warnings_list


def write_datm_netcdf(data, times, output_dir, lat=None, lon=None):
    """Write DATM-compatible NetCDF files."""
    if xr is None:
        # Fallback: write CSV summary
        csv_path = os.path.join(output_dir, "forcing_summary.csv")
        rows = []
        n = len(times) if hasattr(times, '__len__') else 0
        for i in range(min(n, 10)):
            row = {"time": str(times[i])}
            for var_name, values in data.items():
                if hasattr(values, '__len__') and len(values) > i:
                    row[var_name] = float(values[i])
            rows.append(row)
        if pd is not None:
            pd.DataFrame(rows).to_csv(csv_path, index=False)
        return csv_path

    os.makedirs(output_dir, exist_ok=True)

    lat_val = lat if lat is not None else 0.0
    lon_val = lon if lon is not None else 0.0

    for var_name, values in data.items():
        if values is None:
            continue

        # Flatten spatial dims if needed
        if values.ndim > 1:
            values = values.reshape(len(times), -1)[:, 0]

        ds_out = xr.Dataset(
            {
                var_name: xr.DataArray(
                    values.reshape(-1, 1, 1),
                    dims=["time", "lat", "lon"],
                    attrs={"units": _get_units(var_name)},
                )
            },
            coords={
                "time": times,
                "lat": [lat_val],
                "lon": [lon_val],
            },
        )

        fname = f"clmforc.{var_name}.nc"
        fpath = os.path.join(output_dir, fname)
        ds_out.to_netcdf(fpath)

    return output_dir


CLM1PT_VARS = ["ZBOT", "TBOT", "RH", "WIND", "PRECTmms", "FSDS", "PSRF", "FLDS"]


def write_clm1pt_monthly(data, times, output_dir, lat, lon, half_width_deg=0.05,
                         resume=True):
    """Write DATM CLM1PT monthly files (``YYYY-MM.nc``).

    One file per calendar month holding every forcing variable, matching
    strm_datfil = ``%ym.nc`` for stream CLM1PT.CLM_USRDAT.  ``time`` is days
    since the first instant of that month on a NOLEAP calendar, which is why
    the leap days must already have been dropped upstream (dt_007).

    ``resume=True`` skips months whose file already exists, so a re-launched
    detached run does not redo a multi-year conversion.
    """
    if nc4 is None:
        raise RuntimeError("netCDF4 is required for the clm1pt layout")

    os.makedirs(output_dir, exist_ok=True)
    t = pd.to_datetime(times)
    years = t.year.to_numpy()
    months = t.month.to_numpy()
    keys = years * 100 + months

    lon360 = float(lon) % 360.0
    written, skipped = [], []

    for key in np.unique(keys):
        yr, mo = int(key // 100), int(key % 100)
        fname = os.path.join(output_dir, f"{yr:04d}-{mo:02d}.nc")
        if resume and os.path.exists(fname):
            skipped.append(os.path.basename(fname))
            continue

        sel = keys == key
        tt = t[sel]
        ref = np.datetime64(f"{yr:04d}-{mo:02d}-01T00:00:00")
        offs = (tt.to_numpy() - ref) / np.timedelta64(1, "s") / 86400.0

        ds = nc4.Dataset(fname + ".tmp", "w", format="NETCDF3_64BIT_OFFSET")
        ds.createDimension("time", None)
        ds.createDimension("lat", 1)
        ds.createDimension("lon", 1)
        ds.createDimension("scalar", 1)

        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = f"days since {yr:04d}-{mo:02d}-01 00:00:00"
        tv.calendar = "noleap"
        tv.long_name = "observation time"
        tv[:] = offs

        lonv = ds.createVariable("LONGXY", "f8", ("lat", "lon"))
        lonv.units = "degrees_east"
        lonv.long_name = "longitude"
        lonv[:] = lon360
        latv = ds.createVariable("LATIXY", "f8", ("lat", "lon"))
        latv.units = "degrees_north"
        latv.long_name = "latitude"
        latv[:] = float(lat)

        for name, val in (("EDGEW", lon360 - half_width_deg),
                          ("EDGEE", lon360 + half_width_deg),
                          ("EDGES", float(lat) - half_width_deg),
                          ("EDGEN", float(lat) + half_width_deg)):
            ev = ds.createVariable(name, "f8", ("scalar",))
            ev.units = "degrees_east" if name in ("EDGEW", "EDGEE") else "degrees_north"
            ev.long_name = f"{name.lower()} edge in atmospheric data"
            ev[:] = val

        for var in CLM1PT_VARS:
            if var not in data:
                raise KeyError(
                    f"CLM1PT layout requires {var}; converter produced "
                    f"{sorted(data)}"
                )
            v = ds.createVariable(var, "f4", ("time", "lat", "lon"))
            v.units = _get_units(var)
            v.long_name = _CLM1PT_LONGNAME[var]
            v.mode = "time-dependent"
            v[:] = np.asarray(data[var])[sel].reshape(-1, 1, 1)

        ds.case_title = "CLM1PT single-point tower forcing"
        ds.history = ("created by CLM5___CTSM KI convert_forcing_to_clm.py "
                      "--datm-layout clm1pt")
        ds.close()
        os.replace(fname + ".tmp", fname)
        written.append(os.path.basename(fname))

    return {"dir": output_dir, "files_written": len(written),
            "files_skipped_existing": len(skipped),
            "first": written[0] if written else (skipped[0] if skipped else None),
            "last": written[-1] if written else (skipped[-1] if skipped else None)}


_CLM1PT_LONGNAME = {
    "ZBOT": "observational height",
    "TBOT": "temperature at the lowest atm level",
    "RH": "relative humidity at the lowest atm level",
    "WIND": "wind at the lowest atm level",
    "PRECTmms": "precipitation",
    "FSDS": "incident solar radiation",
    "PSRF": "pressure at the lowest atm level",
    "FLDS": "incident longwave radiation",
}


def _get_units(var_name):
    """Return CF-convention units for CLM5 DATM variables."""
    units_map = {
        "TBOT": "K",
        "QBOT": "kg/kg",
        "RH": "%",
        "ZBOT": "m",
        "WIND": "m/s",
        "PRECTmms": "mm/s",
        "FSDS": "W/m2",
        "FLDS": "W/m2",
        "PSRF": "Pa",
    }
    return units_map.get(var_name, "unknown")


def main():
    parser = argparse.ArgumentParser(
        description="Convert atmospheric forcing data to CLM5 DATM format"
    )
    parser.add_argument(
        "--source", type=str, required=True,
        choices=["era5", "gswp3", "crujra", "csv", "fluxnet"],
        help="Forcing data source type"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Input file or directory path"
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Output directory for DATM NetCDF files"
    )
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--lat", type=float, default=None, help="Latitude")
    parser.add_argument("--lon", type=float, default=None, help="Longitude")
    parser.add_argument(
        "--datm-layout", type=str, default="legacy",
        choices=["legacy", "clm1pt"],
        help="legacy = one file per variable (NOT readable by DATM); "
             "clm1pt = monthly YYYY-MM.nc files for the CLM1PT/CLM_USRDAT stream"
    )
    parser.add_argument("--zbot", type=float, default=30.0,
                        help="Forcing reference height (m) written as ZBOT")
    parser.add_argument("--elevation", type=float, default=None,
                        help="Site elevation (m); used only if the source has "
                             "no pressure column")
    parser.add_argument("--half-width-deg", type=float, default=0.05,
                        help="Half-width of the single-point cell (EDGE*)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Rewrite monthly files that already exist")

    args = parser.parse_args()

    validate_inputs(args)
    data, times, meta = process(args)
    warnings_list = validate_outputs(data)

    os.makedirs(args.output, exist_ok=True)
    if args.datm_layout == "clm1pt":
        if args.lat is None or args.lon is None:
            print(json.dumps({"status": "error", "errors": [
                "--lat and --lon are required for --datm-layout clm1pt"]}))
            sys.exit(1)
        layout_info = write_clm1pt_monthly(
            data, times, args.output, args.lat, args.lon,
            half_width_deg=args.half_width_deg, resume=not args.no_resume,
        )
        output_path = layout_info["dir"]
    else:
        layout_info = None
        output_path = write_datm_netcdf(
            data, times, args.output, lat=args.lat, lon=args.lon
        )

    result = {
        "status": "success",
        "source": args.source,
        "datm_layout": args.datm_layout,
        "output_dir": args.output,
        "output_path": output_path,
        "variables_converted": list(data.keys()),
        "n_timesteps": len(times) if hasattr(times, '__len__') else 0,
        "source_meta": meta,
        "layout": layout_info,
        "warnings": warnings_list,
    }

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
