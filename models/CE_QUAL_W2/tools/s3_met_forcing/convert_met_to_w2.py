#!/usr/bin/env python3
"""
convert_met_to_w2.py -- Build the CE-QUAL-W2 met file straight from a forcing source.

Two halves, kept apart on purpose:

  1. source -> STANDARD SERIES   (shared, ki_tools_common.load_forcing.load_hourly_forcing)
         dates             numpy datetime64 (UTC), one per step
         timestep_seconds  3600 (nasa_power) or 10800 (cmfd, mswx)
         temp_c            air temperature      (deg C)
         srad_wm2          incoming short-wave  (W/m^2)
         wind_ms           wind speed           (m/s)
         shum_kgkg         specific humidity    (kg/kg)
         pres_pa           air pressure         (Pa)

  2. STANDARD SERIES -> met file  (this KI, standard_to_met() below)
         JDAY, TAIR, TDEW, WIND, PHI, CLOUD, SRO

What half 2 does, column by column (each one is a silent error if wrong):
  JDAY   decimal day, 1.0 = 00:00 on 1 Jan of --start_year, in LOCAL STANDARD time.
         The sources are in UTC; CE-QUAL-W2 works out the sun's position from JDAY
         as local standard time (heat-exchange.f90, SHORT_WAVE_RADIATION). The
         offset is the model's own rule, int(lon/15) hours, unless
         --utc_offset_hours is given. Only the time stamp moves; no value changes.
  TAIR   deg C, the source value.
  TDEW   deg C, from specific humidity and the source's own pressure:
         e = q p / (0.622 + 0.378 q), then the inverse of the Tetens formula of
         ki_tools_common.humidity. Where e is above saturation TDEW is set to
         TAIR (counted in the summary).
  WIND   m/s, the source value (no height adjustment).
  PHI    wind direction in RADIANS (the v5 binary uses cos(PHI - PHI0); the
         DeGray example file holds 4.37-5.24). The sources have no wind
         direction: the constant --wind_dir_deg (default 270, westerly) is
         written as radians (4.712) and the summary says so.
  CLOUD  TENTHS, 0-10 (dt_001). Estimated per local day from short-wave with the
         model's own relation (heat-exchange.f90):
             SRO = (1 - 0.0065 CLOUD^2) * SRO_clear(sun altitude)
         CLOUD = sqrt((1 - SW_day / SW_clear_day) / 0.0065), limited to 0-10,
         one value per local day. A day with no usable daylight in the series
         (the dark hours at either end of the period) takes the value of the
         nearest day that has one; more than 3 such days in a row stops the tool.
  SRO    W/m^2, the source short-wave. The model reads it only when SROC is ON
         in the control file; with SROC OFF it computes short-wave from CLOUD.

File form: the v5 binary's CSV form (time-varying-data.f90): first character '$',
three header lines, then comma-separated rows. With SROC OFF the binary reads
the first six values of each row and ignores SRO.

No value is made up. A missing or non-finite value, an uneven time axis or a
period that is not fully covered stops the tool with a clear error and writes
nothing. A summary is written next to the met file as <output>.summary.json.

Usage:
    python convert_met_to_w2.py --source mswx --forcing_dir KISSPATH_FORCING \
        --lat 34.2 --lon -93.1 --start_year 1980 --end_year 1980 \
        --output <run_dir>/met.npt

    python convert_met_to_w2.py --source cmfd \
        --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
        --lat 32.54 --lon 111.51 --start_year 2005 --end_year 2010 \
        --output <run_dir>/met.npt

    python convert_met_to_w2.py --source nasa_power \
        --lat 34.2 --lon -93.1 --start_year 2005 --end_year 2005 \
        --output <run_dir>/met.npt

Exit codes: 0 success, 1 bad arguments, 2 source or series not usable (nothing written).
"""

import argparse
import json
import os
import sys

import numpy as np

from ki_tools_common.humidity import saturation_vapor_pressure

SOURCES = ("cmfd", "mswx", "nasa_power")

