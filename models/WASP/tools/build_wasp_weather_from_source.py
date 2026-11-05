#!/usr/bin/env python3
"""
build_wasp_weather_from_source.py -- daily weather for WASP 8.5 heat balance + wind reaeration.

Loads one grid cell with the shared loader (ki_tools_common.load_forcing.load_daily_forcing) and
writes the five WASP weather time functions the Advanced Eutrophication heat module reads:

  column            WASP time function (ISC)              unit     from loader key
  solar_wm2         Solar Radiation - 1 (4)               W/m2     srad_wm2 (daily mean)
  air_temp_c        Air Temperature Function 1 (17)       deg C    temp_mean_c
  dew_point_c       Dew Point Function 1 (29)             deg C    Magnus inverse of shum_kgkg+pres_pa
  wind_ms           Wind Speed Function 1 (21)            m/s      wind_ms (at wind_height_m, 10 m)
  cloud_frac        Cloud Cover Function 1 (25)           0-1      Kasten-Czeplak inverse of srad/Rso

Derived variables (the loader has no dew point or cloud cover):
  e  = q p / (0.622 + 0.378 q);  Td = 243.04 ln(e/611.2) / (17.625 - ln(e/611.2))   (Alduchov &
       Eskridge 1996 Magnus form; e, p in Pa)
  Rso = (0.75 + 2e-5 z) Ra  (FAO-56 eq. 37; Ra eq. 21);  C = ((1 - Rs/Rso)/0.75)^(1/3.4), clipped
       to [0, 1] (Kasten & Czeplak 1980).
validate_outputs() refuses physically impossible values (unit errors) and a dew point above air
temperature by more than 1 K on average; nothing is filled or clipped silently except cloud [0,1].

Usage
  python build_wasp_weather_from_source.py --source nasa_power --lat 41.95 --lon -81.55 \
      --start 2005-01-01 --end 2014-12-31 --elev 174 --out weather.csv
Exit codes: 0 ok; 1 load or validation failed; 2 bad command line.
"""
import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_KTC = Path(os.environ.get("KI_TOOLS_COMMON") or "KISSPATH_KI_TOOLS_COMMON"
            ).expanduser().absolute()
if _KTC.is_dir() and str(_KTC) not in sys.path:
    sys.path.insert(0, str(_KTC))
from ki_tools_common.load_forcing import load_daily_forcing  # noqa: E402

# CMFD folder: --forcing-dir -> $WASP_CMFD_DIR -> server default (other sources: the loader's own default)
DEFAULT_CMFD_DIR = "KISSPATH_FORCING/Data_forcing_01dy_010deg"
COLUMNS = ["date", "solar_wm2", "air_temp_c", "dew_point_c", "wind_ms", "cloud_frac"]


def dew_point_c(q, p):
    e = q * p / (0.622 + 0.378 * q)
    x = np.log(np.maximum(e, 1e-3) / 611.2)
    return 243.04 * x / (17.625 - x)


def clear_sky_wm2(dates, lat, elev):
    """FAO-56 clear-sky shortwave Rso (daily mean, W/m2)."""
    J = pd.DatetimeIndex(dates).dayofyear.values.astype(float)
    phi = math.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * J / 365)
    dl = 0.409 * np.sin(2 * np.pi * J / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dl), -1, 1))
    ra = (24 * 60 / np.pi) * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dl)
                                             + np.cos(phi) * np.cos(dl) * np.sin(ws))  # MJ/m2/d
    return (0.75 + 2e-5 * elev) * ra * 1e6 / 86400.0


