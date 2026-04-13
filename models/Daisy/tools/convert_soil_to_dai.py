#!/usr/bin/env python3
"""convert_soil_to_dai.py — Convert soil texture data to Daisy .dai soil definition.

Converts HWSD, custom soil profile, or standard texture databases into Daisy's
Lisp-like horizon and column definitions. Handles unit conversions for texture
fractions, bulk density, and hydraulic parameters.

Usage:
    python convert_soil_to_dai.py \\
        --input soil_profile.csv \\
        --output my-soil.dai \\
        --site-name "MySite" \\
        --max-root-depth 100 \\
        --groundwater deep
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(df, config):
    """Validate soil profile input data."""
    errors = []

    # Check required columns
    required = ["depth_bottom"]
    for col in required:
        if col not in df.columns:
            errors.append(f"Missing required column: '{col}'")

    # Need at least one texture system
    has_usda3 = all(c in df.columns for c in ["clay", "silt", "sand"])
    has_isss4 = all(c in df.columns for c in ["clay", "silt", "fine_sand", "coarse_sand"])
    if not has_usda3 and not has_isss4:
        errors.append("Need texture columns: (clay, silt, sand) or (clay, silt, fine_sand, coarse_sand)")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    # Warnings
    for _, row in df.iterrows():
        if has_usda3:
            total = row["clay"] + row["silt"] + row["sand"]
        else:
            total = row["clay"] + row["silt"] + row["fine_sand"] + row["coarse_sand"]

        # Check if fractions or percent
        if total > 2.0 and total < 110:
            # Likely percent
            if config.get("texture_unit") is None:
                print("WARNING: Texture fractions sum > 2 — interpreting as percent, will divide by 100")
                config["texture_unit"] = "percent"
        elif total > 110:
            errors.append(f"Texture fractions sum to {total:.1f} — exceeds 100%")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    return True


def validate_outputs(horizons, column_def):
    """Validate generated Daisy soil definitions."""
    warnings = []

    for h in horizons:
        # Check texture sums
        total = sum(h["texture"].values())
        if abs(total - 1.0) > 0.02:
            warnings.append(f"Horizon '{h['name']}': texture sums to {total:.3f}, not 1.0")

        # Check bulk density
        if "dry_bulk_density" in h:
            bd = h["dry_bulk_density"]
            if bd < 0.5 or bd > 2.5:
                warnings.append(f"Horizon '{h['name']}': bulk density {bd:.2f} g/cm³ outside typical range")

        # Check depth is negative
        if h["depth"] > 0:
            warnings.append(f"Horizon '{h['name']}': depth {h['depth']} should be negative (below surface)")

    for w in warnings:
        print(f"WARNING: {w}")

    return len(warnings) == 0


# ---------------------------------------------------------------------------
# Unit conversion functions
# ---------------------------------------------------------------------------

def convert_texture(values, from_unit):
    """Convert texture fractions.

    Daisy expects fractions (0-1) for clay, silt, sand, etc.
    HWSD and many databases provide percent (0-100).
    """
    from_unit = (from_unit or "auto").lower()
    arr = np.asarray(values, dtype=float)

    if from_unit == "percent" or from_unit == "%":
        return arr / 100.0
    elif from_unit == "fraction" or from_unit == "0-1":
        return arr
    elif from_unit == "auto":
        # Auto-detect: if any value > 1.5, assume percent
        if np.any(arr > 1.5):
            print("AUTO: Interpreting texture as percent, converting to fraction")
            return arr / 100.0
        return arr
    else:
        raise ValueError(f"Unknown texture unit: {from_unit}")


def convert_bulk_density(value, from_unit):
    """Convert bulk density to g/cm³.

    Daisy expects dry_bulk_density in g/cm³.
    Common: kg/m³ (divide by 1000), g/cm³ (identity).
    """
    from_unit = (from_unit or "auto").lower()
    if from_unit in ("g/cm3", "g/cm^3", "gcm-3"):
        return value
    elif from_unit in ("kg/m3", "kg/m^3", "kgm-3"):
        return value / 1000.0
    elif from_unit == "auto":
        if value > 100:  # likely kg/m³
            return value / 1000.0
        return value
    else:
        raise ValueError(f"Unknown bulk density unit: {from_unit}")


def convert_depth(value, from_unit):
    """Convert depth to negative cm (Daisy convention: negative = below surface).

    Daisy expects horizon depths as negative values from surface.
    """
    from_unit = (from_unit or "auto").lower()
    val = float(value)

    if from_unit in ("cm_positive", "cm"):
        return -abs(val)
    elif from_unit in ("m_positive", "m"):
        return -abs(val) * 100.0
    elif from_unit in ("cm_negative",):
        return -abs(val)  # ensure negative
    elif from_unit == "auto":
        if val > 0:
            # Assume positive depth in cm
            return -val
        return val
    else:
        raise ValueError(f"Unknown depth unit: {from_unit}")


def convert_ksat(value, from_unit):
    """Convert saturated hydraulic conductivity to cm/h.

    Daisy expects K_sat in cm/h.
    Common: m/s, cm/d, mm/h.
    """
    from_unit = (from_unit or "cm/h").lower()
    if from_unit in ("cm/h", "cm/hr"):
        return value
    elif from_unit in ("m/s", "ms-1"):
        return value * 360000.0  # m/s → cm/h
    elif from_unit in ("cm/d", "cm/day"):
        return value / 24.0
    elif from_unit in ("mm/h", "mm/hr"):
        return value / 10.0
    else:
        raise ValueError(f"Unknown K_sat unit: {from_unit}")


# ---------------------------------------------------------------------------
# Soil definition generator
# ---------------------------------------------------------------------------

def generate_horizon_dai(name, texture_system, texture, humus=None,
                         dry_bulk_density=None, c_per_n=None,
                         hydraulic=None):
    """Generate a Daisy horizon definition string.

    Parameters
    ----------
    name : str
        Horizon name.
    texture_system : str
        One of "USDA3", "FAO3", "ISSS4".
    texture : dict
        Texture fractions (0-1): {clay, silt, sand} or {clay, silt, fine_sand, coarse_sand}.
    humus : float, optional
        Humus fraction (0-1).
    dry_bulk_density : float, optional
        Dry bulk density in g/cm³.
    c_per_n : float, optional
        Carbon to nitrogen ratio.
    hydraulic : str, optional
        Hydraulic model specification (e.g., "M_vG", "Cosby_et_al", "hypres").
    """
    lines = [f'(defhorizon "{name}" {texture_system}']

    if texture_system == "ISSS4":
        lines.append(f'  (clay {texture["clay"]:.3f})')
        lines.append(f'  (silt {texture["silt"]:.3f})')
        lines.append(f'  (fine_sand {texture["fine_sand"]:.3f})')
        lines.append(f'  (coarse_sand {texture["coarse_sand"]:.3f})')
    else:  # USDA3 or FAO3
        lines.append(f'  (clay {texture["clay"]:.3f})')
        lines.append(f'  (silt {texture["silt"]:.3f})')
        lines.append(f'  (sand {texture["sand"]:.3f})')

    if humus is not None:
        lines.append(f'  (humus {humus:.4f})')

    if c_per_n is not None:
        lines.append(f'  (C_per_N {c_per_n:.1f})')

    if dry_bulk_density is not None:
        lines.append(f'  (dry_bulk_density {dry_bulk_density:.2f} [g/cm^3])')

    if hydraulic is not None and hydraulic != "default":
        lines.append(f'  (hydraulic {hydraulic})')

    lines.append(")")
    return "\n".join(lines)


def generate_column_dai(site_name, horizons, max_root_depth=100,
                        groundwater="deep", organic_matter=None):
    """Generate a Daisy column definition string.

    Parameters
    ----------
    site_name : str
        Column/site name.
    horizons : list of dict
        Each with "name" and "depth" (negative cm).
    max_root_depth : float
        Maximum rooting depth in cm.
    groundwater : str
        Groundwater model: "deep", "aquitard", "fixed".
    organic_matter : dict, optional
        Organic matter initialization params.
    """
    lines = [f'(defcolumn {site_name} default']
    lines.append(f'  (Soil (MaxRootingDepth {max_root_depth:.0f} [cm])')
    lines.append(f'        (horizons')

    for h in horizons:
        lines.append(f'          ({h["depth"]:.0f} [cm] "{h["name"]}")')

    lines.append(f'        ))')

    if groundwater == "deep":
        lines.append(f'  (Groundwater deep)')
    elif groundwater == "aquitard":
        lines.append(f'  (Groundwater aquitard')
        lines.append(f'    (K_aquitard 0.050 [cm/h])')
        lines.append(f'    (Z_aquitard 200 [cm]))')
    else:
        lines.append(f'  (Groundwater {groundwater})')

    if organic_matter:
        c_input = organic_matter.get("c_input", 1400)
        root_input = organic_matter.get("root_input", 480)
        end_depth = organic_matter.get("end_depth", -20)
        lines.append(f'  (OrganicMatter original')
        lines.append(f'    (init (input {c_input} [kg C/ha/y])')
        lines.append(f'          (root {root_input} [kg C/ha/y])')
        lines.append(f'          (end {end_depth} [cm])))')

    lines.append(")")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------

def process(input_path, output_path, config):
    """Main conversion: CSV soil profile → Daisy .dai file.

    Parameters
    ----------
    input_path : str
        CSV with columns: depth_bottom, clay, silt, sand (or fine_sand, coarse_sand),
        optional: humus, dry_bulk_density, C_per_N, K_sat, etc.
    output_path : str
        Output .dai file path.
    config : dict
        site_name, max_root_depth, groundwater, texture_unit, bd_unit, depth_unit, etc.
    """
    df = pd.read_csv(input_path)

    # Validate
    validate_inputs(df, config)

    # Determine texture system
    has_isss4 = "fine_sand" in df.columns and "coarse_sand" in df.columns
    texture_system = "ISSS4" if has_isss4 else "USDA3"

    texture_unit = config.get("texture_unit", "auto")
    bd_unit = config.get("bd_unit", "auto")
    depth_unit = config.get("depth_unit", "auto")

    # Process each horizon
    site_name = config.get("site_name", "MySite")
    horizons = []
    horizon_defs = []

    for i, row in df.iterrows():
        name = row.get("name", f"{site_name} H{i+1}")

        # Convert texture
        if texture_system == "ISSS4":
            texture = {
                "clay": convert_texture(row["clay"], texture_unit)[0] if hasattr(convert_texture(row["clay"], texture_unit), '__len__') else float(convert_texture(np.array([row["clay"]]), texture_unit)[0]),
                "silt": float(convert_texture(np.array([row["silt"]]), texture_unit)[0]),
                "fine_sand": float(convert_texture(np.array([row["fine_sand"]]), texture_unit)[0]),
                "coarse_sand": float(convert_texture(np.array([row["coarse_sand"]]), texture_unit)[0]),
            }
        else:
            texture = {
                "clay": float(convert_texture(np.array([row["clay"]]), texture_unit)[0]),
                "silt": float(convert_texture(np.array([row["silt"]]), texture_unit)[0]),
                "sand": float(convert_texture(np.array([row["sand"]]), texture_unit)[0]),
            }

        # Normalize to sum = 1
        total = sum(texture.values())
        if total > 0:
            humus_frac = 0.0
            if "humus" in row and pd.notna(row["humus"]):
                humus_frac = float(convert_texture(np.array([row["humus"]]), texture_unit)[0])
            mineral_total = total
            if abs(mineral_total - 1.0) > 0.01:
                for k in texture:
                    texture[k] /= mineral_total

        # Bulk density
        bd = None
        if "dry_bulk_density" in row and pd.notna(row.get("dry_bulk_density")):
            bd = convert_bulk_density(row["dry_bulk_density"], bd_unit)

        # C/N ratio
        c_per_n = None
        if "C_per_N" in row and pd.notna(row.get("C_per_N")):
            c_per_n = float(row["C_per_N"])

        # Humus
        humus = None
        if "humus" in row and pd.notna(row.get("humus")):
            humus = float(convert_texture(np.array([row["humus"]]), texture_unit)[0])

        # Hydraulic model
        hydraulic = config.get("hydraulic", "default")

        # Depth
        depth = convert_depth(row["depth_bottom"], depth_unit)

        horizon_def = generate_horizon_dai(
            name=name,
            texture_system=texture_system,
            texture=texture,
            humus=humus,
            dry_bulk_density=bd,
            c_per_n=c_per_n,
            hydraulic=hydraulic if hydraulic != "default" else None,
        )
        horizon_defs.append(horizon_def)
        horizons.append({"name": name, "depth": depth, "texture": texture})

    # Validate outputs
    validate_outputs(horizons, None)

    # Generate column definition
    column_def = generate_column_dai(
        site_name=site_name,
        horizons=horizons,
        max_root_depth=config.get("max_root_depth", 100),
        groundwater=config.get("groundwater", "deep"),
        organic_matter=config.get("organic_matter"),
    )

    # Write output
    with open(output_path, "w") as f:
        f.write(f";;; {Path(output_path).name} --- Soil definition for {site_name}\n")
        f.write(f";;; Generated by convert_soil_to_dai.py\n\n")
        for hdef in horizon_defs:
            f.write(hdef + "\n\n")
        f.write(column_def + "\n\n")
        f.write(f";;; {Path(output_path).name} ends here.\n")

    print(f"Wrote {len(horizons)} horizons + 1 column to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert soil profile CSV to Daisy .dai soil definition")
    parser.add_argument("--input", required=True, help="Input CSV with soil horizons")
    parser.add_argument("--output", required=True, help="Output .dai file path")
    parser.add_argument("--site-name", default="MySite", help="Site/column name")
    parser.add_argument("--max-root-depth", type=float, default=100,
                        help="Maximum rooting depth in cm")
    parser.add_argument("--groundwater", default="deep",
                        choices=["deep", "aquitard", "fixed"],
                        help="Groundwater model type")
    parser.add_argument("--texture-unit", default="auto",
                        choices=["auto", "percent", "fraction"],
                        help="Input texture unit")
    parser.add_argument("--bd-unit", default="auto",
                        choices=["auto", "g/cm3", "kg/m3"],
                        help="Input bulk density unit")
    parser.add_argument("--depth-unit", default="auto",
                        choices=["auto", "cm", "m"],
                        help="Input depth unit (positive values, converted to negative)")
    parser.add_argument("--hydraulic", default="default",
                        choices=["default", "M_vG", "Cosby_et_al", "hypres"],
                        help="Hydraulic parameter model")

    args = parser.parse_args()

    config = {
        "site_name": args.site_name,
        "max_root_depth": args.max_root_depth,
        "groundwater": args.groundwater,
        "texture_unit": args.texture_unit,
        "bd_unit": args.bd_unit,
        "depth_unit": args.depth_unit,
        "hydraulic": args.hydraulic,
    }

    process(args.input, args.output, config)


if __name__ == "__main__":
    main()
