"""SYNTHETIC CSV fixtures exercising real delivery-format edge cases."""
import csv
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agrometeo_data_ki_reader", ROOT/"tools/read_observations.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def source(tmp_path, encoding="utf-8", change=None):
    fixture = json.loads((ROOT/"fixtures/synthetic_agrometeo.json").read_text(encoding="utf-8"))
    header = fixture["header"]
    start = datetime.fromisoformat(fixture["start_date"])
    rows = [[fixture["station"], (start+timedelta(hours=i)).isoformat(sep=" "),
             fixture["latitude_raw"], fixture["longitude_raw"], fixture["temperature_C_raw"]]
            for i in range(fixture["hour_count"])]
    if change:
        change(header, rows)
    path = tmp_path/"soilTemp10cm_2020.csv"
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def extract(path, tmp_path):
    return reader.extract([path], "Synthetic station", "2020-02-29", "2020-02-29", tmp_path/"result")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_native_field_text_encoding_complete_leap_day_and_hashes(tmp_path, encoding):
    path = source(tmp_path, encoding)
    before = reader.digest(path)
    report = extract(path, tmp_path)
    rows = list(csv.DictReader((tmp_path/"result/observations.csv").open(encoding="utf-8")))
    assert len(rows) == 24 and rows[0]["soil_temperature_C_raw"] == "1.2500"
    assert rows[0]["latitude_raw"] == "45.250000" and rows[0]["source_csv_record"] == "2"
    assert report["status"] == "extracted" and report["expected_hourly_timestamps"] == 24
    assert report["missing_hourly_ranges"] == [] and report["quality_flag_fields"] == []
    assert report["sources"][0]["sha256"] == before == reader.digest(path)
    assert report["outputs"][0]["sha256"] == reader.digest(tmp_path/"result/observations.csv")
    assert report["time"]["timezone"] is None and report["depth"]["nominal_m"] == 0.1
    assert report["model_executed"] is False and report["weather_fields"] == []


def test_gaps_duplicates_nonfinite_coordinate_change_and_exclusions(tmp_path):
    def change(header, rows):
        rows.pop(2)
        rows.append(rows[0].copy())
        rows[1][4] = "NaN"
        rows[3][2] = "45.26"
        rows.append(["Synthetic station", "bad time", "45", "-71", "2"])
        rows.append(["Synthetic station", "2020-03-01 00:00:00", "45", "-71", "2"])
    report = extract(source(tmp_path, change=change), tmp_path)
    assert report["status"] == "review_required" and report["missing_hourly_timestamps"] == 1
    assert report["missing_hourly_ranges"] == [{"start": "2020-02-29 02:00:00", "end": "2020-02-29 02:00:00", "hours": 1}]
    assert report["hours_without_finite_value"] == 2 and len(report["duplicate_timestamps"]) == 1
    assert len(report["coordinates"]) == 2 and report["excluded_selected_records"] == 2
    excluded = list(csv.DictReader((tmp_path/"result/excluded_selected_records.csv").open(encoding="utf-8")))
    assert {r["reason"] for r in excluded} == {"unparseable_native_timestamp", "outside_requested_period"}


@pytest.mark.parametrize("bad_header", ["soil temp(K)", "air temp(°C)"])
def test_wrong_quantity_or_units_rejected(tmp_path, bad_header):
    path = source(tmp_path, change=lambda header, rows: header.__setitem__(4, bad_header))
    with pytest.raises(ValueError, match="schema/units"):
        extract(path, tmp_path)
    assert not (tmp_path/"result").exists()


def test_malformed_other_station_row_is_not_silently_ignored(tmp_path):
    path = source(tmp_path, change=lambda header, rows: rows.append(["Other station", "bad"]))
    with pytest.raises(ValueError, match="field count"):
        extract(path, tmp_path)


def test_no_station_and_no_output_overwrite(tmp_path):
    path = source(tmp_path)
    with pytest.raises(ValueError, match="no selected station"):
        reader.extract([path], "Absent", "2020-02-29", "2020-02-29", tmp_path/"result")
    extract(path, tmp_path)
    before = (tmp_path/"result/observations.csv").read_bytes()
    with pytest.raises(ValueError, match="must be new"):
        extract(path, tmp_path)
    assert (tmp_path/"result/observations.csv").read_bytes() == before


def test_outputs_cannot_be_nested_in_raw_directory(tmp_path):
    source(tmp_path)
    with pytest.raises(ValueError, match="raw data directory"):
        reader.extract([tmp_path], "Synthetic station", "2020-02-29", "2020-02-29", tmp_path/"result")


def test_distinct_same_basename_sources_cannot_create_ambiguous_provenance(tmp_path):
    paths = []
    for folder in ("delivery1", "delivery2"):
        directory = tmp_path/folder
        directory.mkdir()
        paths.append(source(directory))
    with pytest.raises(ValueError, match="ambiguous source basenames"):
        reader.extract(paths, "Synthetic station", "2020-02-29", "2020-02-29", tmp_path/"result")
    assert not (tmp_path/"result").exists()
    # Listing the exact same resolved file twice is unambiguous and deduplicated.
    report = reader.extract([paths[0], paths[0]], "Synthetic station", "2020-02-29", "2020-02-29", tmp_path/"result")
    assert report["rows"] == 24 and len(report["sources"]) == 1
