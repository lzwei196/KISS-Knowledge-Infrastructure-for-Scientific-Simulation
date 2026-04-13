#!/usr/bin/env python3
"""
rzwqm2_calibrate.py
===================
AI-guided RZWQM2 calibration using Latin Hypercube Sampling + agent-directed
batch optimization.

Architecture (mirrors VIC vic_cali_ai):
    - 10-run batches
    - Round 1: Latin Hypercube or Sobol sampling for initial exploration
    - Subsequent rounds: agent analyzes results, writes next batch parameters
    - Auto-continue mode: if no manual plan, generate heuristic batch from
      error signals (PBIAS on yield, soil moisture NSE)
    - Stop: combined_score < threshold OR max_runs reached

Calibration parameters (multipliers applied to ALL horizons):
    - ksat_factor:  Saturated hydraulic conductivity multiplier [0.2, 5.0]
    - ws_factor:    Porosity (saturated water content) multiplier [0.85, 1.15]
    - fc33_factor:  Field capacity multiplier [0.7, 1.4]

Usage:
    python rzwqm2_calibrate.py \\
        --scenario_dir <path> \\
        --obs_yield <csv> \\
        [--obs_sm <csv>] \\
        [--max_runs 100] \\
        [--batch_size 10] \\
        [--output_dir <path>]

Outputs:
    calibration_results.csv   — all runs with params + metrics
    calibration_log.txt       — detailed log
    best_params.json          — best parameter set found
    batch_plan.md             — agent-writable next batch plan
"""
import sys
import os
import json
import csv
import shutil
import time
import subprocess
import math
from pathlib import Path
from datetime import datetime

