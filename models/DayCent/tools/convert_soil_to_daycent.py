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
    7: root fraction     (0..1, sums to 1.0 across layers)
    8: sand fraction     (0..1)
    9: clay fraction     (0..1)
   10: organic matter    (fraction of mass, 0..1)  ← MUST be fraction, NOT percent
   11: delta_min         (minimum volumetric water content, ~WP×0.9)
   12: saturated K       (cm/sec)
   13: pH                (unitless)

BUG FIX (2026-04-22, from AT-Neu + US-Var FLUXNET runs):
  - Added column 11 (delta_min). Without it DayCent reads Ksat into the
    delta_min slot, producing "swclimit[1] is negative" errors.
  - Fixed OM threshold: values 0.5-1.5 (typical HWSD OC%) were not converted
    to fraction. Now any OM > 0.2 is treated as percent and divided by 100.

HWSD provides texture and bulk density at two depths (topsoil 0-30, subsoil
30-100). We expand into 13 layers using the same layering as the Wooster
example (0-2, 2-5, 5-10, 10-20, 20-30, 30-45, 45-60, 60-75, 75-90, 90-105,
105-120, 120-150, 150-180 cm) and run ROSETTA on each layer texture to fill
field capacity, wilting point, and Ksat.

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


# Layering used by the Wooster reference run (cm)
LAYER_EDGES_CM = [0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0,
                  75.0, 90.0, 105.0, 120.0, 150.0, 180.0]

# Root-fraction template (decreases exponentially) — sums to 1.0
ROOT_FRACTION_TEMPLATE = [0.01, 0.04, 0.25, 0.30, 0.10, 0.05, 0.04, 0.03,
                          0.02, 0.01, 0.0, 0.0, 0.0]

# Evap coefficient template — strongest near surface
EVAP_COEFF_TEMPLATE = [0.80, 0.20, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
                       0.00, 0.00, 0.00, 0.00, 0.00]


def validate_inputs(lat, lon):
    if not (-90.0 <= lat <= 90.0):
        raise ValueError(f"lat out of range: {lat}")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError(f"lon out of range: {lon}")


def build_layer_record(top, bot, soil, vgn, idx):
    """Assemble one row for soils.in."""
    bulkd = soil.get("bulk_density", soil.get("bulkd", 1.30))
    if bulkd > 100.0:  # almost certainly kg/m³ (HWSD raw)
        bulkd = bulkd / 1000.0
    sand = soil.get("sand", 0.40)
    clay = soil.get("clay", 0.20)
    if sand > 1.5:  # percent → fraction
        sand /= 100.0
    if clay > 1.5:
        clay /= 100.0
    om = soil.get("om", soil.get("oc", 0.02))
    if om > 0.2:  # HWSD OC is typically 0.5-5.0 percent; fraction would be 0.005-0.05
        om /= 100.0
    ph = soil.get("ph", 6.5)

    fc = vgn.get("field_capacity", vgn.get("fc", 0.30))
    wp = vgn.get("wilting_point", vgn.get("wp", 0.13))
    ksat_cm_sec = vgn.get("Ksat_cm_per_sec",
                          vgn.get("ksat", 0.0005))

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
    if len(rows) < 5:
        raise RuntimeError(f"only {len(rows)} layers produced — expected 13")
    if len(rows[0]) != 13:
        raise RuntimeError(f"each row must have 13 columns, got {len(rows[0])}")
    root_sum = sum(r[6] for r in rows)
    if not (0.95 <= root_sum <= 1.05):
        print(f"WARN: root fraction sum = {root_sum:.3f} (expected ~1.0)")
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

    # Build topsoil and subsoil dicts from the single HWSD return
    soil_top = {
        "sand": hwsd.get("sand", 40.0),
        "silt": hwsd.get("silt", 40.0),
        "clay": hwsd.get("clay", 20.0),
        "bulk_density": hwsd.get("bulk_density", 1.30),
        "oc": hwsd.get("oc", 1.0),
        "om": hwsd.get("oc", 1.0),
        "ph": hwsd.get("ph", 6.5),
    }
    soil_sub = {
        "sand": hwsd.get("sub_sand", soil_top["sand"]),
        "silt": hwsd.get("sub_silt", soil_top["silt"]),
        "clay": hwsd.get("sub_clay", soil_top["clay"]),
        "bulk_density": hwsd.get("bulk_density", 1.30),
        "oc": hwsd.get("oc", 1.0) * 0.5,  # subsoil OC typically lower
        "om": hwsd.get("oc", 1.0) * 0.5,
        "ph": hwsd.get("ph", 6.5),
    }
    print(f"  topsoil: sand={soil_top['sand']}, clay={soil_top['clay']}, bulkd={soil_top['bulk_density']}, ph={soil_top['ph']}")
    print(f"  subsoil: sand={soil_sub['sand']}, clay={soil_sub['clay']}")

    rows = []
    for i in range(len(LAYER_EDGES_CM) - 1):
        top = LAYER_EDGES_CM[i]
        bot = LAYER_EDGES_CM[i + 1]
        soil = soil_top if (top + bot) / 2 < 30.0 else soil_sub
        # ROSETTA prefers fractions; soil dict may carry percentages
        sand = soil.get("sand", 0.40)
        clay = soil.get("clay", 0.20)
        if sand > 1.5:
            sand /= 100.0
        if clay > 1.5:
            clay /= 100.0
        vgn = rosetta_vgn(sand=sand, clay=clay)
        rows.append(build_layer_record(top, bot, soil, vgn, i))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_soils_in(rows, out)
    print(f"Wrote {out} ({len(rows)} layers)")
    validate_outputs(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
