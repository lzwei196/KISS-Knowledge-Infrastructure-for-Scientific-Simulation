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
  - Mollisol BD correction for NE China black soils (黑土)  [OFF by default since 2026-10-18; opt-in flag]
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

    # Mollisol BD correction is OFF by default (since 2026-10-18); turn it on only as a named test:
    python convert_soilgrids_to_sol.py --lat 44.05 --lon 126.05 \\
        --output SOIL.SOL --enable_mollisol_bd_correction

    # Minimum gap between saturation and field capacity (default 0.05, tested on maize only;
    # 0.01 to 0.2 in whole thousandths), or the old files:
    python convert_soilgrids_to_sol.py ... --min_gap 0.05
    python convert_soilgrids_to_sol.py ... --legacy_gap_rule

Minimum gap (since 2026-10): done the paper's way (Saxton & Rawls 2006, p. 1574: "a minimum
difference ... was set to limit the DF value"). Where the density step leaves SSAT - SDUL below
the minimum gap, the density used is lowered until the gap is reached and printed as SBDM;
SSAT = 1 - SBDM/2.65, SDUL from Eq. 9 at that density, SSKS from the final gap, printed with
3 decimals. The old handling (SDUL pulled down to SSAT - 0.005, SSAT clipped to 0.25-0.75,
mapped density printed, SSKS with 2 decimals) is kept as rule="legacy" / --legacy_gap_rule,
off by default, so old files can be reproduced byte for byte.

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

# Empirical BD correction for NE China black soils (黑土). OFF by default since 2026-10-18 (owner decision).
# Origin: the May 2026 NE China SHAW run (outputs/ne_china_shaw_vic_dssat/run_shaw_parallel.py --mollisol_bd)
# used it in the SHAW soil tool vic_to_shaw_soil.py (removed 2026-10-02) to correct HWSD density
# (HWSD ~1.40-1.60 g/cm3 vs ~1.05-1.25 in field measurements; no paper source recorded). The 3 VIC-layer
# factors were copied here and stretched to 6 layers. SoilGrids topsoil density in NE China is already
# ~1.14 (median of the 4,739 NE rice cells), so the HWSD-tuned cut does not carry over, and paddy soils
# are not black-soil uplands. Turn on only as a named sensitivity test (--enable_mollisol_bd_correction).
ENABLE_MOLLISOL_BD_CORRECTION = False

# Mollisol correction parameters (project-specific)
MOLLIC_LAT = (38.0, 54.0)
MOLLIC_LON = (118.0, 135.0)
MOLLIC_BD_THRESHOLD = 1.25              # g/cm³ — only correct cells above this
MOLLIC_BD_SCALE = [0.82, 0.88, 0.94, 0.94, 0.94, 0.94]  # per depth layer

# Nearest-neighbour fallback radius
MAX_NN_DIST_DEG = 0.075
MAX_NN_DIST2    = MAX_NN_DIST_DEG ** 2

# Minimum-gap rule (Saxton & Rawls 2006, SSSAJ 70:1574). Paper: "A large adjustment of density
# could cause Eq. [10] to become negative, thus a minimum difference of 0.5%v was set to limit the
# DF value in these cases." So the paper lowers the density used when SSAT - SDUL gets too small.
# The paper's 0.005 only guards against a negative number. DSSAT maize cuts root uptake when a
# layer is within PORM = 0.05 of saturation, and this KI's validator asks for at least 0.01.
# Default 0.05 (owner decision 2026-10-03), from DSSAT CERES-Maize runs on Route B cells
# (soil_fix_20261003/runs, arms A1 = 0.02 and A2 = 0.05): at 0.05 every DayCent stop went
# and no new crash or crop failure came; at 0.02 the stops went too, but the 3-decimal SSKS
# of a 0.02 gap (about 0.003 cm/h) nearly closed dense layers and failed seasons rose.
# Tested on maize only; for other crops see the doc (Step 10b, "min_gap for other crops").
# Same values and same code as convert_hwsd_to_sol.py (a test checks the two copies agree).
MIN_GAP_DEFAULT  = 0.05
MIN_GAP_FLOOR    = 0.01    # smallest gap the tool accepts (KI validator; DSSAT sets SAT = DUL + 0.01, IPSOIL_Inp.for)
MAX_BD_DROP      = 0.30    # g/cm3: the density used is never more than this below the input density
MIN_BD_USED      = 1.00    # g/cm3: never lowered below this (the paper excluded samples below 1.0 g/cm3,
                           #        p. 1570); an input below 1.0 is never lowered
