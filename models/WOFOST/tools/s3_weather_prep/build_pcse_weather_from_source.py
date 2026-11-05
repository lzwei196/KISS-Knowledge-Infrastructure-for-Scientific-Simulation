#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_pcse_weather_from_source
Stage:        s3_weather_prep
Description:  Build the PCSE CSVWeatherDataProvider file for ONE point straight
              from a weather product (cmfd, mswx or nasa_power), read through
              the shared loader ki_tools_common.load_forcing.load_daily_forcing.
              This is the KI's only route from a gridded / API weather source
              to PCSE weather. No other model's input files are involved.

              Loader value            -> PCSE CSV column
                srad_wm2 (24-h mean)  -> IRRAD kJ/m2/day  (W/m2 x 86.4)
                temp_min_c            -> TMIN  deg C
                temp_max_c            -> TMAX  deg C
                shum_kgkg + pres_pa   -> VAP   kPa   e = q*p / (0.622 + 0.378*q)
                wind_ms               -> WIND  m/s  (as the source gives it)
                precip_mm (mm in day) -> RAIN  mm/day
                (none)                -> SNOWDEPTH NaN

              The file is written by write_pcse_csv() of
              create_csv_weather_file.py (the ONE writer in this KI).

              No made-up values. The tool stops with exit code 2 and writes
              NOTHING when: a needed value is missing or not finite, the time
              axis is not one row per day, the period start_year-01-01 ..
              end_year-12-31 is not fully covered, or a value is outside what
              the unit allows (negative rain / radiation / wind, humidity or
              pressure <= 0, TMIN > TMAX).

Usage:
  python build_pcse_weather_from_source.py --source nasa_power \\
      --lat 41.5 --lon -93.5 --elev 300 --start_year 2016 --end_year 2020 \\
      --output weather_pcse_41.50_-93.50.csv
  python build_pcse_weather_from_source.py --source cmfd --forcing_dir <CMFD 3-hourly dir> \\
      --lat 36.5 --lon 116.5 --elev 30 --start_year 2015 --end_year 2015 \\
      --output weather_pcse_36.50_116.50.csv

Outputs:
  - <output>                 PCSE CSV weather file
  - <output>.summary.json    source, point, period, annual rain, mean T

Notes:
  - Give every point its own output file NAME: PCSE caches a loaded CSV under
    the file's basename only (dt_018).
  - mswx sits on an exfat disk that wedges under parallel reads; this tool makes
    the shared reader run one file at a time. Never run two mswx builds at once.
  - WIND is written at the source's own height (cmfd / mswx / nasa_power: 10 m).

Exit codes:
  0 — success, 1 — input error, 2 — refused (bad or missing data), 3 — output error
