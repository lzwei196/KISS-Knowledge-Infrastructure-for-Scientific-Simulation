#!/usr/bin/env python3
"""
parse_glm_output.py — Parse GLM NetCDF output and lake.csv.

Extracts key variables from GLM simulation output:
  - Temperature profiles (depth x time)
  - Surface and bottom temperature time series
  - Lake level / volume
  - Ice thickness and duration
  - Thermocline depth (if stratified)
  - Schmidt stability
  - Evaporation

Output formats: JSON summary, CSV time series, or both.

Usage:
    python parse_glm_output.py --output_nc output/output.nc --lake_csv output/lake.csv \
        --summary summary.json --timeseries surface_temp.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate input files exist."""
    errors = []
    if args.output_nc and not os.path.exists(args.output_nc):
        errors.append(f"output.nc not found: {args.output_nc}")
    if args.lake_csv and not os.path.exists(args.lake_csv):
        errors.append(f"lake.csv not found: {args.lake_csv}")
    if not args.output_nc and not args.lake_csv:
        errors.append("Must provide at least one of --output_nc or --lake_csv")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def parse_lake_csv(lake_csv_path):
    """Parse GLM lake.csv for lake-integrated time series."""
    df = pd.read_csv(lake_csv_path)

    # Standardize column names (GLM uses various conventions)
    col_map = {}
    for col in df.columns:
        cl = col.strip().lower()
        if 'time' in cl or 'date' in cl:
            col_map[col] = 'time'
        elif 'surface' in cl and 'temp' in cl:
            col_map[col] = 'surface_temp'
        elif cl == 'temp_surface' or cl == 'hfl':
            col_map[col] = 'surface_temp'
        elif 'lake level' in cl or 'lake_level' in cl or 'lvl' in cl:
            col_map[col] = 'lake_level'
        elif cl.strip() == 'volume' or cl.strip() == 'vol':
            col_map[col] = 'volume'
        elif 'blue ice' in cl and 'thick' in cl:
            col_map[col] = 'blue_ice_thickness'
        elif 'white ice' in cl and 'thick' in cl:
            col_map[col] = 'white_ice_thickness'
        elif 'snow' in cl and 'thick' in cl:
            col_map[col] = 'snow_thickness'
        elif 'evap' in cl:
            col_map[col] = 'evaporation'
        elif 'overflow' in cl or 'ovrflw' in cl:
            col_map[col] = 'overflow'
        elif 'tot_inflow' in cl:
            col_map[col] = 'total_inflow'
        elif 'tot_outflow' in cl:
            col_map[col] = 'total_outflow'

    df = df.rename(columns=col_map)

    if 'time' in df.columns:
        # GLM outputs "24:00:00" timestamps which pandas cannot parse.
        # Convert "24:00:00" to "00:00:00" of the next day.
        def fix_hour24(ts_str):
            ts_str = str(ts_str).strip()
            if ' 24:00:00' in ts_str:
                date_part = ts_str.split(' ')[0]
                fixed = pd.Timestamp(date_part) + pd.Timedelta(days=1)
                return fixed.strftime('%Y-%m-%d %H:%M:%S')
            return ts_str
        df['time'] = df['time'].apply(fix_hour24)
        df['time'] = pd.to_datetime(df['time'], errors='coerce')

    return df


def _nc_times(ds):
    """Decode the GLM output.nc time axis to python datetimes."""
    import netCDF4 as nc
    time_var = ds.variables.get('time', None)
    if time_var is None:
        return None
    try:
        return nc.num2date(
            time_var[:], time_var.units,
            calendar=getattr(time_var, 'calendar', 'standard'),
            only_use_cftime_datetimes=False, only_use_python_datetimes=True)
    except Exception:
        return time_var[:]


