#!/usr/bin/env python3
"""Execute a GemPy geological model end-to-end.

Reads structural parameters (from build_structural_params.py output) and
CSV data files, creates and computes a GemPy model, and saves results.

Usage:
  python run_gempy_model.py \
      --params structural_params.json \
      --surface-points gempy_input/surface_points.csv \
      --orientations gempy_input/orientations.csv \
      --output-dir results/

  python run_gempy_model.py \
      --params structural_params.json \
      --surface-points gempy_input/surface_points.csv \
      --orientations gempy_input/orientations.csv \
      --backend pytorch --use-gpu \
      --output-dir results/

  python run_gempy_model.py \
      --example horizontal_strat \
      --output-dir results/
"""

import argparse
import json
import os
import sys
import time
import traceback


def validate_inputs(args):
    """Validate all input arguments."""
    errors = []

    if not args.example:
        if not args.params:
            errors.append("--params required when not using --example")
        elif not os.path.isfile(args.params):
            errors.append(f"Params file not found: {args.params}")

        if not args.surface_points:
            errors.append("--surface-points required when not using --example")
        elif not os.path.isfile(args.surface_points):
            errors.append(f"Surface points file not found: {args.surface_points}")

        if args.orientations and not os.path.isfile(args.orientations):
            errors.append(f"Orientations file not found: {args.orientations}")

    if args.backend not in ("numpy", "pytorch"):
        errors.append(f"Unknown backend: {args.backend}. Supported: numpy, pytorch")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def run_example_model(example_name, output_dir):
    """Run a built-in GemPy example model."""
    try:
        import gempy as gp
    except ImportError:
        return {
            "status": "error",
            "errors": ["gempy not installed. Run: pip install 'gempy[base]'"]
        }

    t0 = time.time()

    try:
        model = gp.create_geomodel(
            project_name=example_name,
            extent=[0, 1000, 0, 1000, 0, 1000],
            resolution=[20, 20, 20],
            refinement=4
        )

        # Add simple horizontal stratigraphy
        element1 = gp.data.StructuralElement(
            name="Layer1",
            color="#015482",
            surface_points=gp.data.SurfacePointsTable.from_arrays(
                x=[500], y=[500], z=[700],
                names=["Layer1"],
                name_id_map={"Layer1": 1}
            ),
            orientations=gp.data.OrientationsTable.from_arrays(
                x=[500], y=[500], z=[700],
                G_x=[0], G_y=[0], G_z=[1],
                names=["Layer1"],
                name_id_map={"Layer1": 1}
            )
        )
        element2 = gp.data.StructuralElement(
            name="Layer2",
            color="#9f0052",
            surface_points=gp.data.SurfacePointsTable.from_arrays(
                x=[500], y=[500], z=[400],
                names=["Layer2"],
                name_id_map={"Layer2": 2}
            ),
            orientations=gp.data.OrientationsTable.initialize_empty()
        )

        group = gp.data.StructuralGroup(
            name="Strat_Series",
            elements=[element1, element2],
            structural_relation=gp.data.StackRelationType.ERODE
        )
        model.structural_frame.structural_groups = [group]

        solutions = gp.compute_model(model)
        elapsed = time.time() - t0

        # Save model
        os.makedirs(output_dir, exist_ok=True)
        gp.save_model(model, path=output_dir, name=example_name)

        return {
            "status": "success",
            "project_name": example_name,
            "computation_time_s": round(elapsed, 2),
            "model_file": os.path.join(output_dir, f"{example_name}.gempy"),
            "n_grid_points": int(model.grid.values.shape[0]) if model.grid.values is not None else 0,
            "has_solutions": solutions is not None,
        }

    except Exception as e:
        return {
            "status": "error",
            "errors": [f"Example model failed: {str(e)}"],
            "traceback": traceback.format_exc()
        }


