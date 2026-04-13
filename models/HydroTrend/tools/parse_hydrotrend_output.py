#!/usr/bin/env python3
"""
parse_hydrotrend_output.py

Parses HydroTrend ASCII output files into structured CSV and JSON summaries.

Input files parsed:
  - {PREFIX}ASCII.Q   — daily water discharge (m³/s)
  - {PREFIX}ASCII.QS  — daily suspended sediment (kg/s)
  - {PREFIX}ASCII.QB  — daily bedload (kg/s)
  - {PREFIX}ASCII.CS  — daily sediment concentration (kg/m³)
  - {PREFIX}ASCII.VWD — daily velocity(m/s), width(m), depth(m)

Output:
  - Combined CSV with date, Q, Qs, Qb, Cs, velocity, width, depth
  - JSON summary with annual statistics
  - Optional: compute NSE, KGE, PBIAS against observed data

Usage:
    python parse_hydrotrend_output.py \\
        --out-dir ./HYDRO_OUTPUT \\
        --prefix HYDRO \\
        --start-year 1908 \\
        --output-csv results.csv \\
        --output-json summary.json

    python parse_hydrotrend_output.py \\
        --out-dir ./HYDRO_OUTPUT \\
        --prefix HYDRO \\
        --start-year 1908 \\
        --observed observed_Q.csv \\
        --obs-date-col date \\
        --obs-value-col discharge_m3s \\
        --output-csv results.csv \\
        --output-json summary.json
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if not os.path.isdir(args.out_dir):
        errors.append(f"Output directory not found: {args.out_dir}")

    q_file = os.path.join(args.out_dir, f"{args.prefix}ASCII.Q")
    if not os.path.isfile(q_file):
        errors.append(
            f"Discharge file not found: {q_file}. "
            "Check that ASCII output was ON in HYDRO.IN line 2."
        )

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def validate_parsed_data(data):
    """Check parsed data for physical plausibility."""
    warnings = []

    if not data:
        warnings.append("No data parsed — output files may be empty")
        return warnings

    q_vals = [d["Q_m3s"] for d in data if d["Q_m3s"] is not None]
    qs_vals = [d["Qs_kgs"] for d in data if d["Qs_kgs"] is not None]

    if q_vals:
        q_min, q_max = min(q_vals), max(q_vals)
        q_mean = sum(q_vals) / len(q_vals)
        if q_min < 0:
            warnings.append(f"Negative discharge found: min Q = {q_min:.3f}")
        if q_max > 1e6:
            warnings.append(
                f"Extremely high discharge: max Q = {q_max:.1f} m³/s "
                "(larger than Amazon)"
            )
        if q_mean == 0:
            warnings.append("Mean discharge is 0 — check input parameters")

    if qs_vals:
        qs_max = max(qs_vals)
        if qs_max > 1e5:
            warnings.append(
                f"Extremely high sediment load: max Qs = {qs_max:.1f} kg/s"
            )

    return warnings


# --------------------------------------------------------------------------- #
#  Parsing
# --------------------------------------------------------------------------- #
def read_single_column(filepath):
    """Read a single-column ASCII file, returning list of floats."""
    values = []
    if not os.path.isfile(filepath):
        return None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                values.append(float(line))
            except ValueError:
                continue
    return values


def read_vwd_file(filepath):
    """Read velocity-width-depth file (three columns per line)."""
    velocities, widths, depths = [], [], []
    if not os.path.isfile(filepath):
        return None, None, None

    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    velocities.append(float(parts[0]))
                    widths.append(float(parts[1]))
                    depths.append(float(parts[2]))
                except ValueError:
                    continue
    return velocities, widths, depths


def parse_all_outputs(out_dir, prefix, start_year):
    """Parse all HydroTrend ASCII output files into a combined dataset."""
    q_vals = read_single_column(
        os.path.join(out_dir, f"{prefix}ASCII.Q")
    )
    qs_vals = read_single_column(
        os.path.join(out_dir, f"{prefix}ASCII.QS")
    )
    qb_vals = read_single_column(
        os.path.join(out_dir, f"{prefix}ASCII.QB")
    )
    cs_vals = read_single_column(
        os.path.join(out_dir, f"{prefix}ASCII.CS")
    )
    vel, wid, dep = read_vwd_file(
        os.path.join(out_dir, f"{prefix}ASCII.VWD")
    )

    if q_vals is None:
        return []

    n_days = len(q_vals)
    start_date = datetime(start_year, 1, 1)

    data = []
    for i in range(n_days):
        date = start_date + timedelta(days=i)
        record = {
            "date": date.strftime("%Y-%m-%d"),
            "year": date.year,
            "month": date.month,
            "day_of_year": date.timetuple().tm_yday,
            "Q_m3s": q_vals[i] if i < len(q_vals) else None,
            "Qs_kgs": qs_vals[i] if qs_vals and i < len(qs_vals) else None,
            "Qb_kgs": qb_vals[i] if qb_vals and i < len(qb_vals) else None,
            "Cs_kgm3": cs_vals[i] if cs_vals and i < len(cs_vals) else None,
            "velocity_ms": vel[i] if vel and i < len(vel) else None,
            "width_m": wid[i] if wid and i < len(wid) else None,
            "depth_m": dep[i] if dep and i < len(dep) else None,
        }
        data.append(record)

    return data


def compute_annual_stats(data):
    """Compute annual statistics from daily data."""
    yearly = defaultdict(lambda: {"Q": [], "Qs": [], "Qb": [], "Cs": []})

    for d in data:
        yr = d["year"]
        if d["Q_m3s"] is not None:
            yearly[yr]["Q"].append(d["Q_m3s"])
        if d["Qs_kgs"] is not None:
            yearly[yr]["Qs"].append(d["Qs_kgs"])
        if d["Qb_kgs"] is not None:
            yearly[yr]["Qb"].append(d["Qb_kgs"])
        if d["Cs_kgm3"] is not None:
            yearly[yr]["Cs"].append(d["Cs_kgm3"])

    annual = []
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        stats = {"year": yr}
        if y["Q"]:
            stats["Q_mean_m3s"] = round(sum(y["Q"]) / len(y["Q"]), 3)
            stats["Q_max_m3s"] = round(max(y["Q"]), 3)
            stats["Q_min_m3s"] = round(min(y["Q"]), 3)
            # Annual volume in km³
            stats["Q_annual_km3"] = round(
                sum(y["Q"]) * 86400 / 1e9, 4
            )
        if y["Qs"]:
            stats["Qs_mean_kgs"] = round(sum(y["Qs"]) / len(y["Qs"]), 3)
            # Annual sediment in Mt
            stats["Qs_annual_Mt"] = round(
                sum(y["Qs"]) * 86400 / 1e9, 6
            )
        if y["Qb"]:
            stats["Qb_mean_kgs"] = round(sum(y["Qb"]) / len(y["Qb"]), 3)
        if y["Cs"]:
            stats["Cs_mean_kgm3"] = round(sum(y["Cs"]) / len(y["Cs"]), 4)

        annual.append(stats)

    return annual


# --------------------------------------------------------------------------- #
#  Metrics
# --------------------------------------------------------------------------- #
def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    if len(obs) != len(sim) or len(obs) == 0:
        return None
    obs_mean = sum(obs) / len(obs)
    numerator = sum((o - s) ** 2 for o, s in zip(obs, sim))
    denominator = sum((o - obs_mean) ** 2 for o in obs)
    if denominator == 0:
        return None
    return round(1 - numerator / denominator, 4)


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    if len(obs) != len(sim) or len(obs) < 2:
        return None
    n = len(obs)
    obs_mean = sum(obs) / n
    sim_mean = sum(sim) / n
    obs_std = math.sqrt(sum((o - obs_mean) ** 2 for o in obs) / (n - 1))
    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in sim) / (n - 1))

    if obs_std == 0 or obs_mean == 0:
        return None

    # Correlation
    cov = sum((o - obs_mean) * (s - sim_mean) for o, s in zip(obs, sim))
    r = cov / ((n - 1) * obs_std * sim_std) if obs_std * sim_std > 0 else 0

    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean

    kge = 1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return round(kge, 4)


def compute_pbias(obs, sim):
    """Percent Bias."""
    if len(obs) != len(sim) or len(obs) == 0:
        return None
    obs_sum = sum(obs)
    if obs_sum == 0:
        return None
    pbias = 100 * sum(s - o for o, s in zip(obs, sim)) / obs_sum
    return round(pbias, 2)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Parse HydroTrend output files"
    )
    parser.add_argument("--out-dir", required=True,
                        help="HydroTrend output directory")
    parser.add_argument("--prefix", default="HYDRO",
                        help="File prefix")
    parser.add_argument("--start-year", type=int, required=True,
                        help="Simulation start year")
    parser.add_argument("--output-csv", default=None,
                        help="Output CSV file path")
    parser.add_argument("--output-json", default=None,
                        help="Output JSON summary path")
    parser.add_argument("--observed", default=None,
                        help="Observed data CSV for validation")
    parser.add_argument("--obs-date-col", default="date",
                        help="Date column in observed CSV")
    parser.add_argument("--obs-value-col", default="discharge_m3s",
                        help="Value column in observed CSV")
    args = parser.parse_args()

    # Step 1: Validate
    check = validate_inputs(args)
    if check["status"] == "error":
        print(json.dumps(check, indent=2))
        sys.exit(1)

    # Step 2: Parse
    data = parse_all_outputs(args.out_dir, args.prefix, args.start_year)

    # Step 3: Validate parsed data
    warnings = validate_parsed_data(data)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    # Step 4: Write CSV
    if args.output_csv and data:
        fieldnames = list(data[0].keys())
        with open(args.output_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    # Step 5: Compute statistics
    annual = compute_annual_stats(data)

    # Step 6: Compute metrics against observed if provided
    metrics = {}
    if args.observed and os.path.isfile(args.observed):
        obs_data = {}
        with open(args.observed, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                obs_data[row[args.obs_date_col]] = float(
                    row[args.obs_value_col]
                )

        sim_dict = {d["date"]: d["Q_m3s"] for d in data if d["Q_m3s"]}
        common_dates = sorted(set(obs_data.keys()) & set(sim_dict.keys()))
        if common_dates:
            obs = [obs_data[d] for d in common_dates]
            sim = [sim_dict[d] for d in common_dates]
            metrics = {
                "n_common_days": len(common_dates),
                "NSE": compute_nse(obs, sim),
                "KGE": compute_kge(obs, sim),
                "PBIAS": compute_pbias(obs, sim),
            }

    # Step 7: Write JSON summary
    q_vals = [d["Q_m3s"] for d in data if d["Q_m3s"] is not None]
    summary = {
        "status": "success",
        "n_days": len(data),
        "n_years": len(annual),
        "discharge_stats": {
            "mean_m3s": round(sum(q_vals) / len(q_vals), 3) if q_vals else 0,
            "max_m3s": round(max(q_vals), 3) if q_vals else 0,
            "min_m3s": round(min(q_vals), 3) if q_vals else 0,
        },
        "annual_summaries": annual[:5],  # First 5 years
        "metrics": metrics,
        "warnings": warnings,
        "output_csv": args.output_csv,
    }

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
