#!/usr/bin/env python3
"""
convert_soil_params.py — Convert HWSD / SoilGrids data to RHESSys soil definition files.

RHESSys requires soil parameters in .def files with specific units.
This tool converts common soil databases (HWSD, SoilGrids) to that format.

CRITICAL UNIT CONVERSIONS:
  - Soil depth: cm -> m  (divide by 100)
  - Ksat: cm/hr -> m/day (multiply by 0.24)
  - Porosity: % -> fraction (divide by 100)
  - Bulk density: g/cm^3 (keep as-is, used for pedotransfer)
  - Pore size index: dimensionless (from texture via Clapp-Hornberger)

Usage:
    python convert_soil_params.py --input hwsd_extract.csv --output-dir defs/ --prefix soil_loam
    python convert_soil_params.py --sand 45 --clay 20 --silt 35 --depth 150 --output-dir defs/ --prefix soil_custom
"""

import argparse
import csv
import json
import math
import os
import sys


# ---------------------------------------------------------------------------
# Pedotransfer functions (Clapp & Hornberger 1978, Cosby et al. 1984)
# ---------------------------------------------------------------------------

# Clapp-Hornberger parameters by USDA texture class
TEXTURE_PARAMS = {
    "sand":       {"porosity": 0.395, "psi_ae": 0.121, "b": 4.05, "ksat": 176.0},
    "loamy_sand": {"porosity": 0.410, "psi_ae": 0.090, "b": 4.38, "ksat": 156.3},
    "sandy_loam": {"porosity": 0.435, "psi_ae": 0.218, "b": 4.90, "ksat": 34.1},
    "silt_loam":  {"porosity": 0.485, "psi_ae": 0.786, "b": 5.30, "ksat": 7.2},
    "loam":       {"porosity": 0.451, "psi_ae": 0.478, "b": 5.39, "ksat": 25.0},
    "sandy_clay_loam": {"porosity": 0.420, "psi_ae": 0.299, "b": 7.12, "ksat": 6.3},
    "silty_clay_loam": {"porosity": 0.477, "psi_ae": 0.356, "b": 7.75, "ksat": 1.7},
    "clay_loam":  {"porosity": 0.476, "psi_ae": 0.630, "b": 8.52, "ksat": 2.5},
    "sandy_clay": {"porosity": 0.426, "psi_ae": 0.153, "b": 10.4, "ksat": 2.2},
    "silty_clay": {"porosity": 0.492, "psi_ae": 0.490, "b": 10.4, "ksat": 1.0},
    "clay":       {"porosity": 0.482, "psi_ae": 0.405, "b": 11.4, "ksat": 0.6},
    "silt":       {"porosity": 0.489, "psi_ae": 0.759, "b": 5.15, "ksat": 5.1},
}


def classify_texture(sand_pct, clay_pct):
    """Classify USDA texture from sand/clay percentages."""
    silt_pct = 100 - sand_pct - clay_pct

    if clay_pct >= 40:
        if sand_pct >= 45:
            return "sandy_clay"
        elif silt_pct >= 40:
            return "silty_clay"
        else:
            return "clay"
    elif clay_pct >= 27:
        if sand_pct >= 20 and sand_pct < 45:
            return "clay_loam"
        elif sand_pct < 20:
            return "silty_clay_loam"
        else:
            return "sandy_clay_loam"
    elif clay_pct >= 7 and clay_pct < 27:
        if silt_pct >= 50 and clay_pct >= 12:
            return "silt_loam"
        elif silt_pct >= 50:
            return "silt_loam"
        elif sand_pct > 52:
            return "sandy_loam"
        else:
            return "loam"
    else:
        if sand_pct >= 85:
            return "sand"
        elif sand_pct >= 70:
            return "loamy_sand"
        else:
            return "sandy_loam"


def compute_ksat_cosby(sand_pct, clay_pct):
    """Estimate Ksat (cm/hr) from Cosby et al. (1984) regression."""
    # log10(Ksat) = -0.6 + 0.0126*sand - 0.0064*clay  (Ksat in inch/hr)
    log_ksat_inch = -0.6 + 0.0126 * sand_pct - 0.0064 * clay_pct
    ksat_inch_hr = 10 ** log_ksat_inch
    ksat_cm_hr = ksat_inch_hr * 2.54
    return ksat_cm_hr


