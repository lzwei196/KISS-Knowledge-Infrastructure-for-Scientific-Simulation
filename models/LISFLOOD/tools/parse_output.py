#!/usr/bin/env python3
"""
LISFLOOD Output Parser
=======================
Extracts LISFLOOD results from NetCDF and TSS files to CSV and diagnostic summaries.

Parses:
  - dis.nc: Discharge [m³/s] at all channel pixels or gauge points
  - TSS files: Time series at gauges (ASCII format)
  - State variables: soil moisture, snow, groundwater storage
  - Water balance: checks mass conservation

Pattern: validate → process → validate

Usage:
    python parse_output.py \
        --output_dir /path/to/lisflood/out/ \
        --settings /path/to/settings.xml \
        --gauges "1,2,3" \
        --csv_out /path/to/results.csv \
        --summary /path/to/summary.json \
        --obs_file /path/to/observed.csv
"""

import argparse
import sys
import os
import json
from pathlib import Path

import numpy as np

try:
    import pandas as pd
    import netCDF4 as nc
except ImportError as e:
    print(f"Missing dependency: {e}. Install with: pip install pandas netCDF4")
    sys.exit(1)


def validate_inputs(output_dir, settings=None, obs_file=None):
    """Validate that output directory and files exist."""
    errors = []

    if not os.path.isdir(output_dir):
        errors.append(f"Output directory not found: {output_dir}")

    if settings and not os.path.isfile(settings):
        errors.append(f"Settings file not found: {settings}")

    if obs_file and not os.path.isfile(obs_file):
        errors.append(f"Observed data file not found: {obs_file}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Check for expected output files
    nc_files = list(Path(output_dir).glob("*.nc"))
    tss_files = list(Path(output_dir).glob("*.tss"))
    print(f"[OK] Output dir: {output_dir}")
    print(f"     NetCDF files: {len(nc_files)}")
    print(f"     TSS files: {len(tss_files)}")
    return True


def parse_tss_file(tss_path):
    """Parse a LISFLOOD TSS (time series) file.

    TSS format:
        Line 1: title string
        Line 2: number of columns
        Lines 3..N+2: column names (one per line)
        Remaining lines: timestep_number values...

    Returns pandas DataFrame with timestep index.
    """
    with open(tss_path, "r") as f:
        lines = f.readlines()

    if len(lines) < 4:
        print(f"[WARNING] TSS file too short: {tss_path}")
        return pd.DataFrame()

    title = lines[0].strip()
    try:
        n_cols = int(lines[1].strip())
    except ValueError:
        print(f"[WARNING] Cannot parse column count in {tss_path}")
        return pd.DataFrame()

    col_names = []
    for i in range(2, 2 + n_cols):
        if i < len(lines):
            col_names.append(lines[i].strip())

    # Parse data lines
    data_lines = lines[2 + n_cols:]
    data = []
    for line in data_lines:
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                row = [float(x) for x in parts]
                data.append(row)
            except ValueError:
                continue

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df.columns = ["timestep"] + col_names[:len(df.columns) - 1]
    df["timestep"] = df["timestep"].astype(int)
    df = df.set_index("timestep")

    print(f"[OK] Parsed TSS: {tss_path} ({len(df)} timesteps, {len(df.columns)} gauges)")
    return df


def parse_discharge_nc(output_dir, gauge_coords=None):
    """Parse discharge from dis.nc.

    If gauge_coords provided, extract time series at specific locations.
    Otherwise, return spatial statistics.
    """
    dis_path = os.path.join(output_dir, "dis.nc")
    if not os.path.exists(dis_path):
        print(f"[WARNING] dis.nc not found in {output_dir}")
        return None

    ds = nc.Dataset(dis_path)

    # Find discharge variable
    dis_var = None
    for vn in ["dis", "discharge", "DischargeMaps", "streamflow"]:
        if vn in ds.variables:
            dis_var = vn
            break

    if dis_var is None:
        print(f"[WARNING] No discharge variable found. Variables: {list(ds.variables.keys())}")
        ds.close()
        return None

    data = ds.variables[dis_var][:]
    time_var = None
    for tn in ["time", "Time"]:
        if tn in ds.variables:
            time_var = tn
            break

    times = None
    if time_var:
        time_units = ds.variables[time_var].units if hasattr(ds.variables[time_var], 'units') else None
        time_calendar = ds.variables[time_var].calendar if hasattr(ds.variables[time_var], 'calendar') else 'standard'
        if time_units:
            try:
                from netCDF4 import num2date
                times = num2date(ds.variables[time_var][:], time_units, calendar=time_calendar)
            except Exception:
                times = np.arange(data.shape[0])

    stats = {
        "shape": list(data.shape),
        "n_timesteps": int(data.shape[0]),
        "max_discharge_m3s": float(np.nanmax(data)),
        "mean_discharge_m3s": float(np.nanmean(data)),
        "min_discharge_m3s": float(np.nanmin(data[data > 0])) if np.any(data > 0) else 0,
    }

    # Extract at gauge points if coordinates provided
    if gauge_coords and len(data.shape) == 3:
        lats = ds.variables["lat"][:] if "lat" in ds.variables else None
        lons = ds.variables["lon"][:] if "lon" in ds.variables else None

        if lats is not None and lons is not None:
            gauge_series = {}
            for gid, (glat, glon) in gauge_coords.items():
                lat_idx = np.argmin(np.abs(lats - glat))
                lon_idx = np.argmin(np.abs(lons - glon))
                gauge_series[gid] = data[:, lat_idx, lon_idx]
            stats["gauge_series"] = gauge_series

    ds.close()
    print(f"[OK] Discharge parsed: {stats['n_timesteps']} steps, "
          f"max={stats['max_discharge_m3s']:.2f} m³/s")
    return stats


def parse_state_variables(output_dir):
    """Parse soil moisture, snow, groundwater state variables."""
    state_vars = {
        "theta1": ("Soil moisture layer 1a", "m3/m3"),
        "theta2": ("Soil moisture layer 1b", "m3/m3"),
        "theta3": ("Soil moisture layer 2", "m3/m3"),
        "snowcov": ("Snow water equivalent", "mm"),
        "uz": ("Upper zone storage", "mm"),
        "lz": ("Lower zone storage", "mm"),
        "twb": ("Total water balance", "mm"),
    }

    results = {}
    for var_name, (description, units) in state_vars.items():
        nc_path = os.path.join(output_dir, f"{var_name}.nc")
        if not os.path.exists(nc_path):
            continue

        try:
            ds = nc.Dataset(nc_path)
            # Find the data variable
            data_var = None
            for vn in ds.variables:
                if vn not in ("lat", "lon", "time", "x", "y"):
                    data_var = vn
                    break

            if data_var:
                data = ds.variables[data_var][:]
                results[var_name] = {
                    "description": description,
                    "units": units,
                    "shape": list(data.shape),
                    "mean": float(np.nanmean(data)),
                    "max": float(np.nanmax(data)),
                    "min": float(np.nanmin(data)),
                }
                print(f"[OK] {var_name}: mean={results[var_name]['mean']:.4f} {units}")
            ds.close()
        except Exception as e:
            print(f"[WARNING] Could not parse {var_name}: {e}")

    return results


def compute_metrics(simulated, observed):
    """Compute hydrological performance metrics.

    Returns dict with NSE, KGE, PBIAS, R², RMSE.
    """
    # Remove NaN pairs
    mask = ~(np.isnan(simulated) | np.isnan(observed))
    sim = simulated[mask]
    obs = observed[mask]

    if len(sim) < 10:
        return {"error": "Too few valid pairs for metrics"}

    # NSE (Nash-Sutcliffe Efficiency)
    nse = 1.0 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)

    # KGE (Kling-Gupta Efficiency)
    r = np.corrcoef(sim, obs)[0, 1]
    alpha = np.std(sim) / np.std(obs)  # variability ratio
    beta = np.mean(sim) / np.mean(obs)  # bias ratio
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    # PBIAS (Percent Bias)
    pbias = 100.0 * np.sum(sim - obs) / np.sum(obs)

    # R²
    r2 = r ** 2

    # RMSE
    rmse = np.sqrt(np.mean((sim - obs) ** 2))

    metrics = {
        "NSE": round(float(nse), 4),
        "KGE": round(float(kge), 4),
        "PBIAS": round(float(pbias), 2),
        "R2": round(float(r2), 4),
        "RMSE": round(float(rmse), 4),
        "r": round(float(r), 4),
        "n_pairs": int(len(sim)),
        "mean_obs": round(float(np.mean(obs)), 4),
        "mean_sim": round(float(np.mean(sim)), 4),
    }
    return metrics


