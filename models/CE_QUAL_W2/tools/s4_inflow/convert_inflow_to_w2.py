#!/usr/bin/env python3
"""
convert_inflow_to_w2.py — Convert CaMa-Flood/VIC discharge to CE-QUAL-W2 inflow files.

Generates three files per branch inflow:
  1. qin_br*.npt — inflow discharge (m^3/s) vs Julian day
  2. tin_br*.npt — inflow temperature (deg C) vs Julian day
  3. cin_br*.npt — inflow constituent concentrations (optional)

CRITICAL (dt_003): CaMa-Flood outputs may be in mm/day over a grid cell area.
Convert to m^3/s: Q_m3s = Q_mm_day * cell_area_m2 / (86400 * 1000)
If the inflow is already in m^3/s (e.g., from routing output), no conversion needed.

Temperature estimation when no observed inflow temperature:
  T_inflow = a * T_air + b (regression: a=0.75, b=3.0 for temperate regions)
  Capped at 0.5 C minimum (above freezing point) and 35 C maximum.

Usage:
    python convert_inflow_to_w2.py \
        --discharge_file /path/to/cama_outflw.nc \
        --met_file met_wb1.npt \
        --start_year 2005 --end_year 2010 \
        --branch_id 1 \
        --output_dir /path/to/output

    python convert_inflow_to_w2.py \
        --discharge_csv /path/to/routing_output.csv \
        --met_file met_wb1.npt \
        --start_year 2005 --end_year 2010 \
        --branch_id 1 \
        --output_dir /path/to/output
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.discharge_file is None and args.discharge_csv is None:
        errors.append("Must provide --discharge_file (NetCDF) or --discharge_csv")

    if args.discharge_file and not os.path.isfile(args.discharge_file):
        errors.append(f"Discharge file not found: {args.discharge_file}")

    if args.discharge_csv and not os.path.isfile(args.discharge_csv):
        errors.append(f"Discharge CSV not found: {args.discharge_csv}")

    if args.branch_id < 1:
        errors.append("--branch_id must be >= 1")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def estimate_inflow_temperature(tair, a=0.75, b=3.0, t_min=0.5, t_max=35.0):
    """
    Estimate inflow temperature from air temperature using linear regression.

    T_inflow = a * T_air + b

    Defaults (temperate regions): a=0.75, b=3.0
    Tropical: a=0.85, b=2.0
    Cold/alpine: a=0.65, b=1.5

    Capped at [0.5, 35.0] C to prevent freezing or unrealistic values.
    """
    t_inflow = a * tair + b
    return np.clip(t_inflow, t_min, t_max)


def read_met_tair(met_file):
    """
    Read air temperature from CE-QUAL-W2 met file for temperature estimation.
    Returns (jdays, tair) arrays.
    """
    jdays = []
    tairs = []

    with open(met_file, "r") as f:
        for line in f:
            if line.startswith("$") or line.strip() == "":
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    jdays.append(float(parts[0]))
                    tairs.append(float(parts[1]))
                except ValueError:
                    continue

    return np.array(jdays), np.array(tairs)


def datetime_to_jday(dt):
    """Convert datetime to decimal Julian day (day of year)."""
    doy = dt.timetuple().tm_yday
    frac = dt.hour / 24.0 + dt.minute / 1440.0
    return doy + frac


def process(args):
    """Main processing."""
    os.makedirs(args.output_dir, exist_ok=True)

    # Read discharge data
    if args.discharge_csv:
        df = pd.read_csv(args.discharge_csv)
        # Expect columns: date (or datetime), discharge (m3/s)
        date_col = next((c for c in df.columns if "date" in c.lower() or "time" in c.lower()), df.columns[0])
        q_col = next((c for c in df.columns if "q" in c.lower() or "discharge" in c.lower() or "flow" in c.lower()), df.columns[1])
        dates = pd.to_datetime(df[date_col])
        discharge = df[q_col].values.astype(float)
    elif args.discharge_file:
        try:
            import xarray as xr
            ds = xr.open_dataset(args.discharge_file)
            # CaMa-Flood output: variable 'outflw' or 'rivout'
            var_name = None
            for v in ["outflw", "rivout", "discharge", "Q"]:
                if v in ds:
                    var_name = v
                    break
            if var_name is None:
                var_name = list(ds.data_vars)[0]

            # Extract time series at the nearest point
            data = ds[var_name]
            if "lat" in data.dims and "lon" in data.dims:
                data = data.sel(lat=args.inflow_lat, lon=args.inflow_lon, method="nearest")
            discharge = data.values.flatten()
            dates = pd.to_datetime(ds["time"].values)
            ds.close()
        except Exception as e:
            print(json.dumps({"status": "error", "errors": [f"Failed to read NetCDF: {e}"]}))
            return 2

    # Apply unit conversion if needed (dt_003)
    if args.convert_mm_to_m3s:
        cell_area_m2 = args.cell_area_km2 * 1e6 if args.cell_area_km2 else 625e6  # default 25x25 km
        discharge = discharge * cell_area_m2 / (86400.0 * 1000.0)

    # Filter to simulation period
    mask = (dates.year >= args.start_year) & (dates.year <= args.end_year)
    dates = dates[mask]
    discharge = discharge[mask]

    # Compute Julian days per year (CE-QUAL-W2 restarts JDAY each year)
    # For multi-year simulations, JDAY continues from year start
    jdays = np.array([datetime_to_jday(d.to_pydatetime()) for d in dates])

    # Estimate inflow temperature
    if args.met_file and os.path.isfile(args.met_file):
        met_jdays, met_tair = read_met_tair(args.met_file)
        # Interpolate air temperature to inflow timestamps
        tair_interp = np.interp(jdays, met_jdays, met_tair)
        t_inflow = estimate_inflow_temperature(tair_interp,
                                                a=args.temp_coef_a,
                                                b=args.temp_coef_b)
    else:
        # Default: assume moderate temperature
        t_inflow = np.full_like(discharge, 15.0)

    # Write qin_br*.npt (discharge)
    br = args.branch_id
    qin_path = os.path.join(args.output_dir, f"qin_br{br}.npt")
    with open(qin_path, "w") as f:
        f.write(f"$Inflow discharge for branch {br} — generated by HydroCraft\n")
        f.write(f"$JDAY          QIN\n")
        for i in range(len(jdays)):
            f.write(f"{jdays[i]:10.3f}{discharge[i]:10.3f}\n")

    # Write tin_br*.npt (temperature)
    tin_path = os.path.join(args.output_dir, f"tin_br{br}.npt")
    with open(tin_path, "w") as f:
        f.write(f"$Inflow temperature for branch {br} — generated by HydroCraft\n")
        f.write(f"$JDAY          TIN\n")
        for i in range(len(jdays)):
            f.write(f"{jdays[i]:10.3f}{t_inflow[i]:10.3f}\n")

    # Write cin_br*.npt (constituents — optional, placeholder)
    if args.enable_wq:
        cin_path = os.path.join(args.output_dir, f"cin_br{br}.npt")
        with open(cin_path, "w") as f:
            f.write(f"$Inflow constituents for branch {br} — generated by HydroCraft\n")
            f.write(f"$JDAY         TDS        ISS      PO4-P      NH4-N      NO3-N         DO\n")
            for i in range(len(jdays)):
                # Default moderate values
                f.write(f"{jdays[i]:10.3f}"
                        f"{200.0:10.3f}"   # TDS mg/L
                        f"{10.0:10.3f}"    # ISS mg/L
                        f"{0.05:10.3f}"    # PO4-P mg/L
                        f"{0.5:10.3f}"     # NH4-N mg/L
                        f"{1.0:10.3f}"     # NO3-N mg/L
                        f"{8.0:10.3f}"     # DO mg/L
                        + "\n")
    else:
        cin_path = None

    # Validate
    warnings = []
    if np.any(discharge < 0):
        warnings.append("Negative discharge values found — check source data")
    if np.any(discharge > 100000):
        warnings.append(f"Very large discharge ({np.max(discharge):.0f} m3/s) — verify units (dt_003)")
    if np.mean(discharge) < 0.01:
        warnings.append(f"Mean discharge very small ({np.mean(discharge):.4f} m3/s) — verify units")

    result = {
        "status": "success",
        "qin_file": qin_path,
        "tin_file": tin_path,
        "cin_file": cin_path,
        "branch_id": br,
        "n_timesteps": len(jdays),
        "discharge_mean_m3s": round(float(np.mean(discharge)), 2),
        "discharge_max_m3s": round(float(np.max(discharge)), 2),
        "temp_range": [round(float(np.min(t_inflow)), 1), round(float(np.max(t_inflow)), 1)],
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Convert discharge to CE-QUAL-W2 inflow files")

    parser.add_argument("--discharge_file", help="CaMa-Flood output NetCDF file")
    parser.add_argument("--discharge_csv", help="CSV with date + discharge columns")
    parser.add_argument("--met_file", help="CE-QUAL-W2 met file for temperature estimation")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--branch_id", type=int, default=1)
    parser.add_argument("--output_dir", required=True)

    # Unit conversion
    parser.add_argument("--convert_mm_to_m3s", action="store_true",
                       help="Convert mm/day to m3/s (for VIC/CaMa grid-cell output)")
    parser.add_argument("--cell_area_km2", type=float,
                       help="Grid cell area in km^2 (for mm to m3/s conversion)")

    # Temperature estimation
    parser.add_argument("--temp_coef_a", type=float, default=0.75,
                       help="T_inflow = a*T_air + b (default a=0.75)")
    parser.add_argument("--temp_coef_b", type=float, default=3.0,
                       help="T_inflow = a*T_air + b (default b=3.0)")

    # Water quality
    parser.add_argument("--enable_wq", action="store_true",
                       help="Generate constituent inflow file (cin_br*.npt)")

    # For NetCDF spatial indexing
    parser.add_argument("--inflow_lat", type=float, help="Latitude of inflow point")
    parser.add_argument("--inflow_lon", type=float, help="Longitude of inflow point")

    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