ON_CAP_DEFAULT   = "lower_sdul"   # cap reached: keep the capped density, lower SDUL (flag "cap_sdul");
                                  # "raise" refuses (ValueError)
PARTICLE_DENSITY = 2.65    # g/cm3 (SOILDYN.for: POROS = 1 - BD/2.65)
SSAT_PRINT_TOL   = 0.0005  # SSAT has 3 printed decimals: compared with the pore space at that precision
GAP_RULES        = ("paper", "legacy")
CAP_RULES        = ("lower_sdul", "raise")


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
        raise ValueError(f"no texture: sand+silt+clay = {total}; no default texture is used")
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


# Properties the writer needs at every depth. A missing one stops the write: no default value,
# no value copied from the topsoil, no invented depth decay (owner rule: no fabricated data).
REQUIRED_PROPS = ("sand", "silt", "clay", "soc", "bdod", "phh2o")


def _missing_soilgrids_values(cell_data: dict) -> List[str]:
    """Return '<prop>_<depth>' keys that are absent, None, NaN, inf, not a number, or negative.

    None of these properties can be negative, so a negative value is a no-data code (SoilGrids
    rasters use -32768) and is reported, not clamped to 0 later."""
    missing = []
    for dk in DEPTH_LAYERS:
        for prop in REQUIRED_PROPS:
            key = f"{prop}_{dk}"
            v = cell_data.get(key)
            try:
                v = float(v)
            except (TypeError, ValueError):
                missing.append(key)
                continue
            if not math.isfinite(v) or v < 0:
                missing.append(key)
    return missing


def _measured(cell_data: dict, key: str) -> float:
    """A value checked by _missing_soilgrids_values(); raises if it is not there."""
    v = float(cell_data[key])
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"SoilGrids value {key} is missing")
    return v


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


def printed_rule_problems(slll: float, sdul: float, ssat: float, sbdm: float,
                          min_gap: float) -> List[str]:
    """Problems with one layer's PRINTED numbers (SLLL, SDUL, SSAT with 3 decimals, SBDM with 2), [] if none.

    Rules (the same in both KI converters and in validate_soil_profile.py):
      1. SLLL < SDUL.
      2. SSAT - SDUL >= min_gap.
      3. pore space of the printed SBDM, 1 - SBDM/2.65 (what DSSAT computes, SOILDYN.for), minus SDUL >= min_gap.
         DSSAT's soil N code divides by this difference; near zero it crashes (DayCent diffusivity).
      4. SSAT at most that pore space, compared at SSAT's printed precision (3 decimals, tolerance 0.0005).
    """
    eps = 1e-9
    out = []
    pore = 1.0 - sbdm / PARTICLE_DENSITY
    if not slll < sdul:
        out.append(f"SLLL {slll:.3f} >= SDUL {sdul:.3f}")
    if ssat - sdul < min_gap - eps:
        out.append(f"SSAT - SDUL = {ssat - sdul:.4f} < {min_gap:.3f}")
    if pore - sdul < min_gap - eps:
        out.append(f"pore space of SBDM {sbdm:.2f} ({pore:.4f}) - SDUL {sdul:.3f} = {pore - sdul:.4f} < {min_gap:.3f}")
    if ssat > pore + SSAT_PRINT_TOL + eps:
        out.append(f"SSAT {ssat:.3f} above the pore space {pore:.4f} of SBDM {sbdm:.2f}")
    return out


def format_ssks(v: Optional[float]) -> str:
    """The 6-character SSKS field.

    DSSAT reads the layer table by header position (READS.for PARSE_HEADERS): under the header '  SSKS' it reads
    only the last 5 characters of the 6-wide field (the field starts one column after the blank that ends 'SRGF').
    So the field must start with a blank: 3 decimals fit below 10 cm/h (' 0.002'); from 10 up, 2 decimals (' 12.35').
    A negative or missing value is written as -99 (DSSAT: no drainage limit)."""
    if v is None or not math.isfinite(v) or v < 0:
        return "   -99"
    s = f"{v:6.3f}" if round(v, 3) < 10.0 else f"{v:6.2f}"
    if len(s) != 6 or s[0] != " ":
        raise ValueError(f"SSKS {v!r} does not fit the 6-character field: {s!r}")
    return s


