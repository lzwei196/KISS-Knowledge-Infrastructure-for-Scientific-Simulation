"""
units.py — All unit conversions for hydrological, meteorological, and ecological variables.

Consolidates conversion logic duplicated across 78+ ki/tools/ scripts.

Design principles:
    - Every function is PURE (no side effects, no file I/O).
    - Every named constant documents source AND target units.
    - A universal ``convert()`` dispatcher is provided for dynamic use.

Examples::

    >>> from ki_tools_common.units import celsius_to_kelvin, convert
    >>> celsius_to_kelvin(25.0)
    298.15
    >>> convert(1.0, 'kg/m2/s', 'mm/day', 'precipitation')
    86400.0
"""

from __future__ import annotations

import math
from typing import Union

import numpy as np

# Type alias for values that can be scalar or array-like.
Numeric = Union[float, int, np.ndarray]

# ---------------------------------------------------------------------------
# Named conversion constants  (SOURCE_UNIT → TARGET_UNIT)
# ---------------------------------------------------------------------------

# Temperature -----------------------------------------------------------
CELSIUS_TO_KELVIN_OFFSET = 273.15  # degC + 273.15 = K

# Precipitation ---------------------------------------------------------
CMFD_PRECIP_KGM2S_TO_MMDAY = 86400.0      # kg/m2/s  → mm/day  (1 kg/m2/s * 86400 s/day)
PRECIP_KGM2S_TO_MMHR = 3600.0             # kg/m2/s  → mm/hr   (1 kg/m2/s * 3600 s/hr)
PRECIP_MMDAY_TO_CMDAY = 0.1               # mm/day   → cm/day
PRECIP_MMDAY_TO_INCHESDAY = 1.0 / 25.4    # mm/day   → inches/day
PRECIP_MMDAY_TO_MDAY = 0.001              # mm/day   → m/day
PRECIP_M_TO_MMDAY = 1000.0                # m (accumulated per day) → mm/day

# Pressure --------------------------------------------------------------
PA_TO_HPA = 0.01            # Pa  → hPa  (1 Pa = 0.01 hPa)
PA_TO_KPA = 0.001           # Pa  → kPa
PA_TO_ATM = 1.0 / 101325.0  # Pa  → atm
HPA_TO_PA = 100.0           # hPa → Pa
KPA_TO_PA = 1000.0          # kPa → Pa
ATM_TO_PA = 101325.0        # atm → Pa
MB_TO_PA = 100.0            # mb  → Pa  (1 mb = 1 hPa = 100 Pa)
PA_TO_MB = 0.01             # Pa  → mb

# Radiation -------------------------------------------------------------
WM2_TO_MJM2DAY = 0.0864          # W/m2 → MJ/m2/day  (1 W/m2 * 86400 s / 1e6)
MJM2DAY_TO_WM2 = 1.0 / 0.0864   # MJ/m2/day → W/m2
WM2_TO_LANGLEYS_DAY = 2.065      # W/m2 → Langleys/day (approx)
LANGLEYS_DAY_TO_WM2 = 1.0 / 2.065
WM2_TO_CAL_CM2_MIN = 1.0 / 697.8  # W/m2 → cal/cm2/min (approx)
CAL_CM2_MIN_TO_WM2 = 697.8

# Wind ------------------------------------------------------------------
MS_TO_KMH = 3.6            # m/s  → km/h
KMH_TO_MS = 1.0 / 3.6      # km/h → m/s
MS_TO_MPH = 2.23694         # m/s  → mph
MPH_TO_MS = 1.0 / 2.23694
MS_TO_KNOTS = 1.94384       # m/s  → knots
KNOTS_TO_MS = 1.0 / 1.94384

# Soil ------------------------------------------------------------------
FRACTION_TO_PERCENT = 100.0   # 0-1 → 0-100
PERCENT_TO_FRACTION = 0.01    # 0-100 → 0-1

