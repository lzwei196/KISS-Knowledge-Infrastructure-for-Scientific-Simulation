"""
test_units.py — Unit tests for the most critical conversions in ki_tools_common.

Run with:  pytest auto_dissect/ki_tools_common/tests/test_units.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ki_tools_common.units import (
    celsius_to_kelvin,
    kelvin_to_celsius,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    kelvin_to_fahrenheit,
    fahrenheit_to_kelvin,
    kgm2s_to_mmday,
    mmday_to_kgm2s,
    kgm2s_to_mmhr,
    mmday_to_cmday,
    mmday_to_inchesday,
    mmday_to_mday,
    mmday_to_mm_timestep,
    m_accumulated_to_mmday,
    pa_to_hpa,
    hpa_to_pa,
    pa_to_kpa,
    pa_to_atm,
    atm_to_pa,
    wm2_to_mjm2day,
    mjm2day_to_wm2,
    ms_to_kmh,
    kmh_to_ms,
    ms_to_knots,
    fraction_to_percent,
    percent_to_fraction,
    gcm2_to_kgcm2,
    gcm2_to_tcha,
    umolm2s_to_gcm2day,
    m_to_cm,
    m_to_mm,
    m_to_feet,
    convert,
    CMFD_PRECIP_KGM2S_TO_MMDAY,
)
from ki_tools_common.humidity import (
    saturation_vapor_pressure,
    specific_humidity_to_rh,
    rh_to_specific_humidity,
    vpd_from_temp_rh,
    dewpoint_from_rh,
)
from ki_tools_common.metrics import nse, kge, pbias, rmse, pearson_r, all_metrics


# ======================================================================
# Temperature conversions
# ======================================================================

class TestTemperature:
    def test_celsius_to_kelvin_zero(self):
        assert celsius_to_kelvin(0.0) == pytest.approx(273.15)

    def test_kelvin_to_celsius_roundtrip(self):
        assert kelvin_to_celsius(celsius_to_kelvin(25.0)) == pytest.approx(25.0)

    def test_celsius_to_fahrenheit_boiling(self):
        assert celsius_to_fahrenheit(100.0) == pytest.approx(212.0)

    def test_fahrenheit_to_celsius_freezing(self):
        assert fahrenheit_to_celsius(32.0) == pytest.approx(0.0)

    def test_kelvin_to_fahrenheit(self):
        assert kelvin_to_fahrenheit(373.15) == pytest.approx(212.0)

    def test_fahrenheit_to_kelvin(self):
        assert fahrenheit_to_kelvin(32.0) == pytest.approx(273.15)

    def test_temperature_numpy_array(self):
        arr = np.array([0.0, 25.0, 100.0])
        result = celsius_to_kelvin(arr)
        expected = np.array([273.15, 298.15, 373.15])
        np.testing.assert_allclose(result, expected)


# ======================================================================
# Precipitation conversions
# ======================================================================

class TestPrecipitation:
    def test_kgm2s_to_mmday(self):
        """1 kg/m2/s = 86400 mm/day."""
        assert kgm2s_to_mmday(1.0) == pytest.approx(86400.0)

    def test_mmday_to_kgm2s_roundtrip(self):
        assert mmday_to_kgm2s(kgm2s_to_mmday(1e-5)) == pytest.approx(1e-5, rel=1e-10)

    def test_kgm2s_to_mmhr(self):
        assert kgm2s_to_mmhr(1.0) == pytest.approx(3600.0)

    def test_mmday_to_cmday(self):
        assert mmday_to_cmday(10.0) == pytest.approx(1.0)

    def test_mmday_to_inchesday(self):
        assert mmday_to_inchesday(25.4) == pytest.approx(1.0)

    def test_mmday_to_mday(self):
        assert mmday_to_mday(1000.0) == pytest.approx(1.0)

    def test_mmday_to_mm_timestep_1hr(self):
        assert mmday_to_mm_timestep(24.0, 1.0) == pytest.approx(1.0)

    def test_mmday_to_mm_timestep_3hr(self):
        assert mmday_to_mm_timestep(24.0, 3.0) == pytest.approx(3.0)

    def test_m_accumulated_to_mmday(self):
        assert m_accumulated_to_mmday(0.005) == pytest.approx(5.0)


# ======================================================================
# Pressure conversions
# ======================================================================

class TestPressure:
    def test_pa_to_hpa(self):
        assert pa_to_hpa(101325.0) == pytest.approx(1013.25)

    def test_hpa_to_pa(self):
        assert hpa_to_pa(1013.25) == pytest.approx(101325.0)

    def test_pa_to_kpa(self):
        assert pa_to_kpa(101325.0) == pytest.approx(101.325)

    def test_pa_to_atm_standard(self):
        assert pa_to_atm(101325.0) == pytest.approx(1.0)

    def test_atm_to_pa_roundtrip(self):
        assert atm_to_pa(pa_to_atm(50000.0)) == pytest.approx(50000.0, rel=1e-10)


# ======================================================================
# Radiation conversions
# ======================================================================

class TestRadiation:
    def test_wm2_to_mjm2day(self):
        assert wm2_to_mjm2day(250.0) == pytest.approx(21.6)

    def test_mjm2day_to_wm2_roundtrip(self):
        val = 300.0
        assert mjm2day_to_wm2(wm2_to_mjm2day(val)) == pytest.approx(val, rel=1e-10)


# ======================================================================
# Wind conversions
# ======================================================================

class TestWind:
    def test_ms_to_kmh(self):
        assert ms_to_kmh(10.0) == pytest.approx(36.0)

    def test_kmh_to_ms_roundtrip(self):
        assert kmh_to_ms(ms_to_kmh(5.0)) == pytest.approx(5.0, rel=1e-10)

    def test_ms_to_knots(self):
        assert ms_to_knots(10.0) == pytest.approx(19.4384, rel=1e-4)


# ======================================================================
# Soil conversions
# ======================================================================

class TestSoil:
    def test_fraction_to_percent(self):
        assert fraction_to_percent(0.35) == pytest.approx(35.0)

    def test_percent_to_fraction(self):
        assert percent_to_fraction(35.0) == pytest.approx(0.35)


# ======================================================================
# Carbon conversions
# ======================================================================

class TestCarbon:
    def test_gcm2_to_kgcm2(self):
        assert gcm2_to_kgcm2(1000.0) == pytest.approx(1.0)

    def test_gcm2_to_tcha(self):
        assert gcm2_to_tcha(100.0) == pytest.approx(1.0)

    def test_umolm2s_to_gcm2day(self):
        # 1 umol/m2/s ≈ 1.038 gC/m2/day
        assert umolm2s_to_gcm2day(1.0) == pytest.approx(1.0378, rel=1e-3)


# ======================================================================
# Length conversions
# ======================================================================

class TestLength:
    def test_m_to_cm(self):
        assert m_to_cm(1.5) == pytest.approx(150.0)

    def test_m_to_mm(self):
        assert m_to_mm(0.5) == pytest.approx(500.0)

    def test_m_to_feet(self):
        assert m_to_feet(1.0) == pytest.approx(3.28084, rel=1e-4)


# ======================================================================
# Universal convert() dispatcher
# ======================================================================

class TestConvert:
    def test_convert_temperature(self):
        assert convert(25.0, "C", "K", "temperature") == pytest.approx(298.15)

    def test_convert_precipitation(self):
        assert convert(1.0, "kg/m2/s", "mm/day", "precipitation") == pytest.approx(86400.0)

    def test_convert_pressure(self):
        assert convert(101325.0, "Pa", "atm", "pressure") == pytest.approx(1.0)

    def test_convert_case_insensitive(self):
        assert convert(10.0, "M/S", "KM/H", "Wind") == pytest.approx(36.0)

    def test_convert_unknown_raises(self):
        with pytest.raises(KeyError):
            convert(1.0, "bananas", "apples", "fruit")

    def test_convert_numpy_array(self):
        arr = np.array([0.0, 100.0])
        result = convert(arr, "C", "K", "temperature")
        np.testing.assert_allclose(result, [273.15, 373.15])


# ======================================================================
# Humidity
# ======================================================================

class TestHumidity:
    def test_svp_at_zero(self):
        assert saturation_vapor_pressure(0.0) == pytest.approx(6.1078, rel=1e-4)

    def test_svp_at_20(self):
        assert saturation_vapor_pressure(20.0) == pytest.approx(23.39, rel=1e-2)

    def test_rh_roundtrip(self):
        """Convert RH -> q -> RH and check consistency."""
        rh_in = 65.0
        temp_k = 293.15
        pres_pa = 101325.0
        q = rh_to_specific_humidity(rh_in, temp_k, pres_pa)
        rh_out = specific_humidity_to_rh(q, temp_k, pres_pa)
        assert rh_out == pytest.approx(rh_in, abs=0.5)

    def test_vpd_at_100_rh(self):
        assert vpd_from_temp_rh(25.0, 100.0) == pytest.approx(0.0, abs=1e-10)

    def test_dewpoint_at_100_rh(self):
        assert dewpoint_from_rh(20.0, 100.0) == pytest.approx(20.0, abs=0.1)


# ======================================================================
# Metrics — NaN handling
# ======================================================================

class TestMetrics:
    def test_nse_perfect(self):
        obs = np.array([1.0, 2.0, 3.0])
        assert nse(obs, obs) == pytest.approx(1.0)

    def test_nse_with_nan(self):
        obs = np.array([1.0, np.nan, 3.0])
        sim = np.array([1.0, 2.0, 3.0])
        result = nse(obs, sim)
        assert not math.isnan(result)

    def test_kge_perfect(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        assert kge(obs, obs) == pytest.approx(1.0)

    def test_rmse_zero(self):
        obs = np.array([5.0, 10.0, 15.0])
        assert rmse(obs, obs) == pytest.approx(0.0)

    def test_pbias_overestimate(self):
        obs = np.array([100.0, 200.0, 300.0])
        sim = np.array([110.0, 210.0, 310.0])
        assert pbias(obs, sim) > 0

    def test_pearson_perfect_positive(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        sim = np.array([2.0, 4.0, 6.0, 8.0])
        assert pearson_r(obs, sim) == pytest.approx(1.0)

    def test_all_metrics_keys(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        sim = np.array([1.1, 2.0, 3.1, 3.9, 5.2])
        m = all_metrics(obs, sim)
        assert set(m.keys()) == {"NSE", "KGE", "PBIAS", "RMSE", "r"}

    def test_metrics_all_nan_returns_nan(self):
        obs = np.array([np.nan, np.nan])
        sim = np.array([np.nan, np.nan])
        assert math.isnan(nse(obs, sim))
        assert math.isnan(kge(obs, sim))
        assert math.isnan(rmse(obs, sim))

    def test_metrics_empty_returns_nan(self):
        assert math.isnan(nse([], []))
        assert math.isnan(kge([], []))
