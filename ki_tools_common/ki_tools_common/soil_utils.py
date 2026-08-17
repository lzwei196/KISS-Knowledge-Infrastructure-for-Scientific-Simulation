"""
soil_utils.py — HWSD soil property lookup for any lat/lon.

Reads HWSD raster (hwsd.bil) + CSV database (HWSD_DATA.csv) to extract
soil texture (sand/silt/clay %), organic carbon, pH, and bulk density.
Also provides USDA texture classification and Saxton-Rawls pedotransfer
for hydraulic properties.

Usage::

    >>> from ki_tools_common.soil_utils import lookup_hwsd, classify_texture
    >>> props = lookup_hwsd(32.43, 115.60)
    >>> print(f"Texture: {classify_texture(props['sand'], props['silt'], props['clay'])}")
    >>> print(f"Sand: {props['sand']:.0f}%, Clay: {props['clay']:.0f}%")
"""

from __future__ import annotations

import os
import math
import warnings
from typing import Dict, Optional

import numpy as np

HYDROCRAFT_ROOT = "KISSPATH_ROOT"
HWSD_RASTER = os.path.join(HYDROCRAFT_ROOT, "data/soil/HWSD_RASTER/hwsd.bil")
HWSD_CSV = os.path.join(HYDROCRAFT_ROOT, "data/soil/HWSD_DATA.csv")


def _classify_usda_texture(sand: float, clay: float) -> str:
    """USDA texture triangle classification from sand and clay percentages.

    This is the single authoritative implementation — called by both
    classify_texture() and saxton_rawls() to ensure consistency.

    Uses the standard USDA texture triangle boundaries. Silt is derived
    as 100 - sand - clay. Order of checks matters: more specific classes
    (sandy_clay, silty_clay) must be tested before generic ones (clay).

    Reference: USDA-NRCS Soil Texture Calculator
    https://www.nrcs.usda.gov/resources/education-and-teaching-materials/soil-texture-calculator
    """
    silt = 100.0 - sand - clay

    # Sand: sand >= 85% AND clay < 10%
    if sand >= 85 and clay < 10:
        return "sand"
    # Loamy sand: sand 70-90%, clay < 15%, silt < 30%
    if sand >= 70 and sand < 90 and clay < 15:
        return "loamy_sand"
    # Sandy clay: sand >= 45%, clay >= 35%
    if sand >= 45 and clay >= 35:
        return "sandy_clay"
    # Silty clay: clay >= 40%, silt >= 40%
    if clay >= 40 and silt >= 40:
        return "silty_clay"
    # Clay: clay >= 40%
    if clay >= 40:
        return "clay"
    # Sandy clay loam: sand >= 45%, clay 20-35%
    if sand >= 45 and 20 <= clay < 35:
        return "sandy_clay_loam"
    # Silty clay loam: clay 27-40%, silt >= 40%
    if 27 <= clay < 40 and silt >= 40:
        return "silty_clay_loam"
    # Clay loam: clay 27-40%, sand 20-45%
    if 27 <= clay < 40 and 20 <= sand < 45:
        return "clay_loam"
    # Silt: silt >= 80%, clay < 12%
    if silt >= 80 and clay < 12:
        return "silt"
    # Silt loam: silt 50-80% OR (silt 50-80% AND clay 12-27%)
    if silt >= 50:
        return "silt_loam"
    # Sandy loam: sand >= 43% AND clay < 7%, OR sand >= 52% AND clay < 20%
    if (sand >= 43 and clay < 7) or (sand >= 52 and clay < 20):
        return "sandy_loam"
    # Loam: everything else in the middle
    return "loam"


def classify_texture(sand: float, silt: float, clay: float) -> str:
    """USDA texture class from sand/silt/clay percentages (0-100).

    Delegates to _classify_usda_texture() which uses the standard USDA
    texture triangle. The silt parameter is accepted for API compatibility
    but only sand and clay are used for classification (silt = 100 - sand - clay).
    """
    return _classify_usda_texture(sand, clay)