# Add lib and tool paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(LIB_DIR))
sys.path.insert(0, SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Parameter ranges (multipliers)
# ---------------------------------------------------------------------------
PARAM_RANGES = {
    'ksat_factor':    (0.3, 6.0),       # vertical Ksat multiplier (wider)
    'ws_factor':      (0.82, 1.12),     # porosity multiplier (wider)
    'fc33_factor':    (0.5, 1.5),       # field capacity multiplier (wider)
    'lateral_ksat':   (0.2, 12.0),      # lateral Ksat to drains (cm/hr, wider)
    'drain_spacing':  (500.0, 4000.0),  # tile drain spacing (cm, wider)
    'field_sat':      (0.70, 1.0),      # field saturation fraction (much wider)
}

PARAM_NAMES = list(PARAM_RANGES.keys())


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def normalize_params(params):
    """Clamp all parameters to valid ranges."""
    return {k: clamp(params[k], *PARAM_RANGES[k]) for k in PARAM_NAMES}


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def latin_hypercube_sample(n_samples, seed=42):
    """Generate n_samples parameter sets via Latin Hypercube Sampling."""
    import random
    rng = random.Random(seed)

    n_params = len(PARAM_NAMES)
    # Create stratified intervals
    intervals = []
    for p in PARAM_NAMES:
        lo, hi = PARAM_RANGES[p]
        edges = [lo + (hi - lo) * i / n_samples for i in range(n_samples)]
        rng.shuffle(edges)
        intervals.append(edges)

    samples = []
    for i in range(n_samples):
        params = {}
        for j, p in enumerate(PARAM_NAMES):
            lo, hi = PARAM_RANGES[p]
            width = (hi - lo) / n_samples
            params[p] = intervals[j][i] + rng.uniform(0, width)
            params[p] = clamp(params[p], lo, hi)
        samples.append(params)

    return samples


def sobol_sample(n_samples, seed=42):
    """Generate n_samples via Sobol-like quasi-random sequence (simple version)."""
    import random
    rng = random.Random(seed)

    # Use van der Corput sequences for each dimension
    def van_der_corput(n, base):
        seq = []
        for i in range(1, n + 1):
            val, denom = 0.0, 1.0
            num = i
            while num > 0:
                denom *= base
                val += (num % base) / denom
                num //= base
            seq.append(val)
        return seq

    bases = [2, 3, 5, 7, 11, 13]  # one per parameter dimension
    sequences = [van_der_corput(n_samples, b) for b in bases[:len(PARAM_NAMES)]]

    samples = []
    for i in range(n_samples):
        params = {}
        for j, p in enumerate(PARAM_NAMES):
            lo, hi = PARAM_RANGES[p]
            params[p] = lo + (hi - lo) * sequences[j][i]
        samples.append(params)

    return samples


# ---------------------------------------------------------------------------
# Run RZWQM2 once
# ---------------------------------------------------------------------------
def run_once(run_id, params, scenario_dir, output_dir, obs_yield_path, obs_sm_path, log_path):
    """Execute one calibration run: modify params → run RZWQM2 → parse output → compute metrics.

    Returns (success: bool, metrics: dict)
    """
    t0 = time.time()

    # Step 0: Restore from backup to ensure clean state before every run
    for name in ('rzwqm.dat', 'RZWQM.dat'):
        dat = os.path.join(scenario_dir, name)
        bak = dat + '.cali_bak'
        if os.path.isfile(bak):
            shutil.copy2(bak, dat)
            break

    # Step 1: Modify soil parameters (direct call, no subprocess)
    from modify_soil_params import apply_factors
    mod_result, mod_err = apply_factors(
        scenario_dir, params['ksat_factor'], params['ws_factor'], params['fc33_factor'],
        lateral_ksat=params.get('lateral_ksat'),
        drain_spacing=params.get('drain_spacing'),
        field_sat=params.get('field_sat'),
    )
    if mod_err:
        _log(log_path, f"Run {run_id}: modify_soil_params FAILED: {mod_err}")
        return False, {}

    # Step 2: Run RZWQM2 binary
    # Find the binary in the scenario directory
    binary = None
    for name in ('main_rzwqm_patched', 'main_ryzen_patched', 'main_ryzen', 'RZWQMRelease.exe'):
        p = os.path.join(scenario_dir, name)
        if os.path.isfile(p):
            binary = p
            break

    if not binary:
        _log(log_path, f"Run {run_id}: No RZWQM2 binary found in {scenario_dir}")
        return False, {}

    _log(log_path, f"Run {run_id}: Starting RZWQM2 ({os.path.basename(binary)})...")
    rz_result = subprocess.run(
        [binary],
        cwd=scenario_dir,
        capture_output=True, text=True,
        timeout=600,  # 10 min max
    )
    duration = time.time() - t0

    # Check for completion (RZWQM2 prints "check your expdata.dat" on success)
    stdout = rz_result.stdout + rz_result.stderr
    if 'check your expdata' not in stdout.lower() and rz_result.returncode != 0:
        _log(log_path, f"Run {run_id}: RZWQM2 FAILED (exit={rz_result.returncode}, {duration:.0f}s)")
        return False, {}

    # Step 3: Parse output and compute metrics
    parse_cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, 'parse_rzwqm2_output.py'),
        scenario_dir,
    ]
    if obs_yield_path:
        parse_cmd += ['--obs_yield', obs_yield_path]
    if obs_sm_path:
        parse_cmd += ['--obs_sm', obs_sm_path]

    parse_result = subprocess.run(parse_cmd, capture_output=True, text=True, timeout=60)
    if parse_result.returncode != 0:
        _log(log_path, f"Run {run_id}: parse_output FAILED: {parse_result.stdout}")
        return False, {}

    try:
        parsed = json.loads(parse_result.stdout)
        result_data = parsed.get('result', {})
        metrics = result_data.get('metrics', {})
        metrics['sim_yield_mean'] = result_data.get('sim_yield_mean', -99)
        metrics['sim_sm_mean'] = result_data.get('sim_sm_mean', -99)
        metrics['sim_et_mean'] = result_data.get('sim_et_mean', -99)
        metrics['duration_sec'] = round(duration, 1)
    except (json.JSONDecodeError, KeyError) as e:
        _log(log_path, f"Run {run_id}: JSON parse error: {e}")
        return False, {}

    _log(log_path, (
        f"Run {run_id}: ksat={params['ksat_factor']:.3f} ws={params['ws_factor']:.3f} "
        f"fc33={params['fc33_factor']:.3f} | yield={metrics.get('sim_yield_mean', '?')} "
        f"score={metrics.get('combined_score', '?')} ({duration:.0f}s)"
    ))

    return True, metrics


