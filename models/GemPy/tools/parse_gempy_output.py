#!/usr/bin/env python3
"""Parse GemPy model results and extract to CSV/JSON.

Loads a GemPy model (.gempy file) and extracts:
  - Block model (formation IDs at each grid point) to CSV
  - Scalar field values to CSV
  - Surface mesh vertices/edges to CSV per surface
  - Model summary statistics to JSON

A GemPy 3 .gempy file holds the model inputs and grid but NOT the solutions. For block,
scalar and mesh the model is therefore recomputed once from the saved inputs and
interpolation options with the NumPy backend (JSON: "solutions_recomputed": true); the
original backend/GPU choice is not stored in the file. --extract summary does not compute.
Exit code 1 when loading, recomputing or any requested extraction fails.

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
    except ImportError as e:
        return None, f"gempy cannot be imported ({e}). Run with the GemPy venv python or pip install 'gempy[base]'"

    try:
        model = gp.load_model(model_file)
        return model, None
    except Exception as e:
        return None, f"Failed to load model: {str(e)}"


def ensure_solutions(model):
    """GemPy 3 .gempy files store inputs + grid only, not solutions: recompute if missing.

    Same engine, saved inputs and interpolation options; NumPy backend (the original
    backend/GPU choice is not stored in the file). Returns (recomputed: bool, error or None).
    """
    if model.solutions is not None:
        return False, None
    try:
        import gempy as gp
        # explicit NumPy engine config (GemPy's default backend follows the environment)
        gp.compute_model(model, engine_config=gp.data.GemPyEngineConfig(
            backend=gp.data.AvailableBackends.numpy, use_gpu=False))
    except Exception as e:
        return False, f"Recomputing solutions from the saved model failed: {e}"
    if model.solutions is None:
        return False, "Recomputing solutions from the saved model gave no solutions"
    return True, None


def _raw_array(raw, *names):
    """First present, non-None attribute of raw arrays (GemPy 3 name first, legacy after)."""
    for name in names:
        val = getattr(raw, name, None)
        if val is not None:
            return val
    return None


def _dense_coords(model, n_points):
    """Coordinates of the dense (regular) grid that lith_block / scalar_field_matrix are on."""
    import numpy as np
    for cand in (getattr(getattr(model.grid, "regular_grid", None), "values", None),
                 getattr(getattr(model.grid, "dense_grid", None), "values", None),
                 model.grid.values):
        if cand is not None and len(cand) == n_points:
            return np.asarray(cand)
    raise ValueError(f"No grid with {n_points} points to match the result array "
                     f"(grid.values has {0 if model.grid.values is None else len(model.grid.values)})")


def extract_block_model(model, output_dir):
    """Extract block model (formation IDs) to CSV."""
    import numpy as np

    raw = model.solutions.raw_arrays if model.solutions is not None else None
    block = _raw_array(raw, "lith_block", "block") if raw is not None else None
    if block is None:
        return {"status": "skipped", "reason": "No block model in solutions"}

    block = np.asarray(block).reshape(-1)
    grid_values = _dense_coords(model, len(block))

    # Write block model CSV
    filepath = os.path.join(output_dir, "block_model.csv")
    os.makedirs(output_dir, exist_ok=True)

    n_points = len(block)
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["X", "Y", "Z", "formation_id"])
        for i in range(n_points):
            writer.writerow([
                round(float(grid_values[i, 0]), 4),
                round(float(grid_values[i, 1]), 4),
                round(float(grid_values[i, 2]), 4),
                int(round(float(block[i])))
            ])

    unique_ids, counts = np.unique(np.rint(block).astype(int), return_counts=True)
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
    """Extract scalar field values to CSV (one column per structural group)."""
    import numpy as np

    raw = model.solutions.raw_arrays if model.solutions is not None else None
    scalar = _raw_array(raw, "scalar_field_matrix", "scalar_field") if raw is not None else None
    if scalar is None:
        return {"status": "skipped", "reason": "No scalar field in solutions"}

    scalar = np.asarray(scalar, dtype=float)
    if scalar.ndim == 1:
        scalar = scalar[np.newaxis, :]
    n_groups, n_points = scalar.shape
    grid_values = _dense_coords(model, n_points)
    group_names = [g.name for g in model.structural_frame.structural_groups]
    if n_groups == 1:
        columns = ["scalar_value"]
    elif len(group_names) == n_groups:
        columns = [f"scalar_value_{name}" for name in group_names]
    else:
        columns = [f"scalar_value_{i}" for i in range(n_groups)]

    filepath = os.path.join(output_dir, "scalar_field.csv")
    os.makedirs(output_dir, exist_ok=True)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["X", "Y", "Z"] + columns)
        for i in range(n_points):
            writer.writerow([
                round(float(grid_values[i, 0]), 4),
                round(float(grid_values[i, 1]), 4),
                round(float(grid_values[i, 2]), 4)
            ] + [round(float(scalar[g, i]), 6) for g in range(n_groups)])

    result = {
        "status": "success",
        "file": filepath,
        "n_points": n_points,
        "n_groups": n_groups,
        "columns": columns,
        "scalar_range": [
            round(float(np.nanmin(scalar)), 6),
            round(float(np.nanmax(scalar)), 6)
        ],
        "scalar_mean": round(float(np.nanmean(scalar)), 6)
    }
    if n_groups > 1:
        result["per_group"] = {
            col: {"range": [round(float(np.nanmin(scalar[g])), 6), round(float(np.nanmax(scalar[g])), 6)],
                  "mean": round(float(np.nanmean(scalar[g])), 6)}
            for g, col in enumerate(columns)}
    return result


def extract_meshes(model, output_dir):
    """Extract surface meshes (vertices + triangles) to CSV files.

    Uses each structural element's own mesh (element.vertices / element.edges), which GemPy
    sets in WORLD coordinates when solutions are assigned (raw_arrays.vertices are internal,
    rescaled engine coordinates and their order is not tied to the element list).
    """
    import numpy as np

    if model.solutions is None:
        return {"status": "skipped", "reason": "No solutions available"}

    elements = list(model.structural_frame.structural_elements)
    if elements and elements[-1].name.lower() == "basement":
        elements = elements[:-1]

    mesh_dir = os.path.join(output_dir, "meshes")
    os.makedirs(mesh_dir, exist_ok=True)

    mesh_results = []
    for idx, element in enumerate(elements):
        vertices = getattr(element, "vertices", None)
        if vertices is None or len(vertices) == 0:
            continue
        vertices = np.asarray(vertices)

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
            "element": element.name,
            "vertices_file": vert_file,
            "n_vertices": len(vertices),
        }

        # Write triangles if available
        edges = getattr(element, "edges", None)
        if edges is not None and len(edges) > 0:
            edge_file = os.path.join(mesh_dir, f"{surface_name}_triangles.csv")
            with open(edge_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["v0", "v1", "v2"])
                for e in edges:
                    writer.writerow([int(e[0]), int(e[1]), int(e[2])])
            mesh_info["triangles_file"] = edge_file
            mesh_info["n_triangles"] = len(edges)

        mesh_results.append(mesh_info)

    if not mesh_results:
        return {"status": "skipped", "reason": "No mesh data in solutions"}

    return {
        "status": "success",
        "mesh_dir": mesh_dir,
        "n_surfaces": len(mesh_results),
        "meshes": mesh_results
    }


def extract_summary(model):
    """Extract model summary statistics."""
    meta = model.meta
    project_name = (getattr(meta, "name", None) or getattr(meta, "project_name", None)
                    or "unknown")
    summary = {
        "project_name": project_name,
        "extent": [float(v) for v in model.grid.extent] if getattr(model.grid, "extent", None) is not None else [],
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
        block = _raw_array(raw, "lith_block", "block")
        scalar = _raw_array(raw, "scalar_field_matrix", "scalar_field")
        vertices = _raw_array(raw, "vertices")
        sol_info = {
            "computed": True,
            "has_block": block is not None,
            "has_scalar_field": scalar is not None,
            "has_meshes": vertices is not None and len(vertices) > 0,
        }
        if block is not None:
            import numpy as np
            sol_info["n_unique_formations"] = int(len(np.unique(np.asarray(block))))
        summary["solutions"] = sol_info
    else:
        summary["solutions"] = {"computed": False,
                                "note": "no solutions in the file (GemPy 3 .gempy stores inputs only)"}

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

    if extracts & {"block", "scalar", "mesh"}:
        recomputed, error = ensure_solutions(model)
        if error:
            return {"status": "error", "model_file": args.model_file, "errors": [error]}
        results["solutions_recomputed"] = recomputed
        if recomputed:
            results["recompute_backend"] = "numpy"

    errors = []
    for key, func in (("block", lambda: extract_block_model(model, args.output_dir)),
                      ("scalar", lambda: extract_scalar_field(model, args.output_dir)),
                      ("mesh", lambda: extract_meshes(model, args.output_dir)),
                      ("summary", lambda: extract_summary(model))):
        if key not in extracts:
            continue
        try:
            results[key] = func()
        except Exception as e:
            results[key] = {"status": "error", "error": str(e)}
            errors.append(f"{key}: {e}")
    if errors:
        results["status"] = "error"
        results["errors"] = errors

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

    if result.get("status") != "success":
        print("GemPy parse FAILED: " + "; ".join(result.get("errors", ["see JSON result"])),
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