def compute_porosity_cosby(sand_pct, clay_pct):
    """Estimate porosity (fraction) from Cosby et al. (1984)."""
    porosity = 0.489 - 0.00126 * sand_pct
    return max(0.2, min(0.7, porosity))


def compute_psi_air_entry(sand_pct, clay_pct):
    """Estimate psi air entry (m) from Cosby et al. (1984)."""
    # log10(psi_ae) = 1.54 - 0.0095*sand + 0.0063*silt (psi in cm)
    silt_pct = 100 - sand_pct - clay_pct
    log_psi_cm = 1.54 - 0.0095 * sand_pct + 0.0063 * silt_pct
    psi_cm = 10 ** log_psi_cm
    psi_m = psi_cm / 100.0  # Convert cm -> m
    return psi_m


def compute_pore_size_index(sand_pct, clay_pct):
    """Estimate pore size index (dimensionless) from Cosby et al. (1984)."""
    # b = 3.10 + 0.157*clay - 0.003*sand
    b = 3.10 + 0.157 * clay_pct - 0.003 * sand_pct
    # Pore size index = 1/b (Brooks-Corey)
    return 1.0 / b if b > 0 else 0.2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.input and not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.sand is not None:
        if not (0 <= args.sand <= 100):
            errors.append(f"Sand percentage must be 0-100, got {args.sand}")
        if args.clay is None:
            errors.append("Must provide --clay when using --sand")
        elif not (0 <= args.clay <= 100):
            errors.append(f"Clay percentage must be 0-100, got {args.clay}")
        elif args.sand + args.clay > 100:
            errors.append(f"Sand + clay cannot exceed 100%, got {args.sand + args.clay}")

    if args.depth is not None and args.depth <= 0:
        errors.append(f"Soil depth must be positive, got {args.depth}")

    if not args.input and args.sand is None:
        errors.append("Must provide either --input or --sand/--clay")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_output(output_path):
    """Validate the generated .def file."""
    errors = []
    warnings = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return {"status": "error", "errors": errors}

    with open(output_path) as f:
        content = f.read()

    # Check essential parameters are present
    required = ["porosity_0", "Ksat_0", "soil_depth", "pore_size_index", "psi_air_entry"]
    for param in required:
        if param not in content:
            errors.append(f"Missing required parameter: {param}")

    # Check value ranges
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                val = float(parts[0])
                name = parts[1]
                if name == "Ksat_0" and val > 200:
                    warnings.append(
                        f"UNIT TRAP: Ksat_0 = {val} m/day seems very high. "
                        f"Check cm/hr -> m/day conversion."
                    )
                if name == "porosity_0" and val > 1.0:
                    warnings.append(
                        f"UNIT TRAP: porosity_0 = {val} > 1.0. "
                        f"Likely still in %. Divide by 100."
                    )
                if name == "soil_depth" and val > 50:
                    warnings.append(
                        f"UNIT TRAP: soil_depth = {val} m seems very deep. "
                        f"Check cm -> m conversion."
                    )
            except ValueError:
                pass

    result = {"status": "ok" if not errors else "error"}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def compute_soil_params(sand_pct, clay_pct, depth_cm=None, bulk_density=None):
    """Compute RHESSys soil parameters from texture."""
    texture = classify_texture(sand_pct, clay_pct)
    params = TEXTURE_PARAMS.get(texture, TEXTURE_PARAMS["loam"])

    porosity = compute_porosity_cosby(sand_pct, clay_pct)
    ksat_cm_hr = compute_ksat_cosby(sand_pct, clay_pct)
    ksat_m_day = ksat_cm_hr * 0.24  # cm/hr -> m/day
    psi_ae_m = compute_psi_air_entry(sand_pct, clay_pct)
    pore_size_idx = compute_pore_size_index(sand_pct, clay_pct)

    soil_depth_m = (depth_cm / 100.0) if depth_cm else 2.0  # Default 2m

    # Porosity decay: typical value 4.0 (1/m)
    porosity_decay = 4.0

    # Transmissivity decay parameter m
    m_param = soil_depth_m * 0.5  # Rough heuristic

    return {
        "texture": texture,
        "soil_depth": soil_depth_m,
        "porosity_0": porosity,
        "porosity_decay": porosity_decay,
        "Ksat_0": ksat_m_day,
        "m": m_param,
        "pore_size_index": pore_size_idx,
        "psi_air_entry": psi_ae_m,
        "sand_pct": sand_pct,
        "clay_pct": clay_pct,
        "silt_pct": 100 - sand_pct - clay_pct,
    }