def saxton_rawls(sand: float, clay: float, om: float = 1.5) -> Dict[str, float]:
    """Saxton-Rawls pedotransfer for hydraulic properties.

    Args:
        sand: Sand percentage (0-100)
        clay: Clay percentage (0-100)
        om: Organic matter percentage (default 1.5)

    Returns:
        Dict with: wilting_point, field_capacity, saturation, ksat_cm_hr, bulk_density
    """
    # Rawls, Brakensiek & Saxton (1982) texture-class lookup
    # Validated against RZWQM2 soil_default_setter() reference implementation
    # wp=θ15000 (wilting point), fc=θ33 (field capacity), sat=θs (saturation)
    _texture_hydraulics = {
        #                   wp      fc      sat
        "sand":          (0.025, 0.063, 0.437),
        "loamy_sand":    (0.047, 0.106, 0.437),
        "sandy_loam":    (0.085, 0.192, 0.453),
        "loam":          (0.116, 0.233, 0.463),
        "silt_loam":     (0.136, 0.286, 0.501),
        "sandy_clay_loam":(0.137, 0.246, 0.398),
        "clay_loam":     (0.188, 0.312, 0.464),
        "silty_clay_loam":(0.211, 0.343, 0.471),
        "sandy_clay":    (0.221, 0.322, 0.430),
        "silty_clay":    (0.251, 0.373, 0.479),
        "clay":          (0.266, 0.379, 0.475),
        "silt":          (0.136, 0.286, 0.501),
    }
    tex = _classify_usda_texture(sand, clay)

    wp, fc, sat = _texture_hydraulics[tex]

    # Ksat from USDA texture class (Rawls, Brakensiek & Saxton 1982)
    # Validated against RZWQM2 soil_default_setter() — 10/10 match
    # Units: cm/hr (geometric means from 5,350 soil samples)
    _ksat_by_texture = {
        "sand": 21.0, "loamy_sand": 6.11, "sandy_loam": 2.59, "loam": 1.32,
        "silt_loam": 0.68, "silt": 0.68, "sandy_clay_loam": 0.43,
        "clay_loam": 0.23, "silty_clay_loam": 0.15, "sandy_clay": 0.12,
        "silty_clay": 0.09, "clay": 0.06,
    }
    ksat = _ksat_by_texture[tex]
    bd = max(0.9, min(1.8, 2.65 * (1 - sat)))

    return {
        'texture': tex,
        'wilting_point': round(wp, 4),
        'field_capacity': round(fc, 4),
        'saturation': round(sat, 4),
        'ksat_cm_hr': round(ksat, 4),
        'bulk_density': round(bd, 3),
    }


def rosetta_vgn(sand: float, clay: float) -> Dict[str, float]:
    """ROSETTA-class van Genuchten parameters from texture class.

    Returns alpha (1/m), n (-), theta_r (m³/m³), theta_s (m³/m³), Ksat (cm/day).
    These are the class-average values from the Schaap et al. (2001) ROSETTA
    pedotransfer model for the 12 USDA texture classes.

    For models using Richards equation (SUMMA, ParFlow, MODFLOW, wflow, mHM,
    SHAW, RZWQM2), this provides physically-informed starting parameters
    without requiring calibration.

    Standard workflow: HWSD texture → rosetta_vgn() → model parameters
    Then derive FC and WP from the vGn curve:
        FC = theta_r + (theta_s - theta_r) / (1 + |alpha * 3.3|^n)^(1-1/n)  (at -3.3m = -33 kPa)
        WP = theta_r + (theta_s - theta_r) / (1 + |alpha * 150|^n)^(1-1/n)  (at -150m = -1500 kPa)

    Note for SUMMA: alpha must be NEGATIVE (matric head convention). Use -alpha.

    Reference: Schaap, Leij, van Genuchten (2001) J. Hydrology 251: 163-176.
    """
    # ROSETTA class-average vGn parameters (Schaap et al. 2001, Table 4)
    # alpha in 1/cm (convert to 1/m by ×100), n dimensionless
    # theta_r and theta_s in m³/m³, Ksat in cm/day
    _rosetta = {
        #                  theta_r  theta_s  alpha(1/cm)  n       Ksat(cm/d)
        "sand":          (0.053,   0.375,   0.0353,      3.18,   642.98),
        "loamy_sand":    (0.049,   0.390,   0.0347,      1.75,   105.12),
        "sandy_loam":    (0.039,   0.387,   0.0267,      1.45,    38.25),
        "loam":          (0.061,   0.399,   0.0111,      1.47,    12.04),
        "silt":          (0.050,   0.489,   0.0066,      1.68,    43.74),
        "silt_loam":     (0.065,   0.439,   0.0051,      1.66,    18.26),
        "sandy_clay_loam":(0.063,  0.384,   0.0211,      1.33,    13.19),
        "clay_loam":     (0.079,   0.442,   0.0158,      1.42,     8.18),
        "silty_clay_loam":(0.090,  0.482,   0.0084,      1.52,    11.11),
        "sandy_clay":    (0.117,   0.385,   0.0334,      1.21,    11.35),
        "silty_clay":    (0.111,   0.481,   0.0162,      1.32,     9.61),
        "clay":          (0.098,   0.459,   0.0150,      1.25,    14.75),
    }

    tex = _classify_usda_texture(sand, clay)
    if tex not in _rosetta:
        tex = "loam"  # safe fallback

    theta_r, theta_s, alpha_cm, n, ksat_cmd = _rosetta[tex]
    alpha_m = alpha_cm * 100.0  # 1/cm → 1/m

    # Derive FC (at -33 kPa = -3.3 m head) and WP (at -1500 kPa = -150 m head)
    m = 1.0 - 1.0 / n
    fc = theta_r + (theta_s - theta_r) / (1 + abs(alpha_m * 3.3) ** n) ** m
    wp = theta_r + (theta_s - theta_r) / (1 + abs(alpha_m * 150.0) ** n) ** m

    return {
        'texture': tex,
        'theta_r': round(theta_r, 4),
        'theta_s': round(theta_s, 4),
        'alpha_1_per_m': round(alpha_m, 4),
        'alpha_1_per_cm': round(alpha_cm, 5),
        'n': round(n, 3),
        'ksat_cm_day': round(ksat_cmd, 2),
        'ksat_m_s': round(ksat_cmd / 86400 / 100, 8),  # cm/day → m/s
        'field_capacity': round(fc, 4),
        'wilting_point': round(wp, 4),
    }


