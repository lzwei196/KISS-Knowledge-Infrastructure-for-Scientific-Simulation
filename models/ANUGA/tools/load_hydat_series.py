#!/usr/bin/env python3
"""Extract a daily HYDAT series (discharge or water level) to a tidy CSV.

Why this exists
---------------
The ANUGA KI could only read the China water-level archive
(`build_inflow_hydrograph.py --gauge_txt`, TAB/-99 format). HYDAT — the
national Canadian archive named as a `desired obs` source for both the
`stage` and `discharge` dag outputs — is a SQLite database with a
month-per-row / day-per-column layout, so nothing in the KI could open it.
This tool closes that gap for BOTH roles:

  * `--variable flow`  -> the upstream driver for build_inflow_hydrograph.py
  * `--variable level` -> the observation the `stage` output is scored against

Layout traps this tool handles (do NOT hand-roll these again):

  1. DLY_FLOWS / DLY_LEVELS store ONE ROW PER STATION-MONTH with 31 value
     columns (FLOW1..FLOW31 / LEVEL1..LEVEL31) plus a parallel symbol column.
     Day columns past the month length hold NULL, and Feb 30/31 must be
     rejected by calendar validation, not by trusting NULLs.
  2. Water level is referenced to the station's OWN vertical datum
     (STATIONS.DATUM_ID). Many stations use an arbitrary/assumed local datum
     whose zero is meaningless; ANUGA carries no datum awareness, so a stage
     comparison is only meaningful when the datum is geodetic. The sidecar
     JSON reports the datum name and every STN_DATUM_CONVERSION offset so the
     caller can check this instead of silently comparing incompatible heights.
  3. The Hydat.sqlite3 shipped on /mnt/disk4 is opened read-only via
     `immutable=1`; `mode=ro` alone fails on read-only media for WAL files.

Output CSV (consumed by build_inflow_hydrograph.py --gauge_csv, and directly
usable as an observation series):

    date,value,symbol
    2020-04-01,920.0,
    2020-04-02,906.0,E

Sidecar JSON (<output_csv>.meta.json) carries station identity, datum and
coverage so the caller never has to re-open the database.

Example:
    python tools/load_hydat_series.py \
        --station 08MF005 --variable flow \
        --start 2020-04-01 --end 2020-06-30 \
        --output_csv ./obs/hope_flow.csv
"""

import argparse
import csv
import datetime as dt
import json
import logging
import os
import sqlite3
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB = "/mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3"

VARIABLES = {
    # variable -> (table, value column prefix, symbol column prefix, unit)
    "flow": ("DLY_FLOWS", "FLOW", "FLOW_SYMBOL", "m3/s"),
    "level": ("DLY_LEVELS", "LEVEL", "LEVEL_SYMBOL", "m"),
}

# HYDAT DATA_TYPE codes in STN_DATA_RANGE
DATA_TYPE = {"flow": "Q", "level": "H"}


def connect(db_path):
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"HYDAT database not found: {db_path}")
    # immutable=1, not mode=ro: the archive lives on read-only media and a
    # bare mode=ro connection fails to open the -wal sidecar.
    return sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)