# ---------------------------------------------------------------------------
# Auto batch generation (heuristic, when agent doesn't provide manual plan)
# ---------------------------------------------------------------------------
def generate_auto_batch(history, batch_size=10):
    """Generate next batch from error signals of the best run so far.

    Returns (candidates: list of param dicts, strategy: str).
    """
    if not history:
        return latin_hypercube_sample(batch_size), "initial_lhs"

    # Find best run
    best = min(history, key=lambda h: h.get('combined_score', 999))
    base = {k: best[k] for k in PARAM_NAMES}

    strategy_parts = []
    yield_pbias = best.get('yield_pbias', 0)
    sm_nse = best.get('sm_nse', -999)

    # Adjust based on yield bias
    if yield_pbias < -20:
        base['ksat_factor'] *= 0.85
        base['fc33_factor'] *= 1.08
        strategy_parts.append(f"yield_low(pbias={yield_pbias:.0f}%): ↓ksat ↑fc33")
    elif yield_pbias > 20:
        base['ksat_factor'] *= 1.15
        base['fc33_factor'] *= 0.92
        strategy_parts.append(f"yield_high(pbias={yield_pbias:.0f}%): ↑ksat ↓fc33")

    # Adjust based on soil moisture
    sm_pbias = best.get('sm_pbias', 0)
    if sm_pbias > 15:
        # Too wet → increase drainage, reduce field_sat
        base['lateral_ksat'] = min(base.get('lateral_ksat', 3.0) * 1.2, 8.0)
        base['drain_spacing'] = max(base.get('drain_spacing', 1500) * 0.85, 800)
        base['field_sat'] = max(base.get('field_sat', 0.95) - 0.03, 0.80)
        strategy_parts.append(f"sm_wet(pbias={sm_pbias:.0f}%): ↑lat_ksat ↓spacing ↓field_sat")
    elif sm_pbias < -10:
        base['lateral_ksat'] = max(base.get('lateral_ksat', 3.0) * 0.8, 0.5)
        base['drain_spacing'] = min(base.get('drain_spacing', 1500) * 1.15, 3000)
        base['field_sat'] = min(base.get('field_sat', 0.95) + 0.03, 1.0)
        strategy_parts.append(f"sm_dry(pbias={sm_pbias:.0f}%): ↓lat_ksat ↑spacing ↑field_sat")

    if sm_nse < 0.3 and sm_nse > -900:
        base['ws_factor'] = max(base.get('ws_factor', 1.0) * 0.97, 0.88)
        strategy_parts.append(f"sm_pattern(NSE={sm_nse:.2f}): adjust ws")

    base = normalize_params(base)
    strategy = "; ".join(strategy_parts) if strategy_parts else "exploration around best"

    # Generate candidates: base + 9 perturbations
    import random
    rng = random.Random(int(time.time()))

    # 6-param deltas: (ksat, ws, fc33, lat_ksat, drain_sp, field_sat)
    deltas = [
        (0.00, 0.00, 0.00, 0.0, 0, 0.00),        # base
        (-0.3, 0.00, +0.05, +0.5, -100, -0.02),   # wetter soil, more drainage
        (+0.3, 0.00, -0.05, -0.5, +100, +0.02),   # drier soil, less drainage
        (0.00, +0.03, 0.00, 0.0, 0, -0.03),       # higher porosity, lower field_sat
        (0.00, -0.03, 0.00, +1.0, -200, 0.00),    # lower porosity, faster drain
        (-0.2, +0.02, +0.08, -0.3, +150, +0.03),  # wet shift
        (+0.2, -0.02, -0.08, +1.0, -200, -0.03),  # dry shift (drain more)
        (0.00, 0.00, 0.00, +2.0, -300, -0.05),    # aggressive drain
        (0.00, 0.00, 0.00, -1.0, +200, +0.05),    # reduce drain
        (0.00, 0.00, 0.00, 0.0, 0, 0.00),         # random perturbation
    ]

    candidates = []
    for i, (dk, dw, df, dl, ds, dfs) in enumerate(deltas):
        p = {
            'ksat_factor': base.get('ksat_factor', 2.0) + dk + rng.uniform(-0.1, 0.1),
            'ws_factor': base.get('ws_factor', 0.95) + dw + rng.uniform(-0.01, 0.01),
            'fc33_factor': base.get('fc33_factor', 1.0) + df + rng.uniform(-0.02, 0.02),
            'lateral_ksat': base.get('lateral_ksat', 3.0) + dl + rng.uniform(-0.3, 0.3),
            'drain_spacing': base.get('drain_spacing', 1500) + ds + rng.uniform(-50, 50),
            'field_sat': base.get('field_sat', 0.95) + dfs + rng.uniform(-0.01, 0.01),
        }
        candidates.append(normalize_params(p))

    return candidates[:batch_size], strategy


