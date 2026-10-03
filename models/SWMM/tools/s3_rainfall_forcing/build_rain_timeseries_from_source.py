#!/usr/bin/env python3
"""
Build a SWMM rainfall timeseries (.dat) straight from a forcing source.

Two halves, kept apart on purpose:

  1. source -> STANDARD SERIES   (shared, ki_tools_common.load_forcing)
     load_hourly_forcing(source, lat, lon, y0, y1, forcing_dir) gives, for
     every source, the same dict; this tool uses three of its entries:
         dates             numpy datetime64, one per step, UTC, the START of
                           the step
         timestep_seconds  10800 for cmfd / mswx, 3600 for nasa_power
         precip_mm         precipitation IN THE STEP (mm, not a rate)

  2. STANDARD SERIES -> SWMM .dat   (this KI, rain_series_to_records() below)
     The same layout as create_rain_timeseries.py (its writer is reused):
         <series_name> <TAB> MM/DD/YYYY <TAB> HH:MM:SS <TAB> value
     Only non-zero rows are written, so the file also carries one comment
     line ';;COVERAGE <start> <end>' (end not included) that says which
     period the data covers; tools/run_city_swmm.py refuses to simulate
     outside it. A fully covered period with no rain at all is valid: the
     file then has no rows, only its header (series name + coverage), and
     run_city_swmm.py runs it as zero rain. For a rain gage SWMM holds each value
     for one INTERVAL from its time stamp and reads a missing row as no rain,
     so the rows can be pasted into [TIMESERIES] as they are.

What half 2 must get right (each one is a silent error if wrong):
  - the [RAINGAGES] FORMAT must match the numbers in the file:
        intensity -> value = precip_mm / step hours   (mm/hr), FORMAT INTENSITY
        volume    -> value = precip_mm                (mm per step), FORMAT VOLUME
  - the [RAINGAGES] INTERVAL must be the data step (3:00 for cmfd / mswx,
    1:00 for nasa_power). A shorter INTERVAL with INTENSITY loses rain
    (0:05 with 3-hourly data keeps 1/36 of it); with VOLUME it does the same.
  This tool prints the FORMAT and INTERVAL to use and stores them in the
  summary file. tools/run_city_swmm.py reads them from there.

No value is made up. A missing, non-finite or negative value, an uneven time
axis, or a period the source does not fully cover stops the tool with a clear
error, and nothing is written.

More than one point (--points "lat,lon;lat,lon"):
  --method average   mean of the points' series, step by step (default)
  --method nearest   the series of the one point nearest to the centre of
                     the given points
  One SWMM rain gage gets one series. For several gages, run the tool once
  per gage with that gage's point.

Time: the time stamps are UTC, as the loader gives them. SWMM has no time
zone; keep every other series of the model (inflows, evaporation) in UTC too.

Inputs:
  --source        cmfd | mswx | nasa_power       (required, no default)
  --points        "lat,lon" or "lat,lon;lat,lon;..."
  --method        average | nearest
  --start_date --end_date   YYYY-MM-DD, both days included
  --forcing_dir   root folder of the cmfd / mswx store (not used by nasa_power)
  --rain_format   intensity | volume
  --series_name   name of the series in [TIMESERIES]
  --output        the .dat file; <output stem>.summary.json is written next to it

Exit codes:
  0 -- success
  1 -- bad arguments
  2 -- the source could not give the period (missing files, network, ...)
  3 -- the series failed a check; nothing written
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_rain_timeseries import write_swmm_timeseries  # noqa: E402

SOURCES = ("cmfd", "mswx", "nasa_power")

# precipitation in ONE step, mm. More than this is a unit error upstream.
MAX_PRECIP_MM_PER_STEP = 500.0

# the .dat keeps 4 decimals; the total in the file must still match the source
TOTAL_TOLERANCE = 0.001


def parse_points(text):
    """'lat,lon;lat,lon' -> [(lat, lon), ...]. Raises ValueError on bad input."""
    points = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(",")
        if len(bits) != 2:
            raise ValueError(f"point '{part}' is not 'lat,lon'")
        lat, lon = float(bits[0]), float(bits[1])
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 360.0):
            raise ValueError(f"point '{part}': lat must be -90..90, lon -180..360 "
                             f"(the order is lat,lon)")
        points.append((lat, lon))
    if not points:
        raise ValueError("no point given")
    return points


def interval_string(timestep_seconds):
    """Step length -> the [RAINGAGES] INTERVAL text (H:MM)."""
    ts = int(timestep_seconds)
    if ts <= 0 or ts % 60:
        raise ValueError(f"time step of {timestep_seconds} s cannot be a SWMM INTERVAL")
    return f"{ts // 3600}:{(ts % 3600) // 60:02d}"


def load_points(source, points, start_year, end_year, forcing_dir=None):
    """Half 1: one standard series per point, through the shared loader."""
    from ki_tools_common.load_forcing import load_hourly_forcing

    out = []
    for lat, lon in points:
        out.append(load_hourly_forcing(source, lat, lon, start_year, end_year,
                                       forcing_dir=forcing_dir))
    return out


def combine_points(series_list, points, method):
    """Several standard series -> one (dates, precip_mm, timestep_seconds).

    Every point must be on the same time axis. Returns also the index of the
    point used by 'nearest' (None for 'average').
    """
    import numpy as np

    first = series_list[0]
    dates = np.asarray(first["dates"]).astype("datetime64[s]")
    ts = int(first.get("timestep_seconds", 0) or 0)
    stack = []
    for (lat, lon), d in zip(points, series_list):
        dd = np.asarray(d["dates"]).astype("datetime64[s]")
        if dd.shape != dates.shape or not (dd == dates).all():
            raise ValueError(f"point {lat},{lon} is on a different time axis than "
                             f"the first point; the points cannot be combined")
        if int(d.get("timestep_seconds", 0) or 0) != ts:
            raise ValueError(f"point {lat},{lon} has a different time step")
        stack.append(np.asarray(d["precip_mm"], dtype=float))
    if method == "average":
        # plain mean: a NaN at one point stays a NaN and is refused later
        return dates, np.mean(np.vstack(stack), axis=0), ts, None
    if method == "nearest":
        clat = sum(p[0] for p in points) / len(points)
        clon = sum(p[1] for p in points) / len(points)
        coslat = np.cos(np.radians(clat))
        dist = [(p[0] - clat) ** 2 + ((p[1] - clon) * coslat) ** 2 for p in points]
        i = int(np.argmin(dist))
        return dates, stack[i], ts, i
    raise ValueError(f"unknown method '{method}'")


def cut_period(dates, precip, timestep_seconds, start_date, end_date):
    """Keep start_date 00:00 .. end_date 24:00 and list what is wrong with it.

    Returns (dates, precip, problems). Nothing is repaired or filled.
    """
    import numpy as np

    problems = []
    ts = int(timestep_seconds or 0)
    if ts <= 0:
        return dates, precip, ["timestep_seconds missing from the source series"]
    t0 = np.datetime64(start_date.strftime("%Y-%m-%dT00:00:00"), "s")
    t1 = np.datetime64((end_date + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"), "s")
    dates = np.asarray(dates).astype("datetime64[s]")
    precip = np.asarray(precip, dtype=float)
    if dates.shape != precip.shape:
        return dates, precip, [f"{precip.shape} rain values for {dates.shape} time steps"]
    keep = (dates >= t0) & (dates < t1)
    d, p = dates[keep], precip[keep]

    n_expected = int((t1 - t0).astype(int) // ts)
    if len(d) == 0:
        return d, p, [f"the source has no step between {start_date:%Y-%m-%d} and "
                      f"{end_date:%Y-%m-%d}"]
    steps = np.diff(d).astype(int)
    if len(steps) and not (steps == ts).all():
        off = int((steps != ts).sum())
        problems.append(f"time axis: {off} of {len(steps)} steps are not {ts} s apart "
                        f"(first at {d[int(np.argmax(steps != ts))]})")
    if d[0] != t0 or len(d) != n_expected:
        problems.append(f"period not fully covered: {len(d)} steps from {d[0]} to {d[-1]}, "
                        f"need {n_expected} steps of {ts} s from {t0}")
    bad = int((~np.isfinite(p)).sum())
    if bad:
        first_bad = d[int(np.argmax(~np.isfinite(p)))]
        problems.append(f"precip_mm: {bad} of {len(p)} values missing or not finite "
                        f"(first at {first_bad})")
    else:
        if p.min() < 0.0:
            problems.append(f"precip_mm: lowest value {p.min():g} is negative")
        if p.max() > MAX_PRECIP_MM_PER_STEP:
            problems.append(f"precip_mm: highest value {p.max():g} mm in one step is above "
                            f"{MAX_PRECIP_MM_PER_STEP:g} (wrong unit upstream?)")
    return d, p, problems


def rain_series_to_records(dates, precip_mm, timestep_seconds, rain_format):
    """Half 2: mm per step -> the (datetime, value) rows SWMM reads."""
    step_hours = timestep_seconds / 3600.0
    records = []
    for d, p in zip(dates.tolist(), precip_mm.tolist()):
        value = p / step_hours if rain_format == "intensity" else p
        records.append((d, value + 0.0))
    return records


def build_rain_dat(dates, precip_mm, timestep_seconds, start_date, end_date,
                   rain_format, series_name, output_path, meta=None):
    """Check the series, then write the .dat and its summary. Returns the summary.

    Raises ValueError (nothing written) when the series is not usable.
    """
    if rain_format not in ("intensity", "volume"):
        raise ValueError(f"rain_format must be intensity or volume, not '{rain_format}'")
    if not series_name or len(series_name.split()) != 1:
        raise ValueError("series_name must be one word (SWMM names have no blanks)")
    if end_date < start_date:
        raise ValueError("end_date is before start_date")

    d, p, problems = cut_period(dates, precip_mm, timestep_seconds, start_date, end_date)
    if problems:
        raise ValueError("rain series not usable, nothing written:\n  - "
                         + "\n  - ".join(problems))

    ts = int(timestep_seconds)
    step_hours = ts / 3600.0
    records = rain_series_to_records(d, p, ts, rain_format)

    # what the file will hold (4 decimals) against what the source gave
    source_total = float(p.sum())
    per_value_mm = step_hours if rain_format == "intensity" else 1.0
    file_total = sum(round(v, 4) for _, v in records) * per_value_mm
    if source_total > 0 and abs(file_total - source_total) > TOTAL_TOLERANCE * source_total:
        raise ValueError(f"rain total in the file would be {file_total:.3f} mm against "
                         f"{source_total:.3f} mm from the source; nothing written")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        n_written = write_swmm_timeseries(
            records, tmp_path, series_name,
            generated_by="build_rain_timeseries_from_source.py",
            coverage=(datetime(start_date.year, start_date.month, start_date.day),
                      datetime(end_date.year, end_date.month, end_date.day)
                      + timedelta(days=1)))
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    daily = {}
    for dt, mm in zip(d.tolist(), p.tolist()):
        key = dt.strftime("%Y-%m-%d")
        daily[key] = daily.get(key, 0.0) + mm
    fmt_word = "INTENSITY" if rain_format == "intensity" else "VOLUME"
    interval = interval_string(ts)
    summary = dict(meta or {})
    summary.update({
        "output": str(output_path),
        "series_name": series_name,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "time_zone": "UTC",
        "timestep_seconds": ts,
        "n_steps": int(len(p)),
        "n_rows_written": int(n_written),
        "rain_format": rain_format,
        "value_unit": "mm/hr" if rain_format == "intensity" else "mm per step",
        "raingage_format": fmt_word,
        "raingage_interval": interval,
        "raingage_line": f"<gage> {fmt_word} {interval} 1.0 TIMESERIES {series_name}",
        "total_mm": round(source_total, 3),
        "total_mm_in_file": round(file_total, 3),
        "max_mm_per_step": round(float(p.max()), 3),
        "max_intensity_mm_hr": round(float(p.max()) / step_hours, 3),
        "daily_total_mm": {k: round(v, 3) for k, v in sorted(daily.items())},
    })
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2))
    summary["summary_path"] = str(summary_path)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build a SWMM rainfall timeseries straight from a forcing source")
    parser.add_argument("--source", required=True, choices=SOURCES,
                        help="Forcing source, read through ki_tools_common.load_forcing. "
                             "There is no default: name the source.")
    parser.add_argument("--points", required=True,
                        help='One or more points: "lat,lon" or "lat,lon;lat,lon;..."')
    parser.add_argument("--method", default="average", choices=["average", "nearest"],
                        help="More than one point: mean of the points (average) or the "
                             "point nearest to their centre (nearest). Default: average")
    parser.add_argument("--start_date", required=True, help="First day, YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="Last day (included), YYYY-MM-DD")
    parser.add_argument("--forcing_dir", default=None,
                        help="Root folder of the cmfd / mswx store (not used by nasa_power)")
    parser.add_argument("--rain_format", required=True, choices=["intensity", "volume"],
                        help="intensity: mm/hr (FORMAT INTENSITY); volume: mm per step "
                             "(FORMAT VOLUME)")
    parser.add_argument("--series_name", default="RainGage1",
                        help="Timeseries name in SWMM (default: RainGage1)")
    parser.add_argument("--output", required=True, help="Output SWMM timeseries file (.dat)")
    args = parser.parse_args()

    try:
        points = parse_points(args.points)
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        if end_date < start_date:
            raise ValueError("--end_date is before --start_date")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    if args.source in ("cmfd", "mswx") and args.forcing_dir \
            and not os.path.isdir(args.forcing_dir):
        print(f"ERROR: --forcing_dir not found: {args.forcing_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.source} precipitation for {len(points)} point(s), "
          f"{args.start_date} to {args.end_date}...")
    try:
        series_list = load_points(args.source, points, start_date.year, end_date.year,
                                  forcing_dir=args.forcing_dir)
    except Exception as e:
        print(f"ERROR: {args.source} could not give {start_date.year}-{end_date.year} "
              f"at {points}: {type(e).__name__}: {e}\nNothing written.", file=sys.stderr)
        sys.exit(2)

    try:
        dates, precip, ts, used = combine_points(series_list, points, args.method)
        meta = {
            "source": args.source,
            "points": [list(p) for p in points],
            "method": args.method if len(points) > 1 else "single point",
            "point_used": list(points[used]) if used is not None else None,
            "forcing_dir": args.forcing_dir,
        }
        summary = build_rain_dat(dates, precip, ts, start_date, end_date,
                                 args.rain_format, args.series_name, args.output, meta)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"  Step: {summary['timestep_seconds']} s, {summary['n_steps']} steps, "
          f"{summary['n_rows_written']} non-zero rows written (times are UTC)")
    print(f"  Rain total: {summary['total_mm']:.1f} mm "
          f"(in the file: {summary['total_mm_in_file']:.1f} mm)")
    print(f"  Highest: {summary['max_mm_per_step']:.2f} mm in one step = "
          f"{summary['max_intensity_mm_hr']:.2f} mm/hr")
    print(f"\nTimeseries written: {summary['output']}")
    print(f"Summary written:    {summary['summary_path']}")
    print("\nUse this in the .inp (FORMAT and INTERVAL must match the data):")
    print("  [RAINGAGES]")
    print(f"  {summary['raingage_line']}")
    print(f"  ;; FORMAT {summary['raingage_format']}  INTERVAL {summary['raingage_interval']}")


if __name__ == "__main__":
    main()
