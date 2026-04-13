#!/usr/bin/env python3
"""
parse_ef5_output.py — Parse EF5/CREST model output and compute metrics.

Extracts time series from EF5 output files, computes hydrological performance
metrics (NSE, KGE, PBIAS, RMSE, R²), and generates validation plots.

Pipeline stage: s7 (Output Analysis)
Pattern: validate → process → validate

Input:
  - EF5 output directory with gauge time series files
  - Observed discharge file (optional, for metrics)
  - Plot configuration

Output:
  - Parsed time series as CSV
  - Computed metrics dictionary
  - Validation figure (observed vs simulated hydrograph)

Supported metrics:
  - NSE (Nash-Sutcliffe Efficiency)
  - KGE (Kling-Gupta Efficiency)
  - PBIAS (Percent Bias)
  - RMSE (Root Mean Square Error)
  - R² (Coefficient of Determination)
  - R (Pearson correlation coefficient)
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ── Constants ──────────────────────────────────────────────────────────────

EF5_NODATA = -9999.0
METRIC_NAMES = ["NSE", "KGE", "PBIAS", "RMSE", "R2", "R"]


# ── Validation ─────────────────────────────────────────────────────────────

def validate_inputs(output_dir, obs_file=None):
    """Validate input files and directories."""
    errors = []

    if not os.path.isdir(output_dir):
        errors.append(f"Output directory not found: {output_dir}")
    else:
        files = os.listdir(output_dir)
        if not files:
            errors.append(f"Output directory is empty: {output_dir}")

    if obs_file and not os.path.isfile(obs_file):
        errors.append(f"Observation file not found: {obs_file}")

    return errors


def validate_outputs(csv_path=None, figure_path=None, metrics=None):
    """Validate generated outputs."""
    errors = []

    if csv_path and not os.path.isfile(csv_path):
        errors.append(f"CSV output not created: {csv_path}")

    if figure_path and not os.path.isfile(figure_path):
        errors.append(f"Figure not created: {figure_path}")

    if metrics:
        nse = metrics.get("NSE", -999)
        if nse < -10:
            errors.append(f"NSE is extremely low ({nse:.3f}). Check model configuration.")

    return errors


# ── Metrics ────────────────────────────────────────────────────────────────

def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - np.mean(obs)) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    r = np.corrcoef(obs, sim)[0, 1] if len(obs) > 1 else 0.0
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 0.0
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else 0.0
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return kge


def compute_pbias(obs, sim):
    """Percent Bias (%)."""
    if np.sum(obs) == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    return np.sqrt(np.mean((obs - sim) ** 2))


def compute_r2(obs, sim):
    """Coefficient of determination."""
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    if len(obs) < 2:
        return float("nan")
    return float(np.corrcoef(obs, sim)[0, 1])


def compute_all_metrics(obs, sim):
    """Compute all hydrological metrics."""
    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        return {m: float("nan") for m in METRIC_NAMES}

    return {
        "NSE": round(compute_nse(obs, sim), 4),
        "KGE": round(compute_kge(obs, sim), 4),
        "PBIAS": round(compute_pbias(obs, sim), 2),
        "RMSE": round(compute_rmse(obs, sim), 4),
        "R2": round(compute_r2(obs, sim), 4),
        "R": round(compute_r(obs, sim), 4),
    }


# ── Parsing ────────────────────────────────────────────────────────────────

def parse_ef5_timeseries(output_dir, gauge_name=None):
    """Parse EF5 output time series files.

    EF5 writes gauge time series as text files with format:
    YYYY/MM/DD HH:UU:SS, simulated_Q, observed_Q (if OBS provided)
    or simulated_Q only.
    """
    results = {}

    for fname in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            continue
        # Skip grid files
        if fname.endswith((".tif", ".asc", ".bif")):
            continue

        if gauge_name and gauge_name.lower() not in fname.lower():
            continue

        dates = []
        sim_q = []
        obs_q = []

        with open(fpath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = re.split(r"[,\t\s]+", line)

                # Try to parse datetime from first parts
                try:
                    # Format: YYYY/MM/DD HH:UU:SS or YYYY-MM-DD HH:UU:SS
                    if len(parts) >= 3:
                        dt_str = f"{parts[0]} {parts[1]}"
                        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                                    "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
                            try:
                                dt = datetime.strptime(dt_str, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            continue

                        # Simulated Q
                        sim = float(parts[2])
                        dates.append(dt)
                        sim_q.append(sim)

                        # Observed Q (optional)
                        if len(parts) >= 4:
                            try:
                                obs = float(parts[3])
                                obs_q.append(obs)
                            except ValueError:
                                obs_q.append(np.nan)
                        else:
                            obs_q.append(np.nan)
                except (ValueError, IndexError):
                    continue

        if dates:
            results[fname] = {
                "dates": dates,
                "sim_q": np.array(sim_q),
                "obs_q": np.array(obs_q),
            }

    return results


def load_observation_file(obs_path, date_col="dates", q_col="Q",
                          date_format=None):
    """Load observation discharge file.

    Supports various CSV/TSV formats common in Chinese hydrology.
    """
    dates = []
    discharge = []

    with open(obs_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)

        # Find column indices
        header_lower = [h.strip().lower() for h in header]
        date_idx = None
        q_idx = None

        for i, h in enumerate(header_lower):
            if h in ("dates", "date", "datetime", "time"):
                date_idx = i
            elif h in ("q", "discharge", "flow", "streamflow"):
                q_idx = i

        if date_idx is None or q_idx is None:
            # Try positional: assume col 1 = date, col 3 = Q
            date_idx = 1
            q_idx = 3

        for row in reader:
            try:
                dt_str = row[date_idx].strip()
                q_val = float(row[q_idx])

                # Try multiple date formats
                dt = None
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
                            "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        break
                    except ValueError:
                        continue

                if dt and q_val >= 0:
                    dates.append(dt)
                    discharge.append(q_val)
            except (ValueError, IndexError):
                continue

    return dates, np.array(discharge)


def align_timeseries(sim_dates, sim_q, obs_dates, obs_q):
    """Align simulated and observed time series by date."""
    obs_dict = dict(zip(obs_dates, obs_q))

    aligned_dates = []
    aligned_sim = []
    aligned_obs = []

    for dt, sq in zip(sim_dates, sim_q):
        # Match by date (ignoring time for daily data)
        dt_date = dt.replace(hour=0, minute=0, second=0)
        if dt_date in obs_dict:
            aligned_dates.append(dt)
            aligned_sim.append(sq)
            aligned_obs.append(obs_dict[dt_date])
        elif dt in obs_dict:
            aligned_dates.append(dt)
            aligned_sim.append(sq)
            aligned_obs.append(obs_dict[dt])

    return aligned_dates, np.array(aligned_sim), np.array(aligned_obs)


# ── Plotting ───────────────────────────────────────────────────────────────

def plot_validation(dates, obs, sim, metrics, output_path,
                    title="CREST Model Validation",
                    basin_name=""):
    """Generate validation hydrograph plot."""
    if not HAS_MPL:
        print("WARNING: matplotlib not available, skipping plot.")
        return

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(dates, obs, color="black", linewidth=1.0, label="Observed", alpha=0.8)
    ax.plot(dates, sim, color="#2563EB", linewidth=1.0, label="Simulated", alpha=0.8)

    ax.set_xlabel("Date")
    ax.set_ylabel("Discharge (m³/s)")
    ax.set_title(f"{title} — {basin_name}" if basin_name else title)
    ax.legend(loc="upper left")

    # Metrics box in top-right
    metric_text = "\n".join([
        f"NSE = {metrics.get('NSE', 'N/A'):.3f}" if isinstance(metrics.get('NSE'), float) else "NSE = N/A",
        f"KGE = {metrics.get('KGE', 'N/A'):.3f}" if isinstance(metrics.get('KGE'), float) else "KGE = N/A",
        f"PBIAS = {metrics.get('PBIAS', 'N/A'):.1f}%" if isinstance(metrics.get('PBIAS'), float) else "PBIAS = N/A",
        f"R = {metrics.get('R', 'N/A'):.3f}" if isinstance(metrics.get('R'), float) else "R = N/A",
    ])
    props = dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9,
                 edgecolor="gray")
    ax.text(0.98, 0.95, metric_text, transform=ax.transAxes,
            fontsize=10, verticalalignment="top", horizontalalignment="right",
            bbox=props, family="monospace")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Figure saved: {output_path}")


def write_csv(dates, obs, sim, output_path):
    """Write aligned time series to CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "observed_cms", "simulated_cms"])
        for dt, o, s in zip(dates, obs, sim):
            writer.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"),
                             f"{o:.3f}", f"{s:.3f}"])
    print(f"  CSV saved: {output_path}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Parse EF5/CREST output and compute metrics"
    )
    parser.add_argument("--output-dir", required=True,
                        help="EF5 output directory")
    parser.add_argument("--obs-file", help="Observed discharge file")
    parser.add_argument("--gauge", help="Gauge name to extract")
    parser.add_argument("--csv-out", help="Output CSV path")
    parser.add_argument("--figure", help="Output figure path")
    parser.add_argument("--metrics-json", help="Output metrics JSON path")
    parser.add_argument("--title", default="CREST Model Validation",
                        help="Plot title")
    parser.add_argument("--basin-name", default="",
                        help="Basin name for plot subtitle")

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.output_dir, args.obs_file)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)
    print("  Input validation passed.")

    # Step 2: Parse output
    print("=== Step 2: Parsing EF5 output ===")
    timeseries = parse_ef5_timeseries(args.output_dir, args.gauge)
    if not timeseries:
        print("  No time series found in output directory.")
        print("  Files present:", os.listdir(args.output_dir)[:20])
        sys.exit(1)

    for name, ts in timeseries.items():
        print(f"  Found gauge: {name} ({len(ts['dates'])} timesteps)")

    # Use first gauge if not specified
    gauge_key = list(timeseries.keys())[0]
    ts = timeseries[gauge_key]

    # Step 3: Compute metrics
    metrics = {}
    if args.obs_file:
        print("=== Step 3: Computing metrics ===")
        obs_dates, obs_q = load_observation_file(args.obs_file)
        print(f"  Loaded {len(obs_dates)} observations")

        aligned_dates, aligned_sim, aligned_obs = align_timeseries(
            ts["dates"], ts["sim_q"], obs_dates, obs_q
        )
        print(f"  Aligned {len(aligned_dates)} timesteps")

        if len(aligned_dates) > 1:
            metrics = compute_all_metrics(aligned_obs, aligned_sim)
            for k, v in metrics.items():
                print(f"  {k}: {v}")
        else:
            print("  WARNING: Insufficient aligned data for metrics.")
    else:
        # Use internal obs if available
        if not np.all(np.isnan(ts["obs_q"])):
            mask = ~np.isnan(ts["obs_q"])
            if np.sum(mask) > 1:
                metrics = compute_all_metrics(ts["obs_q"][mask], ts["sim_q"][mask])
                aligned_dates = [ts["dates"][i] for i in range(len(ts["dates"])) if mask[i]]
                aligned_sim = ts["sim_q"][mask]
                aligned_obs = ts["obs_q"][mask]
                for k, v in metrics.items():
                    print(f"  {k}: {v}")
            else:
                aligned_dates = ts["dates"]
                aligned_sim = ts["sim_q"]
                aligned_obs = ts["obs_q"]
        else:
            aligned_dates = ts["dates"]
            aligned_sim = ts["sim_q"]
            aligned_obs = np.full_like(ts["sim_q"], np.nan)

    # Step 4: Generate outputs
    print("=== Step 4: Generating outputs ===")

    if args.csv_out:
        write_csv(aligned_dates, aligned_obs, aligned_sim, args.csv_out)

    if args.figure and HAS_MPL and len(aligned_dates) > 0:
        if not np.all(np.isnan(aligned_obs)):
            plot_validation(aligned_dates, aligned_obs, aligned_sim, metrics,
                            args.figure, title=args.title,
                            basin_name=args.basin_name)
        else:
            # Plot simulated only
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(aligned_dates, aligned_sim, color="#2563EB",
                    linewidth=1.0, label="Simulated")
            ax.set_xlabel("Date")
            ax.set_ylabel("Discharge (m³/s)")
            ax.set_title(args.title)
            ax.legend()
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            os.makedirs(os.path.dirname(args.figure), exist_ok=True)
            fig.savefig(args.figure, dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(f"  Figure saved: {args.figure}")

    if args.metrics_json:
        os.makedirs(os.path.dirname(args.metrics_json), exist_ok=True)
        with open(args.metrics_json, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"  Metrics saved: {args.metrics_json}")

    # Step 5: Validate outputs
    print("=== Step 5: Validating outputs ===")
    errors = validate_outputs(args.csv_out, args.figure, metrics)
    if errors:
        for e in errors:
            print(f"  WARNING: {e}")
    else:
        print("  Output validation passed.")

    print("\nDone.")
    return metrics


if __name__ == "__main__":
    main()
