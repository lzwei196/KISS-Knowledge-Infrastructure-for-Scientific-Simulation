#!/usr/bin/env python3
"""
Convert soil/hydrogeology data (HWSD, SoilGrids, GLHYMPS) to PHREEQC
EXCHANGE and SURFACE keyword blocks.

Converts:
  - CEC (cmol+/kg from HWSD) -> exchange capacity (mol/kgw for PHREEQC)
  - Clay fraction -> surface area for surface complexation
  - Mineralogy -> EQUILIBRIUM_PHASES block

Usage:
    python3 convert_soil_params.py --cec 25.0 --clay-pct 35 --porosity 0.3 \
        --output soil_params.pqi --bulk-density 1.5
"""
import argparse
import json
import os
import sys
import math

# Typical mineral assemblages by soil texture class
MINERAL_ASSEMBLAGES = {
    "sandy": {
        "Quartz": {"si": 0.0, "moles": 100.0},
        "K-feldspar": {"si": 0.0, "moles": 5.0},
        "Kaolinite": {"si": 0.0, "moles": 1.0},
    },
    "loamy": {
        "Quartz": {"si": 0.0, "moles": 50.0},
        "K-feldspar": {"si": 0.0, "moles": 10.0},
        "Calcite": {"si": 0.0, "moles": 5.0},
        "Kaolinite": {"si": 0.0, "moles": 5.0},
        "Illite": {"si": 0.0, "moles": 3.0},
    },
    "clayey": {
        "Quartz": {"si": 0.0, "moles": 20.0},
        "Calcite": {"si": 0.0, "moles": 5.0},
        "Kaolinite": {"si": 0.0, "moles": 10.0},
        "Illite": {"si": 0.0, "moles": 8.0},
        "Montmorillonite": {"si": 0.0, "moles": 5.0},
    },
    "organic": {
        "Quartz": {"si": 0.0, "moles": 10.0},
        "Calcite": {"si": 0.0, "moles": 2.0},
        "Fe(OH)3(a)": {"si": 0.0, "moles": 1.0},
    },
}