# Carbon ----------------------------------------------------------------
GCM2_TO_KGCM2 = 0.001                  # gC/m2  → kgC/m2
KGCM2_TO_GCM2 = 1000.0                 # kgC/m2 → gC/m2
GCM2_TO_TCHA = 0.01                     # gC/m2  → tC/ha  (1 gC/m2 * 10000 m2/ha / 1e6 g/t)
TCHA_TO_GCM2 = 100.0                    # tC/ha  → gC/m2
UMOLM2S_TO_GCM2DAY = 12.011e-6 * 86400  # umol/m2/s → gC/m2/day  (MW_C * 1e-6 * 86400)
GCM2DAY_TO_UMOLM2S = 1.0 / UMOLM2S_TO_GCM2DAY

# Length ----------------------------------------------------------------
M_TO_CM = 100.0
CM_TO_M = 0.01
M_TO_MM = 1000.0
MM_TO_M = 0.001
M_TO_INCHES = 39.3701
INCHES_TO_M = 1.0 / 39.3701
M_TO_FEET = 3.28084
FEET_TO_M = 1.0 / 3.28084
CM_TO_MM = 10.0
MM_TO_CM = 0.1
INCHES_TO_MM = 25.4
MM_TO_INCHES = 1.0 / 25.4


# ======================================================================
# Temperature conversions
# ======================================================================

def celsius_to_kelvin(temp_c: Numeric) -> Numeric:
    """Convert temperature from Celsius to Kelvin.

    Args:
        temp_c: Temperature in degrees Celsius.

    Returns:
        Temperature in Kelvin.

    Example::

        >>> celsius_to_kelvin(0.0)
        273.15
    """
    return temp_c + CELSIUS_TO_KELVIN_OFFSET


def kelvin_to_celsius(temp_k: Numeric) -> Numeric:
    """Convert temperature from Kelvin to Celsius.

    Args:
        temp_k: Temperature in Kelvin.

    Returns:
        Temperature in degrees Celsius.

    Example::

        >>> kelvin_to_celsius(273.15)
        0.0
    """
    return temp_k - CELSIUS_TO_KELVIN_OFFSET


def celsius_to_fahrenheit(temp_c: Numeric) -> Numeric:
    """Convert temperature from Celsius to Fahrenheit.

    Args:
        temp_c: Temperature in degrees Celsius.

    Returns:
        Temperature in degrees Fahrenheit.

    Example::

        >>> celsius_to_fahrenheit(100.0)
        212.0
    """
    return temp_c * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(temp_f: Numeric) -> Numeric:
    """Convert temperature from Fahrenheit to Celsius.

    Args:
        temp_f: Temperature in degrees Fahrenheit.

    Returns:
        Temperature in degrees Celsius.

    Example::

        >>> fahrenheit_to_celsius(32.0)
        0.0
    """
    return (temp_f - 32.0) * 5.0 / 9.0


def kelvin_to_fahrenheit(temp_k: Numeric) -> Numeric:
    """Convert temperature from Kelvin to Fahrenheit.

    Args:
        temp_k: Temperature in Kelvin.

    Returns:
        Temperature in degrees Fahrenheit.

    Example::

        >>> kelvin_to_fahrenheit(373.15)
        212.0
    """
    return celsius_to_fahrenheit(kelvin_to_celsius(temp_k))


def fahrenheit_to_kelvin(temp_f: Numeric) -> Numeric:
    """Convert temperature from Fahrenheit to Kelvin.

    Args:
        temp_f: Temperature in degrees Fahrenheit.

    Returns:
        Temperature in Kelvin.

    Example::

        >>> fahrenheit_to_kelvin(32.0)
        273.15
    """
    return celsius_to_kelvin(fahrenheit_to_celsius(temp_f))


# ======================================================================
# Precipitation conversions
# ======================================================================

def kgm2s_to_mmday(precip: Numeric) -> Numeric:
    """Convert precipitation from kg/m2/s to mm/day.

    Args:
        precip: Precipitation rate in kg/m2/s.

    Returns:
        Precipitation rate in mm/day.

    Example::

        >>> kgm2s_to_mmday(1.157e-5)  # ~1 mm/day
        0.99965...
    """
    return precip * CMFD_PRECIP_KGM2S_TO_MMDAY


def mmday_to_kgm2s(precip: Numeric) -> Numeric:
    """Convert precipitation from mm/day to kg/m2/s.

    Args:
        precip: Precipitation rate in mm/day.

    Returns:
        Precipitation rate in kg/m2/s.

    Example::

        >>> mmday_to_kgm2s(86.4)
        0.001
    """
    return precip / CMFD_PRECIP_KGM2S_TO_MMDAY