def _check_hydraulic_consistency(
    hyd: Dict[str, float], sbdm: float,
    lat: float, lon: float, depth_key: str,
    min_gap: float = MIN_GAP_FLOOR,
) -> List[str]:
    """Warn (and return the problems) if the printed numbers break the rules of printed_rule_problems()
    or SSKS is outside [0.001, 63]. The writer refuses to write a layer with a problem (paper rule)."""
    problems = printed_rule_problems(hyd["SLLL"], hyd["SDUL"], hyd["SSAT"], sbdm, min_gap)
    if not (0.001 <= hyd["SSKS"] <= 63.0):
        problems.append(f"SSKS outside DSSAT range [0.001,63]: SSKS={hyd['SSKS']}")
    for p in problems:
        warnings.warn(f"Soil rule broken at ({lat},{lon}) {depth_key}: {p}")
    return problems


def _check_hydraulic_consistency_legacy(
    hyd: Dict[str, float], sbdm: float,
    lat: float, lon: float, depth_key: str
) -> None:
    """The check as it was before 2026-10 (used with rule="legacy" only).
    Warn if SLLL < SDUL < SSAT is violated or SSAT is far from 1−BD/2.65."""
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
                      bd_gcm3: float, *, rule: str = "paper",
                      min_gap: float = MIN_GAP_DEFAULT,
                      max_bd_drop: float = MAX_BD_DROP,
                      min_bd_used: float = MIN_BD_USED,
                      on_cap: str = ON_CAP_DEFAULT) -> Dict[str, float]:
    """
    Saxton & Rawls (2006) SSSA J. 70:1569-1578 — full density-adjusted version.

    Inputs:
        sand    sand content (%)
        clay    clay content (%)
        oc_pct  organic carbon (%) — NOT organic matter, NOT g/kg
        bd_gcm3 bulk density (g/cm³); a value outside 0.5-2.2 (or NaN) is treated as missing and the
                texture-derived normal density is used (rule="paper"; legacy uses it as given)
        rule    "paper" (default): Saxton & Rawls 2006 p. 1574, "limit the DF value". If the printed
                numbers at the input density break a rule of printed_rule_problems() (gap below
                min_gap), the density used is lowered to the largest 2-decimal density at which
                the printed numbers meet every rule (the density at which Eq. 10 equals min_gap,
                rounded down to 2 decimals, give or take one step of 0.01 for rounding; the printed
                numbers decide, as they are what DSSAT reads). SBDM = that density,
                SSAT = 1 - SBDM/2.65 (Eq. 8; at most 0.80, an old bound that acts only below SBDM 0.53); SDUL Eq. 9 at SBDM; SSKS from the final gap.
                Layers whose printed numbers already meet the rules are not changed.
                "legacy": the old function, byte-identical (SSAT = 1 - BD/2.65 clipped to
                0.25-0.75, SDUL pulled down to SSAT - 0.005; no SBDM returned). Only to reproduce
                old files.
        min_gap, max_bd_drop, min_bd_used, on_cap: as in convert_hwsd_to_sol.saxton_rawls
                (defaults 0.05, 0.30 g/cm³, 1.00 g/cm³, "lower_sdul").

    Returns (rule="paper"):
        SLLL  wilting point (cm³/cm³)
        SDUL  field capacity, density-adjusted (cm³/cm³)
        SSAT  saturation = pore space of SBDM (at most 0.80)
        SSKS  saturated hydraulic conductivity (cm/hr)
        SBDM  the density used (g/cm³) — print this, not the mapped density
        gap_rule, min_gap, bd_input, bd_source, bd_drop, sdul_cut: what the rule did
                (see convert_hwsd_to_sol.saxton_rawls)
    """
    if not (0 <= sand <= 100):
        raise ValueError(f"sand out of range: {sand}")
    if not (0 <= clay <= 100):
        raise ValueError(f"clay out of range: {clay}")
    if rule == "legacy":
        return _saxton_rawls_2006_legacy(sand, clay, oc_pct, bd_gcm3)
    if rule != "paper":
        raise ValueError(f"rule must be one of {GAP_RULES}: {rule!r}")
    if not (0 <= oc_pct <= 20):
        warnings.warn(f"OC% looks unusual: {oc_pct}")
    if bd_gcm3 is None or not (0.5 <= bd_gcm3 <= 2.2):
        warnings.warn(f"BD looks unusual: {bd_gcm3} (normal density used)")
    return _saxton_rawls_paper(sand, clay, oc_pct, bd_gcm3, min_gap, max_bd_drop, min_bd_used, on_cap)


