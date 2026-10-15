#!/usr/bin/env python3
"""
convert_forcing_to_shaw.py — Build a SHAW weather file (.wea) DIRECTLY from a forcing source.

Standard path (--source nasa_power | cmfd | mswx, with --lat/--lon):
    the weather is read through the shared loader ki_tools_common.load_forcing
    (load_daily_forcing for --mode daily, load_hourly_forcing for --mode hourly).
    This tool does NOT open the source NetCDF files itself. The loader owns
    every source unit conversion
    (CMFD rain rate kg m-2 s-1 -> mm, K -> degC, POWER kW-hr -> W/m2, ...).

Other named inputs:
    --source csv --csv FILE          daily station table (RISMA / EC / AAFC export)

Output formats (SI units, IFLAGSI=1):
- Hourly (MTSTEP=0): JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR   (JH 0..23, local standard time)
- Daily  (MTSTEP=1): JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR      (SOLAR = daily MEAN W/m2)

What this tool converts (the loader output is already SI):
    - specific humidity (kg/kg) + pressure (Pa) -> dew point (daily) or RH % (hourly)
    - loader hourly time stamps are UTC -> shifted to local standard time (--utc_offset)
    - 3-hourly sources (CMFD, MSWX) in hourly mode -> three hourly records per step
      (state held, step rain split evenly)
    - 4-digit year -> 2-digit year (triplet shaw_032)

No made-up fill values: a variable the source does not give (missing key or NaN)
stops the tool with an error that names the variable and the first bad date.

Usage:
    python convert_forcing_to_shaw.py --source nasa_power --lat 45.3 --lon -75.0 \
        --start_year 2015 --end_year 2019 --mode daily --output site.wea
    python convert_forcing_to_shaw.py --source cmfd --lat 32.43 --lon 115.6 \
        --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
        --start_year 2010 --end_year 2010 --mode daily --output site.wea
"""

import argparse
import sys
import math
import json
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

LOADER_SOURCES = ("nasa_power", "cmfd", "mswx")
_KI_TOOLS_COMMON_ROOT = "KISSPATH_KI_TOOLS_COMMON"


class ForcingError(RuntimeError):
    """A needed weather variable is missing or the series is not usable."""


def specific_to_dewpoint(q, P):
    """Dew point (C) from specific humidity (kg/kg) and pressure (Pa).

    Same Tetens constants as specific_to_relative_humidity, so RH and dew point agree.
    """
    ea = q * P / (0.622 + 0.378 * q)          # Pa
    if not ea > 0.0:
        raise ForcingError(f"vapour pressure {ea} Pa from q={q}, P={P} is not positive")
    g = math.log(ea / 611.2)
    return 243.5 * g / (17.67 - g)


def specific_to_relative_humidity(q, T, P):
    """
    Convert specific humidity to relative humidity.

    Args:
        q: Specific humidity (kg/kg)
        T: Temperature (C)
        P: Pressure (Pa)

    Returns:
        RH: Relative humidity (%)
    """
    # Saturation vapor pressure (Pa) - Tetens formula
    es = 611.2 * math.exp(17.67 * T / (T + 243.5))
    # Actual vapor pressure from specific humidity
    ea = q * P / (0.622 + 0.378 * q)
    # Relative humidity
    rh = 100.0 * ea / es
    return max(0.0, min(100.0, rh))


def temp_to_dewpoint(T, RH):
    """
    Compute dew-point temperature from air temperature and relative humidity.

    Args:
        T: Air temperature (C)
        RH: Relative humidity (%)

    Returns:
        Td: Dew-point temperature (C)
    """
    if not math.isfinite(RH) or not 0 < RH <= 100:
        raise ForcingError("RH must be in (0,100] for a finite dew point")
    rh_frac = RH / 100.0
    a = 17.27
    b = 237.7
    gamma = a * T / (b + T) + math.log(rh_frac)
    td = b * gamma / (a - gamma)
    return td