def kgm2s_to_mmhr(precip: Numeric) -> Numeric:
    """Convert precipitation from kg/m2/s to mm/hr.

    Args:
        precip: Precipitation rate in kg/m2/s.

    Returns:
        Precipitation rate in mm/hr.

    Example::

        >>> kgm2s_to_mmhr(2.778e-4)  # ~1 mm/hr
        1.00008
    """
    return precip * PRECIP_KGM2S_TO_MMHR


def mmday_to_cmday(precip: Numeric) -> Numeric:
    """Convert precipitation from mm/day to cm/day.

    Args:
        precip: Precipitation in mm/day.

    Returns:
        Precipitation in cm/day.

    Example::

        >>> mmday_to_cmday(10.0)
        1.0
    """
    return precip * PRECIP_MMDAY_TO_CMDAY


def mmday_to_inchesday(precip: Numeric) -> Numeric:
    """Convert precipitation from mm/day to inches/day.

    Args:
        precip: Precipitation in mm/day.

    Returns:
        Precipitation in inches/day.

    Example::

        >>> mmday_to_inchesday(25.4)
        1.0
    """
    return precip * PRECIP_MMDAY_TO_INCHESDAY


def mmday_to_mday(precip: Numeric) -> Numeric:
    """Convert precipitation from mm/day to m/day.

    Args:
        precip: Precipitation in mm/day.

    Returns:
        Precipitation in m/day.

    Example::

        >>> mmday_to_mday(1000.0)
        1.0
    """
    return precip * PRECIP_MMDAY_TO_MDAY


def mmday_to_mm_timestep(precip: Numeric, timestep_hours: float) -> Numeric:
    """Convert precipitation from mm/day to mm per model timestep.

    Args:
        precip: Precipitation in mm/day.
        timestep_hours: Model timestep length in hours.

    Returns:
        Precipitation in mm per timestep.

    Example::

        >>> mmday_to_mm_timestep(24.0, 1.0)
        1.0
        >>> mmday_to_mm_timestep(24.0, 3.0)
        3.0
    """
    return precip * (timestep_hours / 24.0)


def m_accumulated_to_mmday(precip_m: Numeric) -> Numeric:
    """Convert accumulated precipitation in metres (e.g., ERA5) to mm/day.

    Args:
        precip_m: Accumulated precipitation in metres.

    Returns:
        Precipitation in mm/day.

    Example::

        >>> m_accumulated_to_mmday(0.005)
        5.0
    """
    return precip_m * PRECIP_M_TO_MMDAY


# ======================================================================
# Pressure conversions
# ======================================================================

def pa_to_hpa(pressure: Numeric) -> Numeric:
    """Convert pressure from Pa to hPa.

    Args:
        pressure: Pressure in Pascals.

    Returns:
        Pressure in hectopascals (hPa).

    Example::

        >>> pa_to_hpa(101325.0)
        1013.25
    """
    return pressure * PA_TO_HPA


def hpa_to_pa(pressure: Numeric) -> Numeric:
    """Convert pressure from hPa to Pa.

    Args:
        pressure: Pressure in hectopascals.

    Returns:
        Pressure in Pascals.

    Example::

        >>> hpa_to_pa(1013.25)
        101325.0
    """
    return pressure * HPA_TO_PA


def pa_to_kpa(pressure: Numeric) -> Numeric:
    """Convert pressure from Pa to kPa.

    Args:
        pressure: Pressure in Pascals.

    Returns:
        Pressure in kilopascals.

    Example::

        >>> pa_to_kpa(101325.0)
        101.325
    """
    return pressure * PA_TO_KPA


def kpa_to_pa(pressure: Numeric) -> Numeric:
    """Convert pressure from kPa to Pa.

    Args:
        pressure: Pressure in kilopascals.

    Returns:
        Pressure in Pascals.

    Example::

        >>> kpa_to_pa(101.325)
        101325.0
    """
    return pressure * KPA_TO_PA


