#!/usr/bin/env python3
"""
parse_output_kineros2.py -- Parse KINEROS2 simulation output and compute
validation metrics against observed discharge.

Reads the JSON output from run_kineros2.py, exports discharge time series
to CSV, computes evaluation metrics (NSE, KGE, r, RMSE, PBIAS) against
observed data, and optionally generates a validation figure.

Output units:
  - Discharge: m3/s (cubic meters per second)
  - Metrics: unitless (except RMSE which has units of Q)

CRITICAL:
  - Simulated Q from KINEROS2 is in m3/s. If observed Q is in mm/d, convert
    using: Q_m3s = Q_mm_d * area_km2 * 1e6 / 86400 / 1000 (dt_011).
  - If NSE << 0 (e.g., -5), the most likely cause is a unit mismatch between
    simulated and observed discharge.
  - Warmup period (typically 1 year) should be excluded from metric computation.

Usage:
    python parse_output_kineros2.py \\
        --input simulation.json \\
        --observed /path/to/observed_Q.csv \\
        --warmup-days 365 \\
        --output results.csv \\
        --metrics-json metrics.json \\
        --figure validation.png

    python parse_output_kineros2.py \\
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
    """Load simulation results from JSON (output of run_kineros2.py).

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
                    "likely unit mismatch in forcing or area (dt_012)")
            elif ratio < 0.1:
                log.append(
                    f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}x -- "
                    "check precipitation conversion or basin area")

    return True


