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
  - Shortwave: BIOME-BGC wants the DAYLIGHT-average flux (metv.swavgfd), not the
    24-h mean that every daily forcing product carries -> x 86400/daylen [dt_027]

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


def convert_to_bgc_met(daily_records, lat, pressure=101325.0,
                       srad_is_daylight_avg=False):
    """
    Convert daily records to BIOME-BGC met format lines.

    CRITICAL CONVERSIONS:
    - prec: mm -> cm (divide by 10)
    - VPD: computed in Pa from q and T
    - Tday: approximated as Tmin + 0.45*(Tmax-Tmin)
    - daylen: computed from latitude and yday (seconds)
    - srad: BIOME-BGC's met column 8 is metv.swavgfd, the DAYLIGHT-AVERAGE
      shortwave flux density (bgc_struct.h; users guide "met file" item 8;
      MTCLIM output). VIC/CMFD/MSWX/NASA POWER/FLUXNET daily radiation is a
      24-h mean, so it is scaled by 86400/daylen here (same daily energy,
      spread over the daylight period). Feeding the 24-h mean under-forces
      photosynthesis by ~1.5x in summer and ~3x in winter at mid-latitudes
      (dt_027). Pass srad_is_daylight_avg=True ONLY for MTCLIM-style input.
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

        # CRITICAL: Day length in seconds, computed from latitude
        dayl = compute_daylength(lat, r["yday"])

        # CRITICAL: shortwave must be the DAYLIGHT average, not the 24-h mean.
        # Daily energy is conserved: W/m2 (24 h) * 86400 s / daylen s.
        srad = max(0.0, r["srad"])
        if not srad_is_daylight_avg and dayl > 0:
            srad = srad * 86400.0 / dayl

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
    if any(r["tmax"] < r["tmin"] for r in daily_records):
        warnings.append("Tmax < Tmin on some days -- columns swapped or proxies used?")

    # Check the written daylight-average shortwave (column 8): a daylight
    # average can never exceed the solar constant; > 1200 W/m2 means the
    # input was ALREADY a daylight average and got scaled twice.
    srad_out = [float(line.split()[7]) for line in met_lines]
    if srad_out and max(srad_out) > 1200:
        warnings.append(
            f"Max daylight-average srad = {max(srad_out):.0f} W/m2 (> 1200). "
            "Input was probably already a daylight average (MTCLIM-style); "
            "re-run with --srad_is_daylight_avg.")

    return warnings


FLUXNET_HH_COLS = ["TIMESTAMP_START", "TA_F", "P_F", "VPD_F", "SW_IN_F", "SW_IN_POT"]


def _fluxnet_hh_path(filepath: str):
    """Sibling FULLSET_HH.csv of a FULLSET_DD.csv (or the file itself if it is HH)."""
    p = Path(filepath)
    if "_HH" in p.name:
        return p
    cand = p.with_name(p.name.replace("_DD", "_HH"))
    return cand if cand.is_file() and cand != p else None


def read_fluxnet_forcing(filepath: str, start_year: int, end_year: int,
                         use_hh: bool = True):
    """
    Read FLUXNET2015 and return daily records for BIOME-BGC.

    BIOME-BGC's met columns are defined (bgc_users_guide, "met file") as the
    DAILY MAXIMUM / MINIMUM temperature, the DAYLIGHT-AVERAGE VPD and the
    DAYLIGHT-AVERAGE shortwave flux -- i.e. MTCLIM output. The half-hourly
    FULLSET_HH.csv shipped next to every FULLSET_DD.csv gives those exactly:
      TA_F      → Tmax = daily max, Tmin = daily min (°C)
      VPD_F     → VPD  = mean over daylight half-hours (SW_IN_POT > 0), hPa
      SW_IN_F   → 24-h mean W/m² (scaled to the daylight average later, dt_027)
      P_F       → mm per half-hour, summed to mm/day
    When the HH file is absent (or use_hh=False) the daily file is used with
    PROXIES and the caller is told so in the returned meta:
      TA_F_MDS_DAY / TA_F_MDS_NIGHT → day/night MEANS standing in for Tmax/Tmin
      VPD_F (24-h mean)             → stands in for the daylight average
    Both paths: -9999 → NaN → ffill/bfill; Feb-29 dropped (365-day model year).

    Returns (records, meta).
    """
    import pandas as pd
    hh_path = _fluxnet_hh_path(filepath) if use_hh else None
    meta = {"fluxnet_source": None, "tmax_tmin_basis": None, "vpd_basis": None}

    if hh_path is not None:
        hh = pd.read_csv(hh_path, usecols=lambda c: c in FLUXNET_HH_COLS, dtype=float)
        missing = [c for c in FLUXNET_HH_COLS if c not in hh.columns and c != "SW_IN_POT"]
        if missing:
            raise ValueError(f"Missing column(s) {missing} in {hh_path}")
        hh = hh.replace(-9999.0, float("nan"))
        t = pd.to_datetime(hh["TIMESTAMP_START"].astype("int64").astype(str), format="%Y%m%d%H%M")
        hh["_date"] = t.dt.floor("D")
        hh = hh[(hh["_date"].dt.year >= start_year) & (hh["_date"].dt.year <= end_year)]
        if "SW_IN_POT" in hh.columns:
            daylight = hh["SW_IN_POT"] > 0           # astronomical day, gap-free
        else:
            daylight = hh["SW_IN_F"] > 0
        g = hh.groupby("_date")
        df = pd.DataFrame({
            "tmax": g["TA_F"].max(),
            "tmin": g["TA_F"].min(),
            "prec_mm": g["P_F"].sum(min_count=1),
            "srad": g["SW_IN_F"].mean(),               # 24-h mean, daylight-scaled later
            "vpd_hpa": hh[daylight].groupby("_date")["VPD_F"].mean(),
        })
        df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"))
        df["_date"] = df.index
        meta.update(fluxnet_source=str(hh_path),
                    tmax_tmin_basis="daily max/min of half-hourly TA_F",
                    vpd_basis="mean of half-hourly VPD_F over daylight (SW_IN_POT>0)")
    else:
        df = pd.read_csv(filepath)
        df = df.replace(-9999.0, float("nan"))
        df["_date"] = pd.to_datetime(df["TIMESTAMP"], format="%Y%m%d")
        df = df[(df["_date"].dt.year >= start_year) & (df["_date"].dt.year <= end_year)]
        required = ["TA_F_MDS_DAY", "TA_F_MDS_NIGHT", "P_F", "VPD_F", "SW_IN_F"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing column {col} in FULLSET_DD — check file")
        df = df.rename(columns={"TA_F_MDS_DAY": "tmax", "TA_F_MDS_NIGHT": "tmin",
                                "P_F": "prec_mm", "VPD_F": "vpd_hpa", "SW_IN_F": "srad"})
        meta.update(fluxnet_source=str(filepath),
                    tmax_tmin_basis="PROXY: TA_F_MDS_DAY/NIGHT day- and night-time MEANS "
                                    "(no FULLSET_HH.csv found; diurnal range compressed)",
                    vpd_basis="PROXY: 24-h mean VPD_F (daylight average is higher)")

    # CRITICAL leap-day fix (dt root-cause): BIOME-BGC metarr_init.c reads EXACTLY
    # 365*nyears met lines sequentially and does NOT index by yday. Emitting 366
    # lines for a leap year shifts ALL subsequent forcing +1 day, drifting GPP out
    # of phase and tanking NSE on later years. Drop Feb-29 → 365 lines every year.
    df = df[~((df["_date"].dt.month == 2) & (df["_date"].dt.day == 29))]

    for col in ["tmax", "tmin", "prec_mm", "vpd_hpa", "srad"]:
        df[col] = df[col].ffill().bfill()

    records = []
    for _, row in df.iterrows():
        records.append({
            "year": int(row["_date"].year),
            "yday": int(row["_date"].timetuple().tm_yday),
            "tmax": float(row["tmax"]),
            "tmin": float(row["tmin"]),
            "prec_mm": max(0.0, float(row["prec_mm"])),
            # hPa; converted to Pa in convert_to_bgc_met
            "vpd_hpa": max(0.0, float(row["vpd_hpa"])),
            "srad": max(0.0, float(row["srad"])),
        })
    return records, meta


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
    parser.add_argument("--fluxnet_daily_only", action="store_true",
                        help="FLUXNET only: ignore the sibling FULLSET_HH.csv and use the "
                             "daily file's day/night-mean temperature and 24-h VPD PROXIES "
                             "(legacy behaviour; Tmax/Tmin/VPD no longer match the model's "
                             "definitions).")
    parser.add_argument("--srad_is_daylight_avg", action="store_true",
                        help="Set ONLY when the input shortwave is already a daylight "
                             "average (MTCLIM-style). By default the 24-h mean that "
                             "VIC/CMFD/MSWX/NASA POWER/FLUXNET daily files carry is "
                             "converted to BIOME-BGC's daylight average (x 86400/daylen).")
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
    source_meta = {}
    try:
        if args.source == "fluxnet":
            daily_records, source_meta = read_fluxnet_forcing(
                args.forcing_file, args.start_year, args.end_year,
                use_hh=not args.fluxnet_daily_only)
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
        met_lines = convert_to_bgc_met(daily_records, args.lat, args.pressure,
                                       srad_is_daylight_avg=args.srad_is_daylight_avg)
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
        "srad_basis": ("daylight average, input used as given"
                       if args.srad_is_daylight_avg else
                       "daylight average, converted from 24-h mean (x 86400/daylen)"),
        **source_meta,
        "srad_daylight_avg_range_Wm2": [
            round(min(float(l.split()[7]) for l in met_lines), 1),
            round(max(float(l.split()[7]) for l in met_lines), 1)],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
