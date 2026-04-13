#!/usr/bin/env python3
"""
check_overtopping.py — Check if reservoir storage ever exceeds max volume.

Analyzes Pywr results for overtopping events and flags them for potential
DLBreach dam-break simulation trigger.

Usage:
    python check_overtopping.py \
        --storage_csv results/storage_timeseries.csv \
        --max_volume_m3 2275000000 \
        --output results/overtopping_report.json

Output:
    JSON report of overtopping events with date, duration, excess volume.
    Exit codes: 0 = no overtopping, 1 = overtopping detected, 2 = input error
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def detect_overtopping(storage_df, max_volume_m3, tolerance_frac=0.001):
    """
    Detect overtopping events (storage > max_volume).

    tolerance_frac: fractional tolerance above max_volume to flag (0.001 = 0.1%)
    """
    threshold = max_volume_m3 * (1.0 + tolerance_frac)

    events = []
    vol_cols = [c for c in storage_df.columns if "volume" in c.lower()]

    for col in vol_cols:
        series = storage_df[col].dropna()
        over_mask = series > threshold

        if not over_mask.any():
            continue

        # Identify contiguous overtopping periods
        in_event = False
        event_start = None
        event_max = 0
        event_max_date = None

        for date, is_over in over_mask.items():
            if is_over and not in_event:
                # Start of event
                in_event = True
                event_start = date
                event_max = series[date]
                event_max_date = date
            elif is_over and in_event:
                # Continue event
                if series[date] > event_max:
                    event_max = series[date]
                    event_max_date = date
            elif not is_over and in_event:
                # End of event
                in_event = False
                duration = (date - event_start).days
                excess_m3 = event_max - max_volume_m3
                events.append({
                    "start_date": event_start.strftime("%Y-%m-%d"),
                    "end_date": date.strftime("%Y-%m-%d"),
                    "duration_days": duration,
                    "max_volume_m3": round(float(event_max), 0),
                    "max_volume_mcm": round(float(event_max / 1e6), 1),
                    "excess_volume_m3": round(float(excess_m3), 0),
                    "excess_volume_mcm": round(float(excess_m3 / 1e6), 1),
                    "excess_fraction": round(float(excess_m3 / max_volume_m3), 4),
                    "peak_date": event_max_date.strftime("%Y-%m-%d"),
                    "column": col,
                })

        # Handle event at end of timeseries
        if in_event:
            duration = (series.index[-1] - event_start).days
            excess_m3 = event_max - max_volume_m3
            events.append({
                "start_date": event_start.strftime("%Y-%m-%d"),
                "end_date": series.index[-1].strftime("%Y-%m-%d"),
                "duration_days": duration,
                "max_volume_m3": round(float(event_max), 0),
                "max_volume_mcm": round(float(event_max / 1e6), 1),
                "excess_volume_m3": round(float(excess_m3), 0),
                "excess_volume_mcm": round(float(excess_m3 / 1e6), 1),
                "excess_fraction": round(float(excess_m3 / max_volume_m3), 4),
                "peak_date": event_max_date.strftime("%Y-%m-%d"),
                "column": col,
            })

    return events


def main():
    parser = argparse.ArgumentParser(
        description="Check for reservoir overtopping events"
    )
    parser.add_argument("--storage_csv", type=str, required=True,
                        help="Storage timeseries CSV from run_pywr.py")
    parser.add_argument("--max_volume_m3", type=float, default=None,
                        help="Maximum reservoir volume in m3")
    parser.add_argument("--max_volume_mcm", type=float, default=None,
                        help="Maximum reservoir volume in MCM (alternative)")
    parser.add_argument("--reservoir_json", type=str, default=None,
                        help="Reservoir properties JSON (to get max_volume)")
    parser.add_argument("--tolerance", type=float, default=0.001,
                        help="Overtopping tolerance fraction (default: 0.001)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON report (default: stdout)")

    args = parser.parse_args()

    try:
        # Determine max volume
        if args.max_volume_m3:
            max_vol = args.max_volume_m3
        elif args.max_volume_mcm:
            max_vol = args.max_volume_mcm * 1e6
        elif args.reservoir_json:
            with open(args.reservoir_json, "r") as f:
                rdata = json.load(f)
            max_vol = rdata["storage"]["max_volume_m3"]
        else:
            print(json.dumps({"error": "Provide --max_volume_m3, --max_volume_mcm, or --reservoir_json"}))
            sys.exit(2)

        # Load storage data
        storage_df = pd.read_csv(args.storage_csv, parse_dates=["date"],
                                  index_col="date")

        # Detect overtopping
        events = detect_overtopping(storage_df, max_vol, args.tolerance)

        report = {
            "status": "OVERTOPPING" if events else "OK",
            "max_volume_m3": max_vol,
            "max_volume_mcm": round(max_vol / 1e6, 1),
            "overtopping_events": len(events),
            "events": events,
            "dlbreach_trigger": len(events) > 0,
            "dlbreach_note": (
                "Overtopping detected. Consider running DLBreach dam-break "
                "simulation for risk assessment."
            ) if events else None,
        }

        output_str = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output_str)
            print(f"Wrote overtopping report to {args.output}")
        else:
            print(output_str)

        sys.exit(1 if events else 0)

    except Exception as e:
        print(json.dumps({"error": str(e), "status": "FAIL"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
