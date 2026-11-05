#!/usr/bin/env python3
"""
parse_gimli_output.py — Parse pyGIMLi inversion/forward results to CSV and metrics.

Reads model arrays, meshes, and response data produced by run_pygimli.py or
native pyGIMLi workflows. Exports cell-by-cell model values to CSV, computes
data-fit metrics, and generates coverage analysis.

Usage:
    python parse_gimli_output.py --results-dir results/ --method ert --output analysis/
    python parse_gimli_output.py --results-dir results/ --method srt --output analysis/
    python parse_gimli_output.py --model model.npy --mesh mesh.bms --method ert --output analysis/

Output files:
    analysis/model_cells.csv     — Cell ID, x, y, z, value, coverage
    analysis/data_fit.csv        — Observed vs. predicted per datum
    analysis/metrics.json        — Summary metrics (chi2, RMS, model stats)
    analysis/model_histogram.png — Distribution of model parameters

Metrics computed:
    - Chi-squared (χ²): Weighted misfit (target ≈ 1.0)
    - Relative RMS: sqrt(mean((obs-pred)²/obs²))
    - Absolute RMS: sqrt(mean((obs-pred)²))
    - Model statistics: min, max, mean, median, std
    - Coverage statistics: % of cells above threshold
"""

import argparse
import json
import os
import sys
import csv
import numpy as np

# ---------------------------------------------------------------------------
# Engine python: pyGIMLi lives in its own venv (pygimli + pgcore pip wheels), not in the HydroCraft python_env that
# SKILL.md uses to start the KI tools. Lookup (same as preflight_check.py): --pygimli-python ->
# $PYGIMLI_PYTHON (empty = unset) -> server default -> this python (only if it imports pygimli). An explicit value is
# used as given (no fallback). If the chosen python is not the one running this tool, the tool
# re-launches itself with it (os.execv, same arguments).
# ---------------------------------------------------------------------------
ENGINE_PYTHON_ENV = "PYGIMLI_PYTHON"
ENGINE_PYTHON_DEFAULT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/pyGIMLi/venv/bin/python"
_REEXEC_GUARD = "KI_PYGIMLI_REEXEC"


def resolve_engine_python(cli_value=None):
    """Return (python, source) for the pyGIMLi interpreter, or (None, reason)."""
    if cli_value is not None:
        return cli_value, "--pygimli-python"
    env_value = os.environ.get(ENGINE_PYTHON_ENV, "").strip() or None  # as preflight_check.py
    if env_value is not None:
        return env_value, "$" + ENGINE_PYTHON_ENV
    if os.path.isfile(ENGINE_PYTHON_DEFAULT):
        return ENGINE_PYTHON_DEFAULT, "server default"
    try:
        import pygimli  # noqa: F401
        return sys.executable, "running python (imports pygimli)"
    except ImportError:
        return None, (f"no python with pygimli: --pygimli-python and ${ENGINE_PYTHON_ENV} not set, "
                      f"server default {ENGINE_PYTHON_DEFAULT} not found, and {sys.executable} "
                      "cannot import pygimli")


def ensure_engine_python(cli_value=None):
    """Re-launch this tool with the pyGIMLi python when another python is running it."""
    python, source = resolve_engine_python(cli_value)
    if python is None:
        print(json.dumps({"status": "error", "errors": [source]}), file=sys.stderr)
        sys.exit(1)
    if os.path.abspath(python) == os.path.abspath(sys.executable):
        return
    if os.environ.get(_REEXEC_GUARD):
        print(json.dumps({"status": "error", "errors": [
            f"re-launch loop: running {sys.executable}, expected {python} ({source})"]}),
            file=sys.stderr)
        sys.exit(1)
    if not (os.path.isfile(python) and os.access(python, os.X_OK)):
        print(json.dumps({"status": "error", "errors": [
            f"pyGIMLi python not found or not executable: {python!r} ({source})"]}),
            file=sys.stderr)
        sys.exit(1)
    python = os.path.abspath(python)  # not realpath: a venv python must keep its own path
    print(f"[{os.path.basename(__file__)}] re-launching with {python} ({source})",
          file=sys.stderr, flush=True)
    env = dict(os.environ, **{_REEXEC_GUARD: "1"})
    try:
        os.execve(python, [python, os.path.abspath(__file__)] + sys.argv[1:], env)
    except OSError as e:
        print(json.dumps({"status": "error", "errors": [
            f"could not start pyGIMLi python {python!r} ({source}): {e}"]}), file=sys.stderr)
        sys.exit(1)


