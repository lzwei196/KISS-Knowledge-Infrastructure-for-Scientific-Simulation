#!/usr/bin/env python3
"""
glm_to_cama_outflow.py — Convert GLM outflow to CaMa-Flood lateral inflow.

Reads GLM outlet CSV (outlet_*.csv or overflow.csv) and converts to
CaMa-Flood-compatible lateral inflow at the downstream grid cell.

This closes the coupling loop:
  CaMa-Flood discharge -> GLM inflow -> GLM lake processes -> GLM outflow -> CaMa-Flood

Usage:
    python glm_to_cama_outflow.py \
        --glm_outlet output/outlet_1.csv \
        --overflow output/overflow.csv \
        --cama_grid_nc outputs/run/vic_temp/grid/basin_grid.nc \
        --downstream_cell_idx 15 \
        --output outputs/run/cama_lateral/glm_outflow.nc
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    has_outlet = args.glm_outlet and os.path.exists(args.glm_outlet)
    has_overflow = args.overflow and os.path.exists(args.overflow)

    if not has_outlet and not has_overflow:
        errors.append("Must provide at least one of --glm_outlet or --overflow")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Read GLM outflow and format for CaMa-Flood."""
    flows = []

    # Read outlet file(s)
    if args.glm_outlet and os.path.exists(args.glm_outlet):
        df_out = pd.read_csv(args.glm_outlet)
        # Find time and flow columns
        time_col = [c for c in df_out.columns if 'time' in c.lower()][0]
        flow_col = [c for c in df_out.columns if 'flow' in c.lower()][0]
        df_out[time_col] = pd.to_datetime(df_out[time_col])
        flows.append(df_out[[time_col, flow_col]].rename(
            columns={time_col: 'time', flow_col: 'flow_outlet'}))

    # Read overflow file
    if args.overflow and os.path.exists(args.overflow):
        df_ovf = pd.read_csv(args.overflow)
        if len(df_ovf.columns) >= 2:
            time_col = df_ovf.columns[0]
            flow_col = df_ovf.columns[1]
            df_ovf[time_col] = pd.to_datetime(df_ovf[time_col])
            flows.append(df_ovf[[time_col, flow_col]].rename(
                columns={time_col: 'time', flow_col: 'flow_overflow'}))

    if not flows:
        print(json.dumps({"status": "error",
                          "errors": ["No flow data could be read"]}))
        sys.exit(1)

    # Merge flows
    if len(flows) == 1:
        df = flows[0].copy()
        if 'flow_outlet' in df.columns:
            df['total_flow'] = df['flow_outlet']
        else:
            df['total_flow'] = df['flow_overflow']
    else:
        df = flows[0].merge(flows[1], on='time', how='outer')
        df = df.fillna(0)
        df['total_flow'] = df.get('flow_outlet', 0) + df.get('flow_overflow', 0)

    df = df.sort_values('time')
    df['total_flow'] = np.maximum(df['total_flow'].values, 0.0)

    # Resample to daily if subdaily
    if len(df) > 0:
        df = df.set_index('time').resample('D').mean().reset_index()

    # Write output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)

    if args.output.endswith('.nc'):
        # Write as NetCDF for CaMa-Flood
        import xarray as xr
        ds = xr.Dataset({
            'outflow': ('time', df['total_flow'].values),
        }, coords={
            'time': df['time'].values,
        })
        ds['outflow'].attrs = {'units': 'm3/s', 'long_name': 'GLM lake outflow'}
        ds.to_netcdf(args.output)
    else:
        # Write as CSV
        df[['time', 'total_flow']].to_csv(args.output, index=False)

    result = {
        "status": "success",
        "output_file": args.output,
        "num_records": len(df),
        "mean_flow_m3s": round(float(df['total_flow'].mean()), 2),
        "max_flow_m3s": round(float(df['total_flow'].max()), 2),
        "total_volume_mcm": round(
            float(df['total_flow'].sum() * 86400 / 1e6), 1),
    }

    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert GLM outflow to CaMa-Flood lateral inflow")
    parser.add_argument("--glm_outlet", type=str,
                        help="GLM outlet CSV file (outlet_*.csv)")
    parser.add_argument("--overflow", type=str,
                        help="GLM overflow CSV file (overflow.csv)")
    parser.add_argument("--downstream_cell_idx", type=int, default=0,
                        help="CaMa grid cell index for downstream insertion")
    parser.add_argument("--output", type=str, required=True,
                        help="Output file (.nc or .csv)")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
