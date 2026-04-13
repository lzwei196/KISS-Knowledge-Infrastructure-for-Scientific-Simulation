#!/usr/bin/env python3
"""
convert_forcing.py — Convert global gridded meteorological data to DHSVM forcing format.

DHSVM expects one ASCII file per grid cell named data_<lat>_<lon> with columns:
  MM/DD/YYYY-HH  Tair(C)  Wind(m/s)  RH(%)  Swin(W/m2)  Lwin(W/m2)  Precip(m/step)

CRITICAL unit traps:
  - Precipitation must be in meters/timestep (NOT mm)
  - Temperature must be Celsius (NOT Kelvin)
  - Relative humidity must be percent 0-100 (NOT fraction 0-1)

Usage:
  python convert_forcing.py --input-dir /data/cmfd --output-dir /dhsvm/forcing \\
      --source-format cmfd --timestep 3 --grid-decimal 5 \\
      --start-date 1970-10-01 --end-date 1971-10-01

  python convert_forcing.py --input-csv /data/era5_merged.csv --output-dir /dhsvm/forcing \\
      --source-format era5 --timestep 3 --grid-decimal 5 \\
      --start-date 2000-01-01 --end-date 2001-01-01
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# Source format specifications
# --------------------------------------------------------------------------- #
SOURCE_SPECS = {
    "cmfd": {
        "temp_unit": "C",        # already Celsius
        "rh_unit": "percent",    # already 0-100
        "wind_unit": "m/s",
        "sw_unit": "W/m2",
        "lw_unit": "W/m2",
        "precip_unit": "mm/hr",
        "timestep_hr": 3,
    },
    "era5": {
        "temp_unit": "K",        # Kelvin → must subtract 273.15
        "rh_unit": "fraction",   # 0-1 → must multiply by 100
        "wind_unit": "m/s",
        "sw_unit": "W/m2",
        "lw_unit": "W/m2",
        "precip_unit": "m/hr",
        "timestep_hr": 1,
    },
    "mswx": {
        "temp_unit": "C",
        "rh_unit": "percent",
        "wind_unit": "m/s",
        "sw_unit": "W/m2",
        "lw_unit": "W/m2",
        "precip_unit": "mm/3hr",
        "timestep_hr": 3,
    },
}


def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if args.input_dir and not os.path.isdir(args.input_dir):
        errors.append(f"Input directory does not exist: {args.input_dir}")
    if args.input_csv and not os.path.isfile(args.input_csv):
        errors.append(f"Input CSV does not exist: {args.input_csv}")
    if not args.input_dir and not args.input_csv:
        errors.append("Must provide either --input-dir or --input-csv")

    if args.source_format not in SOURCE_SPECS:
        errors.append(f"Unknown source format '{args.source_format}'. "
                       f"Valid: {list(SOURCE_SPECS.keys())}")

    if args.timestep not in [1, 2, 3, 6, 12, 24]:
        errors.append(f"Timestep {args.timestep} hr is unusual for DHSVM. "
                       "Common values: 1, 2, 3, 6, 24")

    if args.grid_decimal < 1 or args.grid_decimal > 10:
        errors.append(f"Grid decimal {args.grid_decimal} out of range [1, 10]")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Invalid date format: {e}. Use YYYY-MM-DD.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def convert_temperature(values, from_unit):
    """Convert temperature to Celsius."""
    if from_unit == "K":
        converted = values - 273.15
        if np.any(converted > 60) or np.any(converted < -80):
            print("WARNING: Temperature out of physical range after "
                  "K→C conversion", file=sys.stderr)
        return converted
    elif from_unit == "C":
        return values
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def convert_rh(values, from_unit):
    """Convert relative humidity to percent (0-100)."""
    if from_unit == "fraction":
        converted = values * 100.0
        if np.any(converted > 100.5):
            print("WARNING: RH > 100% after fraction→percent conversion",
                  file=sys.stderr)
        return np.clip(converted, 0.0, 100.0)
    elif from_unit == "percent":
        return np.clip(values, 0.0, 100.0)
    else:
        raise ValueError(f"Unknown RH unit: {from_unit}")


def convert_wind(values, from_unit):
    """Convert wind speed to m/s."""
    if from_unit == "km/hr":
        return values / 3.6
    elif from_unit == "m/s":
        return values
    else:
        raise ValueError(f"Unknown wind unit: {from_unit}")


def convert_radiation(values, from_unit):
    """Convert radiation to W/m2."""
    if from_unit == "MJ/m2/day":
        return values * 1.0e6 / 86400.0
    elif from_unit == "W/m2":
        return values
    else:
        raise ValueError(f"Unknown radiation unit: {from_unit}")


def convert_precip(values, from_unit, source_dt_hr, target_dt_hr):
    """Convert precipitation to meters per target timestep.

    CRITICAL: DHSVM expects meters/timestep, not mm.
    """
    # First convert to mm/hr
    if from_unit == "mm/hr":
        mm_per_hr = values
    elif from_unit == "mm/3hr":
        mm_per_hr = values / 3.0
    elif from_unit == "m/hr":
        mm_per_hr = values * 1000.0
    elif from_unit == "mm/day":
        mm_per_hr = values / 24.0
    else:
        raise ValueError(f"Unknown precip unit: {from_unit}")

    # Convert mm/hr → m/timestep
    m_per_step = mm_per_hr * target_dt_hr / 1000.0

    if np.any(m_per_step > 0.1):
        print("WARNING: Precipitation > 100 mm/step detected. Check units.",
              file=sys.stderr)
    if np.any(m_per_step < 0):
        print("WARNING: Negative precipitation detected. Setting to 0.",
              file=sys.stderr)
        m_per_step = np.maximum(m_per_step, 0.0)

    return m_per_step


def generate_timestamps(start_date, end_date, timestep_hr):
    """Generate DHSVM-format timestamps: MM/DD/YYYY-HH."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dt = timedelta(hours=timestep_hr)

    timestamps = []
    current = start
    while current < end:
        ts = current.strftime("%m/%d/%Y-") + f"{current.hour:02d}"
        timestamps.append(ts)
        current += dt
    return timestamps


