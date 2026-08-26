"""
humidity.py — ONE canonical Tetens implementation for humidity calculations.

Consolidates 17 independent implementations found across ki/tools/ scripts.

All functions are PURE — no side effects, no file I/O.  Functions accept
scalars or numpy arrays.

Tetens coefficients used throughout: a = 17.269, b = 237.3 (degrees Celsius).
These match the most common variant in the codebase.

Reference:
    Tetens, O. (1930). Uber einige meteorologische Begriffe. Z. Geophys., 6, 297-309.

Examples::

    >>> from ki_tools_common.humidity import saturation_vapor_pressure, vpd_from_temp_rh
    >>> round(saturation_vapor_pressure(20.0), 2)
    23.39
    >>> round(vpd_from_temp_rh(25.0, 60.0), 2)
    12.67
"""

from __future__ import annotations

import numpy as np
from typing import Union

from ki_tools_common.units import CELSIUS_TO_KELVIN_OFFSET

Numeric = Union[float, int, np.ndarray]

# Tetens formula coefficients
_TETENS_A = 17.269
_TETENS_B = 237.3   # degC

# Ratio of molecular weights (water vapour / dry air)
_EPSILON = 0.622


def saturation_vapor_pressure(temp_c: Numeric) -> Numeric:
    """Saturation vapour pressure using the Tetens formula.

    .. math::

        e_s = 6.1078 \\times \\exp\\left(\\frac{17.269 \\, T}{237.3 + T}\\right)

    Args:
        temp_c: Air temperature in degrees Celsius.

    Returns:
        Saturation vapour pressure in hPa (mbar).

    Example::

        >>> round(saturation_vapor_pressure(20.0), 2)
        23.39
        >>> round(saturation_vapor_pressure(0.0), 4)
        6.1078
    """
    return 6.1078 * np.exp((_TETENS_A * temp_c) / (_TETENS_B + temp_c))


def specific_humidity_to_rh(
    q: Numeric,
    temp_k: Numeric,
    pres_pa: Numeric,
) -> Numeric:
    """Convert specific humidity to relative humidity.

    Args:
        q: Specific humidity in kg/kg.
        temp_k: Air temperature in Kelvin.
        pres_pa: Surface pressure in Pascals.

    Returns:
        Relative humidity in percent (0-100).

    Example::

        >>> # Approx. RH for q=0.01 kg/kg at 293 K and 101325 Pa
        >>> rh = specific_humidity_to_rh(0.01, 293.15, 101325.0)
        >>> 50 < rh < 80
        True
    """
    temp_c = temp_k - CELSIUS_TO_KELVIN_OFFSET
    es_hpa = saturation_vapor_pressure(temp_c)
    es_pa = es_hpa * 100.0  # hPa → Pa

    # Actual vapour pressure from specific humidity:
    #   q = epsilon * e / (p - (1 - epsilon) * e)
    #   => e = q * p / (epsilon + q * (1 - epsilon))
    e_pa = q * pres_pa / (_EPSILON + q * (1.0 - _EPSILON))
    rh = (e_pa / es_pa) * 100.0

    # Clip to physical range
    return np.clip(rh, 0.0, 100.0)


def rh_to_specific_humidity(
    rh_pct: Numeric,
    temp_k: Numeric,
    pres_pa: Numeric,
) -> Numeric:
    """Convert relative humidity to specific humidity.

    Args:
        rh_pct: Relative humidity in percent (0-100).
        temp_k: Air temperature in Kelvin.
        pres_pa: Surface pressure in Pascals.

    Returns:
        Specific humidity in kg/kg.

    Example::

        >>> q = rh_to_specific_humidity(65.0, 293.15, 101325.0)
        >>> 0.005 < q < 0.015
        True
    """
    temp_c = temp_k - CELSIUS_TO_KELVIN_OFFSET
    es_hpa = saturation_vapor_pressure(temp_c)
    es_pa = es_hpa * 100.0  # hPa → Pa

    e_pa = (rh_pct / 100.0) * es_pa

    # q = epsilon * e / (p - (1 - epsilon) * e)
    q = _EPSILON * e_pa / (pres_pa - (1.0 - _EPSILON) * e_pa)
    return np.maximum(q, 0.0)


def vpd_from_temp_rh(temp_c: Numeric, rh_pct: Numeric) -> Numeric:
    """Vapour pressure deficit from temperature and relative humidity.

    .. math::

        VPD = e_s \\times (1 - RH / 100)

    Args:
        temp_c: Air temperature in degrees Celsius.
        rh_pct: Relative humidity in percent (0-100).

    Returns:
        Vapour pressure deficit in hPa.

    Example::

        >>> round(vpd_from_temp_rh(25.0, 60.0), 2)
        12.67
        >>> round(vpd_from_temp_rh(25.0, 100.0), 2)
        0.0
    """
    es = saturation_vapor_pressure(temp_c)
    vpd = es * (1.0 - rh_pct / 100.0)
    return np.maximum(vpd, 0.0)


def dewpoint_from_rh(temp_c: Numeric, rh_pct: Numeric) -> Numeric:
    """Dewpoint temperature from air temperature and relative humidity.

    Inverts the Tetens formula applied to the actual vapour pressure.

    .. math::

        T_d = \\frac{b \\, \\gamma}{a - \\gamma}

    where :math:`\\gamma = \\ln(RH/100) + a T / (b + T)`.

    Args:
        temp_c: Air temperature in degrees Celsius.
        rh_pct: Relative humidity in percent (0-100).

    Returns:
        Dewpoint temperature in degrees Celsius.

    Example::

        >>> round(dewpoint_from_rh(25.0, 50.0), 1)
        13.9
        >>> round(dewpoint_from_rh(20.0, 100.0), 1)
        20.0
    """
    rh_frac = np.clip(rh_pct, 1e-6, 100.0) / 100.0
    gamma = np.log(rh_frac) + (_TETENS_A * temp_c) / (_TETENS_B + temp_c)
    td = (_TETENS_B * gamma) / (_TETENS_A - gamma)
    return td
