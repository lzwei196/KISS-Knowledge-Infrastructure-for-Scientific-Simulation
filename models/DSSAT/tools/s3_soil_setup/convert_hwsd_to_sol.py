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

Usage:
    python convert_hwsd_to_sol.py \
        --lat 32.43 --lon 115.60 \
        --output SOIL.SOL \
        --soil_id WJBA000001
"""

import argparse
import os
import math
import numpy as np
import pandas as pd

HYDROCRAFT   = "KISSPATH_ROOT"
HWSD_RASTER  = os.path.join(HYDROCRAFT, "data/soil/HWSD_RASTER/hwsd.bil")
HWSD_CSV     = os.path.join(HYDROCRAFT, "data/soil/HWSD_DATA.csv")


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


# ── Saxton-Rawls 2006 PTF ──────────────────────────────────────────────────

def saxton_rawls(sand, clay, oc=1.0, bd=None):
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
           If provided and valid, used for density adjustment; otherwise the
           texture-derived normal-density saturation is used.

    DSSAT outputs
    -------------
    SLLL : lower limit (wilting point),       cm³/cm³
    SDUL : drained upper limit (field cap.),  cm³/cm³
    SSAT : saturation,                        cm³/cm³
    SSKS : sat. hydraulic conductivity,       cm/hr
           (S&R gives Ks in mm/hr → ÷ 10 for DSSAT)
    SBDM : bulk density,                      g/cm³
    """
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


# ── HWSD lookup ────────────────────────────────────────────────────────────