def read_daily_csv(filepath, start_year=None, end_year=None, *, solar_units=None):
    """Read complete daily station data without dropping, filling or clipping.

    Dates must be consecutive and ordered. Supplied year bounds require the
    corresponding Jan-1/Dec-31 coverage. Solar units follow the column name:
    srad_mj_m2/solar_mj/totrs_mj -> MJ/m2/day, srad_wm2/solar_wm2/swdown_wm2
    -> daily mean W/m2. Generic srad/solar requires explicit solar_units.
    """
    import csv
    if solar_units not in (None, "mj_m2_day", "wm2"):
        raise ForcingError("solar_units must be mj_m2_day or wm2")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ForcingError("start_year must not exceed end_year")
    rows = []
    dates = []
    with open(filepath, newline="") as fh:
        reader = csv.DictReader(fh)
        for lineno, raw in enumerate(reader, 2):
            row = {k.strip().lower(): v for k, v in raw.items() if k is not None}
            text = next((row[k] for k in ("date", "datetime", "day") if k in row), None)
            try:
                dt = datetime.fromisoformat(str(text).strip())
                if dt.hour or dt.minute or dt.second or dt.microsecond or dt.tzinfo:
                    raise ValueError("not a local daily date")
            except (ValueError, TypeError):
                raise ForcingError(f"{filepath} line {lineno}: missing/invalid daily date {text!r}") from None
            if start_year is not None and dt.year < start_year:
                continue
            if end_year is not None and dt.year > end_year:
                continue

            def value(*names):
                key = next((k for k in names if k in row), names[0])
                try:
                    v = float(row.get(key))
                except (ValueError, TypeError):
                    raise ForcingError(f"{filepath} {dt.date()}: {key} missing or nonnumeric") from None
                if not math.isfinite(v):
                    raise ForcingError(f"{filepath} {dt.date()}: {key} nonfinite; no filling")
                return v

            tmax = value("tmax_c", "tmax", "tmax_air", "maxair_t")
            tmin = value("tmin_c", "tmin", "tmin_air", "minair_t")
            precip = value("precip_mm", "precip", "prcp", "rain_mm")
            wind = value("wind_m_s", "wind", "avgws", "windspeed")
            rh = value("rh_pct", "rh", "avgrh", "humidity")
            mj_keys = ("srad_mj_m2", "solar_mj", "totrs_mj")
            watt_keys = ("srad_wm2", "solar_wm2", "swdown_wm2")
            solar_key = next((k for k in mj_keys + watt_keys + ("srad", "solar") if k in row), "srad_mj_m2")
            srad = value(solar_key)
            units = "mj_m2_day" if solar_key in mj_keys else "wm2" if solar_key in watt_keys else solar_units
            if units is None:
                raise ForcingError(f"{filepath}: ambiguous {solar_key} units; provide --csv-solar-units")
            if solar_units is not None and solar_units != units:
                raise ForcingError(f"{filepath}: solar units conflict with column {solar_key}")
            if tmin > tmax or tmin <= -273.15:
                raise ForcingError(f"{filepath} {dt.date()}: invalid tmin_c/tmax_c")
            for key, v in (("precip_mm", precip), ("wind_m_s", wind), (solar_key, srad)):
                if v < 0:
                    raise ForcingError(f"{filepath} {dt.date()}: {key} must be nonnegative; no clipping")
            if not 0 < rh <= 100:
                raise ForcingError(f"{filepath} {dt.date()}: rh_pct must be in (0,100] for finite dew point")
            if dates and dt - dates[-1] != timedelta(days=1):
                raise ForcingError(f"{filepath}: calendar gap, duplicate or unordered date between {dates[-1].date()} and {dt.date()}")
            dates.append(dt)
            rows.append(dict(jday=dt.timetuple().tm_yday, year=dt.year,
                             tmax=tmax, tmin=tmin, tavg=.5*(tmax+tmin), wind=wind,
                             precip=precip, swdown=srad*1e6/86400. if units=="mj_m2_day" else srad, rh=rh))
    if not rows:
        raise ForcingError(f"{filepath}: no daily weather records for requested period")
    if start_year is not None and dates[0] != datetime(start_year, 1, 1):
        raise ForcingError(f"{filepath}: calendar coverage does not start on {start_year}-01-01")
    if end_year is not None and dates[-1] != datetime(end_year, 12, 31):
        raise ForcingError(f"{filepath}: calendar coverage does not end on {end_year}-12-31")
    return rows


def _import_loader():
    """Import the shared loader (pip-installed; fall back to its server path)."""
    try:
        from ki_tools_common import load_forcing as lf
    except ImportError:
        sys.path.insert(0, _KI_TOOLS_COMMON_ROOT)
        from ki_tools_common import load_forcing as lf
    return lf


