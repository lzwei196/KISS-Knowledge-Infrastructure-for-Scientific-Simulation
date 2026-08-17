#!/usr/bin/env python3
"""
run_ensemble_comparison.py — Run multiple Raven model structures on the same basin.

This is Raven's unique capability: run GR4J, HBV-EC, HMETS, MOHYSE, SAC-SMA,
HYMOD, UBC, and HYPR on identical forcing/basin data, then compare performance.

Quantifies STRUCTURAL UNCERTAINTY: how much do results vary by model choice?

Usage:
    python run_ensemble_comparison.py \
        --base_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --templates gr4j,hbv_ec,hmets,hymod,sac_sma \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --raven_exe KISSPATH_BINARIES/raven/Raven.exe
"""

import argparse
import json
import os
import sys
import shutil
from datetime import datetime

# Add tools directory to path
TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TOOLS_DIR, "s0_config"))
sys.path.insert(0, os.path.join(TOOLS_DIR, "s2_parameters"))
sys.path.insert(0, os.path.join(TOOLS_DIR, "s6_execution"))
sys.path.insert(0, os.path.join(TOOLS_DIR, "s7_output"))

try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


DEFAULT_TEMPLATES = ["gr4j", "hbv_ec", "hmets", "hymod", "sac_sma"]
RAVEN_EXE_DEFAULT = "KISSPATH_BINARIES/raven/Raven.exe"


