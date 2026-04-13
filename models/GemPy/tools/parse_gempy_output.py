#!/usr/bin/env python3
"""Parse GemPy model results and extract to CSV/JSON.

Loads a computed GemPy model (from .gempy binary or in-memory) and extracts:
  - Block model (formation IDs at each grid point) to CSV
  - Scalar field values to CSV
  - Surface mesh vertices/edges to CSV per surface
  - Model summary statistics to JSON

Usage:
  python parse_gempy_output.py \
      --model-file results/test_model.gempy \
      --output-dir parsed_output/

  python parse_gempy_output.py \
      --model-file results/test_model.gempy \
      --extract block scalar mesh \
      --output-dir parsed_output/

  python parse_gempy_output.py \
      --model-file results/test_model.gempy \
      --extract summary \
      --output summary.json
"""

import argparse
import csv
import json
import os
import sys
import traceback


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.model_file):
        errors.append(f"Model file not found: {args.model_file}")

    valid_extracts = {"block", "scalar", "mesh", "summary", "all"}
    for ext in args.extract:
        if ext not in valid_extracts:
            errors.append(f"Unknown extract type: {ext}. Supported: {sorted(valid_extracts)}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def load_model(model_file):
    """Load a GemPy model from .gempy binary file."""
    try:
        import gempy as gp
    except ImportError:
        return None, "gempy not installed. Run: pip install 'gempy[base]'"

    try:
        model = gp.load_model(model_file)
        return model, None
    except Exception as e:
        return None, f"Failed to load model: {str(e)}"


def extract_block_model(model, output_dir):
    """Extract block model (formation IDs) to CSV."""
    import numpy as np

    raw = model.solutions.raw_arrays
    if raw is None or not hasattr(raw, 'block') or raw.block is None:
        return {"status": "skipped", "reason": "No block model in solutions"}

    block = raw.block
    grid_values = model.grid.values

    if grid_values is None:
        return {"status": "skipped", "reason": "No grid values available"}

    # Write block model CSV
    filepath = os.path.join(output_dir, "block_model.csv")
    os.makedirs(output_dir, exist_ok=True)

    n_points = min(len(grid_values), len(block))
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["X", "Y", "Z", "formation_id"])
        for i in range(n_points):
            writer.writerow([
                round(float(grid_values[i, 0]), 4),
                round(float(grid_values[i, 1]), 4),
                round(float(grid_values[i, 2]), 4),
                int(block[i])
            ])

    unique_ids, counts = np.unique(block[:n_points], return_counts=True)
    formation_stats = {
        str(int(uid)): int(count) for uid, count in zip(unique_ids, counts)
    }

    return {
        "status": "success",
        "file": filepath,
        "n_points": n_points,
        "n_formations": len(unique_ids),
        "formation_cell_counts": formation_stats
    }


def extract_scalar_field(model, output_dir):
    """Extract scalar field values to CSV."""
    raw = model.solutions.raw_arrays
    if raw is None or not hasattr(raw, 'scalar_field') or raw.scalar_field is None:
        return {"status": "skipped", "reason": "No scalar field in solutions"}

    scalar = raw.scalar_field
    grid_values = model.grid.values

    if grid_values is None:
        return {"status": "skipped", "reason": "No grid values available"}

    filepath = os.path.join(output_dir, "scalar_field.csv")
    os.makedirs(output_dir, exist_ok=True)

    n_points = min(len(grid_values), len(scalar))
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["X", "Y", "Z", "scalar_value"])
        for i in range(n_points):
            writer.writerow([
                round(float(grid_values[i, 0]), 4),
                round(float(grid_values[i, 1]), 4),
                round(float(grid_values[i, 2]), 4),
                round(float(scalar[i]), 6)
            ])

    import numpy as np
    return {
        "status": "success",
        "file": filepath,
        "n_points": n_points,
        "scalar_range": [
            round(float(np.nanmin(scalar[:n_points])), 6),
            round(float(np.nanmax(scalar[:n_points])), 6)
        ],
        "scalar_mean": round(float(np.nanmean(scalar[:n_points])), 6)
    }