def _floor2(v: float) -> float:
    """Round down to 2 decimals (float32 inputs such as 1.1299999952 count as 1.13)."""
    return math.floor(round(v * 100.0, 4)) / 100.0


def _ceil2(v: float) -> float:
    """Round up to 2 decimals (float32 inputs such as 1.1300000048 count as 1.13)."""
    return math.ceil(round(v * 100.0, 4)) / 100.0


def _floor3(v: float) -> float:
    """Round down to 3 decimals (with the same float guard)."""
    return math.floor(round(v * 1000.0, 4)) / 1000.0


def _check_rule_args(min_gap, max_bd_drop, min_bd_used, on_cap) -> None:
    if not (isinstance(min_gap, (int, float)) and math.isfinite(min_gap)
            and MIN_GAP_FLOOR - 1e-12 <= min_gap <= 0.2):
        raise ValueError(f"min_gap must be a number from {MIN_GAP_FLOOR} to 0.2: {min_gap!r}")
    if abs(min_gap * 1000.0 - round(min_gap * 1000.0)) > 1e-6:
        raise ValueError(f"min_gap must be whole thousandths (the printed precision of SSAT and SDUL): {min_gap!r}")
    if not (math.isfinite(max_bd_drop) and 0.0 <= max_bd_drop <= 1.0):
        raise ValueError(f"max_bd_drop must be from 0 to 1 g/cm3: {max_bd_drop!r}")
    if not (math.isfinite(min_bd_used) and 0.5 <= min_bd_used <= 2.2):
        raise ValueError(f"min_bd_used must be from 0.5 to 2.2 g/cm3: {min_bd_used!r}")
    if on_cap not in CAP_RULES:
        raise ValueError(f"on_cap must be one of {CAP_RULES}: {on_cap!r}")


