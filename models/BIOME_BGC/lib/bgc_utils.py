"""
bgc_utils.py
Shared utility functions for BIOME-BGC knowledge infrastructure tools.

Provides:
- Day length calculation (astronomical formula from CBM, Dunn & Mackay 1976)
- VPD calculation from temperature + humidity
- Tday approximation (daytime average temperature)
- Unit conversion helpers
- INI file keyword-based section generator
"""

import math
import os
import sys
import json
from pathlib import Path
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius
from ki_tools_common.humidity import saturation_vapor_pressure

# ---------------------------------------------------------------------------
# Physical constants (matching bgc_constants.h)
# ---------------------------------------------------------------------------
RAD2PAR = 0.45        # fraction of shortwave that is PAR
SBC = 5.67e-8         # Stefan-Boltzmann constant (W/m2/K4)
EPS = 0.6219          # ratio of molecular weight of water to dry air


# ---------------------------------------------------------------------------
# Day length (seconds) from latitude and day-of-year
# Using the CBM method (Dunn & Mackay 1976), same as MTCLIM
# ---------------------------------------------------------------------------
def compute_daylength(lat_deg: float, yday: int) -> float:
    """
    Compute day length in seconds from latitude (degrees) and year-day.

    Parameters
    ----------
    lat_deg : float
        Site latitude in decimal degrees (negative for S hemisphere).
    yday : int
        Day of year (1-366).

    Returns
    -------
    float
        Day length in seconds.
    """
    lat_rad = lat_deg * math.pi / 180.0
    # solar declination (radians)
    decl = -23.4856 * math.cos(2.0 * math.pi * (yday + 10.0) / 365.25)
    decl_rad = decl * math.pi / 180.0

    # hour angle at sunrise/sunset
    cosphi = -math.tan(lat_rad) * math.tan(decl_rad)

    if cosphi < -1.0:
        # polar day (24 hours)
        return 86400.0
    elif cosphi > 1.0:
        # polar night (0 hours)
        return 0.0
    else:
        ha = math.acos(cosphi)
        dayl = 2.0 * ha * (86400.0 / (2.0 * math.pi))
        return dayl


# ---------------------------------------------------------------------------
# VPD from temperature and specific humidity
# ---------------------------------------------------------------------------
def compute_vpd_from_tmin_tmax_q(tmin: float, tmax: float, q: float,
                                  pressure: float = 101325.0) -> float:
    """
    Compute daytime average VPD in Pa from temperature and specific humidity.

    Parameters
    ----------
    tmin : float
        Daily minimum temperature (deg C).
    tmax : float
        Daily maximum temperature (deg C).
    q : float
        Specific humidity (kg/kg).
    pressure : float
        Surface pressure (Pa). Default 101325 Pa.

    Returns
    -------
    float
        Vapor pressure deficit (Pa). Minimum 0.
    """
    tday = tmin + 0.45 * (tmax - tmin)
    es = float(saturation_vapor_pressure(tday)) * 100.0  # hPa -> Pa (ki_tools_common)
    ea = q * pressure / (EPS + (1.0 - EPS) * q)
    vpd = max(0.0, es - ea)
    return vpd


def compute_vpd_from_t_rh(t: float, rh: float) -> float:
    """
    Compute VPD in Pa from temperature (C) and relative humidity (%).

    Parameters
    ----------
    t : float
        Temperature (deg C).
    rh : float
        Relative humidity (0-100 %).

    Returns
    -------
    float
        Vapor pressure deficit (Pa). Minimum 0.
    """
    es = float(saturation_vapor_pressure(t)) * 100.0  # hPa -> Pa (ki_tools_common)
    ea = es * rh / 100.0
    vpd = max(0.0, es - ea)
    return vpd


# ---------------------------------------------------------------------------
# Tday approximation (Thornton & Running 1999)
# ---------------------------------------------------------------------------
def compute_tday(tmin: float, tmax: float) -> float:
    """
    Approximate daytime average temperature.
    Tday = Tmin + 0.45 * (Tmax - Tmin)
    """
    return tmin + 0.45 * (tmax - tmin)


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------
def mm_to_cm(mm: float) -> float:
    """Convert mm to cm (BIOME-BGC precipitation unit)."""
    return mm / 10.0


def kpa_to_pa(kpa: float) -> float:
    """Convert kPa to Pa (BIOME-BGC VPD unit)."""
    return kpa * 1000.0


def kelvin_to_celsius(k: float) -> float:
    """Convert Kelvin to Celsius."""
    return kelvin_to_celsius(k)