def process_csv(args, spec):
    """Process a single merged CSV file with all grid cells."""
    import pandas as pd

    df = pd.read_csv(args.input_csv)

    required_cols = ["lat", "lon", "datetime", "tair", "rh", "wind",
                     "swdown", "lwdown", "precip"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(json.dumps({"status": "error",
                           "errors": [f"Missing columns: {missing}"]}))
        sys.exit(1)

    target_dt = args.timestep
    source_dt = spec["timestep_hr"]

    # Convert units
    df["tair_c"] = convert_temperature(df["tair"].values, spec["temp_unit"])
    df["rh_pct"] = convert_rh(df["rh"].values, spec["rh_unit"])
    df["wind_ms"] = convert_wind(df["wind"].values, spec["wind_unit"])
    df["sw_wm2"] = convert_radiation(df["swdown"].values, spec["sw_unit"])
    df["lw_wm2"] = convert_radiation(df["lwdown"].values, spec["lw_unit"])
    df["precip_m"] = convert_precip(df["precip"].values, spec["precip_unit"],
                                     source_dt, target_dt)

    # Group by grid cell and write files
    os.makedirs(args.output_dir, exist_ok=True)
    fmt_str = f"%.{args.grid_decimal}f"
    cells_written = 0

    for (lat, lon), group in df.groupby(["lat", "lon"]):
        lat_str = f"{lat:.{args.grid_decimal}f}"
        lon_str = f"{lon:.{args.grid_decimal}f}"
        fname = f"data_{lat_str}_{lon_str}"
        fpath = os.path.join(args.output_dir, fname)

        with open(fpath, "w") as f:
            for _, row in group.iterrows():
                dt_obj = datetime.strptime(str(row["datetime"]),
                                           "%Y-%m-%d %H:%M:%S")
                ts = dt_obj.strftime("%m/%d/%Y-") + f"{dt_obj.hour:02d}"
                f.write(f"{ts}\t{row['tair_c']:.4f}\t{row['wind_ms']:.4f}\t"
                        f"{row['rh_pct']:.4f}\t{row['sw_wm2']:.4f}\t"
                        f"{row['lw_wm2']:.4f}\t{row['precip_m']:.6f}\n")
        cells_written += 1

    return {
        "status": "success",
        "cells_written": cells_written,
        "output_dir": args.output_dir,
        "timestep_hr": target_dt,
        "grid_decimal": args.grid_decimal,
    }


def process_directory(args, spec):
    """Process individual forcing files from a directory."""
    os.makedirs(args.output_dir, exist_ok=True)

    input_files = sorted(Path(args.input_dir).glob("data_*"))
    if not input_files:
        input_files = sorted(Path(args.input_dir).glob("*.csv"))
    if not input_files:
        return {"status": "error",
                "errors": ["No data_* or *.csv files found in input directory"]}

    target_dt = args.timestep
    source_dt = spec["timestep_hr"]
    cells_written = 0

    for fpath in input_files:
        try:
            data = np.loadtxt(str(fpath), dtype=str)
        except Exception as e:
            print(f"WARNING: Could not read {fpath}: {e}", file=sys.stderr)
            continue

        if data.ndim == 1:
            data = data.reshape(1, -1)

        timestamps = data[:, 0]
        values = data[:, 1:].astype(float)

        if values.shape[1] < 6:
            print(f"WARNING: {fpath} has only {values.shape[1]} columns, "
                  "expected 6", file=sys.stderr)
            continue

        tair = convert_temperature(values[:, 0], spec["temp_unit"])
        rh = convert_rh(values[:, 1], spec["rh_unit"])
        wind = convert_wind(values[:, 2], spec["wind_unit"])
        sw = convert_radiation(values[:, 3], spec["sw_unit"])
        lw = convert_radiation(values[:, 4], spec["lw_unit"])
        precip = convert_precip(values[:, 5], spec["precip_unit"],
                                source_dt, target_dt)

        outpath = os.path.join(args.output_dir, fpath.name)
        with open(outpath, "w") as f:
            for i in range(len(timestamps)):
                f.write(f"{timestamps[i]}\t{tair[i]:.4f}\t{wind[i]:.4f}\t"
                        f"{rh[i]:.4f}\t{sw[i]:.4f}\t{lw[i]:.4f}\t"
                        f"{precip[i]:.6f}\n")
        cells_written += 1

    return {
        "status": "success",
        "cells_written": cells_written,
        "output_dir": args.output_dir,
        "timestep_hr": target_dt,
        "grid_decimal": args.grid_decimal,
    }


def validate_outputs(result):
    """Validate output results."""
    if result.get("status") != "success":
        return result

    warnings = []
    if result.get("cells_written", 0) == 0:
        warnings.append("No grid cells were written. Check input data.")
    if result.get("cells_written", 0) < 5:
        warnings.append(f"Only {result['cells_written']} cells written. "
                        "Verify basin coverage.")

    # Check a sample output file
    output_dir = result.get("output_dir", "")
    if os.path.isdir(output_dir):
        sample_files = sorted(Path(output_dir).glob("data_*"))[:1]
        for sf in sample_files:
            try:
                data = np.loadtxt(str(sf), dtype=str)
                if data.ndim == 1:
                    data = data.reshape(1, -1)
                vals = data[:, 1:].astype(float)
                # Check temperature range
                if np.any(vals[:, 0] > 60) or np.any(vals[:, 0] < -80):
                    warnings.append(f"Temperature out of range in {sf.name}")
                # Check precip is in meters (should be small)
                if np.any(vals[:, 5] > 0.1):
                    warnings.append(f"Precip > 100mm/step in {sf.name}. "
                                    "Likely still in mm?")
                # Check RH is percent
                if np.all(vals[:, 1] < 1.1) and np.any(vals[:, 1] > 0):
                    warnings.append(f"RH all < 1.1 in {sf.name}. "
                                    "Likely fraction, not percent?")
            except Exception:
                pass

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert global met data to DHSVM forcing format")
    parser.add_argument("--input-dir", help="Directory with source forcing files")
    parser.add_argument("--input-csv", help="Single CSV with all grid cells")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for DHSVM forcing files")
    parser.add_argument("--source-format", required=True,
                        choices=list(SOURCE_SPECS.keys()),
                        help="Source data format")
    parser.add_argument("--timestep", type=int, default=3,
                        help="DHSVM timestep in hours (default: 3)")
    parser.add_argument("--grid-decimal", type=int, default=5,
                        help="Decimal places in grid file names (default: 5)")
    parser.add_argument("--start-date", required=True,
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True,
                        help="End date YYYY-MM-DD")
    parser.add_argument("--output", help="Output JSON report file")
    args = parser.parse_args()

    validate_inputs(args)

    spec = SOURCE_SPECS[args.source_format]
    if args.input_csv:
        result = process_csv(args, spec)
    else:
        result = process_directory(args, spec)

    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