def station_metadata(conn, station):
    cur = conn.cursor()
    row = cur.execute(
        "SELECT STATION_NUMBER, STATION_NAME, PROV_TERR_STATE_LOC, LATITUDE, "
        "LONGITUDE, DRAINAGE_AREA_GROSS, DATUM_ID, HYD_STATUS "
        "FROM STATIONS WHERE STATION_NUMBER = ?",
        (station,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Station {station} not present in HYDAT STATIONS")

    keys = ("station_id", "station_name", "prov", "lat", "lon",
            "drainage_area_km2", "datum_id", "hyd_status")
    meta = dict(zip(keys, row))

    datum_name = cur.execute(
        "SELECT DATUM_EN FROM DATUM_LIST WHERE DATUM_ID = ?",
        (meta["datum_id"],),
    ).fetchone()
    meta["datum_name"] = datum_name[0] if datum_name else None

    # Every published conversion FROM this station's datum, e.g.
    # (35 -> 605, +0.163) = add 0.163 m to go from GSC datum to CGVD2013.
    meta["datum_conversions"] = [
        {"from_datum_id": a, "to_datum_id": b,
         "to_datum_name": (cur.execute(
             "SELECT DATUM_EN FROM DATUM_LIST WHERE DATUM_ID = ?", (b,)
         ).fetchone() or [None])[0],
         "add_m": f}
        for a, b, f in cur.execute(
            "SELECT DATUM_ID_FROM, DATUM_ID_TO, CONVERSION_FACTOR "
            "FROM STN_DATUM_CONVERSION WHERE STATION_NUMBER = ?", (station,))
    ]
    meta["regulation"] = [
        {"year_from": a, "year_to": b, "regulated": bool(c)}
        for a, b, c in cur.execute(
            "SELECT YEAR_FROM, YEAR_TO, REGULATED FROM STN_REGULATION "
            "WHERE STATION_NUMBER = ?", (station,))
    ]
    return meta


def load_series(conn, station, variable, start, end):
    """Return {date: (value, symbol)} for [start, end] inclusive."""
    table, vpfx, spfx, _unit = VARIABLES[variable]
    cur = conn.cursor()

    cols = [d[0] for d in cur.execute(
        f"SELECT * FROM {table} LIMIT 1").description]

    rows = cur.execute(
        f"SELECT * FROM {table} WHERE STATION_NUMBER = ? "
        "AND YEAR BETWEEN ? AND ?",
        (station, start.year, end.year),
    ).fetchall()

    out = {}
    for raw in rows:
        rec = dict(zip(cols, raw))
        year, month = rec["YEAR"], rec["MONTH"]
        for day in range(1, 32):
            val = rec.get(f"{vpfx}{day}")
            if val is None:
                continue
            try:
                # Day columns run to 31 for EVERY month; Feb 30 must be
                # rejected on the calendar, not assumed NULL.
                date = dt.date(year, month, day)
            except ValueError:
                continue
            if not (start <= date <= end):
                continue
            sym = rec.get(f"{spfx}{day}") or ""
            out[date] = (float(val), str(sym).strip())
    return out


def validate(series, station, variable, start, end, min_coverage):
    span = (end - start).days + 1
    if not series:
        raise ValueError(
            f"No {variable} values for {station} in {start}..{end}. Check "
            "STN_DATA_RANGE: seasonal stations (e.g. freshet-only level "
            "gauges) have no record outside their operating months."
        )
    cov = len(series) / float(span)
    if cov < min_coverage:
        raise ValueError(
            f"{station} {variable}: only {len(series)}/{span} days "
            f"({cov:.0%}) present in {start}..{end}; below --min_coverage "
            f"{min_coverage:.0%}. Refusing to emit a gappy series that would "
            "silently shorten the scored period."
        )
    vals = [v for v, _ in series.values()]
    logger.info(
        "%s %s: %d/%d days (%.0f%%), range %.3f..%.3f",
        station, variable, len(series), span, 100 * cov, min(vals), max(vals),
    )
    return cov


def process(args):
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        raise ValueError(f"--end {end} precedes --start {start}")

    conn = connect(args.db)
    try:
        meta = station_metadata(conn, args.station)
        series = load_series(conn, args.station, args.variable, start, end)
    finally:
        conn.close()

    cov = validate(series, args.station, args.variable, start, end,
                   args.min_coverage)

    out_dir = os.path.dirname(os.path.abspath(args.output_csv))
    os.makedirs(out_dir, exist_ok=True)
    dates = sorted(series)
    with open(args.output_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value", "symbol"])
        for d in dates:
            v, s = series[d]
            w.writerow([d.isoformat(), f"{v:.4f}", s])

    symbols = {}
    for _v, s in series.values():
        symbols[s or "(none)"] = symbols.get(s or "(none)", 0) + 1

    meta.update({
        "variable": args.variable,
        "unit": VARIABLES[args.variable][3],
        "hydat_data_type": DATA_TYPE[args.variable],
        "db": args.db,
        "period_start": dates[0].isoformat(),
        "period_end": dates[-1].isoformat(),
        "n_days": len(dates),
        "coverage": round(cov, 4),
        "symbol_counts": symbols,
        "output_csv": os.path.abspath(args.output_csv),
    })
    meta_path = args.output_csv + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Wrote %s (%d rows) and %s", args.output_csv, len(dates),
                meta_path)
    logger.info("Datum: %s (id %s); conversions: %s",
                meta["datum_name"], meta["datum_id"],
                meta["datum_conversions"] or "none published")
    return args.output_csv


def main():
    p = argparse.ArgumentParser(
        description="Extract a daily HYDAT flow/level series to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", default=DEFAULT_DB, help="Hydat.sqlite3 path")
    p.add_argument("--station", required=True, help="HYDAT station number")
    p.add_argument("--variable", required=True, choices=sorted(VARIABLES),
                   help="flow (m3/s, DLY_FLOWS) or level (m, DLY_LEVELS)")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--output_csv", required=True)
    p.add_argument("--min_coverage", type=float, default=0.9,
                   help="Minimum fraction of days present (default 0.9)")
    args = p.parse_args()
    try:
        process(args)
    except Exception as e:
        logger.error("%s: %s", type(e).__name__, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