def pa_to_atm(pressure: Numeric) -> Numeric:
    """Convert pressure from Pa to atmospheres.

    Args:
        pressure: Pressure in Pascals.

    Returns:
        Pressure in standard atmospheres.

    Example::

        >>> pa_to_atm(101325.0)
        1.0
    """
    return pressure * PA_TO_ATM


def atm_to_pa(pressure: Numeric) -> Numeric:
    """Convert pressure from atmospheres to Pa.

    Args:
        pressure: Pressure in standard atmospheres.

    Returns:
        Pressure in Pascals.

    Example::

        >>> atm_to_pa(1.0)
        101325.0
    """
    return pressure * ATM_TO_PA


def pa_to_mb(pressure: Numeric) -> Numeric:
    """Convert pressure from Pa to millibars.

    Note: 1 mb = 1 hPa.

    Args:
        pressure: Pressure in Pascals.

    Returns:
        Pressure in millibars.

    Example::

        >>> pa_to_mb(101325.0)
        1013.25
    """
    return pressure * PA_TO_MB


def mb_to_pa(pressure: Numeric) -> Numeric:
    """Convert pressure from millibars to Pa.

    Args:
        pressure: Pressure in millibars.

    Returns:
        Pressure in Pascals.

    Example::

        >>> mb_to_pa(1013.25)
        101325.0
    """
    return pressure * MB_TO_PA


# ======================================================================
# Radiation conversions
# ======================================================================

def wm2_to_mjm2day(rad: Numeric) -> Numeric:
    """Convert radiation from W/m2 to MJ/m2/day.

    Args:
        rad: Radiation in W/m2.

    Returns:
        Radiation in MJ/m2/day.

    Example::

        >>> round(wm2_to_mjm2day(250.0), 2)
        21.6
    """
    return rad * WM2_TO_MJM2DAY


def mjm2day_to_wm2(rad: Numeric) -> Numeric:
    """Convert radiation from MJ/m2/day to W/m2.

    Args:
        rad: Radiation in MJ/m2/day.

    Returns:
        Radiation in W/m2.

    Example::

        >>> round(mjm2day_to_wm2(21.6), 1)
        250.0
    """
    return rad * MJM2DAY_TO_WM2


def wm2_to_langleys_day(rad: Numeric) -> Numeric:
    """Convert radiation from W/m2 to Langleys/day.

    Args:
        rad: Radiation in W/m2.

    Returns:
        Radiation in Langleys/day.

    Example::

        >>> round(wm2_to_langleys_day(100.0), 1)
        206.5
    """
    return rad * WM2_TO_LANGLEYS_DAY


def langleys_day_to_wm2(rad: Numeric) -> Numeric:
    """Convert radiation from Langleys/day to W/m2.

    Args:
        rad: Radiation in Langleys/day.

    Returns:
        Radiation in W/m2.

    Example::

        >>> round(langleys_day_to_wm2(206.5), 1)
        100.0
    """
    return rad * LANGLEYS_DAY_TO_WM2


def wm2_to_cal_cm2_min(rad: Numeric) -> Numeric:
    """Convert radiation from W/m2 to cal/cm2/min.

    Args:
        rad: Radiation in W/m2.

    Returns:
        Radiation in cal/cm2/min.

    Example::

        >>> round(wm2_to_cal_cm2_min(697.8), 4)
        1.0
    """
    return rad * WM2_TO_CAL_CM2_MIN


def cal_cm2_min_to_wm2(rad: Numeric) -> Numeric:
    """Convert radiation from cal/cm2/min to W/m2.

    Args:
        rad: Radiation in cal/cm2/min.

    Returns:
        Radiation in W/m2.

    Example::

        >>> cal_cm2_min_to_wm2(1.0)
        697.8
    """
    return rad * CAL_CM2_MIN_TO_WM2


# ======================================================================
# Wind conversions
# ======================================================================

def ms_to_kmh(wind: Numeric) -> Numeric:
    """Convert wind speed from m/s to km/h.

    Args:
        wind: Wind speed in m/s.

    Returns:
        Wind speed in km/h.

    Example::

        >>> ms_to_kmh(10.0)
        36.0
    """
    return wind * MS_TO_KMH


def kmh_to_ms(wind: Numeric) -> Numeric:
    """Convert wind speed from km/h to m/s.

    Args:
        wind: Wind speed in km/h.

    Returns:
        Wind speed in m/s.

    Example::

        >>> round(kmh_to_ms(36.0), 1)
        10.0
    """
    return wind * KMH_TO_MS