"""

import argparse
import datetime as _dt
import hashlib
import json
import logging
import math
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in ["KISSPATH_KI_TOOLS_COMMON"]:
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")) and _cand not in sys.path:
        sys.path.insert(0, _cand)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

SOURCES = ("cmfd", "mswx", "nasa_power")
# CMFD is a China product; the shared loader takes the nearest cell with no
# domain check, so a point outside the grid would silently get an edge cell.
CMFD_BOX = {"lat": (15.0, 55.0), "lon": (70.0, 140.0)}
# MSWX variables this tool needs (LWd is not read: one year of one variable is
# a whole-file decompression).
MSWX_VARIABLES = ("P", "Tair", "SWd", "Wind", "spechum", "Pres")
NEEDED = ("srad_wm2", "temp_min_c", "temp_max_c", "wind_ms", "precip_mm",
          "shum_kgkg", "pres_pa")


class WeatherRefused(Exception):
    """The source data cannot be turned into a PCSE file without making values up."""


class _SerialExecutor:
    """Stand-in for ProcessPoolExecutor that runs the tasks one after another.

    The shared MSWX reader fans its per-file reads out over processes. The MSWX
    store sits on an exfat disk that wedges under parallel reads, so this tool
    makes that reader run ONE file at a time.
    """

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, *iterables):
        return [fn(*a) for a in zip(*iterables)]


def load_source(source, lat, lon, start_year, end_year, forcing_dir=None):
    """Call the shared loader (the only place weather is read from a product)."""
    from ki_tools_common.load_forcing import load_daily_forcing
    if source != "mswx":
        return load_daily_forcing(source, lat, lon, start_year, end_year,
                                  forcing_dir=forcing_dir)
    import concurrent.futures as cf
    saved = cf.ProcessPoolExecutor
    cf.ProcessPoolExecutor = _SerialExecutor
    try:
        return load_daily_forcing(source, lat, lon, start_year, end_year,
                                  forcing_dir=forcing_dir, variables=MSWX_VARIABLES)
    finally:
        cf.ProcessPoolExecutor = saved


def vap_kpa(shum_kgkg, pres_pa):
    """Actual vapour pressure (kPa) from specific humidity and air pressure."""
    q = float(shum_kgkg)
    return ((q * float(pres_pa)) / (0.622 + 0.378 * q)) / 1000.0


def check_forcing(forcing, start_year, end_year):
    """Refuse anything that is not a complete, finite, daily record of the period.

    Returns the list of datetime.date, one per day.
    """
    import numpy as np
    import pandas as pd

    missing = [k for k in ("dates",) + NEEDED if k not in forcing or forcing[k] is None]
    if missing:
        raise WeatherRefused(f"loader result has no {missing}")
    try:
        days = [d.date() for d in pd.to_datetime([str(d) for d in forcing["dates"]])]
    except Exception as e:
        raise WeatherRefused(f"dates cannot be read: {e}")
    n = len(days)
    if n == 0:
        raise WeatherRefused("loader returned no days")
    for k in NEEDED:
        if len(forcing[k]) != n:
            raise WeatherRefused(f"{k} has {len(forcing[k])} values, dates has {n}")

    first, last = _dt.date(start_year, 1, 1), _dt.date(end_year, 12, 31)
    for i in range(1, n):
        if (days[i] - days[i - 1]).days != 1:
            raise WeatherRefused(f"time axis is not one row per day: {days[i - 1]} is "
                                 f"followed by {days[i]}")
    if days[0] != first or days[-1] != last:
        raise WeatherRefused(f"period not fully covered: asked {first}..{last}, "
                             f"source gave {days[0]}..{days[-1]}")

    arr = {k: np.asarray(forcing[k], dtype=float) for k in NEEDED}
    for k in NEEDED:
        bad = np.where(~np.isfinite(arr[k]))[0]
        if bad.size:
            raise WeatherRefused(f"{k}: {bad.size} missing / non-finite value(s), "
                                 f"first on {days[int(bad[0])]}")
    limits = (("precip_mm", arr["precip_mm"] < 0, "negative rain"),
              ("srad_wm2", arr["srad_wm2"] < 0, "negative radiation"),
              ("wind_ms", arr["wind_ms"] < 0, "negative wind"),
              ("shum_kgkg", arr["shum_kgkg"] <= 0, "specific humidity <= 0"),
              ("pres_pa", arr["pres_pa"] <= 0, "pressure <= 0"),
              ("temp_min_c", arr["temp_min_c"] > arr["temp_max_c"], "TMIN > TMAX"))
    for k, mask, what in limits:
        bad = np.where(mask)[0]
        if bad.size:
            raise WeatherRefused(f"{k}: {what} on {bad.size} day(s), first on "
                                 f"{days[int(bad[0])]}")
    return days


def forcing_to_frame(forcing, days):
    """Loader dict -> DataFrame in the PCSE CSV units.

    The loader values are first rounded as the generic weather CSV of the earlier
    in-script chain held them (2 decimals; VAP and RAIN 4), so this tool gives
    the same file, value for value, as that chain did.
    """
    import pandas as pd
    r2 = lambda x: float(f"{float(x):.2f}")   # noqa: E731
    r4 = lambda x: float(f"{float(x):.4f}")   # noqa: E731
    n = len(days)
    return pd.DataFrame({
        "date": pd.to_datetime([d.isoformat() for d in days]),
        "IRRAD": [r2(forcing["srad_wm2"][i]) * 86.4 for i in range(n)],   # W/m2 -> kJ/m2/day
        "TMIN": [r2(forcing["temp_min_c"][i]) for i in range(n)],
        "TMAX": [r2(forcing["temp_max_c"][i]) for i in range(n)],
        "VAP": [r4(vap_kpa(forcing["shum_kgkg"][i], forcing["pres_pa"][i])) for i in range(n)],
        "WIND": [r2(forcing["wind_ms"][i]) for i in range(n)],
        "RAIN": [r4(forcing["precip_mm"][i]) for i in range(n)],          # mm/day
    })


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_from_forcing(forcing, source, lat, lon, elev, start_year, end_year, output,
                       summary=None):
    """Check a loader dict and write the PCSE CSV + summary. Nothing is written on refusal."""
    import numpy as np
    from create_csv_weather_file import write_pcse_csv

    days = check_forcing(forcing, start_year, end_year)
    df = forcing_to_frame(forcing, days)

    output = os.path.abspath(output)
    summary = os.path.abspath(summary) if summary else output + ".summary.json"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".tmp"
    try:
        write_pcse_csv(df, tmp, lat, lon, elev,
                       f"{source} via ki_tools_common.load_forcing.load_daily_forcing")
        os.replace(tmp, output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    rain = np.asarray(forcing["precip_mm"], dtype=float)
    years = np.array([d.year for d in days])
    rain_by_year = {str(y): round(float(rain[years == y].sum()), 1)
                    for y in range(start_year, end_year + 1)}
    tmean = forcing.get("temp_mean_c")
    if tmean is not None and len(tmean) == len(days) and np.all(np.isfinite(np.asarray(tmean, float))):
        mean_t, mean_t_from = float(np.mean(np.asarray(tmean, float))), "temp_mean_c"
    else:
        mean_t = float(np.mean((np.asarray(forcing["temp_min_c"], float)
                                + np.asarray(forcing["temp_max_c"], float)) / 2.0))
        mean_t_from = "(TMIN+TMAX)/2"
    info = {
        "tool": "build_pcse_weather_from_source",
        "source": source,
        "lat": lat, "lon": lon, "elev_m": elev,
        "period": f"{days[0].isoformat()}..{days[-1].isoformat()}",
        "n_days": len(days),
        "annual_rain_mm": rain_by_year,
        "mean_annual_rain_mm": round(float(np.mean(list(rain_by_year.values()))), 1),
        "mean_temp_c": round(mean_t, 2),
        "mean_temp_from": mean_t_from,
        "mean_irrad_kj_m2_day": round(float(df["IRRAD"].mean()), 1),
        "mean_vap_kpa": round(float(df["VAP"].mean()), 3),
        "mean_wind_ms": round(float(df["WIND"].mean()), 2),
        "wind_note": "WIND is at the source's own height (cmfd/mswx/nasa_power: 10 m), not reduced to 2 m",
        "units": {"IRRAD": "kJ/m2/day", "TMIN": "degC", "TMAX": "degC", "VAP": "kPa",
                  "WIND": "m/s", "RAIN": "mm/day", "SNOWDEPTH": "NaN (not given)"},
        "output_file": output,
        "output_sha256": _sha256(output),
    }
    with open(summary, "w") as fh:
        json.dump(info, fh, indent=2)
    info["summary_file"] = summary
    logger.info(f"Created: {output} ({len(days)} days, {source})")
    return info


def build(source, lat, lon, elev, start_year, end_year, output, forcing_dir=None,
          summary=None):
    """Read one point from the source and write its PCSE weather file."""
    source = str(source).lower().strip()
    if source not in SOURCES:
        raise ValueError(f"--source must be one of {SOURCES}, got {source!r}")
    if end_year < start_year:
        raise ValueError(f"end_year {end_year} is before start_year {start_year}")
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 360.0):
        raise ValueError(f"point ({lat},{lon}) is not a lat/lon")
    if source in ("cmfd", "mswx"):
        if not forcing_dir or not os.path.isdir(forcing_dir):
            raise ValueError(f"--forcing_dir is needed for {source} and must exist: {forcing_dir}")
    if source == "cmfd" and not (CMFD_BOX["lat"][0] <= lat <= CMFD_BOX["lat"][1]
                                 and CMFD_BOX["lon"][0] <= lon <= CMFD_BOX["lon"][1]):
        raise WeatherRefused(f"point ({lat},{lon}) is outside the CMFD (China) grid; "
                             f"use mswx or nasa_power")
    try:
        forcing = load_source(source, lat, lon, start_year, end_year, forcing_dir)
    except Exception as e:
        raise WeatherRefused(f"{source} could not give {start_year}-{end_year} at "
                             f"({lat},{lon}): {type(e).__name__}: {e}")
    return build_from_forcing(forcing, source, lat, lon, elev, start_year, end_year,
                              output, summary)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build a PCSE CSV weather file for one point from cmfd, mswx or "
                    "nasa_power (shared loader). Refuses gaps and missing values.")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--elev", type=float, required=True, help="site elevation, m")
    ap.add_argument("--start_year", type=int, required=True)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--forcing_dir", default=None, help="root folder of the product (cmfd, mswx)")
    ap.add_argument("--output", required=True, help="PCSE CSV weather file to write")
    ap.add_argument("--summary", default=None, help="summary JSON (default <output>.summary.json)")
    args = ap.parse_args(argv)
    if not math.isfinite(args.elev):
        logger.error("--elev must be a number")
        return 1
    try:
        info = build(args.source, args.lat, args.lon, args.elev, args.start_year,
                     args.end_year, args.output, args.forcing_dir, args.summary)
    except ValueError as e:
        logger.error(str(e))
        return 1
    except WeatherRefused as e:
        logger.error(f"REFUSED, nothing written: {e}")
        return 2
    except OSError as e:
        logger.error(f"cannot write: {e}")
        return 3
    print(json.dumps({"status": "success", **info}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