# The standard series half 2 needs, and the range a real value can lie in.
# Outside the range is a unit error upstream, not weather.
NEEDED_SERIES = {
    "temp_c":    (-90.0, 60.0),
    "srad_wm2":  (0.0, 1500.0),
    "wind_ms":   (0.0, 100.0),
    "shum_kgkg": (0.0, 0.05),
    "pres_pa":   (30000.0, 110000.0),
}

CLOUD_COEF = 0.0065          # heat-exchange.f90: SRON = (1.0-0.0065*CLOUD**2)*clear sky
BTU_FT2_DAY_TO_W_M2 = 0.1314  # heat-exchange.f90
MIN_CLEAR_DAY_WM2 = 20.0     # a day needs this much mean clear-sky short-wave to give a cloud value
MAX_CARRY_DAYS = 3


def check_standard_series(d):
    """Problems that make a standard series unusable (empty list = usable).

    Nothing is repaired here.
    """
    problems = []
    if "dates" not in d or len(d["dates"]) == 0:
        return ["no time steps were returned"]
    n = len(d["dates"])
    for name, (lo, hi) in NEEDED_SERIES.items():
        if name not in d or d[name] is None:
            problems.append(f"{name}: series missing")
            continue
        a = np.asarray(d[name], dtype=float)
        if a.shape != (n,):
            problems.append(f"{name}: {a.shape} values for {n} time steps")
            continue
        bad = int((~np.isfinite(a)).sum())
        if bad:
            problems.append(f"{name}: {bad} of {n} values missing or not finite")
            continue
        if a.min() < lo or a.max() > hi:
            problems.append(f"{name}: range {a.min():g} to {a.max():g} is outside "
                            f"{lo:g} to {hi:g} (wrong unit upstream?)")
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    steps = np.diff(dates).astype("timedelta64[s]").astype(int)
    ts = int(d.get("timestep_seconds", 0) or 0)
    if ts <= 0 or 86400 % ts:
        problems.append(f"timestep_seconds {ts} does not divide a day")
    elif len(steps) and not (steps == ts).all():
        off = int((steps != ts).sum())
        problems.append(f"time axis: {off} of {len(steps)} steps are not {ts} s apart "
                        f"(first at {dates[int(np.argmax(steps != ts))]})")
    return problems