def ms_to_mph(wind: Numeric) -> Numeric:
    """Convert wind speed from m/s to mph.

    Args:
        wind: Wind speed in m/s.

    Returns:
        Wind speed in mph.

    Example::

        >>> round(ms_to_mph(10.0), 4)
        22.3694
    """
    return wind * MS_TO_MPH


def mph_to_ms(wind: Numeric) -> Numeric:
    """Convert wind speed from mph to m/s.

    Args:
        wind: Wind speed in mph.

    Returns:
        Wind speed in m/s.

    Example::

        >>> round(mph_to_ms(22.3694), 1)
        10.0
    """
    return wind * MPH_TO_MS


def ms_to_knots(wind: Numeric) -> Numeric:
    """Convert wind speed from m/s to knots.

    Args:
        wind: Wind speed in m/s.

    Returns:
        Wind speed in knots.

    Example::

        >>> round(ms_to_knots(10.0), 4)
        19.4384
    """
    return wind * MS_TO_KNOTS


def knots_to_ms(wind: Numeric) -> Numeric:
    """Convert wind speed from knots to m/s.

    Args:
        wind: Wind speed in knots.

    Returns:
        Wind speed in m/s.

    Example::

        >>> round(knots_to_ms(19.4384), 1)
        10.0
    """
    return wind * KNOTS_TO_MS


# ======================================================================
# Soil conversions
# ======================================================================

def fraction_to_percent(value: Numeric) -> Numeric:
    """Convert a fraction (0-1) to percent (0-100).

    Args:
        value: Value as a fraction (0-1 range).

    Returns:
        Value as a percentage (0-100 range).

    Example::

        >>> fraction_to_percent(0.35)
        35.0
    """
    return value * FRACTION_TO_PERCENT


def percent_to_fraction(value: Numeric) -> Numeric:
    """Convert percent (0-100) to a fraction (0-1).

    Args:
        value: Value as a percentage (0-100 range).

    Returns:
        Value as a fraction (0-1 range).

    Example::

        >>> percent_to_fraction(35.0)
        0.35
    """
    return value * PERCENT_TO_FRACTION


# ======================================================================
# Carbon conversions
# ======================================================================

def gcm2_to_kgcm2(carbon: Numeric) -> Numeric:
    """Convert carbon flux from gC/m2 to kgC/m2.

    Args:
        carbon: Carbon in gC/m2.

    Returns:
        Carbon in kgC/m2.

    Example::

        >>> gcm2_to_kgcm2(1000.0)
        1.0
    """
    return carbon * GCM2_TO_KGCM2


def kgcm2_to_gcm2(carbon: Numeric) -> Numeric:
    """Convert carbon flux from kgC/m2 to gC/m2.

    Args:
        carbon: Carbon in kgC/m2.

    Returns:
        Carbon in gC/m2.

    Example::

        >>> kgcm2_to_gcm2(1.0)
        1000.0
    """
    return carbon * KGCM2_TO_GCM2


def gcm2_to_tcha(carbon: Numeric) -> Numeric:
    """Convert carbon from gC/m2 to tC/ha.

    Args:
        carbon: Carbon in gC/m2.

    Returns:
        Carbon in tC/ha (tonnes carbon per hectare).

    Example::

        >>> gcm2_to_tcha(100.0)
        1.0
    """
    return carbon * GCM2_TO_TCHA


def tcha_to_gcm2(carbon: Numeric) -> Numeric:
    """Convert carbon from tC/ha to gC/m2.

    Args:
        carbon: Carbon in tC/ha.

    Returns:
        Carbon in gC/m2.

    Example::

        >>> tcha_to_gcm2(1.0)
        100.0
    """
    return carbon * TCHA_TO_GCM2


def umolm2s_to_gcm2day(flux: Numeric) -> Numeric:
    """Convert carbon flux from umol/m2/s to gC/m2/day.

    Uses molecular weight of carbon (12.011 g/mol).

    Args:
        flux: Carbon flux in umol/m2/s.

    Returns:
        Carbon flux in gC/m2/day.

    Example::

        >>> round(umolm2s_to_gcm2day(1.0), 4)
        1.0378
    """
    return flux * UMOLM2S_TO_GCM2DAY