def validate_inputs(args):
    """Validate input paths and requirements."""
    errors = []

    if args.results_dir:
        if not os.path.isdir(args.results_dir):
            errors.append(f"Results directory not found: {args.results_dir}")
        else:
            model_path = os.path.join(args.results_dir, "model.npy")
            if not os.path.isfile(model_path):
                errors.append(f"model.npy not found in {args.results_dir}")
    elif args.model:
        if not os.path.isfile(args.model):
            errors.append(f"Model file not found: {args.model}")
    else:
        errors.append("Provide either --results-dir or --model")

    if args.method not in ("ert", "srt"):
        errors.append(f"Unsupported method: {args.method}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def load_results(args):
    """Load model, mesh, and response from results directory or files."""
    data = {}

    if args.results_dir:
        base = args.results_dir
        data["model"] = np.load(os.path.join(base, "model.npy"))
        resp_path = os.path.join(base, "response.npy")
        if os.path.isfile(resp_path):
            data["response"] = np.load(resp_path)
        vel_path = os.path.join(base, "velocity.npy")
        if os.path.isfile(vel_path):
            data["velocity"] = np.load(vel_path)
        meta_path = os.path.join(base, "result.json")
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                data["metadata"] = json.load(f)
        mesh_path = os.path.join(base, "mesh.bms")
        if os.path.isfile(mesh_path):
            data["mesh_path"] = mesh_path
    else:
        data["model"] = np.load(args.model)
        if args.mesh:
            data["mesh_path"] = args.mesh

    return data


def compute_cell_coordinates(mesh_path):
    """Extract cell centres from a pyGIMLi mesh file.

    Needs pygimli; errors (no pygimli, unreadable mesh) are raised to the caller.
    """
    import pygimli as pg
    mesh = pg.load(mesh_path)
    three_d = mesh.dim() > 2  # a cell centre (RVector3) has no dim(); the mesh has
    centres = []
    for cell in mesh.cells():
        c = cell.center()
        centres.append((c.x(), c.y(), c.z() if three_d else 0.0))
    return np.array(centres)


def compute_metrics(observed, predicted, errors=None):
    """Compute data-fit metrics.

    Parameters
    ----------
    observed : array-like
        Observed data values.
    predicted : array-like
        Predicted (forward response) data values.
    errors : array-like, optional
        Data error estimates (as fractions, 0-1).

    Returns
    -------
    dict : Metrics dictionary.
    """
    obs = np.asarray(observed, dtype=float)
    pred = np.asarray(predicted, dtype=float)

    residuals = obs - pred
    abs_rms = float(np.sqrt(np.mean(residuals ** 2)))

    # Relative RMS (avoid division by zero)
    mask = np.abs(obs) > 1e-12
    if np.any(mask):
        rel_residuals = residuals[mask] / obs[mask]
        rel_rms = float(np.sqrt(np.mean(rel_residuals ** 2)))
    else:
        rel_rms = float("nan")

    # Chi-squared (if errors provided)
    chi2 = float("nan")
    if errors is not None:
        err = np.asarray(errors, dtype=float)
        err = np.where(err > 0, err, 1e-6)
        weighted = residuals / (obs * err + 1e-30)
        chi2 = float(np.mean(weighted ** 2))

    # Correlation
    if len(obs) > 1:
        r = float(np.corrcoef(obs, pred)[0, 1])
    else:
        r = float("nan")

    return {
        "abs_rms": abs_rms,
        "rel_rms": rel_rms,
        "chi2": chi2,
        "r": r,
        "r_squared": r ** 2 if not np.isnan(r) else float("nan"),
        "n_data": len(obs),
        "max_residual": float(np.max(np.abs(residuals))),
        "mean_residual": float(np.mean(residuals)),
    }


def compute_model_stats(model, method="ert"):
    """Compute model parameter statistics."""
    stats = {
        "n_cells": len(model),
        "min": float(np.min(model)),
        "max": float(np.max(model)),
        "mean": float(np.mean(model)),
        "median": float(np.median(model)),
        "std": float(np.std(model)),
        "log_mean": float(np.exp(np.mean(np.log(np.abs(model) + 1e-30)))),
    }

    if method == "ert":
        stats["unit"] = "Ohm·m"
        stats["parameter"] = "resistivity"
    elif method == "srt":
        stats["unit"] = "s/m"
        stats["parameter"] = "slowness"

    return stats


def export_model_csv(model, output_path, cell_coords=None, method="ert"):
    """Export model to CSV with cell coordinates."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        if method == "ert":
            header = ["cell_id", "x", "y", "z", "resistivity_ohm_m"]
        elif method == "srt":
            header = ["cell_id", "x", "y", "z", "slowness_s_per_m", "velocity_m_per_s"]
        else:
            header = ["cell_id", "x", "y", "z", "value"]

        writer.writerow(header)

        for i in range(len(model)):
            if cell_coords is not None and i < len(cell_coords):
                x, y, z = cell_coords[i]
            else:
                x, y, z = i, 0.0, 0.0

            row = [i, f"{x:.4f}", f"{y:.4f}", f"{z:.4f}"]
            if method == "srt":
                row.append(f"{model[i]:.8f}")
                row.append(f"{1.0/model[i]:.2f}" if model[i] > 0 else "nan")
            else:
                row.append(f"{model[i]:.4f}")

            writer.writerow(row)

    return output_path


def export_data_fit_csv(observed, predicted, output_path):
    """Export observed vs. predicted data to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["datum_id", "observed", "predicted", "residual", "relative_residual"])
        for i in range(len(observed)):
            obs = observed[i]
            pred = predicted[i]
            resid = obs - pred
            rel_resid = resid / obs if abs(obs) > 1e-12 else float("nan")
            writer.writerow([i, f"{obs:.6f}", f"{pred:.6f}",
                             f"{resid:.6f}", f"{rel_resid:.6f}"])
    return output_path


