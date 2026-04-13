#!/usr/bin/env python3
"""
convert_climate_to_monica.py — Convert global meteorological data to MONICA climate.csv

Supports input from:
  - Generic CSV (ERA5, MSWX, station data)
  - NetCDF point extraction (CMFD, ERA5-Land)

Performs unit conversions and writes semicolon-separated MONICA climate.csv
with the required 2-header-row format.

Usage:
    python convert_climate_to_monica.py --input forcing.csv --format generic_csv \
        --output climate.csv --date-col date --date-fmt "%Y-%m-%d" \
        --tavg-col Tmean --tmin-col Tmin --tmax-col Tmax \
        --precip-col Precip --wind-col Wind --globrad-col Radiation \
        --relhumid-col RH

    python convert_climate_to_monica.py --input era5.nc --format netcdf \
        --output climate.csv --lat 52.8 --lon 13.8 \
        --start-date 1991-01-01 --end-date 2000-12-31
"""

import argparse
import json
import os
import sys
import csv
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def w_m2_to_mj_m2_day(sw):
    """Convert W m⁻² (mean daily) to MJ m⁻² d⁻¹."""
    return sw * 0.0864

def j_cm2_to_mj_m2_day(rad):
    """Convert J cm⁻² to MJ m⁻² d⁻¹ (divide by 100)."""
    return rad / 100.0

def kj_m2_to_mj_m2_day(rad):
    """Convert kJ m⁻² to MJ m⁻² d⁻¹."""
    return rad / 1000.0

def kmh_to_ms(wind):
    """Convert km h⁻¹ to m s⁻¹."""
    return wind / 3.6

def frac_to_pct(rh):
    """Convert RH fraction [0–1] to percent [0–100]."""
    return rh * 100.0

def m_to_mm(precip):
    """Convert precipitation m d⁻¹ to mm d⁻¹."""
    return precip * 1000.0

def kpa_to_mmhg(vp):
    """Convert kPa to mm Hg."""
    return vp * 7.50062

