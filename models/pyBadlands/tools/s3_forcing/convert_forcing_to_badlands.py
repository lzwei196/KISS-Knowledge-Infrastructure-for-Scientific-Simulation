#!/usr/bin/env python3
"""
convert_forcing_to_badlands.py — Convert global climate/tectonic data to pyBadlands format.

Converts rainfall, sea-level, and tectonic displacement data from common global
datasets (ERA5, CMFD, CRU, SRTM) into the formats expected by pyBadlands XML
configuration.

Rainfall: Global datasets provide mm/day or mm/month → convert to m/year.
Sea-level: Datasets may use ka or Ma for time → convert to years.
Tectonic: Rate maps (m/year) → total displacement maps (m) for event duration.

Usage:
    python convert_forcing_to_badlands.py --type rainfall \\
        --input era5_precip.nc --output rain_map.csv \\
        --input-units mm/day --start 0 --end 1000000

    python convert_forcing_to_badlands.py --type sealevel \\
        --input sealevel_curve.csv --output sl_curve.csv \\
        --time-units ka

    python convert_forcing_to_badlands.py --type tectonic \\
        --input uplift_rate.csv --output uplift_total.csv \\
        --duration 1000000

CRITICAL:
    - Rainfall must be in m/year (NOT mm/day, NOT mm/year)
    - Sea-level time must be in years (NOT ka, NOT Ma)
    - Tectonic displacements must be TOTAL (m), not rates (m/year)
"""

import argparse
import json
import os
import sys
import numpy as np

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate inputs and fail fast with JSON error."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.type not in ("rainfall", "sealevel", "tectonic"):
        errors.append(f"Unknown type: {args.type}. Must be rainfall, sealevel, or tectonic.")

    if args.type == "rainfall":
        valid_units = ["mm/day", "mm/month", "mm/year", "m/year", "m/s"]
        if args.input_units not in valid_units:
            errors.append(f"Unknown rainfall units: {args.input_units}. Valid: {valid_units}")

    if args.type == "sealevel":
        valid_tunits = ["years", "ka", "Ma"]
        if args.time_units not in valid_tunits:
            errors.append(f"Unknown time units: {args.time_units}. Valid: {valid_tunits}")

    if args.type == "tectonic" and args.duration is None:
        errors.append("--duration required for tectonic conversion (years).")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def convert_rainfall(input_path, output_path, input_units, start_yr, end_yr):
    """
    Convert rainfall data to pyBadlands m/year format.

    Supported input units:
        mm/day   → × 365.25 / 1000  = m/year
        mm/month → × 12 / 1000      = m/year
        mm/year  → ÷ 1000           = m/year
        m/year   → no conversion
        m/s      → × 86400 × 365.25 = m/year
    """
    conversion = {
        "mm/day":   lambda x: x * 365.25 / 1000.0,
        "mm/month": lambda x: x * 12.0 / 1000.0,
        "mm/year":  lambda x: x / 1000.0,
        "m/year":   lambda x: x,
        "m/s":      lambda x: x * 86400.0 * 365.25,
    }

    data = np.loadtxt(input_path, delimiter=",", skiprows=1)
    if data.ndim == 1:
        # Single uniform value
        val_converted = conversion[input_units](data[0])
        result = {"type": "uniform", "rval": float(val_converted), "units": "m/year"}
    else:
        # Spatial map: columns = x, y, rainfall
        data[:, -1] = conversion[input_units](data[:, -1])
        np.savetxt(output_path, data, delimiter=" ", fmt="%.6f",
                   header="x y rainfall_m_per_year", comments="")
        result = {
            "type": "spatial_map",
            "output": output_path,
            "units": "m/year",
            "n_points": len(data),
            "min_rain": float(data[:, -1].min()),
            "max_rain": float(data[:, -1].max()),
        }

    # Post-validation: check reasonable range
    max_val = result.get("max_rain", result.get("rval", 0))
    if max_val > 15.0:
        result["warning"] = (
            f"Max rainfall = {max_val:.2f} m/year is very high. "
            "Verify input units are correct (dt_001)."
        )
    if max_val < 0:
        result["warning"] = "Negative rainfall detected. Check input data."

    return result


