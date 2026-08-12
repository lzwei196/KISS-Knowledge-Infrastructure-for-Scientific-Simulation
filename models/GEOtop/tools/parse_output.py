#!/usr/bin/env python3
"""
parse_output.py - Extract GEOtop model outputs to tidy CSV format.

Parses the various output file formats produced by GEOtop:
  - Basin-averaged time series (output-tabs/basin*.txt)
  - Point time series (output-tabs/point*.txt)
  - Soil temperature/moisture profiles (output-tabs/soilTz*.txt, thetaliq*.txt)
  - Snow profiles (output-tabs/snowDepth*.txt, snowT*.txt)
  - Discharge time series (output-tabs/discharge*.txt)

All outputs are converted to tidy (long-format) CSV with standardized columns.

Usage:
    python parse_output.py \\
        --sim-dir /path/to/simulation/folder \\
        --output-type basin \\
        --variables "Tair,LE,H,SWin,LWin,Evap_surface,Prain_below_canopy" \\
        --output /path/to/results/basin_timeseries.csv

    python parse_output.py \\
        --sim-dir /path/to/simulation/folder \\
        --output-type soil_profile \\
        --point 1 \\
        --variables "temperature,liquid_water" \\
        --output /path/to/results/soil_profiles.csv

    python parse_output.py \\
        --sim-dir /path/to/simulation/folder \\
        --output-type summary \\
        --output /path/to/results/run_summary.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

NODATA = -9999
GEOTOP_DATE_FMT = "%d/%m/%Y %H:%M"


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    sim_dir = Path(args.sim_dir)
    if not sim_dir.is_dir():
        errors.append(f"Simulation directory not found: {args.sim_dir}")

    output_dir = sim_dir / "output-tabs"
    if not output_dir.is_dir():
        errors.append(f"Output directory not found: {output_dir}")

    if args.output_type not in ("basin", "point", "soil_profile", "snow_profile", "discharge", "summary"):
        errors.append(f"Unknown output type: {args.output_type}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_geotop_header(header_line):
    """Parse GEOtop column headers, extracting variable name and unit.

    GEOtop headers look like: "Tair[C]" or "LE[W/m2]" or "Date12[DDMMYYYYhhmm]"
    Returns list of (name, unit) tuples.
    """
    cols = []
    for col in header_line:
        col = col.strip().strip('"')
        match = re.match(r"(.+)\[(.+)\]", col)
        if match:
            cols.append((match.group(1), match.group(2)))
        else:
            cols.append((col, ""))
    return cols


def find_output_files(sim_dir, pattern):
    """Find output files matching a glob pattern."""
    output_dir = Path(sim_dir) / "output-tabs"
    files = sorted(output_dir.glob(pattern))
    return files


def read_basin_output(sim_dir, variables=None):
    """Read basin-averaged time series output.

    File format: CSV with header row containing column[unit] names.
    """
    files = find_output_files(sim_dir, "basin*.txt")
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as e:
            print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
            continue

        # Parse headers
        parsed = parse_geotop_header(df.columns)
        col_map = {}
        units = {}
        for (name, unit), orig_col in zip(parsed, df.columns):
            col_map[orig_col] = name
            units[name] = unit

        df = df.rename(columns=col_map)

        # Parse date column
        date_cols = [c for c in df.columns if "Date" in c or "date" in c]
        if date_cols:
            try:
                df["datetime"] = pd.to_datetime(df[date_cols[0]], format=GEOTOP_DATE_FMT)
            except Exception:
                # Try alternate formats
                df["datetime"] = pd.to_datetime(df[date_cols[0]], dayfirst=True)

        # Filter variables if specified
        if variables:
            var_list = [v.strip() for v in variables.split(",")]
            keep_cols = ["datetime"] + [c for c in df.columns if any(v in c for v in var_list)]
            df = df[[c for c in keep_cols if c in df.columns]]

        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    result = pd.concat(dfs, ignore_index=True)

    # Replace nodata
    result = result.replace(NODATA, np.nan)

    return result


def read_point_output(sim_dir, point_id=1, variables=None):
    """Read point-specific time series output."""
    pattern = f"point{point_id:04d}*.txt"
    files = find_output_files(sim_dir, pattern)
    if not files:
        # Try without zero-padding
        pattern = f"point{point_id}*.txt"
        files = find_output_files(sim_dir, pattern)

    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception:
            continue

        parsed = parse_geotop_header(df.columns)
        col_map = {}
        for (name, unit), orig_col in zip(parsed, df.columns):
            col_map[orig_col] = name
        df = df.rename(columns=col_map)

        date_cols = [c for c in df.columns if "Date" in c]
        if date_cols:
            try:
                df["datetime"] = pd.to_datetime(df[date_cols[0]], format=GEOTOP_DATE_FMT)
            except Exception:
                df["datetime"] = pd.to_datetime(df[date_cols[0]], dayfirst=True)

        if variables:
            var_list = [v.strip() for v in variables.split(",")]
            keep_cols = ["datetime"] + [c for c in df.columns if any(v in c for v in var_list)]
            df = df[[c for c in keep_cols if c in df.columns]]

        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True).replace(NODATA, np.nan)


def read_soil_profile(sim_dir, point_id=1, variables=None):
    """Read soil profile outputs (matrix format: rows=time, cols=layers).

    Files: soilTzXXXX.txt (temperature), thetaliqXXXX.txt (water content),
           thetaiceXXXX.txt (ice content), psizXXXX.txt (matric potential)
    """
    profile_types = {
        "temperature": ("soilTz", "C"),
        "liquid_water": ("thetaliq", "-"),
        "ice_content": ("thetaice", "-"),
        "matric_potential": ("psiz", "mm"),
    }

    all_dfs = []

    for var_name, (prefix, unit) in profile_types.items():
        if variables and var_name not in variables:
            continue

        pattern = f"{prefix}{point_id:04d}*.txt"
        files = find_output_files(sim_dir, pattern)
        if not files:
            pattern = f"{prefix}{point_id}*.txt"
            files = find_output_files(sim_dir, pattern)

        for f in files:
            try:
                df = pd.read_csv(f)
            except Exception:
                continue

            # First columns are date/time, remaining are layer values
            date_cols = [c for c in df.columns if "Date" in c or "date" in c]
            if not date_cols:
                continue

            try:
                dates = pd.to_datetime(df[date_cols[0]], format=GEOTOP_DATE_FMT)
            except Exception:
                dates = pd.to_datetime(df[date_cols[0]], dayfirst=True)

            # Layer columns are everything except the leading metadata columns.
            #
            # BUGFIX (2026-07-21, GEOtop NCP MODIS-LST real case): `IDpoint`
            # was NOT in the skip set, so the point-id column was emitted as
            # "layer 1" -- a fake layer holding the constant 1.0 -- and EVERY
            # real soil layer was shifted one index deeper. A profile
            # validation against, say, a 5 cm soil-moisture probe therefore
            # silently read the 15 cm model layer, and any depth-weighted
            # storage sum picked up a bogus 1.0 * Dz term. GEOtop point
            # profiles have exactly these six leading columns:
            #   Date12, JulianDayFromYear0, TimeFromStart, Simulation_Period,
            #   Run, IDpoint
            skip = {c for c in df.columns if "Date" in c or "Julian" in c or
                    "Time" in c or "Simulation" in c or "Run" in c or
                    "IDpoint" in c or "IDbasin" in c}
            layer_cols = [c for c in df.columns if c not in skip]

            # The layer column HEADERS are the layer mid-point depths in mm
            # (e.g. "5.000000", "15.000000", ...). Carry them through: depth,
            # not layer ordinal, is what a profile observation is matched on.
            for i, col in enumerate(layer_cols):
                try:
                    depth_mm = float(str(col).strip())
                except ValueError:
                    depth_mm = np.nan
                layer_df = pd.DataFrame({
                    "datetime": dates,
                    "variable": var_name,
                    "layer": i + 1,
                    "depth_mm": depth_mm,
                    "value": df[col].replace(NODATA, np.nan),
                    "unit": unit,
                })
                all_dfs.append(layer_df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def read_snow_profile(sim_dir, point_id=1):
    """Read snow layer profile outputs."""
    profile_types = {
        "snow_temperature": ("snowT", "C"),
        "snow_depth": ("snowDepth", "mm"),
        "snow_ice": ("snowIce", "kg/m2"),
        "snow_liquid": ("snowLiq", "kg/m2"),
    }

    all_dfs = []

    for var_name, (prefix, unit) in profile_types.items():
        pattern = f"{prefix}{point_id:04d}*.txt"
        files = find_output_files(sim_dir, pattern)

        for f in files:
            try:
                df = pd.read_csv(f)
            except Exception:
                continue

            date_cols = [c for c in df.columns if "Date" in c]
            if not date_cols:
                continue

            try:
                dates = pd.to_datetime(df[date_cols[0]], format=GEOTOP_DATE_FMT)
            except Exception:
                dates = pd.to_datetime(df[date_cols[0]], dayfirst=True)

            skip = {c for c in df.columns if "Date" in c or "Julian" in c or
                    "Time" in c or "Simulation" in c or "Run" in c}
            layer_cols = [c for c in df.columns if c not in skip]

            for i, col in enumerate(layer_cols):
                layer_df = pd.DataFrame({
                    "datetime": dates,
                    "variable": var_name,
                    "layer": i + 1,
                    "value": df[col].replace(NODATA, np.nan),
                    "unit": unit,
                })
                all_dfs.append(layer_df)

    if not all_dfs:
        return pd.DataFrame()

    return pd.concat(all_dfs, ignore_index=True)


def read_discharge(sim_dir):
    """Read discharge time series."""
    files = find_output_files(sim_dir, "discharge*.txt")
    if not files:
        return pd.DataFrame()

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception:
            continue

        parsed = parse_geotop_header(df.columns)
        col_map = {}
        for (name, unit), orig_col in zip(parsed, df.columns):
            col_map[orig_col] = name
        df = df.rename(columns=col_map)

        date_cols = [c for c in df.columns if "Date" in c]
        if date_cols:
            try:
                df["datetime"] = pd.to_datetime(df[date_cols[0]], format=GEOTOP_DATE_FMT)
            except Exception:
                df["datetime"] = pd.to_datetime(df[date_cols[0]], dayfirst=True)

        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True).replace(NODATA, np.nan)


def generate_summary(sim_dir):
    """Generate a JSON summary of the model run."""
    sim_path = Path(sim_dir)
    output_dir = sim_path / "output-tabs"

    summary = {
        "sim_dir": str(sim_dir),
        "success_marker": (sim_path / "_SUCCESSFUL_RUN").exists(),
        "output_files": {},
        "statistics": {},
    }

    if output_dir.is_dir():
        for f in sorted(output_dir.iterdir()):
            info = {"size_bytes": f.stat().st_size}
            if f.suffix == ".txt":
                with open(f) as fh:
                    lines = fh.readlines()
                info["n_lines"] = len(lines)
                info["n_data_rows"] = len(lines) - 1 if len(lines) > 0 else 0
            summary["output_files"][f.name] = info

    # Try to compute basic statistics from basin output
    try:
        basin = read_basin_output(sim_dir)
        if not basin.empty:
            stats = {}
            for col in basin.select_dtypes(include=[np.number]).columns:
                s = basin[col].dropna()
                if len(s) > 0:
                    stats[col] = {
                        "mean": round(float(s.mean()), 4),
                        "min": round(float(s.min()), 4),
                        "max": round(float(s.max()), 4),
                        "std": round(float(s.std()), 4),
                    }
            summary["statistics"]["basin"] = stats
    except Exception:
        pass

    return summary


def process(args):
    """Main processing: read and convert outputs."""
    if args.output_type == "basin":
        df = read_basin_output(args.sim_dir, args.variables)
    elif args.output_type == "point":
        df = read_point_output(args.sim_dir, args.point, args.variables)
    elif args.output_type == "soil_profile":
        df = read_soil_profile(args.sim_dir, args.point, args.variables)
    elif args.output_type == "snow_profile":
        df = read_snow_profile(args.sim_dir, args.point)
    elif args.output_type == "discharge":
        df = read_discharge(args.sim_dir)
    elif args.output_type == "summary":
        summary = generate_summary(args.sim_dir)
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(summary, f, indent=2)
        return summary
    else:
        print(json.dumps({"status": "error", "errors": [f"Unknown type: {args.output_type}"]}),
              file=sys.stderr)
        sys.exit(1)

    if df.empty:
        print(json.dumps({"status": "warning", "message": f"No data found for {args.output_type}"}),
              file=sys.stderr)
        return {"n_rows": 0}

    # Write output CSV
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df.to_csv(args.output, index=False, float_format="%.6f")
    return {"n_rows": len(df), "columns": list(df.columns)}


def validate_outputs(result, output_path):
    """Validate the generated output file."""
    warnings = []

    if isinstance(result, dict) and result.get("n_rows", 0) == 0:
        warnings.append("No data rows in output. Check model ran and produced output.")

    if os.path.isfile(output_path):
        size = os.path.getsize(output_path)
        if size == 0:
            warnings.append("Output file is empty.")

    output = {
        "status": "ok" if not warnings else "warning",
        "result": result,
        "warnings": warnings,
    }
    print(json.dumps(output, indent=2), file=sys.stderr)
    return output


def main():
    parser = argparse.ArgumentParser(description="Parse GEOtop model outputs to tidy CSV")
    parser.add_argument("--sim-dir", required=True, help="Simulation directory path")
    parser.add_argument("--output-type", required=True,
                        choices=["basin", "point", "soil_profile", "snow_profile", "discharge", "summary"],
                        help="Type of output to extract")
    parser.add_argument("--point", type=int, default=1, help="Point ID for point/profile outputs")
    parser.add_argument("--variables", default=None,
                        help="Comma-separated variable names to extract (default: all)")
    parser.add_argument("--output", required=True, help="Output file path")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    validate_outputs(result, args.output)

    if isinstance(result, dict):
        print(f"Wrote {result.get('n_rows', 'N/A')} rows to {args.output}")


if __name__ == "__main__":
    main()