def extract_depth_timeseries(output_nc_path, depths_m):
    """Interpolate the simulated temperature profile onto FIXED depths below
    the water surface (metres), one row per output timestep.

    Why this exists (dag comparison caveat + dt_036): GLM's vertical grid is
    ADAPTIVE LAGRANGIAN -- layer count (NS) and layer heights (z) change every
    timestep, so column index != depth and no raw output variable is "the
    temperature at 0.5 m". Every comparison against a fixed-depth observation
    (thermistor chain, profile logger, soil/water sensor at a set depth) MUST
    interpolate the active layers onto the observation depths first.

    Reads ONE TIMESTEP AT A TIME (dt_034): a bulk `var[:]` read of the padded
    z=500 arrays segfaults libnetcdf with no traceback on long runs.

    z[] holds layer TOP heights above the lake bottom, ascending, valid only
    for the first NS entries; the water surface is z[NS-1]. Layer centres are
    used as the interpolation nodes, so `depth_below_surface = z[NS-1] - centre`.
    Depths below the lake bottom return NaN (never a clamped bottom value).
    """
    import netCDF4 as nc

    depths_m = np.asarray(depths_m, dtype=float)
    ds = nc.Dataset(output_nc_path)
    try:
        times = _nc_times(ds)
        ns_all = np.asarray(ds.variables['NS'][:]).astype(int)
        zvar = ds.variables['z']
        tvar = ds.variables['temp']
        nt = len(ns_all)
        rows = np.full((nt, len(depths_m)), np.nan)
        surf = np.full(nt, np.nan)
        for i in range(nt):
            ns = int(ns_all[i])
            if ns < 1:
                continue
            z = np.asarray(np.squeeze(zvar[i]), dtype=float)[:ns]
            t = np.asarray(np.squeeze(tvar[i]), dtype=float)[:ns]
            good = np.isfinite(z) & np.isfinite(t)
            z, t = z[good], t[good]
            if z.size == 0:
                continue
            bottoms = np.concatenate(([0.0], z[:-1]))
            centres = 0.5 * (bottoms + z)
            surface_h = float(z[-1])
            surf[i] = surface_h
            d = surface_h - centres          # depth below surface, descending
            order = np.argsort(d)
            d, tt = d[order], t[order]
            vals = np.interp(depths_m, d, tt)   # clamps to surface layer above d[0]
            vals = np.where(depths_m > surface_h, np.nan, vals)
            rows[i] = vals
    finally:
        ds.close()

    out = pd.DataFrame(rows, columns=[f"temp_{d:g}m" for d in depths_m])
    out.insert(0, 'time', pd.to_datetime(times) if times is not None else np.arange(len(out)))
    out['water_depth_m'] = surf
    return out


def parse_output_nc(output_nc_path):
    """Parse GLM output.nc for temperature profiles."""
    import netCDF4 as nc

    ds = nc.Dataset(output_nc_path)

    # Get dimensions and variables
    info = {
        "dimensions": {dim: ds.dimensions[dim].size for dim in ds.dimensions},
        "variables": list(ds.variables.keys()),
    }

    # Extract temperature profile.
    # dt_034: read timestep-by-timestep over the ACTIVE layers only. A bulk
    # `[:]` read of the padded z=500 array segfaults libnetcdf on long runs,
    # and the padding rows would poison min/max/mean anyway.
    temp = None
    tname = next((v for v in ('temp', 'temperature', 'TEMP') if v in ds.variables), None)
    if tname is not None and 'NS' in ds.variables:
        ns_all = np.asarray(ds.variables['NS'][:]).astype(int)
        tvar = ds.variables[tname]
        chunks = []
        for i in range(len(ns_all)):
            ns = int(ns_all[i])
            if ns < 1:
                continue
            chunks.append(np.asarray(np.squeeze(tvar[i]), dtype=float)[:ns])
        if chunks:
            temp = np.concatenate(chunks)
    elif tname is not None:
        temp = ds.variables[tname][:]

    # Get time
    time_var = ds.variables.get('time', None)
    if time_var is not None:
        import cftime
        try:
            times = nc.num2date(time_var[:], time_var.units,
                                calendar=time_var.calendar if hasattr(time_var, 'calendar')
                                else 'standard')
        except Exception:
            times = time_var[:]
    else:
        times = None

    # Get depth/height
    z = None
    for var_name in ['z', 'depth', 'NS', 'heights']:
        if var_name in ds.variables:
            z = ds.variables[var_name][:]
            break

    ds.close()

    return {
        "info": info,
        "temp": temp,
        "times": times,
        "z": z,
    }


def compute_thermocline_depth(temp_profile, depths):
    """
    Estimate thermocline depth as the depth of maximum temperature gradient.
    Returns NaN if lake is well-mixed (gradient < 0.5 C/m everywhere).
    """
    if temp_profile is None or depths is None:
        return np.nan
    if len(temp_profile) < 3:
        return np.nan

    # Remove NaN
    valid = ~np.isnan(temp_profile) & ~np.isnan(depths)
    if valid.sum() < 3:
        return np.nan

    t = temp_profile[valid]
    d = depths[valid]

    # Compute gradient
    dt = np.diff(t)
    dd = np.diff(d)
    gradient = np.abs(dt / np.maximum(dd, 0.01))

    if np.max(gradient) < 0.5:  # Well-mixed
        return np.nan

    idx = np.argmax(gradient)
    return (d[idx] + d[idx + 1]) / 2.0


def compute_schmidt_stability(temp_profile, depths, area_profile=None):
    """
    Compute Schmidt stability (resistance to mechanical mixing).
    S = g/A_s * integral((z - z_v) * rho(z) * A(z) dz)
    Simplified version using density from temperature.
    """
    if temp_profile is None or depths is None:
        return np.nan

    valid = ~np.isnan(temp_profile) & ~np.isnan(depths)
    if valid.sum() < 3:
        return np.nan

    t = temp_profile[valid]
    d = depths[valid]

    # Density from temperature (UNESCO 1983, simplified for freshwater)
    rho = 999.842594 + 6.793952e-2 * t - 9.095290e-3 * t**2 + \
          1.001685e-4 * t**3 - 1.120083e-6 * t**4

    # Volume-weighted mean depth (center of mass)
    z_v = np.trapz(d * rho, d) / np.trapz(rho, d) if np.trapz(rho, d) != 0 else np.mean(d)

    # Schmidt stability (simplified, per unit area)
    g = 9.81
    integrand = (d - z_v) * (rho - np.mean(rho))
    S = g * np.trapz(integrand, d)

    return round(float(S), 2)


