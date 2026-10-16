#!/usr/bin/env python3
"""Convert meteorological forcing data to COSIPY input netCDF format.

Handles ERA5, AWS station data, and generic CSV/netCDF inputs.
Performs unit conversions, bounds checking, and lapse rate corrections.

Usage:
    python convert_forcing.py \\
        --input forcing.csv \\
        --output cosipy_input.nc \\
        --static static.nc \\
        --source era5 \\
        --start "2009-01-01" \\
        --end "2009-12-31"
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


# ─── Variable specification ────────────────────────────────────────────
COSIPY_VARIABLES = {
    "T2":       {"units": "K",      "bounds": (223.16, 316.16), "desc": "2m air temperature"},
    "RH2":      {"units": "%",      "bounds": (0.0, 100.0),     "desc": "2m relative humidity"},
    "U2":       {"units": "m/s",    "bounds": (0.0, 50.0),      "desc": "2m wind speed"},
    "G":        {"units": "W/m2",   "bounds": (0.0, 1600.0),    "desc": "Incoming shortwave radiation"},
    "PRES":     {"units": "hPa",    "bounds": (200.0, 1080.0),  "desc": "Surface air pressure"},
    "RRR":      {"units": "mm",     "bounds": (0.0, 20.0),      "desc": "Total precipitation per timestep"},
    "N":        {"units": "fraction","bounds": (0.0, 1.0),      "desc": "Cloud cover fraction"},
    "LWin":     {"units": "W/m2",   "bounds": (0.0, 400.0),     "desc": "Incoming longwave radiation"},
    "SNOWFALL": {"units": "m",      "bounds": (0.0, 0.05),      "desc": "Snowfall in snow height per timestep"},
}

STATIC_VARIABLES = ["HGT", "ASPECT", "SLOPE", "MASK"]


def validate_inputs(input_path: str, source: str) -> bool:
    """Validate input file exists and source type is recognized.

    Args:
        input_path: Path to input file.
        source: Data source type.

    Returns:
        True if inputs are valid.

    Raises:
        FileNotFoundError: Input file not found.
        ValueError: Unknown source type.
    """
    if not Path(input_path).exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    valid_sources = ["era5", "aws", "csv", "wrf", "generic"]
    if source not in valid_sources:
        raise ValueError(f"Unknown source: {source}. Valid: {valid_sources}")

    return True


class ForcingError(Exception):
    """Input forcing cannot be converted honestly (missing, bad or unclear)."""


def _naive_wall_times(values, where: str) -> pd.DatetimeIndex:
    """Parse timestamps the way COSIPY's own aws2cosipy does.

    aws2cosipy (cosipy/utilities/aws2cosipy/aws2cosipy.py, read_input_file)
    parses TIMESTAMP with dateutil.parser.parse(x, ignoretz=True): a UTC
    offset in the text is dropped and the clock time is kept. COSIPY itself
    only sees naive times. We do the same, but a file whose stamps carry more
    than one offset (e.g. a daylight-saving switch) cannot be read that way
    without making duplicate or missing hours, so it stops with an error.
    """
    vals = pd.Index(values)
    try:
        idx = pd.DatetimeIndex(pd.to_datetime(vals, format="ISO8601"))
    except (ValueError, TypeError):
        try:
            stamps = [pd.Timestamp(v) for v in vals]
        except (ValueError, TypeError) as e:
            raise ForcingError(f"{where}: cannot read TIMESTAMP values ({e})")
        offsets = {t.utcoffset() for t in stamps if t is not pd.NaT}
        if len(offsets) > 1:
            raise ForcingError(
                f"{where}: TIMESTAMP values carry more than one UTC offset "
                f"{sorted(str(o) for o in offsets)}; dropping the offset (as "
                f"COSIPY's aws2cosipy does) would make duplicate or missing "
                f"hours. Convert the file to one time zone first.")
        idx = pd.DatetimeIndex([t.tz_localize(None) if t.tzinfo else t
                                for t in stamps])
    if idx.tz is not None:
        idx = idx.tz_localize(None)                 # keep the clock time
    if idx.isna().any():
        raise ForcingError(f"{where}: {int(idx.isna().sum())} empty TIMESTAMP value(s)")
    return idx.rename("TIMESTAMP")


def _bound(text):
    """A --start/--end bound as a naive clock time (offset dropped, as above)."""
    if text is None or str(text).strip() == "":
        return None
    t = pd.Timestamp(str(text).strip())
    return t.tz_localize(None) if t.tzinfo is not None else t


def _window_bounds(start, end):
    """(t0, t1) inclusive. A date-only --end keeps the whole day."""
    t0 = _bound(start)
    t1 = _bound(end)
    if t1 is not None and len(str(end).strip()) <= 10:
        t1 = t1 + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    return t0, t1


def _window(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Rows with t0 <= time <= t1. A mask, not .loc slicing, so an unsorted or
    duplicated time axis is kept as it is and reported later (never sorted or
    merged here)."""
    t0, t1 = _window_bounds(start, end)
    keep = np.ones(len(df), dtype=bool)
    if t0 is not None:
        keep &= np.asarray(df.index >= t0)
    if t1 is not None:
        keep &= np.asarray(df.index <= t1)
    out = df[keep]
    out.attrs = dict(df.attrs)
    return out


