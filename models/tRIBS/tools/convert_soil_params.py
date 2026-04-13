#!/usr/bin/env python3
"""Convert soil and land-use data to tRIBS parameter tables.

Supports: HWSD (Harmonized World Soil Database), SSURGO, and generic CSV.
Produces: Soil reclassification table (.sdt) and land-use table (.ldt).

tRIBS soil table (.sdt) columns:
  ID  Ks(mm/hr)  ThetaS  ThetaR  PsiB(mm)  PoreSize  Conductivity  Residual
  Porosity  VolHeatCond  SoilHeatCap  ...

tRIBS land-use table (.ldt) columns:
  ID  a  b1  P  S  K  bv  LAI  ...

Usage:
  python convert_soil_params.py \\
      --source hwsd \\
      --input /path/to/hwsd_data.csv \\
      --output /path/to/tables/ \\
      --sdt-file soil_params.sdt \\
      --ldt-file landuse_params.ldt
"""

import argparse
import csv
import json
import math
import os
import sys


# ---------------------------------------------------------------------------
# Unit-conversion helpers for soil parameters
# ---------------------------------------------------------------------------

def ks_ms_to_mmhr(ks_ms):
    """Convert saturated hydraulic conductivity from m/s to mm/hr.

    CRITICAL: HWSD reports Ks in m/s. tRIBS expects mm/hr.
    1 m/s = 3,600,000 mm/hr = 3.6e6 mm/hr.

    Common trap: forgetting this conversion gives Ks values like 1e-6 mm/hr,
    which means essentially zero infiltration and 100% surface runoff.
    """
    return ks_ms * 3.6e6


def depth_m_to_mm(depth_m):
    """Convert soil depth from meters to millimeters.

    CRITICAL: HWSD reports depths in meters. tRIBS expects mm.
    Forgetting gives a soil column of ~1mm depth, causing immediate
    saturation and unrealistic runoff.
    """
    return depth_m * 1000.0


def porosity_pct_to_frac(porosity_pct):
    """Convert porosity from percent to fraction (0–1)."""
    return porosity_pct / 100.0


def bulk_density_to_porosity(bd_gcc):
    """Estimate porosity from bulk density (g/cm³).

    porosity = 1 - (bulk_density / particle_density)
    Assumes particle density = 2.65 g/cm³ (quartz).
    """
    return 1.0 - (bd_gcc / 2.65)


def saxton_ks(sand_pct, clay_pct):
    """Estimate Ks (mm/hr) from sand and clay percentage using Saxton & Rawls (2006).

    Simplified pedotransfer function.
    """
    sand = sand_pct / 100.0
    clay = clay_pct / 100.0
    # Saxton-Rawls approximation
    lam = math.exp(-4.396 - 0.0715 * clay_pct -
                   4.88e-4 * sand_pct**2 - 4.285e-5 * sand_pct**2 * clay_pct)
    ks_cm_hr = lam * 2.54  # approximate conversion
    return max(0.01, ks_cm_hr * 10.0)  # cm/hr → mm/hr


def saxton_psi_b(sand_pct, clay_pct):
    """Estimate air-entry pressure PsiB (mm) from texture using Saxton & Rawls."""
    # Simplified Clapp-Hornberger based on texture
    psi_cm = math.exp(1.88 - 0.013 * sand_pct)
    return psi_cm * 10.0  # cm → mm


def pore_size_index(sand_pct, clay_pct):
    """Estimate Brooks-Corey pore-size distribution index."""
    return max(0.1, 0.2 + 0.005 * sand_pct - 0.006 * clay_pct)


# ---------------------------------------------------------------------------
# HWSD texture class defaults
# ---------------------------------------------------------------------------

HWSD_TEXTURE_DEFAULTS = {
    # class: (sand%, clay%, Ks_mm_hr, ThetaS, ThetaR, PsiB_mm, PoreSize)
    "sand":          (92, 3,  120.0, 0.43, 0.02, 72.6,  0.59),
    "loamy_sand":    (82, 6,   60.0, 0.41, 0.04, 86.9,  0.47),
    "sandy_loam":    (65, 11,  26.0, 0.41, 0.04, 146.6, 0.38),
    "loam":          (42, 20,  13.2, 0.43, 0.03, 111.5, 0.25),
    "silt_loam":     (20, 15,   6.8, 0.45, 0.02, 207.6, 0.23),
    "silt":          (8,  5,    6.0, 0.46, 0.02, 250.0, 0.20),
    "sandy_clay_loam": (58, 27, 4.3, 0.39, 0.07, 280.8, 0.32),
    "clay_loam":     (32, 34,   2.3, 0.41, 0.06, 258.8, 0.24),
    "silty_clay_loam": (10, 34, 1.5, 0.43, 0.05, 325.6, 0.18),
    "sandy_clay":    (52, 42,   1.2, 0.38, 0.10, 292.2, 0.22),
    "silty_clay":    (8,  47,   0.9, 0.36, 0.07, 340.0, 0.15),
    "clay":          (22, 58,   0.6, 0.38, 0.09, 373.0, 0.17),
}