# Surface complexation parameters
# Surface area (m2/g) for common adsorbents
SURFACE_PARAMS = {
    "Hfo": {  # Hydrous ferric oxide (ferrihydrite)
        "strong_sites": 0.005,  # mol/mol Fe
        "weak_sites": 0.2,     # mol/mol Fe
        "surface_area": 600.0,  # m2/g
        "mass_g": 0.09,        # g per L (default)
    },
    "Kaolinite": {
        "sites": 0.01,  # mol/mol
        "surface_area": 20.0,  # m2/g
    },
    "Montmorillonite": {
        "sites": 0.05,
        "surface_area": 750.0,
    },
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.cec is not None and args.cec < 0:
        errors.append(f"CEC must be >= 0, got {args.cec}")
    if args.clay_pct is not None and not (0 <= args.clay_pct <= 100):
        errors.append(f"Clay percentage must be 0-100, got {args.clay_pct}")
    if args.porosity is not None and not (0 < args.porosity < 1):
        errors.append(f"Porosity must be 0-1, got {args.porosity}")
    if args.bulk_density is not None and not (0.5 < args.bulk_density < 3.0):
        errors.append(f"Bulk density must be 0.5-3.0 g/cm3, got {args.bulk_density}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def cec_to_exchange_mol(cec_cmol_kg, bulk_density, porosity):
    """
    Convert CEC from cmol+/kg (HWSD units) to mol per kg water (PHREEQC EXCHANGE units).

    CEC [cmol+/kg soil] * bulk_density [kg/L] / (porosity * water_density [kg/L]) / 100
    = mol exchange sites per kg water

    TRAP: HWSD CEC is in cmol(+)/kg = meq/100g. Must divide by 100 to get mol/kg soil,
    then convert soil mass to water mass via bulk density and porosity.
    """
    # cmol+/kg -> mol/kg soil
    cec_mol_per_kg_soil = cec_cmol_kg / 100.0

    # mol/kg soil -> mol/L pore volume
    # soil mass per L bulk = bulk_density (kg/L of bulk volume)
    # pore volume per L bulk = porosity (L water / L bulk)
    # water mass per L bulk = porosity * 1.0 (kg/L water density)
    cec_mol_per_kgw = cec_mol_per_kg_soil * bulk_density / porosity

    return cec_mol_per_kgw


def classify_texture(clay_pct, sand_pct=None):
    """Classify soil texture for mineral assemblage selection."""
    if clay_pct > 40:
        return "clayey"
    elif clay_pct > 20:
        return "loamy"
    elif clay_pct <= 10:
        return "sandy"
    else:
        return "loamy"


def estimate_surface_area(clay_pct):
    """Estimate specific surface area (m2/g) from clay content."""
    # Empirical: ~7.5 m2/g per % clay (Petersen et al., 1996)
    return clay_pct * 7.5


def process(args):
    """Generate PHREEQC EXCHANGE, SURFACE, and EQUILIBRIUM_PHASES blocks."""
    results = {
        "status": "success",
        "blocks": [],
        "conversions": [],
        "warnings": [],
    }

    output_lines = []
    porosity = args.porosity if args.porosity else 0.3
    bulk_density = args.bulk_density if args.bulk_density else 1.5

    # --- EXCHANGE block ---
    if args.cec is not None:
        cec_mol = cec_to_exchange_mol(args.cec, bulk_density, porosity)
        results["conversions"].append({
            "parameter": "CEC",
            "input_value": args.cec,
            "input_unit": "cmol+/kg",
            "output_value": round(cec_mol, 6),
            "output_unit": "mol/kgw",
            "formula": "CEC/100 * bulk_density / porosity",
        })

        output_lines.append("EXCHANGE 1")
        output_lines.append(f"    # CEC = {args.cec} cmol+/kg -> {cec_mol:.6f} mol/kgw")
        output_lines.append(f"    # bulk_density = {bulk_density} g/cm3, porosity = {porosity}")
        output_lines.append(f"    X    {cec_mol:.6f}")
        output_lines.append(f"    -equilibrate  1  # equilibrate with solution 1")
        output_lines.append("")
        results["blocks"].append("EXCHANGE")

    # --- SURFACE block ---
    if args.clay_pct is not None and args.clay_pct > 5:
        ssa = estimate_surface_area(args.clay_pct)
        # Assume some HFO present if clay > 10%
        hfo_mass_g = 0.09 * (args.clay_pct / 30.0)  # scale HFO with clay
        hfo_strong = SURFACE_PARAMS["Hfo"]["strong_sites"] * hfo_mass_g / 89.0 * 1000
        hfo_weak = SURFACE_PARAMS["Hfo"]["weak_sites"] * hfo_mass_g / 89.0 * 1000

        output_lines.append("SURFACE 1")
        output_lines.append(f"    # Clay {args.clay_pct}%, SSA ~ {ssa:.1f} m2/g")
        output_lines.append(f"    # HFO mass ~ {hfo_mass_g:.4f} g/L")
        output_lines.append(f"    Hfo_sOH   {hfo_strong:.6f}  {SURFACE_PARAMS['Hfo']['surface_area']:.1f}  {hfo_mass_g:.4f}")
        output_lines.append(f"    Hfo_wOH   {hfo_weak:.6f}")
        output_lines.append(f"    -equilibrate  1")
        output_lines.append("")
        results["blocks"].append("SURFACE")

        results["conversions"].append({
            "parameter": "Clay to HFO surface",
            "input_value": args.clay_pct,
            "input_unit": "%",
            "output_value": round(hfo_mass_g, 4),
            "output_unit": "g/L",
        })

    # --- EQUILIBRIUM_PHASES block ---
    if args.clay_pct is not None or args.texture:
        texture = args.texture if args.texture else classify_texture(
            args.clay_pct if args.clay_pct else 20
        )
        minerals = MINERAL_ASSEMBLAGES.get(texture, MINERAL_ASSEMBLAGES["loamy"])

        output_lines.append("EQUILIBRIUM_PHASES 1")
        output_lines.append(f"    # Texture class: {texture}")
        for mineral, params in minerals.items():
            output_lines.append(f"    {mineral:20s}  {params['si']:.1f}  {params['moles']:.1f}")
        output_lines.append("")
        results["blocks"].append("EQUILIBRIUM_PHASES")

    # --- TRANSPORT block (if dispersivity provided) ---
    if args.dispersivity is not None:
        # TRAP: dispersivity must be in meters, not cm
        disp_m = args.dispersivity
        if disp_m > 100:
            results["warnings"].append(
                f"Dispersivity {disp_m} m seems very large. Check if input is in cm (should be m)."
            )

        ncells = args.cells if args.cells else 20
        length = args.length if args.length else 1.0
        dx = length / ncells
        peclet = dx / disp_m if disp_m > 0 else float("inf")

        if peclet < 2:
            results["warnings"].append(
                f"Grid Peclet number = {peclet:.2f} < 2. Numerical dispersion may dominate. "
                f"Increase cells or decrease dispersivity."
            )

        output_lines.append("TRANSPORT")
        output_lines.append(f"    -cells          {ncells}")
        output_lines.append(f"    -lengths        {dx:.6f}   # {length} m / {ncells} cells")
        output_lines.append(f"    -dispersivities {disp_m:.6f}  # meters")
        output_lines.append(f"    -porosity       {porosity}")
        output_lines.append(f"    -shifts         {ncells * 2}")
        output_lines.append(f"    -time_step      {3600.0}  # seconds")
        output_lines.append(f"    -flow_direction forward")
        output_lines.append(f"    -boundary_conditions flux  flux")
        output_lines.append(f"    -diffusion_coefficient  1.0e-9")
        output_lines.append(f"    -print_cells    {ncells}")
        output_lines.append(f"    -print_frequency {max(1, ncells // 10)}")
        output_lines.append("")
        results["blocks"].append("TRANSPORT")

    output_text = "\n".join(output_lines) + "\n"
    return results, output_text


def validate_outputs(results, output_text):
    """Post-processing validation."""
    if not results["blocks"]:
        results["warnings"].append("No parameter blocks generated. Provide --cec or --clay-pct.")

    results["summary"] = {
        "blocks_generated": results["blocks"],
        "output_lines": len(output_text.splitlines()),
        "conversions": len(results["conversions"]),
    }
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/hydrogeology parameters to PHREEQC input blocks"
    )
    parser.add_argument("--cec", type=float, default=None,
                        help="Cation exchange capacity (cmol+/kg, HWSD units)")
    parser.add_argument("--clay-pct", type=float, default=None,
                        help="Clay content (percent, 0-100)")
    parser.add_argument("--porosity", type=float, default=0.3,
                        help="Soil porosity (0-1, default 0.3)")
    parser.add_argument("--bulk-density", type=float, default=1.5,
                        help="Bulk density (g/cm3, default 1.5)")
    parser.add_argument("--dispersivity", type=float, default=None,
                        help="Dispersivity in meters for transport block")
    parser.add_argument("--cells", type=int, default=20,
                        help="Number of cells for transport (default 20)")
    parser.add_argument("--length", type=float, default=1.0,
                        help="Domain length in meters (default 1.0)")
    parser.add_argument("--texture", default=None, choices=["sandy", "loamy", "clayey", "organic"],
                        help="Override texture classification")
    parser.add_argument("--output", required=True,
                        help="Output PHREEQC input file")
    parser.add_argument("--json-output", default=None,
                        help="Path for JSON result summary")

    args = parser.parse_args()
    validate_inputs(args)
    results, output_text = process(args)
    results = validate_outputs(results, output_text)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(output_text)
    print(f"Wrote {len(results['blocks'])} blocks to {args.output}", file=sys.stderr)

    if args.json_output:
        os.makedirs(os.path.dirname(args.json_output) or ".", exist_ok=True)
        with open(args.json_output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