def read_point_csv(input_path: str, start_date=None, end_date=None) -> pd.DataFrame:
    """Read a COSIPY point CSV (one header line, TIMESTAMP column).

    Same layout as COSIPY's aws2cosipy input (data/input/Zhadang/
    Zhadang_ERA5_2009_2018.csv): comma separated, na_values "NAN", TIMESTAMP
    parsed with the offset dropped. Nothing is filled in.
    """
    df = pd.read_csv(input_path, na_values="NAN")
    if "TIMESTAMP" not in df.columns:
        raise ForcingError(f"{input_path}: no TIMESTAMP column (columns: {list(df.columns)})")
    df.index = _naive_wall_times(df.pop("TIMESTAMP"), input_path)
    return _window(df, start_date, end_date)


# A single-cell axis has no spacing to judge "inside the grid" by. Half the
# ERA5 0.25 deg spacing is the farthest a correct nearest ERA5 cell can be;
# override with --max-offset-deg for a single-cell file from a coarser grid.
SINGLE_CELL_MAX_OFFSET_DEG = 0.125


def _spacing(vals, circular=False):
    """Smallest spacing between distinct coordinate values (deg); None for one value.

    Longitude is circular: [359.75, 0] are 0.25 deg apart, not 359.75.
    """
    v = np.unique(np.asarray(vals, dtype=float) % 360.0 if circular
                  else np.asarray(vals, dtype=float))
    if len(v) < 2:
        return None
    d = np.diff(v)
    if circular:
        d = np.append(d, v[0] + 360.0 - v[-1])
    d = d[d > 0]
    return float(d.min()) if len(d) else None


def _nearest_cell(lats, lons, lat, lon, la="lat", lo="lon", where="",
                  single_max=None):
    """Index of the grid cell nearest to (lat, lon), longitude-convention safe.

    Longitude differences are taken modulo 360 so a 0..360 grid and a
    -180..180 request (or the reverse) pick the same place, also across 0/360.
    The nearest cell must be within half a grid spacing (+1 %) on each axis,
    i.e. the point lies inside that cell; a single-cell axis must be within
    `single_max` deg (default SINGLE_CELL_MAX_OFFSET_DEG). Otherwise the point
    is outside the grid: error, no other place's data is used.
    """
    if single_max is None:
        single_max = SINGLE_CELL_MAX_OFFSET_DEG
    lats = np.atleast_1d(np.asarray(lats, dtype=float))
    lons = np.atleast_1d(np.asarray(lons, dtype=float))
    # NaN compares False with every limit, so it would pass: refuse it.
    if not (np.isfinite(float(lat)) and np.isfinite(float(lon))
            and -90.0 <= float(lat) <= 90.0):
        raise ForcingError(f"{where}: requested point ({lat}, {lon}) is not a valid place")
    if not (np.isfinite(float(single_max)) and float(single_max) >= 0.0):
        raise ForcingError(f"{where}: --max-offset-deg {single_max} must be finite and >= 0")
    if not (np.isfinite(lats).all() and np.isfinite(lons).all()):
        raise ForcingError(f"{where}: the file's {la}/{lo} coordinates have "
                           f"non-finite values; its places are unknown")
    dlon = (lons - float(lon) + 180.0) % 360.0 - 180.0
    dlat = lats - float(lat)
    i = int(np.argmin(np.abs(dlat)))
    j = int(np.argmin(np.abs(dlon)))
    sp_lat = _spacing(lats)
    sp_lon = _spacing(lons, circular=True)
    lim_lat = 0.505 * sp_lat if sp_lat is not None else single_max
    lim_lon = 0.505 * sp_lon if sp_lon is not None else single_max
    if abs(dlat[i]) > lim_lat or abs(dlon[j]) > lim_lon:
        raise ForcingError(
            f"{where}: point ({lat}, {lon}) is outside the grid (nearest cell "
            f"{lats[i]}, {lons[j]}; allowed offset {lim_lat:g} / {lim_lon:g} deg)")
    return {la: i, lo: j}


def _no_inf(data, where):
    """Raw inputs must not hold +/-inf: a later clip or max() would turn it
    into a plausible value (e.g. tp=-inf -> 0 mm, tcc=inf -> N=1). NaN is
    left alone here; it is reported as missing by the later check."""
    for k, v in data.items():          # dict, or DataFrame columns
        try:
            a = np.asarray(v, dtype=float)
        except (TypeError, ValueError):
            continue
        if a.ndim and np.isinf(a).any():
            raise ForcingError(f"{where}: {k} has {int(np.isinf(a).sum())} infinite value(s)")


