#!/usr/bin/env python3
"""Extract native HYDAT daily flows without modifying the acquired database."""
from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3

VERSION = "1.0.0"
UNIT_SOURCE = "https://www.canada.ca/en/environment-climate-change/services/environmental-indicators/water-quantity-canadian-rivers.html"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def ranges(values):
    result = []
    for value in sorted(values):
        if result and value == result[-1][1] + timedelta(days=1):
            result[-1][1] = value
        else:
            result.append([value, value])
    return [{"start": a.isoformat(), "end": b.isoformat(), "days": (b-a).days+1}
            for a, b in result]


def numeric(value):
    if value is None:
        return "missing", None
    if not isinstance(value, (int, float)):
        return "not_numeric", None
    return ("finite", float(value)) if math.isfinite(value) else ("nonfinite", None)


def extract(source, station, start, end, output_dir):
    source, output_dir = Path(source).resolve(), Path(output_dir).resolve()
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or (end-start).days > 36600:
        raise ValueError("require an ordered period of at most 100 years")
    if not station or not source.is_file():
        raise ValueError("provide an existing HYDAT database and an exact station number")
    if output_dir.exists():
        raise ValueError("output directory must be new; existing outputs are preserved")
    before = {"name": source.name, "bytes": source.stat().st_size, "sha256": digest(source)}
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        required = {
            "STATIONS": {"STATION_NUMBER", "STATION_NAME", "LATITUDE", "LONGITUDE"},
            "DLY_FLOWS": {"STATION_NUMBER", "YEAR", "MONTH"} |
                {f"FLOW{i}" for i in range(1, 32)} | {f"FLOW_SYMBOL{i}" for i in range(1, 32)},
            "DATA_SYMBOLS": {"SYMBOL_ID", "SYMBOL_EN", "SYMBOL_FR"},
        }
        schema = {}
        for table, columns in required.items():
            schema[table] = [r["name"] for r in connection.execute(f'PRAGMA table_info("{table}")')]
            if not columns.issubset(schema[table]):
                raise ValueError(f"unsupported HYDAT schema: {table} missing {sorted(columns-set(schema[table]))}")
        stations = connection.execute("SELECT * FROM STATIONS WHERE STATION_NUMBER = ?", (station,)).fetchall()
        if len(stations) != 1:
            raise ValueError(f"expected one station record, found {len(stations)}")
        station_metadata = dict(stations[0])
        for name, limit in (("LATITUDE", 90), ("LONGITUDE", 180)):
            state, value = numeric(station_metadata[name])
            if state != "finite" or abs(value) > limit:
                raise ValueError(f"station {name} is missing or invalid")
        symbols = [dict(r) for r in connection.execute("SELECT * FROM DATA_SYMBOLS ORDER BY SYMBOL_ID")]
        versions = ([dict(r) for r in connection.execute("SELECT * FROM VERSION")]
                    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='VERSION'").fetchone()
                    else [])
        rows, seen, finite_dates, values = [], Counter(), set(), []
        states, flags = Counter(), Counter()
        sql = "SELECT rowid AS source_rowid, * FROM DLY_FLOWS WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ? ORDER BY YEAR, MONTH, rowid"
        for record in connection.execute(sql, (station, start.year, end.year)):
            year, month = record["YEAR"], record["MONTH"]
            if type(year) is not int or type(month) is not int or not 1 <= month <= 12:
                raise ValueError("invalid YEAR/MONTH in selected station records")
            for day in range(1, calendar.monthrange(year, month)[1]+1):
                when = date(year, month, day)
                if not start <= when <= end:
                    continue
                value, flag = record[f"FLOW{day}"], record[f"FLOW_SYMBOL{day}"]
                state, number = numeric(value)
                seen[when] += 1
                states[state] += 1
                flags["<NULL>" if flag is None else str(flag)] += 1
                if number is not None:
                    finite_dates.add(when)
                    values.append(number)
                rows.append({"station_number": station, "date": when.isoformat(),
                             "discharge_native": "" if value is None else str(value),
                             "value_status": state, "quality_symbol_raw": "" if flag is None else str(flag),
                             "quality_symbol_is_null": flag is None, "source_file": source.name,
                             "source_rowid": record["source_rowid"], "source_day_column": f"FLOW{day}"})
    finally:
        connection.close()
    if not rows:
        raise ValueError("no selected station daily records in the requested period")
    if digest(source) != before["sha256"] or source.stat().st_size != before["bytes"]:
        raise ValueError("source changed during extraction; no outputs published")
    expected = {start + timedelta(days=i) for i in range((end-start).days+1)}
    missing, no_finite = expected-set(seen), expected-finite_dates
    duplicates = [{"date": d.isoformat(), "rows": n} for d, n in sorted(seen.items()) if n > 1]
    issues = bool(missing or no_finite or duplicates or any(v < 0 for v in values))
    report = {
        "schema_version": "geoforge.observation-reader/1", "data_ki": "HYDAT_Observations",
        "reader_version": VERSION, "reader_sha256": digest(Path(__file__)),
        "dataset_id": "hydat_sqlite", "execution_scope": "data_preparation", "model_executed": False,
        "status": "review_required" if issues else "extracted", "source": before,
        "source_unchanged": True, "database_version": versions, "source_schema": schema,
        "station": station_metadata, "requested": {"station": station, "start": start.isoformat(), "end": end.isoformat()},
        "units": {"quantity": "daily mean discharge", "unit": "m3/s", "source": UNIT_SOURCE,
                  "evidence": "ECCC documentation; no units column in inspected DLY_FLOWS", "conversion_applied": False},
        "time": {"representation": "native calendar date", "timezone": None,
                 "utc_offset": None, "day_boundary_verified": False},
        "rows": len(rows), "expected_calendar_days": len(expected), "unique_calendar_dates": len(seen),
        "missing_calendar_dates_count": len(missing), "missing_calendar_ranges": ranges(missing),
        "days_without_finite_value": len(no_finite), "without_finite_value_ranges": ranges(no_finite),
        "duplicate_calendar_dates": duplicates, "value_status_counts": dict(states),
        "minimum_native": min(values) if values else None, "maximum_native": max(values) if values else None,
        "negative_values": sum(v < 0 for v in values), "quality_symbol_counts": dict(flags),
        "quality_symbol_definitions": symbols, "quality_policy_applied": "none; all native symbols retained",
        "limitations": ["No gap filling, unit conversion, flag filtering or weather generation.",
                        "Missing monthly records are reported as gaps, never emitted as invented daily observations.",
                        "Empty and NULL quality symbols do not assert quality assurance.",
                        "Confirm daily time convention and model/observation quantities before comparison."],
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    result = output_dir / "observations.csv"
    with result.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report["output"] = {"name": result.name, "bytes": result.stat().st_size, "sha256": digest(result)}
    (output_dir / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="already acquired HYDAT SQLite file")
    parser.add_argument("--station", required=True, help="exact STATION_NUMBER")
    parser.add_argument("--start", required=True, help="inclusive native date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="inclusive native date YYYY-MM-DD")
    parser.add_argument("--output-dir", required=True, help="new output directory")
    args = parser.parse_args()
    try:
        report = extract(args.source, args.station, args.start, args.end, args.output_dir)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"HYDAT reader failed: {exc}\n")
    print(json.dumps({"status": report["status"], "rows": report["rows"], "model_executed": False}))


if __name__ == "__main__":
    main()
