"""Small SYNTHETIC schema fixtures, not scientific performance evidence."""
import csv
from datetime import date
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hydat_data_ki_reader", ROOT/"tools/read_observations.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


@pytest.fixture
def database(tmp_path):
    fixture = json.loads((ROOT/"fixtures/synthetic_hydat.json").read_text(encoding="utf-8"))
    path = tmp_path/"synthetic.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE STATIONS (STATION_NUMBER TEXT, STATION_NAME TEXT, LATITUDE REAL, LONGITUDE REAL)")
        db.execute("INSERT INTO STATIONS VALUES (?,?,?,?)", tuple(fixture["station"].values()))
        cols = ["STATION_NUMBER TEXT", "YEAR INTEGER", "MONTH INTEGER"]
        for day in range(1, 32):
            cols.extend([f"FLOW{day} REAL", f"FLOW_SYMBOL{day} TEXT"])
        db.execute("CREATE TABLE DLY_FLOWS ("+",".join(cols)+")")
        months = {}
        for row in fixture["daily_values"]:
            when = date.fromisoformat(row["date"])
            monthly = months.setdefault((when.year, when.month), ["TEST001", when.year, when.month]+[None]*62)
            monthly[3+(when.day-1)*2:5+(when.day-1)*2] = [row["flow"], row["symbol"]]
        for row in months.values():
            db.execute("INSERT INTO DLY_FLOWS VALUES ("+",".join(["?"]*65)+")", row)
        db.execute("CREATE TABLE DATA_SYMBOLS (SYMBOL_ID TEXT, SYMBOL_EN TEXT, SYMBOL_FR TEXT)")
        db.execute("INSERT INTO DATA_SYMBOLS VALUES (?,?,?)", tuple(fixture["quality_symbols"][0].values()))
        db.execute("CREATE TABLE VERSION (Version TEXT, Date TEXT)")
        db.execute("INSERT INTO VERSION VALUES ('synthetic-1','2020-01-01')")
    return path


def extract(database, tmp_path, **kwargs):
    return reader.extract(database, kwargs.get("station", "TEST001"), kwargs.get("start", "2020-02-28"),
                          kwargs.get("end", "2020-03-02"), tmp_path/"result")


def test_leap_day_native_null_flags_and_real_hashes(database, tmp_path):
    before = reader.digest(database)
    report = extract(database, tmp_path)
    rows = list(csv.DictReader((tmp_path/"result/observations.csv").open(encoding="utf-8")))
    assert [r["date"] for r in rows] == ["2020-02-28", "2020-02-29", "2020-03-01", "2020-03-02"]
    assert rows[0]["discharge_native"] == "1.25" and rows[0]["quality_symbol_raw"] == "B"
    assert rows[1]["value_status"] == "missing" and rows[1]["discharge_native"] == ""
    assert rows[1]["quality_symbol_is_null"] == "True"
    assert report["days_without_finite_value"] == 1 and report["missing_calendar_dates_count"] == 0
    assert report["without_finite_value_ranges"] == [{"start": "2020-02-29", "end": "2020-02-29", "days": 1}]
    assert report["source"]["sha256"] == before == reader.digest(database)
    assert report["output"]["sha256"] == reader.digest(tmp_path/"result/observations.csv")
    assert report["time"]["timezone"] is None and report["model_executed"] is False
    assert report["quality_symbol_definitions"][0]["SYMBOL_EN"] == "Ice Conditions"


def test_missing_month_report_has_real_gaps_without_fake_rows(database, tmp_path):
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM DLY_FLOWS WHERE MONTH=3")
        db.execute("UPDATE DLY_FLOWS SET FLOW31=999")
    report = extract(database, tmp_path)
    assert report["rows"] == 2  # February padding is not a calendar observation.
    assert report["missing_calendar_ranges"] == [{"start": "2020-03-01", "end": "2020-03-02", "days": 2}]


def test_duplicates_invalid_values_and_negatives_are_visible(database, tmp_path):
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO DLY_FLOWS SELECT * FROM DLY_FLOWS WHERE MONTH=2")
        db.execute("UPDATE DLY_FLOWS SET FLOW1='broken', FLOW2=-1 WHERE MONTH=3")
    report = extract(database, tmp_path)
    assert report["status"] == "review_required"
    assert report["value_status_counts"]["not_numeric"] == 1 and report["negative_values"] == 1
    assert [x["date"] for x in report["duplicate_calendar_dates"]] == ["2020-02-28", "2020-02-29"]


@pytest.mark.parametrize("station", ["missing", "TEST001' OR 1=1 --"])
def test_unknown_station_and_sql_text_are_not_interpolated(database, tmp_path, station):
    with pytest.raises(ValueError, match="station record"):
        extract(database, tmp_path, station=station)
    assert not (tmp_path/"result").exists()


def test_missing_schema_and_existing_output_fail(database, tmp_path):
    with sqlite3.connect(database) as db:
        db.execute("DROP TABLE DATA_SYMBOLS")
    with pytest.raises(ValueError, match="schema"):
        extract(database, tmp_path)
    (tmp_path/"result").mkdir()
    with pytest.raises(ValueError, match="must be new"):
        extract(database, tmp_path)


def test_sqlite_connection_is_explicitly_read_only(database, tmp_path, monkeypatch):
    original = reader.sqlite3.connect
    seen = []
    def connect(database_uri, **kwargs):
        seen.append((database_uri, kwargs))
        db = original(database_uri, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            db.execute("CREATE TABLE must_not_write(x)")
        return db
    monkeypatch.setattr(reader.sqlite3, "connect", connect)
    extract(database, tmp_path)
    assert seen[0][0].endswith("?mode=ro") and seen[0][1]["uri"] is True
