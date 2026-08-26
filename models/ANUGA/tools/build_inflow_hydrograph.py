#!/usr/bin/env python3
"""Build an ANUGA inflow hydrograph CSV from a gauge discharge record.

ANUGA's dag lists "inflow discharge" (m^3/s, applied via Inlet_operator) as a
first-class forcing for riverine flooding, but no tool produced one: the KI
could only drive rain-on-grid via Rate_operator. This tool closes that gap by
converting a daily gauge discharge series into the CSV that
run_anuga.py --inflow_csv consumes.

Input format A -- `--gauge_txt`, China water-level archive, e.g.
KISSPATH_DATA/china_water_level/淮河txt/*.txt:

    stcd	dates	z	Q	name
    50101100	1952-5-30	0	403	王家坝

  - TAB separated, one header row
  - `dates` is NOT zero padded (2003-7-1, not 2003-07-01)
  - -99 is the missing-value sentinel (z is frequently -99 even when Q is good)
  - Q is discharge in m^3/s

Input format B -- `--gauge_csv`, the tidy `date,value[,symbol]` CSV emitted by
tools/load_hydat_series.py (HYDAT and any other archive normalised to it):

    date,value,symbol
    2020-04-01,920.0000,

  - comma separated, ISO dates, `value` is discharge in m^3/s
  - the -99 / negative sentinel rule is applied here too, so a source that
    encodes missing data as a negative number cannot silently under-drive the
    inlet.

Exactly one of --gauge_txt / --gauge_csv is required.

Output CSV (consumed by run_anuga.py):

    time_seconds,discharge_m3s
    0.0,3540.0
    86400.0,3610.0

  time_seconds is relative to --start at 00:00, so it shares the t=0 origin of
  the rainfall CSV emitted by convert_forcing_to_anuga.py.

Example:
    python tools/build_inflow_hydrograph.py \
        --gauge_txt KISSPATH_DATA/china_water_level/淮河txt/鲁台子.txt \
        --start 2003-07-01 --end 2003-08-07 \
        --output_csv ./forcing/inflow_lutaizi.csv
"""

import argparse
import csv
import datetime as dt
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MISSING = -99.0
SECONDS_PER_DAY = 86400.0


def parse_loose_date(s):
    """Parse a non-zero-padded date such as '2003-7-1' → datetime.date."""
    y, m, d = (int(p) for p in s.strip().split("-"))
    return dt.date(y, m, d)


