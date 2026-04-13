#!/usr/bin/env python3
"""
convert_parameters.py — Convert soil/land/catchment parameters to WSIMOD node configs.

Converts global datasets (HWSD soil data, land use maps, catchment attributes) into
WSIMOD node configuration dictionaries suitable for Model.add_nodes().

CRITICAL UNIT CONVERSIONS:
  - Area: km² → m² (× KM2_TO_M2 = 1e6)
  - Soil depth: mm → m (× MM_TO_M = 1e-3)
  - Capacity: m³ → ML (÷ ML_TO_M3 = 1000) if using ML units
  - Pollutant load: g/m² → kg/km² (× G_M2_TO_KG_KM2 = 1e3)
  - Nutrient load: mg·mm/L → kg/km² (× MGMM_L_TO_KG_KM2)

Usage:
    python convert_parameters.py --catchment-area 50.0 --area-unit km2 \\
        --soil-depth 500 --depth-unit mm \\
        --land-use '{"urban": 0.3, "rural": 0.7}' \\
        --output nodes_config.json
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Constants (mirroring wsimod.core.constants)
# ---------------------------------------------------------------------------
KM2_TO_M2 = 1e6
HA_TO_M2 = 1e4
MM_TO_M = 1e-3
ML_TO_M3 = 1000
G_M2_TO_KG_KM2 = 1e3
G_M2_TO_KG_M2 = 1e-3
MGMM_L_TO_KG_KM2 = 1e-6 * 1e3 * 1e-3 * 1e6
PCT_TO_PROP = 1 / 100

# Default surface parameters
DEFAULT_PERVIOUS = {
    "type_": "PerviousSurface",
    "surface": "rural",
    "depth": 0.5,          # m (soil depth)
    "pollutant_load": {"phosphate": 1e-7},
    "field_capacity": 0.3,
    "wilting_point": 0.12,
}

DEFAULT_IMPERVIOUS = {
    "type_": "ImperviousSurface",
    "surface": "urban",
    "pollutant_load": {"phosphate": 1e-7},
}

DEFAULT_GROWING = {
    "type_": "GrowingSurface",
    "surface": "agricultural",
    "depth": 0.6,
    "pollutant_load": {"phosphate": 2e-7, "nitrate": 5e-7},
}

# HWSD soil texture class → field capacity / wilting point
SOIL_HYDRAULIC_PARAMS = {
    "sand":       {"field_capacity": 0.12, "wilting_point": 0.05},
    "loamy_sand": {"field_capacity": 0.18, "wilting_point": 0.08},
    "sandy_loam": {"field_capacity": 0.25, "wilting_point": 0.10},
    "loam":       {"field_capacity": 0.30, "wilting_point": 0.12},
    "silt_loam":  {"field_capacity": 0.35, "wilting_point": 0.15},
    "silt":       {"field_capacity": 0.38, "wilting_point": 0.17},
    "clay_loam":  {"field_capacity": 0.36, "wilting_point": 0.20},
    "silty_clay": {"field_capacity": 0.40, "wilting_point": 0.25},
    "clay":       {"field_capacity": 0.42, "wilting_point": 0.28},
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate input arguments."""
    errors = []
    warnings = []

    if args.catchment_area <= 0:
        errors.append(f"Catchment area must be positive, got {args.catchment_area}")

    if args.soil_depth <= 0:
        errors.append(f"Soil depth must be positive, got {args.soil_depth}")

    # Parse and validate land use fractions
    try:
        land_use = json.loads(args.land_use) if args.land_use else {"rural": 1.0}
        total = sum(land_use.values())
        if abs(total - 1.0) > 0.01:
            warnings.append(
                f"Land use fractions sum to {total}, not 1.0. "
                "Will be normalized."
            )
    except json.JSONDecodeError:
        errors.append(f"Invalid JSON for --land-use: {args.land_use}")

    if args.soil_texture and args.soil_texture not in SOIL_HYDRAULIC_PARAMS:
        warnings.append(
            f"Unknown soil texture '{args.soil_texture}'. "
            f"Known: {list(SOIL_HYDRAULIC_PARAMS.keys())}. Using 'loam' defaults."
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)


