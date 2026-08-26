"""Tests for validate_water_balance() — catches unit errors via water balance closure."""
import numpy as np
import pytest
from ki_tools_common.validation import validate_water_balance


def test_good_balance():
    r = validate_water_balance(1000, 600, 350, 20)
    assert r["status"] == "PASS"
    assert abs(r["residual_mm"] - 30.0) < 0.1


def test_extreme_precip_detected():
    """P=800,000 mm/yr should be caught as a unit error."""
    r = validate_water_balance(800000, 400000, 350000, period_days=365)
    assert r["status"] == "FAIL"
    assert any("exceeds physical maximum" in d for d in r["diagnostics"])


def test_zero_q_with_normal_p():
    """SUMMA dt_025 pattern: P=800 mm/yr but Q=0.1 mm/yr."""
    r = validate_water_balance(800, 300, 0.1, period_days=365)
    assert any("near zero" in d for d in r["diagnostics"])


def test_q_exceeds_p():
    """Q > 10x P indicates a unit error."""
    r = validate_water_balance(1000, 600, 500000)
    assert r["status"] == "FAIL"
    assert any("10x Precipitation" in d for d in r["diagnostics"])


def test_severe_residual():
    """Residual > P indicates fundamental error."""
    r = validate_water_balance(1000, 0, 3000)
    assert any("exceeds total precipitation" in d for d in r["diagnostics"])


def test_daily_rates():
    r = validate_water_balance(1000, 600, 350, period_days=365)
    assert "daily_rates" in r
    assert abs(r["daily_rates"]["P_mm_day"] - 1000 / 365) < 0.01