def _load_parse_diagnostics():
    """Import the canonical Diagnostics.csv parser from the s7 output tool.

    Diagnostics.csv is a header row plus one data row per observation series,
    NOT name,value pairs. Re-implementing that parse here is what left ensemble
    diagnostics empty and every model ranked at -999 (dt_rav_037), so the s7
    parser is the single source of truth.
    """
    try:
        from parse_raven_output import parse_diagnostics
        return parse_diagnostics
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "parse_raven_output",
            os.path.join(TOOLS_DIR, "s7_output", "parse_raven_output.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.parse_diagnostics


parse_diagnostics = _load_parse_diagnostics()


def setup_ensemble_run(base_dir, basin_name, template, start_date, end_date):
    """
    Set up a single ensemble member's run directory.
    Copies shared .rvh and .rvt, generates template-specific .rvi and .rvp.
    """
    run_dir = os.path.join(base_dir, "ensemble", template)
    os.makedirs(run_dir, exist_ok=True)

    # Copy shared files (.rvh, .rvt)
    for ext in [".rvh", ".rvt", ".rvc"]:
        src = os.path.join(base_dir, f"{basin_name}{ext}")
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(run_dir, f"{basin_name}{ext}"))

    # Generate template-specific .rvi
    try:
        from select_model_template import TEMPLATES, generate_rvi_content
        rvi_content, _ = generate_rvi_content(template, basin_name, start_date,
                                              end_date, run_dir=run_dir)
        with open(os.path.join(run_dir, f"{basin_name}.rvi"), "w") as f:
            f.write(rvi_content)
    except ImportError:
        # Fallback: try to import from full path
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "select_model_template",
            os.path.join(TOOLS_DIR, "s0_config", "select_model_template.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rvi_content, _ = mod.generate_rvi_content(template, basin_name, start_date,
                                                  end_date, run_dir=run_dir)
        with open(os.path.join(run_dir, f"{basin_name}.rvi"), "w") as f:
            f.write(rvi_content)

    # Generate template-specific .rvp
    try:
        from build_rvp_parameters import parse_rvh_classes, generate_rvp_content, TEMPLATE_PARAMS
        rvh_path = os.path.join(run_dir, f"{basin_name}.rvh")
        lus, vcs, sps, tcs = parse_rvh_classes(rvh_path)
        rvp_content = generate_rvp_content(template, basin_name, lus, vcs, sps, tcs)
        with open(os.path.join(run_dir, f"{basin_name}.rvp"), "w") as f:
            f.write(rvp_content)
    except ImportError:
        spec = importlib.util.spec_from_file_location(
            "build_rvp_parameters",
            os.path.join(TOOLS_DIR, "s2_parameters", "build_rvp_parameters.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rvh_path = os.path.join(run_dir, f"{basin_name}.rvh")
        lus, vcs, sps, tcs = mod.parse_rvh_classes(rvh_path)
        rvp_content = mod.generate_rvp_content(template, basin_name, lus, vcs, sps, tcs)
        with open(os.path.join(run_dir, f"{basin_name}.rvp"), "w") as f:
            f.write(rvp_content)

    return run_dir


def run_single_model(run_dir, basin_name, raven_exe, timeout=1800):
    """Run a single Raven model and parse output."""
    import subprocess
    import time

    output_dir = os.path.join(run_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        os.path.abspath(raven_exe),
        basin_name,
        "-o", os.path.abspath(output_dir) + "/",
    ]

    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=os.path.abspath(run_dir),
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.time() - t0
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {"status": "timeout", "elapsed": elapsed}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    # Parse hydrograph
    hydro_file = None
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        if "hydrograph" in f.lower() and f.endswith(".csv"):
            hydro_file = os.path.join(output_dir, f)
            break

    discharge = None
    if hydro_file:
        try:
            df = pd.read_csv(hydro_file)
            # Get simulated column (3rd column typically)
            if len(df.columns) >= 3:
                sim_col = df.columns[2]
                discharge = pd.to_numeric(df[sim_col], errors="coerce").values
        except Exception:
            pass

    # Parse diagnostics
    diag_file = None
    for f in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
        if "diagnostic" in f.lower() and f.endswith(".csv"):
            diag_file = os.path.join(output_dir, f)
            break

    # Canonical parser (s7): header row + one data row per observation series.
    diagnostics = parse_diagnostics(diag_file) if diag_file else {}

    return {
        "status": "success" if success else "error",
        "elapsed": round(elapsed, 1),
        "output_dir": output_dir,
        "discharge": discharge,
        "diagnostics": diagnostics,
        "returncode": result.returncode,
        "stderr_tail": result.stderr[-300:] if result.stderr else "",
    }


def compute_ensemble_stats(ensemble_results):
    """Compute ensemble statistics across all model structures."""
    # Collect all discharge time series
    discharges = {}
    for template, result in ensemble_results.items():
        if result.get("discharge") is not None:
            discharges[template] = result["discharge"]

    if not discharges:
        return {"warning": "No valid discharge data from any model"}

    stats = {}

    # Per-model mean discharge
    for t, d in discharges.items():
        valid = d[~np.isnan(d)] if isinstance(d, np.ndarray) else d
        if len(valid) > 0:
            stats[t] = {
                "mean_Q_m3s": round(float(np.mean(valid)), 2),
                "max_Q_m3s": round(float(np.max(valid)), 2),
                "annual_volume_mm": None,  # would need area
            }

    # Ensemble spread (structural uncertainty)
    all_means = [s["mean_Q_m3s"] for s in stats.values()]
    if len(all_means) >= 2:
        stats["ensemble"] = {
            "mean_of_means": round(float(np.mean(all_means)), 2),
            "std_of_means": round(float(np.std(all_means)), 2),
            "cv_of_means": round(float(np.std(all_means) / np.mean(all_means)), 3) if np.mean(all_means) > 0 else None,
            "range": [round(float(np.min(all_means)), 2), round(float(np.max(all_means)), 2)],
            "n_models": len(all_means),
        }

    # Rank models by NSE. A member whose Diagnostics.csv carried no NSE is
    # reported as null and sorted last — never as a -999 "score", which reads
    # like a real (terrible) fit instead of a missing measurement.
    ranked = []
    for t, result in ensemble_results.items():
        diag = result.get("diagnostics") or {}
        ranked.append({
            "template": t,
            "NSE": diag.get("NASH_SUTCLIFFE"),
            "KGE": diag.get("KLING_GUPTA"),
            "diagnostics_available": bool(diag),
        })

    ranked.sort(key=lambda x: (x["NSE"] is not None, x["NSE"] if x["NSE"] is not None else 0.0),
                reverse=True)
    stats["ranking"] = ranked
    stats["n_ranked_with_diagnostics"] = sum(1 for r in ranked if r["NSE"] is not None)

    return stats


def process(args):
    """Run all ensemble members and compare."""
    templates = [t.strip() for t in args.templates.split(",")]

    results = {
        "basin_name": args.basin_name,
        "templates": templates,
        "models": {},
    }

    for i, template in enumerate(templates):
        print(f"[{i+1}/{len(templates)}] Running {template}...", flush=True)

        # Setup
        try:
            run_dir = setup_ensemble_run(
                args.base_dir, args.basin_name, template,
                args.start_date, args.end_date,
            )
        except Exception as e:
            results["models"][template] = {"status": "setup_error", "message": str(e)}
            continue

        # Run
        model_result = run_single_model(run_dir, args.basin_name, args.raven_exe)
        results["models"][template] = {
            "status": model_result["status"],
            "elapsed": model_result.get("elapsed"),
            "diagnostics": model_result.get("diagnostics", {}),
            "output_dir": model_result.get("output_dir"),
        }

        if model_result.get("discharge") is not None:
            d = model_result["discharge"]
            valid = d[~np.isnan(d)] if isinstance(d, np.ndarray) else d
            if len(valid) > 0:
                results["models"][template]["mean_Q_m3s"] = round(float(np.mean(valid)), 2)
                results["models"][template]["max_Q_m3s"] = round(float(np.max(valid)), 2)

        print(f"  -> {model_result['status']} ({model_result.get('elapsed', '?')}s)", flush=True)

    # Ensemble statistics
    ensemble_data = {}
    for t, r in results["models"].items():
        if r["status"] == "success":
            # Re-read discharge for statistics
            output_dir = r.get("output_dir", "")
            if os.path.isdir(output_dir):
                for f in os.listdir(output_dir):
                    if "hydrograph" in f.lower() and f.endswith(".csv"):
                        try:
                            df = pd.read_csv(os.path.join(output_dir, f))
                            if len(df.columns) >= 3:
                                d = pd.to_numeric(df[df.columns[2]], errors="coerce").values
                                ensemble_data[t] = {"discharge": d, "diagnostics": r.get("diagnostics", {})}
                        except Exception:
                            pass

    results["ensemble_stats"] = compute_ensemble_stats(ensemble_data)
    results["status"] = "success"

    return results


def main():
    parser = argparse.ArgumentParser(description="Run Raven multi-model ensemble comparison")
    parser.add_argument("--base_dir", required=True, help="Base directory with shared .rvh/.rvt files")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--templates", default=",".join(DEFAULT_TEMPLATES),
                        help="Comma-separated list of templates to run")
    parser.add_argument("--start_date", default="2000-01-01", help="Start date")
    parser.add_argument("--end_date", default="2010-12-31", help="End date")
    parser.add_argument("--raven_exe", default=RAVEN_EXE_DEFAULT, help="Path to Raven executable")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
        sys.exit(2)

    # Serialize — convert numpy arrays to lists for JSON
    def default_serializer(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.int32, np.int64)):
            return int(obj)
        return str(obj)

    print(json.dumps(results, indent=2, default=default_serializer))
    sys.exit(0)


if __name__ == "__main__":
    main()