def process(args):
    """Parse GLM output and compute summary statistics."""
    result = {"status": "success"}

    # Parse lake.csv
    if args.lake_csv and os.path.exists(args.lake_csv):
        df = parse_lake_csv(args.lake_csv)
        result["lake_csv"] = {
            "num_records": len(df),
            "columns": list(df.columns),
        }

        if 'time' in df.columns:
            result["lake_csv"]["start_date"] = str(df['time'].iloc[0])
            result["lake_csv"]["end_date"] = str(df['time'].iloc[-1])

        if 'surface_temp' in df.columns:
            st = df['surface_temp'].dropna()
            result["surface_temp"] = {
                "mean_degC": round(float(st.mean()), 2),
                "min_degC": round(float(st.min()), 2),
                "max_degC": round(float(st.max()), 2),
                "std_degC": round(float(st.std()), 2),
            }

        if 'lake_level' in df.columns:
            ll = df['lake_level'].dropna()
            result["lake_level"] = {
                "mean_m": round(float(ll.mean()), 3),
                "min_m": round(float(ll.min()), 3),
                "max_m": round(float(ll.max()), 3),
                "range_m": round(float(ll.max() - ll.min()), 3),
            }

        # Compute total ice thickness from blue + white ice
        ice_total = pd.Series(0.0, index=df.index)
        if 'blue_ice_thickness' in df.columns:
            ice_total = ice_total + df['blue_ice_thickness'].fillna(0)
        if 'white_ice_thickness' in df.columns:
            ice_total = ice_total + df['white_ice_thickness'].fillna(0)
        if ice_total.max() > 0.001:
            ice_days = int((ice_total > 0.01).sum())
            result["ice"] = {
                "total_ice_days": ice_days,
                "max_thickness_m": round(float(ice_total.max()), 3),
                "mean_thickness_when_frozen_m": round(
                    float(ice_total[ice_total > 0.01].mean()), 3) if ice_days > 0 else 0.0,
            }

        if args.timeseries:
            os.makedirs(os.path.dirname(args.timeseries) or '.', exist_ok=True)
            df.to_csv(args.timeseries, index=False)
            result["timeseries_file"] = args.timeseries

    # Parse output.nc
    if args.output_nc and os.path.exists(args.output_nc):
        nc_data = parse_output_nc(args.output_nc)
        result["output_nc"] = nc_data["info"]

        if nc_data["temp"] is not None:
            temp = nc_data["temp"]
            result["temperature_profile"] = {
                "n_active_layer_samples": int(np.asarray(temp).size),
                "global_min_degC": round(float(np.nanmin(temp)), 2),
                "global_max_degC": round(float(np.nanmax(temp)), 2),
                "global_mean_degC": round(float(np.nanmean(temp)), 2),
            }

        # Fixed-depth extraction (dag caveat: "interpolate to fixed observation
        # depths" -- Lagrangian layers shift between outputs).
        if args.depths:
            depths = [float(x) for x in str(args.depths).split(',') if x.strip()]
            dts = extract_depth_timeseries(args.output_nc, depths)
            result["depth_timeseries"] = {
                "depths_m": depths,
                "n_records": int(len(dts)),
                "means_degC": {c: (round(float(dts[c].mean()), 2)
                                   if np.isfinite(dts[c].to_numpy(dtype=float)).any() else None)
                               for c in dts.columns if c.startswith('temp_')},
            }
            if args.depth_timeseries:
                os.makedirs(os.path.dirname(args.depth_timeseries) or '.', exist_ok=True)
                dts.to_csv(args.depth_timeseries, index=False)
                result["depth_timeseries"]["file"] = args.depth_timeseries

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse GLM output files and compute summary statistics")
    parser.add_argument("--output_nc", type=str,
                        help="Path to GLM output.nc")
    parser.add_argument("--lake_csv", type=str,
                        help="Path to GLM lake.csv")
    parser.add_argument("--summary", type=str,
                        help="Output JSON summary path")
    parser.add_argument("--timeseries", type=str,
                        help="Output CSV time series path")
    parser.add_argument("--depths", type=str,
                        help="Comma-separated depths BELOW WATER SURFACE (m) to "
                             "interpolate the simulated profile onto, e.g. "
                             "'0.05,0.2,1.0'. Required for any comparison against "
                             "fixed-depth observations (Lagrangian layers move).")
    parser.add_argument("--depth_timeseries", type=str,
                        help="Output CSV path for the fixed-depth temperature "
                             "series produced by --depths")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    output_json = json.dumps(result, indent=2, default=str)
    if args.summary:
        os.makedirs(os.path.dirname(args.summary) or '.', exist_ok=True)
        with open(args.summary, 'w') as f:
            f.write(output_json)
        print(f"Summary written to {args.summary}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
