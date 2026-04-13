#!/usr/bin/env python3
"""
Automated calibration for HEC-HMS using GLUE-style random sampling.

Samples parameter space (CN, Ia_ratio, k_recession, q_base_init, recharge_fraction)
and selects the parameter set that maximizes KGE (or NSE) against observed discharge.

Usage:
  python3 calibrate_hms.py \
    --forcing_csv ./forcing_out/basin_avg_forcing.csv \
    --obs_file /path/to/51080_bengbu.txt \
    --basin_area_km2 121330 \
    --start_date 1981-01-01 --end_date 1990-12-31 \
    --n_samples 500 \
    --output_params ./calibrated_params.json
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Import the run engine
sys.path.insert(0, os.path.dirname(__file__))
from run_hec_hms import scs_cn_loss, scs_unit_hydrograph, linear_reservoir_baseflow, estimate_tp_from_area


# ---------------------------------------------------------------------------
# Parameter ranges for calibration
# ---------------------------------------------------------------------------
PARAM_RANGES = {
    "cn":                  (50.0, 95.0),     # Curve Number
    "ia_ratio":            (0.01, 0.20),     # Initial abstraction ratio
    "k_recession":         (0.80, 0.999),    # Baseflow recession constant
    "q_base_init":         (10.0, 200.0),    # Initial baseflow (m³/s)
    "recharge_fraction":   (0.01, 0.20),     # Groundwater recharge fraction
    "tp_scale":            (0.5, 2.0),       # Multiplier on estimated Tp
}


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check inputs exist."""
    errors = []
    if not os.path.isfile(args.forcing_csv):
        errors.append(f"Forcing CSV not found: {args.forcing_csv}")
    if not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")
    if args.basin_area_km2 <= 0:
        errors.append("Basin area must be positive")
    if args.n_samples < 10:
        errors.append("Need at least 10 samples")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Read observation data
# ---------------------------------------------------------------------------
def read_observations(obs_file, start_date, end_date):
    """Read observed discharge."""
    try:
        df = pd.read_csv(obs_file, sep=r"\s+", header=None,
                         names=["stcd", "date", "z", "Q", "name"],
                         parse_dates=["date"], na_values=["-9999", "-99", "NA", ""])
    except Exception:
        df = pd.read_csv(obs_file, sep=None, engine="python", header=None,
                         parse_dates=[1], na_values=["-9999", "-99", "NA", ""])
        df.columns = ["stcd", "date", "z", "Q", "name"][:len(df.columns)]

    df = df.dropna(subset=["date"])
    df["Q"] = pd.to_numeric(df["Q"], errors="coerce")
    df = df.set_index("date").sort_index()
    df = df[df["Q"] > 0]

    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]

    return df["Q"].resample("D").mean()


# ---------------------------------------------------------------------------
# Single run with given parameters
# ---------------------------------------------------------------------------
def run_single(precip_mm, basin_area_km2, params, tp_base):
    """Run a single simulation with given parameter set."""
    cn = params["cn"]
    ia_ratio = params["ia_ratio"]
    k_recession = params["k_recession"]
    q_init = params["q_base_init"]
    recharge_frac = params["recharge_fraction"]
    tp_hr = tp_base * params["tp_scale"]

    # SCS-CN loss
    runoff_mm, loss_mm = scs_cn_loss(precip_mm, cn, ia_ratio)

    # SCS Unit Hydrograph
    q_direct = scs_unit_hydrograph(runoff_mm, basin_area_km2, tp_hr, dt_hr=24.0)

    # Baseflow
    q_base = linear_reservoir_baseflow(
        precip_mm, runoff_mm, basin_area_km2,
        k_recession=k_recession, q_init_m3s=q_init,
        recharge_fraction=recharge_frac
    )

    q_total = q_direct + q_base
    q_total = np.maximum(q_total, 0.0)
    return q_total


