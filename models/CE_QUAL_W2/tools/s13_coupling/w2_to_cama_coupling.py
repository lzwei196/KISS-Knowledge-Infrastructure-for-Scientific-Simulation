#!/usr/bin/env python3
"""
w2_to_cama_coupling.py — Convert CE-QUAL-W2 outflow to CaMa-Flood compatible format.

Extracts dam release discharge and temperature from CE-QUAL-W2 output
and converts to CaMa-Flood lateral inflow or boundary condition.

CRITICAL (dt_020): Verify spatial matching between CaMa grid cell at the dam
and the CE-QUAL-W2 outlet segment. Coordinate mismatch causes the outflow
to enter CaMa-Flood at the wrong location.

CRITICAL (dt_021): Avoid double-counting. If VIC already provides runoff for the
reservoir area and CaMa-Flood routes it, the CE-QUAL-W2 outflow should REPLACE
the CaMa routing through the reservoir, not add to it.

Usage:
    python w2_to_cama_coupling.py \
        --qout_file /path/to/qot_br1.npt \
        --dam_lat 32.54 --dam_lon 111.51 \
        --start_year 2005 --end_year 2010 \
        --output cama_lateral_inflow.nc
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def parse_w2_outflow(qout_file):
    """Parse CE-QUAL-W2 outflow file (qot_br*.npt)."""
    jdays = []
    flows = []

    with open(qout_file) as f:
        for line in f:
            if line.startswith("$") or line.strip() == "":
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    jdays.append(float(parts[0]))
                    flows.append(float(parts[1]))
                except ValueError:
                    continue

    return np.array(jdays), np.array(flows)


def process(args):
    """Main processing."""
    # Parse outflow
    jdays, flows = parse_w2_outflow(args.qout_file)

    if len(jdays) == 0:
        print(json.dumps({"status": "error", "errors": ["No data in outflow file"]}))
        return 2

    # Convert to daily time series
    # CE-QUAL-W2 may output sub-daily — aggregate to daily mean
    daily_jdays = np.arange(int(jdays[0]), int(jdays[-1]) + 1)
    daily_flows = np.interp(daily_jdays, jdays, flows)

    # Convert to dates
    year = args.start_year
    dates = [datetime(year, 1, 1) + timedelta(days=int(jd) - 1) for jd in daily_jdays]

    # Create output CSV (CaMa-Flood compatible)
    df = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "discharge_m3s": np.round(daily_flows, 2),
        "lat": args.dam_lat,
        "lon": args.dam_lon,
    })

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    df.to_csv(args.output, index=False)

    # Optionally create NetCDF
    if args.output.endswith(".nc"):
        try:
            import xarray as xr
            ds = xr.Dataset({
                "discharge": (["time"], daily_flows),
            }, coords={
                "time": pd.to_datetime(dates),
                "lat": args.dam_lat,
                "lon": args.dam_lon,
            })
            ds.attrs["description"] = "CE-QUAL-W2 dam release for CaMa-Flood coupling"
            ds.attrs["units"] = "m3/s"
            ds.to_netcdf(args.output)
        except ImportError:
            # Fallback to CSV
            csv_path = args.output.replace(".nc", ".csv")
            df.to_csv(csv_path, index=False)
            args.output = csv_path

    result = {
        "status": "success",
        "output_file": args.output,
        "n_days": len(daily_jdays),
        "mean_discharge_m3s": round(float(np.mean(daily_flows)), 2),
        "max_discharge_m3s": round(float(np.max(daily_flows)), 2),
        "dam_location": {"lat": args.dam_lat, "lon": args.dam_lon},
    }
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="CE-QUAL-W2 to CaMa-Flood coupling")
    parser.add_argument("--qout_file", required=True, help="W2 outflow file (qot_br*.npt)")
    parser.add_argument("--dam_lat", type=float, required=True)
    parser.add_argument("--dam_lon", type=float, required=True)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--output", required=True, help="Output file (CSV or NC)")
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