def gcm2day_to_umolm2s(flux: Numeric) -> Numeric:
    """Convert carbon flux from gC/m2/day to umol/m2/s.

    Args:
        flux: Carbon flux in gC/m2/day.

    Returns:
        Carbon flux in umol/m2/s.

    Example::

        >>> round(gcm2day_to_umolm2s(1.0378), 1)
        1.0
    """
    return flux * GCM2DAY_TO_UMOLM2S


# ======================================================================
# Length conversions
# ======================================================================

def m_to_cm(length: Numeric) -> Numeric:
    """Convert length from metres to centimetres.

    Example::

        >>> m_to_cm(1.5)
        150.0
    """
    return length * M_TO_CM


def cm_to_m(length: Numeric) -> Numeric:
    """Convert length from centimetres to metres.

    Example::

        >>> cm_to_m(150.0)
        1.5
    """
    return length * CM_TO_M


def m_to_mm(length: Numeric) -> Numeric:
    """Convert length from metres to millimetres.

    Example::

        >>> m_to_mm(0.5)
        500.0
    """
    return length * M_TO_MM


def mm_to_m(length: Numeric) -> Numeric:
    """Convert length from millimetres to metres.

    Example::

        >>> mm_to_m(500.0)
        0.5
    """
    return length * MM_TO_M


def m_to_inches(length: Numeric) -> Numeric:
    """Convert length from metres to inches.

    Example::

        >>> round(m_to_inches(1.0), 4)
        39.3701
    """
    return length * M_TO_INCHES


def inches_to_m(length: Numeric) -> Numeric:
    """Convert length from inches to metres.

    Example::

        >>> round(inches_to_m(39.3701), 4)
        1.0
    """
    return length * INCHES_TO_M


def m_to_feet(length: Numeric) -> Numeric:
    """Convert length from metres to feet.

    Example::

        >>> round(m_to_feet(1.0), 4)
        3.2808
    """
    return length * M_TO_FEET


def feet_to_m(length: Numeric) -> Numeric:
    """Convert length from feet to metres.

    Example::

        >>> round(feet_to_m(3.28084), 4)
        1.0
    """
    return length * FEET_TO_M


# ======================================================================
# Universal conversion dispatcher
# ======================================================================