def validate_outputs(result):
    """Validate generated node configs for physical reasonableness."""
    warnings = []
    nodes = result.get("nodes", [])

    for node in nodes:
        if node.get("type_") == "Land":
            for surf in node.get("surfaces", []):
                area = surf.get("area", 0)
                if area > 1e10:
                    warnings.append(
                        f"Surface '{surf.get('surface')}' area = {area:.0f} m² "
                        f"({area/1e6:.1f} km²) — verify unit conversion (dt_008)."
                    )
                if area < 1:
                    warnings.append(
                        f"Surface '{surf.get('surface')}' area = {area} m² — "
                        "suspiciously small. Did you forget km²→m² conversion?"
                    )
                depth = surf.get("depth", 0)
                if depth > 10:
                    warnings.append(
                        f"Soil depth = {depth} m — unusually deep. "
                        "Check mm→m conversion (dt_011)."
                    )

        if node.get("type_") == "Sewer":
            cap = node.get("capacity", 0)
            if cap > 1000:
                warnings.append(
                    f"Sewer capacity = {cap} m³/d — very high. "
                    "Sewer capacity is in m³/d, not ML/d (dt_006)."
                )

    return warnings


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process(args):
    """Generate WSIMOD node configuration dictionaries."""

    # Convert area to m²
    area_m2 = args.catchment_area
    if args.area_unit == "km2":
        area_m2 *= KM2_TO_M2
    elif args.area_unit == "ha":
        area_m2 *= HA_TO_M2
    # else already m2

    # Convert soil depth to m
    depth_m = args.soil_depth
    if args.depth_unit == "mm":
        depth_m *= MM_TO_M
    # else already m

    # Parse land use fractions and normalize
    land_use = json.loads(args.land_use) if args.land_use else {"rural": 1.0}
    total = sum(land_use.values())
    if total > 0:
        land_use = {k: v / total for k, v in land_use.items()}

    # Get soil hydraulic parameters
    soil_params = SOIL_HYDRAULIC_PARAMS.get(
        args.soil_texture, SOIL_HYDRAULIC_PARAMS["loam"]
    )

    # Build surfaces
    surfaces = []
    for land_type, fraction in land_use.items():
        surf_area = area_m2 * fraction
        if land_type in ("urban", "impervious"):
            surf = dict(DEFAULT_IMPERVIOUS)
            surf["area"] = surf_area
        elif land_type in ("agricultural", "crop", "growing"):
            surf = dict(DEFAULT_GROWING)
            surf["area"] = surf_area
            surf["depth"] = depth_m
            surf.update(soil_params)
        else:
            surf = dict(DEFAULT_PERVIOUS)
            surf["area"] = surf_area
            surf["depth"] = depth_m
            surf.update(soil_params)
        surfaces.append(surf)

    # Build node configs
    nodes = []

    # Land node
    land_node = {
        "type_": "Land",
        "name": args.name_prefix + "_land",
        "surfaces": surfaces,
    }
    nodes.append(land_node)

    # Groundwater node
    gw_capacity = area_m2 * depth_m * soil_params.get("field_capacity", 0.3)
    gw_node = {
        "type_": "Groundwater",
        "name": args.name_prefix + "_gw",
        "area": area_m2,
        "capacity": gw_capacity,
    }
    nodes.append(gw_node)

    # River node
    river_node = {
        "type_": "Node",
        "name": args.name_prefix + "_river",
    }
    nodes.append(river_node)

    # Waste (outlet) node
    waste_node = {
        "type_": "Waste",
        "name": args.name_prefix + "_outlet",
    }
    nodes.append(waste_node)

    # Sewer node (if urban fraction exists)
    if any(k in ("urban", "impervious") for k in land_use):
        urban_area = sum(
            area_m2 * f for k, f in land_use.items()
            if k in ("urban", "impervious")
        )
        sewer_capacity = urban_area * 0.001  # rough: 1 mm/d capacity per m²
        sewer_node = {
            "type_": "Sewer",
            "name": args.name_prefix + "_sewer",
            "capacity": sewer_capacity,
        }
        nodes.append(sewer_node)

    # Build default arcs
    arcs = [
        {"type_": "Arc", "name": f"{args.name_prefix}_percolation",
         "in_port": f"{args.name_prefix}_land",
         "out_port": f"{args.name_prefix}_gw"},
        {"type_": "Arc", "name": f"{args.name_prefix}_runoff",
         "in_port": f"{args.name_prefix}_land",
         "out_port": f"{args.name_prefix}_river"},
        {"type_": "Arc", "name": f"{args.name_prefix}_baseflow",
         "in_port": f"{args.name_prefix}_gw",
         "out_port": f"{args.name_prefix}_river"},
        {"type_": "Arc", "name": f"{args.name_prefix}_outflow",
         "in_port": f"{args.name_prefix}_river",
         "out_port": f"{args.name_prefix}_outlet"},
    ]

    # Add sewer arcs if urban
    if any(k in ("urban", "impervious") for k in land_use):
        arcs.append({
            "type_": "Arc",
            "name": f"{args.name_prefix}_urban_drain",
            "in_port": f"{args.name_prefix}_land",
            "out_port": f"{args.name_prefix}_sewer",
        })
        arcs.append({
            "type_": "Arc",
            "name": f"{args.name_prefix}_cso",
            "in_port": f"{args.name_prefix}_sewer",
            "out_port": f"{args.name_prefix}_river",
        })

    result = {
        "status": "success",
        "nodes": nodes,
        "arcs": arcs,
        "area_m2": area_m2,
        "soil_depth_m": depth_m,
        "soil_texture": args.soil_texture or "loam",
        "soil_params": soil_params,
        "land_use_fractions": land_use,
        "conversions_applied": {
            "area": f"{args.catchment_area} {args.area_unit} → {area_m2} m²",
            "depth": f"{args.soil_depth} {args.depth_unit} → {depth_m} m",
        },
    }

    # Validate outputs
    warnings = validate_outputs(result)
    if warnings:
        result["warnings"] = warnings

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert catchment parameters to WSIMOD node configurations"
    )
    parser.add_argument(
        "--catchment-area", type=float, required=True,
        help="Total catchment area"
    )
    parser.add_argument(
        "--area-unit", default="km2", choices=["km2", "ha", "m2"],
        help="Unit of catchment area (default: km2)"
    )
    parser.add_argument(
        "--soil-depth", type=float, default=500,
        help="Soil depth (default: 500 mm)"
    )
    parser.add_argument(
        "--depth-unit", default="mm", choices=["mm", "m"],
        help="Unit of soil depth (default: mm)"
    )
    parser.add_argument(
        "--soil-texture", default="loam",
        help="HWSD soil texture class (e.g., sand, loam, clay)"
    )
    parser.add_argument(
        "--land-use", default='{"rural": 1.0}',
        help='JSON dict of land use fractions, e.g. \'{"urban": 0.3, "rural": 0.7}\''
    )
    parser.add_argument(
        "--name-prefix", default="catchment",
        help="Prefix for node names (default: catchment)"
    )
    parser.add_argument(
        "--output", required=True, help="Path to output JSON file"
    )

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    summary = {
        "status": result["status"],
        "n_nodes": len(result["nodes"]),
        "n_arcs": len(result["arcs"]),
        "area_m2": result["area_m2"],
        "soil_depth_m": result["soil_depth_m"],
        "output": args.output,
    }
    if "warnings" in result:
        summary["warnings"] = result["warnings"]

    print(json.dumps(summary, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