def read_era5_data(input_path: str, start_date: str, end_date: str,
                   lat: float = None, lon: float = None,
                   single_max: float = None) -> pd.DataFrame:
    """Read ERA5 netCDF or CSV data and convert units.

    ERA5 native units:
        - T2: K (no conversion needed)
        - dewpoint temperature: K (needs RH conversion)
        - u10, v10: m/s at 10m (needs height correction)
        - ssrd: J/m2 accumulated (needs /dt to get W/m2)
        - strd: J/m2 accumulated (needs /dt to get W/m2)
        - tp: m accumulated (needs /dt and *1000 for mm)
        - sp: Pa (needs /100 for hPa)

    ERA5 single-level accumulations (ssrd, strd, tp, sf) are totals over the
    one hour before each stamp, so the netCDF path declares a 3600 s step and
    the time-axis check refuses any other spacing (a 3-hourly subset would
    hold only the last hour's precipitation).

    Args:
        input_path: Path to ERA5 data file.
        start_date: Start date string.
        end_date: End date string.
        lat, lon: point to take (nearest) when the file has a lat/lon grid.

    Returns:
        DataFrame with COSIPY-formatted forcing data, indexed by time.
    """
    if not input_path.endswith(".nc"):
        # A CSV here is already in COSIPY variables/units (TIMESTAMP index).
        return read_point_csv(input_path, start_date, end_date)

    with xr.open_dataset(input_path) as ds:
        tname = next((n for n in ("valid_time", "time") if n in ds.dims), None)
        if tname is None:
            raise ForcingError(f"{input_path}: no time dimension (dims: {dict(ds.sizes)})")
        # The file's place must be the requested place, whatever shape its
        # coordinates have: grid dims, a 1x1 grid, or scalar point coordinates
        # (e.g. left by ds.isel(latitude=0, longitude=0)). No lat/lon at all
        # -> the place cannot be checked -> error.
        pair = next(((la, lo) for la, lo in (("latitude", "longitude"), ("lat", "lon"))
                     if la in ds.coords and lo in ds.coords), None)
        if pair is None:
            raise ForcingError(f"{input_path}: no latitude/longitude coordinates; "
                               f"cannot check that the data is at the requested point")
        if lat is None or lon is None:
            raise ForcingError(f"{input_path}: give --lat/--lon")
        la, lo = pair
        # Only a fixed place per file is accepted: each coordinate is scalar or
        # lies along its own axis. Coordinates along time (a moving point, or
        # records from several places) or 2-D (curvilinear) grids are refused.
        for c in (la, lo):
            if ds[c].dims not in ((), (c,)):
                raise ForcingError(f"{input_path}: {c} coordinate has dims {ds[c].dims}; "
                                   f"only a scalar or its own 1-D axis is supported")
        cell = _nearest_cell(ds[la].values, ds[lo].values, lat, lon, la, lo,
                             input_path, single_max)
        ds = ds.isel({k: v for k, v in cell.items() if k in ds.dims})
        extra = [d for d in ds.dims if d != tname]
        if any(ds.sizes[d] > 1 for d in extra):
            raise ForcingError(f"{input_path}: extra dimension(s) "
                               f"{ {d: ds.sizes[d] for d in extra} }; cannot pick one series")
        ds = ds.isel({d: 0 for d in extra})
        names = [v for v in ds.data_vars if ds[v].dims == (tname,)]
        df = ds[names].to_dataframe()
    df.index = _naive_wall_times(df.index, input_path)
    df = _window(df, start_date, end_date)
    _no_inf(df, input_path)          # before any clip/max can hide it

    # Unit conversions for ERA5
    result = pd.DataFrame(index=df.index)
    if any(v in df.columns for v in ("ssrd", "strd", "tp", "sf")):
        # hourly accumulations: only a 3600 s axis is valid (checked in main)
        result.attrs["timestep_seconds"] = 3600

    # Temperature: ERA5 gives K, COSIPY expects K — no conversion
    if "t2m" in df.columns:
        result["T2"] = df["t2m"].values
    elif "T2" in df.columns:
        result["T2"] = df["T2"].values

    # Relative humidity from dewpoint
    if "d2m" in df.columns:
        if "t2m" not in df.columns:
            raise ForcingError(f"{input_path}: d2m given without t2m; cannot derive RH2")
        t2 = df["t2m"].values
        d2 = df["d2m"].values
        # Magnus formula: RH = 100 * exp(17.625*Td/(243.04+Td)) / exp(17.625*T/(243.04+T))
        # where Td and T are in Celsius
        t2c = t2 - 273.16
        d2c = d2 - 273.16
        rh = 100.0 * np.exp(17.625 * d2c / (243.04 + d2c)) / np.exp(17.625 * t2c / (243.04 + t2c))
        result["RH2"] = np.clip(rh, 0.0, 100.0)
    elif "RH2" in df.columns:
        result["RH2"] = df["RH2"].values

    # Wind speed: ERA5 gives u10, v10 at 10m; COSIPY expects U2 at 2m
    if "u10" in df.columns and "v10" in df.columns:
        u10 = np.sqrt(df["u10"].values ** 2 + df["v10"].values ** 2)
        # Log wind profile correction: U2 = U10 * ln(2/z0) / ln(10/z0)
        z0 = 0.001  # roughness length in m (typical for snow)
        result["U2"] = u10 * np.log(2.0 / z0) / np.log(10.0 / z0)
    elif "U2" in df.columns:
        result["U2"] = df["U2"].values

    # Shortwave radiation: ERA5 gives accumulated J/m2, convert to W/m2
    if "ssrd" in df.columns:
        # ERA5 hourly: J/m2 summed over the hour -> mean W/m2 (the 3600 s
        # step is declared above and enforced by the time-axis check)
        ssrd = df["ssrd"].values
        dt_seconds = 3600.0
        result["G"] = np.maximum(ssrd / dt_seconds, 0.0)
    elif "G" in df.columns:
        result["G"] = np.maximum(df["G"].values, 0.0)

    # Longwave radiation: ERA5 gives accumulated J/m2
    if "strd" in df.columns:
        strd = df["strd"].values
        dt_seconds = 3600.0
        result["LWin"] = np.maximum(strd / dt_seconds, 0.0)
    elif "LWin" in df.columns:
        result["LWin"] = df["LWin"].values

    # Pressure: ERA5 gives Pa, COSIPY expects hPa
    if "sp" in df.columns:
        result["PRES"] = df["sp"].values / 100.0
    elif "PRES" in df.columns:
        result["PRES"] = df["PRES"].values

    # Precipitation: ERA5 gives m accumulated, COSIPY expects mm per timestep
    if "tp" in df.columns:
        result["RRR"] = np.maximum(df["tp"].values * 1000.0, 0.0)  # m -> mm
    elif "RRR" in df.columns:
        result["RRR"] = np.maximum(df["RRR"].values, 0.0)

    # Cloud cover (if available)
    if "tcc" in df.columns:
        result["N"] = np.clip(df["tcc"].values, 0.0, 1.0)
    elif "N" in df.columns:
        result["N"] = df["N"].values

    # Snowfall (if available)
    if "sf" in df.columns:
        # ERA5 snowfall in m w.e., convert to m snow height
        density_fresh = 250.0  # approximate fresh snow density
        result["SNOWFALL"] = np.maximum(df["sf"].values * 1000.0 / density_fresh, 0.0)
    elif "SNOWFALL" in df.columns:
        result["SNOWFALL"] = df["SNOWFALL"].values

    return result


