"""Frozen review evidence describes real NetCDF layouts instead of hiding them."""
from __future__ import annotations

import json

import pytest

from kiss_cli import binary_evidence, ki_investigation

netCDF4 = pytest.importorskip("netCDF4")


def chanobs(path, hour, flows):
    """The real WRF-Hydro v5.2.0 CHANOBS layout: one time step per file."""
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("feature_id", len(flows))
        ds.createDimension("time", 1)
        ds.model_output_valid_time = f"2011-08-26_{hour:02d}:00:00"
        time = ds.createVariable("time", "i4", ("time",))
        time.units = "minutes since 1970-01-01 00:00:00 UTC"
        time[:] = [21905340 + 60 * hour]
        flow = ds.createVariable("streamflow", "f4", ("feature_id",), fill_value=-9999.0)
        flow.units = "m3 s-1"
        flow.missing_value = -9999.0
        flow.valid_range = [0.0, 50000.0]
        flow[:] = flows


def test_summary_shows_attributes_raw_and_masked_values(tmp_path):
    path = tmp_path / "201108260100.CHANOBS_DOMAIN1"
    chanobs(path, 1, [1.5, 60000.0, 2.5])
    assert binary_evidence.is_scientific_binary(path)
    text = binary_evidence.summarize(path, series_size=168, series="#.CHANOBS_DOMAIN#")
    assert "series: 168 files match #.CHANOBS_DOMAIN#" in text
    assert "feature_id = 3" in text and "time = 1" in text
    assert "@valid_range = [0.0, 50000.0]" in text
    assert "@_FillValue = -9999.0" in text
    assert "@units = 'minutes since 1970-01-01 00:00:00 UTC'" in text
    assert "model_output_valid_time = '2011-08-26_01:00:00'" in text
    # The library masks the out-of-range value; the raw sample keeps the stored number.
    assert "sample (library masking/scaling applied): [1.5, None, 2.5]" in text
    assert "sample (raw stored values): [1.5, 60000.0, 2.5]" in text
    assert "masked=1" in text


def test_text_and_non_netcdf_binaries_are_not_summarized(tmp_path):
    (tmp_path / "notes.txt").write_text("plain", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01binary")
    assert not binary_evidence.is_scientific_binary(tmp_path / "notes.txt")
    assert not binary_evidence.is_scientific_binary(tmp_path / "blob.bin")


def test_series_are_sampled_first_and_last_with_outputs_first():
    rows = [(f"outputs/run/2011082601{n:02d}.CHANOBS_DOMAIN1", 100.0) for n in range(10)]
    rows += [("inputs/DOMAIN/geo_em.d01.nc", 200.0), ("inputs/DOMAIN/Fulldom_hires.nc", 200.0)]
    chosen = binary_evidence.select(rows)
    assert chosen[:2] == [("outputs/run/201108260100.CHANOBS_DOMAIN1", 10),
                          ("outputs/run/201108260109.CHANOBS_DOMAIN1", 10)]
    assert {path for path, _ in chosen[2:]} == {"inputs/DOMAIN/geo_em.d01.nc", "inputs/DOMAIN/Fulldom_hires.nc"}


def test_selection_is_capped(monkeypatch):
    monkeypatch.setattr(binary_evidence, "MAX_SUMMARIES", 3)
    rows = [(f"outputs/c{chr(97 + n)}/x.nc", 1.0) for n in range(5)]
    assert len(binary_evidence.select(rows)) == 3


def test_frozen_context_writes_summaries_beside_inventory_rows(tmp_path):
    project = tmp_path / "project"
    run = project / "outputs" / "run"
    run.mkdir(parents=True)
    for hour in range(1, 6):
        chanobs(run / f"20110826{hour:02d}00.CHANOBS_DOMAIN1", hour, [1.0, 2.0, float(hour)])
    (project / "README.md").write_text("case notes", encoding="utf-8")
    sources = {"project": project}
    context = tmp_path / "context"
    result = ki_investigation._context_copy(sources, ki_investigation._source_state(sources), context)
    manifest = json.loads((context / "manifest.json").read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in manifest["files"]}
    first = "project/outputs/run/201108260100.CHANOBS_DOMAIN1"
    last = "project/outputs/run/201108260500.CHANOBS_DOMAIN1"
    middle = "project/outputs/run/201108260300.CHANOBS_DOMAIN1"
    assert result["binary_summary_count"] == 2
    assert rows[first]["omitted"] == "binary_inventory_only"
    assert rows[first]["binary_summary"] == first + binary_evidence.SUFFIX
    assert "binary_summary" in rows[last] and "binary_summary" not in rows[middle]
    summary = (context / (first + binary_evidence.SUFFIX)).read_text(encoding="utf-8")
    assert "series: 5 files" in summary and "@valid_range" in summary
    assert (context / "project" / "README.md").read_text(encoding="utf-8") == "case notes"
    assert any("geoforge-summary" in line for line in manifest["limitations"])


def test_unreadable_netcdf_is_recorded_not_fatal(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "outputs").mkdir(parents=True)
    chanobs(project / "outputs" / "a.nc", 1, [1.0])
    def broken(*_args, **_kwargs):
        raise OSError("cannot decode")
    monkeypatch.setattr(binary_evidence, "summarize", broken)
    sources = {"project": project}
    ki_investigation._context_copy(sources, ki_investigation._source_state(sources), tmp_path / "context")
    manifest = json.loads((tmp_path / "context" / "manifest.json").read_text(encoding="utf-8"))
    row = next(r for r in manifest["files"] if r["path"] == "project/outputs/a.nc")
    assert "cannot decode" in row["binary_summary_error"] and "binary_summary" not in row