UNIT_CONVERTERS = {
    "globrad": {
        "W_m2":   w_m2_to_mj_m2_day,
        "J_cm2":  j_cm2_to_mj_m2_day,
        "kJ_m2":  kj_m2_to_mj_m2_day,
    },
    "wind": {
        "km_h": kmh_to_ms,
    },
    "relhumid": {
        "fraction": frac_to_pct,
    },
    "precip": {
        "m": m_to_mm,
    },
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments before processing."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.format == "netcdf":
        if args.lat is None or args.lon is None:
            errors.append("--lat and --lon required for NetCDF input")
    if args.format == "generic_csv":
        for req in ["tavg_col", "tmin_col", "tmax_col", "precip_col"]:
            if getattr(args, req) is None:
                errors.append(f"--{req.replace('_', '-')} is required for generic_csv format")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(df_rows, output_path):
    """Validate the generated climate.csv for physical plausibility."""
    warnings = []
    if len(df_rows) == 0:
        warnings.append("Output file has zero data rows")
        return warnings

    for i, row in enumerate(df_rows):
        tavg = row.get("tavg")
        tmin = row.get("tmin")
        tmax = row.get("tmax")
        precip = row.get("precip")
        globrad = row.get("globrad")
        relhumid = row.get("relhumid")
        wind = row.get("wind")

        if tavg is not None and (tavg < -60 or tavg > 60):
            warnings.append(f"Row {i}: tavg={tavg} outside [-60, 60] °C")
        if tmin is not None and tmax is not None and tmin > tmax:
            warnings.append(f"Row {i}: tmin ({tmin}) > tmax ({tmax})")
        if precip is not None and (precip < 0 or precip > 500):
            warnings.append(f"Row {i}: precip={precip} outside [0, 500] mm")
        if globrad is not None and (globrad < 0 or globrad > 50):
            warnings.append(f"Row {i}: globrad={globrad} outside [0, 50] MJ m-2 d-1")
        if relhumid is not None and (relhumid < 0 or relhumid > 100):
            warnings.append(f"Row {i}: relhumid={relhumid} — suspect fraction instead of %. "
                            "Use --relhumid-unit fraction to auto-convert.")
        if wind is not None and wind < 0:
            warnings.append(f"Row {i}: wind={wind} is negative")

        if len(warnings) > 20:
            warnings.append("... (truncated, too many warnings)")
            break

    if os.path.isfile(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        warnings.append(f"Output size: {size_kb:.1f} KB, {len(df_rows)} rows")

    return warnings


# ---------------------------------------------------------------------------
# Processing — generic CSV
# ---------------------------------------------------------------------------

def process_generic_csv(args):
    """Read a generic CSV and convert to MONICA climate rows."""
    rows = []
    with open(args.input, "r", newline="") as f:
        sep = args.csv_sep or ","
        reader = csv.DictReader(f, delimiter=sep)
        for rec in reader:
            try:
                dt = datetime.strptime(rec[args.date_col].strip(), args.date_fmt)
            except (KeyError, ValueError) as e:
                print(f"Warning: skipping row, date parse error: {e}", file=sys.stderr)
                continue

            tavg = float(rec[args.tavg_col])
            tmin = float(rec[args.tmin_col])
            tmax = float(rec[args.tmax_col])
            precip = float(rec[args.precip_col])

            # Optional columns with defaults
            wind = float(rec.get(args.wind_col, 2.0)) if args.wind_col and args.wind_col in rec else 2.0
            globrad_raw = float(rec.get(args.globrad_col, 10.0)) if args.globrad_col and args.globrad_col in rec else 10.0
            relhumid_raw = float(rec.get(args.relhumid_col, 70.0)) if args.relhumid_col and args.relhumid_col in rec else 70.0
            sunhours = float(rec.get(args.sunhours_col, -1)) if args.sunhours_col and args.sunhours_col in rec else -1

            # Apply unit conversions
            globrad = globrad_raw
            if args.globrad_unit and args.globrad_unit in UNIT_CONVERTERS.get("globrad", {}):
                globrad = UNIT_CONVERTERS["globrad"][args.globrad_unit](globrad_raw)

            if args.wind_unit and args.wind_unit in UNIT_CONVERTERS.get("wind", {}):
                wind = UNIT_CONVERTERS["wind"][args.wind_unit](wind)

            relhumid = relhumid_raw
            if args.relhumid_unit and args.relhumid_unit in UNIT_CONVERTERS.get("relhumid", {}):
                relhumid = UNIT_CONVERTERS["relhumid"][args.relhumid_unit](relhumid_raw)

            if args.precip_unit and args.precip_unit in UNIT_CONVERTERS.get("precip", {}):
                precip = UNIT_CONVERTERS["precip"][args.precip_unit](precip)

            # Clamp
            globrad = max(0.0, globrad)
            relhumid = max(0.0, min(100.0, relhumid))
            precip = max(0.0, precip)

            rows.append({
                "date": dt,
                "tavg": round(tavg, 2),
                "tmin": round(tmin, 2),
                "tmax": round(tmax, 2),
                "wind": round(wind, 2),
                "globrad": round(globrad, 4),
                "precip": round(precip, 2),
                "relhumid": round(relhumid, 1),
                "sunhours": round(sunhours, 1) if sunhours >= 0 else "",
            })
    return rows


def process_netcdf(args):
    """Extract point timeseries from NetCDF and convert to MONICA climate rows."""
    try:
        import netCDF4
        import numpy as np
    except ImportError:
        print(json.dumps({"status": "error",
                          "errors": ["netCDF4 and numpy required for NetCDF input. "
                                     "pip install netCDF4 numpy"]}),
              file=sys.stderr)
        sys.exit(1)

    ds = netCDF4.Dataset(args.input, "r")
    # Find nearest grid cell
    lats = ds.variables["lat"][:]
    lons = ds.variables["lon"][:]
    lat_idx = int(np.argmin(np.abs(lats - args.lat)))
    lon_idx = int(np.argmin(np.abs(lons - args.lon)))

    time_var = ds.variables["time"]
    times = netCDF4.num2date(time_var[:], time_var.units, time_var.calendar)

    # Try common variable names
    var_map = {
        "tavg": ["t2m", "tmp", "tavg", "Tmean", "tas"],
        "tmin": ["tmin", "mn2t", "tasmin"],
        "tmax": ["tmax", "mx2t", "tasmax"],
        "precip": ["tp", "precip", "pr", "prate"],
        "wind": ["wind", "u10", "sfcWind", "ws"],
        "globrad": ["ssrd", "rsds", "srad", "swdown"],
        "relhumid": ["rh", "relhumid", "hurs"],
    }

    def find_var(nc, candidates):
        for c in candidates:
            if c in nc.variables:
                return c
        return None

    rows = []
    for ti in range(len(times)):
        dt = times[ti]
        if isinstance(dt, (int, float)):
            continue
        dt_py = datetime(dt.year, dt.month, dt.day)
        if args.start_date and dt_py < datetime.strptime(args.start_date, "%Y-%m-%d"):
            continue
        if args.end_date and dt_py > datetime.strptime(args.end_date, "%Y-%m-%d"):
            continue

        row = {"date": dt_py}
        for monica_var, candidates in var_map.items():
            vname = find_var(ds, candidates)
            if vname:
                val = float(ds.variables[vname][ti, lat_idx, lon_idx])
                # Auto-detect K→C for temperature
                if monica_var in ("tavg", "tmin", "tmax") and val > 200:
                    val -= 273.15
                # Auto-detect W m⁻² for radiation
                if monica_var == "globrad" and val > 100:
                    val = w_m2_to_mj_m2_day(val)
                # Auto-detect fraction for RH
                if monica_var == "relhumid" and val <= 1.0:
                    val = frac_to_pct(val)
                # Auto-detect m for precip
                if monica_var == "precip" and val < 0.5 and val > 0:
                    val = m_to_mm(val)
                row[monica_var] = round(val, 4)
            else:
                row[monica_var] = ""
        row.setdefault("sunhours", "")
        rows.append(row)

    ds.close()
    return rows


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_monica_csv(rows, output_path, date_format="iso"):
    """Write MONICA-format climate.csv with 2 header rows."""
    columns = ["iso-date", "tavg", "tmin", "tmax", "wind", "globrad", "precip", "relhumid"]
    has_sunhours = any(r.get("sunhours", "") != "" for r in rows)
    if has_sunhours:
        columns.append("sunhours")

    units = {
        "iso-date": "",
        "tavg": "C_deg",
        "tmin": "C_deg",
        "tmax": "C_deg",
        "wind": "m/s",
        "globrad": "MJ_m-2",
        "precip": "mm",
        "relhumid": "%",
        "sunhours": "hours",
    }

    with open(output_path, "w", newline="") as f:
        # Header row 1: names
        f.write(";".join(columns) + "\n")
        # Header row 2: units
        f.write(";".join(units[c] for c in columns) + "\n")
        # Data rows
        for row in rows:
            vals = []
            for c in columns:
                if c == "iso-date":
                    vals.append(row["date"].strftime("%Y-%m-%d"))
                else:
                    v = row.get(c, "")
                    vals.append(str(v) if v != "" else "")
            f.write(";".join(vals) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to MONICA climate.csv format")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--format", choices=["generic_csv", "netcdf"], default="generic_csv")
    parser.add_argument("--output", required=True, help="Output climate.csv path")
    parser.add_argument("--csv-sep", default=",", help="CSV separator for generic_csv")
    parser.add_argument("--date-col", default="date", help="Date column name")
    parser.add_argument("--date-fmt", default="%Y-%m-%d", help="Date format string")
    parser.add_argument("--tavg-col", help="Mean temperature column")
    parser.add_argument("--tmin-col", help="Min temperature column")
    parser.add_argument("--tmax-col", help="Max temperature column")
    parser.add_argument("--precip-col", help="Precipitation column")
    parser.add_argument("--wind-col", help="Wind speed column")
    parser.add_argument("--globrad-col", help="Global radiation column")
    parser.add_argument("--relhumid-col", help="Relative humidity column")
    parser.add_argument("--sunhours-col", help="Sunshine hours column")
    parser.add_argument("--globrad-unit", choices=["W_m2", "J_cm2", "kJ_m2"],
                        help="Source radiation unit for auto-conversion")
    parser.add_argument("--wind-unit", choices=["km_h"],
                        help="Source wind unit for auto-conversion")
    parser.add_argument("--relhumid-unit", choices=["fraction"],
                        help="Source RH unit for auto-conversion")
    parser.add_argument("--precip-unit", choices=["m"],
                        help="Source precipitation unit for auto-conversion")
    parser.add_argument("--lat", type=float, help="Latitude for NetCDF extraction")
    parser.add_argument("--lon", type=float, help="Longitude for NetCDF extraction")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD")

    args = parser.parse_args()
    validate_inputs(args)

    if args.format == "generic_csv":
        rows = process_generic_csv(args)
    elif args.format == "netcdf":
        rows = process_netcdf(args)
    else:
        print(json.dumps({"status": "error", "errors": [f"Unknown format: {args.format}"]}),
              file=sys.stderr)
        sys.exit(1)

    write_monica_csv(rows, args.output)
    warnings = validate_outputs(rows, args.output)

    result = {
        "status": "success",
        "output": args.output,
        "n_rows": len(rows),
        "date_range": [rows[0]["date"].isoformat(), rows[-1]["date"].isoformat()] if rows else [],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
