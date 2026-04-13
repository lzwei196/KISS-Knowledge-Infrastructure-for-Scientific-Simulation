#!/usr/bin/env python3
"""
convert_forcing_data.py — Atmospheric Forcing Data Converter for FATES/CTSM

Converts raw meteorological data (CSV, NetCDF) from common global datasets
(GSWP3, CRU-NCEP, ERA5, flux tower) into DATM-compatible format with
correct units for CLM/FATES simulations.

CRITICAL UNIT CONVERSIONS (silent errors if wrong — see dt_005, dt_006, dt_007):
  - Temperature:   sources often give degC; DATM wants Kelvin (add 273.15)
  - Precipitation:  sources give mm/day or mm/3hr; DATM wants mm/s (÷86400 or ÷10800)
  - Radiation:      sources give MJ/m2/day; DATM wants W/m2 (×1e6 / 86400)
  - Pressure:       sources give hPa or kPa; DATM wants Pa (×100 or ×1000)
  - Humidity:       sources give RH (%) or g/kg; DATM wants specific humidity kg/kg

Follows validate -> process -> validate pattern.

Usage:
    # Convert ERA5 CSV forcing for a single point
    python convert_forcing_data.py \
        --input era5_forcing.csv --format csv \
        --lat 9.15 --lon -79.85 \
        --temp-units degC --precip-units mm_day --rad-units MJ_m2_day \
        --pressure-units hPa --humidity-type RH \
        --output datm_forcing.csv

    # Convert tower data with specific column mapping
    python convert_forcing_data.py \
        --input tower_obs.csv --format csv \
        --lat 42.54 --lon -72.17 \
        --col-map "time=TIMESTAMP,temp=TA,precip=P,sw=SW_IN,lw=LW_IN,wind=WS,rh=RH,psurf=PA" \
        --temp-units degC --precip-units mm_30min --rad-units W_m2 \
        --pressure-units kPa --humidity-type RH \
        --output harvard_datm.csv

    # Validate existing forcing file
    python convert_forcing_data.py \
        --input existing_forcing.csv --format csv \
        --operation validate
"""

import argparse
import json
import os
import sys
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# --- DATM Expected Variable Names and Units ---
DATM_VARIABLES = {
    "TBOT":     {"units": "K",    "description": "Air temperature at 2m",
                 "valid_range": (180.0, 340.0)},
    "PRECTmms": {"units": "mm/s", "description": "Total precipitation rate",
                 "valid_range": (0.0, 0.1)},
    "FSDS":     {"units": "W/m2", "description": "Downwelling shortwave radiation",
                 "valid_range": (0.0, 1400.0)},
    "FLDS":     {"units": "W/m2", "description": "Downwelling longwave radiation",
                 "valid_range": (50.0, 600.0)},
    "QBOT":     {"units": "kg/kg","description": "Specific humidity at 2m",
                 "valid_range": (0.0, 0.06)},
    "WIND":     {"units": "m/s",  "description": "Wind speed at 10m",
                 "valid_range": (0.0, 75.0)},
    "PSRF":     {"units": "Pa",   "description": "Surface air pressure",
                 "valid_range": (30000.0, 110000.0)},
}

# --- Conversion factors from common source units ---
TEMP_CONVERSIONS = {
    "K":     lambda x: x,
    "degC":  lambda x: x + 273.15,
    "degF":  lambda x: (x - 32.0) * 5.0 / 9.0 + 273.15,
}

PRECIP_CONVERSIONS = {
    "mm_s":     lambda x: x,
    "mm_day":   lambda x: x / 86400.0,
    "mm_hr":    lambda x: x / 3600.0,
    "mm_3hr":   lambda x: x / 10800.0,
    "mm_30min": lambda x: x / 1800.0,
    "m_day":    lambda x: x * 1000.0 / 86400.0,
    "kg_m2_s":  lambda x: x,  # equivalent to mm/s for water
}

RAD_CONVERSIONS = {
    "W_m2":       lambda x: x,
    "MJ_m2_day":  lambda x: x * 1.0e6 / 86400.0,
    "kJ_m2_hr":   lambda x: x * 1000.0 / 3600.0,
    "cal_cm2_min": lambda x: x * 697.3,
}

PRESSURE_CONVERSIONS = {
    "Pa":   lambda x: x,
    "hPa":  lambda x: x * 100.0,
    "kPa":  lambda x: x * 1000.0,
    "mbar": lambda x: x * 100.0,
    "atm":  lambda x: x * 101325.0,
}

HUMIDITY_CONVERSIONS = {
    "kg_kg": lambda x, **kw: x,
    "g_kg":  lambda x, **kw: x / 1000.0,
}


