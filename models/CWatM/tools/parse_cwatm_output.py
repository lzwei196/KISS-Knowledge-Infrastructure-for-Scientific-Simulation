#!/usr/bin/env python3
"""
parse_cwatm_output.py — Extract CWatM results from NetCDF outputs to CSV/analysis format.

CWatM produces:
  - NetCDF time series at gauge locations (discharge, ET, runoff, etc.)
  - NetCDF gridded maps (spatial variables at different temporal aggregations)
  - TSS text files (legacy format)

This tool:
  1. Reads discharge/state variable NetCDFs from the output directory
  2. Extracts time series at specified gauge locations
  3. Computes summary statistics and hydrological metrics
  4. Exports to CSV for analysis

Usage:
    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --variable discharge \\
        --gauge_index 0 \\
        --csv_out discharge_timeseries.csv

    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --variable discharge \\
        --all_gauges \\
        --csv_out all_gauges.csv \\
        --compute_metrics \\
        --observed_csv /path/to/observed.csv

    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --summary \\
        --csv_out summary.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    if nc is None:
        errors.append("netCDF4 package required. Install with: pip install netCDF4")

    if args.observed_csv and not os.path.isfile(args.observed_csv):
        errors.append(f"Observed data file not found: {args.observed_csv}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


# CWatM writes gauge time series requested with OUT_TSS_* as a TSS-style CSV
# (`<var>_daily.csv`), NOT NetCDF.  Only the OUT_Map_* variables become .nc.
# Layout:
#   line 0  Timeseries,settingsfile: ...,Runnning date: ...,CWATM: ...
#   line 1  xloc,<lon1>[,<lon2>...]
#   line 2  yloc,<lat1>[,<lat2>...]
#   line 3  Date,G1[,G2...]
#   line 4+ DD/MM/YYYY,<value>[,<value>...]
TSS_DATE_FMTS = ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y")


def read_tss_csv(csv_path, gauge_index=0):
    """Read a CWatM OUT_TSS_* gauge time series (TSS-style CSV).

    Returns (dates, values, metadata) with the same contract as
    extract_timeseries so both sources are interchangeable.
    """
    dates, values = [], []
    header_cols, xloc, yloc = None, None, None

    with open(csv_path, "r") as f:
        for raw in f:
            row = [c.strip() for c in raw.rstrip("\n").split(",")]
            if not row or not row[0]:
                continue
            tag = row[0].lower()
            if tag == "xloc":
                xloc = row[1:]
                continue
            if tag == "yloc":
                yloc = row[1:]
                continue
            if tag == "date":
                header_cols = row[1:]
                continue
            if header_cols is None:
                continue  # provenance banner line
            d = None
            for fmt in TSS_DATE_FMTS:
                try:
                    d = datetime.strptime(row[0], fmt)
                    break
                except ValueError:
                    continue
            if d is None:
                continue
            if gauge_index >= len(row) - 1:
                raise ValueError(
                    f"Gauge index {gauge_index} out of range in {csv_path}: "
                    f"{len(row) - 1} gauge column(s) present"
                )
            try:
                values.append(float(row[1 + gauge_index]))
            except ValueError:
                values.append(np.nan)
            dates.append(d)

    if not dates:
        raise ValueError(f"No data rows parsed from TSS file {csv_path}")

    gauge_name = (header_cols[gauge_index]
                  if header_cols and gauge_index < len(header_cols)
                  else f"G{gauge_index + 1}")
    metadata = {
        "variable": os.path.basename(csv_path).rsplit("_", 1)[0],
        "units": "m3/s",
        "long_name": f"CWatM TSS gauge {gauge_name}",
        "shape": [len(values)],
        "source": "tss_csv",
        "gauge": gauge_name,
        "xloc": xloc[gauge_index] if xloc and gauge_index < len(xloc) else None,
        "yloc": yloc[gauge_index] if yloc and gauge_index < len(yloc) else None,
    }
    return dates, np.array(values, dtype=float), metadata


def find_output_files(output_dir):
    """Discover CWatM output files and their variables."""
    import glob

    files = {}
    for csv_path in sorted(glob.glob(os.path.join(output_dir, "*.csv"))):
        basename = os.path.basename(csv_path)
        stem = basename[:-4]
        # `<var>_<aggregation>` — the TSS variable is everything before the suffix
        varname = stem.rsplit("_", 1)[0] if "_" in stem else stem
        files[basename] = {
            "path": csv_path,
            "kind": "tss_csv",
            "variables": [{
                "name": varname,
                "shape": [],
                "units": "unknown",
                "long_name": varname,
            }],
            "n_timesteps": 0,
        }

    for nc_path in sorted(glob.glob(os.path.join(output_dir, "*.nc"))):
        basename = os.path.basename(nc_path)
        try:
            ds = nc.Dataset(nc_path)
            variables = []
            for vname in ds.variables:
                if vname not in ("time", "lat", "lon", "latitude", "longitude", "x", "y"):
                    var = ds.variables[vname]
                    variables.append({
                        "name": vname,
                        "shape": list(var.shape),
                        "units": getattr(var, "units", "unknown"),
                        "long_name": getattr(var, "long_name", vname),
                    })
            has_time = "time" in ds.variables
            n_times = len(ds.variables["time"]) if has_time else 0
            ds.close()
            files[basename] = {
                "path": nc_path,
                "kind": "netcdf",
                "variables": variables,
                "n_timesteps": n_times,
            }
        except Exception as e:
            files[basename] = {"path": nc_path, "kind": "netcdf", "error": str(e)}

    return files


def extract_timeseries(nc_path, variable, gauge_index=0):
    """
    Extract time series from a CWatM output NetCDF.

    Returns
    -------
    dates : list of datetime
    values : np.ndarray
    metadata : dict
    """
    ds = nc.Dataset(nc_path)

    # Get time dimension
    if "time" not in ds.variables:
        ds.close()
        raise ValueError(f"No time dimension in {nc_path}")

    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units,
                        getattr(time_var, "calendar", "standard"))

    # Find the data variable.  CWatM suffixes the NetCDF variable with its
    # temporal aggregation (`discharge` -> `discharge_monthavg`), so an exact
    # match usually fails; fall back to the same prefix/substring rule that
    # find_output_files() uses to select the file, otherwise discovery and
    # extraction disagree and a file that WAS matched raises "not found".
    if variable not in ds.variables:
        found = None
        for vname in ds.variables:
            if vname.lower() == variable.lower():
                found = vname
                break
        if found is None:
            coords = ("time", "lat", "lon", "latitude", "longitude", "x", "y")
            for vname in ds.variables:
                if vname in coords:
                    continue
                if vname.lower().startswith(variable.lower()) or \
                   variable.lower() in vname.lower():
                    found = vname
                    break
        if found is None:
            available = [v for v in ds.variables if v not in ("time", "lat", "lon")]
            ds.close()
            raise ValueError(
                f"Variable '{variable}' not found. Available: {available}"
            )
        variable = found

    data_var = ds.variables[variable]
    data = data_var[:]

    metadata = {
        "variable": variable,
        "units": getattr(data_var, "units", "unknown"),
        "long_name": getattr(data_var, "long_name", variable),
        "shape": list(data.shape),
    }

    # Extract based on dimensions
    if data.ndim == 1:
        # Single gauge time series
        values = data
    elif data.ndim == 2:
        # (time, gauge) — extract specific gauge
        if gauge_index >= data.shape[1]:
            ds.close()
            raise ValueError(
                f"Gauge index {gauge_index} out of range. "
                f"Available gauges: 0 to {data.shape[1]-1}"
            )
        values = data[:, gauge_index]
    elif data.ndim == 3:
        # (time, lat, lon) — spatial data, need coordinates
        values = data  # Return full spatial data
    else:
        values = data

    ds.close()

    dates = [datetime(t.year, t.month, t.day) if hasattr(t, "year") else t
             for t in times]
    return dates, np.array(values), metadata


def compute_hydrological_metrics(sim, obs, dates=None):
    """
    Compute standard hydrological performance metrics.

    Parameters
    ----------
    sim : np.ndarray
        Simulated values
    obs : np.ndarray
        Observed values
    dates : list of datetime, optional

    Returns
    -------
    dict with metrics: NSE, KGE, PBIAS, RMSE, R², MAE
    """
    # Remove NaN pairs
    mask = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[mask]
    obs = obs[mask]

    if len(sim) < 10:
        return {"error": f"Too few valid data points: {len(sim)}"}

    # Delegate to the shared, deterministic implementation so this KI reports
    # the same numbers as every other model KI.  Hand-rolling NSE/KGE here
    # duplicated ki_tools_common and could drift from it silently.
    from ki_tools_common.metrics import all_metrics

    m = all_metrics(obs, sim)
    r = float(m["r"])

    return {
        "NSE": round(float(m["NSE"]), 4),
        "KGE": round(float(m["KGE"]), 4),
        "PBIAS": round(float(m["PBIAS"]), 2),
        "RMSE": round(float(m["RMSE"]), 4),
        "R2": round(r ** 2, 4),
        "R": round(r, 4),
        "MAE": round(float(np.mean(np.abs(sim - obs))), 4),
        "mean_sim": round(float(np.mean(sim)), 4),
        "mean_obs": round(float(np.mean(obs)), 4),
        "n_points": int(len(sim)),
    }


# Sentinels used by the Chinese gauge archives (china_gaugeflux) and by GRDC.
OBS_MISSING = (-99.0, -999.0, -9999.0, -99.99, -999.99)
OBS_DATE_KEYS = ("date", "dates", "datetime", "time", "day", "ymd")
OBS_VALUE_KEYS = ("q", "discharge", "discharge_m3s", "streamflow", "flow",
                  "value", "obs", "runoff")


def read_observed_csv(csv_path):
    """Read observed discharge from a delimited text file.

    Handles both plain `date,value` CSV and the china_gaugeflux archive layout
    (`/mnt/datasets/china_water_level/<basin>txt/<gauge>.txt`), which is
    TAB-separated with columns `stcd dates z Q name`, non-zero-padded dates
    (`1950-1-1`) and -99 as the missing-value sentinel.  The original
    comma-only, column-0/1 reader silently produced ZERO usable rows on those
    files — every row parsed as a single field, so no gauge in china_gaugeflux
    could be scored through this tool.
    """
    dates = []
    values = []

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]

    if not lines:
        return dates, np.array(values)

    # Sniff the delimiter from the header: whichever splits it into most fields.
    header_line = lines[0]
    delim = max(("\t", ",", ";", None),
                key=lambda d: len(header_line.split(d)))
    header = [h.strip().lower() for h in header_line.split(delim)]

    date_col, val_col = None, None
    for i, h in enumerate(header):
        if date_col is None and h in OBS_DATE_KEYS:
            date_col = i
        if val_col is None and h in OBS_VALUE_KEYS:
            val_col = i
    has_header = date_col is not None and val_col is not None
    if not has_header:
        # No recognisable header -> assume the legacy date,value layout and
        # treat line 0 as a header row to skip.
        date_col, val_col = 0, 1

    for line in lines[1:]:
        row = [c.strip() for c in line.split(delim)]
        if len(row) <= max(date_col, val_col):
            continue
        d = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d"):
            try:
                d = datetime.strptime(row[date_col], fmt)
                break
            except ValueError:
                continue
        if d is None:
            continue
        try:
            val = float(row[val_col])
        except ValueError:
            continue
        if val in OBS_MISSING or val <= -99.0:
            continue
        dates.append(d)
        values.append(val)

    return dates, np.array(values)


def write_csv(dates, values, output_path, variable="value", metadata=None):
    """Write time series to CSV."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Write header comment with metadata
        if metadata:
            f.write(f"# Variable: {metadata.get('variable', variable)}\n")
            f.write(f"# Units: {metadata.get('units', 'unknown')}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")

        writer.writerow(["date", variable])
        for date, val in zip(dates, values):
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            writer.writerow([date_str, f"{val:.6f}"])

    return output_path


