#!/usr/bin/env python3
"""Build an EPIC .SOL soil profile by copying umstead.SOL and overlaying
HWSD-derived layer properties.

EPIC SOL format (lines 0-indexed):
  [0]  Title
  [1]  SALB HSG USLE_K SSLPLN ... (10 soil-level params, F8.2)
  [2]  SOL_ZMX NLAYER ...          (10 more, F8.2)
  [3]  Z      — layer depth bottoms (m)
  [4]  BD     — bulk density (g/cm3)
  [5]  WP     — wilting point (m3/m3, -15 bar)
  [6]  FC     — field capacity (m3/m3, -0.33 bar)
  [7]  SAND%
  [8]  SILT%
  [9]  (internal — leave from template)
  [10] PH
  [11] OC     — organic carbon (g/kg)
  [12] (organic N fraction — leave from template)
  [13] CaCO3  — (leave from template)
  [14] CEC    (cmol/kg)
  [15] (initial labile P — leave from template)
  [16] KSAT   — saturated hydraulic conductivity (mm/hr)
  [17+] (leave from template)

Data sources:
  - HWSD topsoil (0-30 cm): sand, silt, clay, OC, pH, bulk_density
  - HWSD subsoil (30-100 cm): sub_sand, sub_silt, sub_clay
  - Saxton-Rawls pedotransfer: WP, FC, Ksat from texture + OM
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (
    copy_template, read_text_crlf, write_text_crlf, add_kdt_common_to_path,
)

N_LAYERS = 6
F8 = "{:>8.2f}"

# 6-layer depth scheme: 3 topsoil (0-30cm) + 3 subsoil (30-100cm)
DEPTH_BOTTOMS = [0.10, 0.20, 0.30, 0.50, 0.75, 1.00]


def fmt_row(vals):
    """Format layer values as 8-char fixed-width columns (EPIC SOL format)."""
    return "".join(F8.format(v) for v in vals)


def _estimate_albedo(sand, oc_pct):
    """Estimate soil albedo from sand% and organic C%.
    Dark organic soils ~0.10, light sandy soils ~0.25."""
    # Baier & Robertson regression (simplified)
    albedo = 0.10 + 0.15 * (sand / 100.0) - 0.03 * min(oc_pct, 4.0)
    return max(0.05, min(0.30, albedo))


def _estimate_hsg(sand, clay, ksat_mm_hr):
    """Estimate USDA hydrologic soil group (1=A, 2=B, 3=C, 4=D)."""
    if ksat_mm_hr > 7.6:
        return 1.0  # A — high infiltration (sand, gravel)
    elif ksat_mm_hr > 3.8:
        return 2.0  # B — moderate (loam, silt loam)
    elif ksat_mm_hr > 1.3:
        return 3.0  # C — slow (clay loam)
    else:
        return 4.0  # D — very slow (clay)


def _estimate_usle_k(sand, silt, clay, oc_pct):
    """Estimate USLE K-factor from texture + organic matter.
    Williams (1995) equation used in EPIC."""
    sn1 = max(0.01, 1.0 - sand / 100.0)
    cl1 = clay / 100.0
    si1 = silt / 100.0
    org = oc_pct * 1.724  # OC to OM
    # Simplified Williams K-factor
    k = (0.2 + 0.3 * (sn1 ** 0.25) * (1.0 - org / 25.0)) * (si1 / (cl1 + si1)) ** 0.3
    return max(0.01, min(0.70, round(k, 2)))


def safe_lookup_hwsd(lat, lon):
    add_kdt_common_to_path()
    try:
        from ki_tools_common.soil_utils import lookup_hwsd
        return lookup_hwsd(lat, lon)
    except Exception as e:
        print(f"  WARN  HWSD lookup unavailable ({e}); keeping template soil.",
              file=sys.stderr)
        return None


def safe_saxton_rawls(sand, clay, om_pct):
    add_kdt_common_to_path()
    try:
        from ki_tools_common.soil_utils import saxton_rawls
        return saxton_rawls(sand, clay, om_pct)
    except Exception:
        # Fallback crude estimates
        return {
            'wilting_point': 0.05 + 0.004 * clay,
            'field_capacity': 0.10 + 0.006 * clay + 0.002 * (100 - sand - clay),
            'ksat_cm_hr': max(0.01, 5.0 - 0.1 * clay),
        }


def build(name, lat, lon, workspace):
    os.makedirs(workspace, exist_ok=True)
    dst = copy_template("umstead.SOL", workspace, new_name=f"{name}.SOL")

    soil = safe_lookup_hwsd(lat, lon)
    text = read_text_crlf(dst)
    lines = text.splitlines()

    if soil is None:
        lines[0] = f"{name:<25}TEMPLATE_SOIL"
        write_text_crlf(dst, "\r\n".join(lines))
        return dst

    # ── Extract HWSD data ────────────────────────────────────────
    top_sand = soil.get("sand", 40.0)
    top_clay = soil.get("clay", 20.0) if "clay" in soil else 100.0 - top_sand - soil.get("silt", 40.0)
    top_silt = 100.0 - top_sand - top_clay
    top_bd = soil.get("bulk_density", 1.40)
    top_oc = soil.get("oc", soil.get("org_c", 1.0))  # %
    top_ph = soil.get("ph", 6.5)

    sub_sand = soil.get("sub_sand", top_sand)
    sub_clay = soil.get("sub_clay", top_clay + 5)  # subsoil typically more clay
    sub_silt = 100.0 - sub_sand - sub_clay
    sub_bd = top_bd + 0.05  # subsoil slightly denser
    sub_oc = max(0.1, top_oc * 0.3)  # subsoil ~30% of topsoil OC
    sub_ph = top_ph + 0.2  # subsoil slightly less acidic

    # ── Saxton-Rawls hydraulics ──────────────────────────────────
    top_om = top_oc * 1.724
    sub_om = sub_oc * 1.724
    top_hyd = safe_saxton_rawls(top_sand, top_clay, top_om)
    sub_hyd = safe_saxton_rawls(sub_sand, sub_clay, sub_om)

    # Use HWSD's own hydraulics if available (often more accurate)
    hwsd_hyd = soil.get("hydraulics", {})
    if hwsd_hyd.get("wilting_point"):
        top_hyd["wilting_point"] = hwsd_hyd["wilting_point"]
    if hwsd_hyd.get("field_capacity"):
        top_hyd["field_capacity"] = hwsd_hyd["field_capacity"]
    if hwsd_hyd.get("ksat_cm_hr"):
        top_hyd["ksat_cm_hr"] = hwsd_hyd["ksat_cm_hr"]

    # ── Build 6-layer arrays (3 topsoil + 3 subsoil) ────────────
    sand = [top_sand] * 3 + [sub_sand] * 3
    silt = [top_silt] * 3 + [sub_silt] * 3
    bd = [top_bd] * 3 + [sub_bd] * 3
    wp = [top_hyd["wilting_point"]] * 3 + [sub_hyd["wilting_point"]] * 3
    fc = [top_hyd["field_capacity"]] * 3 + [sub_hyd["field_capacity"]] * 3
    ksat = [top_hyd["ksat_cm_hr"] * 10] * 3 + [sub_hyd["ksat_cm_hr"] * 10] * 3  # cm/hr → mm/hr
    oc_gkg = [top_oc * 10] * 3 + [sub_oc * 10] * 3  # % → g/kg
    ph = [top_ph] * 3 + [sub_ph] * 3
    cec_top = soil.get("cec", max(5.0, top_clay * 0.5 + top_oc * 3))
    cec_sub = max(3.0, cec_top * 0.7)
    cec = [cec_top] * 3 + [cec_sub] * 3

    # ── Update soil-level header (line 1) ────────────────────────
    salb = _estimate_albedo(top_sand, top_oc)
    hsg = _estimate_hsg(top_sand, top_clay, ksat[0])
    usle_k = _estimate_usle_k(top_sand, top_silt, top_clay, top_oc)

    # Preserve template values for fields we can't estimate
    old_hdr = lines[1] if len(lines) > 1 else ""
    old_vals = old_hdr.split()
    # Line 1 format: SALB HSG USLE_K SSLPLN CN2 CHP FFC RSMP SCON FUL
    hdr_vals = [float(v) if v.replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0
                for v in old_vals[:10]]
    while len(hdr_vals) < 10:
        hdr_vals.append(0.0)
    hdr_vals[0] = salb
    hdr_vals[1] = hsg
    hdr_vals[2] = usle_k

    # ── Write ────────────────────────────────────────────────────
    lines[0] = f"{name:<25}HWSD_{soil.get('texture', 'unknown')}"
    lines[1] = fmt_row(hdr_vals[:6]) + fmt_row(hdr_vals[6:10])

    layer_rows = {
        3: DEPTH_BOTTOMS,
        4: bd,
        5: wp,
        6: fc,
        7: sand,
        8: silt,
        # [9]: leave from template (internal EPIC variable)
        10: ph,
        11: oc_gkg,
        # [12]: leave from template (org N fraction)
        # [13]: leave from template (CaCO3)
        14: cec,
        # [15]: leave from template (initial labile P)
        16: ksat,
    }
    for idx, vals in layer_rows.items():
        if idx < len(lines):
            lines[idx] = fmt_row(vals)

    write_text_crlf(dst, "\r\n".join(lines))
    print(f"  soil: {soil.get('texture', '?')} (sand={top_sand:.0f}% clay={top_clay:.0f}%)"
          f" → WP={wp[0]:.3f} FC={fc[0]:.3f} Ksat={ksat[0]:.1f}mm/hr")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args()
    path = build(args.name, args.lat, args.lon, args.workspace)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