def check_period_covered(d, start_year, end_year):
    """The series must hold every step of start_year..end_year, no more, no less."""
    ts = int(d["timestep_seconds"])
    first = np.datetime64(f"{start_year:04d}-01-01T00:00:00")
    days = int((np.datetime64(f"{end_year + 1:04d}-01-01") - np.datetime64(f"{start_year:04d}-01-01"))
               / np.timedelta64(1, "D"))
    want = days * (86400 // ts)
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    if len(dates) != want or dates[0] != first:
        raise ValueError(
            f"forcing does not cover {start_year}-{end_year}: {len(dates)} steps from "
            f"{dates[0] if len(dates) else 'nothing'}, expected {want} steps from {first}. "
            f"Nothing written.")


def dewpoint_from_specific_humidity(shum_kgkg, pres_pa, temp_c):
    """(TDEW deg C, number of steps limited to TAIR).

    e = q p / (0.622 + 0.378 q) in hPa, then the inverse of the Tetens formula
    es = es0 exp(a T / (b + T)) used by ki_tools_common.humidity.
    """
    q = np.asarray(shum_kgkg, dtype=float)
    e_hpa = q * (np.asarray(pres_pa, dtype=float) / 100.0) / (0.622 + 0.378 * q)
    if (e_hpa <= 0).any():
        raise ValueError(f"vapour pressure is zero or negative at {int((e_hpa <= 0).sum())} "
                         f"steps (specific humidity 0): no dew point exists")
    es0 = float(saturation_vapor_pressure(0.0))
    # a and b from the shared formula itself, so the two can never drift apart
    b = 237.3
    a = float(np.log(saturation_vapor_pressure(b) / es0) * 2.0)
    ln_term = np.log(e_hpa / es0)
    tdew = b * ln_term / (a - ln_term)
    temp = np.asarray(temp_c, dtype=float)
    above = tdew > temp
    return np.where(above, temp, tdew), int(above.sum())


def w2_clear_sky_wm2(lat, jday_local, lon, std_meridian):
    """Clear-sky short-wave (W/m^2) as the v5 binary computes it (heat-exchange.f90).

    jday_local is local standard time; lon and std_meridian are degrees east.
    """
    jd = np.asarray(jday_local, dtype=float)
    hour = (jd - np.floor(jd)) * 24.0
    iday = np.floor(jd) - np.floor(jd / 365.0) * 365.0
    iday = iday - np.floor(np.floor(jd / 365.0) / 4.0)
    taud = 2.0 * np.pi * (iday - 1.0) / 365.0
    eqt = 0.170 * np.sin(4.0 * np.pi * (iday - 80.0) / 373.0) \
        - 0.129 * np.sin(2.0 * np.pi * (iday - 8.0) / 355.0)
    # minutes east of the standard meridian put the sun ahead of the clock
    hh = 0.261799 * (hour + (lon - std_meridian) / 15.0 + eqt - 12.0)
    decl = (0.006918 - 0.399912 * np.cos(taud) + 0.070257 * np.sin(taud)
            - 0.006758 * np.cos(2 * taud) + 0.000907 * np.sin(2 * taud)
            - 0.002697 * np.cos(3 * taud) + 0.001480 * np.sin(3 * taud))
    lat_r = np.radians(lat)
    sinal = np.sin(lat_r) * np.sin(decl) + np.cos(lat_r) * np.cos(decl) * np.cos(hh)
    a0 = np.degrees(np.arcsin(np.clip(sinal, -1.0, 1.0)))
    clear = 24.0 * (2.044 * a0 + 0.1296 * a0 ** 2 - 1.941e-3 * a0 ** 3
                    + 7.591e-6 * a0 ** 4) * BTU_FT2_DAY_TO_W_M2
    return np.where(a0 > 0.0, clear, 0.0)


def estimate_cloud_tenths(srad, jday_local, step_days, lat, lon, std_meridian):
    """(CLOUD in tenths per step, number of steps that took a neighbour day's value).

    One value per local day: the cloud cover with which the model's own formula
    gives that day's mean short-wave. The clear-sky mean of a step is taken over
    the step [stamp, stamp + step) at 5-minute points; whether the source stamps
    the start or the end of its step moves only night hours across the day edge.
    """
    n_sub = max(1, int(round(step_days * 288)))
    offs = (np.arange(n_sub) + 0.5) * step_days / n_sub
    clear_step = w2_clear_sky_wm2(lat, jday_local[:, None] + offs[None, :],
                                  lon, std_meridian).mean(axis=1)
    day = np.floor(jday_local + 1e-9).astype(int)
    days = np.unique(day)
    cloud_day = np.full(len(days), np.nan)
    for k, dd in enumerate(days):
        m = day == dd
        clear_mean = clear_step[m].mean()
        if clear_mean >= MIN_CLEAR_DAY_WM2:
            ratio = srad[m].mean() / clear_mean
            cloud_day[k] = np.sqrt(np.clip((1.0 - ratio) / CLOUD_COEF, 0.0, 100.0))
    known = np.where(np.isfinite(cloud_day))[0]
    if len(known) == 0:
        raise ValueError("cloud cover cannot be estimated: no day in the series has daylight")
    carried_steps = 0
    for k in np.where(~np.isfinite(cloud_day))[0]:
        near = known[np.argmin(np.abs(known - k))]
        if abs(int(near) - int(k)) > MAX_CARRY_DAYS:
            raise ValueError(
                f"cloud cover cannot be estimated from short-wave around local day {days[k]}: "
                f"more than {MAX_CARRY_DAYS} days in a row without daylight. Nothing written.")
        cloud_day[k] = cloud_day[near]
        carried_steps += int((day == days[k]).sum())
    return cloud_day[np.searchsorted(days, day)], carried_steps


def utc_offset_for(lon, utc_offset_hours=None):
    """(offset in hours, where it came from). Default: the model's own standard-meridian rule."""
    if utc_offset_hours is None:
        return float(int(lon / 15.0)), "int(lon/15), the rule the model itself uses for its standard meridian"
    return float(utc_offset_hours), "--utc_offset_hours"


def years_to_load(start_year, end_year, utc_offset_hours):
    """UTC years needed so that the LOCAL years start_year..end_year are fully covered.

    East of Greenwich local midnight of 1 Jan falls in the UTC year before; west of it
    the last local hours of 31 Dec fall in the UTC year after.
    """
    if utc_offset_hours > 0:
        return start_year - 1, end_year
    if utc_offset_hours < 0:
        return start_year, end_year + 1
    return start_year, end_year


def standard_to_met(d, lat, lon, start_year, end_year, output, source_label,
                    wind_dir_deg=270.0, utc_offset_hours=None, loaded_years=None):
    """Half 2: write a STANDARD SERIES dict as a CE-QUAL-W2 v5 met file.

    Returns the summary dict. Raises ValueError when the series is not usable;
    in that case no file is written.
    """
    problems = check_standard_series(d)
    if problems:
        raise ValueError("forcing series not usable, nothing written:\n  - "
                         + "\n  - ".join(problems))
    # d holds whole UTC years; loaded_years says which (default: the years asked for)
    load_y0, load_y1 = loaded_years if loaded_years else (start_year, end_year)
    check_period_covered(d, load_y0, load_y1)
    if not (0.0 <= wind_dir_deg <= 360.0):
        raise ValueError(f"--wind_dir_deg {wind_dir_deg} is not between 0 and 360")

    ts = int(d["timestep_seconds"])
    dates = np.asarray(d["dates"]).astype("datetime64[s]")
    tair = np.asarray(d["temp_c"], dtype=float) + 0.0
    wind = np.asarray(d["wind_ms"], dtype=float) + 0.0
    sro = np.asarray(d["srad_wm2"], dtype=float) + 0.0
    tdew, n_tdew_limited = dewpoint_from_specific_humidity(d["shum_kgkg"], d["pres_pa"], tair)

    utc_offset_hours, offset_from = utc_offset_for(lon, utc_offset_hours)
    std_meridian = 15.0 * utc_offset_hours
    t0 = np.datetime64(f"{start_year:04d}-01-01T00:00:00")
    jday = 1.0 + (dates - t0).astype("timedelta64[s]").astype(float) / 86400.0 \
        + utc_offset_hours / 24.0

    cloud, n_cloud_carried = estimate_cloud_tenths(sro, jday, ts / 86400.0, lat, lon, std_meridian)
    phi = np.full(len(jday), np.radians(wind_dir_deg))

    # keep the LOCAL years asked for, bracketed: from the last stamp at or before JDAY 1.0
    # (00:00 local, 1 Jan start_year) to the first stamp at or after 00:00 local on 1 Jan of
    # the year after end_year, so a run over the whole period finds met data at both ends
    n_days_local = int((np.datetime64(f"{end_year + 1:04d}-01-01") - np.datetime64(f"{start_year:04d}-01-01"))
                       / np.timedelta64(1, "D"))
    j_start, j_end = 1.0, 1.0 + n_days_local
    edge_padded = bool(loaded_years) and tuple(loaded_years) != (start_year, end_year)
    before = np.nonzero(jday <= j_start + 1e-9)[0]
    after = np.nonzero(jday >= j_end - 1e-9)[0]
    covered = bool(len(before) and len(after))
    if edge_padded or covered:
        if not covered:
            raise ValueError(f"after the move to local time the series runs from JDAY {jday[0]:.3f} to "
                             f"{jday[-1]:.3f} and does not bracket {j_start:.1f}..{j_end:.1f} "
                             f"(local {start_year}-{end_year}). Nothing written.")
        keep = slice(int(before[-1]), int(after[0]) + 1)
        jday, tair, tdew, wind, phi, cloud, sro, dates = (
            a[keep] for a in (jday, tair, tdew, wind, phi, cloud, sro, dates))

    cols = (jday, tair, tdew, wind, phi, cloud, sro)
    for name, c in zip(("JDAY", "TAIR", "TDEW", "WIND", "PHI", "CLOUD", "SRO"), cols):
        if not np.isfinite(c).all():
            raise ValueError(f"{name}: non-finite value after conversion. Nothing written.")

    out_dir = os.path.dirname(os.path.abspath(output))
    os.makedirs(out_dir, exist_ok=True)
    tmp = output + ".tmp"
    with open(tmp, "w") as f:
        # exactly three header lines; '$' as first character = the v5 CSV form
        f.write(f"$CE-QUAL-W2 met file from {source_label} at lat {lat:g} lon {lon:g} "
                f"{start_year}-{end_year} (HydroCraft convert_met_to_w2)\n")
        f.write(f"$JDAY 1.0 = 00:00 on 1 Jan {start_year} local standard time (UTC{utc_offset_hours:+g} h); "
                f"PHI in radians; CLOUD in tenths\n")
        f.write("JDAY,TAIR,TDEW,WIND,PHI,CLOUD,SRO\n")
        for i in range(len(jday)):
            f.write(f"{jday[i]:.5f},{tair[i]:.3f},{tdew[i]:.3f},{wind[i]:.3f},"
                    f"{phi[i]:.3f},{cloud[i]:.2f},{sro[i]:.3f}\n")
    os.replace(tmp, output)

    return {
        "status": "success",
        "output_file": output,
        "file_form": "CE-QUAL-W2 v5 CSV met file ('$' first character, 3 header lines)",
        "columns": ["JDAY", "TAIR", "TDEW", "WIND", "PHI", "CLOUD", "SRO"],
        "source": source_label,
        "point": {"lat": lat, "lon": lon},
        "timestep_seconds": ts,
        "n_timesteps": int(len(jday)),
        "period_utc": [str(dates[0]), str(dates[-1])],
        "utc_offset_hours": utc_offset_hours,
        "utc_offset_from": offset_from,
        "utc_years_loaded": [load_y0, load_y1],
        "local_period_fully_covered": covered,
        "jday_range": [round(float(jday[0]), 5), round(float(jday[-1]), 5)],
        "means": {
            "TAIR_degC": round(float(tair.mean()), 3),
            "TDEW_degC": round(float(tdew.mean()), 3),
            "WIND_ms": round(float(wind.mean()), 3),
            "CLOUD_tenths": round(float(cloud.mean()), 3),
            "SRO_wm2": round(float(sro.mean()), 3),
        },
        "ranges": {
            "TAIR_degC": [round(float(tair.min()), 2), round(float(tair.max()), 2)],
            "TDEW_degC": [round(float(tdew.min()), 2), round(float(tdew.max()), 2)],
            "WIND_ms": [round(float(wind.min()), 2), round(float(wind.max()), 2)],
            "CLOUD_tenths": [round(float(cloud.min()), 2), round(float(cloud.max()), 2)],
            "SRO_wm2": [round(float(sro.min()), 2), round(float(sro.max()), 2)],
        },
        "estimated": {
            "TDEW": "from specific humidity and the source's pressure: e = q p/(0.622+0.378 q), "
                    "inverse Tetens; limited to TAIR at "
                    f"{n_tdew_limited} steps where e was above saturation",
            "PHI": f"NOT from the source (it has no wind direction): the constant "
                   f"{wind_dir_deg:g} deg = {float(np.radians(wind_dir_deg)):.3f} rad at every step",
            "CLOUD": "one value per local day from short-wave with the model's own relation "
                     "SRO = (1-0.0065 CLOUD^2) SRO_clear; "
                     f"{n_cloud_carried} steps on days without usable daylight took the nearest "
                     "day's value",
            "JDAY": "source time is UTC; stamps moved to local standard time, values unchanged",
        },
        "notes": [
            "SRO is read by the model only when SROC is ON; with SROC OFF short-wave comes from CLOUD.",
            "Wind is at the source's height (no adjustment); set WINDH in the control file to it.",
            f"The first stamp is JDAY {float(jday[0]):.3f} and the last {float(jday[-1]):.3f}: "
            "a run must start and end inside this range."
            + ("" if covered else
               " --no_edge_padding was given: the first or last local hours of the period are NOT in the file."),
        ],
    }


def parse_args():
    p = argparse.ArgumentParser(
        description="Build a CE-QUAL-W2 v5 met file straight from a forcing source")
    p.add_argument("--source", required=True, choices=SOURCES,
                   help="Forcing source, read through ki_tools_common.load_forcing."
                        "load_hourly_forcing. There is no default: name the source.")
    p.add_argument("--forcing_dir", default=None,
                   help="Root folder of the cmfd / mswx store (not used by nasa_power; "
                        "the loader's own default is used when left out)")
    p.add_argument("--lat", type=float, required=True, help="Latitude (degrees north)")
    p.add_argument("--lon", type=float, required=True, help="Longitude (degrees east)")
    p.add_argument("--start_year", type=int, required=True)
    p.add_argument("--end_year", type=int, required=True)
    p.add_argument("--output", required=True,
                   help="Met file path (give it the name the control file expects)")
    p.add_argument("--wind_dir_deg", type=float, default=270.0,
                   help="Wind direction written at every step, degrees (the sources have "
                        "none). Written to the file in radians. Default 270.")
    p.add_argument("--utc_offset_hours", type=float, default=None,
                   help="Local standard time minus UTC, hours. Default int(lon/15), the "
                        "model's own standard-meridian rule.")
    p.add_argument("--no_edge_padding", action="store_true",
                   help="Do NOT read the neighbouring UTC year. The file then misses the first "
                        "local hours of the period (east of Greenwich) or the last ones (west). "
                        "Default: the neighbouring year is read so the local years are complete; "
                        "if the source does not have that year the tool stops.")
    return p.parse_args()


def fail(code, message):
    print(json.dumps({"status": "error", "errors": [message]}, indent=2))
    return code


def main():
    args = parse_args()
    if not (-90 <= args.lat <= 90) or not (-180 <= args.lon <= 180):
        return fail(1, f"--lat {args.lat} / --lon {args.lon} out of range")
    if args.start_year > args.end_year:
        return fail(1, f"start_year {args.start_year} is after end_year {args.end_year}")
    if args.forcing_dir and not os.path.isdir(args.forcing_dir):
        return fail(1, f"--forcing_dir not found: {args.forcing_dir}")

    from ki_tools_common.load_forcing import load_hourly_forcing
    offset, _ = utc_offset_for(args.lon, args.utc_offset_hours)
    y0, y1 = (args.start_year, args.end_year) if args.no_edge_padding \
        else years_to_load(args.start_year, args.end_year, offset)
    try:
        d = load_hourly_forcing(args.source, args.lat, args.lon, y0, y1, args.forcing_dir)
    except Exception as exc:
        extra = "" if (y0, y1) == (args.start_year, args.end_year) else (
            f" (UTC years {y0}-{y1} are needed to cover the local years {args.start_year}-"
            f"{args.end_year} at UTC{offset:+g} h; if the source does not have the extra year, "
            f"shorten the period or pass --no_edge_padding and start/end the run inside the file)")
        return fail(2, f"{args.source} could not be read for {y0}-{y1} "
                       f"at ({args.lat}, {args.lon}); nothing written{extra}. "
                       f"{type(exc).__name__}: {exc}")
    try:
        summary = standard_to_met(d, args.lat, args.lon, args.start_year, args.end_year,
                                  args.output, args.source,
                                  wind_dir_deg=args.wind_dir_deg,
                                  utc_offset_hours=args.utc_offset_hours,
                                  loaded_years=(y0, y1))
    except ValueError as exc:
        return fail(2, str(exc))
    summary["forcing_dir"] = args.forcing_dir or "the loader's default"
    with open(args.output + ".summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
