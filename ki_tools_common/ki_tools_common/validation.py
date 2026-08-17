"""
validation.py — Physical range validation and sanity checks for forcing and model output.

Consolidates range-checking logic duplicated across 30+ ki/tools/ scripts.

All functions are PURE — they inspect data and return diagnostics, but never
modify the data or produce file I/O.

Examples::

    >>> from ki_tools_common.validation import validate_forcing_ranges
    >>> warnings = validate_forcing_ranges({
    ...     'temperature': np.array([20.0, 25.0]),
    ...     'precipitation': np.array([0.0001, 0.0002]),
    ... })
    >>> for w in warnings:
    ...     print(w)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

Numeric = Union[float, int, np.ndarray]

# ---------------------------------------------------------------------------
# Physical bounds for common forcing variables.
# Each entry: (expected_unit, physical_min, physical_max,
#              unit_trap_condition, unit_trap_hint)
# ---------------------------------------------------------------------------
_FORCING_BOUNDS: Dict[str, dict] = {
    "temperature": {
        "expected_unit": "K",
        "phys_min": 180.0,
        "phys_max": 340.0,
        "traps": [
            {
                "condition": lambda mean: mean < 100.0,
                "hint": "Temperature likely in Celsius, expected Kelvin.",
            },
            {
                "condition": lambda mean: mean > 500.0,
                "hint": "Temperature may be in tenths of degrees or wrong variable.",
            },
        ],
    },
    "precipitation": {
        "expected_unit": "mm/day",
        "phys_min": 0.0,
        "phys_max": 1000.0,
        "traps": [
            {
                "condition": lambda mean: 0.0 < mean < 0.01,
                "hint": "Precipitation likely in kg/m2/s, expected mm/day. "
                "Multiply by 86400.",
            },
            {
                "condition": lambda mean: mean > 2000.0,
                "hint": "Precipitation may be in mm/year or wrong accumulation period.",
            },
        ],
    },
    "pressure": {
        "expected_unit": "Pa",
        "phys_min": 30000.0,
        "phys_max": 110000.0,
        "traps": [
            {
                "condition": lambda mean: 300.0 < mean < 1200.0,
                "hint": "Pressure likely in hPa, expected Pa. Multiply by 100.",
            },
            {
                "condition": lambda mean: 30.0 < mean < 120.0,
                "hint": "Pressure likely in kPa, expected Pa. Multiply by 1000.",
            },
        ],
    },
    "radiation": {
        "expected_unit": "W/m2",
        "phys_min": 0.0,
        "phys_max": 1400.0,
        "traps": [
            {
                "condition": lambda mean: mean > 2000.0,
                "hint": "Radiation may be in J/m2/day or MJ/m2/day, expected W/m2.",
            },
        ],
    },
    "wind": {
        "expected_unit": "m/s",
        "phys_min": 0.0,
        "phys_max": 120.0,
        "traps": [
            {
                "condition": lambda mean: mean > 200.0,
                "hint": "Wind likely in km/h or cm/s, expected m/s.",
            },
        ],
    },
    "humidity": {
        "expected_unit": "kg/kg",
        "phys_min": 0.0,
        "phys_max": 0.06,
        "traps": [
            {
                "condition": lambda mean: mean > 1.0,
                "hint": "Humidity likely in g/kg or percent, expected kg/kg.",
            },
        ],
    },
}


def validate_forcing_ranges(
    data_dict: Dict[str, np.ndarray],
) -> List[str]:
    """Check all forcing variables against physical bounds, with unit-trap hints.

    Args:
        data_dict: Mapping of variable name (e.g. ``'temperature'``,
            ``'precipitation'``) to 1-D or N-D numpy array of values.
            Variable names are matched case-insensitively and with common
            aliases (e.g. ``'temp'`` -> ``'temperature'``).

    Returns:
        List of human-readable warning strings. Empty list means all checks
        passed.

    Example::

        >>> ws = validate_forcing_ranges({'temperature': np.array([25.0, 30.0])})
        >>> any('likely in Celsius' in w for w in ws)
        True
    """
    # Alias mapping
    aliases = {
        "temp": "temperature",
        "tair": "temperature",
        "t2m": "temperature",
        "prec": "precipitation",
        "precip": "precipitation",
        "pre": "precipitation",
        "rainfall": "precipitation",
        "pres": "pressure",
        "press": "pressure",
        "sp": "pressure",
        "ps": "pressure",
        "srad": "radiation",
        "rsds": "radiation",
        "swdown": "radiation",
        "ssrd": "radiation",
        "wind": "wind",
        "u10": "wind",
        "wspd": "wind",
        "shum": "humidity",
        "q": "humidity",
        "huss": "humidity",
    }

    warnings_list: List[str] = []

    for var_name, data in data_dict.items():
        canonical = aliases.get(var_name.lower(), var_name.lower())
        if canonical not in _FORCING_BOUNDS:
            continue

        bounds = _FORCING_BOUNDS[canonical]
        arr = np.asarray(data, dtype=float)
        valid = arr[np.isfinite(arr)]
        if valid.size == 0:
            warnings_list.append(
                f"[{var_name}] All values are NaN or infinite."
            )
            continue

        mean_val = float(np.nanmean(valid))
        min_val = float(np.nanmin(valid))
        max_val = float(np.nanmax(valid))

        # Physical range check
        if min_val < bounds["phys_min"]:
            warnings_list.append(
                f"[{var_name}] Minimum value {min_val:.4g} is below physical "
                f"lower bound {bounds['phys_min']} ({bounds['expected_unit']})."
            )
        if max_val > bounds["phys_max"]:
            warnings_list.append(
                f"[{var_name}] Maximum value {max_val:.4g} exceeds physical "
                f"upper bound {bounds['phys_max']} ({bounds['expected_unit']})."
            )

        # Unit-trap heuristics
        for trap in bounds.get("traps", []):
            try:
                if trap["condition"](mean_val):
                    warnings_list.append(
                        f"[{var_name}] UNIT TRAP: {trap['hint']} "
                        f"(mean={mean_val:.4g})"
                    )
            except Exception:
                pass

    return warnings_list


def validate_discharge(
    sim: np.ndarray,
    obs: np.ndarray,
) -> List[str]:
    """Validate simulated and observed discharge arrays before metric computation.

    Checks for NaN prevalence, negative values, and magnitude ratio.

    Args:
        sim: Simulated discharge array (e.g. m3/s).
        obs: Observed discharge array (e.g. m3/s).

    Returns:
        List of warning strings. Empty if no issues found.

    Example::

        >>> ws = validate_discharge(np.array([100, 200]), np.array([110, -5]))
        >>> any('negative' in w.lower() for w in ws)
        True
    """
    warnings_list: List[str] = []
    sim_arr = np.asarray(sim, dtype=float)
    obs_arr = np.asarray(obs, dtype=float)

    # Length mismatch
    if sim_arr.shape != obs_arr.shape:
        warnings_list.append(
            f"Shape mismatch: sim={sim_arr.shape}, obs={obs_arr.shape}."
        )

    # NaN prevalence
    sim_nan_pct = 100.0 * np.sum(np.isnan(sim_arr)) / max(sim_arr.size, 1)
    obs_nan_pct = 100.0 * np.sum(np.isnan(obs_arr)) / max(obs_arr.size, 1)

    if sim_nan_pct > 10.0:
        warnings_list.append(
            f"Simulated discharge has {sim_nan_pct:.1f}% NaN values."
        )
    if obs_nan_pct > 10.0:
        warnings_list.append(
            f"Observed discharge has {obs_nan_pct:.1f}% NaN values."
        )

    # Negative values
    if np.any(sim_arr[np.isfinite(sim_arr)] < 0):
        warnings_list.append(
            "Simulated discharge contains negative values."
        )
    if np.any(obs_arr[np.isfinite(obs_arr)] < 0):
        warnings_list.append(
            "Observed discharge contains negative values."
        )

    # Magnitude ratio
    sim_valid = sim_arr[np.isfinite(sim_arr)]
    obs_valid = obs_arr[np.isfinite(obs_arr)]

    if sim_valid.size > 0 and obs_valid.size > 0:
        sim_mean = np.mean(np.abs(sim_valid))
        obs_mean = np.mean(np.abs(obs_valid))
        if obs_mean > 0:
            ratio = sim_mean / obs_mean
            if ratio > 10.0 or ratio < 0.1:
                warnings_list.append(
                    f"Magnitude ratio sim/obs = {ratio:.2f}. "
                    f"Possible unit mismatch (sim_mean={sim_mean:.2f}, "
                    f"obs_mean={obs_mean:.2f})."
                )

    return warnings_list


def check_constant_values(
    data: np.ndarray,
    threshold: float = 1e-10,
) -> Dict[str, Any]:
    """Detect constant or fill-value-dominated arrays.

    Args:
        data: N-D numpy array to inspect.
        threshold: Standard deviation below which the data is considered
            constant.

    Returns:
        Dict with keys:
            - ``'is_constant'``: bool
            - ``'std'``: float — standard deviation of finite values
            - ``'fill_value_candidates'``: list of values that appear
              suspiciously often (> 50% of data)
            - ``'finite_fraction'``: float — fraction of finite values

    Example::

        >>> result = check_constant_values(np.array([1e20, 1e20, 1e20, 5.0]))
        >>> result['is_constant']
        False
        >>> len(result['fill_value_candidates']) > 0
        True
    """
    arr = np.asarray(data, dtype=float).ravel()
    finite_mask = np.isfinite(arr)
    finite_vals = arr[finite_mask]
    finite_frac = finite_vals.size / max(arr.size, 1)

    result: Dict[str, Any] = {
        "is_constant": False,
        "std": 0.0,
        "fill_value_candidates": [],
        "finite_fraction": finite_frac,
    }

    if finite_vals.size == 0:
        result["is_constant"] = True
        return result

    std_val = float(np.std(finite_vals))
    result["std"] = std_val
    result["is_constant"] = std_val < threshold

    # Detect fill-value candidates: values that appear in > 50% of the array
    # Common fill values: 1e20, -9999, -999, 9999, -1e20, 0
    common_fills = [1e20, -1e20, 9.96921e36, -9.96921e36, -9999.0, -999.0, 9999.0]
    fill_candidates = []
    for fv in common_fills:
        count = np.sum(np.isclose(arr, fv, rtol=1e-5, atol=0))
        if count > 0.5 * arr.size:
            fill_candidates.append(fv)

    # Also check the mode for non-standard fill values
    if finite_vals.size > 0:
        unique, counts = np.unique(finite_vals, return_counts=True)
        max_count_idx = np.argmax(counts)
        if counts[max_count_idx] > 0.5 * arr.size:
            mode_val = unique[max_count_idx]
            if mode_val not in fill_candidates:
                fill_candidates.append(float(mode_val))

    result["fill_value_candidates"] = fill_candidates
    return result


# ---------------------------------------------------------------------------
# Water balance closure check
# ---------------------------------------------------------------------------

def validate_water_balance(
    precip_mm: Numeric,
    et_mm: Numeric,
    runoff_mm: Numeric,
    delta_storage_mm: Optional[Numeric] = None,
    period_days: Optional[int] = None,
    tolerance_mm: float = 50.0,
    tolerance_pct: float = 10.0,
) -> Dict[str, Any]:
    """Check water balance closure: |P - ET - Q - dS| should be small.

    This catches unit errors immediately. A ×1000 precip error produces a
    residual of thousands of mm. A ×86400 error produces residuals larger
    than annual precipitation.

    Args:
        precip_mm: Total precipitation (mm) over the period
        et_mm: Total evapotranspiration (mm) over the period
        runoff_mm: Total runoff/discharge (mm) over the period
        delta_storage_mm: Change in storage (mm), optional (assumed 0 if None)
        period_days: Number of days (for reporting daily rates)
        tolerance_mm: Absolute closure threshold (mm)
        tolerance_pct: Relative closure threshold (% of precip)

    Returns:
        dict with: residual_mm, residual_pct, status ('PASS'/'WARNING'/'FAIL'),
                   components, diagnostics

    Example::

        >>> result = validate_water_balance(
        ...     precip_mm=1000, et_mm=600, runoff_mm=350, delta_storage_mm=20)
        >>> print(result['status'])  # 'PASS' (residual=30mm, 3%)
    """
    P = float(np.sum(precip_mm))
    ET = float(np.sum(et_mm))
    Q = float(np.sum(runoff_mm))
    dS = float(np.sum(delta_storage_mm)) if delta_storage_mm is not None else 0.0

    residual = P - ET - Q - dS
    residual_pct = abs(residual) / max(P, 1.0) * 100

    diagnostics = []

    # Check if P itself is physically unreasonable (catches 1000x input errors)
    if period_days and P > 0:
        annual_rate = P / period_days * 365
        if annual_rate > 15000:  # Max on Earth ~12,000 mm/yr (Mawsynram, India)
            diagnostics.append(
                f"UNIT ERROR: Annual P = {annual_rate:.0f} mm/yr exceeds physical "
                f"maximum (~12,000 mm/yr). Precipitation likely in wrong units "
                f"(e.g., kg/m²/s read as mm/day → 86400x too high)."
            )

    # Check for near-zero Q with reasonable P (SUMMA dt_025 pattern)
    if period_days and P > 500 and Q > 0:
        annual_q = Q / period_days * 365
        if annual_q < 1.0:
            diagnostics.append(
                f"UNIT ERROR: Annual Q = {annual_q:.2f} mm/yr is near zero despite "
                f"P = {P / period_days * 365:.0f} mm/yr. Output runoff may be in "
                f"m/s instead of kg/m²/s (factor 1000), or the model produced no "
                f"runoff due to a configuration error."
            )

    # Check for obvious unit errors
    if P > 0 and Q > P * 10:
        diagnostics.append(
            f"UNIT ERROR: Runoff ({Q:.0f} mm) > 10x Precipitation ({P:.0f} mm). "
            f"Check runoff units — may be in m/s instead of mm, or per-second instead of per-day."
        )
    if P > 0 and ET > P * 5:
        diagnostics.append(
            f"UNIT ERROR: ET ({ET:.0f} mm) > 5x Precipitation ({P:.0f} mm). "
            f"Check ET units or sign convention (negative ET = evaporation in some models)."
        )
    if P > 0 and Q < P * 0.001 and ET < P * 0.1:
        diagnostics.append(
            f"UNIT ERROR: Both Q ({Q:.1f} mm) and ET ({ET:.1f} mm) are near zero "
            f"relative to P ({P:.0f} mm). Precipitation may be in wrong units (e.g., "
            f"kg/m2/s read as mm/day → 86400x too low)."
        )
    if abs(residual) > P and P > 100:
        diagnostics.append(
            f"SEVERE: Residual ({residual:.0f} mm) exceeds total precipitation ({P:.0f} mm). "
            f"This indicates a fundamental unit or sign error, not just imbalance."
        )

    # Determine status
    if abs(residual) < tolerance_mm and residual_pct < tolerance_pct:
        status = "PASS"
    elif abs(residual) < tolerance_mm * 3 and residual_pct < tolerance_pct * 3:
        status = "WARNING"
    else:
        status = "FAIL"

    result = {
        "residual_mm": round(residual, 1),
        "residual_pct": round(residual_pct, 1),
        "status": status,
        "components": {
            "P_mm": round(P, 1),
            "ET_mm": round(ET, 1),
            "Q_mm": round(Q, 1),
            "dS_mm": round(dS, 1),
        },
        "diagnostics": diagnostics,
    }

    if period_days:
        result["daily_rates"] = {
            "P_mm_day": round(P / period_days, 2),
            "ET_mm_day": round(ET / period_days, 2),
            "Q_mm_day": round(Q / period_days, 2),
        }

    return result