def rh_to_specific_humidity(rh_pct: np.ndarray, temp_k: np.ndarray,
                            psurf_pa: np.ndarray) -> np.ndarray:
    """Convert relative humidity (%) to specific humidity (kg/kg).

    Uses Tetens formula for saturation vapor pressure.
    CRITICAL: RH must be 0-100 (percent), not 0-1 (fraction).
    """
    # Tetens formula: e_sat in Pa
    temp_c = temp_k - 273.15
    e_sat = 610.78 * np.exp(17.269 * temp_c / (temp_c + 237.3))

    # Actual vapor pressure
    rh_frac = np.clip(rh_pct / 100.0, 0.0, 1.0)
    e_actual = rh_frac * e_sat

    # Specific humidity: q = 0.622 * e / (P - 0.378 * e)
    epsilon = 0.622
    q = epsilon * e_actual / (psurf_pa - (1.0 - epsilon) * e_actual)
    return np.clip(q, 0.0, 0.06)


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate command-line arguments and input files."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.operation == "convert":
        if args.temp_units and args.temp_units not in TEMP_CONVERSIONS:
            errors.append(
                f"Unknown temperature units '{args.temp_units}'. "
                f"Valid: {list(TEMP_CONVERSIONS.keys())}")
        if args.precip_units and args.precip_units not in PRECIP_CONVERSIONS:
            errors.append(
                f"Unknown precipitation units '{args.precip_units}'. "
                f"Valid: {list(PRECIP_CONVERSIONS.keys())}")
        if args.rad_units and args.rad_units not in RAD_CONVERSIONS:
            errors.append(
                f"Unknown radiation units '{args.rad_units}'. "
                f"Valid: {list(RAD_CONVERSIONS.keys())}")
        if args.pressure_units and args.pressure_units not in PRESSURE_CONVERSIONS:
            errors.append(
                f"Unknown pressure units '{args.pressure_units}'. "
                f"Valid: {list(PRESSURE_CONVERSIONS.keys())}")

        if not args.output:
            errors.append("--output required for convert operation")

    if args.lat is not None and (args.lat < -90 or args.lat > 90):
        errors.append(f"Latitude must be in [-90, 90], got {args.lat}")
    if args.lon is not None and (args.lon < -360 or args.lon > 360):
        errors.append(f"Longitude must be in [-360, 360], got {args.lon}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def parse_column_map(col_map_str: str) -> Dict[str, str]:
    """Parse column mapping string: 'time=TIMESTAMP,temp=TA,precip=P,...'"""
    mapping = {}
    for pair in col_map_str.split(","):
        key, val = pair.strip().split("=")
        mapping[key.strip()] = val.strip()
    return mapping


def load_csv_forcing(filepath: str,
                     col_map: Optional[Dict[str, str]] = None
                     ) -> Dict[str, np.ndarray]:
    """Load forcing data from CSV file."""
    import csv

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("Error: CSV file is empty.", file=sys.stderr)
        sys.exit(1)

    # Default column mapping (common names)
    default_map = {
        "time": "time", "temp": "temp", "precip": "precip",
        "sw": "sw_down", "lw": "lw_down", "wind": "wind",
        "rh": "rh", "qbot": "qbot", "psurf": "psurf",
    }
    if col_map:
        default_map.update(col_map)

    # Auto-detect columns
    available_cols = set(rows[0].keys())
    data = {}

    # Time column
    time_col = default_map.get("time")
    if time_col and time_col in available_cols:
        try:
            data["time"] = [row[time_col] for row in rows]
        except (KeyError, ValueError):
            data["time"] = list(range(len(rows)))
    else:
        data["time"] = list(range(len(rows)))

    # Numeric columns
    numeric_map = {
        "temp": "TBOT", "precip": "PRECTmms", "sw": "FSDS",
        "lw": "FLDS", "wind": "WIND", "rh": "RH",
        "qbot": "QBOT", "psurf": "PSRF",
    }
    for key, datm_name in numeric_map.items():
        src_col = default_map.get(key)
        if src_col and src_col in available_cols:
            try:
                values = [float(row[src_col]) if row[src_col] not in ("", "NA", "NaN")
                          else np.nan for row in rows]
                data[datm_name] = np.array(values)
            except (ValueError, KeyError):
                pass

    return data


def convert_units(data: Dict[str, np.ndarray],
                  temp_units: str = "K",
                  precip_units: str = "mm_s",
                  rad_units: str = "W_m2",
                  pressure_units: str = "Pa",
                  humidity_type: str = "kg_kg") -> Dict[str, np.ndarray]:
    """Apply unit conversions to all forcing variables."""
    result = dict(data)
    conversions_applied = []

    # Temperature
    if "TBOT" in result and temp_units != "K":
        conv = TEMP_CONVERSIONS[temp_units]
        result["TBOT"] = conv(result["TBOT"])
        conversions_applied.append(f"TBOT: {temp_units} -> K")

    # Precipitation
    if "PRECTmms" in result and precip_units != "mm_s":
        conv = PRECIP_CONVERSIONS[precip_units]
        result["PRECTmms"] = conv(result["PRECTmms"])
        # Ensure non-negative
        result["PRECTmms"] = np.maximum(result["PRECTmms"], 0.0)
        conversions_applied.append(f"PRECTmms: {precip_units} -> mm/s")

    # Shortwave radiation
    if "FSDS" in result and rad_units != "W_m2":
        conv = RAD_CONVERSIONS[rad_units]
        result["FSDS"] = conv(result["FSDS"])
        # Ensure non-negative
        result["FSDS"] = np.maximum(result["FSDS"], 0.0)
        conversions_applied.append(f"FSDS: {rad_units} -> W/m2")

    # Longwave radiation (same units as shortwave typically)
    if "FLDS" in result and rad_units != "W_m2":
        conv = RAD_CONVERSIONS[rad_units]
        result["FLDS"] = conv(result["FLDS"])
        result["FLDS"] = np.maximum(result["FLDS"], 0.0)
        conversions_applied.append(f"FLDS: {rad_units} -> W/m2")

    # Pressure
    if "PSRF" in result and pressure_units != "Pa":
        conv = PRESSURE_CONVERSIONS[pressure_units]
        result["PSRF"] = conv(result["PSRF"])
        conversions_applied.append(f"PSRF: {pressure_units} -> Pa")

    # Humidity: convert RH to specific humidity if needed
    if "RH" in result and humidity_type == "RH":
        if "TBOT" in result and "PSRF" in result:
            result["QBOT"] = rh_to_specific_humidity(
                result["RH"], result["TBOT"], result["PSRF"])
            del result["RH"]
            conversions_applied.append("RH (%) -> QBOT (kg/kg) via Tetens")
        else:
            print("Warning: Cannot convert RH without TBOT and PSRF.",
                  file=sys.stderr)

    # Specific humidity from g/kg
    if "QBOT" in result and humidity_type == "g_kg":
        result["QBOT"] = result["QBOT"] / 1000.0
        conversions_applied.append("QBOT: g/kg -> kg/kg")

    result["_conversions"] = conversions_applied
    return result


def validate_forcing_ranges(data: Dict[str, np.ndarray]) -> List[Dict[str, Any]]:
    """Check all forcing variables against physical ranges."""
    warnings = []

    for var_name, meta in DATM_VARIABLES.items():
        if var_name not in data:
            continue

        values = data[var_name]
        valid = values[~np.isnan(values)]
        if len(valid) == 0:
            warnings.append({
                "variable": var_name,
                "issue": "All values are NaN",
                "severity": "error",
            })
            continue

        lo, hi = meta["valid_range"]
        vmin, vmax = float(np.min(valid)), float(np.max(valid))

        if vmin < lo:
            warnings.append({
                "variable": var_name,
                "issue": f"Min value {vmin:.4g} below valid range [{lo}, {hi}] {meta['units']}",
                "severity": "error" if vmin < lo * 0.5 else "warning",
                "hint": _get_unit_hint(var_name, vmin, lo),
            })
        if vmax > hi:
            warnings.append({
                "variable": var_name,
                "issue": f"Max value {vmax:.4g} above valid range [{lo}, {hi}] {meta['units']}",
                "severity": "error" if vmax > hi * 2 else "warning",
                "hint": _get_unit_hint(var_name, vmax, hi),
            })

    return warnings


def _get_unit_hint(var_name: str, value: float, bound: float) -> str:
    """Generate helpful hint for likely unit conversion errors."""
    if var_name == "TBOT" and value < 100:
        return "Likely in degC — add 273.15 to convert to K (dt_005)"
    if var_name == "PRECTmms" and value > 1.0:
        return "Likely in mm/day — divide by 86400 to get mm/s (dt_006)"
    if var_name == "FSDS" and value < 50 and value > 0:
        return "Likely in MJ/m2/day — multiply by 11.574 to get W/m2 (dt_007)"
    if var_name == "PSRF" and value < 2000:
        return "Likely in hPa or kPa — multiply by 100 or 1000 to get Pa"
    if var_name == "QBOT" and value > 0.1:
        return "Likely in g/kg — divide by 1000 to get kg/kg"
    return ""


def export_forcing_csv(data: Dict[str, np.ndarray], output_path: str) -> None:
    """Export converted forcing data to DATM-compatible CSV."""
    import csv

    times = data.get("time", list(range(len(next(iter(
        {k: v for k, v in data.items()
         if k not in ("time", "_conversions") and isinstance(v, np.ndarray)}.values()
    ))))))

    datm_vars = [v for v in DATM_VARIABLES if v in data]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header with DATM variable names
        header = ["time"] + datm_vars
        writer.writerow(header)

        # Units row
        units = [""] + [DATM_VARIABLES[v]["units"] for v in datm_vars]
        writer.writerow(units)

        # Data rows
        for i in range(len(times)):
            row = [str(times[i])]
            for var in datm_vars:
                val = data[var][i] if i < len(data[var]) else np.nan
                row.append(f"{val:.6g}" if not np.isnan(val) else "NaN")
            writer.writerow(row)

    print(f"  DATM forcing written: {output_path} ({len(times)} timesteps, "
          f"{len(datm_vars)} variables)", file=sys.stderr)


def validate_outputs(data: Dict[str, np.ndarray],
                     warnings_from_range: List[Dict]) -> List[str]:
    """Stage 3: Final validation of converted forcing data."""
    warnings = []

    # Check completeness
    required = ["TBOT", "PRECTmms", "FSDS"]
    for var in required:
        if var not in data:
            warnings.append(f"Missing required variable: {var}")

    # Propagate range warnings
    for w in warnings_from_range:
        if w["severity"] == "error":
            hint = w.get("hint", "")
            warnings.append(f"{w['variable']}: {w['issue']}. {hint}")

    # Check for constant values (possible fill-value issue)
    for var_name in DATM_VARIABLES:
        if var_name in data:
            valid = data[var_name][~np.isnan(data[var_name])]
            if len(valid) > 10 and np.std(valid) < 1e-10:
                warnings.append(
                    f"{var_name}: All values are constant ({valid[0]:.4g}) "
                    "— possible fill value or extraction error")

    # Check temporal coverage
    n_steps = len(data.get("time", []))
    if n_steps < 8:
        warnings.append(f"Only {n_steps} timesteps — insufficient for DATM cycling")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert atmospheric forcing data for FATES/CTSM (DATM format)")
    parser.add_argument("--input", required=True,
                        help="Input forcing file (CSV)")
    parser.add_argument("--format", choices=["csv"], default="csv",
                        help="Input file format (default: csv)")
    parser.add_argument("--output", help="Output DATM-compatible CSV file")
    parser.add_argument("--operation", choices=["convert", "validate"],
                        default="convert", help="Operation mode")
    parser.add_argument("--lat", type=float, help="Site latitude")
    parser.add_argument("--lon", type=float, help="Site longitude")
    parser.add_argument("--col-map",
                        help="Column mapping: 'time=TIMESTAMP,temp=TA,...'")
    parser.add_argument("--temp-units", default="K",
                        choices=list(TEMP_CONVERSIONS.keys()),
                        help="Temperature units in source (default: K)")
    parser.add_argument("--precip-units", default="mm_s",
                        choices=list(PRECIP_CONVERSIONS.keys()),
                        help="Precipitation units in source (default: mm_s)")
    parser.add_argument("--rad-units", default="W_m2",
                        choices=list(RAD_CONVERSIONS.keys()),
                        help="Radiation units in source (default: W_m2)")
    parser.add_argument("--pressure-units", default="Pa",
                        choices=list(PRESSURE_CONVERSIONS.keys()),
                        help="Pressure units in source (default: Pa)")
    parser.add_argument("--humidity-type", default="kg_kg",
                        choices=["RH", "kg_kg", "g_kg"],
                        help="Humidity type in source (default: kg_kg)")
    args = parser.parse_args()

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Stage 2: Process
    col_map = parse_column_map(args.col_map) if args.col_map else None
    data = load_csv_forcing(args.input, col_map)

    print(f"Loaded {len(data.get('time', []))} timesteps from {args.input}",
          file=sys.stderr)

    if args.operation == "convert":
        data = convert_units(
            data,
            temp_units=args.temp_units,
            precip_units=args.precip_units,
            rad_units=args.rad_units,
            pressure_units=args.pressure_units,
            humidity_type=args.humidity_type,
        )
        conversions = data.pop("_conversions", [])
        for c in conversions:
            print(f"  Applied: {c}", file=sys.stderr)

    # Validate ranges
    range_warnings = validate_forcing_ranges(data)

    # Export if converting
    if args.operation == "convert" and args.output:
        export_forcing_csv(data, args.output)

    # Stage 3: Validate outputs
    output_warnings = validate_outputs(data, range_warnings)

    # Summary
    summary = {
        "status": "success" if not output_warnings else "completed_with_warnings",
        "input_file": args.input,
        "output_file": args.output,
        "operation": args.operation,
        "n_timesteps": len(data.get("time", [])),
        "variables_found": [v for v in DATM_VARIABLES if v in data],
        "conversions_applied": conversions if args.operation == "convert" else [],
        "range_warnings": range_warnings,
        "output_warnings": output_warnings,
    }
    print(json.dumps(summary, indent=2))

    if output_warnings:
        print("\n--- Output Validation Warnings ---", file=sys.stderr)
        for w in output_warnings:
            print(f"  WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
