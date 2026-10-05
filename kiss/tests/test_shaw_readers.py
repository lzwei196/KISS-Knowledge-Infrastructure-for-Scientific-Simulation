"""SHAW output readers anchored in the official 3.03 Trial outputs (all platforms)."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "models" / "SHAW" / "s6_execution" / "tools"
FIXTURES = Path(__file__).parent / "fixtures" / "shaw_trial"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    parser = load("parse_shaw_output", TOOLS / "parse_shaw_output.py")
    monkeypatch.setitem(sys.modules, "parse_shaw_output", parser)
    return SimpleNamespace(parser=parser, frost=load("shaw_frost_test", TOOLS / "shaw_frost_analysis.py"))


def test_official_water_columns_and_hour24(modules):
    rows = modules.parser.parse_water_file(FIXTURES / "water.txt")
    assert rows[0]["datetime"] == "1986-12-05T00:00:00"
    assert rows[-1]["datetime"] == "1986-12-17T00:00:00"
    assert rows[0]["precip_mm"] == 0
    assert rows[0]["et_mm"] == .02
    assert rows[0]["drainage_mm"] == -2.69
    assert rows[0]["storage_change_mm"] == 2.67
    # DAY HR YR = 339 24 86: HR is not the year, so the values keep their own columns.
    assert (rows[1]["jday"], rows[1]["hour"], rows[1]["year"]) == (339, 24, 1986)
    assert rows[1]["precip_mm"] == 9.1
    assert rows[1]["snowmelt_mm"] == 1.17
    assert rows[1]["intercepted_precip_mm"] == 2.42
    assert rows[1]["et_mm"] == .06
    assert rows[1]["storage_change_mm"] == pytest.approx(15.69)
    assert "rain_mm" not in rows[1] and "snow_mm" not in rows[1]


def test_official_energy_and_frost_units(modules):
    first = modules.parser.parse_energy_file(FIXTURES / "energy.txt")[0]
    assert first["rnet_wm2"] == pytest.approx(92.7)
    assert (first["sensible_wm2"], first["latent_wm2"], first["ground_wm2"]) == (-71.5, -1.4, 11.5)
    last = modules.parser.parse_frost_file(FIXTURES / "frost.txt")[-1]
    assert (last["thaw_depth_cm"], last["frost_depth_cm"], last["snow_depth_cm"]) == (0, .1, 4.5)
    assert last["swe_mm"] == 9.2
    assert last["swe_cm"] == pytest.approx(.92)


def test_official_profiles_keep_all_nodes_and_normalize_end(modules):
    rows = modules.parser.parse_profile_file(FIXTURES / "temp.txt", "temp_C")
    assert rows[0]["datetime"] == "1986-12-04T12:00:00"
    assert rows[-1]["datetime"] == "1986-12-17T00:00:00"
    assert len([key for key in rows[-1] if key.startswith("temp_C_node")]) == 11
    assert rows[-1]["temp_C_node1"] == -.1
    assert rows[-1]["temp_C_node11"] == 8.4
    assert len(modules.parser.parse_profile_file(FIXTURES / "moist.txt")) == 3


def test_four_digit_year_and_leap_boundary(modules, tmp_path):
    source = tmp_path / "temp.out"
    source.write_text("366 24 2024 1.2D+00\n", encoding="utf-8")
    row = modules.parser.parse_profile_file(source)[0]
    assert row["year"] == 2024
    assert row["datetime"] == "2025-01-01T00:00:00"
    assert row["value_node1"] == 1.2


@pytest.mark.parametrize("line", ["338 24 86 1 2", "338 24 86 nan 0 0 0", "366 24 2023 0 0 0 0", "350 24"])
def test_invalid_scientific_rows_are_not_silently_dropped(modules, tmp_path, line):
    source = tmp_path / "frost.out"
    source.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frost.out:1"):
        modules.parser.parse_frost_file(source)


@pytest.mark.parametrize("text", ["338 12 86 1 2 3\n338 13 86 1\n", "DY HR YR 0.0 0.1 0.2\n338 12 86 1\n"])
def test_profile_rejects_missing_nodes(modules, tmp_path, text):
    source = tmp_path / "temp.out"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="nodes; expected 3"):
        modules.parser.parse_profile_file(source)


def test_frost_metrics_count_days_not_six_hour_samples(modules):
    rows = modules.frost.parse_frost_output(FIXTURES / "frost.txt")
    last = rows[-1]
    rows.append({**last, "hour": 18})
    metrics = modules.frost.compute_frost_metrics(rows)[0]
    assert metrics["frozen_days"] == 1
    assert metrics["snow_cover_days"] == 2
    assert metrics["max_swe_cm"] == .9


def test_plot_readers_share_correct_scientific_columns(modules):
    pytest.importorskip("matplotlib")
    plot = load("shaw_plot_test", TOOLS / "plot_shaw_profiles.py")
    times, water = plot.read_water_data(FIXTURES / "water.txt")
    assert times[-1].isoformat() == "1986-12-17T00:00:00"
    assert water["precip"][1] == 9.1 and water["snowmelt"][1] == 1.17
    assert plot.read_energy_data(FIXTURES / "energy.txt")[1]["rnet"][0] == pytest.approx(92.7)
    assert plot.read_frost_data(FIXTURES / "frost.txt")[1][-1] == .1