# ---------------------------------------------------------------------------
# Manual batch plan loading
# ---------------------------------------------------------------------------
def load_manual_batch(plan_path, batch_start_run):
    """Load agent-written batch plan from markdown file.

    Format:
        ## batch_start_run=11 strategy: description
        batch_start_run=11, candidate=1, ksat_factor=1.5, ws_factor=1.0, fc33_factor=0.9
        ...
    """
    if not os.path.isfile(plan_path):
        return [], ""

    candidates = []
    strategy = ""
    with open(plan_path) as f:
        for line in f:
            line = line.strip()
            if f"batch_start_run={batch_start_run}" in line:
                if line.startswith('##'):
                    # Extract strategy from header
                    if 'strategy:' in line:
                        strategy = line.split('strategy:', 1)[1].strip()
                elif 'candidate=' in line:
                    # Parse parameter values
                    parts = {}
                    for segment in line.split(','):
                        segment = segment.strip()
                        if '=' in segment:
                            k, v = segment.split('=', 1)
                            k = k.strip()
                            if k in PARAM_NAMES:
                                parts[k] = float(v.strip())
                    if len(parts) == len(PARAM_NAMES):
                        candidates.append(normalize_params(parts))

    return candidates, strategy


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------
def is_converged(scores, threshold=0.15, window=10):
    """Stop when score is below threshold and stable over last window runs."""
    if len(scores) < window + 1:
        return False
    if scores[-1] > threshold:
        return False
    diffs = [abs(scores[i] - scores[i - 1]) for i in range(len(scores) - window, len(scores))]
    return all(d < 0.01 for d in diffs)


