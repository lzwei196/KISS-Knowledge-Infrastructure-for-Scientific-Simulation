#!/usr/bin/env python3
"""
parse_output_velma.py -- Parse VELMA simulation output and compute validation
metrics against observed discharge.

Reads the JSON output from run_velma.py, exports discharge time series to CSV,
computes evaluation metrics (NSE, KGE, r, RMSE, PBIAS) against observed data,
and optionally generates a validation figure.

Output units:
  - Discharge: m3/s (cubic meters per second)
  - Metrics: unitless (except RMSE which has units of Q)

CRITICAL:
  - Simulated Q from VELMA is in m3/s. If observed Q is in mm/d, convert
    using: Q_m3s = Q_mm_d * area_km2 * 1e6 / 86400 / 1000 (dt_013).
  - If NSE << 0 (e.g., -5), the most likely cause is a unit mismatch between
    simulated and observed discharge.
  - Warmup period (typically 1 year) should be excluded from metric computation.

Usage:
    python parse_output_velma.py \\
        --input simulation.json \\
        --observed /path/to/observed_Q.csv \\
        --warmup-days 365 \\
        --output results.csv \\
        --metrics-json metrics.json \\
        --figure validation.png

    python parse_output_velma.py \\
        --input calibrated.json \\
        --output results.csv \\
        --metrics-json metrics.json
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def validate_inputs(args):
    """Validate input files and arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed file not found: {args.observed}")

    if args.warmup_days < 0:
        errors.append(f"warmup_days must be >= 0, got: {args.warmup_days}")

    if pd is None:
        errors.append("pandas required. Run: pip install pandas")

    return errors


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency. Range: (-inf, 1], 1 = perfect."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    if ss_tot == 0:
        return float("nan")
    return 1 - ss_res / ss_tot


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency (Gupta et al. 2009). Range: (-inf, 1]."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else float("nan")
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float("nan")
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)


def compute_rmse(obs, sim):
    """Root Mean Square Error in units of Q (m3/s)."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return np.sqrt(np.mean((obs - sim) ** 2))


def compute_pbias(obs, sim):
    """Percent Bias. 0 = perfect, positive = overestimation."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if np.sum(obs) == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")
    return float(np.corrcoef(obs, sim)[0, 1])


def load_simulation(input_path):
    """Load simulation results from JSON (output of run_velma.py).

    Returns DataFrame with DatetimeIndex and Q_sim_m3s column.
    Also returns the full JSON data for metadata access.
    """
    with open(input_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Input file has error status: {data.get('errors')}")

    output = data.get("output", data)
    dates = pd.DatetimeIndex(output["dates"])
    q_sim = np.array(output["Q_sim_m3s"], dtype=float)

    df = pd.DataFrame({"Q_sim_m3s": q_sim}, index=dates)

    # Include observed if present (from calibration output)
    if "Q_obs_m3s" in output:
        q_obs_raw = output["Q_obs_m3s"]
        q_obs = np.array([v if v is not None else np.nan for v in q_obs_raw],
                         dtype=float)
        df["Q_obs_m3s"] = q_obs

    return df, data


def load_observed(obs_path, date_col="dates", q_col="Q"):
    """Load observed discharge from CSV/TSV file.

    Handles Bengbu format and standard CSV.
    Returns Series indexed by date with values in m3/s.
    """
    try:
        obs = pd.read_csv(obs_path, sep="\t", encoding="latin1")
    except Exception:
        obs = pd.read_csv(obs_path)

    # Find date column
    for col in [date_col, "date", "Date", "time", "Time"]:
        if col in obs.columns:
            obs[date_col] = pd.to_datetime(obs[col])
            break

    obs = obs.set_index(date_col).sort_index()

    # Find Q column
    for col in [q_col, "Q", "discharge", "q", "streamflow", "Q_m3s", "Q_sim_m3s"]:
        if col in obs.columns:
            q_series = obs[col].astype(float).copy()
            break
    else:
        raise KeyError(f"No discharge column found in {obs_path}. "
                       f"Available columns: {list(obs.columns)}")

    # Flag sentinel values
    q_series.loc[q_series < 0] = np.nan

    return q_series


def validate_output(sim_values, obs_values, log):
    """Check output values for physical plausibility."""
    sim = np.asarray(sim_values, float)

    if np.any(sim < 0):
        log.append("[WARN] Negative simulated discharge -- possible model instability")

    if np.any(~np.isfinite(sim)):
        log.append("[CRITICAL] Non-finite values in simulated discharge")

    if np.max(sim) > 100000:
        log.append(f"[WARN] Max simulated Q = {np.max(sim):.1f} m3/s "
                   "-- verify precipitation units and basin area")

    if obs_values is not None:
        obs = np.asarray(obs_values, float)
        mask = ~np.isnan(obs) & ~np.isnan(sim)
        if mask.sum() > 0:
            ratio = np.mean(sim[mask]) / max(np.mean(obs[mask]), 1e-6)
            if ratio > 10:
                log.append(
                    f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}x -- "
                    "likely unit mismatch in forcing or area (dt_014)")
            elif ratio < 0.1:
                log.append(
                    f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}x -- "
                    "check precipitation conversion or basin area")

    return True


