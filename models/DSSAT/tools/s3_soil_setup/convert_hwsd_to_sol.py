#!/usr/bin/env python3
"""
convert_hwsd_to_sol.py — Convert HWSD soil data to DSSAT SOIL.SOL format.

Reads HWSD raster + CSV database to extract soil properties for a location,
then generates a DSSAT-compatible SOIL.SOL file with 2 layers (0-30 cm topsoil
and 30-200 cm subsoil; HWSD subsoil is 30-100 cm extended to 200 cm for DSSAT).

Corrections applied (vs original version):
  1. HWSD T_OC / S_OC are organic carbon %; S&R-2006 needs OM % → OM = OC × 1.724
  2. HWSD T_REF_BULK_DENSITY / S_REF_BULK_DENSITY (kg/dm³ ≡ g/cm³) are used
     directly in S&R density adjustment rather than recomputing BD from texture
  3. Dominant HWSD component selected by max SHARE (not always iloc[0])
  4. Separate T_PH_H2O / S_PH_H2O used per layer
  5. Minimum gap between saturation and field capacity done the paper's way
     (Saxton & Rawls 2006, p. 1574: "a minimum difference ... was set to limit the
     DF value"): where the density step leaves SSAT - SDUL below the minimum gap,
     the density used is lowered until the gap is reached and that density is
     printed as SBDM; SSAT = 1 - SBDM/2.65, SDUL from Eq. 9 at that density, SSKS
     from the final gap (Eq. 16), printed with 3 decimals. The old handling (SSAT
     raised to SDUL + 0.005 with the density kept, SSKS printed with 2 decimals)
     stays reachable as rule="legacy" / --legacy_gap_rule, off by default, so old
     files can be reproduced byte for byte. See saxton_rawls().

Usage:
    python convert_hwsd_to_sol.py \
        --lat 32.43 --lon 115.60 \
        --output SOIL.SOL \
        --soil_id WJBA000001
    # minimum gap 0.05 by default (tested on maize only); --min_gap to change it
    # (whole thousandths, 0.01 to 0.2); --legacy_gap_rule for old files
"""

import argparse
import os
import math
import numpy as np
import pandas as pd

HYDROCRAFT   = "KISSPATH_ROOT"
HWSD_RASTER  = os.path.join(HYDROCRAFT, "data/soil/HWSD_RASTER/hwsd.bil")
HWSD_CSV     = os.path.join(HYDROCRAFT, "data/soil/HWSD_DATA.csv")


# ── Minimum-gap rule (Saxton & Rawls 2006, SSSAJ 70:1574) ──────────────────
# Paper: "A large adjustment of density could cause Eq. [10] to become negative,
# thus a minimum difference of 0.5%v was set to limit the DF value in these cases."
# So the paper lowers the density used (DF) when the gap SSAT - SDUL gets too small.
# The paper's 0.005 only guards against a negative number. DSSAT maize cuts root
# uptake when a layer is within PORM = 0.05 of saturation (MZCER048.SPE, ROOTWU.for),
# and this KI's validator asks for a gap of at least 0.01.
# Default 0.05 (owner decision 2026-10-03), from DSSAT CERES-Maize runs on Route B cells
# (soil_fix_20261003/runs, arms A1 = 0.02 and A2 = 0.05): at 0.05 every DayCent stop went
# and no new crash or crop failure came; at 0.02 the stops went too, but the 3-decimal SSKS
# of a 0.02 gap (about 0.003 cm/h) nearly closed dense layers and failed seasons rose.
# Tested on maize only; for other crops see the doc (Step 10b, "min_gap for other crops").
MIN_GAP_DEFAULT  = 0.05
MIN_GAP_FLOOR    = 0.01    # smallest gap the tool accepts (KI validator; DSSAT sets SAT = DUL + 0.01, IPSOIL_Inp.for)
MAX_BD_DROP      = 0.30    # g/cm3: the density used is never more than this below the input density
MIN_BD_USED      = 1.00    # g/cm3: the density used is never lowered below this (the paper excluded
                           #        samples below 1.0 g/cm3, p. 1570); an input below 1.0 is never lowered