def convert_sealevel(input_path, output_path, time_units):
    """
    Convert sea-level curve to pyBadlands format (time in years, elevation in m).

    Input formats:
        ka → × 1000 = years
        Ma → × 1e6  = years
        years → no conversion
    """
    time_conversion = {
        "years": 1.0,
        "ka":    1000.0,
        "Ma":    1.0e6,
    }

    data = np.loadtxt(input_path, delimiter=",", skiprows=0)
    if data.shape[1] < 2:
        return {"status": "error", "message": "Sea-level file must have 2 columns: time, elevation"}

    # Convert time column
    data[:, 0] *= time_conversion[time_units]

    # Ensure chronological order
    sort_idx = np.argsort(data[:, 0])
    data = data[sort_idx]

    np.savetxt(output_path, data, delimiter=" ", fmt="%.6f",
               header="time_years sealevel_m", comments="")

    result = {
        "output": output_path,
        "time_range": [float(data[0, 0]), float(data[-1, 0])],
        "sealevel_range": [float(data[:, 1].min()), float(data[:, 1].max())],
        "n_points": len(data),
        "units": {"time": "years", "elevation": "m"},
    }

    return result


def convert_tectonic(input_path, output_path, duration_years):
    """
    Convert tectonic rate map (m/year) to total displacement map (m).

    pyBadlands displacement events specify TOTAL displacement over the event
    duration, NOT a rate. This function multiplies rate by duration.

    CRITICAL: If input is already total displacement, set duration=1.
    """
    data = np.loadtxt(input_path, delimiter=",", skiprows=1)

    if data.ndim == 1 or data.shape[1] < 3:
        return {"status": "error", "message": "Tectonic file must have >= 3 columns: x, y, rate"}

    # Multiply rate column(s) by duration
    # Columns: x, y, vertical_rate [, horizontal_rate_x, horizontal_rate_y]
    for col in range(2, data.shape[1]):
        data[:, col] *= duration_years

    np.savetxt(output_path, data, delimiter=" ", fmt="%.6f",
               header="x y displacement_m", comments="")

    result = {
        "output": output_path,
        "duration_years": duration_years,
        "n_points": len(data),
        "max_displacement_m": float(np.abs(data[:, 2:]).max()),
        "units": "m (total over event)",
    }

    # Post-validation
    if result["max_displacement_m"] > 50000:
        result["warning"] = (
            f"Max displacement = {result['max_displacement_m']:.0f} m seems very large. "
            "Verify input is rate (m/year), not already total displacement (dt_005)."
        )

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Route to appropriate converter based on type."""
    if args.type == "rainfall":
        return convert_rainfall(args.input, args.output, args.input_units,
                                args.start, args.end)
    elif args.type == "sealevel":
        return convert_sealevel(args.input, args.output, args.time_units)
    elif args.type == "tectonic":
        return convert_tectonic(args.input, args.output, args.duration)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--type", required=True,
                        choices=["rainfall", "sealevel", "tectonic"],
                        help="Forcing data type to convert")
    parser.add_argument("--input", required=True,
                        help="Path to input data file")
    parser.add_argument("--output", required=True,
                        help="Path to output file (badlands format)")
    parser.add_argument("--input-units", dest="input_units", default="mm/day",
                        help="Input rainfall units (default: mm/day)")
    parser.add_argument("--time-units", dest="time_units", default="years",
                        help="Sea-level time units (default: years)")
    parser.add_argument("--duration", type=float, default=None,
                        help="Tectonic event duration in years")
    parser.add_argument("--start", type=float, default=0,
                        help="Simulation start time (years)")
    parser.add_argument("--end", type=float, default=1e6,
                        help="Simulation end time (years)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "result": result}, indent=2))


if __name__ == "__main__":
    main()