# ---------------------------------------------------------------------------
# Compute KGE
# ---------------------------------------------------------------------------
def compute_kge(obs, sim):
    """Compute Kling-Gupta Efficiency."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]
    if len(obs) < 10:
        return -999.0

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 0
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else 0
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return float(kge)


# ---------------------------------------------------------------------------
# Sample parameters
# ---------------------------------------------------------------------------
def sample_parameters(n_samples, seed=42):
    """Generate random parameter samples using Latin Hypercube-like sampling."""
    rng = np.random.RandomState(seed)
    samples = []
    for _ in range(n_samples):
        params = {}
        for name, (lo, hi) in PARAM_RANGES.items():
            params[name] = rng.uniform(lo, hi)
        samples.append(params)
    return samples


# ---------------------------------------------------------------------------
# Process (calibration)
# ---------------------------------------------------------------------------
def process(args):
    """Run GLUE-style calibration."""
    print("=" * 60)
    print("HEC-HMS Calibration (GLUE-style random sampling)")
    print("=" * 60)

    # Suppress run_hec_hms print output during calibration
    import io
    from contextlib import redirect_stdout

    # 1. Read forcing
    print("\n[forcing] Reading forcing data...")
    forcing_df = pd.read_csv(args.forcing_csv, index_col=0, parse_dates=True)
    precip_mm = forcing_df["precip_mm"].values.copy()
    precip_mm = np.maximum(precip_mm, 0.0)

    # 2. Read observations
    print("[obs] Reading observations...")
    obs_q = read_observations(args.obs_file, args.start_date, args.end_date)
    print(f"  Obs period: {obs_q.index[0]} to {obs_q.index[-1]}, {obs_q.count()} valid days")

    # Determine overlap
    forcing_dates = forcing_df.index
    obs_dates = obs_q.index
    start = max(forcing_dates[0], obs_dates[0])
    end = min(forcing_dates[-1], obs_dates[-1])
    if args.start_date:
        start = max(start, pd.Timestamp(args.start_date))
    if args.end_date:
        end = min(end, pd.Timestamp(args.end_date))

    # Index into forcing array
    forcing_start = forcing_df.index[0]
    idx_start = (start - forcing_start).days
    idx_end = (end - forcing_start).days + 1
    precip_window = precip_mm[max(0, idx_start):min(len(precip_mm), idx_end)]

    # Estimate base Tp
    tp_base = estimate_tp_from_area(args.basin_area_km2)

    # 3. Generate parameter samples
    print(f"\n[calibrate] Sampling {args.n_samples} parameter sets...")
    samples = sample_parameters(args.n_samples)

    # 4. Run all samples
    best_kge = -999
    best_params = None
    results = []

    # Silence individual run prints
    null_out = io.StringIO()

    for i, params in enumerate(samples):
        try:
            with redirect_stdout(null_out):
                q_sim = run_single(precip_window, args.basin_area_km2, params, tp_base)

            # Build simulated series aligned with dates
            sim_dates = pd.date_range(start, periods=len(q_sim), freq="D")
            sim_series = pd.Series(q_sim, index=sim_dates)

            # Align with observations
            merged = pd.DataFrame({"obs": obs_q, "sim": sim_series}).dropna()
            if len(merged) < 10:
                continue

            kge = compute_kge(merged["obs"].values, merged["sim"].values)
            results.append({"params": params, "kge": kge})

            if kge > best_kge:
                best_kge = kge
                best_params = params.copy()

        except Exception:
            continue

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{args.n_samples}] Best KGE so far: {best_kge:.4f}")

    print(f"\n[result] Best KGE: {best_kge:.4f}")
    print(f"  Best parameters:")
    for k, v in best_params.items():
        print(f"    {k}: {v:.4f}")

    # 5. Also compute behavioral parameter ranges (KGE > threshold)
    threshold = max(best_kge - 0.2, 0.0)
    behavioral = [r for r in results if r["kge"] > threshold]
    print(f"\n[behavioral] {len(behavioral)}/{len(results)} samples with KGE > {threshold:.2f}")

    # 6. Write output
    output = {
        "status": "success",
        "best_kge": round(best_kge, 4),
        "best_params": {k: round(v, 4) for k, v in best_params.items()},
        "n_samples": args.n_samples,
        "n_behavioral": len(behavioral),
        "threshold": round(threshold, 4),
        "param_ranges_tested": PARAM_RANGES,
    }

    os.makedirs(os.path.dirname(args.output_params) or ".", exist_ok=True)
    with open(args.output_params, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[write] Calibrated params: {args.output_params}")

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="HEC-HMS GLUE calibration")
    parser.add_argument("--forcing_csv", required=True, help="Forcing CSV")
    parser.add_argument("--obs_file", required=True, help="Observed discharge file")
    parser.add_argument("--basin_area_km2", type=float, required=True, help="Basin area (km²)")
    parser.add_argument("--start_date", default=None, help="Calibration start date")
    parser.add_argument("--end_date", default=None, help="Calibration end date")
    parser.add_argument("--n_samples", type=int, default=500, help="Number of parameter samples")
    parser.add_argument("--output_params", required=True, help="Output calibrated params JSON")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