def read_aws_data(input_path: str, start_date: str, end_date: str,
                  temp_in_celsius: bool = False) -> pd.DataFrame:
    """Read AWS station CSV data (COSIPY point CSV layout, see read_point_csv).

    Args:
        input_path: Path to CSV file.
        start_date: Start date.
        end_date: End date.
        temp_in_celsius: If True, convert temperature from C to K.

    Returns:
        DataFrame with forcing data.
    """
    df = read_point_csv(input_path, start_date, end_date)

    if temp_in_celsius and "T2" in df.columns:
        df["T2"] = df["T2"] + 273.16

    return df


def apply_lapse_rates(df: pd.DataFrame, station_alt: float, target_alt: float,
                      lapse_T: float = -0.006, lapse_RH: float = 0.0,
                      lapse_RRR: float = 0.0) -> pd.DataFrame:
    """Apply lapse rate corrections for elevation difference.

    Args:
        df: Forcing dataframe.
        station_alt: Station elevation (m).
        target_alt: Target grid cell elevation (m).
        lapse_T: Temperature lapse rate (K/m), default -0.006.
        lapse_RH: Relative humidity lapse rate (%/m), default 0.
        lapse_RRR: Precipitation lapse rate (mm/m), default 0.

    Returns:
        Corrected dataframe.
    """
    dz = target_alt - station_alt

    if "T2" in df.columns:
        df["T2"] = df["T2"] + dz * lapse_T

    if "RH2" in df.columns:
        df["RH2"] = np.clip(df["RH2"] + dz * lapse_RH, 0.0, 100.0)

    if "RRR" in df.columns:
        df["RRR"] = np.maximum(df["RRR"] + dz * lapse_RRR, 0.0)

    return df