def _need(data, keys, source, what):
    """Return float arrays for `keys`; stop if a key is absent or holds NaN."""
    dates = np.asarray(data["dates"])
    out = {}
    for k in keys:
        if k not in data or data[k] is None:
            raise ForcingError(
                f"source '{source}' ({what}) did not return '{k}'. SHAW needs it and this "
                f"tool does not invent it. Loader keys: {sorted(data.keys())}")
        a = np.asarray(data[k], dtype=float)
        if a.shape[0] != dates.shape[0]:
            raise ForcingError(f"'{k}' has {a.shape[0]} values but there are {dates.shape[0]} dates")
        bad = ~np.isfinite(a)
        if bad.any():
            first = str(dates[int(np.argmax(bad))])
            raise ForcingError(
                f"source '{source}' ({what}): '{k}' is missing (NaN) on {int(bad.sum())} of "
                f"{a.size} steps, first at {first}. No fill value is used; choose a period or "
                f"source that has this variable.")
        out[k] = a
    return out


def read_source_daily(source, lat, lon, start_year, end_year, forcing_dir=None):
    """Daily SHAW records straight from ki_tools_common.load_forcing.load_daily_forcing."""
    lf = _import_loader()
    data = lf.load_daily_forcing(source, lat, lon, start_year, end_year, forcing_dir=forcing_dir)
    v = _need(data, ("precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c",
                     "srad_wm2", "wind_ms", "shum_kgkg", "pres_pa"), source, "daily")
    days = np.asarray(data["dates"]).astype("datetime64[D]")
    if days.size == 0:
        raise ForcingError(f"source '{source}' returned no days for {start_year}-{end_year}")
    step = np.diff(days).astype(int)
    if (step != 1).any():
        i = int(np.argmax(step != 1))
        raise ForcingError(
            f"source '{source}': daily series is not consecutive after {days[i]} "
            f"(next is {days[i + 1]}). SHAW DAY2HR aborts on a missing calendar day.")
    recs = []
    for i, d in enumerate(days):
        dt = d.astype(datetime)
        recs.append({
            "jday": dt.timetuple().tm_yday, "year": dt.year,
            "tmax": float(v["temp_max_c"][i]), "tmin": float(v["temp_min_c"][i]),
            "tavg": float(v["temp_mean_c"][i]),
            "wind": float(v["wind_ms"][i]),
            "precip": max(0.0, float(v["precip_mm"][i])),
            "swdown": max(0.0, float(v["srad_wm2"][i])),
            "rh": specific_to_relative_humidity(float(v["shum_kgkg"][i]),
                                                float(v["temp_mean_c"][i]),
                                                float(v["pres_pa"][i])),
            "tdew": specific_to_dewpoint(float(v["shum_kgkg"][i]), float(v["pres_pa"][i])),
        })
    return recs, {"wind_height_m": data.get("wind_height_m")}


def read_source_hourly(source, lat, lon, start_year, end_year, forcing_dir=None,
                       utc_offset=None):
    """Hourly SHAW records straight from load_hourly_forcing.

    The loader time axis is UTC. SHAW works in local time (HRNOON), so the
    series is shifted by `utc_offset` hours (default round(lon/15)) and cut to
    whole local days. 3-hourly sources are written as three hourly records per
    step (temperature, wind, humidity, radiation held; step rain split evenly).
    """
    lf = _import_loader()
    data = lf.load_hourly_forcing(source, lat, lon, start_year, end_year, forcing_dir=forcing_dir)
    v = _need(data, ("precip_mm", "temp_c", "srad_wm2", "wind_ms", "shum_kgkg", "pres_pa"),
              source, "sub-daily")
    if "timestep_seconds" not in data:
        raise ForcingError(f"source '{source}' sub-daily data has no 'timestep_seconds'")
    ts = int(data["timestep_seconds"])
    if ts % 3600 or 86400 % ts:
        raise ForcingError(f"timestep {ts} s cannot be written as whole hours")
    nrep = ts // 3600
    if utc_offset is None:
        utc_offset = int(round(lon / 15.0))
    times = np.asarray(data["dates"]).astype("datetime64[s]").astype(datetime)
    recs = []
    for i, t in enumerate(times):
        rh = specific_to_relative_humidity(float(v["shum_kgkg"][i]), float(v["temp_c"][i]),
                                           float(v["pres_pa"][i]))
        for k in range(nrep):
            lt = t + timedelta(hours=utc_offset + k)
            recs.append({
                "jday": lt.timetuple().tm_yday, "hour": lt.hour, "year": lt.year,
                "date": lt, "tmax": float(v["temp_c"][i]), "tmin": float(v["temp_c"][i]),
                "tavg": float(v["temp_c"][i]), "wind": float(v["wind_ms"][i]), "rh": rh,
                "precip": max(0.0, float(v["precip_mm"][i])) / nrep,
                "swdown": max(0.0, float(v["srad_wm2"][i])),
            })
    # keep whole local days inside the asked period only
    per_day = {}
    for r in recs:
        per_day.setdefault((r["year"], r["jday"]), 0)
        per_day[(r["year"], r["jday"])] += 1
    kept = [r for r in recs
            if per_day[(r["year"], r["jday"])] == 24 and start_year <= r["year"] <= end_year]
    if not kept:
        raise ForcingError(f"source '{source}': no whole local day after the UTC{utc_offset:+d} shift")
    for a, b in zip(kept[:-1], kept[1:]):
        if b["date"] - a["date"] != timedelta(hours=1):
            raise ForcingError(f"hourly series has a gap between {a['date']} and {b['date']}")
    print(f"  UTC{utc_offset:+d} shift, source step {ts} s -> {len(kept)} hourly records "
          f"({len(recs) - len(kept)} dropped at the ends: partial local days)")
    return kept, {"wind_height_m": data.get("wind_height_m"), "utc_offset": utc_offset,
                  "source_timestep_seconds": ts}


