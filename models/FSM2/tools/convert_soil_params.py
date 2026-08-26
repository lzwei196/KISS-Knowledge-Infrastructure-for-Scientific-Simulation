#!/usr/bin/env python3
"""
Derive FSM2 soil parameters from HWSD soil texture data.

FSM2 requires clay fraction (fcly) and sand fraction (fsnd) to compute:
  - Clapp-Hornberger exponent b
  - Volumetric heat capacity of dry soil
  - Saturated soil water pressure
  - Volumetric soil moisture at saturation
  - Thermal conductivity of dry soil

This tool looks up HWSD clay/sand fractions for a given location or accepts
manual input, then generates the &params namelist block.
"""

import argparse
import sys
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# HWSD soil texture classes → clay/sand fractions
# (simplified lookup when full HWSD raster is not available)
# ---------------------------------------------------------------------------

USDA_TEXTURE_CLASSES = {
    "sand":             {"fcly": 0.05, "fsnd": 0.90},
    "loamy_sand":       {"fcly": 0.07, "fsnd": 0.82},
    "sandy_loam":       {"fcly": 0.10, "fsnd": 0.65},
    "loam":             {"fcly": 0.18, "fsnd": 0.42},
    "silt_loam":        {"fcly": 0.15, "fsnd": 0.20},
    "silt":             {"fcly": 0.05, "fsnd": 0.08},
    "sandy_clay_loam":  {"fcly": 0.27, "fsnd": 0.58},
    "clay_loam":        {"fcly": 0.34, "fsnd": 0.32},
    "silty_clay_loam":  {"fcly": 0.34, "fsnd": 0.10},
    "sandy_clay":       {"fcly": 0.42, "fsnd": 0.52},
    "silty_clay":       {"fcly": 0.47, "fsnd": 0.07},
    "clay":             {"fcly": 0.60, "fsnd": 0.20},
    "organic":          {"fcly": 0.10, "fsnd": 0.10},  # peat/organic soils
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_input(fcly: float, fsnd: float) -> list[str]:
    """Validate clay and sand fractions."""
    issues = []
    if fcly < 0 or fcly > 1:
        issues.append(f"fcly={fcly} out of range [0, 1]")
    if fsnd < 0 or fsnd > 1:
        issues.append(f"fsnd={fsnd} out of range [0, 1]")
    if fcly + fsnd > 1.01:
        issues.append(f"fcly + fsnd = {fcly + fsnd:.3f} > 1.0 (impossible)")
    if fcly + fsnd < 0.1:
        issues.append(f"fcly + fsnd = {fcly + fsnd:.3f} very low — check if organic/peat soil")
    return issues


def validate_output(params: dict) -> list[str]:
    """Check derived parameters are in physical range."""
    issues = []
    if params["b"] < 2 or params["b"] > 15:
        issues.append(f"Clapp-Hornberger b={params['b']:.2f} outside typical range [2, 15]")
    if params["Vsat"] < 0.3 or params["Vsat"] > 0.6:
        issues.append(f"Vsat={params['Vsat']:.3f} outside typical range [0.3, 0.6]")
    if params["hcap_soil"] < 1e6 or params["hcap_soil"] > 3e6:
        issues.append(f"hcap_soil={params['hcap_soil']:.2e} outside typical range [1e6, 3e6] J/K/m³")
    return issues


# ---------------------------------------------------------------------------
# Core computation (matches FSM2.F90 lines 210-215)
# ---------------------------------------------------------------------------

def compute_soil_properties(fcly: float, fsnd: float) -> dict:
    """
    Compute FSM2 soil properties from clay and sand fractions.

    Reproduces exactly the equations in FSM2.F90:
      b = 3.1 + 15.7*fcly - 0.3*fsnd
      hcap_soil = (2.128*fcly + 2.385*fsnd)*1e6 / (fcly + fsnd)
      sathh = 10**(0.17 - 0.63*fcly - 1.58*fsnd)
      Vsat = 0.505 - 0.037*fcly - 0.142*fsnd
      Vcrit = Vsat*(sathh/3.364)**(1/b)
      hcon_soil = (hcon_air**Vsat) * ((hcon_clay**fcly)*(hcon_sand**(1-fcly))**(1-Vsat))
    """
    # Constants from FSM2_MODULES.F90
    hcon_air = 0.025
    hcon_clay = 1.16
    hcon_sand = 1.57

    b = 3.1 + 15.7 * fcly - 0.3 * fsnd
    hcap_soil = (2.128 * fcly + 2.385 * fsnd) * 1e6 / (fcly + fsnd)
    sathh = 10 ** (0.17 - 0.63 * fcly - 1.58 * fsnd)
    Vsat = 0.505 - 0.037 * fcly - 0.142 * fsnd
    Vcrit = Vsat * (sathh / 3.364) ** (1.0 / b)
    hcon_soil = (hcon_air ** Vsat) * (
        (hcon_clay ** fcly) * (hcon_sand ** (1 - fcly)) ** (1 - Vsat)
    )

    return {
        "fcly": fcly,
        "fsnd": fsnd,
        "b": b,
        "hcap_soil": hcap_soil,
        "sathh": sathh,
        "Vsat": Vsat,
        "Vcrit": Vcrit,
        "hcon_soil": hcon_soil,
    }


# ---------------------------------------------------------------------------
# Generate namelist
# ---------------------------------------------------------------------------

def generate_namelist_block(fcly: float, fsnd: float) -> str:
    """Generate the &params namelist block with soil parameters."""
    return f"&params\n  fcly = {fcly}\n  fsnd = {fsnd}\n/\n"


def lookup_hwsd_fractions(lat: float, lon: float) -> tuple[float, float, dict]:
    """Look up TOPSOIL clay/sand fractions at a point from the HWSD raster.

    The module docstring has always promised "looks up HWSD clay/sand fractions
    for a given location", but until 2026-08-21 no code did it — only the manual
    `--fractions` path and the coarse USDA texture-class table existed, so every
    caller had to guess a texture class.  The real raster lookup lives in the
    shared toolkit; use it rather than re-implementing the .bil + MU_GLOBAL join.

    HWSD reports T_CLAY / T_SAND as PERCENT of the < 2 mm fraction; FSM2 wants
    fractions 0-1, so the values are divided by 100.

    Returns (fcly, fsnd, raw_hwsd_record).
    """
    from ki_tools_common.soil_utils import lookup_hwsd

    rec = lookup_hwsd(lat, lon)
    if not rec or rec.get("clay") is None or rec.get("sand") is None:
        raise RuntimeError(
            f"HWSD lookup returned no clay/sand at ({lat}, {lon}): {rec!r}. "
            "Do NOT silently fall back to a default texture — pick the texture "
            "class explicitly with --texture and say so in the run notes."
        )
    fcly = float(rec["clay"]) / 100.0
    fsnd = float(rec["sand"]) / 100.0
    print(f"HWSD at ({lat}, {lon}): mu_id={rec.get('mu_id')} "
          f"texture={rec.get('texture')} clay={rec['clay']}% sand={rec['sand']}% "
          f"-> fcly={fcly:.3f}, fsnd={fsnd:.3f}")
    return fcly, fsnd, rec


def lookup_texture_class(texture: str) -> tuple[float, float]:
    """Look up clay/sand fractions from USDA texture class name."""
    key = texture.lower().replace(" ", "_").replace("-", "_")
    if key not in USDA_TEXTURE_CLASSES:
        available = ", ".join(sorted(USDA_TEXTURE_CLASSES.keys()))
        raise ValueError(f"Unknown texture class '{texture}'. Available: {available}")
    t = USDA_TEXTURE_CLASSES[key]
    return t["fcly"], t["fsnd"]


# ---------------------------------------------------------------------------
# Main process
# ---------------------------------------------------------------------------

def convert_soil(
    fcly: float | None = None,
    fsnd: float | None = None,
    texture_class: str | None = None,
    output_file: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """
    Derive FSM2 soil parameters.

    Parameters
    ----------
    fcly, fsnd : float, optional
        Clay and sand fractions. If None, texture_class is used.
    texture_class : str, optional
        USDA soil texture class name.
    output_file : str, optional
        Path to write namelist snippet.

    Returns
    -------
    dict with derived soil properties
    """
    # Resolve input
    hwsd_record = None
    if fcly is not None and fsnd is not None:
        pass
    elif lat is not None and lon is not None:
        fcly, fsnd, hwsd_record = lookup_hwsd_fractions(lat, lon)
    elif texture_class is not None:
        fcly, fsnd = lookup_texture_class(texture_class)
        print(f"Texture class '{texture_class}': fcly={fcly}, fsnd={fsnd}")
    else:
        raise ValueError("Provide fcly+fsnd, or lat+lon (HWSD lookup), or texture_class")

    # Validate input
    issues = validate_input(fcly, fsnd)
    if issues:
        print("WARNING: Input validation issues:")
        for iss in issues:
            print(f"  - {iss}")

    # Compute
    params = compute_soil_properties(fcly, fsnd)

    # Validate output
    out_issues = validate_output(params)
    if out_issues:
        print("WARNING: Output validation issues:")
        for iss in out_issues:
            print(f"  - {iss}")

    # Report
    print(f"\nDerived FSM2 soil properties:")
    print(f"  Clay fraction (fcly):    {params['fcly']:.3f}")
    print(f"  Sand fraction (fsnd):    {params['fsnd']:.3f}")
    print(f"  Clapp-Hornberger b:      {params['b']:.2f}")
    print(f"  Heat capacity (J/K/m³):  {params['hcap_soil']:.2e}")
    print(f"  Sat. water pressure (m): {params['sathh']:.4f}")
    print(f"  Porosity Vsat:           {params['Vsat']:.3f}")
    print(f"  Critical moisture Vcrit: {params['Vcrit']:.3f}")
    print(f"  Thermal conductivity:    {params['hcon_soil']:.4f} W/m/K")

    # Write namelist
    if output_file:
        nml = generate_namelist_block(fcly, fsnd)
        Path(output_file).write_text(nml)
        print(f"\nWrote namelist block to {output_file}")

    params["issues"] = issues + out_issues
    if hwsd_record is not None:
        params["hwsd"] = hwsd_record
    return params


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Derive FSM2 soil params from clay/sand fractions")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--texture", help="USDA soil texture class (e.g. 'loam', 'sandy_clay')")
    group.add_argument("--fractions", nargs=2, type=float, metavar=("FCLY", "FSND"),
                       help="Clay and sand fractions (0-1)")
    group.add_argument("--latlon", nargs=2, type=float, metavar=("LAT", "LON"),
                       help="Look the clay/sand fractions up in HWSD at this point")
    parser.add_argument("-o", "--output", help="Output namelist file")
    args = parser.parse_args()

    if args.fractions:
        convert_soil(fcly=args.fractions[0], fsnd=args.fractions[1], output_file=args.output)
    elif args.latlon:
        convert_soil(lat=args.latlon[0], lon=args.latlon[1], output_file=args.output)
    else:
        convert_soil(texture_class=args.texture, output_file=args.output)


if __name__ == "__main__":
    main()