def build(source, lat, lon, start, end, elev, forcing_dir=None):
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    if source == "cmfd" and not forcing_dir:
        forcing_dir = os.environ.get("WASP_CMFD_DIR") or DEFAULT_CMFD_DIR
    kw = {"forcing_dir": str(Path(forcing_dir).expanduser().absolute())} if forcing_dir else {}
    d = load_daily_forcing(source, lat, lon, t0.year, t1.year, **kw)
    df = pd.DataFrame({"date": pd.to_datetime(d["dates"])})
    df["solar_wm2"] = np.asarray(d["srad_wm2"], float)
    df["air_temp_c"] = np.asarray(d["temp_mean_c"], float)
    df["dew_point_c"] = dew_point_c(np.asarray(d["shum_kgkg"], float), np.asarray(d["pres_pa"], float))
    df["wind_ms"] = np.asarray(d["wind_ms"], float)
    rso = clear_sky_wm2(df["date"], lat, elev)
    kt = np.clip(df["solar_wm2"].values / rso, 0, 1)
    df["cloud_frac"] = np.clip(((1 - kt) / 0.75) ** (1 / 3.4), 0, 1)
    df = df[(df.date >= t0) & (df.date <= t1)].reset_index(drop=True)
    meta = {"source": source, "lat": lat, "lon": lon, "elev_m": elev,
            "wind_height_m": float(d.get("wind_height_m", float("nan")))}
    return df, meta


def validate_outputs(df, start, end):
    errs = []
    want = pd.date_range(start, end, freq="D")
    if len(df) != len(want) or not (df.date.values == want.values).all():
        errs.append(f"dates: got {len(df)} rows, need every day {start}..{end} ({len(want)})")
    for c in COLUMNS[1:]:
        if df[c].isna().any():
            errs.append(f"{c}: {int(df[c].isna().sum())} missing values")
    rng = {"solar_wm2": (0, 450), "air_temp_c": (-50, 50), "dew_point_c": (-60, 35),
           "wind_ms": (0, 40), "cloud_frac": (0, 1)}
    for c, (lo, hi) in rng.items():
        if df[c].min() < lo or df[c].max() > hi:
            errs.append(f"{c} outside [{lo},{hi}]: {df[c].min():.2f}..{df[c].max():.2f}")
    if not 50 <= df.solar_wm2.mean() <= 300:
        errs.append(f"mean solar {df.solar_wm2.mean():.1f} W/m2 not plausible (MJ/m2/d or J given?)")
    if (df.dew_point_c - df.air_temp_c).mean() > 1.0:
        errs.append("dew point above air temperature on average: humidity/pressure unit error")
    return errs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--source", required=True, choices=["nasa_power", "cmfd", "mswx"])
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--elev", type=float, default=0.0, help="site elevation m (clear-sky Rso)")
    ap.add_argument("--out", required=True, help="output CSV")
    ap.add_argument("--forcing-dir", help="forcing folder for the loader (cmfd: else $WASP_CMFD_DIR, else "
                                          f"{DEFAULT_CMFD_DIR}; other sources: the loader default)")
    a = ap.parse_args()
    if pd.Timestamp(a.end) < pd.Timestamp(a.start):
        print("ERROR: --end before --start", file=sys.stderr)
        return 2
    if a.source == "nasa_power":
        os.environ.setdefault("REALTIME", "1")
    try:
        df, meta = build(a.source, a.lat, a.lon, a.start, a.end, a.elev, a.forcing_dir)
    except Exception as e:  # loader errors are reported, never replaced by other data
        print(f"ERROR: loading {a.source} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    errs = validate_outputs(df, a.start, a.end)
    if errs:
        print("ERROR: weather failed validation:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 1
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        f.write("# " + " ".join(f"{k}={v}" for k, v in meta.items()) + "\n")
        df.to_csv(f, index=False, date_format="%Y-%m-%d", float_format="%.4f")
    print(f"wrote {a.out}: {len(df)} days; means solar {df.solar_wm2.mean():.1f} W/m2, "
          f"air {df.air_temp_c.mean():.2f} C, dew {df.dew_point_c.mean():.2f} C, "
          f"wind {df.wind_ms.mean():.2f} m/s @{meta['wind_height_m']} m, cloud {df.cloud_frac.mean():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