def validate_outputs(dates, values, variable):
    """Post-extraction validation."""
    warnings = []

    if len(values) == 0:
        warnings.append(f"No data extracted for variable '{variable}'")
        return warnings

    if np.all(np.isnan(values)):
        warnings.append(f"All NaN values for variable '{variable}'")

    if variable.lower() == "discharge":
        max_q = float(np.nanmax(values))
        min_q = float(np.nanmin(values))
        if max_q > 1e6:
            warnings.append(
                f"UNIT TRAP: Max discharge = {max_q:.1f} m³/s — extremely high. "
                f"Check precipitation unit conversion."
            )
        if min_q < -0.01:
            warnings.append(f"Negative discharge: min = {min_q:.4f} m³/s")
        if max_q == 0:
            warnings.append("All discharge values are 0. Model may not be generating runoff.")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Parse CWatM output files")
    parser.add_argument("--output_dir", required=True, help="CWatM output directory")
    parser.add_argument("--variable", default="discharge", help="Variable to extract")
    parser.add_argument("--gauge_index", type=int, default=0, help="Gauge index (0-based)")
    parser.add_argument("--all_gauges", action="store_true", help="Extract all gauges")
    parser.add_argument("--csv_out", default=None, help="Output CSV path")
    parser.add_argument("--summary", action="store_true", help="Print summary of all outputs")
    parser.add_argument("--compute_metrics", action="store_true", help="Compute NSE/KGE metrics")
    parser.add_argument("--observed_csv", default=None, help="Observed data CSV for metrics")
    parser.add_argument("--aggregation", default="daily",
                        choices=["daily", "monthavg", "monthtot", "annualavg",
                                 "annualtot", "totalend"],
                        help="Preferred temporal aggregation of the output to read "
                             "(default: daily — the OUT_TSS_Daily gauge series)")

    args = parser.parse_args()

    print("=== CWatM Output Parser ===")
    validate_inputs(args)

    # Summary mode
    if args.summary:
        files = find_output_files(args.output_dir)
        print(f"\nFound {len(files)} output files:")
        for fname, info in files.items():
            if "error" in info:
                print(f"  {fname}: ERROR - {info['error']}")
            else:
                vars_str = ", ".join(v["name"] for v in info["variables"])
                print(f"  {fname}: {info['n_timesteps']} timesteps, vars: [{vars_str}]")
        print(json.dumps(files, indent=2, default=str))
        return

    # Find the output file containing our variable.
    #
    # Selection is AGGREGATION-AWARE.  A plain sorted glob puts
    # `discharge_annualavg.nc` (a 3-D map with one value per year) ahead of
    # `discharge_daily.csv` (the gauge time series you actually want to score),
    # so scoring silently got the wrong file.  Rank candidates by how well they
    # match --aggregation, preferring the gauge TSS over a gridded map.
    files = find_output_files(args.output_dir)
    agg = args.aggregation.lower()
    agg_order = [agg] + [a for a in ("daily", "monthavg", "monthtot",
                                     "annualavg", "annualtot", "totalend")
                         if a != agg]

    def rank(fname, info):
        stem = os.path.basename(fname).rsplit(".", 1)[0].lower()
        suffix = stem.rsplit("_", 1)[1] if "_" in stem else ""
        try:
            agg_rank = agg_order.index(suffix)
        except ValueError:
            agg_rank = len(agg_order)
        kind_rank = 0 if info.get("kind") == "tss_csv" else 1
        return (agg_rank, kind_rank, fname)

    candidates = []
    for fname, info in files.items():
        for v in info.get("variables", []):
            if v["name"].lower() == args.variable.lower() or \
               args.variable.lower() in v["name"].lower():
                candidates.append((rank(fname, info), fname, info))
                break

    target_file, target_kind = None, None
    if candidates:
        candidates.sort(key=lambda c: c[0])
        target_file = candidates[0][2]["path"]
        target_kind = candidates[0][2].get("kind")

    if target_file is None:
        # Try the most likely filename
        import glob
        candidates = glob.glob(
            os.path.join(args.output_dir, f"*{args.variable}*.nc")
        )
        if candidates:
            target_file = candidates[0]
            target_kind = "tss_csv" if target_file.endswith(".csv") else "netcdf"
        else:
            print(f"ERROR: Cannot find output file containing variable '{args.variable}'")
            print(f"Available files: {list(files.keys())}")
            sys.exit(1)

    print(f"Reading from: {target_file}")

    # Extract time series
    if target_kind == "tss_csv" or target_file.endswith(".csv"):
        dates, values, metadata = read_tss_csv(target_file, args.gauge_index)
    else:
        dates, values, metadata = extract_timeseries(
            target_file, args.variable, args.gauge_index
        )

    if values.ndim > 1:
        print(f"Spatial data extracted: shape = {values.shape}")
        print(f"Use --gauge_index to extract a point time series")
        return

    # Validate extracted data
    warnings = validate_outputs(dates, values, args.variable)
    for w in warnings:
        print(f"  WARNING: {w}")

    # Print statistics
    print(f"\n  Variable: {metadata['variable']} [{metadata['units']}]")
    print(f"  Period: {dates[0]} to {dates[-1]} ({len(dates)} timesteps)")
    print(f"  Min: {np.nanmin(values):.4f}")
    print(f"  Max: {np.nanmax(values):.4f}")
    print(f"  Mean: {np.nanmean(values):.4f}")

    # Write CSV
    if args.csv_out:
        write_csv(dates, values, args.csv_out, args.variable, metadata)
        print(f"\n  CSV written to: {args.csv_out}")

    # Compute metrics against observed data
    if args.compute_metrics and args.observed_csv:
        obs_dates, obs_values = read_observed_csv(args.observed_csv)
        print(f"\n  Observed data: {len(obs_dates)} points from {args.observed_csv}")

        # Align dates
        sim_dict = {d.strftime("%Y-%m-%d"): v for d, v in zip(dates, values)}
        obs_dict = {d.strftime("%Y-%m-%d"): v for d, v in zip(obs_dates, obs_values)}
        common_dates = sorted(set(sim_dict.keys()) & set(obs_dict.keys()))

        if len(common_dates) < 10:
            print(f"  ERROR: Only {len(common_dates)} overlapping dates")
        else:
            sim_aligned = np.array([sim_dict[d] for d in common_dates])
            obs_aligned = np.array([obs_dict[d] for d in common_dates])

            metrics = compute_hydrological_metrics(sim_aligned, obs_aligned)
            print(f"\n  === Performance Metrics ({len(common_dates)} days) ===")
            for k, v in metrics.items():
                print(f"  {k}: {v}")

            print(json.dumps({"status": "success", "metrics": metrics}, indent=2))

    result = {
        "status": "success",
        "variable": metadata["variable"],
        "units": metadata["units"],
        "n_timesteps": len(dates),
        "min": float(np.nanmin(values)),
        "max": float(np.nanmax(values)),
        "mean": float(np.nanmean(values)),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