# ---------------------------------------------------------------------------
# Logging and output
# ---------------------------------------------------------------------------
def _log(log_path, msg):
    """Append timestamped message to log file and print to stderr."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(log_path, 'a') as f:
        f.write(line + '\n')
    print(line, file=sys.stderr)


def write_results_csv(csv_path, history):
    """Write/overwrite calibration results CSV."""
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'run_id', 'ksat_factor', 'ws_factor', 'fc33_factor',
            'lateral_ksat', 'drain_spacing', 'field_sat',
            'sim_yield_mean', 'yield_rmse', 'yield_pbias',
            'sm_nse', 'sm_rmse', 'sm_pbias', 'combined_score', 'duration_sec'
        ])
        for h in history:
            writer.writerow([
                h['run_id'],
                f"{h.get('ksat_factor', -99):.4f}",
                f"{h.get('ws_factor', -99):.4f}",
                f"{h.get('fc33_factor', -99):.4f}",
                f"{h.get('lateral_ksat', -99):.2f}",
                f"{h.get('drain_spacing', -99):.0f}",
                f"{h.get('field_sat', -99):.3f}",
                h.get('sim_yield_mean', -99),
                h.get('yield_rmse', -99),
                h.get('yield_pbias', -99),
                h.get('sm_nse', -99),
                h.get('sm_rmse', -99),
                h.get('sm_pbias', -99),
                h.get('combined_score', -99),
                h.get('duration_sec', -99),
            ])


def write_batch_summary(log_path, batch_num, batch_history, global_best):
    """Write batch summary with hints for the agent."""
    _log(log_path, f"\n{'='*60}")
    _log(log_path, f"BATCH {batch_num} SUMMARY (runs {batch_history[0]['run_id']}-{batch_history[-1]['run_id']})")
    _log(log_path, f"{'='*60}")

    # Top 3
    sorted_batch = sorted(batch_history, key=lambda h: h.get('combined_score', 999))
    for rank, h in enumerate(sorted_batch[:3], 1):
        _log(log_path, (
            f"  Top{rank}: run {h['run_id']} score={h.get('combined_score', '?'):.4f} "
            f"yield={h.get('sim_yield_mean', '?')} "
            f"ksat={h['ksat_factor']:.3f} ws={h['ws_factor']:.3f} fc33={h['fc33_factor']:.3f}"
        ))

    _log(log_path, f"  Global best: run {global_best['run_id']} score={global_best.get('combined_score', '?'):.4f}")

    # Direction hints
    best = sorted_batch[0]
    hints = []
    pbias = best.get('yield_pbias', 0)
    sm_nse = best.get('sm_nse', -999)
    if pbias < -20:
        hints.append("yield too low → try ↓ksat_factor, ↑fc33_factor")
    elif pbias > 20:
        hints.append("yield too high → try ↑ksat_factor, ↓fc33_factor")
    if sm_nse < 0.3 and sm_nse > -900:
        hints.append(f"soil moisture poor (NSE={sm_nse:.2f}) → try adjusting ws_factor")
    if not hints:
        hints.append("results look reasonable — try fine-tuning around current best")

    _log(log_path, f"  Direction hints: {'; '.join(hints)}")
    _log(log_path, "")


# ---------------------------------------------------------------------------
# Main calibration loop
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="RZWQM2 AI-guided calibration")
    parser.add_argument('--scenario_dir', required=True)
    parser.add_argument('--obs_yield', default=None)
    parser.add_argument('--obs_sm', default=None)
    parser.add_argument('--max_runs', type=int, default=100)
    parser.add_argument('--batch_size', type=int, default=10)
    parser.add_argument('--output_dir', default=None)
    parser.add_argument('--sampling', choices=['lhs', 'sobol'], default='lhs')
    parser.add_argument('--no_auto_continue', action='store_true')
    args = parser.parse_args()

    scenario_dir = os.path.abspath(args.scenario_dir)
    output_dir = args.output_dir or os.path.join(scenario_dir, 'calibration')
    os.makedirs(output_dir, exist_ok=True)

    log_path = os.path.join(output_dir, 'calibration_log.txt')
    csv_path = os.path.join(output_dir, 'calibration_results.csv')
    best_path = os.path.join(output_dir, 'best_params.json')
    plan_path = os.path.join(output_dir, 'batch_plan.md')

    # Backup original rzwqm.dat
    for name in ('rzwqm.dat', 'RZWQM.dat'):
        dat = os.path.join(scenario_dir, name)
        if os.path.isfile(dat):
            bak = dat + '.cali_bak'
            if not os.path.isfile(bak):
                shutil.copy2(dat, bak)
            break

    _log(log_path, f"RZWQM2 Calibration started")
    _log(log_path, f"  scenario: {scenario_dir}")
    _log(log_path, f"  obs_yield: {args.obs_yield}")
    _log(log_path, f"  obs_sm: {args.obs_sm}")
    _log(log_path, f"  max_runs: {args.max_runs}, batch_size: {args.batch_size}")
    _log(log_path, f"  sampling: {args.sampling}")

    history = []
    scores = []
    best_score = 999.0
    best_run = None
    queue = []
    batch_num = 0
    batch_history = []

    for run_id in range(1, args.max_runs + 1):
        # --- Get parameters for this run ---
        if not queue:
            batch_num += 1

            if batch_num == 1:
                # Initial sampling
                if args.sampling == 'sobol':
                    queue = sobol_sample(args.batch_size)
                else:
                    queue = latin_hypercube_sample(args.batch_size)
                strategy = f"initial_{args.sampling}"
            else:
                # Try manual plan first
                batch_start = run_id
                manual_candidates, manual_strategy = load_manual_batch(plan_path, batch_start)
                if manual_candidates:
                    queue = manual_candidates
                    strategy = f"manual: {manual_strategy}"
                else:
                    queue, strategy = generate_auto_batch(history, args.batch_size)

            _log(log_path, f"\nBatch {batch_num} starting at run {run_id}: {strategy}")
            batch_history = []

        params = queue.pop(0)

        # --- Run ---
        ok, metrics = run_once(
            run_id, params, scenario_dir, output_dir,
            args.obs_yield, args.obs_sm, log_path
        )

        if not ok:
            entry = {'run_id': run_id, **params, 'combined_score': 999}
            history.append(entry)
            batch_history.append(entry)
            scores.append(999)
            continue

        entry = {'run_id': run_id, **params, **metrics}
        history.append(entry)
        batch_history.append(entry)

        score = metrics.get('combined_score', 999)
        scores.append(score)

        # Update best
        if score < best_score and score > -900:
            best_score = score
            best_run = entry
            with open(best_path, 'w') as f:
                json.dump(best_run, f, indent=2, default=str)
            _log(log_path, f"  *** NEW BEST: run {run_id} score={score:.4f}")

        # Write results after every run
        write_results_csv(csv_path, history)

        # End of batch summary
        if len(batch_history) >= args.batch_size:
            write_batch_summary(log_path, batch_num, batch_history, best_run or entry)

            if args.no_auto_continue:
                _log(log_path, "Pausing for agent review. Write next batch to batch_plan.md and re-run.")
                break

        # Convergence check
        if is_converged(scores):
            _log(log_path, f"\nCONVERGED at run {run_id} (score={score:.4f})")
            break

    # Restore original rzwqm.dat
    for name in ('rzwqm.dat', 'RZWQM.dat'):
        dat = os.path.join(scenario_dir, name)
        bak = dat + '.cali_bak'
        if os.path.isfile(bak):
            shutil.copy2(bak, dat)
            break

    # Final summary
    _log(log_path, f"\nCalibration complete: {len(history)} runs")
    if best_run:
        _log(log_path, f"Best: run {best_run['run_id']} score={best_score:.4f}")
        _log(log_path, f"  ksat={best_run['ksat_factor']:.4f} ws={best_run['ws_factor']:.4f} fc33={best_run['fc33_factor']:.4f}")
        _log(log_path, f"  yield={best_run.get('sim_yield_mean', '?')} yield_pbias={best_run.get('yield_pbias', '?')}")

    print(json.dumps({
        "status": "SUCCESS",
        "total_runs": len(history),
        "best_run": best_run,
        "output_dir": output_dir,
    }, default=str))


if __name__ == '__main__':
    main()
