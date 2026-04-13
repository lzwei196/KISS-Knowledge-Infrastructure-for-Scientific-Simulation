#!/usr/bin/env python3
"""
calibrate_raven_dds.py — DDS (Dynamically Dimensioned Search) calibration for Raven.

Implements the DDS algorithm (Tolson & Shoemaker, 2007) natively in Python,
consistent with HydroCraft's AI calibration approach. No external Ostrich dependency.

Modifies parameters in the .rvp file, runs Raven, reads Diagnostics.csv,
and iterates to maximize NSE (or minimize any objective function).

Usage:
    python calibrate_raven_dds.py \
        --run_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --template hbv_ec \
        --n_iterations 100 \
        --objective NSE \
        --raven_exe /mnt/disk1/Hydrocraft_server/model/raven/Raven.exe
"""

import argparse
import json
import os
import sys
import subprocess
import shutil
import time
import re
from datetime import datetime

try:
    import numpy as np
except ImportError:
    print(json.dumps({"status": "error", "message": "numpy required"}))
    sys.exit(1)

RAVEN_EXE_DEFAULT = "/mnt/disk1/Hydrocraft_server/model/raven/Raven.exe"

# Calibration parameter definitions per template
# name: (min, max, default, description)
CALIBRATION_PARAMS = {
    "gr4j": {
        "GR4J_X1": (1.0, 1500.0, 350.0, "Production store capacity (mm)"),
        "GR4J_X2": (-10.0, 5.0, 0.0, "GW exchange coefficient (mm/d)"),
        "GR4J_X3": (1.0, 500.0, 90.0, "Routing store capacity (mm)"),
        "GR4J_X4": (0.5, 10.0, 1.5, "Unit hydrograph time base (d)"),
    },
    "hbv_ec": {
        "MELT_FACTOR": (1.0, 8.0, 4.0, "Degree-day snowmelt factor"),
        "HBV_BETA": (0.5, 6.0, 2.0, "Soil moisture nonlinearity"),
        "MAX_PERC_RATE": (0.1, 10.0, 2.0, "Max percolation rate (mm/d)"),
        "BASEFLOW_COEFF": (0.001, 0.5, 0.05, "Baseflow recession (1/d)"),
        "FIELD_CAPACITY": (0.1, 0.5, 0.31, "Field capacity (fraction)"),
    },
    "hmets": {
        "DEGREE_DAY_MELT_FACTOR": (0.5, 10.0, 3.0, "Melt factor"),
        "DD_MELT_TEMP": (-5.0, 5.0, 0.0, "Melt threshold temp"),
        "HMETS_RUNOFF_COEFF": (0.0, 1.0, 0.5, "Runoff coefficient"),
    },
    "hymod": {
        "HYMOD_CMAX": (1.0, 1000.0, 200.0, "Max soil moisture capacity"),
        "HYMOD_B": (0.0, 2.0, 0.5, "Spatial variability index"),
        "HYMOD_ALPHA": (0.0, 1.0, 0.7, "Quick/slow flow partition"),
        "HYMOD_KS": (0.001, 0.1, 0.01, "Slow reservoir rate"),
        "HYMOD_KQ": (0.1, 0.99, 0.3, "Quick reservoir rate"),
    },
    "sac_sma": {
        "SAC_UZTWM": (1.0, 150.0, 50.0, "UZ tension water max"),
        "SAC_UZFWM": (1.0, 150.0, 40.0, "UZ free water max"),
        "SAC_LZTWM": (1.0, 500.0, 130.0, "LZ tension water max"),
        "SAC_UZK": (0.1, 0.75, 0.3, "UZ depletion rate"),
        "SAC_LZPK": (0.001, 0.05, 0.01, "LZ primary depletion rate"),
        "SAC_PFREE": (0.0, 0.8, 0.06, "Percolation fraction"),
    },
}


def dds_perturbation(x, x_min, x_max, sigma=0.2):
    """DDS perturbation: Gaussian with reflection at bounds."""
    x_new = x + sigma * (x_max - x_min) * np.random.standard_normal()
    # Reflect at bounds
    if x_new < x_min:
        x_new = x_min + (x_min - x_new)
        if x_new > x_max:
            x_new = x_min
    if x_new > x_max:
        x_new = x_max - (x_new - x_max)
        if x_new < x_min:
            x_new = x_max
    return float(x_new)


def update_rvp_parameter(rvp_path, param_name, value):
    """Update a parameter value in the .rvp file."""
    with open(rvp_path) as f:
        content = f.read()

    # Try GlobalParameter block
    pattern = rf"({param_name}\s+)([\d\.\-eE\+]+)"
    new_content = re.sub(pattern, rf"\g<1>{value:.6f}", content)

    # Also try SoilParameterList and other parameter lists
    if new_content == content:
        # Param not found with simple regex — try line-by-line
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            if param_name in line and not line.strip().startswith("#"):
                # Replace numeric values after the param name
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == param_name and i + 1 < len(parts):
                        try:
                            float(parts[i + 1])
                            parts[i + 1] = f"{value:.6f}"
                            break
                        except ValueError:
                            continue
                line = "  ".join(parts)
            new_lines.append(line)
        new_content = "\n".join(new_lines)

    with open(rvp_path, "w") as f:
        f.write(new_content)


