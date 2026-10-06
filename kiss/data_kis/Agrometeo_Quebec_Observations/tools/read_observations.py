#!/usr/bin/env python3
"""Extract native station soil temperature from acquired Agrometeo yearly CSVs."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path

VERSION = "1.0.0"
FIELDS = ["Station", "date", "latitude", "longitude"]
TEMPERATURE_HEADERS = {"soil temp (°C)", "soil temp(°C)"}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def ranges(values):
    result = []
    for value in sorted(values):
        if result and value == result[-1][1]+timedelta(hours=1):
            result[-1][1] = value
        else:
            result.append([value, value])
    return [{"start": a.isoformat(sep=" "), "end": b.isoformat(sep=" "),
             "hours": int((b-a).total_seconds()/3600)+1} for a, b in result]


def extract(sources, station, start, end, output_dir):
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if start_date > end_date or (end_date-start_date).days > 36600 or not station:
        raise ValueError("require an exact station and ordered period of at most 100 years")
    start = datetime.combine(start_date, time.min)
    stop = datetime.combine(end_date+timedelta(days=1), time.min)
    files = []
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise ValueError("output directory must be new; existing outputs are preserved")
    for raw in sources:
        path = Path(raw).resolve()
        if path.is_dir():
            if output_dir.is_relative_to(path):
                raise ValueError("outputs must not be placed inside the raw data directory")
            files.extend(sorted(path.glob("soilTemp10cm_*.csv")))
        else:
            files.append(path)
    files = sorted(set(p.resolve() for p in files))
    if not files or any(not p.is_file() for p in files):
        raise ValueError("no matching acquired soilTemp10cm CSV files")
    if len(files) > 200:
        raise ValueError("select at most 200 explicit source files")
    # Rows bind their source by basename; require a unique portable identifier.
    if len({path.name.casefold() for path in files}) != len(files):
        raise ValueError("ambiguous source basenames; select files with unique names")
    rows, excluded, sources_meta, values = [], [], [], []
    seen, finite_times, coords, states = Counter(), set(), Counter(), Counter()
    off_hour = invalid_coords = suspect_sentinels = 0
    for path in files:
        before = {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        with path.open("rb") as stream:
            header_bytes = stream.readline()
        try:
            header_bytes.decode("utf-8-sig", errors="strict")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            encoding = "cp1252"
        count = 0
        with path.open(encoding=encoding, errors="strict", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, [])
            if len(header) != 5 or header[:4] != FIELDS or header[4] not in TEMPERATURE_HEADERS:
                raise ValueError(f"unsupported soil-temperature schema/units in {path.name}: {header!r}")
            for record_number, record in enumerate(reader, 2):
                count += 1
                if len(record) != 5:
                    raise ValueError(f"wrong field count in {path.name}, CSV record {record_number}")
                if record[0] != station:
                    continue
                item = {"station": record[0], "timestamp_native": record[1], "latitude_raw": record[2],
                        "longitude_raw": record[3], "soil_temperature_C_raw": record[4],
                        "source_file": path.name, "source_csv_record": record_number}
                try:
                    when = datetime.strptime(record[1], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    excluded.append({**item, "reason": "unparseable_native_timestamp"})
                    continue
                if not start <= when < stop:
                    excluded.append({**item, "reason": "outside_requested_period"})
                    continue
                seen[when] += 1
                off_hour += when.minute != 0 or when.second != 0
                try:
                    lat, lon = float(record[2]), float(record[3])
                    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                        raise ValueError("invalid coordinate")
                    coords[(lat, lon)] += 1
                except ValueError:
                    invalid_coords += 1
                value, state = None, "missing" if not record[4].strip() else "not_numeric"
                try:
                    value = float(record[4])
                    state = "finite" if math.isfinite(value) else "nonfinite"
                except ValueError:
                    pass
                states[state] += 1
                if state == "finite":
                    finite_times.add(when)
                    values.append(value)
                    suspect_sentinels += value in {-99999, -9999, -999, -99, 999, 9999, 99999}
                rows.append({**item, "value_status": state})
        if path.stat().st_size != before["bytes"] or digest(path) != before["sha256"]:
            raise ValueError(f"source changed during extraction: {path.name}")
        sources_meta.append({**before, "encoding": encoding, "header": header, "data_records_scanned": count,
                             "source_unchanged": True})
    if not rows:
        raise ValueError("no selected station records in the requested period")
    expected = {start + timedelta(hours=i) for i in range(int((stop-start).total_seconds()/3600))}
    missing, no_finite = expected-set(seen), expected-finite_times
    duplicates = [{"timestamp_native": d.isoformat(sep=" "), "rows": n} for d, n in sorted(seen.items()) if n > 1]
    unparseable = sum(r["reason"] == "unparseable_native_timestamp" for r in excluded)
    issues = bool(missing or no_finite or duplicates or unparseable or off_hour or invalid_coords or len(coords) != 1 or suspect_sentinels)
    report = {
        "schema_version": "geoforge.observation-reader/1", "data_ki": "Agrometeo_Quebec_Observations",
        "reader_version": VERSION, "reader_sha256": digest(Path(__file__)), "dataset_id": "agrometeo_quebec",
        "execution_scope": "data_preparation", "model_executed": False, "status": "review_required" if issues else "extracted",
        "requested": {"station": station, "start": start_date.isoformat(), "end": end_date.isoformat()},
        "sources": sources_meta, "units": {"quantity": "soil temperature", "unit": "degC", "evidence": "explicit CSV header", "conversion_applied": False},
        "depth": {"nominal_m": 0.1 if all(p.name.startswith("soilTemp10cm_") for p in files) else None,
                  "evidence": "soilTemp10cm filename only; not per-sensor metadata"},
        "time": {"representation": "native naive timestamp", "timezone": None, "utc_offset": None,
                 "expected_grid": "hourly native wall-clock labels; no UTC/DST conversion"},
        "quality_flag_fields": [], "weather_fields": [], "qc_pass_claimed": False,
        "rows": len(rows), "unique_timestamps": len(seen), "expected_hourly_timestamps": len(expected),
        "missing_hourly_timestamps": len(missing), "missing_hourly_ranges": ranges(missing),
        "hours_without_finite_value": len(no_finite), "without_finite_value_ranges": ranges(no_finite),
        "duplicate_timestamps": duplicates, "off_hour_records": off_hour, "value_status_counts": dict(states),
        "minimum_C": min(values) if values else None, "maximum_C": max(values) if values else None,
        "suspected_sentinel_values": suspect_sentinels, "sentinel_definition_supplied": False,
        "coordinates": [{"latitude": a, "longitude": b, "rows": n} for (a, b), n in sorted(coords.items())],
        "invalid_coordinate_records": invalid_coords, "excluded_selected_records": len(excluded),
        "unparseable_selected_timestamps": unparseable,
        "limitations": ["No interpolation, resampling, unit conversion or weather generation.",
                        "Finite values and complete timestamps do not establish scientific quality.",
                        "No QC flags, timezone or sensor-depth column exists in the supported delivery schema.",
                        "CSV record numbers count parsed records including the header, not physical text lines."],
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    report["outputs"] = []
    for name, records in (("observations.csv", rows), ("excluded_selected_records.csv", excluded)):
        if not records:
            continue
        output = output_dir / name
        with output.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        report["outputs"].append({"name": name, "bytes": output.stat().st_size, "sha256": digest(output)})
    (output_dir / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", nargs="+", required=True, help="acquired CSV files or a directory of soilTemp10cm_*.csv")
    parser.add_argument("--station", required=True, help="exact native station name")
    parser.add_argument("--start", required=True, help="inclusive native date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="inclusive native date YYYY-MM-DD")
    parser.add_argument("--output-dir", required=True, help="new output directory")
    args = parser.parse_args()
    try:
        report = extract(args.source, args.station, args.start, args.end, args.output_dir)
    except (ValueError, OSError, csv.Error) as exc:
        parser.exit(2, f"Agrometeo reader failed: {exc}\n")
    print(json.dumps({"status": report["status"], "rows": report["rows"], "model_executed": False}))


if __name__ == "__main__":
    main()