def generate_figure(sim_df, obs_series, metrics, output_path, metadata, log):
    """Generate a multi-panel validation figure.

    Panel 1: Precipitation (inverted, if available in metadata)
    Panel 2: Hydrograph (observed vs simulated)
    Panel 3: Scatter plot (validation period)
    """
    if not HAS_MPL:
        log.append("matplotlib not available, skipping figure")
        return

    dates = sim_df.index
    q_sim = sim_df["Q_sim_m3s"].values
    q_obs = obs_series.reindex(dates).values if obs_series is not None else None

    # Determine panel count
    has_obs = q_obs is not None and not np.all(np.isnan(q_obs))
    n_panels = 3 if has_obs else 1
    height_ratios = [3, 1.5] if has_obs else [1]
    if has_obs:
        height_ratios = [3, 1.5]

    fig, axes = plt.subplots(n_panels if has_obs else 1, 1,
                              figsize=(14, 4 * (n_panels if has_obs else 2)),
                              squeeze=False)

    # Panel 1: Hydrograph
    ax = axes[0, 0]
    ax.plot(dates, q_sim, "b-", lw=0.8, alpha=0.8, label="Simulated (KINEROS2)")
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
    ax.set_title(f"KINEROS2 (Analytic) -- Daily Discharge Validation"
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
        mask = ~np.isnan(q_obs)
        residuals = np.where(mask, q_sim - q_obs, np.nan)
        ax3.bar(dates, residuals, width=1, color="steelblue", alpha=0.5)
        ax3.axhline(0, color="black", lw=0.5)
        ax3.set_ylabel("Residual (m3/s)")
        ax3.set_xlabel("Date")
        ax3.set_xlim(dates[0], dates[-1])
        ax3.set_title("Residuals (Sim - Obs)", fontsize=10)

    plt.tight_layout()
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.append(f"Validation figure saved to {output_path}")


def process(args):
    """Main processing: parse output, compute metrics, export CSV."""
    log = []

    # Load simulation results
    sim_df, metadata = load_simulation(args.input)
    log.append(f"Loaded simulation: {len(sim_df)} timesteps "
               f"({sim_df.index[0].date()} to {sim_df.index[-1].date()})")

    # Apply warmup
    if args.warmup_days > 0 and args.warmup_days < len(sim_df):
        sim_eval = sim_df.iloc[args.warmup_days:]
        log.append(f"Warmup: skipping first {args.warmup_days} days")
    else:
        sim_eval = sim_df

    # Load external observed data (if not embedded in simulation output)
    obs_series = None
    if args.observed:
        obs_series = load_observed(args.observed)
        log.append(f"Loaded external observed data: "
                   f"{obs_series.notna().sum()} valid values")
    elif "Q_obs_m3s" in sim_df.columns:
        obs_series = sim_df["Q_obs_m3s"]
        log.append("Using embedded observed data from simulation output")

    # Export to CSV
    if args.output:
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        export_df = sim_df.copy()
        if obs_series is not None and "Q_obs_m3s" not in export_df.columns:
            export_df["Q_obs_m3s"] = obs_series.reindex(export_df.index)
        export_df.to_csv(args.output)
        log.append(f"Time series exported to {args.output}")

    # Compute metrics
    metrics = {}
    if obs_series is not None:
        common = sim_eval.index.intersection(obs_series.dropna().index)
        if len(common) > 10:
            q_s = sim_eval.loc[common, "Q_sim_m3s"].values
            q_o = obs_series.reindex(common).values

            # Validate
            validate_output(q_s, q_o, log)

            metrics = {
                "NSE": round(float(compute_nse(q_o, q_s)), 4),
                "KGE": round(float(compute_kge(q_o, q_s)), 4),
                "r": round(float(compute_r(q_o, q_s)), 4),
                "PBIAS": round(float(compute_pbias(q_o, q_s)), 2),
                "RMSE": round(float(compute_rmse(q_o, q_s)), 1),
                "n_points": len(common),
            }

            log.append(f"\nValidation metrics ({len(common)} overlapping days):")
            for k, v in metrics.items():
                log.append(f"  {k} = {v}")

            # Diagnostic warnings
            if metrics["NSE"] < -1:
                log.append(
                    f"[CRITICAL] NSE = {metrics['NSE']:.2f} << 0 -- "
                    "likely unit mismatch between observed and simulated (dt_011)")

            if abs(metrics["PBIAS"]) > 50:
                log.append(
                    f"[WARN] |PBIAS| = {abs(metrics['PBIAS']):.1f}% > 50% -- "
                    "large systematic bias, check forcing conversion")
        else:
            log.append(f"[WARN] Only {len(common)} overlapping days -- "
                       "insufficient for metric computation")

    # Write metrics JSON
    if args.metrics_json and metrics:
        mdir = os.path.dirname(args.metrics_json)
        if mdir:
            os.makedirs(mdir, exist_ok=True)
        with open(args.metrics_json, "w") as f:
            json.dump(metrics, f, indent=2)
        log.append(f"Metrics written to {args.metrics_json}")

    # Generate figure
    if args.figure:
        generate_figure(sim_eval, obs_series, metrics, args.figure, metadata, log)

    # Also include metrics from calibration output if present
    cal_metrics = metadata.get("output", {}).get("calibration_metrics", {})
    val_metrics = metadata.get("output", {}).get("validation_metrics", {})

    result = {
        "status": "success",
        "output": {
            "n_timesteps": len(sim_df),
            "warmup_days": args.warmup_days,
            "Q_mean_m3s": round(float(sim_eval["Q_sim_m3s"].mean()), 2),
            "Q_max_m3s": round(float(sim_eval["Q_sim_m3s"].max()), 2),
            "metrics": metrics,
        },
        "log": log,
    }

    if cal_metrics:
        result["output"]["calibration_metrics"] = cal_metrics
    if val_metrics:
        result["output"]["validation_metrics"] = val_metrics

    return result


def validate_result(result):
    """Final validation of parsed output."""
    if result["status"] != "success":
        return result

    warnings_list = []
    mean_q = result["output"].get("Q_mean_m3s", 0)

    if mean_q < 0:
        warnings_list.append("Negative mean discharge -- check model output")
    if mean_q > 50000:
        warnings_list.append("Mean Q > 50000 m3/s -- unusually high for most basins")

    result["output"]["warnings"] = warnings_list
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse KINEROS2 output and compute validation metrics")
    parser.add_argument("--input", required=True,
                        help="Simulation JSON from run_kineros2.py")
    parser.add_argument("--observed", default=None,
                        help="Observed discharge CSV/TSV (optional if embedded)")
    parser.add_argument("--warmup-days", type=int, default=365,
                        help="Days to skip for model warmup (default: 365)")
    parser.add_argument("--output", default=None,
                        help="Output CSV file for time series")
    parser.add_argument("--metrics-json", default=None,
                        help="Output JSON file for metrics")
    parser.add_argument("--figure", default=None,
                        help="Output validation figure (PNG)")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: process
    result = process(args)

    # Step 3: validate result
    result = validate_result(result)

    # Step 4: print summary
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in result.get("log", []):
            print(line)

        # Also print final JSON summary
        print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