def summarize(data, mode):
    """Annual totals/means of what is written, for a quick sanity check."""
    years = {}
    for r in data:
        y = years.setdefault(r["year"], {"precip_mm": 0.0, "t": [], "n": 0})
        y["precip_mm"] += r["precip"]
        y["t"].append(r["tavg"])
        y["n"] += 1
    out = {}
    for yr in sorted(years):
        y = years[yr]
        out[str(yr)] = {"precip_mm": round(y["precip_mm"], 2),
                        "tavg_c": round(float(np.mean(y["t"])), 2),
                        "records": y["n"]}
        print(f"  {yr}: precip {y['precip_mm']:.1f} mm, mean T {np.mean(y['t']):.2f} C, "
              f"{y['n']} {mode} records")
    return out


def write_hourly_weather(data, output_path, steps_per_day=8):
    """
    Write SHAW hourly weather file.
    Format: JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR
    """
    with open(output_path, 'w') as f:
        for rec in data:
            # Snow density: 0 = let model calculate from temperature
            snoden = 0.0
            f.write(
                f" {rec['jday']:3d} {rec['hour']:2d} {rec['year'] % 100:02d} "
                f"{rec['tavg']:6.1f} {rec['wind']:5.2f} {rec['rh']:5.1f} "
                f"{rec['precip']:6.2f} {snoden:3.1f} "
                f"{rec['swdown']:7.1f}\n"
            )

    print(f"Hourly weather file written: {output_path}")
    print(f"  Records: {len(data)}")
    print(f"  Period: day {data[0]['jday']}/{data[0]['year']} to day {data[-1]['jday']}/{data[-1]['year']}")


def write_daily_weather(data, output_path, steps_per_day=8):
    """
    Write SHAW daily weather file.
    Format: JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR

    Aggregates sub-daily data to daily.
    """
    # Group by day
    daily = {}
    for rec in data:
        key = (rec['year'], rec['jday'])
        if key not in daily:
            daily[key] = {
                'jday': rec['jday'],
                'year': rec['year'],
                'tmax': -999,
                'tmin': 999,
                'wind_sum': 0,
                'precip_sum': 0,
                'sw_sum': 0,
                'rh_sum': 0,
                'tavg_sum': 0,
                'tdew_sum': 0,
                'tdew_n': 0,
                'count': 0,
            }
        d = daily[key]
        d['tmax'] = max(d['tmax'], rec['tmax'])
        d['tmin'] = min(d['tmin'], rec['tmin'])
        d['wind_sum'] += rec['wind']
        d['precip_sum'] += rec['precip']
        d['sw_sum'] += rec['swdown']
        d['rh_sum'] += rec['rh']
        d['tavg_sum'] += rec['tavg']
        if 'tdew' in rec:
            d['tdew_sum'] += rec['tdew']
            d['tdew_n'] += 1
        d['count'] += 1

    with open(output_path, 'w') as f:
        for key in sorted(daily.keys()):
            d = daily[key]
            n = d['count']
            wind_avg = d['wind_sum'] / n
            solar_avg = d['sw_sum'] / n
            rh_avg = d['rh_sum'] / n
            tavg = d['tavg_sum'] / n

            # Dew point: straight from the source humidity when every record of
            # the day carries it, else from average temp and RH (CSV)
            if d['tdew_n'] == n:
                tdew = d['tdew_sum'] / n
            else:
                tdew = temp_to_dewpoint(tavg, rh_avg)

            # Year as 2-digit (SHAW convention: 86 for 1986)
            yr = d['year'] % 100

            f.write(
                f" {d['jday']:3d} {yr:2d} "
                f"{d['tmax']:6.1f} {d['tmin']:6.1f} {tdew:6.1f} "
                f"{wind_avg:5.2f} {d['precip_sum']:6.1f} "
                f"{solar_avg:7.1f}\n"
            )

    print(f"Daily weather file written: {output_path}")
    print(f"  Days: {len(daily)}")
    first = sorted(daily.keys())[0]
    last = sorted(daily.keys())[-1]
    print(f"  Period: day {first[1]}/{first[0]} to day {last[1]}/{last[0]}")


