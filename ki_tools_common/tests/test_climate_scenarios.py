"""
test_climate_scenarios.py -- unit tests for ki_tools_common.climate_scenarios
(pure array/math layer for the Climate-Change Scenarios Framework KI).

These tests use only synthetic in-memory arrays -- no dependency on the
real ISIMIP3b/HiCPC files on disk (those are exercised separately by
climate_scenarios/knowledge_infrastructure/tools/*.py against real data).

Run with:  pytest models/ki_tools_common/tests/test_climate_scenarios.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from ki_tools_common.climate_scenarios import (
    delta_perturbation,
    direct_transient,
    harmonize,
    provenance,
    qc,
    uncertainty,
    warming_levels,
)


# ---------------------------------------------------------------------------
# harmonize.py
# ---------------------------------------------------------------------------

def test_to_canonical_precip_mmday_to_kgm2s():
    da = xr.DataArray([86.4, 0.0, 43.2], dims="time")
    out = harmonize.to_canonical(da, "pr", "mm/day")
    np.testing.assert_allclose(out.values, [0.001, 0.0, 0.0005])
    assert out.attrs["canonical_units"] == "kg m-2 s-1"


def test_to_canonical_temperature_celsius_to_kelvin():
    da = xr.DataArray([0.0, 25.0], dims="time")
    out = harmonize.to_canonical(da, "tas", "degC")
    np.testing.assert_allclose(out.values, [273.15, 298.15])


def test_to_canonical_rejects_unverified_unit():
    da = xr.DataArray([1.0], dims="time")
    with pytest.raises(harmonize.UnverifiedUnitError):
        harmonize.to_canonical(da, "tas", "UNVERIFIED")


def test_to_canonical_unknown_variable_raises():
    da = xr.DataArray([1.0], dims="time")
    with pytest.raises(KeyError):
        harmonize.to_canonical(da, "not_a_variable", "K")


def test_enforce_temperature_consistency_fixes_violations():
    tas = xr.DataArray([10.0, 20.0, 5.0], dims="time")
    tasmin = xr.DataArray([12.0, 15.0, 6.0], dims="time")   # tasmin > tas at idx 0
    tasmax = xr.DataArray([15.0, 18.0, 4.0], dims="time")   # tas > tasmax at idx 1,2
    out_tas, out_tasmin, out_tasmax = harmonize.enforce_temperature_consistency(tas, tasmin, tasmax)
    assert bool((out_tasmin <= out_tas).all())
    assert bool((out_tas <= out_tasmax).all())


def test_validate_ranges_flags_out_of_bounds():
    da = xr.DataArray([50.0, -5.0, 120.0], dims="time")  # hurs must be 0-100
    problems = harmonize.validate_ranges(da, "hurs")
    assert len(problems) == 2  # both the low and high violation are reported
    assert all("hurs" in p for p in problems)


def test_huss_hurs_roundtrip_reasonable():
    tas_k = xr.DataArray([293.15], dims="time")   # 20 degC
    ps_pa = xr.DataArray([101325.0], dims="time")
    hurs_in = xr.DataArray([60.0], dims="time")
    huss = harmonize.hurs_to_huss(hurs_in, tas_k, ps_pa)
    hurs_out = harmonize.huss_to_hurs(huss, tas_k, ps_pa)
    np.testing.assert_allclose(hurs_out.values, hurs_in.values, atol=1.0)


# ---------------------------------------------------------------------------
# delta_perturbation.py (Mode B)
# ---------------------------------------------------------------------------

def test_additive_delta():
    x_ref = xr.DataArray([10.0, 12.0], dims="time")
    x_fut = xr.DataArray([15.0, 15.0], dims="time")
    x_hist = xr.DataArray([12.0, 12.0], dims="time")
    out = delta_perturbation.additive_delta(x_ref, x_fut, x_hist)
    np.testing.assert_allclose(out.values, [13.0, 15.0])


def test_multiplicative_delta_with_lower_bound():
    x_ref = xr.DataArray([5.0, 0.0], dims="time")
    x_fut = xr.DataArray([10.0, 10.0], dims="time")
    x_hist = xr.DataArray([5.0, 5.0], dims="time")
    out = delta_perturbation.multiplicative_delta(x_ref, x_fut, x_hist, lower_bound=0.0)
    np.testing.assert_allclose(out.values, [10.0, 0.0])
    assert float(out.min()) >= 0.0


def test_quantile_delta_mapping_additive_shift():
    rng = np.random.default_rng(0)
    x_ref = rng.normal(10, 2, 2000)
    x_hist = rng.normal(10, 2, 2000)
    x_fut = rng.normal(13, 2, 2000)
    out = delta_perturbation.quantile_delta_mapping(x_ref, x_hist, x_fut, kind="additive")
    assert out.shape == x_ref.shape
    assert abs((out.mean() - x_ref.mean()) - 3.0) < 0.5


def test_quantile_delta_mapping_multiplicative_lower_bound():
    rng = np.random.default_rng(1)
    x_ref = np.abs(rng.normal(5, 2, 2000))
    x_hist = np.abs(rng.normal(5, 2, 2000))
    x_fut = np.abs(rng.normal(7, 2, 2000))
    out = delta_perturbation.quantile_delta_mapping(x_ref, x_hist, x_fut, kind="multiplicative", lower_bound=0.0)
    assert out.min() >= 0.0


def test_derive_snowfall_from_fraction_conserves_total():
    pr_hicpc = xr.DataArray([10.0, 5.0, 0.0], dims="time")
    pr_isimip = xr.DataArray([10.0, 5.0, 0.0], dims="time")
    prsn_isimip = xr.DataArray([3.0, 5.0, 0.0], dims="time")  # 100% snow at idx1
    prsn_hybrid, pr_rain = delta_perturbation.derive_snowfall_from_fraction(pr_hicpc, pr_isimip, prsn_isimip)
    np.testing.assert_allclose((prsn_hybrid + pr_rain).values, pr_hicpc.values)
    assert float(prsn_hybrid[1]) == pytest.approx(5.0)  # all-snow day transfers fully


# ---------------------------------------------------------------------------
# direct_transient.py (Mode A)
# ---------------------------------------------------------------------------

def _daily_series(start, end, gcm="GCM-A", member="r1i1p1f1"):
    times = pd.date_range(start, end, freq="D")
    da = xr.DataArray(np.arange(len(times), dtype=float), dims="time", coords={"time": times})
    da.attrs["gcm"] = gcm
    da.attrs["member"] = member
    return da


def test_concatenate_historical_and_ssp_ok():
    hist = _daily_series("2010-01-01", "2014-12-31")
    fut = _daily_series("2015-01-01", "2020-12-31")
    out = direct_transient.concatenate_historical_and_ssp(hist, fut)
    assert out.sizes["time"] == hist.sizes["time"] + fut.sizes["time"]
    assert out.attrs["forcing_mode"] == "direct_transient"


def test_concatenate_rejects_mismatched_gcm():
    hist = _daily_series("2010-01-01", "2014-12-31", gcm="GCM-A")
    fut = _daily_series("2015-01-01", "2020-12-31", gcm="GCM-B")
    with pytest.raises(direct_transient.InconsistentTrajectoryError):
        direct_transient.concatenate_historical_and_ssp(hist, fut)


def test_concatenate_rejects_time_gap():
    hist = _daily_series("2010-01-01", "2014-12-31")
    fut = _daily_series("2015-06-01", "2020-12-31")   # gap
    with pytest.raises(direct_transient.InconsistentTrajectoryError):
        direct_transient.concatenate_historical_and_ssp(hist, fut)


def test_future_change_computes_delta():
    da = _daily_series("2000-01-01", "2020-12-31")
    delta = direct_transient.future_change(da, "2000-01-01", "2004-12-31", "2016-01-01", "2020-12-31")
    assert float(delta) > 0   # later values are larger by construction (arange)


# ---------------------------------------------------------------------------
# warming_levels.py (Mode C)
# ---------------------------------------------------------------------------

def test_find_warming_level_windows_linear_warming():
    years = np.arange(1850, 2101)
    tas = pd.Series(14.0 + 3.0 * (years - 1850) / (2100 - 1850), index=years)
    windows = warming_levels.find_warming_level_windows(tas, levels=[1.5, 2.0, 4.0])
    w15, w20, w40 = windows
    assert w15.reached and w20.reached
    assert w15.crossing_year < w20.crossing_year
    assert w40.reached is False   # only +3C achieved by 2100 in this toy series


def test_global_annual_mean_anomaly_requires_baseline_coverage():
    tas = pd.Series([10.0, 11.0], index=[2015, 2016])
    with pytest.raises(ValueError):
        warming_levels.global_annual_mean_anomaly(tas, baseline_years=(1850, 1900))


# ---------------------------------------------------------------------------
# qc.py
# ---------------------------------------------------------------------------

def test_qc_duplicate_dates_detected():
    times = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-02"])
    da = xr.DataArray([1.0, 2.0, 3.0], dims="time", coords={"time": times})
    report = qc.QCReport()
    qc.check_no_duplicate_dates(da, report)
    assert not report.all_passed


def test_qc_variable_range_pass_and_fail():
    good = xr.DataArray([0.0, 50.0, 100.0], dims="time")
    bad = xr.DataArray([0.0, 150.0], dims="time")
    report = qc.QCReport()
    qc.check_variable_range(good, "hurs", report)
    qc.check_variable_range(bad, "hurs", report)
    assert report.results[0].passed
    assert not report.results[1].passed


def test_qc_coordinate_ordering_handles_scalar_point_coords():
    # A point extraction (single lat/lon value, 0-d coord) must not crash np.diff -- regression
    # for the bug caught by s2_build_canonical_cube.py against a real ISIMIP3b point extraction.
    times = pd.date_range("2020-01-01", periods=5, freq="D")
    da = xr.DataArray(
        np.arange(5, dtype=float), dims="time",
        coords={"time": times, "lat": 33.0, "lon": 117.0},
    )
    report = qc.QCReport()
    qc.check_valid_coordinate_ordering(da, report)
    assert report.all_passed


def test_qc_temperature_consistency_gate():
    tas = xr.DataArray([10.0], dims="time")
    tasmin = xr.DataArray([15.0], dims="time")  # violates tasmin<=tas
    tasmax = xr.DataArray([20.0], dims="time")
    report = qc.QCReport()
    qc.check_temperature_consistency(tas, tasmin, tasmax, report)
    assert not report.all_passed


def test_climate_signal_epsilon_pass_and_fail():
    ok = qc.climate_signal_epsilon(delta_processed=3.05, delta_source=3.0, tolerance=0.5)
    fail = qc.climate_signal_epsilon(delta_processed=5.0, delta_source=3.0, tolerance=0.5)
    assert ok.passed
    assert not fail.passed


# ---------------------------------------------------------------------------
# uncertainty.py
# ---------------------------------------------------------------------------

def test_ensemble_stats_and_robust_change():
    deltas = np.array([1.0, 1.5, 0.8, -0.2, 2.0])
    stats = uncertainty.ensemble_stats(deltas, historical_variability=0.5)
    assert stats.n_members == 5
    assert 0.0 <= stats.frac_positive <= 1.0
    # majority positive (4/5=0.8) and snr = median/hv = 1.0/0.5 = 2.0 >= 1.0 -> robust
    assert stats.robust_change(majority_threshold=0.66, snr_threshold=1.0)


def test_ensemble_stats_rejects_zero_variability():
    with pytest.raises(ValueError):
        uncertainty.ensemble_stats(np.array([1.0, 2.0]), historical_variability=0.0)


def test_two_way_variance_decomposition_balanced():
    d = {("A", "ssp126"): 1.0, ("A", "ssp585"): 3.0, ("B", "ssp126"): 1.2, ("B", "ssp585"): 3.4}
    vd = uncertainty.two_way_variance_decomposition(d)
    assert vd.ssp_fraction > vd.gcm_fraction   # SSP drives most of the spread in this toy example
    assert vd.gcm_fraction + vd.ssp_fraction + vd.interaction_fraction == pytest.approx(1.0, abs=1e-6)


def test_two_way_variance_decomposition_rejects_unbalanced():
    d = {("A", "ssp126"): 1.0, ("B", "ssp585"): 3.4}  # missing (A,ssp585) and (B,ssp126)
    with pytest.raises(ValueError):
        uncertainty.two_way_variance_decomposition(d)


# ---------------------------------------------------------------------------
# provenance.py
# ---------------------------------------------------------------------------

def test_run_id_matches_framework_example_shape():
    p = provenance.ClimateProvenance(
        model_name="SHAW", model_version="git_abc123", parameter_set="paramset03",
        primary_source="HiCPC", auxiliary_source="ISIMIP3b",
        hicpc_dataset_version="v1.0", isimip_dataset_version="ISIMIP3b_w5e5",
        gcm="ACCESS-CM2", member="r1i1p1f1", scenario="ssp585",
        forcing_mode="direct_hybrid", baseline="1995-2014",
        regridding="bilinear", calendar_conversion="none",
        humidity_derivation="none", snowfall_derivation="none",
        temporal_disaggregation="none",
        spinup_method="convergence", initial_state_id="abc123",
        run_start="1979-01-01", run_end="2100-12-31",
    )
    rid = p.run_id()
    assert "SHAW" in rid and "ACCESS-CM2" in rid and "ssp585" in rid and "1979-2100" in rid
    manifest = p.to_manifest()
    assert manifest["climate"]["gcm"] == "ACCESS-CM2"
    assert manifest["model"]["parameter_set"] == "paramset03"


def test_provenance_write_roundtrip(tmp_path):
    p = provenance.ClimateProvenance(
        model_name="VIC", model_version="5.1.0", parameter_set="default",
        primary_source="ISIMIP3b", auxiliary_source=None,
        hicpc_dataset_version=None, isimip_dataset_version="ISIMIP3b_w5e5",
        gcm="GFDL-ESM4", member="r1i1p1f1", scenario="ssp585",
        forcing_mode="direct_transient", baseline="1995-2014",
        regridding="none", calendar_conversion="none",
        humidity_derivation="none", snowfall_derivation="none",
        temporal_disaggregation="none",
        spinup_method="convergence", initial_state_id="xyz",
        run_start="2015-01-01", run_end="2100-12-31",
    )
    out_path = p.write(tmp_path / "manifest.json")
    assert out_path.exists()
    import json
    loaded = json.loads(out_path.read_text())
    assert loaded["run_id"] == p.run_id()