def extract_meshes(model, output_dir):
    """Extract surface meshes (vertices + edges) to CSV files."""
    raw = model.solutions.raw_arrays
    if raw is None:
        return {"status": "skipped", "reason": "No solutions available"}

    vertices_list = getattr(raw, 'vertices', None)
    edges_list = getattr(raw, 'edges', None)

    if vertices_list is None or not vertices_list:
        return {"status": "skipped", "reason": "No mesh data in solutions"}

    mesh_dir = os.path.join(output_dir, "meshes")
    os.makedirs(mesh_dir, exist_ok=True)

    mesh_results = []
    for idx, vertices in enumerate(vertices_list):
        if vertices is None or len(vertices) == 0:
            continue

        surface_name = f"surface_{idx:03d}"

        # Write vertices
        vert_file = os.path.join(mesh_dir, f"{surface_name}_vertices.csv")
        with open(vert_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["X", "Y", "Z"])
            for v in vertices:
                writer.writerow([
                    round(float(v[0]), 4),
                    round(float(v[1]), 4),
                    round(float(v[2]), 4)
                ])

        mesh_info = {
            "surface": surface_name,
            "vertices_file": vert_file,
            "n_vertices": len(vertices),
        }

        # Write edges if available
        if edges_list and idx < len(edges_list) and edges_list[idx] is not None:
            edges = edges_list[idx]
            edge_file = os.path.join(mesh_dir, f"{surface_name}_triangles.csv")
            with open(edge_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["v0", "v1", "v2"])
                for e in edges:
                    writer.writerow([int(e[0]), int(e[1]), int(e[2])])
            mesh_info["triangles_file"] = edge_file
            mesh_info["n_triangles"] = len(edges)

        mesh_results.append(mesh_info)

    return {
        "status": "success",
        "mesh_dir": mesh_dir,
        "n_surfaces": len(mesh_results),
        "meshes": mesh_results
    }


def extract_summary(model):
    """Extract model summary statistics."""
    summary = {
        "project_name": model.meta.project_name if hasattr(model.meta, 'project_name') else "unknown",
        "extent": list(model.grid.extent) if hasattr(model.grid, 'extent') else [],
    }

    # Structural frame info
    sf = model.structural_frame
    if sf is not None:
        groups = []
        for group in sf.structural_groups:
            g_info = {
                "name": group.name,
                "type": str(group.structural_relation) if hasattr(group, 'structural_relation') else "unknown",
                "n_elements": len(group.elements),
                "elements": [e.name for e in group.elements]
            }
            groups.append(g_info)
        summary["structural_groups"] = groups
        summary["n_groups"] = len(groups)

    # Grid info
    if model.grid is not None:
        grid_info = {
            "n_points": int(model.grid.values.shape[0]) if model.grid.values is not None else 0,
        }
        summary["grid"] = grid_info

    # Solutions info
    if model.solutions is not None:
        raw = model.solutions.raw_arrays
        sol_info = {
            "has_block": hasattr(raw, 'block') and raw.block is not None,
            "has_scalar_field": hasattr(raw, 'scalar_field') and raw.scalar_field is not None,
            "has_meshes": hasattr(raw, 'vertices') and raw.vertices is not None,
        }
        if sol_info["has_block"]:
            import numpy as np
            sol_info["n_unique_formations"] = int(len(np.unique(raw.block)))
        summary["solutions"] = sol_info

    return {"status": "success", "summary": summary}


def process(args):
    """Main processing: load model and extract requested data."""
    model, error = load_model(args.model_file)
    if error:
        return {"status": "error", "errors": [error]}

    extracts = set(args.extract)
    if "all" in extracts:
        extracts = {"block", "scalar", "mesh", "summary"}

    results = {"status": "success", "model_file": args.model_file}

    if "block" in extracts:
        results["block"] = extract_block_model(model, args.output_dir)

    if "scalar" in extracts:
        results["scalar"] = extract_scalar_field(model, args.output_dir)

    if "mesh" in extracts:
        results["mesh"] = extract_meshes(model, args.output_dir)

    if "summary" in extracts:
        results["summary"] = extract_summary(model)

    return results


def validate_outputs(result):
    """Validate extraction results."""
    if result.get("status") != "success":
        return result

    warnings = []
    for key in ("block", "scalar", "mesh"):
        sub = result.get(key, {})
        if sub.get("status") == "skipped":
            warnings.append(f"{key}: {sub.get('reason', 'skipped')}")

    if warnings:
        result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse GemPy model output and extract to CSV/JSON"
    )
    parser.add_argument(
        "--model-file", type=str, required=True,
        help="Path to .gempy model file"
    )
    parser.add_argument(
        "--extract", nargs="+", default=["all"],
        help="What to extract: block, scalar, mesh, summary, all (default: all)"
    )
    parser.add_argument(
        "--output-dir", type=str, default="parsed_output",
        help="Output directory for CSV files (default: parsed_output)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write JSON result to this file"
    )
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Result written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
