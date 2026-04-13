#!/usr/bin/env python3
"""Build GemPy structural frame parameters from a JSON configuration.

Reads a structural configuration file and validates it for use with GemPy's
map_stack_to_surfaces API and fault relations. Produces a validated JSON
config that can be consumed by the execution wrapper.

Usage:
  python build_structural_params.py \
      --config structural_config.json \
      --surface-points gempy_input/surface_points.csv \
      --output structural_params.json

  python build_structural_params.py \
      --config structural_config.json \
      --validate-only

Example config (structural_config.json):
  {
    "project_name": "test_model",
    "extent": [0, 2000, 0, 2000, -1000, 0],
    "resolution": [50, 50, 50],
    "refinement": 6,
    "interpolation_type": "octree",
    "structural_groups": [
      {
        "name": "Fault_Series",
        "type": "fault",
        "surfaces": ["Main_Fault"],
        "fault_relations": {"Strat_Series": true}
      },
      {
        "name": "Strat_Series",
        "type": "erode",
        "surfaces": ["Sandstone", "Siltstone", "Shale", "Basement"]
      }
    ],
    "nugget_surface_points": 0.00002,
    "nugget_orientations": 0.01
  }
"""

import argparse
import csv
import json
import os
import sys


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.isfile(args.config):
        errors.append(f"Config file not found: {args.config}")

    if args.surface_points and not os.path.isfile(args.surface_points):
        errors.append(f"Surface points file not found: {args.surface_points}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def load_config(config_path):
    """Load and parse the structural configuration JSON."""
    with open(config_path, "r") as f:
        config = json.load(f)
    return config


def validate_config(config):
    """Validate structural configuration completeness and consistency."""
    errors = []
    warnings = []

    # Required top-level fields
    required = ["project_name", "extent", "structural_groups"]
    for field in required:
        if field not in config:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors, warnings

    # Validate extent
    extent = config["extent"]
    if not isinstance(extent, list) or len(extent) != 6:
        errors.append("extent must be a list of 6 values: [xmin, xmax, ymin, ymax, zmin, zmax]")
    else:
        if extent[0] >= extent[1]:
            errors.append(f"extent x_min ({extent[0]}) >= x_max ({extent[1]})")
        if extent[2] >= extent[3]:
            errors.append(f"extent y_min ({extent[2]}) >= y_max ({extent[3]})")
        if extent[4] >= extent[5]:
            errors.append(
                f"extent z_min ({extent[4]}) >= z_max ({extent[5]}). "
                "TRAP dt_005: Z-axis must have min < max"
            )
        # Check for suspiciously small extents
        x_range = extent[1] - extent[0]
        y_range = extent[3] - extent[2]
        if x_range < 10 or y_range < 10:
            warnings.append(
                f"Very small extent ({x_range} x {y_range}). "
                "TRAP dt_001: Are coordinates in km? GemPy expects meters."
            )

    # Validate resolution/refinement
    if "resolution" in config and "refinement" in config:
        warnings.append(
            "Both resolution and refinement specified. "
            "refinement is for OCTREE, resolution for DENSE grid."
        )

    interp_type = config.get("interpolation_type", "octree")
    if interp_type == "octree":
        ref = config.get("refinement", 6)
        if ref < 1 or ref > 10:
            errors.append(f"refinement must be 1-10, got {ref}")
        if ref > 8:
            warnings.append(
                f"refinement={ref} is very high — may be slow/memory-intensive"
            )
    elif interp_type == "dense":
        res = config.get("resolution", [50, 50, 50])
        if not isinstance(res, list) or len(res) != 3:
            errors.append("resolution must be [nx, ny, nz]")
        else:
            total_cells = res[0] * res[1] * res[2]
            if total_cells > 1e7:
                warnings.append(
                    f"Dense grid has {total_cells:.0e} cells — may cause OOM. "
                    "TRAP dt_014: Consider OCTREE or lower resolution."
                )

    # Validate structural groups
    groups = config["structural_groups"]
    if not groups:
        errors.append("At least one structural group is required")
    else:
        all_surfaces = []
        group_names = []
        fault_groups = []

        for i, group in enumerate(groups):
            if "name" not in group:
                errors.append(f"Group {i}: missing 'name'")
                continue
            if "surfaces" not in group or not group["surfaces"]:
                errors.append(f"Group '{group['name']}': missing or empty 'surfaces'")
                continue

            group_names.append(group["name"])
            all_surfaces.extend(group["surfaces"])

            gtype = group.get("type", "erode")
            if gtype not in ("erode", "onlap", "fault"):
                errors.append(
                    f"Group '{group['name']}': unknown type '{gtype}'. "
                    "Supported: erode, onlap, fault"
                )

            if gtype == "fault":
                fault_groups.append(group["name"])
                if len(group["surfaces"]) > 1:
                    warnings.append(
                        f"Group '{group['name']}': faults with multiple surfaces "
                        "are unusual — verify this is intended"
                    )

        # Check for duplicate surfaces
        seen = set()
        for surface in all_surfaces:
            if surface in seen:
                errors.append(f"Duplicate surface name: '{surface}'")
            seen.add(surface)

        # Validate fault relations
        for group in groups:
            if group.get("type") == "fault" and "fault_relations" in group:
                for target in group["fault_relations"]:
                    if target not in group_names:
                        errors.append(
                            f"Fault '{group['name']}' references unknown group '{target}'"
                        )

    # Validate nugget values
    nugget_sp = config.get("nugget_surface_points", 0.00002)
    nugget_or = config.get("nugget_orientations", 0.01)
    if nugget_sp < 1e-8:
        warnings.append(
            f"nugget_surface_points={nugget_sp} is very small. "
            "TRAP dt_008: May cause singular matrix."
        )
    if nugget_sp > 0.1:
        warnings.append(
            f"nugget_surface_points={nugget_sp} is large. "
            "TRAP dt_007: Surfaces may not honor data points."
        )
    if nugget_or > 1.0:
        warnings.append(
            f"nugget_orientations={nugget_or} is very large — orientations will be weakly enforced."
        )

    return errors, warnings


def cross_validate_with_data(config, surface_points_path):
    """Cross-validate config surfaces against actual data file."""
    warnings = []

    with open(surface_points_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        data_formations = set()
        for row in reader:
            if "formation" in row:
                data_formations.add(row["formation"])

    config_surfaces = set()
    for group in config.get("structural_groups", []):
        config_surfaces.update(group.get("surfaces", []))

    missing_in_data = config_surfaces - data_formations
    missing_in_config = data_formations - config_surfaces

    if missing_in_data:
        warnings.append(
            f"Surfaces in config but not in data: {sorted(missing_in_data)}. "
            "These surfaces will have no data points."
        )
    if missing_in_config:
        warnings.append(
            f"Formations in data but not in config: {sorted(missing_in_config)}. "
            "These formations will be ignored."
        )

    return warnings


def process(args):
    """Process structural configuration."""
    config = load_config(args.config)

    # Validate config
    errors, warnings = validate_config(config)
    if errors:
        return {"status": "error", "errors": errors, "warnings": warnings}

    # Cross-validate with data if provided
    if args.surface_points:
        data_warnings = cross_validate_with_data(config, args.surface_points)
        warnings.extend(data_warnings)

    # Build the validated parameter set
    params = {
        "project_name": config["project_name"],
        "extent": config["extent"],
        "interpolation_type": config.get("interpolation_type", "octree"),
        "refinement": config.get("refinement", 6),
        "resolution": config.get("resolution", [50, 50, 50]),
        "nugget_surface_points": config.get("nugget_surface_points", 0.00002),
        "nugget_orientations": config.get("nugget_orientations", 0.01),
        "mapping_object": {},
        "fault_groups": [],
        "fault_relations": {},
    }

    for group in config["structural_groups"]:
        name = group["name"]
        surfaces = tuple(group["surfaces"])
        params["mapping_object"][name] = surfaces

        if group.get("type") == "fault":
            params["fault_groups"].append(name)
            if "fault_relations" in group:
                params["fault_relations"][name] = group["fault_relations"]

    result = {
        "status": "success",
        "params": params,
        "n_groups": len(config["structural_groups"]),
        "n_surfaces": sum(
            len(g["surfaces"]) for g in config["structural_groups"]
        ),
        "n_faults": len(params["fault_groups"]),
    }

    if warnings:
        result["warnings"] = warnings

    return result


def validate_outputs(result):
    """Validate the output parameter set."""
    if result.get("status") != "success":
        return result

    params = result.get("params", {})
    if not params.get("mapping_object"):
        result["status"] = "error"
        result["errors"] = ["No structural groups in output"]

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build and validate GemPy structural parameters"
    )
    parser.add_argument(
        "--config", type=str, required=True,
        help="Path to structural configuration JSON"
    )
    parser.add_argument(
        "--surface-points", type=str, default=None,
        help="Path to surface points CSV for cross-validation"
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Only validate config, don't produce output"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write output JSON to this file"
    )
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    if args.validate_only:
        if result["status"] == "success":
            result = {
                "status": "valid",
                "n_groups": result["n_groups"],
                "n_surfaces": result["n_surfaces"],
                "n_faults": result["n_faults"],
                "warnings": result.get("warnings", []),
            }

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