ON_CAP_DEFAULT   = "lower_sdul"   # when the cap stops the density drop: keep the capped density and lower
                                  # SDUL to meet the gap (flagged "cap_sdul"); "raise" refuses (ValueError)
PARTICLE_DENSITY = 2.65    # g/cm3, the paper's and DSSAT's value (SOILDYN.for: POROS = 1 - BD/2.65)
SSAT_PRINT_TOL   = 0.0005  # SSAT is printed with 3 decimals, so it is compared with the pore space at that precision
GAP_RULES        = ("paper", "legacy")
CAP_RULES        = ("lower_sdul", "raise")


# ── helpers ────────────────────────────────────────────────────────────────

def safe_float(value, default):
    """Convert HWSD value to float, handling NaN and HWSD missing-data codes."""
    try:
        v = float(value)
        if not np.isfinite(v) or v in (-9999, -999, -99):
            return default
        return v
    except Exception:
        return default


def classify_texture(sand, silt, clay):
    """USDA texture classification from sand/silt/clay percentages."""
    if sand >= 85:
        return "Sa"
    elif sand >= 70 and clay < 15:
        return "LoSa"
    elif clay >= 40:
        return "C"
    elif clay >= 27:
        if sand >= 20:
            return "SaCl"
        elif silt >= 40:
            return "SiCl"
        else:
            return "ClLo"
    elif silt >= 50:
        if clay >= 12:
            return "SiLo"
        else:
            return "Si"
    elif sand >= 52:
        return "SaLo"
    else:
        return "Lo"


def printed_rule_problems(slll, sdul, ssat, sbdm, min_gap):
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


def format_ssks(v):
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


def _floor2(v):
    """Round down to 2 decimals (float32 inputs such as 1.1299999952 count as 1.13)."""
    return math.floor(round(v * 100.0, 4)) / 100.0


def _ceil2(v):
    """Round up to 2 decimals (float32 inputs such as 1.1300000048 count as 1.13)."""
    return math.ceil(round(v * 100.0, 4)) / 100.0


def _floor3(v):
    """Round down to 3 decimals (with the same float guard)."""
    return math.floor(round(v * 1000.0, 4)) / 1000.0


# ── Saxton-Rawls 2006 PTF ──────────────────────────────────────────────────