def _saxton_rawls_paper(sand, clay, oc, bd, min_gap, max_bd_drop, min_bd_used, on_cap) -> Dict[str, float]:
    """The paper rule (see saxton_rawls_2006). The same code is in convert_hwsd_to_sol.py; a test checks they agree."""
    _check_rule_args(min_gap, max_bd_drop, min_bd_used, on_cap)
    S  = sand / 100.0
    C  = clay / 100.0
    OM = oc   * 1.724          # OC → OM via van Bemmelen factor

    # θ1500 (wilting point, −1500 kPa) [Eq. 1]
    theta1500t = (-0.024*S + 0.487*C + 0.006*OM
                  + 0.005*S*OM - 0.013*C*OM
                  + 0.068*S*C + 0.031)
    theta1500  = theta1500t + (0.14 * theta1500t - 0.02)
    # θ33 (field capacity, −33 kPa, normal density) [Eq. 2]
    theta33t = (-0.251*S + 0.195*C + 0.011*OM
                + 0.006*S*OM - 0.027*C*OM
                + 0.452*S*C + 0.299)
    theta33  = theta33t + (1.283 * theta33t**2 - 0.374 * theta33t - 0.015)
    # θS - θ33 [Eq. 3] and normal-density saturation θS [Eq. 5]
    thetaS33t = (0.278*S + 0.034*C + 0.022*OM
                 - 0.018*S*OM - 0.027*C*OM
                 - 0.584*S*C + 0.078)
    thetaS33  = thetaS33t + (0.636 * thetaS33t - 0.107)
    thetaS0   = theta33 + thetaS33 - 0.097*S + 0.043

    bd_normal = PARTICLE_DENSITY * (1.0 - thetaS0)            # Eq. 6
    if bd is not None and math.isfinite(bd) and 0.5 <= bd <= 2.2:
        bd_in, bd_source = float(bd), "mapped"
    else:
        bd_in, bd_source = min(max(bd_normal, 0.5), 2.2), "normal"

    slll0 = max(0.005, theta1500)                              # same bounds and order as the HWSD tool
    slll  = min(max(slll0, 0.005), 0.60)

    def layer_at(bd_used):
        """Unrounded SDUL and SSAT when the density used is bd_used."""
        x    = 1.0 - bd_used / PARTICLE_DENSITY                # Eq. 8
        sdul = theta33 - 0.2 * (thetaS0 - x)                   # Eq. 9
        sdul = max(sdul, slll0 + 0.005)
        sdul = min(max(sdul, slll + 0.005), 0.65)
        ssat = min(x, 0.80)
        return sdul, ssat

    def meets(sdul, ssat, sbdm):
        return not printed_rule_problems(round(slll, 3), round(sdul, 3), round(ssat, 3), sbdm, min_gap)

    sdul, ssat = layer_at(bd_in)
    sbdm = round(bd_in, 2)
    gap_rule, sdul_cut = "unchanged", 0.0
    if not meets(sdul, ssat, sbdm):
        x_t  = (min_gap + theta33 - 0.2 * thetaS0) / 0.8       # Eq. 10 = min_gap, solved for Eq. 8
        bd_t = PARTICLE_DENSITY * (1.0 - x_t)
        gap_rule = "paper_df" if bd_t < bd_in else "print_fix"
        # lowest density allowed: the cap, in whole hundredths; the 2-decimal rounding step below the
        # input is always allowed (an input such as 0.9676 may be printed as 0.96)
        bound  = max(bd_in - max_bd_drop, min_bd_used)
        lowest = min(_ceil2(min(bound, bd_in)), _floor2(bd_in))
        # the largest 2-decimal density whose printed numbers meet the rules: search down from the input
        # density in steps of 0.01. It ends at bd_t rounded down to 2 decimals, give or take one step for
        # rounding, unless an SDUL bound acts (checked on all real layers in the tests)
        cand = _floor2(bd_in)
        found = False
        while cand >= lowest - 1e-9:
            sdul, ssat = layer_at(cand)
            if meets(sdul, ssat, cand):
                found = True
                break
            cand = round(cand - 0.01, 2)
        if found:
            sbdm = cand
        else:
            # The cap stops the density drop before the gap is met.
            sbdm = lowest
            if on_cap == "raise":
                raise ValueError(
                    f"min gap {min_gap} needs the density lowered from {bd_in:.3f} below the cap "
                    f"(max drop {max_bd_drop}, min density {min_bd_used}): sand={sand} clay={clay} oc={oc}")
            sdul_eq9, ssat = layer_at(sbdm)
            pore = 1.0 - sbdm / PARTICLE_DENSITY
            sdul = min(_floor3(min(round(ssat, 3), pore) - min_gap), round(sdul_eq9, 3))
            if sdul - round(slll, 3) < 0.005 - 1e-9:
                raise ValueError(
                    f"min gap {min_gap} cannot be met: at the capped density {sbdm:.2f} SDUL would be {sdul:.3f}, "
                    f"within 0.005 of SLLL {slll:.3f}: sand={sand} clay={clay} oc={oc} bd={bd_in:.3f}")
            sdul_cut = round(sdul_eq9, 3) - sdul
            gap_rule = "cap_sdul"
        problems = printed_rule_problems(round(slll, 3), round(sdul, 3), round(ssat, 3), sbdm, min_gap)
        if problems:                                           # cannot happen; fail closed if it does
            raise ValueError(f"paper rule left broken printed numbers: {problems}")

    # λ (pore-size index, Eq. 15 and 18) and Ksat (Eq. 16) from the final SLLL/SDUL/SSAT
    lam  = (math.log(sdul) - math.log(slll)) / (math.log(1500.0) - math.log(33.0))
    ksat = 1930.0 * (ssat - sdul) ** (3.0 - lam) / 10.0       # cm/hr
    ksat = min(max(ksat, 0.001), 63.0)

    return {
        "SLLL": round(slll, 3),
        "SDUL": round(sdul, 3),
        "SSAT": round(ssat, 3),
        "SSKS": round(ksat, 3),
        "SBDM": round(sbdm, 2),
        "gap_rule":  gap_rule,
        "min_gap":   float(min_gap),
        "bd_input":  round(bd_in, 4),
        "bd_source": bd_source,
        "bd_drop":   0.0 if gap_rule == "unchanged" else round(bd_in - sbdm, 4),
        "sdul_cut":  round(sdul_cut, 3),
    }