def run_from_params(args):
    """Run model from parameter file and CSV data."""
    try:
        import gempy as gp
    except ImportError:
        return {
            "status": "error",
            "errors": ["gempy not installed. Run: pip install 'gempy[base]'"]
        }

    t0 = time.time()

    try:
        # Load parameters
        with open(args.params, "r") as f:
            param_data = json.load(f)

        # Extract params (handle both direct and nested format)
        params = param_data.get("params", param_data)

        project_name = params.get("project_name", "gempy_model")
        extent = params["extent"]
        refinement = params.get("refinement", 6)
        interp_type = params.get("interpolation_type", "octree")

        # Create model with CSV data
        importer = gp.data.ImporterHelper(
            path_to_surface_points=args.surface_points,
            path_to_orientations=args.orientations
        )

        if interp_type == "octree":
            model = gp.create_geomodel(
                project_name=project_name,
                extent=extent,
                refinement=refinement,
                importer_helper=importer
            )
        else:
            resolution = params.get("resolution", [50, 50, 50])
            model = gp.create_geomodel(
                project_name=project_name,
                extent=extent,
                resolution=resolution,
                importer_helper=importer
            )

        # Apply structural mapping
        mapping = params.get("mapping_object", {})
        if mapping:
            gp.map_stack_to_surfaces(
                gempy_model=model,
                mapping_object=mapping
            )

        # Configure faults
        fault_groups = params.get("fault_groups", [])
        if fault_groups:
            for fg in fault_groups:
                gp.set_is_fault(model, [fg])

        # Configure backend
        engine_config = None
        if args.backend == "pytorch":
            try:
                from gempy_engine.core.backend_tensor import BackendTensor
                engine_config = gp.data.GemPyEngineConfig(
                    backend=gp.data.AvailableBackends.PYTORCH,
                    use_gpu=args.use_gpu
                )
            except ImportError:
                print(
                    '{"status": "warning", "message": "PyTorch not available, falling back to NumPy"}',
                    file=sys.stderr
                )

        # Compute
        solutions = gp.compute_model(model, engine_config=engine_config)
        elapsed = time.time() - t0

        # Save outputs
        os.makedirs(args.output_dir, exist_ok=True)
        model_path = os.path.join(args.output_dir, f"{project_name}.gempy")
        gp.save_model(model, path=args.output_dir, name=project_name)

        # Collect result metadata
        result = {
            "status": "success",
            "project_name": project_name,
            "computation_time_s": round(elapsed, 2),
            "model_file": model_path,
            "backend": args.backend,
            "interpolation_type": interp_type,
            "extent": extent,
            "n_grid_points": int(model.grid.values.shape[0]) if model.grid.values is not None else 0,
            "n_surfaces": len(model.structural_frame.surface_points_copy.df) if hasattr(model.structural_frame, 'surface_points_copy') else -1,
            "has_solutions": solutions is not None,
        }

        # Extract block model stats
        if solutions is not None:
            raw = model.solutions.raw_arrays
            if hasattr(raw, 'block') and raw.block is not None:
                import numpy as np
                unique_ids = np.unique(raw.block)
                result["n_unique_formations"] = int(len(unique_ids))
                result["block_shape"] = list(raw.block.shape)

        return result

    except Exception as e:
        return {
            "status": "error",
            "errors": [f"Model computation failed: {str(e)}"],
            "traceback": traceback.format_exc(),
            "computation_time_s": round(time.time() - t0, 2)
        }


def process(args):
    """Execute the appropriate model run."""
    if args.example:
        return run_example_model(args.example, args.output_dir)
    else:
        return run_from_params(args)


def validate_outputs(result):
    """Validate model execution results."""
    if result.get("status") != "success":
        return result

    warnings = []

    if not result.get("has_solutions"):
        warnings.append("Model computed but no solutions returned")

    ct = result.get("computation_time_s", 0)
    if ct > 300:
        warnings.append(
            f"Computation took {ct:.0f}s. Consider using OCTREE or lower resolution."
        )

    if result.get("n_unique_formations", 0) <= 1:
        warnings.append(
            "Only 1 formation in block model — "
            "check structural mapping and input data."
        )

    if warnings:
        result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Execute a GemPy geological model"
    )
    parser.add_argument(
        "--params", type=str, default=None,
        help="Path to structural params JSON (from build_structural_params.py)"
    )
    parser.add_argument(
        "--surface-points", type=str, default=None,
        help="Path to surface points CSV"
    )
    parser.add_argument(
        "--orientations", type=str, default=None,
        help="Path to orientations CSV"
    )
    parser.add_argument(
        "--example", type=str, default=None,
        help="Run a built-in example model instead of custom data"
    )
    parser.add_argument(
        "--backend", type=str, default="numpy",
        help="Computation backend: numpy or pytorch (default: numpy)"
    )
    parser.add_argument(
        "--use-gpu", action="store_true",
        help="Use GPU acceleration (requires pytorch backend)"
    )
    parser.add_argument(
        "--output-dir", type=str, default="results",
        help="Directory for output files (default: results)"
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