def saxton_rawls(sand, clay, oc=1.0, bd=None, *, rule="paper", min_gap=MIN_GAP_DEFAULT,
                 max_bd_drop=MAX_BD_DROP, min_bd_used=MIN_BD_USED, on_cap=ON_CAP_DEFAULT):
    """
    Saxton & Rawls (2006) PTF for DSSAT SOIL.SOL.

    Reference: Saxton & Rawls, SSSAJ 70(5):1569-1578, 2006.

    Inputs
    ------
    sand : sand content, %, 0-100
    clay : clay content, %, 0-100
    oc   : organic carbon, % (from HWSD T_OC or S_OC)
           → converted internally to OM via OM = OC × 1.724
    bd   : optional measured bulk density, g/cm³
           (HWSD T_REF_BULK_DENSITY / S_REF_BULK_DENSITY in kg/dm³ = g/cm³).
           If provided and valid (0.5-2.2), used for density adjustment; otherwise the
           texture-derived normal density is used (DF = 1).
    rule : "paper" (default) or "legacy".
           paper  — Saxton & Rawls 2006 p. 1574, "limit the DF value": if the printed numbers at the
                    input density break a rule of printed_rule_problems() (gap below min_gap), the
                    density used is lowered to the largest 2-decimal density at which the printed
                    numbers meet every rule (the density at which Eq. 10 equals min_gap, rounded
                    down to 2 decimals, give or take one step of 0.01 for rounding; the printed
                    numbers decide, as they are what DSSAT reads). SBDM = that density,
                    SSAT = 1 - SBDM/2.65 (Eq. 8; at most 0.80, an old bound that acts only below SBDM 0.53); SDUL Eq. 9 at SBDM; SSKS from the final gap.
                    Layers whose printed numbers already meet the rules are not changed.
           legacy — the old handling, byte-identical to the tool before 2026-10: SSAT raised to
                    SDUL + 0.005 with the density kept. Only to reproduce old files.
    min_gap     : minimum SSAT - SDUL and pore space - SDUL, cm³/cm³ (paper rule only); >= 0.01,
                  whole thousandths. Default 0.05 (MIN_GAP_DEFAULT; tested on maize only).
    max_bd_drop : largest drop of the density used below the input density, g/cm³ (default 0.30).
    min_bd_used : the density used is never lowered below this, g/cm³ (default 1.00).
    on_cap      : when max_bd_drop / min_bd_used stop the drop before the gap is met:
                  "lower_sdul" (default) keeps the capped density and lowers SDUL to the largest
                  printed value that meets the rules (flagged gap_rule="cap_sdul"; refuses with
                  ValueError if SDUL would then come within 0.005 of SLLL);
                  "raise" refuses (ValueError).

    DSSAT outputs
    -------------
    SLLL : lower limit (wilting point),       cm³/cm³
    SDUL : drained upper limit (field cap.),  cm³/cm³
    SSAT : saturation,                        cm³/cm³
    SSKS : sat. hydraulic conductivity,       cm/hr
           (S&R gives Ks in mm/hr → ÷ 10 for DSSAT)
    SBDM : bulk density (the density used),   g/cm³

    What the paper rule did (paper rule only; the legacy dict has the five keys above only)
    -----------------------------------------------------------------------------------------
    gap_rule  : "unchanged"  the input density met every rule;
                "paper_df"   the Eq. 10 gap at the input density was below min_gap: density lowered;
                "print_fix"  the Eq. 10 gap was enough but the printed (rounded) numbers broke a rule:
                             density lowered by the rounding step;
                "cap_sdul"   the cap stopped the drop: density at the cap, SDUL lowered (see sdul_cut).
    min_gap   : the minimum gap used.
    bd_input  : the density before the rule (mapped, or the normal density), g/cm³.
    bd_source : "mapped" or "normal" (no valid input density).
    bd_drop   : bd_input - SBDM for a changed layer, else 0.0.
    sdul_cut  : SDUL from Eq. 9 at SBDM minus the SDUL written (cap_sdul only), else 0.0.
    """
    if rule == "legacy":
        return _saxton_rawls_legacy(sand, clay, oc=oc, bd=bd)
    if rule != "paper":
        raise ValueError(f"rule must be one of {GAP_RULES}: {rule!r}")
    return _saxton_rawls_paper(sand, clay, oc, bd, min_gap, max_bd_drop, min_bd_used, on_cap)


def _check_rule_args(min_gap, max_bd_drop, min_bd_used, on_cap):
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


def _saxton_rawls_paper(sand, clay, oc, bd, min_gap, max_bd_drop, min_bd_used, on_cap):
    """The paper rule (see saxton_rawls). The same code is in convert_soilgrids_to_sol.py; a test checks they agree."""
    _check_rule_args(min_gap, max_bd_drop, min_bd_used, on_cap)
    S  = sand / 100.0          # decimal fraction
    C  = clay / 100.0          # decimal fraction
    OM = oc   * 1.724          # OC % → OM % for S&R equations

    # θ_1500 wilting point [S&R 2006, Eq. 1]
    theta1500t = (-0.024*S + 0.487*C + 0.006*OM
                  + 0.005*S*OM - 0.013*C*OM
                  + 0.068*S*C + 0.031)
    theta1500  = theta1500t + (0.14 * theta1500t - 0.02)
    # θ_33 field capacity at normal density [Eq. 2]
    theta33t = (-0.251*S + 0.195*C + 0.011*OM
                + 0.006*S*OM - 0.027*C*OM
                + 0.452*S*C + 0.299)
    theta33  = theta33t + (1.283 * theta33t**2 - 0.374 * theta33t - 0.015)
    # θ_S - θ_33 [Eq. 3] and normal-density saturation θ_S [Eq. 5]
    thetaS33t = (0.278*S + 0.034*C + 0.022*OM
                 - 0.018*S*OM - 0.027*C*OM
                 - 0.584*S*C + 0.078)
    thetaS33  = thetaS33t + (0.636 * thetaS33t - 0.107)
    thetaS0   = theta33 + thetaS33 - 0.097*S + 0.043

    bd_normal = PARTICLE_DENSITY * (1.0 - thetaS0)            # Eq. 6
    if bd is not None and np.isfinite(bd) and 0.5 <= bd <= 2.2:
        bd_in, bd_source = float(bd), "mapped"
    else:
        bd_in, bd_source = min(max(bd_normal, 0.5), 2.2), "normal"

    slll0 = max(0.005, theta1500)                              # same bounds and order as the legacy tool
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


