"""
forcing_sources.py — Data source variable name mappings and conversion factors.

Consolidates forcing-source metadata duplicated across 68 ki/tools/ scripts.
Provides canonical dictionaries for CMFD, MSWX, ERA5, and FLUXNET variable
definitions, and a ``get_conversion_factor()`` helper for dynamic lookups.

Examples::

    >>> from ki_tools_common.forcing_sources import get_conversion_factor, CMFD_VARIABLES
    >>> CMFD_VARIABLES['prec']['unit']
    'kg/m2/s'
    >>> get_conversion_factor('CMFD', 'prec', 'mm/day')
    86400.0
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ======================================================================
# CMFD (China Meteorological Forcing Dataset)
# ======================================================================

CMFD_VARIABLES: Dict[str, Dict[str, Any]] = {
    "prec": {
        "unit": "kg/m2/s",
        "long_name": "precipitation",
        "standard_name": "precipitation_flux",
        "conversions": {
            "mm/day": 86400.0,
            "mm/hr": 3600.0,
            "m/day": 86.4,
        },
    },
    "temp": {
        "unit": "K",
        "long_name": "near-surface air temperature",
        "standard_name": "air_temperature",
        "conversions": {
            "degC": -273.15,  # additive offset, not multiplicative
        },
    },
    "shum": {
        "unit": "kg/kg",
        "long_name": "near-surface specific humidity",
        "standard_name": "specific_humidity",
        "conversions": {
            "g/kg": 1000.0,
        },
    },
    "pres": {
        "unit": "Pa",
        "long_name": "surface pressure",
        "standard_name": "surface_air_pressure",
        "conversions": {
            "hPa": 0.01,
            "kPa": 0.001,
        },
    },
    "wind": {
        "unit": "m/s",
        "long_name": "near-surface wind speed",
        "standard_name": "wind_speed",
        "conversions": {
            "km/h": 3.6,
            "mph": 2.23694,
        },
    },
    "srad": {
        "unit": "W/m2",
        "long_name": "downward shortwave radiation",
        "standard_name": "surface_downwelling_shortwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
            "Langleys/day": 2.065,
        },
    },
    "lrad": {
        "unit": "W/m2",
        "long_name": "downward longwave radiation",
        "standard_name": "surface_downwelling_longwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
}

# ======================================================================
# MSWX (Multi-Source Weather)
# ======================================================================

MSWX_VARIABLES: Dict[str, Dict[str, Any]] = {
    "P": {
        "unit": "mm/3hr",
        "long_name": "precipitation",
        "standard_name": "precipitation_amount",
        "conversions": {
            "mm/day": 8.0,  # 8 x 3-hr periods per day
            "kg/m2/s": 8.0 / 86400.0,
        },
    },
    "Tair": {
        "unit": "K",
        "long_name": "near-surface air temperature",
        "standard_name": "air_temperature",
        "conversions": {
            "degC": -273.15,
        },
    },
    "Tmax": {
        "unit": "K",
        "long_name": "daily maximum temperature",
        "standard_name": "air_temperature",
        "conversions": {
            "degC": -273.15,
        },
    },
    "Tmin": {
        "unit": "K",
        "long_name": "daily minimum temperature",
        "standard_name": "air_temperature",
        "conversions": {
            "degC": -273.15,
        },
    },
    "Wind": {
        "unit": "m/s",
        "long_name": "near-surface wind speed",
        "standard_name": "wind_speed",
        "conversions": {
            "km/h": 3.6,
        },
    },
    "SWd": {
        "unit": "W/m2",
        "long_name": "downward shortwave radiation",
        "standard_name": "surface_downwelling_shortwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
    "LWd": {
        "unit": "W/m2",
        "long_name": "downward longwave radiation",
        "standard_name": "surface_downwelling_longwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
    "Qair": {
        "unit": "kg/kg",
        "long_name": "near-surface specific humidity",
        "standard_name": "specific_humidity",
        "conversions": {
            "g/kg": 1000.0,
        },
    },
    "PSurf": {
        "unit": "Pa",
        "long_name": "surface pressure",
        "standard_name": "surface_air_pressure",
        "conversions": {
            "hPa": 0.01,
            "kPa": 0.001,
        },
    },
    "RelHum": {
        "unit": "%",
        "long_name": "relative humidity",
        "standard_name": "relative_humidity",
        "conversions": {
            "fraction": 0.01,
        },
    },
}

# ======================================================================
# ERA5 (ECMWF Reanalysis v5)
# ======================================================================

ERA5_VARIABLES: Dict[str, Dict[str, Any]] = {
    "tp": {
        "unit": "m/accumulated",
        "long_name": "total precipitation",
        "standard_name": "precipitation_amount",
        "conversions": {
            "mm/day": 1000.0,  # m -> mm (assuming daily accumulation)
            "kg/m2/s": 1000.0 / 86400.0,
        },
    },
    "t2m": {
        "unit": "K",
        "long_name": "2 metre temperature",
        "standard_name": "air_temperature",
        "conversions": {
            "degC": -273.15,
        },
    },
    "d2m": {
        "unit": "K",
        "long_name": "2 metre dewpoint temperature",
        "standard_name": "dew_point_temperature",
        "conversions": {
            "degC": -273.15,
        },
    },
    "sp": {
        "unit": "Pa",
        "long_name": "surface pressure",
        "standard_name": "surface_air_pressure",
        "conversions": {
            "hPa": 0.01,
            "kPa": 0.001,
        },
    },
    "u10": {
        "unit": "m/s",
        "long_name": "10 metre U wind component",
        "standard_name": "eastward_wind",
        "conversions": {
            "km/h": 3.6,
        },
    },
    "v10": {
        "unit": "m/s",
        "long_name": "10 metre V wind component",
        "standard_name": "northward_wind",
        "conversions": {
            "km/h": 3.6,
        },
    },
    "ssrd": {
        "unit": "J/m2/accumulated",
        "long_name": "surface solar radiation downwards",
        "standard_name": "surface_downwelling_shortwave_flux_in_air",
        "conversions": {
            "W/m2": 1.0 / 86400.0,  # J/m2/day -> W/m2
            "MJ/m2/day": 1e-6,
        },
    },
    "strd": {
        "unit": "J/m2/accumulated",
        "long_name": "surface thermal radiation downwards",
        "standard_name": "surface_downwelling_longwave_flux_in_air",
        "conversions": {
            "W/m2": 1.0 / 86400.0,
            "MJ/m2/day": 1e-6,
        },
    },
}

# ======================================================================
# FLUXNET (eddy-covariance observations)
# ======================================================================

FLUXNET_VARIABLES: Dict[str, Dict[str, Any]] = {
    "P_F": {
        "unit": "mm",
        "long_name": "precipitation (gap-filled)",
        "standard_name": "precipitation_amount",
        "conversions": {
            "m": 0.001,
            "kg/m2/s": 1.0 / 86400.0,  # mm/day -> kg/m2/s
        },
    },
    "TA_F": {
        "unit": "degC",
        "long_name": "air temperature (gap-filled)",
        "standard_name": "air_temperature",
        "conversions": {
            "K": 273.15,  # additive
        },
    },
    "SW_IN_F": {
        "unit": "W/m2",
        "long_name": "shortwave radiation incoming (gap-filled)",
        "standard_name": "surface_downwelling_shortwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
    "LW_IN_F": {
        "unit": "W/m2",
        "long_name": "longwave radiation incoming (gap-filled)",
        "standard_name": "surface_downwelling_longwave_flux_in_air",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
    "VPD_F": {
        "unit": "hPa",
        "long_name": "vapour pressure deficit (gap-filled)",
        "standard_name": "water_vapor_saturation_deficit_in_air",
        "conversions": {
            "Pa": 100.0,
            "kPa": 0.1,
        },
    },
    "GPP_NT_VUT_REF": {
        "unit": "gC/m2/day",
        "long_name": "gross primary production (nighttime, VUT, reference)",
        "standard_name": "gross_primary_productivity_of_biomass_expressed_as_carbon",
        "conversions": {
            "umol/m2/s": 1.0 / (12.011e-6 * 86400),
            "kgC/m2/day": 0.001,
        },
    },
    "NEE_VUT_REF": {
        "unit": "gC/m2/day",
        "long_name": "net ecosystem exchange (VUT, reference)",
        "standard_name": "surface_upward_mass_flux_of_carbon_dioxide_expressed_as_carbon_due_to_emission_from_natural_sources",
        "conversions": {
            "umol/m2/s": 1.0 / (12.011e-6 * 86400),
            "kgC/m2/day": 0.001,
        },
    },
    "LE_F_MDS": {
        "unit": "W/m2",
        "long_name": "latent heat flux (MDS gap-filled)",
        "standard_name": "surface_upward_latent_heat_flux",
        "conversions": {
            "MJ/m2/day": 0.0864,
            "mm/day": 1.0 / 2.45,  # approx. LE -> ET using L_v=2.45 MJ/kg
        },
    },
    "H_F_MDS": {
        "unit": "W/m2",
        "long_name": "sensible heat flux (MDS gap-filled)",
        "standard_name": "surface_upward_sensible_heat_flux",
        "conversions": {
            "MJ/m2/day": 0.0864,
        },
    },
    "WS_F": {
        "unit": "m/s",
        "long_name": "wind speed (gap-filled)",
        "standard_name": "wind_speed",
        "conversions": {
            "km/h": 3.6,
        },
    },
}


# ======================================================================
# Aggregated source registry
# ======================================================================

_SOURCES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "CMFD": CMFD_VARIABLES,
    "cmfd": CMFD_VARIABLES,
    "MSWX": MSWX_VARIABLES,
    "mswx": MSWX_VARIABLES,
    "ERA5": ERA5_VARIABLES,
    "era5": ERA5_VARIABLES,
    "FLUXNET": FLUXNET_VARIABLES,
    "fluxnet": FLUXNET_VARIABLES,
}

# Temperature conversion entries use additive offsets, not multiplicative factors.
# This set tracks which (source, variable, target_unit) entries are additive.
_ADDITIVE_CONVERSIONS = {
    ("CMFD", "temp", "degC"),
    ("MSWX", "Tair", "degC"),
    ("MSWX", "Tmax", "degC"),
    ("MSWX", "Tmin", "degC"),
    ("ERA5", "t2m", "degC"),
    ("ERA5", "d2m", "degC"),
    ("FLUXNET", "TA_F", "K"),
}


def get_conversion_factor(
    source: str,
    variable: str,
    target_unit: str,
) -> float:
    """Look up the numeric conversion factor for a forcing variable.

    For most variables the conversion is multiplicative:
    ``target = source_value * factor``.

    For temperature conversions (K <-> degC), the "factor" is an **additive
    offset** (e.g., -273.15 to go from K to degC). Callers should add rather
    than multiply. This is documented on each entry but can also be checked
    via the ``is_additive_conversion()`` helper.

    Args:
        source: Data source name (``'CMFD'``, ``'MSWX'``, ``'ERA5'``,
            ``'FLUXNET'``; case-insensitive lookup supported).
        variable: Variable name in the source's convention.
        target_unit: Desired target unit string.

    Returns:
        Numeric conversion factor (float).

    Raises:
        KeyError: If source, variable, or target_unit is not found.

    Example::

        >>> get_conversion_factor('CMFD', 'prec', 'mm/day')
        86400.0
        >>> get_conversion_factor('ERA5', 'tp', 'mm/day')
        1000.0
    """
    src_vars = _SOURCES.get(source)
    if src_vars is None:
        src_vars = _SOURCES.get(source.upper())
    if src_vars is None:
        raise KeyError(
            f"Unknown source '{source}'. "
            f"Available: CMFD, MSWX, ERA5, FLUXNET."
        )

    var_info = src_vars.get(variable)
    if var_info is None:
        raise KeyError(
            f"Unknown variable '{variable}' for source '{source}'. "
            f"Available: {list(src_vars.keys())}."
        )

    conversions = var_info.get("conversions", {})
    if target_unit not in conversions:
        raise KeyError(
            f"No conversion from {var_info['unit']} to '{target_unit}' "
            f"registered for {source}/{variable}. "
            f"Available targets: {list(conversions.keys())}."
        )

    return float(conversions[target_unit])


def is_additive_conversion(
    source: str,
    variable: str,
    target_unit: str,
) -> bool:
    """Check whether a conversion factor is additive (e.g. K -> degC).

    Args:
        source: Data source name.
        variable: Variable name.
        target_unit: Target unit string.

    Returns:
        True if the conversion is additive (use ``value + factor``), False
        if multiplicative (use ``value * factor``).

    Example::

        >>> is_additive_conversion('CMFD', 'temp', 'degC')
        True
        >>> is_additive_conversion('CMFD', 'prec', 'mm/day')
        False
    """
    key = (source.upper(), variable, target_unit)
    # Also check with original case
    return key in _ADDITIVE_CONVERSIONS or (source, variable, target_unit) in _ADDITIVE_CONVERSIONS