def process(args):
    """Main processing pipeline."""
    result = {
        "status": "success",
        "method": args.method,
    }

    data = load_results(args)
    model = data["model"]

    # Model statistics
    result["model_stats"] = compute_model_stats(model, args.method)

    # Cell coordinates from mesh
    cell_coords = None
    if "mesh_path" in data:
        try:
            cell_coords = compute_cell_coordinates(data["mesh_path"])
        except Exception as e:  # no pygimli, unreadable mesh, ...
            print(json.dumps({"status": "error", "errors": [
                f"could not read cell centres from {data['mesh_path']}: "
                f"{type(e).__name__}: {e}"]}), file=sys.stderr)
            sys.exit(1)
        if len(cell_coords) != len(model):
            print(json.dumps({"status": "error", "errors": [
                f"mesh {data['mesh_path']} has {len(cell_coords)} cells but the model "
                f"has {len(model)} values"]}), file=sys.stderr)
            sys.exit(1)
    else:
        result["warnings"] = ["no mesh given/found: x in model_cells.csv is the cell "
                              "index, y and z are 0"]

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Export model CSV
    model_csv = os.path.join(args.output, "model_cells.csv")
    export_model_csv(model, model_csv, cell_coords, args.method)
    result["model_csv"] = model_csv

    # Data fit analysis
    if "response" in data:
        # Need observed data too - load from metadata or assume response matches
        if "metadata" in data and "chi2" in data["metadata"]:
            result["chi2"] = data["metadata"]["chi2"]
        result["response_range"] = [
            float(np.min(data["response"])),
            float(np.max(data["response"])),
        ]
        resp_csv = os.path.join(args.output, "response.csv")
        np.savetxt(resp_csv, data["response"], delimiter=",",
                   header="predicted_value", comments="")
        result["response_csv"] = resp_csv

    # Velocity export for SRT
    if "velocity" in data:
        vel_csv = os.path.join(args.output, "velocity_cells.csv")
        np.savetxt(vel_csv, data["velocity"], delimiter=",",
                   header="velocity_m_per_s", comments="")
        result["velocity_csv"] = vel_csv
        result["velocity_stats"] = {
            "min": float(np.min(data["velocity"])),
            "max": float(np.max(data["velocity"])),
            "mean": float(np.mean(data["velocity"])),
        }

    # Copy metadata
    if "metadata" in data:
        result["inversion_metadata"] = data["metadata"]

    return result


def validate_outputs(result):
    """Post-validation of parsed outputs."""
    warnings = list(result.get("warnings", []))

    stats = result.get("model_stats", {})
    method = result.get("method", "")

    if method == "ert":
        if stats.get("min", 0) <= 0:
            warnings.append("Model contains zero or negative resistivity. "
                            "Check inversion convergence.")
        if stats.get("max", 0) / max(stats.get("min", 1), 1e-10) > 1e6:
            warnings.append("Model dynamic range > 10^6. "
                            "Possible artifact or unit issue.")

    if method == "srt":
        vel_stats = result.get("velocity_stats", {})
        if vel_stats.get("min", 0) < 50:
            warnings.append("Minimum velocity < 50 m/s — unrealistic for earth materials.")
        if vel_stats.get("max", 0) > 8000:
            warnings.append("Maximum velocity > 8000 m/s — exceeds typical crustal values.")

    chi2 = result.get("chi2", result.get("inversion_metadata", {}).get("chi2"))
    if chi2 is not None:
        if chi2 > 5:
            warnings.append(f"Chi² = {chi2:.2f}. Poor data fit — review errors/lambda.")
        elif chi2 < 0.3:
            warnings.append(f"Chi² = {chi2:.2f}. Overfitting — increase lambda or errors.")

    if warnings:
        result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse pyGIMLi output to CSV and compute metrics."
    )
    parser.add_argument("--results-dir", "-r", default=None,
                        help="Results directory from run_pygimli.py")
    parser.add_argument("--model", default=None,
                        help="Direct path to model.npy")
    parser.add_argument("--mesh", default=None,
                        help="Direct path to mesh.bms")
    parser.add_argument("--method", "-m", required=True,
                        choices=["ert", "srt"],
                        help="Geophysical method")
    parser.add_argument("--output", "-o", default="analysis",
                        help="Output directory (default: analysis/)")
    parser.add_argument("--coverage-threshold", type=float, default=0.1,
                        help="Coverage threshold for masking (default: 0.1)")
    parser.add_argument("--pygimli-python", default=None,
                        help="Python of the pyGIMLi venv, used to read mesh cell centres "
                             "(default: $PYGIMLI_PYTHON, else the server venv, else this "
                             "python if it imports pygimli). The tool re-launches itself "
                             "with it; without any such python only a model without a "
                             "mesh can be parsed.")

    args = parser.parse_args()
    if args.pygimli_python is not None or resolve_engine_python()[0] is not None:
        ensure_engine_python(args.pygimli_python)

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Save metrics
    metrics_path = os.path.join(args.output, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