def _saxton_rawls_2006_legacy(sand: float, clay: float, oc_pct: float,
                              bd_gcm3: float) -> Dict[str, float]:
    """
    The function as it was before 2026-10 (unchanged code; saxton_rawls_2006(rule="legacy")).
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
                         enabled: bool = False) -> List[float]:
    """
    Optional empirical BD correction for NE China black soils (黑土), tuned on HWSD density in the
    May 2026 NE China SHAW run (see ENABLE_MOLLISOL_BD_CORRECTION). Off unless enabled.
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
                        output_path: str, *, rule: str = "paper",
                        min_gap: float = MIN_GAP_DEFAULT,
                        max_bd_drop: float = MAX_BD_DROP,
                        min_bd_used: float = MIN_BD_USED,
                        on_cap: str = ON_CAP_DEFAULT) -> bool:
    """
    Build a 6-layer DSSAT SOIL.SOL at output_path from SoilGrids data.
    Returns True on success, False if no SoilGrids data is available.
    rule / min_gap / max_bd_drop / min_bd_used / on_cap: see saxton_rawls_2006(). With rule="paper"
    (default) SBDM is the density used, SSKS is printed with 3 decimals (format_ssks), and a layer whose
    printed numbers break a rule is refused (ValueError) before anything is written; rule="legacy"
    writes the old file byte for byte.
    """
    legacy = (rule == "legacy")
    cell_data = lookup_soilgrids(lat, lon)
    if cell_data is None:
        warnings.warn(f"No SoilGrids data found for ({lat}, {lon})")
        return False

    _validate_cell_units(cell_data, lat, lon)

    # Every property at every depth must be measured; a gap stops here (ValueError), before
    # anything is written. No default texture/carbon/density/pH and no depth decay from the topsoil.
    missing = _missing_soilgrids_values(cell_data)
    if missing:
        raise ValueError(f"SoilGrids record for ({lat}, {lon}) (matched cell {cell_data.get('lat')}, "
                         f"{cell_data.get('lon')}) has no value for {missing}; no default is used and "
                         f"nothing is written")

    sand_t = _measured(cell_data, "sand_0-5cm")
    clay_t = _measured(cell_data, "clay_0-5cm")
    silt_t = _measured(cell_data, "silt_0-5cm")
    soc_t  = _measured(cell_data, "soc_0-5cm")
    sand_t, silt_t, clay_t = _normalize_texture(sand_t, silt_t, clay_t)

    tex  = classify_texture(sand_t, silt_t, clay_t)
    slpf = 1.00 if USE_NEUTRAL_SLPF else _slpf_from_soc(soc_t)

    bdod_raw  = [_measured(cell_data, f"bdod_{dk}") for dk in DEPTH_LAYERS]
    bdod_vals = _mollisol_correct_bd(bdod_raw, lat, lon,
                                     enabled=ENABLE_MOLLISOL_BD_CORRECTION)
    srgf_vals = [1.00, 0.85, 0.60, 0.35, 0.15, 0.05]

    title = ("*SOILS: SoilGrids-derived soil profile (Saxton-Rawls 2006 PTF)" if legacy else
             f"*SOILS: SoilGrids-derived soil profile (Saxton-Rawls 2006 PTF); DF limit, min gap {min_gap:.3f}")
    lines = [
        title + "\n\n",
        f"*{soil_id:<10s} SoilGrids {tex:5s}    {200:5d}  SoilGrids 0.1deg\n",
        f"@SITE        COUNTRY          LAT     LONG SCS FAMILY\n",
        f" SoilGrids   Global       {lat:7.3f} {lon:8.3f} {tex}\n",
        f"@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE\n",
        f"    BN  0.13   6.0  0.60  73.0  1.00 {slpf:5.2f} SA001 SA001 SA001\n",
        f"@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC\n",
    ]

    for i, (depth_key, slb, srgf) in enumerate(
            zip(DEPTH_LAYERS, DEPTH_BOTTOM, srgf_vals)):
        sand = _measured(cell_data, f"sand_{depth_key}")
        clay = _measured(cell_data, f"clay_{depth_key}")
        silt = _measured(cell_data, f"silt_{depth_key}")
        soc  = _measured(cell_data, f"soc_{depth_key}")
        bdod = float(bdod_vals[i])
        ph   = _measured(cell_data, f"phh2o_{depth_key}")
        # Coarse fragments (cfvo) are not in the current CSVs. Paper rule: an absent value is
        # written as -99 (DSSAT "missing"; SOILDYN.for:547 then uses 0 and warns), so the file
        # does not claim a measured 0 %. Legacy keeps the old 0.0 for byte-identical files.
        cfvo = _get_float(cell_data, f"cfvo_{depth_key}", -99.0)
        cfvo_missing = (cfvo < 0)          # absent, or a negative no-data code
        if cfvo_missing and legacy:
            cfvo, cfvo_missing = 0.0, False

        # Hard bounds before PTF
        sand = min(max(sand, 0.0), 100.0)
        clay = min(max(clay, 0.0), 100.0)
        silt = min(max(silt, 0.0), 100.0)
        soc  = min(max(soc,  0.0), 300.0)
        bdod = min(max(bdod, 0.5),   2.2)
        ph   = min(max(ph,   2.5),  10.5)
        if not cfvo_missing:
            cfvo = min(max(cfvo, 0.0),  90.0)

        sand, silt, clay = _normalize_texture(sand, silt, clay)

        oc_pct = max(0.01, soc / 10.0)        # g/kg → OC%
        sloc   = round(oc_pct, 3)
        slni   = round(max(0.001, sloc / 10.0), 3)   # C:N ≈ 10
        hyd = saxton_rawls_2006(sand, clay, oc_pct, bdod, rule=rule, min_gap=min_gap,
                                max_bd_drop=max_bd_drop, min_bd_used=min_bd_used, on_cap=on_cap)
        if legacy:
            sbdm = round(bdod, 2)
            _check_hydraulic_consistency_legacy(hyd, sbdm, lat, lon, depth_key)
            ssks_txt = f"{hyd['SSKS']:6.2f}"
        else:
            sbdm = hyd["SBDM"]              # the density used (lowered where the gap needed it)
            if _check_hydraulic_consistency(hyd, sbdm, lat, lon, depth_key, min_gap):
                raise ValueError(f"SoilGrids layer {depth_key} at ({lat}, {lon}) breaks the soil rules; "
                                 f"nothing written")
            ssks_txt = format_ssks(hyd["SSKS"])

        layer = "Ap" if i == 0 else ("B" if i < 3 else "C")
        # DSSAT reads the soil layer table FIXED-WIDTH (each column is exactly 6
        # chars, right-justified — matching the @ header). Earlier formatting used
        # explicit separator spaces plus width specifiers (e.g. SSKS as ' {:6.3f}')
        # which produced 7-char fields for SSKS<10, shifting every later column and
        # making INSOIL mis-read garbage -> SIGFPE crash. Emit strict 6-char cols.
        # SSKS: 3 decimals (format_ssks) so values below 0.005 cm/h are not printed as 0.00,
        # which DSSAT reads as "no drainage limit"; legacy keeps the old 2 decimals.
        lines.append(
            f"{slb:6d}{layer:>6s}"
            f"{hyd['SLLL']:6.3f}{hyd['SDUL']:6.3f}{hyd['SSAT']:6.3f}"
            f"{srgf:6.3f}{ssks_txt}{sbdm:6.2f}"
            f"{sloc:6.2f}{clay:6.1f}{silt:6.1f}{'   -99' if cfvo_missing else f'{cfvo:6.1f}'}"
            f"{slni:6.3f}{ph:6.1f}   -99   -99\n"
        )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as fh:
        fh.writelines(lines)
    return True


