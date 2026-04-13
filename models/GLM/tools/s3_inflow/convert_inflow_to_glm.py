#!/usr/bin/env python3
"""
convert_inflow_to_glm.py — Convert CaMa-Flood/VIC discharge to GLM inflow CSV.

GLM inflow CSV format:
    time,FLOW,TEMP,SALT
    YYYY-MM-DD HH:MM:SS,m3/s,degC,psu

Inflow temperature estimation (when not measured):
    T_inflow = a * T_air + b  (default: a=0.9, b=1.5 for temperate)

CRITICAL: Inflow salinity should be 0.0 for freshwater lakes.
    Non-zero salinity causes density-driven insertion at wrong depth.

Usage:
    python convert_inflow_to_glm.py \
        --cama_outflow model/cmf_v420_pkg/out/run1/outflw_YYYY.nc \
        --cell_idx 42 \
        --met_csv bcs/met_hourly.csv \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output bcs/inflow_1.csv

    python convert_inflow_to_glm.py \
        --vic_routing_file routing_output.day \
        --met_csv bcs/met_hourly.csv \
        --output bcs/inflow_1.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    has_cama = args.cama_outflow is not None
    has_vic_routing = args.vic_routing_file is not None
    has_constant = args.constant_flow is not None

    if not (has_cama or has_vic_routing or has_constant):
        errors.append(
            "Must provide one of: --cama_outflow, --vic_routing_file, "
            "or --constant_flow")

    if has_cama and not os.path.exists(args.cama_outflow):
        errors.append(f"CaMa-Flood output not found: {args.cama_outflow}")

    if has_vic_routing and not os.path.exists(args.vic_routing_file):
        errors.append(f"VIC routing file not found: {args.vic_routing_file}")

    if args.met_csv and not os.path.exists(args.met_csv):
        errors.append(f"Met CSV not found: {args.met_csv}")

    if args.temp_coeff_a < 0 or args.temp_coeff_a > 2:
        errors.append(f"--temp_coeff_a should be 0-2, got {args.temp_coeff_a}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def estimate_inflow_temp(air_temp, coeff_a=0.9, coeff_b=1.5, min_temp=0.5):
    """
    Estimate inflow water temperature from air temperature.

    Linear regression: T_water = a * T_air + b
    Default coefficients from literature (temperate rivers):
      a = 0.9, b = 1.5 (Stefan & Preud'homme, 1993)

    For cold regions (alpine/glacier):
      a = 0.7, b = 0.5
    For tropical:
      a = 0.95, b = 2.0

    Minimum temperature capped at min_temp to prevent density issues.
    """
    t_water = coeff_a * np.array(air_temp) + coeff_b
    t_water = np.maximum(t_water, min_temp)
    return t_water


def read_cama_outflow(cama_file, cell_idx, start_date, end_date):
    """Read CaMa-Flood outflw NetCDF and extract flow at specified cell."""
    import xarray as xr

    ds = xr.open_dataset(cama_file)
    # CaMa output variable is 'outflw' (m3/s)
    if 'outflw' in ds:
        flow_var = 'outflw'
    elif 'rivout' in ds:
        flow_var = 'rivout'
    else:
        flow_var = list(ds.data_vars)[0]

    flow = ds[flow_var]

    # Handle different CaMa output structures
    if 'lat' in flow.dims and 'lon' in flow.dims:
        # Standard CaMa gridded output (time, lat, lon) — flatten spatial dims
        # cell_idx indexes into the flattened lat*lon grid
        nlat = flow.sizes['lat']
        nlon = flow.sizes['lon']
        lat_idx = cell_idx // nlon
        lon_idx = cell_idx % nlon
        flow_ts = flow.isel(lat=lat_idx, lon=lon_idx)
    elif 'x' in flow.dims and 'y' in flow.dims:
        # Gridded output with x/y dims
        flow_ts = flow.isel(x=cell_idx % flow.sizes['x'],
                            y=cell_idx // flow.sizes['x'])
    elif len(flow.dims) == 2:
        # Time x station format
        flow_ts = flow.isel({flow.dims[1]: cell_idx})
    else:
        flow_ts = flow

    times = pd.DatetimeIndex(ds.time.values)
    values = flow_ts.values.flatten()

    ds.close()

    # Filter to date range
    mask = (times >= start_date) & (times <= end_date)
    return times[mask], values[mask]


def read_vic_routing(routing_file, start_date, end_date):
    """Read VIC Lohmann routing output (daily discharge)."""
    # Routing output format: YYYY MM DD Q(m3/s)
    data = pd.read_csv(routing_file, sep=r'\s+', header=None,
                       names=['year', 'month', 'day', 'flow'])
    data['time'] = pd.to_datetime(
        data[['year', 'month', 'day']])
    data = data[(data['time'] >= start_date) & (data['time'] <= end_date)]
    return data['time'].values, data['flow'].values


def process(args):
    """Build GLM inflow CSV."""
    start_dt = pd.Timestamp(args.start_date)
    end_dt = pd.Timestamp(args.end_date)

    if args.cama_outflow:
        times, flow = read_cama_outflow(args.cama_outflow, args.cell_idx,
                                        start_dt, end_dt)
    elif args.vic_routing_file:
        times, flow = read_vic_routing(args.vic_routing_file, start_dt, end_dt)
    else:
        # Constant flow mode
        n_days = (end_dt - start_dt).days + 1
        times = pd.date_range(start_dt, periods=n_days, freq='D')
        flow = np.full(n_days, args.constant_flow)

    # Ensure flow is positive
    flow = np.maximum(flow, 0.0)

    # Estimate inflow temperature
    if args.met_csv:
        met = pd.read_csv(args.met_csv)
        met['time'] = pd.to_datetime(met['time'])

        # Resample met to daily for temperature matching
        met_daily = met.set_index('time').resample('D')['AirTemp'].mean()

        temp_values = []
        for t in times:
            t_pd = pd.Timestamp(t)
            if t_pd in met_daily.index:
                air_t = met_daily[t_pd]
            else:
                # Find nearest date
                idx = met_daily.index.get_indexer([t_pd], method='nearest')[0]
                air_t = met_daily.iloc[idx]
            temp_values.append(air_t)

        temp = estimate_inflow_temp(temp_values, args.temp_coeff_a,
                                    args.temp_coeff_b)
    elif args.constant_temp is not None:
        temp = np.full(len(times), args.constant_temp)
    else:
        # Default: 10 degC constant
        temp = np.full(len(times), 10.0)
        print("WARNING: No temperature data provided. Using constant 10 degC.",
              file=sys.stderr)

    # Salinity (0 for freshwater)
    salt = np.full(len(times), args.salinity)

    df = pd.DataFrame({
        'time': pd.DatetimeIndex(times).strftime('%Y-%m-%d %H:%M:%S'),
        'FLOW': np.round(flow, 3),
        'TEMP': np.round(temp, 2),
        'SALT': np.round(salt, 3),
    })

    return df


def validate_outputs(df):
    """Validate inflow data."""
    warnings = []

    if df['FLOW'].min() < 0:
        warnings.append("Negative flow values detected — clipped to 0")
    if df['FLOW'].max() == 0:
        warnings.append("All flow values are zero — lake will have no inflow")

    temp_min = df['TEMP'].min()
    temp_max = df['TEMP'].max()
    if temp_min < 0:
        warnings.append(f"Inflow temperature below 0 degC ({temp_min:.1f}) — "
                        f"may cause density issues")
    if temp_max > 40:
        warnings.append(f"Inflow temperature very high ({temp_max:.1f} degC)")
    if temp_max - temp_min < 1:
        warnings.append("Inflow temperature has very little variation — "
                        "check if estimation is working")

    if df['SALT'].max() > 0 and df['SALT'].max() < 0.5:
        warnings.append("Salinity is non-zero but low — verify if this is a "
                        "freshwater lake (should be 0.0)")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert discharge data to GLM inflow CSV format")
    parser.add_argument("--cama_outflow", type=str,
                        help="CaMa-Flood outflw NetCDF file")
    parser.add_argument("--cell_idx", type=int, default=0,
                        help="CaMa grid cell index for the lake inlet")
    parser.add_argument("--vic_routing_file", type=str,
                        help="VIC Lohmann routing output file (.day)")
    parser.add_argument("--constant_flow", type=float,
                        help="Constant inflow rate (m3/s)")
    parser.add_argument("--met_csv", type=str,
                        help="GLM meteorological CSV (for temperature estimation)")
    parser.add_argument("--constant_temp", type=float,
                        help="Constant inflow temperature (degC)")
    parser.add_argument("--temp_coeff_a", type=float, default=0.9,
                        help="T_water = a*T_air + b coefficient a (default: 0.9)")
    parser.add_argument("--temp_coeff_b", type=float, default=1.5,
                        help="T_water = a*T_air + b coefficient b (default: 1.5)")
    parser.add_argument("--salinity", type=float, default=0.0,
                        help="Inflow salinity in psu (default: 0.0 for freshwater)")
    parser.add_argument("--start_date", type=str, required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    args = parser.parse_args()

    validate_inputs(args)
    df = process(args)
    warnings = validate_outputs(df)

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    df.to_csv(args.output, index=False)

    result = {
        "status": "success",
        "output_file": args.output,
        "num_records": len(df),
        "flow_mean_m3s": round(float(df['FLOW'].mean()), 2),
        "flow_max_m3s": round(float(df['FLOW'].max()), 2),
        "temp_mean_degC": round(float(df['TEMP'].mean()), 1),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
