#!/usr/bin/env python3
"""
convert_soilgrids_to_sol.py — Convert SoilGrids 0.1° data to DSSAT SOIL.SOL format.

Generates a 6-layer DSSAT soil profile using SoilGrids v2 properties
(bdod, clay, sand, silt, soc, phh2o at 0–5, 5–15, 15–30, 30–60, 60–100, 100–200 cm).
Hydraulic properties are derived using the Saxton & Rawls (2006) PTF.

Advantages over convert_hwsd_to_sol.py:
  - 6 depth layers instead of 2 (resolves subsoil texture and organic carbon)
  - Bulk density directly from SoilGrids bdod (not estimated from saturation)
  - Depth-varying SOC and pH per layer
  - Saxton & Rawls 2006 PTF (density-adjusted saturation)
  - Mollisol BD correction for NE China black soils (黑土)  [optional flag]
  - SLPF = 1.00 baseline (SOC-derived SLPF available as sensitivity option)

Data sources (automatically selected by region):
  China subset:    KISSPATH_DATA/soilgrids/soilgrids_cold_china_01deg.csv
  Global fallback: KISSPATH_DATA/soilgrids_global/soilgrids_global_01deg.csv

Both CSVs are in conventional units:
  bdod  = g/cm³    sand/silt/clay = %    soc = g/kg    phh2o = pH

Usage:
    python convert_soilgrids_to_sol.py \\
        --lat 44.05 --lon 126.05 \\
        --output SOIL.SOL \\
        --soil_id SGS1260044

    # Self-test (no lat/lon required):
    python convert_soilgrids_to_sol.py --test

    # Disable Mollisol correction (outside NE China):
    python convert_soilgrids_to_sol.py --lat 30.0 --lon 120.0 \\
        --output SOIL.SOL --disable_mollisol_bd_correction

Reference:
    Saxton & Rawls (2006) Soil Water Characteristic Estimates by Texture and
    Organic Matter for Hydrologic Solutions. SSSA J. 70:1569-1578.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import warnings
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── Data paths ────────────────────────────────────────────────────────────────
SG_CHINA_CSV  = "KISSPATH_DATA/soilgrids/soilgrids_cold_china_01deg.csv"
SG_GLOBAL_CSV = "KISSPATH_DATA/soilgrids_global/soilgrids_global_01deg.csv"

DEPTH_LAYERS = ['0-5cm', '5-15cm', '15-30cm', '30-60cm', '60-100cm', '100-200cm']
DEPTH_BOTTOM = [5, 15, 30, 60, 100, 200]    # DSSAT SLB (cm)

# ── Global behaviour flags ────────────────────────────────────────────────────
# Both local CSVs are already in conventional units (g/cm³, %, g/kg, pH).
# Set True only if you supply a raw SoilGrids CSV (integer-scaled mapped units).
RAW_SOILGRIDS_UNITS = False

# SLPF = 1.00 is the safe baseline for climate/water sensitivity analysis.
# It prevents yield patterns from tracking soil carbon rather than water stress.
# Enable SOC-derived SLPF only as a named sensitivity test.
USE_NEUTRAL_SLPF = True

# Empirical BD correction for NE China black soils (黑土). Validated against
# the SHAW global cold-China pipeline. Disable for non-NE-China simulations.
ENABLE_MOLLISOL_BD_CORRECTION = True

# Mollisol correction parameters (project-specific)
MOLLIC_LAT = (38.0, 54.0)
MOLLIC_LON = (118.0, 135.0)
MOLLIC_BD_THRESHOLD = 1.25              # g/cm³ — only correct cells above this
MOLLIC_BD_SCALE = [0.82, 0.88, 0.94, 0.94, 0.94, 0.94]  # per depth layer

# Nearest-neighbour fallback radius
MAX_NN_DIST_DEG = 0.075
MAX_NN_DIST2    = MAX_NN_DIST_DEG ** 2


# ── Unit conversion (raw SoilGrids CSVs only) ─────────────────────────────────

_RAW_CONV = {
    "bdod":     100.0,   # cg/cm³   → g/cm³
    "sand":      10.0,   # g/kg     → %
    "silt":      10.0,
    "clay":      10.0,
    "soc":       10.0,   # dg/kg    → g/kg
    "phh2o":     10.0,   # pH×10    → pH
    "cfvo":      10.0,
    "nitrogen": 100.0,
    "cec":       10.0,
}

def _apply_unit_conversion(df: pd.DataFrame, raw: bool) -> pd.DataFrame:
    """Divide raw SoilGrids mapped values by their scale factors if raw=True."""
    if not raw:
        return df
    df = df.copy()
    df["value"] = df.apply(
        lambda r: r["value"] / _RAW_CONV.get(str(r["property"]).lower(), 1.0),
        axis=1,
    )
    return df


# ── Safe numeric helpers ──────────────────────────────────────────────────────

def _get_float(cell_data: dict, key: str, default: float) -> float:
    """
    Get a numeric value from cell_data, replacing None / NaN / inf with default.

    After pivot_table, a column can exist but contain NaN for a specific cell.
    dict.get(key, default) does NOT fall back to default in that case — it
    returns the NaN. This function handles that correctly.
    """
    value = cell_data.get(key, default)
    if value is None:
        return float(default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(value) or math.isinf(value):
        return float(default)
    return value


def _normalize_texture(sand: float, silt: float,
                        clay: float) -> Tuple[float, float, float]:
    """
    Normalize sand/silt/clay to sum to 100 when the total is moderately off.
    Leaves values unchanged if already within 95–105 (rounding within tolerance).
    """
    total = sand + silt + clay
    if total <= 0:
        return 40.0, 40.0, 20.0
    if 95.0 <= total <= 105.0:
        return sand, silt, clay
    factor = 100.0 / total
    return sand * factor, silt * factor, clay * factor


def _sanitize_soil_id(soil_id: str) -> str:
    """Return a DSSAT-safe 10-character uppercase alphanumeric soil ID.

    DSSAT matches the FileX FIELDS soil ID against the .SOL profile name over a
    FIXED 10-char field. Soil IDs shorter than ~8 chars break that match and the
    soil arrays are left uninitialised -> SIGFPE in INSOIL (verified 2026-06-08).
    So zero-pad short IDs to the full 10-char width rather than emit a short ID.
    """
    clean = "".join(ch for ch in soil_id.upper() if ch.isalnum())
    return (clean or "SGS0000000").ljust(10, "0")[:10]


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_cell_units(cell_data: dict, lat: float, lon: float) -> None:
    """
    Raise ValueError if SoilGrids values appear to be unconverted raw units.
    Catches the most common mistake: forgetting RAW_SOILGRIDS_UNITS=True.
    """
    issues = []
    for dk in DEPTH_LAYERS:
        sand = _get_float(cell_data, f"sand_{dk}",  -1)
        clay = _get_float(cell_data, f"clay_{dk}",  -1)
        silt = _get_float(cell_data, f"silt_{dk}",  -1)
        soc  = _get_float(cell_data, f"soc_{dk}",   -1)
        bdod = _get_float(cell_data, f"bdod_{dk}",  -1)
        ph   = _get_float(cell_data, f"phh2o_{dk}", -1)

        if sand >= 0 and not (0 <= sand <= 100):
            issues.append(f"sand_{dk}={sand:.1f} outside 0–100 %")
        if clay >= 0 and not (0 <= clay <= 100):
            issues.append(f"clay_{dk}={clay:.1f} outside 0–100 %")
        if silt >= 0 and not (0 <= silt <= 100):
            issues.append(f"silt_{dk}={silt:.1f} outside 0–100 %")
        if sand >= 0 and clay >= 0 and silt >= 0:
            total = sand + clay + silt
            if not (85 <= total <= 115):
                issues.append(f"texture sum at {dk}={total:.1f}; expected ~100")
        if soc  >= 0 and not (0 <= soc  <= 300):
            issues.append(f"soc_{dk}={soc:.1f} g/kg looks suspicious")
        if bdod >= 0 and not (0.5 <= bdod <= 2.2):
            issues.append(f"bdod_{dk}={bdod:.2f} g/cm³ outside 0.5–2.2")
        if ph   >= 0 and not (2.5 <= ph   <= 10.5):
            issues.append(f"phh2o_{dk}={ph:.1f} outside 2.5–10.5")

    if issues:
        raise ValueError(
            f"SoilGrids unit check failed at ({lat}, {lon}) — "
            f"possible raw-unit conversion problem:\n" + "\n".join(issues)
        )


def _check_hydraulic_consistency(
    hyd: Dict[str, float], sbdm: float,
    lat: float, lon: float, depth_key: str
) -> None:
    """Warn if SLLL < SDUL < SSAT is violated or SSAT is far from 1−BD/2.65."""
    if not (hyd["SLLL"] < hyd["SDUL"] < hyd["SSAT"]):
        warnings.warn(
            f"Hydraulic ordering problem at ({lat},{lon}) {depth_key}: "
            f"SLLL={hyd['SLLL']} SDUL={hyd['SDUL']} SSAT={hyd['SSAT']}"
        )
    porosity = 1.0 - sbdm / 2.65
    if abs(hyd["SSAT"] - porosity) > 0.05:
        warnings.warn(
            f"SSAT–SBDM inconsistency at ({lat},{lon}) {depth_key}: "
            f"SSAT={hyd['SSAT']:.3f}, 1-BD/2.65={porosity:.3f}, SBDM={sbdm:.2f}"
        )
    if not (0.001 <= hyd["SSKS"] <= 63.0):
        warnings.warn(
            f"SSKS outside DSSAT range [0.001,63] at "
            f"({lat},{lon}) {depth_key}: SSKS={hyd['SSKS']}"
        )


# ── Pedotransfer functions ────────────────────────────────────────────────────

def saxton_rawls_2006(sand: float, clay: float, oc_pct: float,
                      bd_gcm3: float) -> Dict[str, float]:
    """
    Saxton & Rawls (2006) SSSA J. 70:1569-1578 — full density-adjusted version.

    Inputs:
        sand    sand content (%)
        clay    clay content (%)
        oc_pct  organic carbon (%) — NOT organic matter, NOT g/kg
        bd_gcm3 bulk density (g/cm³)

    Returns:
        SLLL  wilting point (cm³/cm³)
        SDUL  field capacity, density-adjusted (cm³/cm³)
        SSAT  density-adjusted saturation, primarily 1–BD/2.65,
              with DSSAT-safe bounds and hydraulic-ordering protection
        SSKS  saturated hydraulic conductivity (cm/hr)
    """
    if not (0 <= sand <= 100):
        raise ValueError(f"sand out of range: {sand}")
    if not (0 <= clay <= 100):
        raise ValueError(f"clay out of range: {clay}")
    if not (0 <= oc_pct <= 20):
        warnings.warn(f"OC% looks unusual: {oc_pct}")
    if not (0.5 <= bd_gcm3 <= 2.2):
        warnings.warn(f"BD looks unusual: {bd_gcm3}")

    S  = sand / 100.0
    C  = clay / 100.0
    OM = oc_pct * 1.724   # OC → OM via van Bemmelen factor

    # θ1500 (wilting point, −1500 kPa)
    th1500t = (-0.024*S + 0.487*C + 0.006*OM + 0.005*S*OM
               - 0.013*C*OM + 0.068*S*C + 0.031)
    th1500  = th1500t + (0.14*th1500t - 0.02)

    # θ33 (field capacity, −33 kPa, normal density)
    th33t = (-0.251*S + 0.195*C + 0.011*OM + 0.006*S*OM
             - 0.027*C*OM + 0.452*S*C + 0.299)
    th33  = th33t + (1.283*th33t**2 - 0.374*th33t - 0.015)

    # θS,0 (texture-derived saturation)
    ths33t = (0.278*S + 0.034*C + 0.022*OM
              - 0.018*S*OM - 0.027*C*OM - 0.584*S*C + 0.078)
    ths33  = ths33t + (0.636*ths33t - 0.107)
    ths0   = th33 + ths33 - 0.097*S + 0.043

    # θS,DF = 1 − BD/2.65 (density-adjusted saturation — key S&R 2006 improvement)
    ths_df = min(max(1.0 - bd_gcm3 / 2.65, 0.25), 0.75)

    # θ33,DF (density-adjusted field capacity)
    th33_df = th33 - 0.2 * (ths0 - ths_df)

    # Enforce SLLL < SDUL < SSAT with minimal margins
    th1500  = min(max(th1500,  0.005), 0.60)
    th33_df = min(max(th33_df, th1500 + 0.005), ths_df - 0.005)
    ths_df  = max(ths_df, th33_df + 0.005)

    # Pore-size distribution index
    lam = (math.log(th33_df) - math.log(th1500)) / (math.log(1500.0) - math.log(33.0))

    # Ksat: S&R returns mm/h; DSSAT SSKS is cm/h
    ksat_cmh = 1930.0 * max(1e-6, ths_df - th33_df) ** (3.0 - lam) / 10.0
    ksat_cmh = min(max(ksat_cmh, 0.001), 63.0)

    return {
        "SLLL": round(th1500,   3),
        "SDUL": round(th33_df,  3),
        "SSAT": round(ths_df,   3),
        "SSKS": round(ksat_cmh, 3),
    }


def classify_texture(sand: float, silt: float, clay: float) -> str:
    """Approximate USDA texture class label for DSSAT soil profile metadata."""
    if sand >= 85:                 return "Sa"
    if sand >= 70 and clay < 15:  return "LoSa"
    if clay >= 40:                 return "C"
    if clay >= 27:
        return "SaCl" if sand >= 20 else ("SiCl" if silt >= 40 else "ClLo")
    if silt >= 50:                 return "SiLo" if clay >= 12 else "Si"
    if sand >= 52:                 return "SaLo"
    return "Lo"


def _mollisol_correct_bd(bdod_vals: List[float], lat: float, lon: float,
                         enabled: bool = True) -> List[float]:
    """
    Optional empirical BD correction for NE China black soils (黑土).
    Project-specific; validated against SHAW global cold-China pipeline.
    Disable for simulations outside the NE China Mollisol zone.
    """
    if not enabled:
        return bdod_vals
    if not (MOLLIC_LAT[0] <= lat <= MOLLIC_LAT[1] and
            MOLLIC_LON[0] <= lon <= MOLLIC_LON[1]):
        return bdod_vals
    return [
        bd * MOLLIC_BD_SCALE[i] if bd > MOLLIC_BD_THRESHOLD else bd
        for i, bd in enumerate(bdod_vals)
    ]


def _slpf_from_soc(soc_gpkg: float) -> float:
    """
    Heuristic SLPF from topsoil SOC — NE China Mollisol sensitivity tests only.
    For baseline simulations use USE_NEUTRAL_SLPF = True (SLPF = 1.00).
    """
    return round(min(1.0, max(0.75, 0.75 + (soc_gpkg / 10.0) * 0.025)), 3)


# ── SoilGrids data loading ────────────────────────────────────────────────────

_SG_CACHE: dict = {}

def _load_soilgrids(csv_path: str) -> pd.DataFrame:
    """Load and pivot SoilGrids CSV (in-memory cache after first load)."""
    cache_key = (csv_path, RAW_SOILGRIDS_UNITS)
    if cache_key in _SG_CACHE:
        return _SG_CACHE[cache_key]

    df = pd.read_csv(csv_path)
    required = {"lat", "lon", "property", "depth", "value"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"SoilGrids CSV missing columns: {missing}")

    df["property"] = df["property"].astype(str).str.lower()
    df["depth"]    = df["depth"].astype(str)
    df = _apply_unit_conversion(df, raw=RAW_SOILGRIDS_UNITS)

    df["col"] = df["property"] + "_" + df["depth"]
    wide = (df.pivot_table(index=["lat", "lon"], columns="col",
                           values="value", aggfunc="mean")
              .reset_index())
    wide["lat_r"] = wide["lat"].round(2)
    wide["lon_r"] = wide["lon"].round(2)

    _SG_CACHE[cache_key] = wide
    return wide


def lookup_soilgrids(lat: float, lon: float) -> Optional[dict]:
    """
    Return SoilGrids property dict for (lat, lon).

    Search order: China CSV (if in domain) → global CSV.
    Matching: exact 0.01° rounded key → nearest within 0.075°.
    Returns None if no match found in either dataset.
    """
    def _try_csv(csv_path: str) -> Optional[dict]:
        if not os.path.exists(csv_path):
            warnings.warn(f"SoilGrids CSV not found: {csv_path}")
            return None
        wide = _load_soilgrids(csv_path)
        key_lat, key_lon = round(lat, 2), round(lon, 2)
        hits = wide[(wide["lat_r"] == key_lat) & (wide["lon_r"] == key_lon)]
        if not hits.empty:
            return hits.iloc[0].to_dict()
        dists = (wide["lat"] - lat)**2 + (wide["lon"] - lon)**2
        if len(dists) > 0 and dists.min() <= MAX_NN_DIST2:
            return wide.loc[dists.idxmin()].to_dict()
        return None

    if 30 <= lat <= 55 and 70 <= lon <= 135:
        result = _try_csv(SG_CHINA_CSV)
        if result is not None:
            return result
    return _try_csv(SG_GLOBAL_CSV)


# ── SOL file writer ───────────────────────────────────────────────────────────

def write_soilgrids_sol(lat: float, lon: float, soil_id: str,
                        output_path: str) -> bool:
    """
    Build a 6-layer DSSAT SOIL.SOL at output_path from SoilGrids data.
    Returns True on success, False if no SoilGrids data is available.
    """
    cell_data = lookup_soilgrids(lat, lon)
    if cell_data is None:
        warnings.warn(f"No SoilGrids data found for ({lat}, {lon})")
        return False

    _validate_cell_units(cell_data, lat, lon)

    # Topsoil reference values (used as depth-decay fallbacks)
    sand_t = _get_float(cell_data, "sand_0-5cm", 40.0)
    clay_t = _get_float(cell_data, "clay_0-5cm", 20.0)
    silt_t = _get_float(cell_data, "silt_0-5cm", 40.0)
    soc_t  = _get_float(cell_data, "soc_0-5cm",  15.0)
    sand_t, silt_t, clay_t = _normalize_texture(sand_t, silt_t, clay_t)

    tex  = classify_texture(sand_t, silt_t, clay_t)
    slpf = 1.00 if USE_NEUTRAL_SLPF else _slpf_from_soc(soc_t)

    bdod_raw  = [_get_float(cell_data, f"bdod_{dk}", 1.4) for dk in DEPTH_LAYERS]
    bdod_vals = _mollisol_correct_bd(bdod_raw, lat, lon,
                                     enabled=ENABLE_MOLLISOL_BD_CORRECTION)
    srgf_vals = [1.00, 0.85, 0.60, 0.35, 0.15, 0.05]

    lines = [
        "*SOILS: SoilGrids-derived soil profile (Saxton-Rawls 2006 PTF)\n\n",
        f"*{soil_id:<10s} SoilGrids {tex:5s}    {200:5d}  SoilGrids 0.1deg\n",
        f"@SITE        COUNTRY          LAT     LONG SCS FAMILY\n",
        f" SoilGrids   Global       {lat:7.3f} {lon:8.3f} {tex}\n",
        f"@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE\n",
        f"    BN  0.13   6.0  0.60  73.0  1.00 {slpf:5.2f} SA001 SA001 SA001\n",
        f"@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC\n",
    ]

    for i, (depth_key, slb, srgf) in enumerate(
            zip(DEPTH_LAYERS, DEPTH_BOTTOM, srgf_vals)):
        sand = _get_float(cell_data, f"sand_{depth_key}", sand_t)
        clay = _get_float(cell_data, f"clay_{depth_key}", clay_t)
        silt = _get_float(cell_data, f"silt_{depth_key}", silt_t)
        soc  = _get_float(cell_data, f"soc_{depth_key}",  soc_t * (0.5 ** i))
        bdod = float(bdod_vals[i])
        ph   = _get_float(cell_data, f"phh2o_{depth_key}", 6.5)
        cfvo = _get_float(cell_data, f"cfvo_{depth_key}",  0.0)  # not in current CSVs

        # Hard bounds before PTF
        sand = min(max(sand, 0.0), 100.0)
        clay = min(max(clay, 0.0), 100.0)
        silt = min(max(silt, 0.0), 100.0)
        soc  = min(max(soc,  0.0), 300.0)
        bdod = min(max(bdod, 0.5),   2.2)
        ph   = min(max(ph,   2.5),  10.5)
        cfvo = min(max(cfvo, 0.0),  90.0)

        sand, silt, clay = _normalize_texture(sand, silt, clay)

        oc_pct = max(0.01, soc / 10.0)        # g/kg → OC%
        sloc   = round(oc_pct, 3)
        slni   = round(max(0.001, sloc / 10.0), 3)   # C:N ≈ 10
        sbdm   = round(bdod, 2)

        hyd = saxton_rawls_2006(sand, clay, oc_pct, bdod)
        _check_hydraulic_consistency(hyd, sbdm, lat, lon, depth_key)

        layer = "Ap" if i == 0 else ("B" if i < 3 else "C")
        # DSSAT reads the soil layer table FIXED-WIDTH (each column is exactly 6
        # chars, right-justified — matching the @ header). Earlier formatting used
        # explicit separator spaces plus width specifiers (e.g. SSKS as ' {:6.3f}')
        # which produced 7-char fields for SSKS<10, shifting every later column and
        # making INSOIL mis-read garbage -> SIGFPE crash. Emit strict 6-char cols.
        lines.append(
            f"{slb:6d}{layer:>6s}"
            f"{hyd['SLLL']:6.3f}{hyd['SDUL']:6.3f}{hyd['SSAT']:6.3f}"
            f"{srgf:6.3f}{hyd['SSKS']:6.2f}{sbdm:6.2f}"
            f"{sloc:6.2f}{clay:6.1f}{silt:6.1f}{cfvo:6.1f}"
            f"{slni:6.3f}{ph:6.1f}   -99   -99\n"
        )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as fh:
        fh.writelines(lines)
    return True


# ── Self-test ─────────────────────────────────────────────────────────────────

def _test_saxton_rawls() -> None:
    """Smoke-test: verify SLLL < SDUL < SSAT and SSKS in range for 5 textures."""
    cases = [
        ("Sand",       89,  5, 0.3, 1.55),
        ("Sandy loam", 60, 10, 1.0, 1.50),
        ("Loam",       40, 20, 1.5, 1.40),
        ("Clay loam",  30, 30, 2.0, 1.35),
        ("Clay",       20, 45, 2.0, 1.30),
    ]
    print(f"{'Texture':15s} {'SLLL':>6s} {'SDUL':>6s} {'SSAT':>6s} {'SSKS':>8s}")
    print("-" * 50)
    for name, sand, clay, oc, bd in cases:
        h = saxton_rawls_2006(sand, clay, oc, bd)
        print(f"{name:15s} {h['SLLL']:6.3f} {h['SDUL']:6.3f} "
              f"{h['SSAT']:6.3f} {h['SSKS']:8.3f}")
        assert h["SLLL"] < h["SDUL"] < h["SSAT"], f"Order violated for {name}"
        assert 0.001 <= h["SSKS"] <= 63.0, f"SSKS out of range for {name}"

    # Test _get_float NaN handling
    d = {"k": float("nan"), "j": None}
    assert _get_float(d, "k", 99.0) == 99.0, "_get_float NaN failed"
    assert _get_float(d, "j", 88.0) == 88.0, "_get_float None failed"
    assert _get_float(d, "missing", 77.0) == 77.0, "_get_float missing key failed"

    # Test texture normalization (values outside 95-105 tolerance should normalize)
    s, si, c = _normalize_texture(40, 40, 30)   # total=110, should normalize
    assert abs(s + si + c - 100.0) < 0.01, "normalize_texture failed"
    s2, si2, c2 = _normalize_texture(34, 44, 24)  # total=102, within tolerance, unchanged
    assert s2 == 34 and si2 == 44 and c2 == 24, "normalize_texture changed in-tolerance values"

    print("All self-tests passed.\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # lat/lon/output are default=None so --test works without them
    ap.add_argument("--lat",     type=float, default=None,
                    help="Latitude (decimal degrees)")
    ap.add_argument("--lon",     type=float, default=None,
                    help="Longitude (decimal degrees)")
    ap.add_argument("--output",  type=str,   default=None,
                    help="Output SOL file path")
    ap.add_argument("--soil_id", type=str,   default=None,
                    help="DSSAT soil ID (10-char, auto-generated if omitted)")
    ap.add_argument("--raw_soilgrids_units", action="store_true", default=False,
                    help="CSV uses raw SoilGrids integer-scaled units")
    ap.add_argument("--soc_slpf", action="store_true", default=False,
                    help="Use SOC-derived SLPF heuristic instead of neutral 1.00")
    ap.add_argument("--disable_mollisol_bd_correction", action="store_true", default=False,
                    help="Disable empirical NE China Mollisol BD correction")
    ap.add_argument("--test", action="store_true", default=False,
                    help="Run self-tests and exit (no lat/lon/output required)")
    args = ap.parse_args()

    if args.test:
        _test_saxton_rawls()
        sys.exit(0)

    if args.lat is None or args.lon is None or args.output is None:
        ap.error("--lat, --lon, and --output are required unless --test is used")

    # Apply CLI overrides to globals
    global RAW_SOILGRIDS_UNITS, USE_NEUTRAL_SLPF, ENABLE_MOLLISOL_BD_CORRECTION
    if args.raw_soilgrids_units:
        RAW_SOILGRIDS_UNITS = True
    if args.soc_slpf:
        USE_NEUTRAL_SLPF = False
    if args.disable_mollisol_bd_correction:
        ENABLE_MOLLISOL_BD_CORRECTION = False

    soil_id = args.soil_id
    if soil_id is None:
        lo = int(abs(args.lon) * 10) % 10000
        la = int(abs(args.lat) * 10) % 10000
        soil_id = f"SGS{lo:04d}{la:04d}"
    soil_id = _sanitize_soil_id(soil_id)

    ok = write_soilgrids_sol(args.lat, args.lon, soil_id, args.output)
    if ok:
        print(f"Written: {args.output}  (soil_id={soil_id})")
        cell = lookup_soilgrids(args.lat, args.lon)
        if cell:
            print(f"  Topsoil: sand={cell.get('sand_0-5cm')}%  "
                  f"clay={cell.get('clay_0-5cm')}%  "
                  f"soc={cell.get('soc_0-5cm')} g/kg  "
                  f"pH={cell.get('phh2o_0-5cm')}  "
                  f"bdod={cell.get('bdod_0-5cm')} g/cm³")
    else:
        print(f"ERROR: no SoilGrids data for ({args.lat}, {args.lon})",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