def lookup_hwsd(lat, lon):
    """
    Look up HWSD soil properties for a grid cell.

    Selects the dominant soil component (highest SHARE) when the mapping unit
    contains multiple records.  Falls back to loam defaults on any failure.
    """
    mu_id = None
    try:
        import rasterio
        with rasterio.open(HWSD_RASTER) as src:
            row, col = src.index(lon, lat)
            if not (0 <= row < src.height and 0 <= col < src.width):
                raise ValueError(f"Point ({lat},{lon}) outside HWSD raster extent.")
            mu_id = int(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
            if mu_id <= 0:
                raise ValueError(f"Invalid MU_GLOBAL={mu_id}")
    except Exception as e:
        print(f"  WARNING: HWSD raster lookup failed: {e}")

    if mu_id and os.path.exists(HWSD_CSV):
        df = pd.read_csv(HWSD_CSV, low_memory=False)
        rows = df[df["MU_GLOBAL"] == mu_id].copy()
        if len(rows) > 0:
            # Select dominant component by SHARE
            if "SHARE" in rows.columns:
                rows["_share"] = pd.to_numeric(rows["SHARE"], errors="coerce").fillna(0)
                rows = rows.sort_values("_share", ascending=False)
            r = rows.iloc[0]

            top_oc = safe_float(r.get("T_OC",    1.5),       1.5)
            sub_oc = safe_float(r.get("S_OC",    top_oc*0.5), top_oc*0.5)

            return {
                "mu_id":               mu_id,
                "T_SAND":              safe_float(r.get("T_SAND", 40),  40),
                "T_SILT":              safe_float(r.get("T_SILT", 40),  40),
                "T_CLAY":              safe_float(r.get("T_CLAY", 20),  20),
                "T_OC":                top_oc,
                "T_PH_H2O":            safe_float(r.get("T_PH_H2O", 6.5), 6.5),
                # HWSD BD in kg/dm³ ≡ g/cm³; pass np.nan if missing/invalid
                "T_REF_BULK_DENSITY":  safe_float(r.get("T_REF_BULK_DENSITY", np.nan), np.nan),
                "S_SAND":              safe_float(r.get("S_SAND", r.get("T_SAND", 40)), 40),
                "S_SILT":              safe_float(r.get("S_SILT", r.get("T_SILT", 40)), 40),
                "S_CLAY":              safe_float(r.get("S_CLAY", r.get("T_CLAY", 20)), 20),
                "S_OC":                sub_oc,
                "S_PH_H2O":            safe_float(r.get("S_PH_H2O", r.get("T_PH_H2O", 6.5)), 6.5),
                "S_REF_BULK_DENSITY":  safe_float(r.get("S_REF_BULK_DENSITY", np.nan), np.nan),
            }

    print(f"  WARNING: Using default loam soil for ({lat}, {lon})")
    return {
        "mu_id": 0,
        "T_SAND": 40, "T_SILT": 40, "T_CLAY": 20,
        "T_OC": 1.5,  "T_PH_H2O": 6.5, "T_REF_BULK_DENSITY": 1.3,
        "S_SAND": 40, "S_SILT": 40, "S_CLAY": 20,
        "S_OC": 0.75, "S_PH_H2O": 6.5, "S_REF_BULK_DENSITY": 1.4,
    }


# ── SOL writer ─────────────────────────────────────────────────────────────

def write_sol(soil_props, output_path, soil_id, lat, lon):
    """
    Write DSSAT SOIL.SOL with two layers:
      Layer 1 : 0–30 cm   (HWSD topsoil)
      Layer 2 : 30–200 cm (HWSD subsoil 30–100 cm extended to 200 cm for DSSAT)
    """
    # DSSAT matches the FileX FIELDS soil ID against the .SOL profile name over a
    # FIXED 10-char field. IDs shorter than ~8 chars break that match, leaving the
    # soil arrays uninitialised -> SIGFPE in INSOIL (verified 2026-06-08). Zero-pad
    # short/alnum IDs to the full 10-char width.
    soil_id = ("".join(c for c in str(soil_id).upper() if c.isalnum())
               or "HWSD000001").ljust(10, "0")[:10]

    top_sand = soil_props["T_SAND"];  top_silt = soil_props["T_SILT"];  top_clay = soil_props["T_CLAY"]
    sub_sand = soil_props.get("S_SAND", top_sand)
    sub_silt = soil_props.get("S_SILT", top_silt)
    sub_clay = soil_props.get("S_CLAY", top_clay)
    top_oc   = soil_props.get("T_OC",  1.5)
    sub_oc   = soil_props.get("S_OC",  top_oc * 0.5)
    top_bd   = soil_props.get("T_REF_BULK_DENSITY", np.nan)   # kg/dm³ = g/cm³
    sub_bd   = soil_props.get("S_REF_BULK_DENSITY", np.nan)
    ph_top   = soil_props.get("T_PH_H2O", 6.5)
    ph_sub   = soil_props.get("S_PH_H2O", ph_top)

    tex_top  = classify_texture(top_sand, top_silt, top_clay)
    tex_sub  = classify_texture(sub_sand, sub_silt, sub_clay)
    hyd_top  = saxton_rawls(top_sand, top_clay, oc=top_oc, bd=top_bd)
    hyd_sub  = saxton_rawls(sub_sand, sub_clay, oc=sub_oc, bd=sub_bd)

    with open(output_path, "w") as f:
        f.write("*SOILS: HWSD-derived soil profile (6-layer)\n\n")
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
            slni = oc / top_oc * 0.10
            f.write(f"{depth:6d}{slmh:>6s}"
                    f"{hyd['SLLL']:6.3f}{hyd['SDUL']:6.3f}{hyd['SSAT']:6.3f}"
                    f"{srgf:6.3f}{hyd['SSKS']:6.2f}{hyd['SBDM']:6.2f}"
                    f"{oc:6.2f}{clay:6.1f}{silt:6.1f}   0.0"
                    f"{slni:6.3f}{ph:6.1f}   -99   -99   -99\n")

    print(f"Written: {output_path}")
    print(f"  HWSD MU: {soil_props['mu_id']}  Top: {tex_top} (sa={top_sand:.0f}% cl={top_clay:.0f}%)")
    print(f"  Top  SLLL={hyd_top['SLLL']:.3f} SDUL={hyd_top['SDUL']:.3f} "
          f"SSAT={hyd_top['SSAT']:.3f} SSKS={hyd_top['SSKS']:.3f} SBDM={hyd_top['SBDM']:.2f}")
    print(f"  Sub  SLLL={hyd_sub['SLLL']:.3f} SDUL={hyd_sub['SDUL']:.3f} "
          f"SSAT={hyd_sub['SSAT']:.3f} SSKS={hyd_sub['SSKS']:.3f} SBDM={hyd_sub['SBDM']:.2f}")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert HWSD soil data to DSSAT SOIL.SOL")
    parser.add_argument("--lat",     type=float, required=True,  help="Latitude")
    parser.add_argument("--lon",     type=float, required=True,  help="Longitude")
    parser.add_argument("--output",  required=True,              help="Output SOIL.SOL path")
    parser.add_argument("--soil_id", default="HWSD000001",       help="DSSAT soil ID (≤10 chars)")
    args = parser.parse_args()

    print(f"Looking up HWSD soil for ({args.lat}, {args.lon})...")
    props = lookup_hwsd(args.lat, args.lon)
    write_sol(props, args.output, args.soil_id, args.lat, args.lon)


if __name__ == "__main__":
    main()