LANDUSE_DEFAULTS = {
    # class: (a, b1, P, S, K, bv, LAI)
    "evergreen_forest": (0.5, 0.8, 2.0, 0.5, 0.1, 0.5, 5.0),
    "deciduous_forest": (0.5, 0.8, 2.0, 0.5, 0.1, 0.5, 4.0),
    "mixed_forest":     (0.5, 0.8, 2.0, 0.5, 0.1, 0.5, 4.5),
    "grassland":        (0.2, 0.4, 1.0, 0.3, 0.05, 0.3, 2.0),
    "shrubland":        (0.3, 0.6, 1.5, 0.4, 0.08, 0.4, 2.5),
    "cropland":         (0.3, 0.5, 1.5, 0.4, 0.07, 0.4, 3.0),
    "urban":            (0.1, 0.1, 0.5, 0.1, 0.02, 0.1, 0.5),
    "water":            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "barren":           (0.1, 0.2, 0.5, 0.2, 0.03, 0.2, 0.5),
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Pre-flight validation."""
    errors = []
    if not os.path.exists(args.input):
        errors.append(f"Input path does not exist: {args.input}")
    if args.source not in ("hwsd", "ssurgo", "csv"):
        errors.append(f"Unsupported source: {args.source}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_sdt(sdt_path):
    """Validate generated soil table."""
    warnings = []
    if not os.path.isfile(sdt_path):
        warnings.append(f"SDT file not created: {sdt_path}")
        return warnings

    with open(sdt_path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines[1:], start=2):  # Skip header
        parts = line.strip().split()
        if len(parts) < 7:
            warnings.append(f"SDT line {i}: too few columns ({len(parts)})")
            continue
        ks = float(parts[1])
        theta_s = float(parts[2])
        theta_r = float(parts[3])

        if ks < 0.001:
            warnings.append(
                f"SDT line {i}: Ks={ks} mm/hr is extremely low. "
                "Check m/s → mm/hr conversion (×3.6e6)."
            )
        if ks > 1000:
            warnings.append(f"SDT line {i}: Ks={ks} mm/hr is very high.")
        if theta_s > 1.0 or theta_s < 0.0:
            warnings.append(
                f"SDT line {i}: ThetaS={theta_s} out of range. "
                "Check if porosity is in % instead of fraction."
            )
        if theta_r >= theta_s:
            warnings.append(
                f"SDT line {i}: ThetaR ({theta_r}) >= ThetaS ({theta_s})."
            )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


# ---------------------------------------------------------------------------
# Readers / processors
# ---------------------------------------------------------------------------

def read_hwsd_csv(input_path):
    """Read HWSD-format CSV and produce soil parameter records.

    Expected columns: ID, TEXTURE (or SAND%, CLAY%, SILT%),
    optionally: Ks_m_s, DEPTH_m, BULK_DENSITY, etc.
    """
    records = []
    with open(input_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = {"ID": int(row.get("ID", len(records) + 1))}

            # Try texture class first
            texture = row.get("TEXTURE", "").lower().replace(" ", "_")
            if texture in HWSD_TEXTURE_DEFAULTS:
                sand, clay, ks, ts, tr, psi, pore = HWSD_TEXTURE_DEFAULTS[texture]
                rec["Ks"] = ks
                rec["ThetaS"] = ts
                rec["ThetaR"] = tr
                rec["PsiB"] = psi
                rec["PoreSize"] = pore
            else:
                # Use sand/clay percentages with pedotransfer
                sand = float(row.get("SAND", row.get("sand_pct", 50)))
                clay = float(row.get("CLAY", row.get("clay_pct", 20)))

                # If Ks is provided in m/s, convert
                if "Ks_m_s" in row or "KS" in row:
                    ks_raw = float(row.get("Ks_m_s", row.get("KS", 1e-5)))
                    rec["Ks"] = ks_ms_to_mmhr(ks_raw)
                else:
                    rec["Ks"] = saxton_ks(sand, clay)

                rec["ThetaS"] = float(row.get("POROSITY", 0.43))
                if rec["ThetaS"] > 1.0:
                    rec["ThetaS"] = porosity_pct_to_frac(rec["ThetaS"])
                rec["ThetaR"] = float(row.get("THETA_R", 0.04))
                rec["PsiB"] = saxton_psi_b(sand, clay)
                rec["PoreSize"] = pore_size_index(sand, clay)

            # Depth conversions
            if "DEPTH_m" in row:
                rec["Depth_mm"] = depth_m_to_mm(float(row["DEPTH_m"]))
            else:
                rec["Depth_mm"] = float(row.get("DEPTH_mm", 1000.0))

            records.append(rec)

    return records


def generate_default_sdt():
    """Generate default soil table from HWSD texture classes."""
    records = []
    for i, (texture, vals) in enumerate(HWSD_TEXTURE_DEFAULTS.items(), start=1):
        sand, clay, ks, ts, tr, psi, pore = vals
        records.append({
            "ID": i,
            "Ks": ks,
            "ThetaS": ts,
            "ThetaR": tr,
            "PsiB": psi,
            "PoreSize": pore,
            "Depth_mm": 1500.0,
        })
    return records


def generate_default_ldt():
    """Generate default land-use table."""
    records = []
    for i, (lu_class, vals) in enumerate(LANDUSE_DEFAULTS.items(), start=1):
        a, b1, p, s, k, bv, lai = vals
        records.append({
            "ID": i,
            "a": a, "b1": b1, "P": p, "S": s, "K": k, "bv": bv, "LAI": lai,
            "name": lu_class,
        })
    return records


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_sdt(records, output_path):
    """Write tRIBS soil reclassification table (.sdt)."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("ID\tKs\tThetaS\tThetaR\tPsiB\tPoreSize\tConductivity\tResidual\n")
        for r in records:
            f.write(
                f"{r['ID']}\t{r['Ks']:.4f}\t{r['ThetaS']:.4f}\t"
                f"{r['ThetaR']:.4f}\t{r['PsiB']:.2f}\t{r['PoreSize']:.4f}\t"
                f"{r['Ks']:.4f}\t{r['ThetaR']:.4f}\n"
            )


def write_ldt(records, output_path):
    """Write tRIBS land-use table (.ldt)."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("ID\ta\tb1\tP\tS\tK\tbv\tLAI\n")
        for r in records:
            f.write(
                f"{r['ID']}\t{r['a']:.4f}\t{r['b1']:.4f}\t"
                f"{r['P']:.4f}\t{r['S']:.4f}\t{r['K']:.4f}\t"
                f"{r['bv']:.4f}\t{r['LAI']:.4f}\n"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/land-use data to tRIBS parameter tables."
    )
    parser.add_argument("--source", required=True,
                        choices=["hwsd", "ssurgo", "csv"],
                        help="Source data type")
    parser.add_argument("--input", required=True,
                        help="Input file or directory")
    parser.add_argument("--output", required=True,
                        help="Output directory")
    parser.add_argument("--sdt-file", default="soil_params.sdt",
                        help="Soil table filename")
    parser.add_argument("--ldt-file", default="landuse_params.ldt",
                        help="Land-use table filename")
    parser.add_argument("--use-defaults", action="store_true",
                        help="Generate default tables from texture classes")
    parser.add_argument("--json-output", type=str, default=None,
                        help="Write result summary to JSON file")

    args = parser.parse_args()

    # --- Validate inputs ---
    if not args.use_defaults:
        validate_inputs(args)

    os.makedirs(args.output, exist_ok=True)
    sdt_path = os.path.join(args.output, args.sdt_file)
    ldt_path = os.path.join(args.output, args.ldt_file)

    # --- Process soil data ---
    if args.use_defaults:
        soil_records = generate_default_sdt()
    elif os.path.isfile(args.input):
        soil_records = read_hwsd_csv(args.input)
    else:
        soil_records = generate_default_sdt()

    write_sdt(soil_records, sdt_path)

    # --- Process land-use data ---
    lu_records = generate_default_ldt()
    write_ldt(lu_records, ldt_path)

    # --- Validate outputs ---
    warnings = validate_sdt(sdt_path)

    result = {
        "status": "success",
        "sdt_file": sdt_path,
        "ldt_file": ldt_path,
        "n_soil_classes": len(soil_records),
        "n_landuse_classes": len(lu_records),
        "warnings": warnings,
    }

    output_json = json.dumps(result, indent=2)
    if args.json_output:
        with open(args.json_output, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
