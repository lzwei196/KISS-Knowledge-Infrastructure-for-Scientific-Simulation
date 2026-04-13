#!/usr/bin/env python3
"""
configure_outflow.py — Generate GLM outflow CSV and namelist parameters.

Supports multiple outflow modes:
  1. Natural overflow (weir/spillway) — no outflow CSV needed, GLM handles internally
  2. Constant release — fixed m3/s
  3. Scheduled release — time-varying from user data or operation rules
  4. Balance mode — outflow = inflow (steady-state lake level)

GLM outflow CSV format:
    time,FLOW
    YYYY-MM-DD HH:MM:SS,m3/s

Usage:
    python configure_outflow.py --mode natural --crest_elev 320 --output_json outflow_config.json
    python configure_outflow.py --mode constant --flow 10.0 \
        --start_date 2000-01-01 --end_date 2010-12-31 --output bcs/outflow.csv
    python configure_outflow.py --mode balance --inflow_csv bcs/inflow_1.csv \
        --output bcs/outflow.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate arguments."""
    errors = []
    if args.mode not in ['natural', 'constant', 'scheduled', 'balance']:
        errors.append(f"Invalid mode: {args.mode}")
    if args.mode == 'constant' and args.flow is None:
        errors.append("--flow is required for constant mode")
    if args.mode == 'balance' and args.inflow_csv is None:
        errors.append("--inflow_csv is required for balance mode")
    if args.mode in ['constant', 'balance'] and (
            args.start_date is None or args.end_date is None):
        errors.append("--start_date and --end_date required for CSV output modes")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Generate outflow configuration."""
    if args.mode == 'natural':
        # No outflow CSV — GLM handles overflow via crest_width and crest_factor
        result = {
            "status": "success",
            "mode": "natural",
            "num_outlet": 0,
            "flt_off_sw": False,
            "outl_elvs": args.crest_elev or 100.0,
            "crest_width": args.crest_width,
            "crest_factor": args.crest_factor,
            "outflow_fl": "",
            "message": "Natural overflow mode — no outflow CSV generated. "
                       "GLM computes overflow using broad-crested weir formula.",
        }
        return result, None

    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d")

    if args.mode == 'constant':
        n_days = (end_dt - start_dt).days + 1
        times = pd.date_range(start_dt, periods=n_days, freq='D')
        flow = np.full(n_days, args.flow)

    elif args.mode == 'balance':
        inflow = pd.read_csv(args.inflow_csv)
        inflow['time'] = pd.to_datetime(inflow['time'])
        inflow = inflow[(inflow['time'] >= args.start_date) &
                        (inflow['time'] <= args.end_date)]
        times = inflow['time']
        flow = inflow['FLOW'].values * args.outflow_fraction

    elif args.mode == 'scheduled':
        if args.schedule_csv:
            sched = pd.read_csv(args.schedule_csv)
            sched['time'] = pd.to_datetime(sched['time'])
            sched = sched[(sched['time'] >= args.start_date) &
                          (sched['time'] <= args.end_date)]
            times = sched['time']
            flow = sched['FLOW'].values
        else:
            # Default seasonal pattern for Chinese reservoirs
            n_days = (end_dt - start_dt).days + 1
            times = pd.date_range(start_dt, periods=n_days, freq='D')
            flow = np.zeros(n_days)
            base_flow = args.flow or 10.0
            for i, t in enumerate(times):
                month = t.month
                if 6 <= month <= 9:  # Flood season: higher release
                    flow[i] = base_flow * 1.5
                else:  # Non-flood: lower release
                    flow[i] = base_flow * 0.7

    df = pd.DataFrame({
        'time': pd.DatetimeIndex(times).strftime('%Y-%m-%d %H:%M:%S'),
        'FLOW': np.round(np.maximum(flow, 0.0), 3),
    })

    outflow_elev = args.outflow_elev or (args.crest_elev - 5.0 if args.crest_elev else 95.0)

    result = {
        "status": "success",
        "mode": args.mode,
        "num_outlet": 1,
        "flt_off_sw": args.floating_offtake,
        "outl_elvs": outflow_elev,
        "bsn_len_outl": args.bsn_len_outl,
        "bsn_wid_outl": args.bsn_wid_outl,
        "outflow_fl": args.output,
        "outflow_factor": args.outflow_factor,
        "crest_width": args.crest_width,
        "crest_factor": args.crest_factor,
        "flow_mean_m3s": round(float(df['FLOW'].mean()), 2),
        "flow_max_m3s": round(float(df['FLOW'].max()), 2),
        "num_records": len(df),
    }

    return result, df


def main():
    parser = argparse.ArgumentParser(
        description="Generate GLM outflow configuration")
    parser.add_argument("--mode", type=str, default="natural",
                        choices=["natural", "constant", "scheduled", "balance"],
                        help="Outflow mode (default: natural)")
    parser.add_argument("--flow", type=float,
                        help="Constant outflow rate (m3/s)")
    parser.add_argument("--inflow_csv", type=str,
                        help="Inflow CSV for balance mode")
    parser.add_argument("--schedule_csv", type=str,
                        help="Scheduled releases CSV (time, FLOW)")
    parser.add_argument("--crest_elev", type=float,
                        help="Crest/spillway elevation (m)")
    parser.add_argument("--outflow_elev", type=float,
                        help="Outflow withdrawal elevation (m)")
    parser.add_argument("--crest_width", type=float, default=100.0,
                        help="Spillway crest width (m, default: 100)")
    parser.add_argument("--crest_factor", type=float, default=0.61,
                        help="Broad-crested weir factor (default: 0.61)")
    parser.add_argument("--outflow_factor", type=float, default=1.0,
                        help="Outflow scaling factor (default: 1.0)")
    parser.add_argument("--outflow_fraction", type=float, default=1.0,
                        help="Fraction of inflow for balance mode (default: 1.0)")
    parser.add_argument("--floating_offtake", action="store_true",
                        help="Enable floating offtake (surface withdrawal)")
    parser.add_argument("--bsn_len_outl", type=float, default=100.0,
                        help="Basin length at outlet (m, default: 100)")
    parser.add_argument("--bsn_wid_outl", type=float, default=50.0,
                        help="Basin width at outlet (m, default: 50)")
    parser.add_argument("--start_date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="bcs/outflow.csv",
                        help="Output CSV file path")
    parser.add_argument("--output_json", type=str,
                        help="Output JSON config path")
    args = parser.parse_args()

    validate_inputs(args)
    result, df = process(args)

    if df is not None:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        df.to_csv(args.output, index=False)
        print(f"Outflow CSV written to {args.output}", file=sys.stderr)

    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or '.', exist_ok=True)
        with open(args.output_json, 'w') as f:
            json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