def _saxton_rawls_legacy(sand, clay, oc=1.0, bd=None):
    """The tool's function as it was before 2026-10 (unchanged code). Pins SSAT - SDUL at 0.005 by
    raising SSAT, keeps the density; kept only to reproduce old files (saxton_rawls(rule="legacy"))."""
    S  = sand / 100.0          # decimal fraction
    C  = clay / 100.0          # decimal fraction
    OM = oc   * 1.724          # OC % → OM % for S&R equations

    # ── θ_1500 wilting point [S&R 2006, Eqs 1-2] ──────────────────────
    theta1500t = (-0.024*S + 0.487*C + 0.006*OM
                  + 0.005*S*OM - 0.013*C*OM
                  + 0.068*S*C + 0.031)
    theta1500  = theta1500t + (0.14 * theta1500t - 0.02)

    # ── θ_33 field capacity before density adjustment [Eqs 3-4] ────────
    theta33t = (-0.251*S + 0.195*C + 0.011*OM
                + 0.006*S*OM - 0.027*C*OM
                + 0.452*S*C + 0.299)
    theta33  = theta33t + (1.283 * theta33t**2 - 0.374 * theta33t - 0.015)

    # ── θ_S - θ_33 and texture-based normal-density saturation [Eqs 5-7]
    thetaS33t = (0.278*S + 0.034*C + 0.022*OM
                 - 0.018*S*OM - 0.027*C*OM
                 - 0.584*S*C + 0.078)
    thetaS33  = thetaS33t + (0.636 * thetaS33t - 0.107)
    thetaS0   = theta33 + thetaS33 - 0.097*S + 0.043   # texture-based θ_S

    # ── density adjustment ──────────────────────────────────────────────
    bd_normal = 2.65 * (1.0 - thetaS0)   # normal-density BD implied by texture
    if bd is not None and np.isfinite(bd) and 0.5 <= bd <= 2.2:
        bd_use = bd
        ssat   = 1.0 - bd_use / 2.65
    else:
        bd_use = bd_normal
        ssat   = thetaS0

    # density-adjusted SDUL
    sdul = theta33 - 0.2 * (thetaS0 - ssat)

    # ── DSSAT ordering and sanity bounds (applied BEFORE Ksat) ──────────
    # Ksat is computed last so λ and Ks are consistent with the final
    # SLLL/SDUL/SSAT values actually written to the .SOL file.
    slll = max(0.005, theta1500)
    sdul = max(sdul,  slll + 0.005)
    ssat = max(ssat,  sdul + 0.005)
    slll = min(max(slll, 0.005), 0.60)
    sdul = min(max(sdul, slll + 0.005), 0.65)
    ssat = min(max(ssat, sdul + 0.005), 0.80)
    bd_use = min(max(bd_use, 0.5), 2.2)

    # ── λ (pore-size index) and Ksat [S&R 2006, Eqs 8-9] ────────────────
    # λ = (log SDUL − log SLLL) / (log 1500 − log 33)
    # Ks [mm/hr] = 1930 × (SSAT − SDUL)^(3 − λ) → ÷10 for DSSAT cm/hr
    # Uses final clipped SLLL/SDUL/SSAT so SSKS is internally consistent.
    lam  = (math.log(sdul) - math.log(slll)) / (math.log(1500.0) - math.log(33.0))
    ksat = 1930.0 * (ssat - sdul) ** (3.0 - lam) / 10.0   # cm/hr
    ksat = min(max(ksat, 0.001), 63.0)

    return {
        "SLLL": round(slll,   3),
        "SDUL": round(sdul,   3),
        "SSAT": round(ssat,   3),
        "SSKS": round(ksat,   3),
        "SBDM": round(bd_use, 2),
    }


