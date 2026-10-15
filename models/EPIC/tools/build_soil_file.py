#!/usr/bin/env python3
"""Build an EPIC .SOL soil profile from the umstead.SOL template, overlaying
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
  - HWSD topsoil (0-30 cm): sand, silt, clay, oc (%), ph, bulk_density, cec
  - HWSD subsoil (30-100 cm): sub_sand, sub_silt, sub_clay, sub_oc, sub_ph,
    sub_bulk_density, sub_cec (all from lookup_hwsd; a missing field stops)
  - Saxton-Rawls pedotransfer (ki_tools_common.saxton_rawls): WP, FC, Ksat
    from texture + OM, OM = OC x 1.724, for both top and subsoil. A failure
    stops the tool (no stand-in formulas).
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math
import tempfile
from _common import (
    template_path, read_text_crlf, write_text_crlf, add_kdt_common_to_path,
)

# Every HWSD field this tool writes into the .SOL. All must come from
# lookup_hwsd; a missing or non-numeric one stops the tool BEFORE any file
# is written (no template value is left standing in for it).
REQUIRED_SOIL_FIELDS = (
    "sand", "silt", "clay", "bulk_density", "oc", "ph", "cec",
    "sub_sand", "sub_silt", "sub_clay", "sub_bulk_density", "sub_oc", "sub_ph",
    "sub_cec",
)
# Template rows overwritten below are [0]..[16]; the template must have them.
MIN_TEMPLATE_LINES = 17


def _validated_soil_values(soil, lat, lon):
    """Return {field: float} for REQUIRED_SOIL_FIELDS, or raise with every
    missing / bad field named. Nothing is written before this passes."""
    if not isinstance(soil, dict):
        raise RuntimeError(f"HWSD soil lookup at lat={lat}, lon={lon} returned "
                           f"{type(soil).__name__}, not a dict")
    missing = [k for k in REQUIRED_SOIL_FIELDS if soil.get(k) is None]
    bad = []
    vals = {}
    for k in REQUIRED_SOIL_FIELDS:
        if k in missing:
            continue
        try:
            v = float(soil[k])
        except (TypeError, ValueError):
            bad.append(f"{k}={soil[k]!r}")
            continue
        if not math.isfinite(v):
            bad.append(f"{k}={soil[k]!r}")
            continue
        vals[k] = v
    if missing or bad:
        raise RuntimeError(
            f"HWSD soil lookup at lat={lat}, lon={lon} is incomplete; no .SOL "
            f"written. missing={missing} bad={bad}")
    return vals

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
    from ki_tools_common.soil_utils import lookup_hwsd
    try:
        return lookup_hwsd(lat, lon)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        # A failed lookup stops the tool; the template soil is NOT kept in its place.
        raise RuntimeError(f"HWSD soil lookup failed at lat={lat}, lon={lon}: {e}") from e


def safe_saxton_rawls(sand, clay, om_pct):
    """Shared Saxton-Rawls; any failure propagates (no crude stand-in)."""
    add_kdt_common_to_path()
    from ki_tools_common.soil_utils import saxton_rawls
    return saxton_rawls(sand, clay, om_pct)


def build(name, lat, lon, workspace):
    os.makedirs(workspace, exist_ok=True)
    dst = os.path.join(workspace, f"{name}.SOL")
    # Look up AND validate everything first. The destination is only written
    # at the very end, by an atomic replace of a finished temp file, so any
    # failure leaves no template soil behind and an existing <name>.SOL is
    # left exactly as it was.
    soil = safe_lookup_hwsd(lat, lon)
    v = _validated_soil_values(soil, lat, lon)

    text = read_text_crlf(template_path("umstead.SOL"))
    lines = text.splitlines()
    if len(lines) < MIN_TEMPLATE_LINES:
        raise RuntimeError(f"template umstead.SOL has {len(lines)} lines, "
                           f"need >= {MIN_TEMPLATE_LINES}; no .SOL written")

    # ── Extract HWSD data ────────────────────────────────────────
    # Every value straight from lookup_hwsd (HWSD T_* / S_* of one row); a
    # missing field stopped above. No subsoil value is derived from the topsoil.
    top_sand, top_silt, top_clay = v["sand"], v["silt"], v["clay"]
    top_bd = v["bulk_density"]                    # g/cm3
    top_oc = v["oc"]                              # % organic carbon
    top_ph = v["ph"]
    sub_sand, sub_silt, sub_clay = v["sub_sand"], v["sub_silt"], v["sub_clay"]
    sub_bd = v["sub_bulk_density"]                # g/cm3
    sub_oc = v["sub_oc"]                          # % organic carbon
    sub_ph = v["sub_ph"]

    # ── Saxton-Rawls hydraulics ──────────────────────────────────
    top_om = top_oc * 1.724
    sub_om = sub_oc * 1.724
    top_hyd = safe_saxton_rawls(top_sand, top_clay, top_om)
    sub_hyd = safe_saxton_rawls(sub_sand, sub_clay, sub_om)

    # (lookup_hwsd's own 'hydraulics' is no longer copied over the topsoil: top
    # and subsoil now come from the same call, OM = OC x 1.724. The shared
    # saxton_rawls is a texture-class table, so OM does not change the result.)

    # ── Build 6-layer arrays (3 topsoil + 3 subsoil) ────────────
    sand = [top_sand] * 3 + [sub_sand] * 3
    silt = [top_silt] * 3 + [sub_silt] * 3
    bd = [top_bd] * 3 + [sub_bd] * 3
    wp = [top_hyd["wilting_point"]] * 3 + [sub_hyd["wilting_point"]] * 3
    fc = [top_hyd["field_capacity"]] * 3 + [sub_hyd["field_capacity"]] * 3
    ksat = [top_hyd["ksat_cm_hr"] * 10] * 3 + [sub_hyd["ksat_cm_hr"] * 10] * 3  # cm/hr → mm/hr
    oc_gkg = [top_oc * 10] * 3 + [sub_oc * 10] * 3  # % → g/kg
    ph = [top_ph] * 3 + [sub_ph] * 3
    cec = [v["cec"]] * 3 + [v["sub_cec"]] * 3  # HWSD T/S_CEC_SOIL, cmol/kg

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
        lines[idx] = fmt_row(vals)

    # Write a temp file in the same folder, then atomically replace dst.
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=".SOL.tmp", dir=workspace)
    os.close(fd)
    try:
        write_text_crlf(tmp, "\r\n".join(lines))
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
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