# Mapping: (variable_type, from_unit, to_unit) -> conversion function or factor
# Units are normalised to lowercase for matching.
_CONVERSION_TABLE: dict[tuple[str, str, str], object] = {
    # Temperature
    ("temperature", "c", "k"): celsius_to_kelvin,
    ("temperature", "celsius", "kelvin"): celsius_to_kelvin,
    ("temperature", "degc", "k"): celsius_to_kelvin,
    ("temperature", "k", "c"): kelvin_to_celsius,
    ("temperature", "kelvin", "celsius"): kelvin_to_celsius,
    ("temperature", "k", "degc"): kelvin_to_celsius,
    ("temperature", "c", "f"): celsius_to_fahrenheit,
    ("temperature", "celsius", "fahrenheit"): celsius_to_fahrenheit,
    ("temperature", "f", "c"): fahrenheit_to_celsius,
    ("temperature", "fahrenheit", "celsius"): fahrenheit_to_celsius,
    ("temperature", "k", "f"): kelvin_to_fahrenheit,
    ("temperature", "kelvin", "fahrenheit"): kelvin_to_fahrenheit,
    ("temperature", "f", "k"): fahrenheit_to_kelvin,
    ("temperature", "fahrenheit", "kelvin"): fahrenheit_to_kelvin,

    # Precipitation
    ("precipitation", "kg/m2/s", "mm/day"): kgm2s_to_mmday,
    ("precipitation", "mm/day", "kg/m2/s"): mmday_to_kgm2s,
    ("precipitation", "kg/m2/s", "mm/hr"): kgm2s_to_mmhr,
    ("precipitation", "mm/day", "cm/day"): mmday_to_cmday,
    ("precipitation", "mm/day", "inches/day"): mmday_to_inchesday,
    ("precipitation", "mm/day", "m/day"): mmday_to_mday,
    ("precipitation", "m", "mm/day"): m_accumulated_to_mmday,

    # Pressure
    ("pressure", "pa", "hpa"): pa_to_hpa,
    ("pressure", "hpa", "pa"): hpa_to_pa,
    ("pressure", "pa", "kpa"): pa_to_kpa,
    ("pressure", "kpa", "pa"): kpa_to_pa,
    ("pressure", "pa", "atm"): pa_to_atm,
    ("pressure", "atm", "pa"): atm_to_pa,
    ("pressure", "pa", "mb"): pa_to_mb,
    ("pressure", "mb", "pa"): mb_to_pa,

    # Radiation
    ("radiation", "w/m2", "mj/m2/day"): wm2_to_mjm2day,
    ("radiation", "mj/m2/day", "w/m2"): mjm2day_to_wm2,
    ("radiation", "w/m2", "langleys/day"): wm2_to_langleys_day,
    ("radiation", "langleys/day", "w/m2"): langleys_day_to_wm2,
    ("radiation", "w/m2", "cal/cm2/min"): wm2_to_cal_cm2_min,
    ("radiation", "cal/cm2/min", "w/m2"): cal_cm2_min_to_wm2,

    # Wind
    ("wind", "m/s", "km/h"): ms_to_kmh,
    ("wind", "km/h", "m/s"): kmh_to_ms,
    ("wind", "m/s", "mph"): ms_to_mph,
    ("wind", "mph", "m/s"): mph_to_ms,
    ("wind", "m/s", "knots"): ms_to_knots,
    ("wind", "knots", "m/s"): knots_to_ms,

    # Soil
    ("soil", "fraction", "percent"): fraction_to_percent,
    ("soil", "percent", "fraction"): percent_to_fraction,

    # Carbon
    ("carbon", "gc/m2", "kgc/m2"): gcm2_to_kgcm2,
    ("carbon", "kgc/m2", "gc/m2"): kgcm2_to_gcm2,
    ("carbon", "gc/m2", "tc/ha"): gcm2_to_tcha,
    ("carbon", "tc/ha", "gc/m2"): tcha_to_gcm2,
    ("carbon", "umol/m2/s", "gc/m2/day"): umolm2s_to_gcm2day,
    ("carbon", "gc/m2/day", "umol/m2/s"): gcm2day_to_umolm2s,

    # Length
    ("length", "m", "cm"): m_to_cm,
    ("length", "cm", "m"): cm_to_m,
    ("length", "m", "mm"): m_to_mm,
    ("length", "mm", "m"): mm_to_m,
    ("length", "m", "inches"): m_to_inches,
    ("length", "inches", "m"): inches_to_m,
    ("length", "m", "feet"): m_to_feet,
    ("length", "feet", "m"): feet_to_m,
}


def convert(
    value: Numeric,
    from_unit: str,
    to_unit: str,
    variable_type: str,
) -> Numeric:
    """Universal unit conversion dispatcher.

    Looks up the appropriate conversion function based on variable type and
    unit pair, then applies it.

    Args:
        value: The numeric value (scalar or numpy array) to convert.
        from_unit: Source unit string (case-insensitive).
        to_unit: Target unit string (case-insensitive).
        variable_type: Category of the variable — one of 'temperature',
            'precipitation', 'pressure', 'radiation', 'wind', 'soil',
            'carbon', 'length'.

    Returns:
        Converted value(s).

    Raises:
        KeyError: If the (variable_type, from_unit, to_unit) combination is
            not registered.

    Example::

        >>> convert(25.0, 'C', 'K', 'temperature')
        298.15
        >>> convert(1.0, 'kg/m2/s', 'mm/day', 'precipitation')
        86400.0
        >>> convert(101325.0, 'Pa', 'atm', 'pressure')
        1.0
    """
    key = (variable_type.lower(), from_unit.lower(), to_unit.lower())
    if key not in _CONVERSION_TABLE:
        raise KeyError(
            f"No conversion registered for ({variable_type!r}, "
            f"{from_unit!r} -> {to_unit!r}). "
            f"Available variable types: temperature, precipitation, pressure, "
            f"radiation, wind, soil, carbon, length."
        )
    func = _CONVERSION_TABLE[key]
    return func(value)