# HWSD missing-data codes (the old safe_float() also treated these as "no value").
HWSD_MISSING_CODES = (-9999.0, -999.0, -99.0)

# Plausible ranges for the values write_sol() uses. A value outside them (for example a
# missing-data code that was not caught upstream) stops the write; nothing is replaced.
HWSD_VALUE_RANGES = {
    "T_SAND": (0.0, 100.0), "T_SILT": (0.0, 100.0), "T_CLAY": (0.0, 100.0),
    "S_SAND": (0.0, 100.0), "S_SILT": (0.0, 100.0), "S_CLAY": (0.0, 100.0),
    "T_OC": (0.0, 100.0), "S_OC": (0.0, 100.0),
    "T_PH_H2O": (0.0, 14.0), "S_PH_H2O": (0.0, 14.0),
}


def check_hwsd_values(soil_props, where=""):
    """Stop (ValueError) if a required HWSD value is missing, a missing-data code, or out of range.

    Bulk density may be NaN (not measured, see lookup_hwsd); if given it must be > 0 and
    not a missing-data code.
    """
    import math
    bad = []
    for col, (lo, hi) in HWSD_VALUE_RANGES.items():
        v = soil_props.get(col)
        try:
            v = float(v)
        except (TypeError, ValueError):
            bad.append(f"{col}={soil_props.get(col)!r} (no value)")
            continue
        if not math.isfinite(v) or v in HWSD_MISSING_CODES:
            bad.append(f"{col}={v:g} (missing-data code / no value)")
        elif not (lo <= v <= hi):
            bad.append(f"{col}={v:g} (outside {lo:g}-{hi:g})")
    for col in ("T_REF_BULK_DENSITY", "S_REF_BULK_DENSITY"):
        if col not in soil_props:
            bad.append(f"{col} (key missing; use NaN for not measured)")
            continue
        try:
            v = float(soil_props[col])
        except (TypeError, ValueError):
            bad.append(f"{col}={soil_props[col]!r} (not a number)")
            continue
        if math.isnan(v):
            continue
        if v in HWSD_MISSING_CODES or not (v > 0) or not math.isfinite(v):
            bad.append(f"{col}={v:g} (missing-data code or not > 0; use NaN for not measured)")
    try:
        if not bad and float(soil_props["T_OC"]) <= 0:
            bad.append("T_OC=0 (topsoil organic carbon is needed to scale SLNI by depth)")
    except (TypeError, ValueError):
        pass
    if bad:
        raise ValueError(f"HWSD soil values{where} are missing or invalid: {bad}; "
                         f"no default is used and no file is written")


# ── HWSD lookup ────────────────────────────────────────────────────────────

