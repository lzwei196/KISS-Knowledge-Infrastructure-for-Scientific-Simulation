#!/usr/bin/env python3
"""
run_pywr.py — Load and run a Pywr model, extract results.

Loads a Pywr JSON model file, runs the simulation, and extracts:
- Storage volume timeseries
- Release flow timeseries
- Spill events
- Supply reliability statistics

Usage:
    python run_pywr.py --model model.json --output_dir results/

Output:
    - results/storage_timeseries.csv
    - results/release_timeseries.csv
    - results/summary.json
    Exit codes: 0 = success, 1 = model infeasible, 2 = input error, 3 = runtime error
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def load_and_run_model(model_path):
    """Load and run a Pywr model from JSON file."""
    from pywr.model import Model

    model = Model.load(str(model_path))
    model.run()
    return model


def extract_storage_timeseries(model, output_dir):
    """Extract storage volume timeseries from all storage nodes."""
    storage_data = {}

    for node in model.nodes:
        if hasattr(node, "volume"):
            # This is a storage node
            recorder_name = f"{node.name}_storage_stats"
            for rec_name, rec in model.recorders.items():
                if hasattr(rec, "data") and node.name in rec_name and "storage" in rec_name.lower():
                    data = rec.data
                    if data is not None and len(data) > 0:
                        storage_data[node.name] = data.flatten()
                    break

    if not storage_data:
        # Fallback: try all recorders that look like storage
        for rec_name, rec in model.recorders.items():
            if hasattr(rec, "data") and "storage" in rec_name.lower():
                data = rec.data
                if data is not None and len(data) > 0:
                    storage_data[rec_name] = data.flatten()

    # Build date index
    start = model.timestepper.start
    n_steps = max(len(v) for v in storage_data.values()) if storage_data else 0
    dates = pd.date_range(start=start, periods=n_steps, freq="D")

    df = pd.DataFrame(index=dates)
    df.index.name = "date"
    for name, values in storage_data.items():
        # Pad if needed
        if len(values) < n_steps:
            values = np.pad(values, (0, n_steps - len(values)), constant_values=np.nan)
        df[f"{name}_volume_m3"] = values[:n_steps]

    csv_path = output_dir / "storage_timeseries.csv"
    df.to_csv(csv_path, float_format="%.2f")
    return df, csv_path


def extract_flow_timeseries(model, output_dir):
    """Extract flow timeseries from link and output nodes."""
    flow_data = {}

    for rec_name, rec in model.recorders.items():
        if hasattr(rec, "data") and "flow" in rec_name.lower():
            data = rec.data
            if data is not None and len(data) > 0:
                col_name = rec_name.replace("_flow_recorder", "")
                flow_data[col_name] = data.flatten()

    # Build date index
    start = model.timestepper.start
    n_steps = max(len(v) for v in flow_data.values()) if flow_data else 0
    dates = pd.date_range(start=start, periods=n_steps, freq="D")

    df = pd.DataFrame(index=dates)
    df.index.name = "date"
    for name, values in flow_data.items():
        if len(values) < n_steps:
            values = np.pad(values, (0, n_steps - len(values)), constant_values=np.nan)
        df[f"{name}_m3s"] = values[:n_steps]

    csv_path = output_dir / "release_timeseries.csv"
    df.to_csv(csv_path, float_format="%.4f")
    return df, csv_path


def compute_statistics(storage_df, flow_df, model_json):
    """Compute summary statistics from results."""
    stats = {"storage": {}, "flows": {}, "reliability": {}}

    # Storage statistics
    for col in storage_df.columns:
        if "volume" in col.lower():
            s = storage_df[col].dropna()
            if len(s) > 0:
                stats["storage"][col] = {
                    "mean_m3": round(float(s.mean()), 0),
                    "mean_mcm": round(float(s.mean() / 1e6), 1),
                    "max_m3": round(float(s.max()), 0),
                    "min_m3": round(float(s.min()), 0),
                    "std_m3": round(float(s.std()), 0),
                    "days_at_max": int((s >= s.max() * 0.99).sum()),
                    "days_at_min": int((s <= s.min() * 1.01).sum()),
                }

    # Flow statistics
    for col in flow_df.columns:
        s = flow_df[col].dropna()
        if len(s) > 0:
            stats["flows"][col] = {
                "mean_m3s": round(float(s.mean()), 4),
                "max_m3s": round(float(s.max()), 4),
                "min_m3s": round(float(s.min()), 4),
                "total_volume_mcm": round(float(s.sum() * 86400 / 1e6), 1),
            }

            # Spill events
            if "spill" in col.lower():
                spill_days = int((s > 0.01).sum())
                stats["flows"][col]["spill_days"] = spill_days
                stats["flows"][col]["spill_fraction"] = round(
                    spill_days / max(len(s), 1), 3
                )

    # Reliability: for demand nodes
    # Get max capacity from model JSON
    max_vol = None
    if "metadata" in model_json and "reservoir" in model_json["metadata"]:
        cap_mcm = model_json["metadata"]["reservoir"].get("capacity_mcm")
        if cap_mcm:
            max_vol = cap_mcm * 1e6

    # Check demand satisfaction
    for col in flow_df.columns:
        if any(k in col.lower() for k in ["demand", "irrigation", "municipal", "environmental"]):
            demand_col = col
            supply = flow_df[demand_col].dropna()
            if len(supply) > 0:
                # Find corresponding max_flow parameter
                node_name = demand_col.replace("_m3s", "")
                # Reliability = days with supply > 0 / total days
                days_supplied = int((supply > 0.001).sum())
                total_days = len(supply)
                stats["reliability"][node_name] = {
                    "days_supplied": days_supplied,
                    "total_days": total_days,
                    "reliability_pct": round(100.0 * days_supplied / max(total_days, 1), 1),
                    "mean_supply_m3s": round(float(supply.mean()), 4),
                }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Run a Pywr model and extract results"
    )
    parser.add_argument("--model", type=str, required=True,
                        help="Pywr model JSON file")
    parser.add_argument("--output_dir", type=str, required=True,
                        help="Output directory for results")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed progress")

    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(json.dumps({"error": f"Model file not found: {args.model}"}))
        sys.exit(2)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model JSON for metadata
    with open(model_path, "r") as f:
        model_json = json.load(f)

    try:
        if args.verbose:
            print("Loading model...", file=sys.stderr)

        model = load_and_run_model(model_path)

        if args.verbose:
            print("Model run complete. Extracting results...", file=sys.stderr)

        # Extract timeseries
        storage_df, storage_csv = extract_storage_timeseries(model, output_dir)
        flow_df, flow_csv = extract_flow_timeseries(model, output_dir)

        # Compute statistics
        stats = compute_statistics(storage_df, flow_df, model_json)

        summary = {
            "status": "OK",
            "model_file": str(model_path),
            "output_dir": str(output_dir),
            "files": {
                "storage_csv": str(storage_csv),
                "release_csv": str(flow_csv),
            },
            "simulation": {
                "start_date": str(model.timestepper.start),
                "end_date": str(model.timestepper.end),
                "timesteps": len(storage_df) if len(storage_df) > 0 else len(flow_df),
            },
            "statistics": stats,
        }

        # Save summary
        summary_path = output_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        summary["files"]["summary_json"] = str(summary_path)
        print(json.dumps(summary, indent=2))
        sys.exit(0)

    except Exception as e:
        error_msg = str(e)
        if "infeasible" in error_msg.lower() or "InfeasibleError" in error_msg:
            print(json.dumps({
                "error": error_msg,
                "status": "INFEASIBLE",
                "hint": "Demands exceed available supply. Reduce demands or increase inflow.",
            }))
            sys.exit(1)
        else:
            import traceback
            print(json.dumps({
                "error": error_msg,
                "traceback": traceback.format_exc(),
                "status": "FAIL",
            }))
            sys.exit(3)


if __name__ == "__main__":
    main()