def run_raven_once(run_dir, basin_name, raven_exe, timeout=600):
    """Run Raven once and return the objective function value."""
    output_dir = os.path.join(run_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Clean old output
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        os.remove(os.path.join(output_dir, f))

    cmd = [
        os.path.abspath(raven_exe),
        basin_name,
        "-o", os.path.abspath(output_dir) + "/",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=os.path.abspath(run_dir),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)

    if result.returncode != 0:
        return None, f"returncode={result.returncode}: {result.stderr[-200:]}"

    # Parse Diagnostics.csv
    diag_file = None
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        if "diagnostic" in f.lower():
            diag_file = os.path.join(output_dir, f)
            break

    if not diag_file:
        return None, "No Diagnostics.csv found"

    metrics = {}
    with open(diag_file) as f:
        for line in f:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    metrics[parts[0]] = float(parts[1])
                except ValueError:
                    pass

    return metrics, None


def process(args):
    """Run DDS calibration."""
    template = args.template
    if template not in CALIBRATION_PARAMS:
        return {"status": "error", "message": f"No calibration parameters defined for template: {template}"}

    params = CALIBRATION_PARAMS[template]
    param_names = list(params.keys())
    n_params = len(param_names)

    # Initialize with defaults
    x_current = {p: info[2] for p, info in params.items()}
    x_best = x_current.copy()
    best_obj = -999.0

    # DDS parameters
    n_iter = args.n_iterations
    r = 0.2  # perturbation radius

    history = []

    # Backup original .rvp
    rvp_path = os.path.join(args.run_dir, f"{args.basin_name}.rvp")
    rvp_backup = rvp_path + ".backup"
    shutil.copy2(rvp_path, rvp_backup)

    print(f"Starting DDS calibration: {n_iter} iterations, {n_params} parameters", flush=True)
    print(f"Template: {template}", flush=True)
    print(f"Objective: maximize {args.objective}", flush=True)

    t0 = time.time()

    for i in range(n_iter):
        # DDS: probability of perturbing each parameter decreases with iteration
        p_perturb = 1.0 - np.log(i + 1) / np.log(n_iter + 1)

        # Select parameters to perturb
        x_candidate = x_current.copy()
        perturbed_any = False
        for pname in param_names:
            if np.random.random() < p_perturb:
                pmin, pmax, pdef, _ = params[pname]
                x_candidate[pname] = dds_perturbation(x_current[pname], pmin, pmax, sigma=r)
                perturbed_any = True

        # If nothing perturbed, perturb one random parameter
        if not perturbed_any:
            pname = param_names[np.random.randint(n_params)]
            pmin, pmax, pdef, _ = params[pname]
            x_candidate[pname] = dds_perturbation(x_current[pname], pmin, pmax, sigma=r)

        # Update .rvp with candidate parameters
        shutil.copy2(rvp_backup, rvp_path)
        for pname, pval in x_candidate.items():
            update_rvp_parameter(rvp_path, pname, pval)

        # Run model
        metrics, error = run_raven_once(args.run_dir, args.basin_name, args.raven_exe)

        if error:
            history.append({"iter": i + 1, "status": "error", "error": error})
            continue

        # Get objective value
        obj_map = {
            "NSE": "NASH_SUTCLIFFE",
            "KGE": "KLING_GUPTA",
            "RMSE": "RMSE",
        }
        obj_key = obj_map.get(args.objective, args.objective)
        obj_value = metrics.get(obj_key, -999)

        # For RMSE, we minimize (so negate)
        if args.objective == "RMSE":
            obj_compare = -obj_value
        else:
            obj_compare = obj_value

        # Accept if better
        if obj_compare > best_obj:
            best_obj = obj_compare
            x_best = x_candidate.copy()
            x_current = x_candidate.copy()

        history.append({
            "iter": i + 1,
            "objective": obj_value,
            "best_so_far": best_obj if args.objective != "RMSE" else -best_obj,
            "params": {k: round(v, 4) for k, v in x_candidate.items()},
        })

        if (i + 1) % 10 == 0:
            best_display = best_obj if args.objective != "RMSE" else -best_obj
            print(f"  Iter {i+1}/{n_iter}: best {args.objective} = {best_display:.4f}", flush=True)

    elapsed = time.time() - t0

    # Apply best parameters
    shutil.copy2(rvp_backup, rvp_path)
    for pname, pval in x_best.items():
        update_rvp_parameter(rvp_path, pname, pval)

    # Run final model with best params
    final_metrics, _ = run_raven_once(args.run_dir, args.basin_name, args.raven_exe)

    best_display = best_obj if args.objective != "RMSE" else -best_obj

    results = {
        "status": "success",
        "template": template,
        "objective": args.objective,
        "n_iterations": n_iter,
        "elapsed_seconds": round(elapsed, 1),
        "best_parameters": {k: round(v, 6) for k, v in x_best.items()},
        "best_objective": round(best_display, 4),
        "final_metrics": final_metrics or {},
        "convergence_history": history[-20:],  # last 20 for brevity
    }

    # Save full history
    history_path = os.path.join(args.run_dir, "calibration_history.json")
    with open(history_path, "w") as f:
        json.dump(history, f, indent=2)
    results["history_file"] = history_path

    return results


def main():
    parser = argparse.ArgumentParser(description="DDS calibration for Raven")
    parser.add_argument("--run_dir", required=True, help="Raven run directory")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--template", required=True, help="Model template name")
    parser.add_argument("--n_iterations", type=int, default=100, help="Number of DDS iterations")
    parser.add_argument("--objective", default="NSE", help="Objective: NSE, KGE, RMSE")
    parser.add_argument("--raven_exe", default=RAVEN_EXE_DEFAULT, help="Raven executable path")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
        sys.exit(2)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