def lookup_hwsd(lat, lon):
    """
    Look up HWSD soil properties for a grid cell.

    Selects the dominant soil component (highest SHARE; ties keep CSV order)
    when the mapping unit has several records. Any failure STOPS: raster read
    error, no map unit (sea/water), missing table, no row, or a missing
    texture / OC / pH value in the chosen row (topsoil T_* or subsoil S_*).
    No loam default and no subsoil value derived from the topsoil.
    Bulk density may be missing (NaN): saxton_rawls() then uses the
    Saxton-Rawls 2006 normal density from texture and OM (the method's own
    density, Eq. 5-6), as before.
    """
    import math
    try:
        import rasterio
        with rasterio.open(HWSD_RASTER) as src:
            row, col = src.index(lon, lat)
            if not (0 <= row < src.height and 0 <= col < src.width):
                raise ValueError(f"Point ({lat},{lon}) outside HWSD raster extent.")
            mu_id = int(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
    except Exception as e:
        raise RuntimeError(f"HWSD raster lookup failed at ({lat}, {lon}): {e}") from e
    if mu_id <= 0:
        raise ValueError(f"HWSD has no soil map unit at ({lat}, {lon}) (MU_GLOBAL={mu_id}); "
                         f"no default soil is used")
    if not os.path.exists(HWSD_CSV):
        raise FileNotFoundError(f"HWSD table not found: {HWSD_CSV}")
    df = pd.read_csv(HWSD_CSV, low_memory=False)
    rows = df[df["MU_GLOBAL"] == mu_id].copy()
    if len(rows) == 0:
        raise ValueError(f"HWSD map unit {mu_id} at ({lat}, {lon}) has no row in {HWSD_CSV}")
    if "SHARE" in rows.columns:
        rows["_share"] = pd.to_numeric(rows["SHARE"], errors="coerce").fillna(0)
        rows = rows.sort_values("_share", ascending=False, kind="stable")
    r = rows.iloc[0]

    def num(col):
        v = r.get(col)
        try:
            v = float(v)
        except (TypeError, ValueError):
            return math.nan
        if v in HWSD_MISSING_CODES:   # HWSD writes -99 / -999 / -9999 for "no data"
            return math.nan
        return v

    props = {"mu_id": mu_id}
    required = ("T_SAND", "T_SILT", "T_CLAY", "T_OC", "T_PH_H2O",
                "S_SAND", "S_SILT", "S_CLAY", "S_OC", "S_PH_H2O")
    for col in required + ("T_REF_BULK_DENSITY", "S_REF_BULK_DENSITY"):
        props[col] = num(col)
    missing = [c for c in required if not math.isfinite(props[c])]
    if missing:
        raise ValueError(f"HWSD map unit {mu_id} at ({lat}, {lon}), dominant row "
                         f"(SEQ {r.get('SEQ')}, SHARE {r.get('SHARE')}): no value for {missing}; "
                         f"no default or topsoil value is used in its place")
    if props["T_SAND"] + props["T_SILT"] + props["T_CLAY"] <= 0:
        raise ValueError(f"HWSD map unit {mu_id} at ({lat}, {lon}) has no topsoil texture")
    if props["S_SAND"] + props["S_SILT"] + props["S_CLAY"] <= 0:
        raise ValueError(f"HWSD map unit {mu_id} at ({lat}, {lon}) has no subsoil texture")
    for col in ("T_REF_BULK_DENSITY", "S_REF_BULK_DENSITY"):
        if not (props[col] > 0):
            props[col] = np.nan   # 0 / missing marks no measured density (see docstring)
    return props


# ── SOL writer ─────────────────────────────────────────────────────────────

def write_sol(soil_props, output_path, soil_id, lat, lon, *, rule="paper", min_gap=MIN_GAP_DEFAULT,
              max_bd_drop=MAX_BD_DROP, min_bd_used=MIN_BD_USED, on_cap=ON_CAP_DEFAULT):
    """
    Write DSSAT SOIL.SOL with two layers:
      Layer 1 : 0–30 cm   (HWSD topsoil)
      Layer 2 : 30–200 cm (HWSD subsoil 30–100 cm extended to 200 cm for DSSAT)
    rule / min_gap / max_bd_drop / min_bd_used / on_cap: see saxton_rawls(). With rule="paper" (default)
    SSKS is printed with 3 decimals (format_ssks) and the printed numbers are checked against the rules
    before anything is written (ValueError if broken); rule="legacy" writes the old file byte for byte.
    """
    # DSSAT matches the FileX FIELDS soil ID against the .SOL profile name over a
    # FIXED 10-char field. IDs shorter than ~8 chars break that match, leaving the
    # soil arrays uninitialised -> SIGFPE in INSOIL (verified 2026-06-08). Zero-pad
    # short/alnum IDs to the full 10-char width.
    soil_id = ("".join(c for c in str(soil_id).upper() if c.isalnum())
               or "HWSD000001").ljust(10, "0")[:10]

    check_hwsd_values(soil_props, f" at ({lat}, {lon})")   # before any calculation or file write
    top_sand = soil_props["T_SAND"];  top_silt = soil_props["T_SILT"];  top_clay = soil_props["T_CLAY"]
    # Every value from lookup_hwsd(); a missing key raises (no defaults, no
    # subsoil value taken from the topsoil). Bulk density NaN = not measured.
    sub_sand = soil_props["S_SAND"]; sub_silt = soil_props["S_SILT"]; sub_clay = soil_props["S_CLAY"]
    top_oc   = soil_props["T_OC"]
    sub_oc   = soil_props["S_OC"]
    top_bd   = soil_props["T_REF_BULK_DENSITY"]   # kg/dm³ = g/cm³
    sub_bd   = soil_props["S_REF_BULK_DENSITY"]
    ph_top   = soil_props["T_PH_H2O"]
    ph_sub   = soil_props["S_PH_H2O"]

    legacy   = (rule == "legacy")
    kw       = dict(rule=rule, min_gap=min_gap, max_bd_drop=max_bd_drop, min_bd_used=min_bd_used, on_cap=on_cap)
    tex_top  = classify_texture(top_sand, top_silt, top_clay)
    tex_sub  = classify_texture(sub_sand, sub_silt, sub_clay)
    hyd_top  = saxton_rawls(top_sand, top_clay, oc=top_oc, bd=top_bd, **kw)
    hyd_sub  = saxton_rawls(sub_sand, sub_clay, oc=sub_oc, bd=sub_bd, **kw)
    if not legacy:                     # fail closed: never write a soil that breaks the printed-number rules
        for name, hyd in (("topsoil", hyd_top), ("subsoil", hyd_sub)):
            problems = printed_rule_problems(hyd["SLLL"], hyd["SDUL"], hyd["SSAT"], hyd["SBDM"], min_gap)
            if problems:
                raise ValueError(f"HWSD {name} at ({lat}, {lon}) breaks the soil rules: {problems}")
    title = ("*SOILS: HWSD-derived soil profile (6-layer)" if legacy else
             f"*SOILS: HWSD-derived soil profile (6-layer); S&R 2006 DF limit, min gap {min_gap:.3f}")

    with open(output_path, "w") as f:
        f.write(title + "\n\n")
        # Line 3 MUST use 'SoilGrids' as source label — DSSAT 4.8.5 fails to find the
        # profile (error 5010) when the source label is 'HWSD'. The soil data are from
        # HWSD; only the header label is changed for DSSAT compatibility.
        f.write(f"*{soil_id:<10s} SoilGrids {tex_top:5s}    {200:5d}  HWSD MU={soil_props['mu_id']}\n")
        f.write(f"@SITE        COUNTRY          LAT     LONG SCS FAMILY\n")
        f.write(f" HWSD        China        {lat:7.3f} {lon:8.3f} {tex_top}\n")
        f.write(f"@ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE\n")
        f.write(f"    BN  0.13   6.0  0.60  73.0  1.00  1.00 SA001 SA001 SA001\n")
        f.write(f"@  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC  SLCL  SLSI  SLCF  SLNI  SLHW  SLHB  SCEC  SADC\n")
        # 6 layers: 5,15,30 cm from HWSD topsoil; 60,100,200 cm from HWSD subsoil
        for depth, hyd, oc, clay, silt, ph, srgf in [
            (  5, hyd_top, top_oc, top_clay, top_silt, ph_top, 1.000),
            ( 15, hyd_top, top_oc, top_clay, top_silt, ph_top, 0.850),
            ( 30, hyd_top, top_oc, top_clay, top_silt, ph_top, 0.600),
            ( 60, hyd_sub, sub_oc, sub_clay, sub_silt, ph_sub, 0.350),
            (100, hyd_sub, sub_oc, sub_clay, sub_silt, ph_sub, 0.150),
            (200, hyd_sub, sub_oc, sub_clay, sub_silt, ph_sub, 0.050),
        ]:
            slmh = 'Ap' if depth <= 30 else 'B'
            # DSSAT reads the soil layer table FIXED-WIDTH (6-char right-justified
            # columns matching the @ header). The previous format had a 7-char SRGF
            # ('  {:.3f}') and a 5-char SLMH for single-letter horizons, shifting
            # every later column so INSOIL mis-read garbage and crashed (SIGFPE).
            # Emit strict 6-char columns (SADC col included for HWSD).
            # SSKS: 3 decimals (format_ssks) so values below 0.005 cm/h are not printed as 0.00,
            # which DSSAT reads as "no drainage limit"; legacy keeps the old 2 decimals.
            slni = oc / top_oc * 0.10
            ssks_txt = f"{hyd['SSKS']:6.2f}" if legacy else format_ssks(hyd["SSKS"])
            f.write(f"{depth:6d}{slmh:>6s}"
                    f"{hyd['SLLL']:6.3f}{hyd['SDUL']:6.3f}{hyd['SSAT']:6.3f}"
                    f"{srgf:6.3f}{ssks_txt}{hyd['SBDM']:6.2f}"
                    f"{oc:6.2f}{clay:6.1f}{silt:6.1f}   0.0"
                    f"{slni:6.3f}{ph:6.1f}   -99   -99   -99\n")

    print(f"Written: {output_path}")
    print(f"  HWSD MU: {soil_props['mu_id']}  Top: {tex_top} (sa={top_sand:.0f}% cl={top_clay:.0f}%)")
    print(f"  Top  SLLL={hyd_top['SLLL']:.3f} SDUL={hyd_top['SDUL']:.3f} "
          f"SSAT={hyd_top['SSAT']:.3f} SSKS={hyd_top['SSKS']:.3f} SBDM={hyd_top['SBDM']:.2f}")
    print(f"  Sub  SLLL={hyd_sub['SLLL']:.3f} SDUL={hyd_sub['SDUL']:.3f} "
          f"SSAT={hyd_sub['SSAT']:.3f} SSKS={hyd_sub['SSKS']:.3f} SBDM={hyd_sub['SBDM']:.2f}")
    if not legacy:
        for name, hyd in (("Top", hyd_top), ("Sub", hyd_sub)):
            if hyd["gap_rule"] != "unchanged":
                print(f"  {name}  gap rule {hyd['gap_rule']} (min gap {min_gap:.3f}): density "
                      f"{hyd['bd_input']:.3f} -> {hyd['SBDM']:.2f}" +
                      (f", SDUL cut by {hyd['sdul_cut']:.3f}" if hyd["gap_rule"] == "cap_sdul" else ""))


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert HWSD soil data to DSSAT SOIL.SOL")
    parser.add_argument("--lat",     type=float, required=True,  help="Latitude")
    parser.add_argument("--lon",     type=float, required=True,  help="Longitude")
    parser.add_argument("--output",  required=True,              help="Output SOIL.SOL path")
    parser.add_argument("--soil_id", default="HWSD000001",       help="DSSAT soil ID (≤10 chars)")
    parser.add_argument("--min_gap", type=float, default=MIN_GAP_DEFAULT,
                        help=f"Minimum SSAT - SDUL and pore space - SDUL (default {MIN_GAP_DEFAULT}, tested on maize "
                             f"only; {MIN_GAP_FLOOR} to 0.2 in whole thousandths); the density used is lowered to reach "
                             f"it (S&R 2006 p. 1574)")
    parser.add_argument("--legacy_gap_rule", action="store_true", default=False,
                        help="Reproduce the old files: SSAT pinned at SDUL + 0.005, density kept, SSKS 2 decimals")
    args = parser.parse_args()

    print(f"Looking up HWSD soil for ({args.lat}, {args.lon})...")
    props = lookup_hwsd(args.lat, args.lon)
    rule = "legacy" if args.legacy_gap_rule else "paper"
    write_sol(props, args.output, args.soil_id, args.lat, args.lon, rule=rule, min_gap=args.min_gap)


if __name__ == "__main__":
    main()