def export_to_csv(discharge_data, tss_data, output_path):
    """Export parsed results to CSV."""
    if tss_data is not None and not tss_data.empty:
        tss_data.to_csv(output_path)
        print(f"[OK] TSS data exported to {output_path}")
        return True
    elif discharge_data and "gauge_series" in discharge_data:
        df = pd.DataFrame(discharge_data["gauge_series"])
        df.index.name = "timestep"
        df.to_csv(output_path)
        print(f"[OK] Discharge data exported to {output_path}")
        return True
    else:
        print("[WARNING] No data available for CSV export")
        return False


def validate_outputs(summary):
    """Validate parsed results for physical reasonableness."""
    warnings = []

    if "discharge" in summary:
        dis = summary["discharge"]
        if dis.get("max_discharge_m3s", 0) <= 0:
            warnings.append("Max discharge is 0 or negative — model may not have run")
        if dis.get("max_discharge_m3s", 0) > 1e6:
            warnings.append(f"Max discharge = {dis['max_discharge_m3s']:.0f} m³/s — "
                           f"extremely high, check units")

    if "state_variables" in summary:
        sv = summary["state_variables"]
        if "theta1" in sv:
            if sv["theta1"]["max"] > 1.0:
                warnings.append("Soil moisture > 1.0 m³/m³ — physically impossible")
            if sv["theta1"]["mean"] < 0.01:
                warnings.append("Mean soil moisture near zero — unrealistic")
        if "twb" in sv:
            if abs(sv["twb"]["mean"]) > 10:
                warnings.append(
                    f"Water balance residual = {sv['twb']['mean']:.2f} mm — "
                    f"mass conservation issue"
                )

    if "metrics" in summary:
        m = summary["metrics"]
        if m.get("NSE", -999) < -1:
            warnings.append(f"NSE = {m['NSE']:.2f} — very poor, model worse than mean")
        if abs(m.get("PBIAS", 0)) > 50:
            warnings.append(f"PBIAS = {m['PBIAS']:.1f}% — large systematic bias")

    for w in warnings:
        print(f"[WARNING] {w}")

    return len(warnings) == 0