def load_gauge_series(gauge_txt, start, end):
    """Read the gauge archive and return [(date, Q_m3s)] within [start, end].

    Rows whose Q is the -99 sentinel, blank, or unparseable are dropped. The
    z (stage) column is ignored entirely: it is -99 across the Huai archive,
    so a stage-driven Time_boundary is not constructible from this source.
    """
    if not os.path.isfile(gauge_txt):
        raise FileNotFoundError(f"Gauge file not found: {gauge_txt}")

    kept, dropped = [], 0
    with open(gauge_txt, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        missing_cols = {"dates", "Q"} - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(
                f"{gauge_txt}: missing required column(s) {sorted(missing_cols)}; "
                f"found {reader.fieldnames}"
            )
        for row in reader:
            try:
                date = parse_loose_date(row["dates"])
            except (ValueError, AttributeError):
                continue
            if not (start <= date <= end):
                continue
            raw = (row.get("Q") or "").strip()
            try:
                q = float(raw)
            except ValueError:
                dropped += 1
                continue
            if q <= MISSING or q < 0.0:
                dropped += 1
                continue
            kept.append((date, q))

    kept.sort(key=lambda r: r[0])
    if dropped:
        logger.warning(f"Dropped {dropped} row(s) with missing/sentinel Q")
    return kept


def load_gauge_csv(gauge_csv, start, end):
    """Read a tidy `date,value[,symbol]` CSV and return [(date, Q_m3s)].

    This is the load_hydat_series.py output format. Same sentinel rule as the
    China archive reader: non-numeric, negative and <= -99 values are dropped
    rather than injected as inflow.
    """
    if not os.path.isfile(gauge_csv):
        raise FileNotFoundError(f"Gauge CSV not found: {gauge_csv}")

    kept, dropped = [], 0
    with open(gauge_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_cols = {"date", "value"} - set(reader.fieldnames or [])
        if missing_cols:
            raise ValueError(
                f"{gauge_csv}: missing required column(s) {sorted(missing_cols)}; "
                f"found {reader.fieldnames}"
            )
        for row in reader:
            try:
                date = dt.date.fromisoformat((row["date"] or "").strip())
            except (ValueError, AttributeError):
                continue
            if not (start <= date <= end):
                continue
            try:
                q = float((row.get("value") or "").strip())
            except ValueError:
                dropped += 1
                continue
            if q <= MISSING or q < 0.0:
                dropped += 1
                continue
            kept.append((date, q))

    kept.sort(key=lambda r: r[0])
    if dropped:
        logger.warning(f"Dropped {dropped} row(s) with missing/sentinel value")
    return kept


def to_hydrograph(series, start):
    """Convert [(date, Q)] → (times_seconds, discharges) with t=0 at `start`."""
    times = [(d - start).days * SECONDS_PER_DAY for d, _ in series]
    flows = [q for _, q in series]
    return times, flows


def validate_series(series, start, end):
    """Fail loud rather than emit a hydrograph that would silently under-drive."""
    if len(series) < 2:
        raise ValueError(
            f"Only {len(series)} valid discharge value(s) in {start}..{end}; "
            "an inflow hydrograph needs at least 2. Check the gauge record "
            "covers the event window and that Q is not all -99."
        )

    span_days = (end - start).days + 1
    coverage = len(series) / float(span_days)
    if coverage < 0.8:
        raise ValueError(
            f"Gauge covers only {len(series)}/{span_days} days "
            f"({coverage:.0%}) of {start}..{end}; refusing to build a "
            "hydrograph with >20% of the event window missing."
        )

    flows = [q for _, q in series]
    if max(flows) <= 0.0:
        raise ValueError(
            f"All discharge values are <= 0 (max {max(flows)}); the inlet "
            "would inject no water and inundation would be structurally zero."
        )
    logger.info(
        f"Gauge series OK: {len(series)}/{span_days} days, "
        f"Q {min(flows):.1f}..{max(flows):.1f} m^3/s"
    )


def process(args):
    start = parse_loose_date(args.start)
    end = parse_loose_date(args.end)
    if end < start:
        raise ValueError(f"--end {end} precedes --start {start}")

    if bool(args.gauge_txt) == bool(args.gauge_csv):
        raise ValueError(
            "Give exactly one of --gauge_txt (China TAB archive) or "
            "--gauge_csv (tidy date,value CSV from load_hydat_series.py)"
        )

    if args.gauge_txt:
        series = load_gauge_series(args.gauge_txt, start, end)
    else:
        series = load_gauge_csv(args.gauge_csv, start, end)
    validate_series(series, start, end)
    times, flows = to_hydrograph(series, start)

    out_dir = os.path.dirname(os.path.abspath(args.output_csv))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_seconds", "discharge_m3s"])
        for t, q in zip(times, flows):
            w.writerow([f"{t:.1f}", f"{q:.3f}"])

    logger.info(
        f"Wrote {args.output_csv}: {len(times)} rows, "
        f"t 0..{times[-1]:.0f}s, peak {max(flows):.1f} m^3/s"
    )
    return args.output_csv


def main():
    p = argparse.ArgumentParser(
        description="Build an ANUGA Inlet_operator inflow hydrograph CSV "
                    "from a gauge discharge archive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--gauge_txt", default=None,
                   help="Tab-separated gauge file with stcd/dates/z/Q/name columns")
    p.add_argument("--gauge_csv", default=None,
                   help="Tidy date,value[,symbol] CSV (load_hydat_series.py "
                        "output); value is discharge in m^3/s. Mutually "
                        "exclusive with --gauge_txt")
    p.add_argument("--start", required=True, help="Window start, YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Window end (inclusive), YYYY-MM-DD")
    p.add_argument("--output_csv", required=True,
                   help="Output CSV: time_seconds,discharge_m3s")
    args = p.parse_args()

    try:
        process(args)
    except Exception as e:
        logger.error(f"{type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