def validate_forcing(df: pd.DataFrame) -> list:
    """Validate forcing data ranges.

    Args:
        df: Forcing dataframe.

    Returns:
        List of warning messages (empty if all OK).
    """
    warnings = []

    for var_name, spec in COSIPY_VARIABLES.items():
        if var_name not in df.columns:
            continue

        values = df[var_name].dropna()
        if len(values) == 0:
            warnings.append(f"WARNING: {var_name} has no valid data")
            continue

        lo, hi = spec["bounds"]
        vmin, vmax = values.min(), values.max()

        if vmin < lo:
            warnings.append(f"WARNING: {var_name} min={vmin:.2f} < lower bound {lo} ({spec['units']})")
        if vmax > hi:
            warnings.append(f"WARNING: {var_name} max={vmax:.2f} > upper bound {hi} ({spec['units']})")

        # Unit detection heuristics
        if var_name == "T2" and vmax < 100:
            warnings.append(f"UNIT TRAP: T2 max={vmax:.1f} — likely Celsius, needs +273.16 for Kelvin")
        if var_name == "RH2" and vmax < 1.5:
            warnings.append(f"UNIT TRAP: RH2 max={vmax:.3f} — likely fraction (0-1), needs *100 for %")
        if var_name == "PRES" and vmin > 2000:
            warnings.append(f"UNIT TRAP: PRES min={vmin:.0f} — likely Pa, needs /100 for hPa")
        if var_name == "G" and vmax > 2000:
            warnings.append(f"UNIT TRAP: G max={vmax:.0f} — likely J/m2 accumulated, needs /dt_s for W/m2")
        if var_name == "N" and vmax > 1.5:
            warnings.append(f"UNIT TRAP: N max={vmax:.1f} — likely %, needs /100 for fraction")
        if var_name == "SNOWFALL" and vmax > 0.1:
            warnings.append(f"UNIT TRAP: SNOWFALL max={vmax:.3f} — likely mm or m w.e., check units")

    # Check for NaN
    nan_counts = df.isna().sum()
    for col, count in nan_counts.items():
        if count > 0:
            warnings.append(f"WARNING: {col} has {count} NaN values ({count/len(df)*100:.1f}%)")

    return warnings


def read_nasa_power_data(lat: float, lon: float, start_year: int, end_year: int,
                         freq: str = "hourly", period=None) -> pd.DataFrame:
    """Fetch NASA POWER forcing via ki_tools_common.load_forcing and map to COSIPY.

    This is the canonical HydroCraft forcing path referenced in SKILL.md
    ("Use ki_tools_common.load_forcing for CMFD/MSWX/NASA POWER"). It returns a
    time-indexed DataFrame with COSIPY variable columns already in COSIPY units:
        T2 (K), RH2 (%), U2 (m/s, 2 m), G (W/m2), LWin (W/m2), PRES (hPa),
        RRR (mm per timestep).
    U2 is the loader's wind2_ms (POWER WS2M); wind_ms is the 10 m wind.
    RH2 is derived from NASA POWER specific humidity (QV2M) using the shared
    ki_tools_common.humidity converter.

    Args:
        lat, lon: point location (deg).
        start_year, end_year: inclusive period.
        freq: "hourly" (dt=3600 s) or "daily" (dt=86400 s).
        period: optional (start, end) dates, end included, passed to the
            loader so only the days actually used must be complete.

    Returns:
        DataFrame indexed by timestamp with COSIPY forcing columns.
    """
    from ki_tools_common.load_forcing import load_hourly_forcing, load_daily_forcing
    from ki_tools_common.humidity import specific_humidity_to_rh

    if freq == "hourly":
        d = load_hourly_forcing("nasa_power", lat, lon, start_year, end_year,
                                period=period)
    elif freq == "daily":
        d = load_daily_forcing("nasa_power", lat, lon, start_year, end_year,
                               period=period)
    else:
        raise ValueError(f"freq must be 'hourly' or 'daily', got {freq}")

    _no_inf({k: v for k, v in d.items() if k != "dates"}, "NASA POWER")
    # hourly returns 'temp_c'; daily returns 'temp_mean_c'
    temp_c = np.asarray(d.get("temp_c", d.get("temp_mean_c")), dtype=float)
    pres_pa = np.asarray(d["pres_pa"], dtype=float)
    temp_k = temp_c + 273.16
    rh = specific_humidity_to_rh(np.asarray(d["shum_kgkg"], dtype=float), temp_k, pres_pa)

    out = pd.DataFrame(index=pd.DatetimeIndex(d["dates"], name="TIMESTAMP"))
    out["T2"] = temp_k
    out["RH2"] = np.clip(rh, 0.0, 100.0)
    # COSIPY needs the 2 m wind. The shared loader's wind_ms is the 10 m wind
    # (WS10M, wind_height_m = 10); the 2 m wind (WS2M) is wind2_ms.
    if "wind2_ms" not in d or d["wind2_ms"] is None:
        raise ForcingError("NASA POWER loader returned no 2 m wind (wind2_ms); "
                           "the 10 m wind is not used in its place.")
    out["U2"] = np.asarray(d["wind2_ms"], dtype=float)
    out["G"] = np.maximum(np.asarray(d["srad_wm2"], dtype=float), 0.0)
    if "lrad_wm2" in d and d["lrad_wm2"] is not None:
        out["LWin"] = np.maximum(np.asarray(d["lrad_wm2"], dtype=float), 0.0)
    out["PRES"] = pres_pa / 100.0                              # Pa -> hPa
    out["RRR"] = np.maximum(np.asarray(d["precip_mm"], dtype=float), 0.0)  # mm per timestep
    out.attrs["timestep_seconds"] = d.get("timestep_seconds",
                                          3600 if freq == "hourly" else 86400)
    return out