# ---------------------------------------------------------------------------
# EPC parameter defaults (from bundled .epc files)
# ---------------------------------------------------------------------------
EPC_DEFAULTS = {
    "ENF": {
        "name": "Evergreen Needleleaf Forest",
        "woody": 1, "evergreen": 1, "c3_flag": 1, "phenology_flag": 1,
        "onday": 0, "offday": 0,
        "transfer_pdays": 0.3, "litfall_pdays": 0.3,
        "leaf_turnover": 0.25, "livewood_turnover": 0.70,
        "mortality": 0.005, "fire_mortality": 0.005,
        "froot_leaf": 1.0, "stem_leaf": 2.2,
        "livewood_wood": 0.1, "croot_stem": 0.3,
        "current_growth_prop": 0.5,
        "leaf_cn": 42.0, "leaflitter_cn": 93.0, "froot_cn": 42.0,
        "livewood_cn": 50.0, "deadwood_cn": 729.0,
        "ll_labile": 0.32, "ll_cellulose": 0.44, "ll_lignin": 0.24,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.76, "dw_lignin": 0.24,
        "int_coef": 0.041, "ext_coef": 0.5,
        "lai_ratio": 2.6, "sla": 12.0, "sla_ratio": 2.0,
        "flnr": 0.04, "gl_smax": 0.003, "gl_c": 0.00001, "gl_bl": 0.08,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
    "EBF": {
        "name": "Evergreen Broadleaf Forest",
        "woody": 1, "evergreen": 1, "c3_flag": 1, "phenology_flag": 1,
        "onday": 0, "offday": 0,
        "transfer_pdays": 0.2, "litfall_pdays": 0.2,
        "leaf_turnover": 0.5, "livewood_turnover": 0.70,
        "mortality": 0.005, "fire_mortality": 0.002,
        "froot_leaf": 1.0, "stem_leaf": 1.0,
        "livewood_wood": 0.22, "croot_stem": 0.3,
        "current_growth_prop": 0.5,
        "leaf_cn": 42.0, "leaflitter_cn": 49.0, "froot_cn": 42.0,
        "livewood_cn": 50.0, "deadwood_cn": 300.0,
        "ll_labile": 0.32, "ll_cellulose": 0.44, "ll_lignin": 0.24,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.76, "dw_lignin": 0.24,
        "int_coef": 0.041, "ext_coef": 0.7,
        "lai_ratio": 2.0, "sla": 12.0, "sla_ratio": 2.0,
        "flnr": 0.06, "gl_smax": 0.005, "gl_c": 0.00001, "gl_bl": 0.01,
        "psi_open": -0.6, "psi_close": -3.9,
        "vpd_open": 1800.0, "vpd_close": 4100.0,
    },
    "DNF": {
        "name": "Deciduous Needleleaf Forest",
        "woody": 1, "evergreen": 0, "c3_flag": 1, "phenology_flag": 0,
        "onday": 100, "offday": 300,
        "transfer_pdays": 0.2, "litfall_pdays": 0.2,
        "leaf_turnover": 1.0, "livewood_turnover": 0.70,
        "mortality": 0.005, "fire_mortality": 0.005,
        "froot_leaf": 1.0, "stem_leaf": 2.2,
        "livewood_wood": 0.1, "croot_stem": 0.23,
        "current_growth_prop": 0.5,
        "leaf_cn": 24.0, "leaflitter_cn": 49.0, "froot_cn": 42.0,
        "livewood_cn": 50.0, "deadwood_cn": 442.0,
        "ll_labile": 0.39, "ll_cellulose": 0.44, "ll_lignin": 0.17,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.76, "dw_lignin": 0.24,
        "int_coef": 0.041, "ext_coef": 0.5,
        "lai_ratio": 2.6, "sla": 30.0, "sla_ratio": 2.0,
        "flnr": 0.08, "gl_smax": 0.005, "gl_c": 0.00001, "gl_bl": 0.08,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
    "DBF": {
        "name": "Deciduous Broadleaf Forest",
        "woody": 1, "evergreen": 0, "c3_flag": 1, "phenology_flag": 1,
        "onday": 0, "offday": 0,
        "transfer_pdays": 0.2, "litfall_pdays": 0.2,
        "leaf_turnover": 1.0, "livewood_turnover": 0.70,
        "mortality": 0.005, "fire_mortality": 0.0025,
        "froot_leaf": 1.0, "stem_leaf": 2.2,
        "livewood_wood": 0.1, "croot_stem": 0.23,
        "current_growth_prop": 0.5,
        "leaf_cn": 24.0, "leaflitter_cn": 49.0, "froot_cn": 42.0,
        "livewood_cn": 50.0, "deadwood_cn": 442.0,
        "ll_labile": 0.39, "ll_cellulose": 0.44, "ll_lignin": 0.17,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.76, "dw_lignin": 0.24,
        "int_coef": 0.041, "ext_coef": 0.7,
        "lai_ratio": 2.0, "sla": 30.0, "sla_ratio": 2.0,
        "flnr": 0.08, "gl_smax": 0.005, "gl_c": 0.00001, "gl_bl": 0.01,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
    "SHRUB": {
        "name": "Evergreen Shrub",
        "woody": 1, "evergreen": 1, "c3_flag": 1, "phenology_flag": 1,
        "onday": 0, "offday": 0,
        "transfer_pdays": 0.3, "litfall_pdays": 0.3,
        "leaf_turnover": 0.25, "livewood_turnover": 0.70,
        "mortality": 0.02, "fire_mortality": 0.01,
        "froot_leaf": 1.0, "stem_leaf": 0.22,
        "livewood_wood": 1.0, "croot_stem": 0.3,
        "current_growth_prop": 0.5,
        "leaf_cn": 42.0, "leaflitter_cn": 93.0, "froot_cn": 42.0,
        "livewood_cn": 50.0, "deadwood_cn": 729.0,
        "ll_labile": 0.32, "ll_cellulose": 0.44, "ll_lignin": 0.24,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.76, "dw_lignin": 0.24,
        "int_coef": 0.041, "ext_coef": 0.5,
        "lai_ratio": 2.6, "sla": 12.0, "sla_ratio": 2.0,
        "flnr": 0.04, "gl_smax": 0.003, "gl_c": 0.00001, "gl_bl": 0.08,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
    "C3GRASS": {
        "name": "C3 Grassland",
        "woody": 0, "evergreen": 0, "c3_flag": 1, "phenology_flag": 0,
        "onday": 0, "offday": 364,
        "transfer_pdays": 1.0, "litfall_pdays": 1.0,
        "leaf_turnover": 1.0, "livewood_turnover": 0.0,
        "mortality": 0.1, "fire_mortality": 0.1,
        "froot_leaf": 2.0, "stem_leaf": 0.0,
        "livewood_wood": 0.0, "croot_stem": 0.0,
        "current_growth_prop": 0.5,
        "leaf_cn": 24.0, "leaflitter_cn": 49.0, "froot_cn": 42.0,
        "livewood_cn": 0.0, "deadwood_cn": 0.0,
        "ll_labile": 0.39, "ll_cellulose": 0.44, "ll_lignin": 0.17,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.75, "dw_lignin": 0.25,
        "int_coef": 0.021, "ext_coef": 0.6,
        "lai_ratio": 2.0, "sla": 45.0, "sla_ratio": 2.0,
        "flnr": 0.15, "gl_smax": 0.005, "gl_c": 0.00001, "gl_bl": 0.04,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
    "C4GRASS": {
        "name": "C4 Grassland",
        "woody": 0, "evergreen": 0, "c3_flag": 0, "phenology_flag": 0,
        "onday": 0, "offday": 364,
        "transfer_pdays": 1.0, "litfall_pdays": 1.0,
        "leaf_turnover": 1.0, "livewood_turnover": 0.0,
        "mortality": 0.1, "fire_mortality": 0.1,
        "froot_leaf": 2.0, "stem_leaf": 0.0,
        "livewood_wood": 0.0, "croot_stem": 0.0,
        "current_growth_prop": 0.5,
        "leaf_cn": 24.0, "leaflitter_cn": 49.0, "froot_cn": 42.0,
        "livewood_cn": 0.0, "deadwood_cn": 0.0,
        "ll_labile": 0.39, "ll_cellulose": 0.44, "ll_lignin": 0.17,
        "fr_labile": 0.30, "fr_cellulose": 0.45, "fr_lignin": 0.25,
        "dw_cellulose": 0.75, "dw_lignin": 0.25,
        "int_coef": 0.021, "ext_coef": 0.6,
        "lai_ratio": 2.0, "sla": 45.0, "sla_ratio": 2.0,
        "flnr": 0.15, "gl_smax": 0.005, "gl_c": 0.00001, "gl_bl": 0.04,
        "psi_open": -0.6, "psi_close": -2.3,
        "vpd_open": 930.0, "vpd_close": 4100.0,
    },
}

# AVHRR land cover -> BIOME-BGC PFT mapping
AVHRR_TO_PFT = {
    1: "ENF",       # Evergreen Needleleaf Forest
    2: "EBF",       # Evergreen Broadleaf Forest
    3: "DNF",       # Deciduous Needleleaf Forest
    4: "DBF",       # Deciduous Broadleaf Forest
    5: "DBF",       # Mixed Forest -> DBF (dominant) or ENF by latitude
    6: "SHRUB",     # Woodland -> shrub
    7: "C3GRASS",   # Wooded Grassland -> C3 grass
    8: "SHRUB",     # Closed Shrubland
    9: "SHRUB",     # Open Shrubland
    10: "C3GRASS",  # Grassland -> C3 (>30N) or C4 (<30N) override
    # 11: cropland -> skip (use LDNDC/DSSAT)
    # 12: bare ground -> skip
    # 13: urban -> skip
}


def avhrr_to_pft(avhrr_class: int, latitude: float = 45.0) -> str:
    """
    Map AVHRR land cover class to BIOME-BGC PFT code.

    Parameters
    ----------
    avhrr_class : int
        AVHRR land cover class (1-13).
    latitude : float
        Site latitude for grassland C3/C4 decision.

    Returns
    -------
    str or None
        PFT code (ENF, EBF, DNF, DBF, SHRUB, C3GRASS, C4GRASS) or None.
    """
    if avhrr_class in (11, 12, 13, 14):
        return None  # skip cropland, bare, urban, water
    if avhrr_class == 10:
        return "C3GRASS" if abs(latitude) > 30.0 else "C4GRASS"
    if avhrr_class == 5:
        return "ENF" if abs(latitude) > 50.0 else "DBF"
    return AVHRR_TO_PFT.get(avhrr_class, None)


# ---------------------------------------------------------------------------
# Output variable map (from output_map_init.c)
# Key output indices used in .ini OUTPUT sections
# ---------------------------------------------------------------------------
OUTPUT_VAR_MAP = {
    # meteorology
    0: "metv.prcp", 1: "metv.tmax", 2: "metv.tmin", 3: "metv.tavg",
    4: "metv.tday", 5: "metv.tnight", 6: "metv.tsoil", 7: "metv.vpd",
    8: "metv.swavgfd", 9: "metv.swabs", 15: "metv.par",
    19: "metv.dayl",
    # water state
    20: "ws.soilw", 21: "ws.snoww", 22: "ws.canopyw",
    # water flux
    38: "wf.canopyw_evap", 40: "wf.snoww_subl",
    42: "wf.soilw_evap", 43: "wf.soilw_trans", 44: "wf.soilw_outflow",
    # carbon state
    50: "cs.leafc", 70: "cs.cwdc",
    71: "cs.litr1c", 72: "cs.litr2c", 73: "cs.litr3c", 74: "cs.litr4c",
    75: "cs.soil1c", 76: "cs.soil2c", 77: "cs.soil3c", 78: "cs.soil4c",
    # ecophysiology
    509: "epv.proj_lai", 510: "epv.all_lai",
    515: "epv.psi", 516: "epv.vwc",
    528: "epv.daily_net_nmin",
    545: "epv.ytd_maxplai",
    # photosynthesis
    579: "psn_sun.A", 609: "psn_shade.A",
    # summary
    620: "summary.daily_npp", 621: "summary.daily_nep",
    622: "summary.daily_nee", 623: "summary.daily_gpp",
    624: "summary.daily_mr", 625: "summary.daily_gr",
    626: "summary.daily_hr", 627: "summary.daily_fire",
    636: "summary.vegc", 637: "summary.litrc",
    638: "summary.soilc", 639: "summary.totalc",
    641: "summary.daily_et", 642: "summary.daily_outflow",
    643: "summary.daily_evap", 644: "summary.daily_trans",
    645: "summary.daily_soilw", 646: "summary.daily_snoww",
}

# Standard daily output set for production runs
STANDARD_DAILY_OUTPUT = [
    (20,  "ws.soilw"),
    (21,  "ws.snoww"),
    (509, "epv.proj_lai"),
    (528, "epv.daily_net_nmin"),
    (620, "summary.daily_npp"),
    (621, "summary.daily_nep"),
    (622, "summary.daily_nee"),
    (623, "summary.daily_gpp"),
    (624, "summary.daily_mr"),
    (625, "summary.daily_gr"),
    (626, "summary.daily_hr"),
    (627, "summary.daily_fire"),
    (636, "summary.vegc"),
    (637, "summary.litrc"),
    (638, "summary.soilc"),
    (639, "summary.totalc"),
    (641, "summary.daily_et"),
    (642, "summary.daily_outflow"),
    (644, "summary.daily_trans"),
    (645, "summary.daily_soilw"),
    (646, "summary.daily_snoww"),
    (579, "psn_sun.A"),
    (44,  "wf.soilw_outflow"),
]

STANDARD_ANNUAL_OUTPUT = [
    (545, "annual maximum projected LAI"),
    (636, "vegetation C"),
    (637, "litter C"),
    (638, "soil C"),
    (639, "total C"),
    (307, "soil mineral N"),
]
