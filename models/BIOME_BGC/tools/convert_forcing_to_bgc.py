#!/usr/bin/env python3
"""
convert_forcing_to_bgc.py
Convert VIC forcing files (7-column ASCII) to BIOME-BGC meteorological format.

BIOME-BGC met file format (MTCLIM 4.x compatible):
  year  yday  Tmax(C)  Tmin(C)  Tday(C)  prcp(cm)  VPD(Pa)  srad(W/m2)  daylen(s)

CRITICAL UNIT CONVERSIONS:
  - Precipitation: mm -> cm (divide by 10!) [dt_007]
  - VPD: Must be in Pa (not kPa!) [dt_008]
  - Temperature: Must be in Celsius (not Kelvin!) [dt_010]
  - Day length: Must be computed from latitude + DOY [dt_009]

This tool reads EITHER:
  (a) VIC forcing files (7-col: PREC TMAX TMIN WIND QAIR SHORTWAVE LONGWAVE, 3-hourly)
  (b) Pre-processed daily CSV with columns: date, tmax, tmin, prec_mm, q, srad, pressure

Usage:
    python convert_forcing_to_bgc.py \\
        --forcing_file outputs/bengbu/vic_temp/forcing/forcing_final/bengbu_0.25deg_46.8750_-114.1250 \\
        --lat 46.8 --start_year 2000 --end_year 2010 \\
        --output metdata/site.mtc43

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import argparse
import math
from pathlib import Path
from datetime import datetime, timedelta

LIB_DIR = os.path.join(os.path.dirname(__file__), '..', 'lib')
sys.path.insert(0, LIB_DIR)
from bgc_utils import (compute_daylength, compute_vpd_from_tmin_tmax_q,
                        compute_tday, mm_to_cm, kelvin_to_celsius)


def read_vic_forcing(filepath: str, start_year: int, end_year: int,
                     steps_per_day: int = 8):
    """
    Read VIC 7-column ASCII forcing and aggregate to daily.

    VIC forcing columns (3-hourly, 8 steps/day):
    0: PREC (mm/step)
    1: TMAX (C) -- or could be AIR_TEMP depending on pipeline
    2: TMIN (C)
    3: WIND (m/s)
    4: QAIR (kg/kg) -- specific humidity
    5: SHORTWAVE (W/m2)
    6: LONGWAVE (W/m2)

    Returns list of dicts: {year, yday, tmax, tmin, prec_mm, q, srad, pressure}
    """
    daily_records = []

    with open(filepath, 'r') as f:
        lines = f.readlines()

    n_days = len(lines) // steps_per_day
    if n_days == 0:
        raise ValueError(f"No data in forcing file: {filepath}")

    # Determine date range
    start_date = datetime(start_year, 1, 1)

    for d in range(n_days):
        day_lines = lines[d * steps_per_day : (d + 1) * steps_per_day]
        if len(day_lines) < steps_per_day:
            break

        prec_sum = 0.0
        tmax_vals = []
        tmin_vals = []
        q_vals = []
        srad_vals = []

        for line in day_lines:
            vals = line.strip().split()
            if len(vals) < 7:
                continue
            prec_sum += float(vals[0])
            tmax_vals.append(float(vals[1]))
            tmin_vals.append(float(vals[2]))
            q_vals.append(float(vals[4]))
            srad_vals.append(float(vals[5]))

        current_date = start_date + timedelta(days=d)

        # Check if temperature is in Kelvin (>100 likely Kelvin)
        tmax_day = max(tmax_vals) if tmax_vals else 0
        tmin_day = min(tmin_vals) if tmin_vals else 0
        if tmax_day > 100:
            tmax_day = kelvin_to_celsius(tmax_day)
            tmin_day = kelvin_to_celsius(tmin_day)

        daily_records.append({
            "year": current_date.year,
            "yday": current_date.timetuple().tm_yday,
            "tmax": tmax_day,
            "tmin": tmin_day,
            "prec_mm": prec_sum,
            "q": sum(q_vals) / len(q_vals) if q_vals else 0,
            "srad": sum(srad_vals) / len(srad_vals) if srad_vals else 0,
        })

    # Filter to requested year range
    daily_records = [r for r in daily_records
                     if start_year <= r["year"] <= end_year]

    return daily_records


def convert_to_bgc_met(daily_records, lat, pressure=101325.0):
    """
    Convert daily records to BIOME-BGC met format lines.

    CRITICAL CONVERSIONS:
    - prec: mm -> cm (divide by 10)
    - VPD: computed in Pa from q and T
    - Tday: approximated as Tmin + 0.45*(Tmax-Tmin)
    - daylen: computed from latitude and yday (seconds)
    """
    met_lines = []

    for r in daily_records:
        tmax = r["tmax"]
        tmin = r["tmin"]
        tday = compute_tday(tmin, tmax)

        # CRITICAL: precipitation in cm, NOT mm
        prcp_cm = mm_to_cm(r["prec_mm"])

        # CRITICAL: VPD in Pa, NOT kPa
        # For FLUXNET input, vpd_hpa is already available (use directly × 100)
        # For VIC input, compute from specific humidity
        if "vpd_hpa" in r:
            vpd_pa = r["vpd_hpa"] * 100.0
        else:
            vpd_pa = compute_vpd_from_tmin_tmax_q(tmin, tmax, r["q"], pressure)

        # Shortwave radiation (already W/m2 in VIC forcing)
        srad = max(0.0, r["srad"])

        # CRITICAL: Day length in seconds, computed from latitude
        dayl = compute_daylength(lat, r["yday"])

        met_lines.append(
            f"  {r['year']:4d}  {r['yday']:4d}"
            f"  {tmax:8.2f}  {tmin:8.2f}  {tday:8.2f}"
            f"  {prcp_cm:8.4f}  {vpd_pa:10.2f}"
            f"  {srad:9.2f}  {dayl:8.0f}"
        )

    return met_lines


def validate_output(met_lines, daily_records):
    """Post-generation validation checks."""
    warnings = []
    n = len(daily_records)

    # Check annual precipitation
    years = set(r["year"] for r in daily_records)
    for year in sorted(years):
        annual_prec_mm = sum(r["prec_mm"] for r in daily_records
                             if r["year"] == year)
        annual_prec_cm = annual_prec_mm / 10.0
        if annual_prec_cm > 300:
            warnings.append(
                f"Year {year}: annual precip = {annual_prec_cm:.0f} cm "
                f"({annual_prec_mm:.0f} mm). If > 3000 mm seems too high, "
                "check that input is in mm (not cm already)."
            )
        if annual_prec_cm < 5:
            warnings.append(
                f"Year {year}: annual precip = {annual_prec_cm:.1f} cm "
                f"({annual_prec_mm:.1f} mm). Very dry -- verify input units."
            )

    # Check temperature range
    tmax_all = [r["tmax"] for r in daily_records]
    tmin_all = [r["tmin"] for r in daily_records]
    if max(tmax_all) > 60:
        warnings.append(f"Max Tmax = {max(tmax_all):.1f} C -- may be in Kelvin?")
    if min(tmin_all) < -80:
        warnings.append(f"Min Tmin = {min(tmin_all):.1f} C -- unrealistic")

    return warnings


def read_fluxnet_forcing(filepath: str, start_year: int, end_year: int):
    """
    Read FLUXNET2015 FULLSET_DD.csv and return daily records for BIOME-BGC.

    Columns used:
      TA_F_MDS_DAY   → Tmax proxy (daytime mean, °C)
      TA_F_MDS_NIGHT → Tmin proxy (nighttime mean, °C)
      P_F            → precipitation (mm/day)  [BIOME-BGC needs cm — ÷10 done later]
      VPD_F          → VPD (hPa) [BIOME-BGC needs Pa — ×100 done later]
      SW_IN_F        → shortwave radiation (W/m²)

    CRITICAL: -9999 fill values replaced with forward-filled or column means.
    """
    import pandas as pd
    df = pd.read_csv(filepath)
    df = df.replace(-9999.0, float("nan"))
    df["_date"] = pd.to_datetime(df["TIMESTAMP"], format="%Y%m%d")
    df = df[(df["_date"].dt.year >= start_year) & (df["_date"].dt.year <= end_year)]

    # CRITICAL leap-day fix (dt root-cause): BIOME-BGC metarr_init.c reads EXACTLY
    # 365*nyears met lines sequentially and does NOT index by yday. Emitting 366
    # lines for a leap year shifts ALL subsequent forcing +1 day, drifting GPP out
    # of phase and tanking NSE on later years. Drop Feb-29 → 365 lines every year.
    df = df[~((df["_date"].dt.month == 2) & (df["_date"].dt.day == 29))]

    required = ["TA_F_MDS_DAY", "TA_F_MDS_NIGHT", "P_F", "VPD_F", "SW_IN_F"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column {col} in FULLSET_DD — check file")
        df[col] = df[col].ffill().bfill()

    records = []
    for _, row in df.iterrows():
        tmax = float(row["TA_F_MDS_DAY"])
        tmin = float(row["TA_F_MDS_NIGHT"])
        records.append({
            "year": int(row["_date"].year),
            "yday": int(row["_date"].timetuple().tm_yday),
            "tmax": tmax,
            "tmin": tmin,
            "prec_mm": max(0.0, float(row["P_F"])),
            # VPD_F is in hPa; store raw — convert to Pa in convert_to_bgc_met
            "vpd_hpa": max(0.0, float(row["VPD_F"])),
            "srad": max(0.0, float(row["SW_IN_F"])),
        })
    return records


def main():
    parser = argparse.ArgumentParser(
        description="Convert VIC forcing or FLUXNET FULLSET_DD to BIOME-BGC met format")
    parser.add_argument("--forcing_file", required=True,
                        help="VIC forcing file (7-col ASCII) or FLUXNET FULLSET_DD.csv")
    parser.add_argument("--source", default="vic",
                        choices=["vic", "fluxnet"],
                        help="Input format: 'vic' (default) or 'fluxnet' (FULLSET_DD.csv)")
    parser.add_argument("--lat", type=float, required=True,
                        help="Site latitude (degrees)")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--steps_per_day", type=int, default=8,
                        help="Sub-daily timesteps per day (VIC only, default 8)")
    parser.add_argument("--pressure", type=float, default=101325.0,
                        help="Surface pressure (Pa) for VPD calculation (VIC only)")
    parser.add_argument("--output", required=True,
                        help="Output met file path")

    args = parser.parse_args()

    # Validate input file exists
    if not os.path.isfile(args.forcing_file):
        result = {"status": "error", "stage": "input_validation",
                  "message": f"Forcing file not found: {args.forcing_file}"}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Read and aggregate
    try:
        if args.source == "fluxnet":
            daily_records = read_fluxnet_forcing(
                args.forcing_file, args.start_year, args.end_year)
            # For FLUXNET, VPD is already known (hPa) — patch convert_to_bgc_met
            # to use vpd_hpa directly instead of computing from q
            for r in daily_records:
                r["q"] = 0.0  # unused sentinel; VPD computed from vpd_hpa below
        else:
            daily_records = read_vic_forcing(
                args.forcing_file, args.start_year, args.end_year,
                args.steps_per_day)
    except Exception as e:
        result = {"status": "error", "stage": "processing",
                  "message": f"Failed to read forcing: {e}"}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    if not daily_records:
        result = {"status": "error", "stage": "processing",
                  "message": "No daily records after filtering by year range"}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Convert
    try:
        met_lines = convert_to_bgc_met(daily_records, args.lat, args.pressure)
    except Exception as e:
        result = {"status": "error", "stage": "processing",
                  "message": f"Conversion failed: {e}"}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Validate output
    warnings = validate_output(met_lines, daily_records)

    # Write with MTCLIM-compatible header
    try:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        n_years = args.end_year - args.start_year + 1
        header_lines = [
            f"HydroCraft BIOME-BGC met file, lat={args.lat:.2f}",
            f"Generated from VIC forcing: {Path(args.forcing_file).name}",
            f"  year  yday    Tmax    Tmin    Tday    prcp      VPD     srad  daylen",
            f"             (deg C) (deg C) (deg C)    (cm)     (Pa)  (W m-2)     (s)",
        ]

        with open(out_path, 'w') as f:
            for h in header_lines:
                f.write(h + "\n")
            for line in met_lines:
                f.write(line + "\n")
    except Exception as e:
        result = {"status": "error", "stage": "output",
                  "message": f"Failed to write: {e}"}
        print(json.dumps(result, indent=2))
        sys.exit(3)

    # Compute summary stats
    years = sorted(set(r["year"] for r in daily_records))
    mean_annual_prec_mm = sum(r["prec_mm"] for r in daily_records) / len(years)

    result = {
        "status": "success",
        "output_file": str(out_path),
        "n_days": len(daily_records),
        "n_years": len(years),
        "year_range": f"{years[0]}-{years[-1]}",
        "header_lines": len(header_lines),
        "latitude": args.lat,
        "mean_annual_precip_mm": round(mean_annual_prec_mm, 1),
        "mean_annual_precip_cm": round(mean_annual_prec_mm / 10.0, 1),
        "tmax_range": [round(min(r["tmax"] for r in daily_records), 1),
                       round(max(r["tmax"] for r in daily_records), 1)],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