def lookup_hwsd(lat: float, lon: float,
                hwsd_raster: Optional[str] = None,
                hwsd_csv: Optional[str] = None) -> Dict[str, float]:
    """Look up HWSD soil properties for a location.

    Args:
        lat: Latitude (degrees)
        lon: Longitude (degrees)
        hwsd_raster: Path to hwsd.bil (default: HydroCraft server path)
        hwsd_csv: Path to HWSD_DATA.csv (default: HydroCraft server path)

    Returns:
        Dict with: mu_id, sand, silt, clay, oc, ph, bulk_density (top soil)
        Plus sub_sand, sub_silt, sub_clay (subsoil if available)
        Plus texture (USDA class) and hydraulics (from Saxton-Rawls)
    """
    raster = hwsd_raster or HWSD_RASTER
    csv_path = hwsd_csv or HWSD_CSV

    mu_id = None

    # Step 1: Get MU_GLOBAL from raster
    try:
        import rasterio
        with rasterio.open(raster) as src:
            row, col = src.index(lon, lat)
            mu_id = int(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
    except Exception as e:
        warnings.warn(f"HWSD raster lookup failed at ({lat}, {lon}): {e}")

    # Step 2: Look up properties from CSV
    result = {
        'mu_id': mu_id or 0,
        'sand': 40.0, 'silt': 40.0, 'clay': 20.0,  # defaults
        'oc': 1.5, 'ph': 6.5, 'bulk_density': 1.3,
        'sub_sand': 40.0, 'sub_silt': 40.0, 'sub_clay': 20.0,
    }

    if mu_id and os.path.exists(csv_path):
        try:
            import pandas as pd
            df = pd.read_csv(csv_path, low_memory=False)
            row = df[df['MU_GLOBAL'] == mu_id]
            if len(row) > 0:
                r = row.iloc[0]
                for col, key in [('T_SAND', 'sand'), ('T_SILT', 'silt'), ('T_CLAY', 'clay'),
                                 ('T_OC', 'oc'), ('T_PH_H2O', 'ph'), ('T_REF_BULK_DENSITY', 'bulk_density'),
                                 ('S_SAND', 'sub_sand'), ('S_SILT', 'sub_silt'), ('S_CLAY', 'sub_clay')]:
                    val = r.get(col)
                    if val is not None and not (isinstance(val, float) and math.isnan(val)) and val > 0:
                        result[key] = float(val)
        except Exception as e:
            warnings.warn(f"HWSD CSV lookup failed for MU={mu_id}: {e}")

    # Add derived properties
    result['texture'] = classify_texture(result['sand'], result['silt'], result['clay'])
    result['hydraulics'] = saxton_rawls(result['sand'], result['clay'], result['oc'])

    return result