def write_cosipy_netcdf(df: pd.DataFrame, static_ds: xr.Dataset,
                        output_path: str, point_lat: float, point_lon: float,
                        hgt: float = 5000.0, slope: float = 0.0,
                        aspect: float = 0.0, mask: int = 1, dt_seconds: int = None):
    """Write COSIPY-format netCDF input file.

    Args:
        df: Forcing dataframe (time-indexed).
        static_ds: Static dataset with HGT, SLOPE, ASPECT, MASK.
        output_path: Output file path.
        point_lat: Latitude for point model.
        point_lon: Longitude for point model.
    """
    # Create dataset
    ds = xr.Dataset()

    # Coordinates
    ds.coords["time"] = ("time", df.index.values)
    ds.coords["lat"] = ("lat", [point_lat])
    ds.coords["lon"] = ("lon", [point_lon])

    ds.lat.attrs = {"standard_name": "latitude", "units": "degrees_north"}
    ds.lon.attrs = {"standard_name": "longitude", "units": "degrees_east"}

    # Static variables from static file or defaults
    if static_ds is not None:
        for var in STATIC_VARIABLES:
            if var in static_ds:
                ds[var] = (("lat", "lon"), static_ds[var].values.reshape(1, 1))
    else:
        # Point-mode static defaults (explicit HGT critical: COSIPY uses elevation
        # for pressure/radiation reference; the old hard-coded 5000 m is wrong for
        # most sites). MASK=1 makes the single cell an active snow/ice column.
        ds["HGT"] = (("lat", "lon"), np.array([[float(hgt)]]))
        ds["SLOPE"] = (("lat", "lon"), np.array([[float(slope)]]))
        ds["ASPECT"] = (("lat", "lon"), np.array([[float(aspect)]]))
        ds["MASK"] = (("lat", "lon"), np.array([[int(mask)]]))

    # Time-varying forcing variables
    metadata = {
        "T2": ("K", "Temperature at 2 m"),
        "RH2": ("%", "Relative humidity at 2 m"),
        "U2": ("m s-1", "Wind velocity at 2 m"),
        "G": ("W m-2", "Incoming shortwave radiation"),
        "PRES": ("hPa", "Atmospheric Pressure"),
        "RRR": ("mm", "Total precipitation"),
        "N": ("%", "Cloud cover fraction"),
        "LWin": ("W m-2", "Incoming longwave radiation"),
        "SNOWFALL": ("m", "Snowfall"),
    }

    for var_name in metadata:
        if var_name in df.columns:
            data = df[var_name].values.reshape(-1, 1, 1)
            units, long_name = metadata[var_name]
            ds[var_name] = (("time", "lat", "lon"), data)
            ds[var_name].attrs = {"units": units, "long_name": long_name}

    # Write
    if dt_seconds is not None:
        # COSIPY reads dt from constants.toml, not from this file; the attr
        # records the forcing step so a run can be checked against it.
        ds.attrs["time_step_seconds"] = int(dt_seconds)
    ds.to_netcdf(output_path)
    print(f"Output written: {output_path}")
    print(f"  Time steps: {len(df)}")
    print(f"  Variables: {list(ds.data_vars)}")


def validate_output(output_path: str) -> bool:
    """Validate the output netCDF file.

    Args:
        output_path: Path to output file.

    Returns:
        True if valid.
    """
    ds = xr.open_dataset(output_path)

    required = ["T2", "RH2", "U2", "G", "PRES", "MASK", "HGT"]
    missing = [v for v in required if v not in ds.data_vars and v not in ds.coords]
    if missing:
        print(f"ERROR: Missing required variables: {missing}")
        ds.close()
        return False

    # Check for either RRR or SNOWFALL
    if "RRR" not in ds.data_vars and "SNOWFALL" not in ds.data_vars:
        print("ERROR: Need at least one of RRR or SNOWFALL")
        ds.close()
        return False

    # Check for either LWin or N
    if "LWin" not in ds.data_vars and "N" not in ds.data_vars:
        print("ERROR: Need at least one of LWin or N (cloud cover)")
        ds.close()
        return False

    bad = {v: int((~np.isfinite(ds[v].values.astype(float))).sum()) for v in ds.data_vars}
    bad = {v: n for v, n in bad.items() if n > 0}
    if bad:
        print(f"ERROR: missing or non-finite values in output variables {bad}")
        ds.close()
        return False

    print("Output validation: PASSED")
    ds.close()
    return True