def main():
    parser = argparse.ArgumentParser(description="LISFLOOD Output Parser")
    parser.add_argument("--output_dir", required=True, help="LISFLOOD output directory")
    parser.add_argument("--settings", default=None, help="Settings XML (for metadata)")
    parser.add_argument("--csv_out", default=None, help="Export discharge to CSV")
    parser.add_argument("--summary", default=None, help="Write summary JSON")
    parser.add_argument("--obs_file", default=None, help="Observed discharge CSV for metrics")
    parser.add_argument("--obs_col", default="discharge", help="Column name in obs CSV")
    args = parser.parse_args()

    print("=" * 60)
    print("LISFLOOD Output Parser")
    print("=" * 60)

    # Step 1: Validate inputs
    if not validate_inputs(args.output_dir, args.settings, args.obs_file):
        sys.exit(1)

    summary = {}

    # Step 2: Parse discharge
    print("\n--- Discharge ---")
    dis_stats = parse_discharge_nc(args.output_dir)
    if dis_stats:
        summary["discharge"] = dis_stats

    # Step 3: Parse TSS files
    print("\n--- Time Series (TSS) ---")
    tss_data = None
    tss_files = list(Path(args.output_dir).glob("*.tss"))
    if tss_files:
        # Parse the first (usually main) TSS file
        tss_data = parse_tss_file(str(tss_files[0]))
        summary["tss_file"] = str(tss_files[0].name)
        summary["tss_timesteps"] = len(tss_data)
    else:
        print("[INFO] No TSS files found")

    # Step 4: Parse state variables
    print("\n--- State Variables ---")
    state = parse_state_variables(args.output_dir)
    if state:
        summary["state_variables"] = state

    # Step 5: Compute metrics if observed data provided
    if args.obs_file:
        print("\n--- Performance Metrics ---")
        try:
            obs_df = pd.read_csv(args.obs_file, parse_dates=True, index_col=0)
            obs_values = obs_df[args.obs_col].values

            if tss_data is not None and not tss_data.empty:
                sim_values = tss_data.iloc[:, 0].values
                # Align lengths
                n = min(len(sim_values), len(obs_values))
                metrics = compute_metrics(sim_values[:n], obs_values[:n])
                summary["metrics"] = metrics
                print(f"  NSE  = {metrics.get('NSE', 'N/A')}")
                print(f"  KGE  = {metrics.get('KGE', 'N/A')}")
                print(f"  PBIAS = {metrics.get('PBIAS', 'N/A')}%")
                print(f"  R²   = {metrics.get('R2', 'N/A')}")
        except Exception as e:
            print(f"[WARNING] Could not compute metrics: {e}")

    # Step 6: Export CSV
    if args.csv_out:
        print("\n--- CSV Export ---")
        export_to_csv(dis_stats, tss_data, args.csv_out)

    # Step 7: Validate outputs
    print("\n--- Output validation ---")
    validate_outputs(summary)

    # Step 8: Write summary JSON
    if args.summary:
        os.makedirs(os.path.dirname(args.summary) or ".", exist_ok=True)
        with open(args.summary, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\n[OK] Summary written to {args.summary}")

    # Print summary
    print("\n--- Summary ---")
    if "discharge" in summary:
        d = summary["discharge"]
        print(f"  Timesteps: {d['n_timesteps']}")
        print(f"  Max Q: {d['max_discharge_m3s']:.2f} m³/s")
        print(f"  Mean Q: {d['mean_discharge_m3s']:.4f} m³/s")

    print("\n[DONE] Output parsing complete")


if __name__ == "__main__":
    main()