def write_def_file(params, output_path, def_id=1):
    """Write RHESSys soil .def file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w") as f:
        f.write(f"# RHESSys soil definition file\n")
        f.write(f"# Texture class: {params['texture']}\n")
        f.write(f"# Sand: {params['sand_pct']:.1f}%  Clay: {params['clay_pct']:.1f}%  "
                f"Silt: {params['silt_pct']:.1f}%\n")
        f.write(f"# Generated by convert_soil_params.py\n")
        f.write(f"#\n")
        f.write(f"{def_id}\t\tsoil_default_ID\n")
        f.write(f"{params['Ksat_0']:.6f}\t\tKsat_0\t\t\t(m/day)\n")
        f.write(f"{params['m']:.6f}\t\tm\t\t\t(m)\n")
        f.write(f"{params['porosity_0']:.6f}\t\tporosity_0\t\t(m3/m3)\n")
        f.write(f"{params['porosity_decay']:.6f}\t\tporosity_decay\t\t(1/m)\n")
        f.write(f"{params['pore_size_index']:.6f}\t\tpore_size_index\t\t(dimensionless)\n")
        f.write(f"{params['psi_air_entry']:.6f}\t\tpsi_air_entry\t\t(m)\n")
        f.write(f"{params['soil_depth']:.6f}\t\tsoil_depth\t\t(m)\n")
        f.write(f"0.000000\t\tm_z\t\t\t(m, depth of active zone)\n")
        f.write(f"0.120000\t\tactive_zone_z\t\t(m)\n")
        f.write(f"0.000000\t\tmax_heat_capacity\t(J/m3/K)\n")
        f.write(f"0.000000\t\tmin_heat_capacity\t(J/m3/K)\n")
        f.write(f"1.000000\t\tsoil_water_cap\t\t(m)\n")
        f.write(f"0.000000\t\tno3_adsorption_rate\t(1/day)\n")
        f.write(f"1200.000000\t\talbedo\t\t\t(fraction, dry soil)\n")

    return output_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to RHESSys .def format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", default=None, help="Input CSV with soil properties")
    parser.add_argument("--sand", type=float, default=None, help="Sand percentage (0-100)")
    parser.add_argument("--clay", type=float, default=None, help="Clay percentage (0-100)")
    parser.add_argument("--silt", type=float, default=None, help="Silt percentage (auto-computed)")
    parser.add_argument("--depth", type=float, default=None,
                        help="Soil depth in cm (will convert to m)")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--prefix", required=True, help="Output filename prefix")
    parser.add_argument("--def-id", type=int, default=1, help="Soil default ID")
    args = parser.parse_args()

    # Step 1: Validate
    validate_inputs(args)

    # Step 2: Process
    if args.input:
        # Read from CSV
        with open(args.input) as f:
            reader = csv.DictReader(f)
            for row in reader:
                normed = {k.strip().lower(): v.strip() for k, v in row.items()}
                sand = float(normed.get("sand", normed.get("sand_pct", "0")))
                clay = float(normed.get("clay", normed.get("clay_pct", "0")))
                depth = float(normed.get("depth", normed.get("soil_depth", "200")))
                params = compute_soil_params(sand, clay, depth)
                break  # Use first row
    else:
        params = compute_soil_params(args.sand, args.clay, args.depth)

    print(f"Texture class: {params['texture']}")
    print(f"Porosity: {params['porosity_0']:.3f} m3/m3")
    print(f"Ksat: {params['Ksat_0']:.4f} m/day")
    print(f"Soil depth: {params['soil_depth']:.2f} m")
    print(f"Pore size index: {params['pore_size_index']:.4f}")

    # Step 3: Write output
    output_path = os.path.join(args.output_dir, f"{args.prefix}.def")
    write_def_file(params, output_path, args.def_id)
    print(f"Wrote: {output_path}")

    # Step 4: Validate output
    result = validate_output(output_path)
    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"WARNING: {w}")
    if result.get("errors"):
        print(json.dumps(result), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"status": "ok", "output": output_path, "texture": params["texture"]}))


if __name__ == "__main__":
    main()
