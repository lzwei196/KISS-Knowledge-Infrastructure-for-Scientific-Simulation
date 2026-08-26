"""
qc.py -- QC gates for the climate scenarios cube (Framework §11). Operates
on already-loaded xarray objects only (see the climate_scenarios package
docstring for the netCDF4/h5netcdf import-order constraint).

Framework §11 lists six gate categories: file-level, variable-level,
temporal, spatial, climate-signal, and process-model checks. Only the
checks that are generically computable from an in-memory array/time index
are implemented here (file-level, variable-level, the computable subset of
temporal, and the climate-signal check). Spatial checks that need a domain
mask / DEM (coast-to-land contamination, elevation corrections) and
process-model checks (water/energy balance closure) are inherently
model- or dataset-specific and belong in the consuming model KI's own
validation, not duplicated here -- see docstrings below for what is
deliberately out of scope.

Every check returns a QCResult so callers can accumulate a report rather
than fail on the first problem (Framework §11: "No model run should begin
until the forcing passes ALL required gates" -- callers should collect
every failure before deciding, not abort on the first).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

from ki_tools_common.climate_scenarios.harmonize import VALID_RANGES, validate_ranges


@dataclass
class QCResult:
    gate: str
    passed: bool
    message: str


@dataclass
class QCReport:
    results: list[QCResult] = field(default_factory=list)

    def add(self, gate: str, passed: bool, message: str) -> None:
        self.results.append(QCResult(gate, passed, message))

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[QCResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        n_fail = len(self.failures)
        lines = [f"QC report: {len(self.results) - n_fail}/{len(self.results)} gates passed."]
        for r in self.failures:
            lines.append(f"  FAIL [{r.gate}] {r.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# §11.1 File-level checks
# ---------------------------------------------------------------------------

def check_no_duplicate_dates(da: xr.DataArray, report: QCReport) -> None:
    times = pd.DatetimeIndex(da["time"].values)
    dupes = times[times.duplicated()]
    report.add(
        "file.no_duplicate_dates",
        len(dupes) == 0,
        "OK" if len(dupes) == 0 else f"{len(dupes)} duplicate timestamps, e.g. {list(dupes[:3])}",
    )


def check_expected_days_present(
    da: xr.DataArray, report: QCReport, expected_start: str, expected_end: str, calendar: str = "standard"
) -> None:
    """Framework §11.1 'expected years and days present'. calendar='noleap' skips Feb-29 from the expectation."""
    times = pd.DatetimeIndex(da["time"].values)
    expected = pd.date_range(expected_start, expected_end, freq="D")
    if calendar == "noleap":
        expected = expected[~((expected.month == 2) & (expected.day == 29))]
    missing = expected.difference(times)
    report.add(
        "file.expected_days_present",
        len(missing) == 0,
        "OK" if len(missing) == 0 else f"{len(missing)} expected days missing, e.g. {list(missing[:3])}",
    )


def check_valid_coordinate_ordering(da: xr.DataArray, report: QCReport) -> None:
    """Time must be monotonically increasing; lat/lon must be monotonic (either direction is fine, but not mixed)."""
    times = pd.DatetimeIndex(da["time"].values)
    time_ok = times.is_monotonic_increasing
    problems = [] if time_ok else ["time coordinate is not monotonically increasing"]
    for dim in ("lat", "lon"):
        if dim in da.coords:
            vals = np.atleast_1d(da[dim].values)
            if vals.size > 1 and not (np.all(np.diff(vals) > 0) or np.all(np.diff(vals) < 0)):
                problems.append(f"{dim} coordinate is not monotonic")
    report.add("file.valid_coordinate_ordering", len(problems) == 0, "OK" if not problems else "; ".join(problems))


# ---------------------------------------------------------------------------
# §11.2 Variable-level checks
# ---------------------------------------------------------------------------

def check_variable_range(da: xr.DataArray, variable: str, report: QCReport) -> None:
    problems = validate_ranges(da, variable)
    report.add(f"variable.{variable}_range", len(problems) == 0, "OK" if not problems else "; ".join(problems))


def check_non_negative(da: xr.DataArray, variable: str, report: QCReport) -> None:
    vals = da.values
    finite = vals[np.isfinite(vals)]
    bad = finite.min() < 0 if finite.size else False
    report.add(
        f"variable.{variable}_non_negative",
        not bad,
        "OK" if not bad else f"{variable}: minimum value {finite.min():.4g} is negative",
    )


def check_temperature_consistency(tas: xr.DataArray, tasmin: xr.DataArray, tasmax: xr.DataArray, report: QCReport) -> None:
    """Framework §5.2 / §11.2: tasmin <= tas <= tasmax."""
    violations = int(((tasmin > tas) | (tas > tasmax)).sum())
    total = int(tas.size)
    report.add(
        "variable.temperature_consistency",
        violations == 0,
        "OK" if violations == 0 else f"{violations}/{total} timesteps violate tasmin<=tas<=tasmax",
    )


def check_snowfall_le_precip(prsn: xr.DataArray, pr: xr.DataArray, report: QCReport) -> None:
    """Framework §11.2: 'snowfall no greater than total precipitation'."""
    violations = int((prsn > pr).sum())
    total = int(pr.size)
    report.add(
        "variable.snowfall_le_precip",
        violations == 0,
        "OK" if violations == 0 else f"{violations}/{total} timesteps have prsn > pr",
    )


def check_specific_humidity_below_saturation(huss: xr.DataArray, huss_sat: xr.DataArray, report: QCReport) -> None:
    """Framework §11.2: 'specific humidity below saturation'. huss_sat = saturation specific humidity at (tas, ps)."""
    violations = int((huss > huss_sat).sum())
    total = int(huss.size)
    report.add(
        "variable.specific_humidity_below_saturation",
        violations == 0,
        "OK" if violations == 0 else f"{violations}/{total} timesteps exceed saturation specific humidity",
    )


# ---------------------------------------------------------------------------
# §11.3 Temporal checks (computable subset)
# ---------------------------------------------------------------------------

def check_no_jump_at_transition(
    da: xr.DataArray, transition_date: str, report: QCReport, max_zscore: float = 5.0, window_days: int = 30
) -> None:
    """Framework §11.3: 'no unexplained jump at historical-SSP transition'.

    Compares the mean level in a window just before vs just after
    transition_date against the day-to-day variability elsewhere in the
    series; flags if the jump exceeds max_zscore standard deviations of
    the typical day-to-day change.
    """
    times = pd.DatetimeIndex(da["time"].values)
    t0 = pd.Timestamp(transition_date)
    before = da.sel(time=slice(t0 - pd.Timedelta(days=window_days), t0 - pd.Timedelta(days=1)))
    after = da.sel(time=slice(t0, t0 + pd.Timedelta(days=window_days - 1)))
    if before.sizes.get("time", 0) == 0 or after.sizes.get("time", 0) == 0:
        report.add("temporal.no_jump_at_transition", False, f"insufficient data around {transition_date} to check")
        return
    jump = float(after.mean() - before.mean())
    daily_diffs = np.diff(da.values.reshape(da.sizes["time"], -1), axis=0)
    typical_std = float(np.nanstd(daily_diffs)) or 1e-9
    zscore = abs(jump) / typical_std
    report.add(
        "temporal.no_jump_at_transition",
        zscore <= max_zscore,
        "OK" if zscore <= max_zscore else f"jump of {jump:.4g} at {transition_date} is {zscore:.1f} sigma (threshold {max_zscore})",
    )


def check_daily_totals_conserved(daily_totals: xr.DataArray, subdaily: xr.DataArray, freq_per_day: int, report: QCReport, rtol: float = 1e-3) -> None:
    """Framework §11.3: 'daily totals conserved after temporal disaggregation'."""
    reconstructed = subdaily.values.reshape(-1, freq_per_day).sum(axis=1)
    diff = np.abs(reconstructed - daily_totals.values)
    rel = diff / np.maximum(np.abs(daily_totals.values), 1e-9)
    bad = int((rel > rtol).sum())
    report.add(
        "temporal.daily_totals_conserved",
        bad == 0,
        "OK" if bad == 0 else f"{bad}/{daily_totals.size} days fail conservation within rtol={rtol}",
    )


# ---------------------------------------------------------------------------
# §11.5 Climate-signal check
# ---------------------------------------------------------------------------

def climate_signal_epsilon(delta_processed: float, delta_source: float, tolerance: float) -> QCResult:
    """Framework §11.5: epsilon_delta = deltaX_processed - deltaX_source; fails when |eps| > tolerance.

    delta_* are climate-change signals (e.g. future-mean minus baseline-mean)
    computed the same way before and after some processing step
    (regridding, re-anchoring, bias correction) -- this checks the
    processing did not distort the signal beyond `tolerance`.
    """
    eps = delta_processed - delta_source
    passed = abs(eps) <= tolerance
    return QCResult(
        "climate_signal.epsilon_delta",
        passed,
        "OK" if passed else f"epsilon_delta={eps:.4g} exceeds tolerance={tolerance:.4g} "
        f"(processed={delta_processed:.4g}, source={delta_source:.4g})",
    )


# ---------------------------------------------------------------------------
# Deliberately out of scope -- see module docstring
# ---------------------------------------------------------------------------
# §11.4 spatial checks needing a domain mask / DEM (coast-to-land
#   contamination, elevation corrections, domain mask consistency across
#   variables) and §11.6 process-model checks (water/energy balance
#   closure, soil-water bounds, carbon/nitrogen conservation, runoff-
#   routing mass conservation, restart continuity) require model- or
#   basin-specific context this generic module does not have. Each
#   consuming model KI already has its own validation
#   (ki_tools_common.validation.validate_water_balance etc.) -- call those
#   downstream of this QC pass rather than reimplementing them here.
