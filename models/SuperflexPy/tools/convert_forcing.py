#!/usr/bin/env python3
"""
convert_forcing.py — Convert forcing data to SuperflexPy input format.

Reads CSV/space-separated forcing files (precipitation, PET, temperature)
and outputs numpy-compatible arrays in mm/d with unit validation.

Supports common global datasets (ERA5, GSWP3, station data) and converts
units automatically. Outputs JSON with arrays or saves .npy files.

Usage:
    python convert_forcing.py --input forcing.csv --output forcing.json
    python convert_forcing.py --input forcing.csv --output forcing.json --p-col 6 --pet-col 7 --q-col 8
    python convert_forcing.py --input forcing.csv --output forcing.json --p-unit mm/h --pet-unit mm/month --timestep 1.0
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Unit conversion factors to mm/d
PRECIP_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "mm/h": 24.0,
    "mm/hr": 24.0,
    "mm/month": 1.0 / 30.4375,
    "m/d": 1000.0,
    "m/day": 1000.0,
    "m/s": 86400000.0,
    "kg/m2/s": 86400.0,
    "in/d": 25.4,
    "in/day": 25.4,
}

PET_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "mm/h": 24.0,
    "mm/hr": 24.0,
    "mm/month": 1.0 / 30.4375,
    "W/m2": 0.0353,  # approx: 1 W/m2 ~ 0.0353 mm/d latent heat
    "MJ/m2/d": 0.408,  # Penman conversion
    "m/d": 1000.0,
}

Q_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "m3/s": None,  # Requires catchment area
    "cms": None,
    "l/s": None,
}


def validate_inputs(args):
    """Validate command-line arguments and input file."""
    errors = []

    input_path = Path(args.input)
    if not input_path.exists():
        errors.append(f"Input file not found: {args.input}")
    if not input_path.suffix in (".csv", ".dat", ".txt", ".tsv"):
        errors.append(
            f"Unsupported file format: {input_path.suffix}. "
            "Expected .csv, .dat, .txt, or .tsv"
        )

    if args.p_unit not in PRECIP_CONVERSIONS:
        errors.append(
            f"Unknown precipitation unit: {args.p_unit}. "
            f"Supported: {list(PRECIP_CONVERSIONS.keys())}"
        )

    if args.pet_unit not in PET_CONVERSIONS:
        errors.append(
            f"Unknown PET unit: {args.pet_unit}. "
            f"Supported: {list(PET_CONVERSIONS.keys())}"
        )

    if args.timestep <= 0:
        errors.append(f"Timestep must be positive, got {args.timestep}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def process(args):
    """Read forcing file and convert to SuperflexPy format."""

    input_path = Path(args.input)

    # Detect separator
    with open(input_path, "r") as f:
        # Skip header lines
        for _ in range(args.header_lines):
            f.readline()
        sample_line = f.readline()

    if "," in sample_line:
        sep = ","
    else:
        sep = r"\s+"

    # Read data, skipping header
    try:
        data = np.genfromtxt(
            str(input_path),
            skip_header=args.header_lines,
            delimiter="," if sep == "," else None,
            filling_values=np.nan,
        )
    except Exception as e:
        return {"status": "error", "errors": [f"Failed to read data: {str(e)}"]}

    if data.ndim == 1:
        return {"status": "error", "errors": ["Data appears to have only one column"]}

    n_cols = data.shape[1]
    n_rows = data.shape[0]

    # Extract columns (0-indexed)
    p_col = args.p_col
    pet_col = args.pet_col
    q_col = args.q_col

    if p_col >= n_cols:
        return {
            "status": "error",
            "errors": [f"P column index {p_col} >= number of columns {n_cols}"],
        }

    # Extract precipitation
    P = data[:, p_col].copy()
    P_factor = PRECIP_CONVERSIONS[args.p_unit]
    P *= P_factor

    # Extract PET
    if pet_col is not None and pet_col < n_cols:
        PET = data[:, pet_col].copy()
        PET_factor = PET_CONVERSIONS[args.pet_unit]
        PET *= PET_factor
    else:
        PET = np.zeros(n_rows)
        print("WARNING: No PET column specified, using zeros", file=sys.stderr)

    # Extract observed Q if available
    Q_obs = None
    if q_col is not None and q_col < n_cols:
        Q_obs = data[:, q_col].copy()
        if args.q_unit in Q_CONVERSIONS and Q_CONVERSIONS[args.q_unit] is not None:
            Q_obs *= Q_CONVERSIONS[args.q_unit]
        elif args.q_unit in ("m3/s", "cms") and args.area is not None:
            # Convert m3/s to mm/d: Q * 86400 / (area_km2 * 1e6) * 1000
            Q_obs = Q_obs * 86400.0 / (args.area * 1e6) * 1000.0
        elif args.q_unit in ("l/s",) and args.area is not None:
            Q_obs = Q_obs * 86.4 / (args.area * 1e6) * 1000.0

    # Extract dates if available
    dates = None
    if args.year_col is not None and args.month_col is not None and args.day_col is not None:
        years = data[:, args.year_col].astype(int)
        months = data[:, args.month_col].astype(int)
        days = data[:, args.day_col].astype(int)
        dates = [f"{y:04d}-{m:02d}-{d:02d}" for y, m, d in zip(years, months, days)]

    result = {
        "status": "success",
        "n_timesteps": int(n_rows),
        "timestep_d": args.timestep,
        "units": {"P": "mm/d", "PET": "mm/d", "Q_obs": "mm/d"},
        "conversions_applied": {
            "P": f"{args.p_unit} -> mm/d (factor={P_factor})",
            "PET": f"{args.pet_unit} -> mm/d (factor={PET_CONVERSIONS[args.pet_unit]})",
        },
        "statistics": {
            "P_mean": float(np.nanmean(P)),
            "P_max": float(np.nanmax(P)),
            "P_total": float(np.nansum(P)),
            "PET_mean": float(np.nanmean(PET)),
            "PET_max": float(np.nanmax(PET)),
        },
        "P": P.tolist(),
        "PET": PET.tolist(),
    }

    if Q_obs is not None:
        result["Q_obs"] = Q_obs.tolist()
        result["statistics"]["Q_obs_mean"] = float(np.nanmean(Q_obs))

    if dates is not None:
        result["dates"] = dates

    return result


def validate_outputs(result):
    """Check output arrays for common silent errors."""
    if result["status"] != "success":
        return result

    warnings = []

    P = np.array(result["P"])
    PET = np.array(result["PET"])

    # Check for negative values
    if np.any(P < 0):
        warnings.append("WARNING: Negative precipitation values detected — check units")

    if np.any(PET < 0):
        warnings.append("WARNING: Negative PET values detected — check units")

    # Check for suspiciously large values (dt_001)
    if np.nanmax(P) > 500:
        warnings.append(
            f"WARNING: Max P = {np.nanmax(P):.1f} mm/d seems very high — "
            "verify unit conversion (dt_001)"
        )

    if np.nanmean(P) > 50:
        warnings.append(
            f"WARNING: Mean P = {np.nanmean(P):.1f} mm/d — "
            "likely wrong units (expected daily, got monthly?)"
        )

    # Check PET magnitude (dt_002)
    if np.nanmax(PET) > 30:
        warnings.append(
            f"WARNING: Max PET = {np.nanmax(PET):.1f} mm/d seems high — "
            "verify PET units (dt_002)"
        )

    # Check for all-zero arrays
    if np.all(P == 0):
        warnings.append("WARNING: All precipitation values are zero")

    # Check NaN fraction
    nan_frac = np.sum(np.isnan(P)) / len(P)
    if nan_frac > 0.1:
        warnings.append(f"WARNING: {nan_frac*100:.1f}% of P values are NaN")

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to SuperflexPy input format"
    )
    parser.add_argument("--input", type=str, required=True, help="Input forcing file path")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path (default: stdout)")
    parser.add_argument("--header-lines", type=int, default=7, help="Number of header lines to skip (default: 7)")
    parser.add_argument("--p-col", type=int, default=6, help="Precipitation column index (0-based, default: 6)")
    parser.add_argument("--pet-col", type=int, default=7, help="PET column index (0-based, default: 7)")
    parser.add_argument("--q-col", type=int, default=8, help="Observed Q column index (0-based, default: 8)")
    parser.add_argument("--year-col", type=int, default=0, help="Year column index")
    parser.add_argument("--month-col", type=int, default=1, help="Month column index")
    parser.add_argument("--day-col", type=int, default=2, help="Day column index")
    parser.add_argument("--p-unit", type=str, default="mm/d", help="Precipitation units")
    parser.add_argument("--pet-unit", type=str, default="mm/d", help="PET units")
    parser.add_argument("--q-unit", type=str, default="mm/d", help="Observed Q units")
    parser.add_argument("--timestep", type=float, default=1.0, help="Timestep in days (default: 1.0)")
    parser.add_argument("--area", type=float, default=None, help="Catchment area in km² (for Q unit conversion)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
