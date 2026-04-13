#!/usr/bin/env python3
"""
forcing_converter.py — Convert meteorological forcing data to PIHM .meteo format.

Reads CSV forcing data (e.g., from ERA5, NLDAS, or station data) and writes
a PIHM-format .meteo file with correct units. Handles the most common unit
conversion traps:
  - Precipitation: mm/hr or mm/day → kg/m2/s
  - Temperature: °C → K
  - Pressure: hPa → Pa
  - Humidity: specific humidity → RH(%)
  - Radiation: MJ/m2/day → W/m2
  - Wind speed: km/hr → m/s

CRITICAL: Incorrect unit conversions produce SILENT errors — the model runs
but results are physically meaningless. See diagnostic triplets dt_001–dt_006.

Usage:
    python forcing_converter.py --input forcing.csv --output project.meteo \\
        --prcp-unit mm/hr --temp-unit C --pres-unit hPa --wind-unit m/s \\
        --rad-unit W/m2 --humidity-type RH --wind-level 10.0

    python forcing_converter.py --input era5_data.csv --output project.meteo \\
        --prcp-unit mm/hr --temp-unit K --pres-unit Pa --humidity-type specific
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime


# Validation thresholds for PIHM internal units
VALID_RANGES = {
    "prcp_kgm2s":  (0.0, 0.1),          # kg/m2/s  (0.1 = 360 mm/hr, extreme)
    "sfctmp_k":    (200.0, 340.0),       # K
    "rh_pct":      (0.0, 100.0),         # %
    "sfcspd_ms":   (0.0, 50.0),          # m/s
    "solar_wm2":   (0.0, 1400.0),        # W/m2
    "longwv_wm2":  (50.0, 600.0),        # W/m2
    "pres_pa":     (50000.0, 110000.0),   # Pa
}


def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []
    if not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")

    valid_prcp = ["kg/m2/s", "mm/hr", "mm/day", "mm/s"]
    if args.prcp_unit not in valid_prcp:
        errors.append(f"Invalid prcp-unit '{args.prcp_unit}'. Valid: {valid_prcp}")

    valid_temp = ["K", "C"]
    if args.temp_unit not in valid_temp:
        errors.append(f"Invalid temp-unit '{args.temp_unit}'. Valid: {valid_temp}")

    valid_pres = ["Pa", "hPa", "kPa"]
    if args.pres_unit not in valid_pres:
        errors.append(f"Invalid pres-unit '{args.pres_unit}'. Valid: {valid_pres}")

    valid_wind = ["m/s", "km/hr"]
    if args.wind_unit not in valid_wind:
        errors.append(f"Invalid wind-unit '{args.wind_unit}'. Valid: {valid_wind}")

    valid_rad = ["W/m2", "MJ/m2/day"]
    if args.rad_unit not in valid_rad:
        errors.append(f"Invalid rad-unit '{args.rad_unit}'. Valid: {valid_rad}")

    valid_hum = ["RH", "specific", "RH_fraction"]
    if args.humidity_type not in valid_hum:
        errors.append(f"Invalid humidity-type '{args.humidity_type}'. Valid: {valid_hum}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def convert_prcp(value, unit):
    """Convert precipitation to kg/m2/s."""
    v = float(value)
    if unit == "mm/hr":
        return v / 3600.0 / 1000.0  # mm/hr → m/s → kg/m2/s (density=1000)
    elif unit == "mm/day":
        return v / 86400.0 / 1000.0
    elif unit == "mm/s":
        return v / 1000.0
    return v  # already kg/m2/s


def convert_temp(value, unit):
    """Convert temperature to Kelvin."""
    v = float(value)
    if unit == "C":
        return v + 273.15
    return v


def convert_pressure(value, unit):
    """Convert pressure to Pa."""
    v = float(value)
    if unit == "hPa":
        return v * 100.0
    elif unit == "kPa":
        return v * 1000.0
    return v


def convert_wind(value, unit):
    """Convert wind speed to m/s."""
    v = float(value)
    if unit == "km/hr":
        return v / 3.6
    return v


def convert_radiation(value, unit):
    """Convert radiation to W/m2."""
    v = float(value)
    if unit == "MJ/m2/day":
        return v / 0.0864
    return v


def convert_humidity(value, humidity_type, temp_k, pres_pa):
    """Convert humidity to RH (%)."""
    v = float(value)
    if humidity_type == "RH":
        return v  # already in %
    elif humidity_type == "RH_fraction":
        return v * 100.0
    elif humidity_type == "specific":
        # Specific humidity (kg/kg) → RH(%)
        # Saturation vapor pressure (Tetens/Buck formula)
        tc = temp_k - 273.15
        es = 611.2 * __import__("math").exp(17.67 * tc / (tc + 243.5))
        # Actual vapor pressure from specific humidity
        e = v * pres_pa / (0.622 + 0.378 * v)
        rh = 100.0 * e / es
        return max(0.0, min(100.0, rh))
    return v


def validate_output_ranges(records):
    """Validate converted values are in physically reasonable ranges."""
    warnings = []
    for i, rec in enumerate(records):
        for var, (lo, hi) in VALID_RANGES.items():
            if var in rec and (rec[var] < lo or rec[var] > hi):
                warnings.append(
                    f"Row {i}: {var}={rec[var]:.6g} outside range [{lo}, {hi}]"
                )
    return warnings


def parse_datetime(dt_str):
    """Parse datetime string to PIHM format 'YYYY-MM-DD HH:MM'."""
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M", "%Y%m%d%H"]:
        try:
            dt = datetime.strptime(dt_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {dt_str}")


def process(args):
    """Read CSV, convert units, write PIHM .meteo file."""
    records = []
    col_map = {
        "time": None, "prcp": None, "temp": None, "rh": None,
        "wind": None, "solar": None, "longwave": None, "pressure": None
    }

    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames]

        # Auto-detect column mapping
        for h in headers:
            if any(k in h for k in ["time", "date", "datetime"]):
                col_map["time"] = h
            elif any(k in h for k in ["prcp", "precip", "rain", "pr"]):
                col_map["prcp"] = h
            elif any(k in h for k in ["temp", "sfctmp", "t2m", "tas"]):
                col_map["temp"] = h
            elif any(k in h for k in ["rh", "humid", "huss", "q2m"]):
                col_map["rh"] = h
            elif any(k in h for k in ["wind", "spd", "sfcspd", "uas", "u10"]):
                col_map["wind"] = h
            elif any(k in h for k in ["solar", "swdown", "ssrd", "rsds"]):
                col_map["solar"] = h
            elif any(k in h for k in ["long", "lwdown", "strd", "rlds"]):
                col_map["longwave"] = h
            elif any(k in h for k in ["pres", "press", "sp", "ps"]):
                col_map["pressure"] = h

        missing = [k for k, v in col_map.items() if v is None]
        if missing:
            print(json.dumps({
                "status": "error",
                "errors": [f"Could not auto-detect columns: {missing}. "
                           f"Available headers: {headers}"]
            }))
            sys.exit(1)

        for row in reader:
            # Strip whitespace from keys
            row = {k.strip().lower(): v for k, v in row.items()}

            temp_k = convert_temp(row[col_map["temp"]], args.temp_unit)
            pres_pa = convert_pressure(row[col_map["pressure"]], args.pres_unit)

            rec = {
                "time": parse_datetime(row[col_map["time"]]),
                "prcp_kgm2s": convert_prcp(row[col_map["prcp"]], args.prcp_unit),
                "sfctmp_k": temp_k,
                "rh_pct": convert_humidity(
                    row[col_map["rh"]], args.humidity_type, temp_k, pres_pa
                ),
                "sfcspd_ms": convert_wind(row[col_map["wind"]], args.wind_unit),
                "solar_wm2": convert_radiation(row[col_map["solar"]], args.rad_unit),
                "longwv_wm2": convert_radiation(row[col_map["longwave"]], args.rad_unit),
                "pres_pa": pres_pa,
            }
            records.append(rec)

    # Validate output ranges
    warnings = validate_output_ranges(records)
    if warnings and len(warnings) > 20:
        warnings = warnings[:20] + [f"... and {len(warnings)-20} more"]

    # Write PIHM .meteo file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(f"METEO_TS\t1\n")
        f.write(f"WIND_LVL\t{args.wind_level:.1f}\n")
        for rec in records:
            f.write(
                f"{rec['time']}\t"
                f"{rec['prcp_kgm2s']:.10e}\t"
                f"{rec['sfctmp_k']:.4f}\t"
                f"{rec['rh_pct']:.2f}\t"
                f"{rec['sfcspd_ms']:.4f}\t"
                f"{rec['solar_wm2']:.4f}\t"
                f"{rec['longwv_wm2']:.4f}\t"
                f"{rec['pres_pa']:.2f}\n"
            )

    return records, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to PIHM .meteo format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output .meteo file path")
    parser.add_argument("--prcp-unit", default="mm/hr",
                        help="Precipitation unit: kg/m2/s, mm/hr, mm/day, mm/s")
    parser.add_argument("--temp-unit", default="C",
                        help="Temperature unit: K, C")
    parser.add_argument("--pres-unit", default="hPa",
                        help="Pressure unit: Pa, hPa, kPa")
    parser.add_argument("--wind-unit", default="m/s",
                        help="Wind speed unit: m/s, km/hr")
    parser.add_argument("--rad-unit", default="W/m2",
                        help="Radiation unit: W/m2, MJ/m2/day")
    parser.add_argument("--humidity-type", default="RH",
                        help="Humidity type: RH (percent), specific (kg/kg), RH_fraction (0-1)")
    parser.add_argument("--wind-level", type=float, default=10.0,
                        help="Height above ground of wind observations (m)")
    args = parser.parse_args()

    validate_inputs(args)
    records, warnings = process(args)

    result = {
        "status": "success",
        "output": args.output,
        "n_records": len(records),
        "time_range": [records[0]["time"], records[-1]["time"]] if records else [],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