REQUIRED_FORCING = ("T2", "RH2", "U2", "G", "PRES")


def _read_and_check(args):
    """Read the forcing, then check it fully before anything is written.

    Missing forcing is a failure, not a warning: no value or time stamp is
    filled in. Returns (df with only COSIPY forcing columns, step seconds).
    """
    # Read data based on source
    if args.source == "nasa_power":
        # Canonical HydroCraft forcing path (ki_tools_common.load_forcing).
        # --input is ignored for this source (data is fetched from the API).
        if not args.start or not args.end:
            raise ForcingError("--start and --end (YYYY-MM-DD) required for nasa_power source")
        sy, ey = int(args.start[:4]), int(args.end[:4])
        df = read_nasa_power_data(args.lat, args.lon, sy, ey, freq=args.freq,
                                  period=(args.start, args.end))
        df = _window(df, args.start, args.end)
    else:
        validate_inputs(args.input, args.source)
        if args.source == "era5":
            df = read_era5_data(args.input, args.start, args.end, args.lat, args.lon,
                                 args.max_offset_deg)
        elif args.source == "aws":
            df = read_aws_data(args.input, args.start, args.end, args.temp_celsius)
        else:
            df = read_point_csv(args.input, args.start, args.end)
    declared = df.attrs.get("timestep_seconds")

    # Only COSIPY forcing fields are written; other columns (comments, flags,
    # station ids, ...) are ignored and are not checked.
    fcols = [c for c in COSIPY_VARIABLES if c in df.columns]
    df = df[fcols].copy()
    for c in fcols:
        if not pd.api.types.is_numeric_dtype(df[c]):
            num = pd.to_numeric(df[c], errors="coerce")
            bad = num.isna() & df[c].notna()
            if bad.any():
                raise ForcingError(f"{c} has non-numeric value(s), first "
                                   f"{df[c][bad].iloc[0]!r} at {df.index[bad][0]}")
            df[c] = num.astype(float)
        inf = np.isinf(df[c].to_numpy(dtype=float))
        if inf.any():
            raise ForcingError(f"{c} has {int(inf.sum())} infinite value(s), first at "
                               f"{df.index[inf][0]}")
    # A forcing column that is empty over the whole period was not supplied:
    # drop it, as COSIPY's aws2cosipy does (df.dropna(axis=1, how="all")).
    # Its role must then be covered by another field (checked next).
    empty = [c for c in fcols if len(df) and df[c].isna().all()]
    if empty:
        print(f"NOTE: forcing column(s) {empty} are empty for the whole period; "
              f"treated as not supplied.")
        df = df.drop(columns=empty)
    miss = [v for v in REQUIRED_FORCING if v not in df.columns]
    if "RRR" not in df.columns and "SNOWFALL" not in df.columns:
        miss.append("RRR or SNOWFALL")
    if "LWin" not in df.columns and "N" not in df.columns:
        miss.append("LWin or N")
    if len(df) and miss:
        raise ForcingError(f"required COSIPY forcing missing: {miss}")

    # Optional elevation lapse correction (forcing source alt -> target site alt)
    if args.station_alt is not None and args.target_alt is not None:
        df = apply_lapse_rates(df, args.station_alt, args.target_alt, lapse_T=args.lapse_t)
        print(f"Applied lapse correction: {args.station_alt:.0f} m -> {args.target_alt:.0f} m "
              f"(dT={args.lapse_t * (args.target_alt - args.station_alt):+.2f} K)")

    # Validate forcing
    warnings = validate_forcing(df)
    for w in warnings:
        print(w)

    if any("UNIT TRAP" in w for w in warnings):
        print("\n*** UNIT TRAPS DETECTED — review warnings above before proceeding ***")

    if len(df) == 0:
        raise ForcingError(f"no forcing rows in {args.start}..{args.end}")
    # The time axis must be the complete grid from --start to --end (or the
    # first..last row when no window is given) at the data's own step: no
    # missing stamp (not a NaN, so the NaN check cannot see it), no duplicate,
    # in order. The step is the reader's declared step when it has one
    # (NASA POWER hourly/daily, ERA5 hourly accumulations), so a single
    # record is valid; otherwise it is read from the rows (needs 2 rows).
    idx = pd.DatetimeIndex(df.index)
    d = np.diff(idx.values).astype("timedelta64[s]").astype(np.int64)
    if (d <= 0).any():
        i = int(np.flatnonzero(d <= 0)[0])
        raise ForcingError(f"time axis duplicated or out of order at {idx[i + 1]}")
    if declared:
        step_s = int(declared)
        if (d != step_s).any():
            i = int(np.flatnonzero(d != step_s)[0])
            raise ForcingError(f"time step {int(d[i])} s at {idx[i + 1]} differs from "
                               f"the source's {step_s} s step")
    else:
        if len(idx) < 2:
            raise ForcingError(f"only {len(idx)} forcing row and the source declares no "
                               f"time step; cannot tell COSIPY's dt")
        step_s = int(d.min())
    step = pd.Timedelta(seconds=step_s)
    t0, t1 = _window_bounds(args.start, args.end)
    lo = t0 if t0 is not None else idx[0]
    hi = t1 if t1 is not None else idx[-1]
    phase = (idx[0] - lo) % step
    want = pd.date_range(lo + phase, hi, freq=step)
    if len(idx) != len(want) or not (idx == want).all():
        lost = want.difference(idx)
        raise ForcingError(
            f"time axis is not complete at step {step}: {len(lost)} of {len(want)} "
            f"stamps missing (first: {', '.join(str(x) for x in lost[:5])}), "
            f"{len(idx.difference(want))} off the grid")

    nan_cols = {c: int(n) for c, n in df.isna().sum().items() if n > 0}
    if nan_cols:
        first = {c: str(df.index[df[c].isna().to_numpy()][0]) for c in nan_cols}
        raise ForcingError(f"missing forcing values {nan_cols} (first: {first})")
    return df, step_s


