#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from typing import Dict, List, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import run_bengbu_ai_calibration as base


PARAM_KEYS = ["binfilt", "Ds", "Dsmax", "Ws", "soil_d2", "soil_d3"]


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def ensure_d3_gt_d2(params: Dict[str, float]) -> None:
    if params["soil_d3"] <= params["soil_d2"]:
        lo, hi = base.PARAM_RANGES["soil_d3"]
        params["soil_d3"] = clamp(params["soil_d2"] + 0.05, lo, hi)


def normalize_params(params: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for k in PARAM_KEYS:
        lo, hi = base.PARAM_RANGES[k]
        out[k] = clamp(float(params[k]), lo, hi)
    ensure_d3_gt_d2(out)
    return out


def read_initial_params_from_soil(soil_path: str) -> Dict[str, float]:
    with open(soil_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if len(parts) <= max(base.INDEX_MAP.values()):
                continue
            params = {
                "binfilt": float(parts[base.INDEX_MAP["binfilt"]]),
                "Ds": float(parts[base.INDEX_MAP["Ds"]]),
                "Dsmax": float(parts[base.INDEX_MAP["Dsmax"]]),
                "Ws": float(parts[base.INDEX_MAP["Ws"]]),
                "soil_d2": float(parts[base.INDEX_MAP["soil_d2"]]),
                "soil_d3": float(parts[base.INDEX_MAP["soil_d3"]]),
            }
            return normalize_params(params)
    raise ValueError(f"No valid data line found in initial soil file: {soil_path}")


def parse_kv_floats(line: str) -> Dict[str, float]:
    kv = {}
    for k, v in re.findall(r"([A-Za-z0-9_]+)=([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", line):
        kv[k] = float(v)
    return kv


def load_batch_candidates(manual_plan_path: str, batch_start_run: int, batch_size: int) -> Tuple[List[Dict[str, float]], str]:
    if not os.path.exists(manual_plan_path):
        return [], ""

    lines = []
    with open(manual_plan_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    candidates = []
    strategy = ""
    marker = f"batch_start_run={batch_start_run}"
    for line in lines:
        if marker in line and "strategy" in line.lower() and not strategy:
            strategy = line.strip()
        if marker in line and "candidate=" in line:
            kv = parse_kv_floats(line)
            if "d2" in kv and "soil_d2" not in kv:
                kv["soil_d2"] = kv["d2"]
            if "d3" in kv and "soil_d3" not in kv:
                kv["soil_d3"] = kv["d3"]
            if all(k in kv for k in PARAM_KEYS):
                params = {k: kv[k] for k in PARAM_KEYS}
                candidates.append(normalize_params(params))

    # unique by candidate order in file; keep first batch_size
    if len(candidates) >= batch_size:
        return candidates[:batch_size], strategy
    return [], strategy


def append_batch_template(manual_plan_path: str, batch_start_run: int, batch_size: int) -> None:
    with open(manual_plan_path, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(f"## batch_start_run={batch_start_run} strategy: [fill by assistant]\n")
        for i in range(1, batch_size + 1):
            f.write(
                f"batch_start_run={batch_start_run}, candidate={i}, "
                "binfilt=0.2000, Ds=0.0000, Dsmax=7.0000, Ws=0.5000, soil_d2=0.3500, soil_d3=1.0000\n"
            )


def generate_auto_batch_candidates(history: List[Dict], fallback: Dict[str, float], batch_size: int) -> Tuple[List[Dict[str, float]], str]:
    """
    Generate one 10-run batch using rule-based manual heuristics.
    This is used only when manual_batch_plan.md has no candidates for the current batch.
    """
    if history:
        best = max(history, key=lambda r: r.get("NSE", float("-inf")))
        base_params = dict(best["params"])
        pbias = float(best.get("PBIAS", 0.0))
        peak = float(best.get("peak_ratio", 1.0))
        lowf = float(best.get("lowflow_ratio", 1.0))
    else:
        base_params = dict(fallback)
        pbias = 0.0
        peak = 1.0
        lowf = 1.0

    strategy_bits = []
    # Bias control
    if pbias < -10:
        base_params["Dsmax"] *= 1.12
        base_params["soil_d2"] *= 1.05
        strategy_bits.append("pbias<0: increase baseflow (Dsmax,d2)")
    elif pbias > 10:
        base_params["Dsmax"] *= 0.90
        base_params["soil_d2"] *= 0.95
        strategy_bits.append("pbias>0: decrease baseflow (Dsmax,d2)")

    # Peak-flow control
    if peak < 0.95:
        base_params["binfilt"] *= 0.92
        base_params["Ws"] *= 0.94
        strategy_bits.append("peak low: lower binfilt/Ws")
    elif peak > 1.05:
        base_params["binfilt"] *= 1.08
        base_params["Ws"] *= 1.06
        strategy_bits.append("peak high: raise binfilt/Ws")

    # Low-flow control
    if lowf > 1.20:
        base_params["Ds"] *= 0.85
        base_params["soil_d3"] *= 0.95
        strategy_bits.append("lowflow high: lower Ds/d3")
    elif lowf < 0.80:
        base_params["Ds"] = max(0.02, base_params["Ds"] * 1.15)
        base_params["soil_d3"] *= 1.05
        strategy_bits.append("lowflow low: raise Ds/d3")

    base_params = normalize_params(base_params)

    # Exploration around adjusted base point (10 candidates)
    deltas = [
        (0.00, 0.00, 0.00, 0.00, 0.00, 0.00),
        (-0.03, 0.00, +0.60, -0.03, +0.02, +0.05),
        (+0.03, 0.00, -0.60, +0.03, -0.02, -0.05),
        (-0.02, -0.02, +0.40, -0.02, +0.01, +0.04),
        (+0.02, +0.02, -0.40, +0.02, -0.01, -0.04),
        (-0.04, 0.00, +0.80, -0.01, +0.03, +0.06),
        (+0.04, 0.00, -0.80, +0.01, -0.03, -0.06),
        (0.00, -0.03, +0.50, 0.00, +0.00, +0.03),
        (0.00, +0.03, -0.50, 0.00, +0.00, -0.03),
        (+0.01, -0.01, +0.20, -0.01, +0.01, +0.02),
    ]

    cands: List[Dict[str, float]] = []
    for i in range(batch_size):
        d = deltas[i % len(deltas)]
        p = dict(base_params)
        p["binfilt"] += d[0]
        p["Ds"] += d[1]
        p["Dsmax"] += d[2]
        p["Ws"] += d[3]
        p["soil_d2"] += d[4]
        p["soil_d3"] += d[5]
        cands.append(normalize_params(p))

    strategy = "; ".join(strategy_bits) if strategy_bits else "local refinement around current best"
    return cands, strategy


def batch_summary_direction(best_row: Dict[str, float]) -> str:
    peak = best_row.get("peak_ratio", float("nan"))
    lowf = best_row.get("lowflow_ratio", float("nan"))
    pbias = best_row.get("PBIAS", float("nan"))

    hints = []
    if isinstance(peak, float):
        if peak < 0.95:
            hints.append("peak low: consider slight lower binfilt / lower Ws")
        elif peak > 1.05:
            hints.append("peak high: consider slight higher binfilt / higher Ws")
    if isinstance(lowf, float) and lowf > 1.20:
        hints.append("lowflow high: consider lower Ds, lower Dsmax, lower soil_d3")
    if isinstance(pbias, float):
        if pbias > 10:
            hints.append("positive bias: consider lower Dsmax / lower soil_d2")
        elif pbias < -10:
            hints.append("negative bias: consider higher Dsmax / higher soil_d2")

    if not hints:
        hints.append("maintain local refinement around current best")
    return "; ".join(hints)


def is_converged(nse_values: List[float]) -> bool:
    if len(nse_values) < 11:
        return False
    latest = nse_values[-1]
    if latest <= 0.85:
        return False
    diffs = [abs(nse_values[i] - nse_values[i - 1]) for i in range(len(nse_values) - 10, len(nse_values))]
    return all(d < 0.005 for d in diffs)


def init_env(output_root: str) -> Tuple[str, str, str, str, str, str]:
    current_dir = os.path.join(output_root, "current_run")
    best_dir = os.path.join(output_root, "best_run")

    base.OUTPUT_ROOT = output_root
    base.CURRENT_DIR = current_dir
    base.BEST_DIR = best_dir
    base.ensure_dir(output_root)

    results_csv = os.path.join(output_root, "calibration_results.csv")
    log_path = os.path.join(output_root, "calibration_log.txt")
    analysis_path = os.path.join(output_root, "ai_analysis.md")
    best_json = os.path.join(output_root, "best_params.json")
    batch_plan = os.path.join(output_root, "batch_plan.md")
    manual_plan = os.path.join(output_root, "manual_batch_plan.md")

    for p in [results_csv, log_path, analysis_path, best_json, batch_plan, manual_plan]:
        if os.path.exists(p):
            os.remove(p)

    base.reset_dir(current_dir)
    if os.path.exists(best_dir):
        shutil.rmtree(best_dir)

    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "run_id",
            "phase",
            "binfilt",
            "Ds",
            "Dsmax",
            "Ws",
            "soil_d2",
            "soil_d3",
            "NSE",
            "RMSE",
            "PBIAS",
            "peak_ratio",
            "lowflow_ratio",
        ])

    with open(batch_plan, "w", encoding="utf-8") as f:
        f.write("# Batch Plan (executed candidates)\n")
    with open(manual_plan, "w", encoding="utf-8") as f:
        f.write("# Manual Batch Plan (assistant-provided candidates)\n")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("# Calibration log\n")
    with open(analysis_path, "w", encoding="utf-8") as f:
        f.write("# AI Analysis\n")

    return results_csv, log_path, analysis_path, best_json, batch_plan, manual_plan


def write_batch_report(
    run_start: int,
    run_end: int,
    rows: List[Dict],
    global_best_before: float,
    global_best_after: float,
    global_best_run: int,
    log_path: str,
    analysis_path: str,
) -> None:
    batch_rows = [r for r in rows if run_start <= r["run_id"] <= run_end]
    if not batch_rows:
        return
    top = sorted(batch_rows, key=lambda x: x["NSE"], reverse=True)
    top1 = top[0]
    top3 = top[:3]

    changed = global_best_after > global_best_before
    delta = global_best_after - global_best_before if global_best_before > -1e20 else 0.0
    next_dir = batch_summary_direction(top1)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\nBatch summary: runs {run_start}-{run_end}\n")
        f.write("Top candidates in this batch:\n")
        for i, r in enumerate(top3, start=1):
            f.write(
                f"  Top{i}: run {r['run_id']} NSE={r['NSE']:.4f} RMSE={r['RMSE']:.2f} PBIAS={r['PBIAS']:.2f}% "
                f"params={r['params']}\n"
            )
        f.write(
            f"Global best change: {'updated' if changed else 'unchanged'} | "
            f"best_run={global_best_run} best_NSE={global_best_after:.4f} delta={delta:+.4f}\n"
        )
        f.write(f"Next batch suggestion: {next_dir}\n")

    with open(analysis_path, "a", encoding="utf-8") as f:
        f.write(f"\n## Batch {run_start}-{run_end}\n")
        f.write("### 10-run parameter table\n")
        for r in batch_rows:
            f.write(
                f"- run {r['run_id']}: {r['params']} | NSE={r['NSE']:.4f}, RMSE={r['RMSE']:.2f}, PBIAS={r['PBIAS']:.2f}%\n"
            )
        f.write("\n### Batch Top Results\n")
        for i, r in enumerate(top3, start=1):
            f.write(f"- Top{i}: run {r['run_id']} NSE={r['NSE']:.4f}, PBIAS={r['PBIAS']:.2f}%\n")
        f.write("\n### Global Best Change\n")
        f.write(
            f"- {'Updated' if changed else 'Unchanged'}; best run={global_best_run}, best NSE={global_best_after:.4f}, delta={delta:+.4f}\n"
        )
        f.write("\n### Next Batch Direction\n")
        f.write(f"- {next_dir}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual AI batch calibration (no random stage)")
    parser.add_argument("--basin-name", type=str, default="bengbu", help="Basin name from shp")
    parser.add_argument("--initial-soil", type=str, required=True, help="Initial soil parameter file")
    parser.add_argument("--soil-base", type=str, default="", help="Base soil parameter file for full-grid rewriting (default: same as --initial-soil)")
    parser.add_argument("--global-base", type=str, default=base.GLOBAL_BASE, help="Base VIC global parameter file")
    parser.add_argument("--obs-file", type=str, default=base.OBS_FILE, help="Observed discharge file")
    parser.add_argument("--routing-template-dir", type=str, default=base.ROUT_TEMPLATE_DIR, help="Routing template directory")
    parser.add_argument("--vic-exe", type=str, default=base.VIC_EXE, help="VIC executable")
    parser.add_argument("--rout-exe", type=str, default=base.ROUT_EXE, help="Routing executable")
    parser.add_argument("--base-output-dir", type=str, default=base.BASE_OUTPUT_DIR, help="Base output directory")
    parser.add_argument("--start-year", type=int, default=1979, help="Simulation start year")
    parser.add_argument("--end-year", type=int, default=1980, help="Simulation end year")
    parser.add_argument("--flux-prefix", type=str, default="huaihe_fluxes_", help="Routing global flux prefix in vic_in")
    parser.add_argument("--max-runs", type=int, default=100, help="Maximum AI runs")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size")
    parser.add_argument("--auto-continue", dest="auto_continue", action="store_true", default=True,
                        help="Auto continue batches (default true)")
    parser.add_argument("--no-auto-continue", dest="auto_continue", action="store_false",
                        help="Disable auto continuation")
    args = parser.parse_args()

    soil_base = args.soil_base if args.soil_base else args.initial_soil

    runtime_cfg = base.RuntimeConfig(
        basin_name=args.basin_name,
        base_output_dir=args.base_output_dir,
        soil_base=soil_base,
        global_base=args.global_base,
        obs_file=args.obs_file,
        rout_template_dir=args.routing_template_dir,
        vic_exe=args.vic_exe,
        rout_exe=args.rout_exe,
        start_year=args.start_year,
        end_year=args.end_year,
        flux_prefix=args.flux_prefix,
    )
    base.configure_runtime(runtime_cfg)

    output_root = os.path.join(args.base_output_dir, f"{args.basin_name}_calibration_ai")
    results_csv, log_path, analysis_path, best_json, batch_plan, manual_plan = init_env(output_root)

    initial_params = read_initial_params_from_soil(args.initial_soil)

    history: List[Dict] = []
    best_nse = float("-inf")
    best_run = -1
    nse_series: List[float] = []

    queue: List[Dict[str, float]] = []
    current_batch_start = None
    batch_strategy = ""

    for run_id in range(1, args.max_runs + 1):
        if run_id == 1:
            params = dict(initial_params)
            phase = "ai_manual"
            decision = "initial from user-specified soil parameter file"
        elif (run_id - 2) % args.batch_size == 0:
            current_batch_start = run_id
            candidates, batch_strategy = load_batch_candidates(manual_plan, run_id, args.batch_size)
            if not candidates:
                candidates, auto_strategy = generate_auto_batch_candidates(history, initial_params, args.batch_size)
                batch_strategy = f"auto-generated: {auto_strategy}"
                with open(manual_plan, "a", encoding="utf-8") as f:
                    f.write("\n")
                    f.write(f"## batch_start_run={run_id} strategy: {batch_strategy}\n")
                    for idx, p in enumerate(candidates, start=1):
                        f.write(
                            f"batch_start_run={run_id}, candidate={idx}, "
                            f"binfilt={p['binfilt']:.4f}, Ds={p['Ds']:.4f}, Dsmax={p['Dsmax']:.4f}, "
                            f"Ws={p['Ws']:.4f}, soil_d2={p['soil_d2']:.4f}, soil_d3={p['soil_d3']:.4f}\n"
                        )
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"\nNo manual candidates found for batch_start_run={run_id}. "
                        "Auto-generated one batch and continued.\n"
                    )

            queue = list(candidates)
            with open(batch_plan, "a", encoding="utf-8") as f:
                f.write(f"\n## batch_start_run={run_id}\n")
                if batch_strategy:
                    f.write(f"- strategy: {batch_strategy}\n")
                for idx, p in enumerate(queue, start=1):
                    f.write(f"- candidate={idx}, params={p}\n")

            params = queue.pop(0)
            phase = "ai_manual"
            decision = batch_strategy or "manual batch from manual_batch_plan.md"
        else:
            if not queue:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"Run {run_id} skipped: empty batch queue.\n")
                continue
            params = queue.pop(0)
            phase = "ai_manual"
            decision = "within current manual 10-run batch"

        start_dt = dt.datetime.now()
        start_epoch = time.time()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Run {run_id} start_time: {start_dt.strftime('%Y-%m-%d %H:%M:%S')} | phase={phase} | params={params}\n")

        ok, metrics = base.run_once(run_id, params, phase, log_path)

        end_dt = dt.datetime.now()
        duration = time.time() - start_epoch

        if not ok:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(
                    f"Run {run_id} end_time: {end_dt.strftime('%Y-%m-%d %H:%M:%S')} | "
                    f"duration_sec={duration:.1f} | status=FAILED\n"
                )
            continue

        with open(results_csv, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                run_id,
                phase,
                params["binfilt"],
                params["Ds"],
                params["Dsmax"],
                params["Ws"],
                params["soil_d2"],
                params["soil_d3"],
                metrics["NSE"],
                metrics["RMSE"],
                metrics["PBIAS"],
                metrics["peak_ratio"],
                metrics["lowflow_ratio"],
            ])

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"Run {run_id} end_time: {end_dt.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"duration_sec={duration:.1f} | NSE={metrics['NSE']:.4f} | "
                f"RMSE={metrics['RMSE']:.2f} | PBIAS={metrics['PBIAS']:.2f}%\n"
            )

        row = {"run_id": run_id, "params": params, **metrics}
        history.append(row)
        nse_series.append(metrics["NSE"])

        if metrics["NSE"] > best_nse:
            best_nse = metrics["NSE"]
            best_run = run_id
            with open(best_json, "w", encoding="utf-8") as f:
                json.dump({"run_id": best_run, "params": params, **metrics}, f, indent=2)
            base.copy_best(base.CURRENT_DIR, base.BEST_DIR)

        base.write_analysis(analysis_path, run_id, params, metrics, best_nse, best_run, decision)

        # Batch summary at end of each 10-run batch (runs 2-11, 12-21, ...)
        if run_id >= 2 and (run_id - 1) % args.batch_size == 0:
            batch_start = run_id - args.batch_size + 1
            batch_end = run_id
            global_before = max([r["NSE"] for r in history if r["run_id"] < batch_start], default=float("-inf"))
            write_batch_report(
                batch_start,
                batch_end,
                history,
                global_before,
                best_nse,
                best_run,
                log_path,
                analysis_path,
            )
            if not args.auto_continue:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\nPaused by --no-auto-continue after current batch.\n")
                break

        if is_converged(nse_series):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(
                    "\nStopping condition met: NSE>0.85 and last 10 adjacent NSE changes < 0.005.\n"
                )
            break

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\nFinished. best_run={best_run}, best_NSE={best_nse:.4f}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