def generate_figure(sim_df, obs_series, metrics, output_path, metadata, log):
    """Generate a multi-panel validation figure.

    Panel 1: Hydrograph (observed vs simulated)
    Panel 2: Scatter plot
    Panel 3: Residual time series
    """
    if not HAS_MPL:
        log.append("matplotlib not available, skipping figure")
        return

    dates = sim_df.index
    q_sim = sim_df["Q_sim_m3s"].values
    q_obs = obs_series.reindex(dates).values if obs_series is not None else None

    has_obs = q_obs is not None and not np.all(np.isnan(q_obs))
    n_panels = 3 if has_obs else 1

    fig, axes = plt.subplots(n_panels, 1,
                              figsize=(14, 4 * n_panels),
                              squeeze=False)

    # Panel 1: Hydrograph
    ax = axes[0, 0]
    ax.plot(dates, q_sim, "b-", lw=0.8, alpha=0.8, label="Simulated (VELMA)")
    if has_obs:
        ax.plot(dates, q_obs, "k-", lw=0.8, alpha=0.7, label="Observed")
        ax.fill_between(dates, 0, q_obs, alpha=0.1, color="blue")

    ax.set_ylabel("Discharge (m3/s)")
    ax.set_xlim(dates[0], dates[-1])
    ax.legend(loc="upper right", fontsize=9)

    # Add metrics text
    if metrics:
        text = "\n".join([f"{k}={v:.3f}" if isinstance(v, float)
                          else f"{k}={v}" for k, v in metrics.items()
                          if k != "n_points"])
        ax.text(0.02, 0.95, text, transform=ax.transAxes, fontsize=9,
                va="top", ha="left",
                bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

    basin_area = metadata.get("output", {}).get("basin_area_km2", "")
    ax.set_title(f"VELMA (4-Layer Analytic) -- Daily Discharge Validation"
                 f"{f' ({basin_area} km2)' if basin_area else ''}",
                 fontsize=11, fontweight="bold")

    # Panel 2: Scatter if observed available
    if has_obs and n_panels >= 2:
        ax2 = axes[1, 0]
        mask = ~np.isnan(q_obs) & ~np.isnan(q_sim)
        if mask.sum() > 0:
            ax2.scatter(q_obs[mask], q_sim[mask], s=5, alpha=0.3,
                        c="steelblue", edgecolors="none")
            max_q = max(np.nanmax(q_obs[mask]), np.nanmax(q_sim[mask])) * 1.1
            ax2.plot([0, max_q], [0, max_q], "k--", lw=1, alpha=0.5,
                     label="1:1 line")
            ax2.set_xlabel("Observed Q (m3/s)")
            ax2.set_ylabel("Simulated Q (m3/s)")
            ax2.set_xlim(0, max_q)
            ax2.set_ylim(0, max_q)
            ax2.set_aspect("equal")
            ax2.legend(fontsize=9)
            nse_val = metrics.get("NSE", "N/A")
            kge_val = metrics.get("KGE", "N/A")
            ax2.set_title(f"Scatter: NSE={nse_val}, KGE={kge_val}", fontsize=10)

    # Panel 3: Residuals
    if has_obs and n_panels >= 3:
        ax3 = axes[2, 0]
        mask = ~np.isnan(q_obs) & ~np.isnan(q_sim)
        residuals = np.where(mask, q_sim - q_obs, np.nan)
        ax3.bar(dates, residuals, width=1, color="steelblue", alpha=0.5)
        ax3.axhline(0, color="k", lw=0.5)
        ax3.set_ylabel("Residual (m3/s)")
        ax3.set_xlabel("Date")
        ax3.set_xlim(dates[0], dates[-1])
        ax3.set_title("Sim - Obs Residuals", fontsize=10)

    plt.tight_layout()

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.append(f"Figure saved: {output_path}")


def process(args, log):
    """Main processing pipeline: load -> compute -> validate -> write."""

    # Load simulation
    sim_df, metadata = load_simulation(args.input)
    n_total = len(sim_df)
    log.append(f"Loaded simulation: {n_total} days "
               f"({sim_df.index[0].date()} to {sim_df.index[-1].date()})")

    # Load observed (from file or from embedded calibration data)
    obs_series = None
    if args.observed:
        obs_series = load_observed(args.observed)
        log.append(f"Loaded observed: {len(obs_series)} records")
    elif "Q_obs_m3s" in sim_df.columns:
        obs_series = sim_df["Q_obs_m3s"]
        log.append("Using observed data embedded in simulation output")

    # Apply warmup
    warmup = args.warmup_days
    if warmup > 0 and warmup < n_total:
        sim_eval = sim_df.iloc[warmup:]
        log.append(f"Excluded {warmup} warmup days, evaluating {len(sim_eval)} days")
    else:
        sim_eval = sim_df

    # Compute metrics
    metrics = {}
    if obs_series is not None:
        q_obs_aligned = obs_series.reindex(sim_eval.index).values
        q_sim = sim_eval["Q_sim_m3s"].values

        mask = ~np.isnan(q_obs_aligned) & ~np.isnan(q_sim)
        n_valid = mask.sum()

        if n_valid >= 10:
            metrics = {
                "NSE": round(compute_nse(q_obs_aligned, q_sim), 4),
                "KGE": round(compute_kge(q_obs_aligned, q_sim), 4),
                "r": round(compute_r(q_obs_aligned, q_sim), 4),
                "RMSE": round(compute_rmse(q_obs_aligned, q_sim), 1),
                "PBIAS": round(compute_pbias(q_obs_aligned, q_sim), 2),
                "n_points": int(n_valid),
                "mean_obs": round(float(np.nanmean(q_obs_aligned[mask])), 1),
                "mean_sim": round(float(np.nanmean(q_sim[mask])), 1),
            }
            log.append(f"Metrics (n={n_valid}): NSE={metrics['NSE']}, "
                       f"KGE={metrics['KGE']}, r={metrics['r']}, "
                       f"RMSE={metrics['RMSE']}, PBIAS={metrics['PBIAS']}%")
        else:
            log.append(f"[WARN] Only {n_valid} valid overlapping points "
                       "-- insufficient for metrics")

        # Validate outputs
        validate_output(q_sim, q_obs_aligned, log)
    else:
        q_sim = sim_eval["Q_sim_m3s"].values
        validate_output(q_sim, None, log)
        log.append("No observed data -- skipping metric computation")

    # Export CSV
    if args.output:
        csv_df = sim_df[["Q_sim_m3s"]].copy()
        if obs_series is not None:
            csv_df["Q_obs_m3s"] = obs_series.reindex(sim_df.index)
        csv_df.index.name = "date"

        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        csv_df.to_csv(args.output)
        log.append(f"CSV saved: {args.output}")

    # Export metrics JSON
    if args.metrics_json:
        metrics_out = {
            "model": "VELMA",
            "input": args.input,
            "warmup_days": warmup,
            "metrics": metrics,
            "diagnostics": metadata.get("output", {}).get("diagnostics", {}),
        }
        out_dir = os.path.dirname(args.metrics_json)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.metrics_json, "w") as f:
            json.dump(metrics_out, f, indent=2)
        log.append(f"Metrics JSON saved: {args.metrics_json}")

    # Generate figure
    if args.figure:
        generate_figure(sim_df, obs_series, metrics, args.figure, metadata, log)

    return {
        "status": "success",
        "output": {
            "n_days": n_total,
            "warmup_days": warmup,
            "metrics": metrics,
            "csv_path": args.output,
            "metrics_json_path": args.metrics_json,
            "figure_path": args.figure,
        },
        "log": log,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse VELMA output and compute validation metrics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITICAL:
  - If NSE << 0 (e.g., -5), check for unit mismatch between sim and obs.
  - Simulated Q is in m3/s. If observed Q is in mm/d, convert first (dt_013).
  - Exclude warmup period (typically 1 year = 365 days) from metrics.
""")

    parser.add_argument("--input", required=True,
                        help="Simulation JSON from run_velma.py")
    parser.add_argument("--observed", default=None,
                        help="Observed discharge CSV/TSV file")
    parser.add_argument("--warmup-days", type=int, default=365,
                        help="Days to exclude as warmup (default: 365)")
    parser.add_argument("--output", default=None,
                        help="Output CSV file path for time series")
    parser.add_argument("--metrics-json", default=None,
                        help="Output JSON file for metrics")
    parser.add_argument("--figure", default=None,
                        help="Output figure path (PNG/PDF)")

    args = parser.parse_args()

    # Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors, "log": []}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    # Process
    log = []
    result = process(args, log)

    # Print summary
    status = result["status"]
    print(f"\n[parse_output_velma] Status: {status}")
    out = result["output"]
    print(f"  Total days: {out['n_days']}, warmup: {out['warmup_days']}")
    if out.get("metrics"):
        m = out["metrics"]
        print(f"  NSE:   {m.get('NSE', 'N/A')}")
        print(f"  KGE:   {m.get('KGE', 'N/A')}")
        print(f"  r:     {m.get('r', 'N/A')}")
        print(f"  RMSE:  {m.get('RMSE', 'N/A')} m3/s")
        print(f"  PBIAS: {m.get('PBIAS', 'N/A')}%")
    if out.get("csv_path"):
        print(f"  CSV: {out['csv_path']}")
    if out.get("metrics_json_path"):
        print(f"  Metrics: {out['metrics_json_path']}")
    if out.get("figure_path"):
        print(f"  Figure: {out['figure_path']}")
    for entry in log:
        if "[CRITICAL]" in entry or "[WARN]" in entry:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