def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to COSIPY format")
    parser.add_argument("-i", "--input", default=None,
                        help="Input data file (CSV or netCDF); not needed for --source nasa_power")
    parser.add_argument("-o", "--output", required=True, help="Output COSIPY netCDF file")
    parser.add_argument("-s", "--static", default=None, help="Static file (optional)")
    parser.add_argument("--source", default="generic",
                        choices=["era5", "aws", "csv", "wrf", "generic", "nasa_power"])
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--lat", type=float, default=30.47, help="Latitude")
    parser.add_argument("--lon", type=float, default=90.64, help="Longitude")
    parser.add_argument("--temp-celsius", action="store_true", help="Temperature is in Celsius")
    parser.add_argument("--freq", default="hourly", choices=["hourly", "daily"],
                        help="NASA POWER timestep. COSIPY's dt is NOT set by this file: "
                             "set GENERAL dt in constants.toml to the printed step")
    parser.add_argument("--hgt", type=float, default=5000.0,
                        help="Point elevation (m) embedded as static HGT")
    parser.add_argument("--slope", type=float, default=0.0, help="Point slope (deg)")
    parser.add_argument("--aspect", type=float, default=0.0, help="Point aspect (deg)")
    parser.add_argument("--station-alt", type=float, default=None,
                        help="Forcing source elevation (m) for lapse correction")
    parser.add_argument("--target-alt", type=float, default=None,
                        help="Target site elevation (m) for lapse correction")
    parser.add_argument("--lapse-t", type=float, default=-0.0065,
                        help="Temperature lapse rate (K/m) for lapse correction")
    parser.add_argument("--max-offset-deg", type=float, default=SINGLE_CELL_MAX_OFFSET_DEG,
                        help="Largest allowed distance (deg) between --lat/--lon and the "
                             "cell of a single-cell ERA5/static file (default: half the "
                             "0.25 deg ERA5 spacing)")
    args = parser.parse_args()

    try:
        if not (np.isfinite(args.lat) and np.isfinite(args.lon) and -90 <= args.lat <= 90):
            raise ForcingError(f"--lat/--lon ({args.lat}, {args.lon}) is not a valid place")
        df, step_s = _read_and_check(args)
    except ForcingError as e:
        print(f"ERROR: {e}; nothing is filled in and nothing is written.")
        sys.exit(1)

    # Read static file if provided
    static_ds = None
    if args.static:
        static_ds = xr.open_dataset(args.static)
        try:
            static_ds = static_ds.isel(_nearest_cell(
                static_ds["lat"].values, static_ds["lon"].values,
                args.lat, args.lon, "lat", "lon", args.static, args.max_offset_deg))
        except ForcingError as e:
            print(f"ERROR: {e}; nothing is written.")
            sys.exit(1)

    # Write output
    write_cosipy_netcdf(df, static_ds, args.output, args.lat, args.lon,
                        hgt=args.hgt, slope=args.slope, aspect=args.aspect,
                        dt_seconds=step_s)
    print(f"  Forcing step: {step_s} s -> set GENERAL dt = {step_s} in COSIPY "
          f"constants.toml (COSIPY does not read it from the input file)")

    # Validate output: a failed check removes the file and exits non-zero
    ok = validate_output(args.output)

    if static_ds is not None:
        static_ds.close()
    if not ok:
        os.remove(args.output)
        print(f"ERROR: output failed validation; {args.output} removed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
