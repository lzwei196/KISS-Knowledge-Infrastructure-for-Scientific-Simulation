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
    """Convert precipitation to kg/m2/s.

    1 mm of water spread over 1 m2 IS 1 kg, so mm/s and kg/m2/s are the SAME
    number -- there is no density division here.  Dividing by 1000 gives m/s,
    and PIHM already does that itself: src/forcing.c:123 does
        elem[i].wf.prcp = forc->meteo[ind].value[PRCP_TS] / 1000.0;
    so a /1000 in this converter is applied twice and the model sees 1e-6 of
    the real rainfall.  Ground truth: input/ShaleHills/ShaleHills.meteo carries
    PRCP = 4.72e-04 kg/m2/s, i.e. 1.7 mm/hr / 1031 mm/yr (Shale Hills PA).
    """
    v = float(value)
    if unit == "mm/hr":
        return v / 3600.0
    elif unit == "mm/day":
        return v / 86400.0
    elif unit == "mm/s":
        return v
    return v  # already kg/m2/s


def validate_prcp_climatology(records, unit):
    """Catch an order-of-magnitude PRCP scaling error, which no per-row check can.

    VALID_RANGES["prcp_kgm2s"] has a LOWER bound of 0.0, so a uniformly
    1000x-too-small precipitation column passes every single row test and the
    model silently desiccates (PIHM Chiuni real_case 2026-08-02: 1.14 mm/yr
    written instead of 1138 mm/yr -> groundwater head pinned at the aquifer
    bottom for all 3134 days, r = -6e-17).  The only detector is the
    AGGREGATE, so reconstruct the annual total and bound it by global
    climatology.  Returns (errors, mm_per_year).
    """
    if len(records) < 2:
        return [], None
    t0 = datetime.strptime(records[0]["time"], "%Y-%m-%d %H:%M")
    t1 = datetime.strptime(records[-1]["time"], "%Y-%m-%d %H:%M")
    span_s = (t1 - t0).total_seconds()
    if span_s <= 0:
        return [], None
    dt_s = span_s / (len(records) - 1)
    total_mm = sum(r["prcp_kgm2s"] for r in records) * dt_s  # kg/m2/s -> mm
    years = span_s / (365.25 * 86400.0)
    mm_yr = total_mm / years if years > 0 else None
    if years < 0.5 or mm_yr is None:
        return [], mm_yr
    if mm_yr < 10.0 or mm_yr > 15000.0:
        return ([
            "PRCP annual total %.4g mm/yr (%.4g mm over %.2f yr) is outside the "
            "global climatological range [10, 15000] mm/yr. The --prcp-unit "
            "'%s' conversion is almost certainly off by a factor of 1000: "
            "kg/m2/s == mm/s, NOT m/s. Compare input/ShaleHills/ShaleHills.meteo "
            "(4.72e-04 kg/m2/s = 1031 mm/yr)." % (mm_yr, total_mm, years, unit)
        ], mm_yr)
    return [], mm_yr


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


def validate_time_series(records):
    """Reject a time axis that IntrplForcing (src/forcing.c) cannot search.

    IntrplForcing binary-searches ftime[] for the bracket containing t and then
    divides by (ftime[middle] - ftime[middle - 1]). So the column has to be
    strictly increasing:
      * duplicate timestamps  -> divide by zero -> inf/NaN forcing;
      * out-of-order rows     -> the search lands in the wrong bracket and the
                                 step silently reuses the previous value.
    Neither shows up as an error at run time, which is exactly the failure mode
    this converter exists to prevent, so these are fatal rather than warnings.
    """
    errors = []
    prev = None
    for i, rec in enumerate(records):
        t = datetime.strptime(rec["time"], "%Y-%m-%d %H:%M")
        if prev is not None and t <= prev[1]:
            errors.append(
                f"Row {i}: timestamp {rec['time']} is not after row {prev[0]} "
                f"({prev[1]:%Y-%m-%d %H:%M}); .meteo must be strictly increasing"
            )
        prev = (i, t)
    return errors


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

    # Fatal: a non-monotonic time axis is unrecoverable downstream
    time_errors = validate_time_series(records)
    if time_errors:
        print(json.dumps({"status": "error",
                          "errors": time_errors[:20] +
                                    ([f"... and {len(time_errors)-20} more"]
                                     if len(time_errors) > 20 else [])}))
        sys.exit(1)

    # Fatal: an order-of-magnitude PRCP scaling error is invisible per-row
    prcp_errors, prcp_mm_yr = validate_prcp_climatology(records, args.prcp_unit)
    if prcp_errors:
        print(json.dumps({"status": "error", "errors": prcp_errors}))
        sys.exit(1)

    # Validate output ranges
    warnings = validate_output_ranges(records)
    if warnings and len(warnings) > 20:
        warnings = warnings[:20] + [f"... and {len(warnings)-20} more"]

    # Write PIHM .meteo file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        # MM-PIHM's ReadMeteo (src/read_forc.c) sscanf's ONE line
        #   "%s %d %s %lf"  ->  METEO_TS <index> WIND_LVL <zlvl>
        # and then CheckHeader(8, TIME PRCP SFCTMP RH SFCSPD SOLAR LONGWV PRES).
        # Writing METEO_TS / WIND_LVL on SEPARATE lines, or omitting the column
        # header, aborts PIHM with ERR_WRONG_FORMAT before the first timestep.
        f.write(f"METEO_TS\t1\tWIND_LVL\t{args.wind_level:.1f}\n")
        f.write("TIME\tPRCP\tSFCTMP\tRH\tSFCSPD\tSOLAR\tLONGWV\tPRES\n")
        f.write("#TS\tkg/m2/s\tK\t%\tm/s\tW/m2\tW/m2\tPa\n")
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

    return records, warnings, prcp_mm_yr


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
    records, warnings, prcp_mm_yr = process(args)

    result = {
        "status": "success",
        "output": args.output,
        "n_records": len(records),
        "prcp_mm_per_year": prcp_mm_yr,
        "time_range": [records[0]["time"], records[-1]["time"]] if records else [],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