# ── Self-test ─────────────────────────────────────────────────────────────────

def _test_saxton_rawls() -> None:
    """Smoke-test: printed-number rules and SSKS range for 5 textures and a dense clay subsoil
    (paper rule, default min gap), and the old order check with rule="legacy"."""
    cases = [
        ("Sand",       89,  5, 0.3, 1.55),
        ("Sandy loam", 60, 10, 1.0, 1.50),
        ("Loam",       40, 20, 1.5, 1.40),
        ("Clay loam",  30, 30, 2.0, 1.35),
        ("Clay",       20, 45, 2.0, 1.30),
        ("Dense clay", 20, 45, 0.5, 1.75),
    ]
    print(f"{'Texture':15s} {'SLLL':>6s} {'SDUL':>6s} {'SSAT':>6s} {'SSKS':>8s} {'SBDM':>5s}  rule")
    print("-" * 64)
    for name, sand, clay, oc, bd in cases:
        h = saxton_rawls_2006(sand, clay, oc, bd)
        print(f"{name:15s} {h['SLLL']:6.3f} {h['SDUL']:6.3f} "
              f"{h['SSAT']:6.3f} {h['SSKS']:8.3f} {h['SBDM']:5.2f}  {h['gap_rule']}")
        assert not printed_rule_problems(h["SLLL"], h["SDUL"], h["SSAT"], h["SBDM"], MIN_GAP_DEFAULT), \
            f"Printed-number rule broken for {name}"
        assert 0.001 <= h["SSKS"] <= 63.0, f"SSKS out of range for {name}"
        old = saxton_rawls_2006(sand, clay, oc, bd, rule="legacy")
        assert old["SLLL"] < old["SDUL"] < old["SSAT"], f"Order violated for {name} (legacy)"
    assert saxton_rawls_2006(20, 45, 0.5, 1.75)["gap_rule"] == "paper_df", "dense clay should be changed"
    assert format_ssks(0.002) == " 0.002" and format_ssks(12.345) == " 12.35", "format_ssks"

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
    try:
        _normalize_texture(0, 0, 0)
        raise AssertionError("normalize_texture accepted zero texture")
    except ValueError:
        pass

    # A record with gaps must be reported, not filled
    gap = {f"{p}_{dk}": 1.0 for p in REQUIRED_PROPS for dk in DEPTH_LAYERS}
    gap["soc_30-60cm"] = float("nan"); del gap["phh2o_0-5cm"]; gap["clay_60-100cm"] = -3276.8
    assert sorted(_missing_soilgrids_values(gap)) == ["clay_60-100cm", "phh2o_0-5cm", "soc_30-60cm"], "missing check"

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
    ap.add_argument("--enable_mollisol_bd_correction", action="store_true", default=False,
                    help="Turn ON the HWSD-tuned NE China Mollisol BD cut (off by default; sensitivity tests only)")
    ap.add_argument("--disable_mollisol_bd_correction", action="store_true", default=False,
                    help="Kept for old callers; the correction is already off by default")
    ap.add_argument("--min_gap", type=float, default=MIN_GAP_DEFAULT,
                    help=f"Minimum SSAT - SDUL and pore space - SDUL (default {MIN_GAP_DEFAULT}, tested on maize "
                         f"only; {MIN_GAP_FLOOR} to 0.2 in whole thousandths); the density used is lowered to reach "
                         f"it (S&R 2006 p. 1574)")
    ap.add_argument("--legacy_gap_rule", action="store_true", default=False,
                    help="Reproduce the old files: SDUL pulled to SSAT - 0.005, mapped density printed, "
                         "SSKS 2 decimals")
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
    if args.enable_mollisol_bd_correction and args.disable_mollisol_bd_correction:
        ap.error("--enable_mollisol_bd_correction and --disable_mollisol_bd_correction contradict each other")
    ENABLE_MOLLISOL_BD_CORRECTION = bool(args.enable_mollisol_bd_correction)

    soil_id = args.soil_id
    if soil_id is None:
        lo = int(abs(args.lon) * 10) % 10000
        la = int(abs(args.lat) * 10) % 10000
        soil_id = f"SGS{lo:04d}{la:04d}"
    soil_id = _sanitize_soil_id(soil_id)

    try:
        ok = write_soilgrids_sol(args.lat, args.lon, soil_id, args.output,
                                 rule="legacy" if args.legacy_gap_rule else "paper",
                                 min_gap=args.min_gap)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
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
