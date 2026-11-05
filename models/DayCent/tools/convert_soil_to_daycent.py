#!/usr/bin/env python3
"""
convert_soil_to_daycent.py — Build a DayCent soils.in file from HWSD + ROSETTA.

DayCent soils.in (no header, whitespace-delimited, one row per layer). The
canonical 13-column layout used by rev 491 (cross-checked against the
WoosterExampleLinux file shipped with the binary distribution):

    1: top depth         (cm)
    2: bottom depth      (cm)
    3: bulk density      (g/cm³)
    4: field capacity    (vol/vol, 0..1)
    5: wilting point     (vol/vol, 0..1)
    6: evap coefficient  (0..1, decreases with depth)
    7: root fraction     (0..1; Wooster example values, sum 0.84 over the 9 layers; checked 0 < sum <= 1)
    8: sand fraction     (0..1)
    9: clay fraction     (0..1)
   10: organic matter    (fraction of mass, 0..1)  ← MUST be fraction, NOT percent
   11: delta_min         (minimum volumetric water content, ~WP×0.9)
   12: saturated K       (cm/sec)
   13: pH                (unitless)

BUG FIX (2026-04-22, from AT-Neu + US-Var FLUXNET runs):
  - Added column 11 (delta_min). Without it DayCent reads Ksat into the
    delta_min slot, producing "swclimit[1] is negative" errors.
  - (2026-10-05) Units are no longer guessed from the size of a value. HWSD
    T_OC/S_OC is % organic carbon -> OM fraction = OC/100 x 1.724; HWSD
    T/S_REF_BULK_DENSITY is kg/dm3 = g/cm3 and is written as is. Subsoil
    (layers below 30 cm) uses HWSD S_OC, S_REF_BULK_DENSITY and S_PH_H2O from
    the same HWSD row; if HWSD has none the tool stops.

HWSD provides texture and bulk density at two depths (topsoil 0-30, subsoil
30-100 cm). The profile uses the first 9 layers of the Wooster example
(0-2, 2-5, 5-10, 10-20, 20-30, 30-45, 45-60, 60-75, 75-90 cm) and ENDS AT
90 cm: HWSD has no data below 100 cm, and DayCent rev 491 rejects a soils.in
layer boundary at 100 cm with the standard fix.100 ADEP layering (10, 20, 15,
15, 30, ... cm -> boundaries 10, 30, 45, 60, 90, 120 ...): "Incompatible soil
structures in fix.100 and soils.in" (tested 2026-10-05). 90 cm is the deepest
ADEP boundary inside the HWSD depth. Layers above 30 cm use HWSD topsoil, the
rest HWSD subsoil. ROSETTA runs on each layer texture to give field capacity,
wilting point and Ksat.

Usage:
    python convert_soil_to_daycent.py --lat 40.78 --lon -81.93 --out soils.in
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
try:
    from ki_tools_common.soil_utils import lookup_hwsd, rosetta_vgn
except ImportError as e:
    print(f"FATAL: ki_tools_common not importable: {e}", file=sys.stderr)
    sys.exit(2)


# Deepest depth HWSD describes (subsoil 30-100 cm).
HWSD_MAX_DEPTH_CM = 100.0

# Layering of the Wooster reference soils.in (DayCent distribution), cut at
# 90 cm (see module docstring): no layer goes below the HWSD depth.
LAYER_EDGES_CM = [0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 75.0, 90.0]

# Column 7 (binary header 'tcoeff', the root/transpiration fraction) and
# column 6 ('ecoeff') copied from the same 9 layers of the Wooster reference
# soils.in (copy in workdir/de_gri/soils.in). The full Wooster column sums to
# 0.85, not 1.0 (its 90-105 cm layer had 0.01); these 9 layers sum to 0.84.
# The values are not changed here because the source gives them this way.
ROOT_FRACTION_TEMPLATE = [0.01, 0.04, 0.25, 0.30, 0.10, 0.05, 0.04, 0.03, 0.02]
EVAP_COEFF_TEMPLATE = [0.80, 0.20, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]


def validate_inputs(lat, lon):
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat out of range: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"lon out of range: {lon}")


# Van Bemmelen factor: organic matter = 1.724 x organic carbon (by mass).
OM_PER_OC = 1.724


def _hwsd_subsoil(hwsd):
    """Subsoil (30-100 cm) OC, bulk density and pH. lookup_hwsd returns them
    (sub_oc, sub_bulk_density, sub_ph; a missing one raises). As a cross-check
    the same HWSD_DATA row (MU_GLOBAL + SEQ, matched on the topsoil values) is
    read again and must give the same S_OC / S_REF_BULK_DENSITY / S_PH_H2O."""
    import math
    import pandas as pd
    from ki_tools_common import soil_utils
    comp = hwsd["hwsd_component"]
    mu, seq = int(hwsd["mu_id"]), comp.get("seq")
    if seq is None:
        raise ValueError(f"HWSD map unit {mu}: lookup_hwsd gave no SEQ, cannot find the "
                         f"subsoil row; no subsoil values are made up")
    df = pd.read_csv(soil_utils.HWSD_CSV, low_memory=False)
    rows = df[(df["MU_GLOBAL"] == mu) & (df["SEQ"] == seq)
              & (df["T_SAND"] == float(hwsd["sand"])) & (df["T_CLAY"] == float(hwsd["clay"]))
              & (df["T_OC"] == float(hwsd["oc"]))]
    if len(rows) != 1:
        raise ValueError(f"HWSD map unit {mu} SEQ {seq}: found {len(rows)} rows matching the "
                         f"lookup_hwsd topsoil; cannot read the subsoil row")
    r = rows.iloc[0]
    out = {"oc": float(hwsd["sub_oc"]), "bulk_density": float(hwsd["sub_bulk_density"]),
           "ph": float(hwsd["sub_ph"])}
    for col, key in (("S_OC", "oc"), ("S_REF_BULK_DENSITY", "bulk_density"), ("S_PH_H2O", "ph")):
        v = r.get(col)
        if v is None or not math.isfinite(float(v)) or float(v) != out[key]:
            raise ValueError(f"HWSD map unit {mu} SEQ {seq}: {col} in the table ({v}) does not "
                             f"match lookup_hwsd ({out[key]}); stopping")
    return out


def build_layer_record(top, bot, soil, vgn, idx):
    """Assemble one row for soils.in.

    Units are fixed by the source, never guessed from the size of a value:
    soil['bulk_density'] is HWSD T/S_REF_BULK_DENSITY in kg/dm3 = g/cm3 (the
    soils.in unit); soil['oc'] is HWSD T/S_OC in % organic carbon by weight;
    sand/clay are HWSD percent. soils.in column 10 is the organic MATTER
    fraction (binary header 'org'; DayCent docs: organic matter fraction),
    so OM = OC% / 100 x 1.724."""
    bulkd = float(soil["bulk_density"])          # g/cm3
    sand = float(soil["sand"]) / 100.0
    clay = float(soil["clay"]) / 100.0
    om = float(soil["oc"]) / 100.0 * OM_PER_OC  # % OC -> OM mass fraction
    ph = float(soil["ph"])

    # rosetta_vgn keys, read directly: a missing key raises (no defaults).
    fc = float(vgn["field_capacity"])
    wp = float(vgn["wilting_point"])
    ksat_cm_sec = float(vgn["ksat_cm_day"]) / 86400.0   # cm/day -> cm/s (soils.in col 12)

    delta_min = wp * 0.9  # minimum volumetric water content ≈ 90% of WP

    return (top, bot, bulkd, fc, wp,
            EVAP_COEFF_TEMPLATE[idx],
            ROOT_FRACTION_TEMPLATE[idx],
            sand, clay, om, delta_min, ksat_cm_sec, ph)


def write_soils_in(rows, out_path):
    """Write 13-column soils.in for DayCent rev 491."""
    with open(out_path, "w") as f:
        for r in rows:
            # 13 columns: top bot BD FC WP evap root sand clay OM delta_min Ksat pH
            f.write(
                f"{r[0]:>5.1f}\t{r[1]:>5.1f}\t{r[2]:.2f}\t"
                f"{r[3]:.5f}\t{r[4]:.5f}\t{r[5]:.2f}\t{r[6]:.2f}\t"
                f"{r[7]:.2f}\t{r[8]:.2f}\t{r[9]:.4f}\t{r[10]:.5f}\t"
                f"{r[11]:.5f}\t{r[12]:.2f}\n"
            )


def validate_outputs(rows):
    n_expected = len(LAYER_EDGES_CM) - 1
    if len(rows) != n_expected:
        raise RuntimeError(f"{len(rows)} layers produced, expected {n_expected}")
    if any(len(r) != 13 for r in rows):
        raise RuntimeError("each row must have 13 columns")
    if rows[-1][1] > HWSD_MAX_DEPTH_CM:
        raise ValueError(f"profile goes to {rows[-1][1]} cm, below the HWSD depth "
                         f"({HWSD_MAX_DEPTH_CM} cm); no values exist there")
    # Root (tcoeff) and evap (ecoeff) columns must be exactly the Wooster
    # source values; any other values have no source and fail.
    if [r[6] for r in rows] != ROOT_FRACTION_TEMPLATE[:len(rows)]:
        raise ValueError("root-fraction column differs from the Wooster source values")
    if [r[5] for r in rows] != EVAP_COEFF_TEMPLATE[:len(rows)]:
        raise ValueError("evap-coefficient column differs from the Wooster source values")
    root_sum = sum(r[6] for r in rows)
    if not (0.0 < root_sum <= 1.0):
        raise ValueError(f"root fraction sum = {root_sum:.3f}; must be > 0 and <= 1")
    for r in rows:
        if r[3] <= r[4]:
            raise ValueError(f"layer {r[0]}-{r[1]}: FC ({r[3]}) <= WP ({r[4]})")
        if not (0.5 < r[2] < 2.5):
            raise ValueError(f"layer {r[0]}-{r[1]}: bulk density {r[2]} g/cm3 implausible")
        if not (0 <= r[7] <= 1) or not (0 <= r[8] <= 1):
            raise ValueError(f"layer {r[0]}-{r[1]}: sand/clay not in 0..1")
        if r[7] + r[8] > 1.0:
            raise ValueError(f"layer {r[0]}-{r[1]}: sand + clay > 1")
        if r[9] > 0.2:
            raise ValueError(f"layer {r[0]}-{r[1]}: OM = {r[9]} looks like percent, not fraction (should be < 0.2)")
    print(f"  columns       : {len(rows[0])} (expected 13)")
    print(f"  layers        : {len(rows)}")
    print(f"  root sum      : {root_sum:.3f}")
    print(f"  bulkd range   : {min(r[2] for r in rows):.2f}..{max(r[2] for r in rows):.2f}")
    print(f"  FC range      : {min(r[3] for r in rows):.3f}..{max(r[3] for r in rows):.3f}")
    print(f"  OM range      : {min(r[9] for r in rows):.4f}..{max(r[9] for r in rows):.4f}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--out", required=True, help="output soils.in path")
    args = p.parse_args(argv)

    validate_inputs(args.lat, args.lon)

    print(f"Looking up HWSD soil at ({args.lat}, {args.lon})")
    hwsd = lookup_hwsd(args.lat, args.lon)

    # Topsoil (0-30 cm) from lookup_hwsd; subsoil (30-100 cm, used below 30 cm)
    # from the same HWSD row's S_* columns. A missing field raises (lookup_hwsd
    # refuses missing fields; _hwsd_subsoil refuses missing S_* values).
    soil_top = {
        "sand": hwsd["sand"], "clay": hwsd["clay"],
        "bulk_density": hwsd["bulk_density"],   # T_REF_BULK_DENSITY, g/cm3
        "oc": hwsd["oc"],                       # T_OC, % organic carbon
        "ph": hwsd["ph"],
    }
    sub = _hwsd_subsoil(hwsd)
    soil_sub = {
        "sand": hwsd["sub_sand"], "clay": hwsd["sub_clay"],
        "bulk_density": sub["bulk_density"],    # S_REF_BULK_DENSITY, g/cm3
        "oc": sub["oc"],                        # S_OC, % organic carbon
        "ph": sub["ph"],                        # S_PH_H2O
    }
    print(f"  topsoil: sand={soil_top['sand']}, clay={soil_top['clay']}, bulkd={soil_top['bulk_density']}, oc%={soil_top['oc']}, ph={soil_top['ph']}")
    print(f"  subsoil: sand={soil_sub['sand']}, clay={soil_sub['clay']}, bulkd={soil_sub['bulk_density']}, oc%={soil_sub['oc']}, ph={soil_sub['ph']}")

    rows = []
    for i in range(len(LAYER_EDGES_CM) - 1):
        top = LAYER_EDGES_CM[i]
        bot = LAYER_EDGES_CM[i + 1]
        soil = soil_top if (top + bot) / 2 < 30.0 else soil_sub
        # rosetta_vgn takes sand/clay in PERCENT (lookup_hwsd units).
        vgn = rosetta_vgn(sand=float(soil["sand"]), clay=float(soil["clay"]))
        rows.append(build_layer_record(top, bot, soil, vgn, i))

    # Check before writing: a failed check leaves no new soils.in behind.
    validate_outputs(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_soils_in(rows, out)
    print(f"Wrote {out} ({len(rows)} layers, 0-{LAYER_EDGES_CM[-1]:g} cm)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