def main():
    parser = argparse.ArgumentParser(
        description="Build a SHAW weather file (.wea) directly from a forcing source "
                    "(NASA POWER / CMFD / MSWX through ki_tools_common.load_forcing), "
                    "or from a daily station CSV")
    parser.add_argument("--source", choices=list(LOADER_SOURCES) + ["csv"], default=None,
                        help="Where the weather comes from. nasa_power|cmfd|mswx = shared loader "
                             "(the standard path; needs --lat/--lon). csv = daily station table "
                             "(needs --csv).")
    parser.add_argument("--forcing_dir", type=str, default=None,
                        help="Root of the CMFD or MSWX store handed to the shared loader "
                             "(--source cmfd|mswx). Left out = the loader's own default.")
    parser.add_argument("--csv", type=str, default=None,
                        help="Daily weather CSV (RISMA/EC/AAFC). Implies --source csv.")
    parser.add_argument("--csv-solar-units", choices=("mj_m2_day", "wm2"), default=None,
                        help="Required for generic CSV solar/srad columns; explicit unit headers take precedence")
    parser.add_argument("--lat", type=float, default=None, help="Target latitude (deg N)")
    parser.add_argument("--lon", type=float, default=None, help="Target longitude (deg E)")
    parser.add_argument("--start_year", type=int, default=None, help="Start year")
    parser.add_argument("--end_year", type=int, default=None, help="End year")
    parser.add_argument("--output", type=str, required=True, help="Output weather file")
    parser.add_argument("--mode", choices=["hourly", "daily"], default="daily",
                        help="Output format: hourly (MTSTEP=0) or daily (MTSTEP=1)")
    parser.add_argument("--utc_offset", type=int, default=None,
                        help="Hours from UTC to local standard time for --mode hourly with a "
                             "loader source (default round(lon/15))")
    parser.add_argument("--summary_json", type=str, default=None,
                        help="Write annual precip totals / mean T of the written file here")

    args = parser.parse_args()

    source = args.source
    if source is None and args.csv:
        source = "csv"
    if source is None:
        parser.error("give --source nasa_power|cmfd|mswx (with --lat/--lon), or --csv FILE. "
                     "There is no default source.")

    meta = {}
    try:
        if source == "csv":
            if not args.csv:
                parser.error("--source csv needs --csv FILE")
            if args.mode == "hourly":
                parser.error("--csv is daily data; use --mode daily (MTSTEP=1)")
            print(f"Reading daily CSV forcing: {args.csv}")
            data = read_daily_csv(args.csv, args.start_year, args.end_year, solar_units=args.csv_solar_units)
            if not data:
                raise ForcingError("no usable rows in --csv")
            steps = 1
        else:  # a loader source
            if args.lat is None or args.lon is None or args.start_year is None or args.end_year is None:
                parser.error(f"--source {source} needs --lat --lon --start_year --end_year")
            print(f"Reading {source} {args.mode} forcing through ki_tools_common.load_forcing "
                  f"at ({args.lat}, {args.lon}) {args.start_year}-{args.end_year}")
            if args.mode == "daily":
                data, meta = read_source_daily(source, args.lat, args.lon, args.start_year,
                                               args.end_year, args.forcing_dir)
                steps = 1
            else:
                data, meta = read_source_hourly(source, args.lat, args.lon, args.start_year,
                                                args.end_year, args.forcing_dir, args.utc_offset)
                steps = 24
            if meta.get("wind_height_m"):
                print(f"  wind is at {meta['wind_height_m']} m: set the .sit instrument height to match")
    except ForcingError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)

    print(f"Read {len(data)} records")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "hourly":
        write_hourly_weather(data, str(output_path), steps)
    else:
        write_daily_weather(data, str(output_path), steps)

    annual = summarize(data, args.mode)
    if args.summary_json:
        Path(args.summary_json).write_text(json.dumps(
            {"source": source, "mode": args.mode, "lat": args.lat, "lon": args.lon,
             "output": str(output_path), "annual": annual, **meta}, indent=2))


if __name__ == "__main__":
    main()
