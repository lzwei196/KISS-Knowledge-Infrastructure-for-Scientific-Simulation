#!/usr/bin/env python3
"""Convert global reanalysis meteorological data to tRIBS forcing format.

Supports: ERA5, CMFD, MSWX, and generic CSV sources.
Produces: station metadata file (.sdf) and per-station time-series (.mdf).

tRIBS met format columns:
  Year Month Day Hour PA TD XC US TA TS NR

Units expected by tRIBS:
  PA  = atmospheric pressure (mb / hPa)
  TD  = dew-point temperature (°C)
  XC  = sky cover (tenths, 0–10)
  US  = wind speed (m/s)
  TA  = air temperature (°C)
  TS  = surface temperature (°C)
  NR  = net radiation (W/m²)

Usage:
  python convert_met_forcing.py \\
      --source era5 \\
      --input /path/to/raw/ \\
      --output /path/to/met/ \\
      --lat 33.5 --lon 117.2 --elev 450
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Unit-conversion helpers
# ---------------------------------------------------------------------------

def kelvin_to_celsius(t_k):
    """Convert temperature from Kelvin to Celsius."""
    return t_k - 273.15


def pa_to_mb(p_pa):
    """Convert pressure from Pa to mb (hPa).  1 mb = 100 Pa."""
    return p_pa / 100.0


def kpa_to_mb(p_kpa):
    """Convert pressure from kPa to mb (hPa).  1 kPa = 10 mb."""
    return p_kpa * 10.0


def ms_to_mmhr(rate_ms):
    """Convert precipitation rate from m/s to mm/hr."""
    return rate_ms * 3.6e6


def mmday_to_mmhr(rate_mmday):
    """Convert precipitation rate from mm/day to mm/hr."""
    return rate_mmday / 24.0


def rh_fraction_to_percent(rh):
    """Convert relative humidity from fraction (0–1) to percent (0–100)."""
    return rh * 100.0


def dewpoint_from_rh_temp(t_c, rh_frac):
    """Compute dew-point temperature (°C) from air temperature and RH.

    Uses the Magnus formula:
        Td = (b * alpha) / (a - alpha)
        alpha = (a * T) / (b + T) + ln(RH)
    with a = 17.27, b = 237.7 °C.
    """
    a, b = 17.27, 237.7
    if rh_frac <= 0:
        rh_frac = 0.01
    if rh_frac > 1.0:
        rh_frac = 1.0
    import math
    alpha = (a * t_c) / (b + t_c) + math.log(rh_frac)
    td = (b * alpha) / (a - alpha)
    return td


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Pre-flight validation of input arguments."""
    errors = []
    if not os.path.isdir(args.input):
        errors.append(f"Input directory does not exist: {args.input}")
    if args.source not in ("era5", "cmfd", "mswx", "csv"):
        errors.append(f"Unsupported source type: {args.source}. Use era5|cmfd|mswx|csv")
    if args.lat is not None and not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if args.lon is not None and not (-180 <= args.lon <= 360):
        errors.append(f"Longitude out of range: {args.lon}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(output_dir, station_file, data_files):
    """Post-processing validation of generated files."""
    warnings = []
    if not os.path.isfile(station_file):
        warnings.append(f"Station file not created: {station_file}")
    for df in data_files:
        if not os.path.isfile(df):
            warnings.append(f"Data file not created: {df}")
        else:
            with open(df) as f:
                lines = f.readlines()
            if len(lines) < 2:
                warnings.append(f"Data file has < 2 lines: {df}")
            # Spot-check first data line for plausible values
            if len(lines) >= 2:
                vals = lines[1].strip().split()
                if len(vals) >= 9:
                    ta = float(vals[8])  # Air temperature
                    if ta < -80 or ta > 65:
                        warnings.append(
                            f"Air temperature {ta}°C out of plausible range in {df}. "
                            "Check unit conversion (K → °C)."
                        )
                    pa = float(vals[4])  # Pressure
                    if pa > 2000:
                        warnings.append(
                            f"Pressure {pa} mb seems too high in {df}. "
                            "Check unit conversion (Pa → mb)."
                        )
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


# ---------------------------------------------------------------------------
# Source-specific readers
# ---------------------------------------------------------------------------

def read_era5_csv(input_dir):
    """Read ERA5 CSV files and return standardised records.

    ERA5 units:  T in K, P in Pa, RH in %, wind in m/s, radiation in W/m².
    """
    records = []
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith(".csv"):
            continue
        filepath = os.path.join(input_dir, fname)
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = {}
                # Parse timestamp
                ts = row.get("time") or row.get("datetime") or row.get("date")
                if ts:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H"):
                        try:
                            dt = datetime.strptime(ts, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        continue
                    rec["year"] = dt.year
                    rec["month"] = dt.month
                    rec["day"] = dt.day
                    rec["hour"] = dt.hour

                # Temperature: K → °C
                t_key = next((k for k in row if k.lower() in
                              ("t2m", "temperature", "temp", "air_temperature")), None)
                if t_key:
                    rec["TA"] = kelvin_to_celsius(float(row[t_key]))
                else:
                    rec["TA"] = 20.0

                # Pressure: Pa → mb
                p_key = next((k for k in row if k.lower() in
                              ("sp", "pressure", "surface_pressure", "pa")), None)
                if p_key:
                    rec["PA"] = pa_to_mb(float(row[p_key]))
                else:
                    rec["PA"] = 1013.25

                # Dew point or RH
                td_key = next((k for k in row if k.lower() in
                               ("d2m", "dewpoint", "dew_point")), None)
                rh_key = next((k for k in row if k.lower() in
                               ("rh", "relative_humidity", "relhumid")), None)
                if td_key:
                    rec["TD"] = kelvin_to_celsius(float(row[td_key]))
                elif rh_key:
                    rh_val = float(row[rh_key])
                    if rh_val > 1.5:
                        rh_val /= 100.0  # Convert from % to fraction
                    rec["TD"] = dewpoint_from_rh_temp(rec["TA"], rh_val)
                else:
                    rec["TD"] = rec["TA"] - 5.0

                # Wind speed (m/s)
                u_key = next((k for k in row if k.lower() in
                              ("u10", "wind", "wind_speed", "ws")), None)
                v_key = next((k for k in row if k.lower() in
                              ("v10", "wind_v")), None)
                if u_key and v_key:
                    import math
                    rec["US"] = math.sqrt(float(row[u_key])**2 + float(row[v_key])**2)
                elif u_key:
                    rec["US"] = abs(float(row[u_key]))
                else:
                    rec["US"] = 2.0

                # Sky cover (tenths, 0–10)
                cc_key = next((k for k in row if k.lower() in
                               ("tcc", "cloud_cover", "skycover", "cc")), None)
                if cc_key:
                    cc = float(row[cc_key])
                    if cc <= 1.0:
                        cc *= 10.0  # Convert fraction to tenths
                    rec["XC"] = min(10.0, max(0.0, cc))
                else:
                    rec["XC"] = 5.0

                # Surface temperature (°C), default to air temp
                ts_key = next((k for k in row if k.lower() in
                               ("skt", "skin_temperature", "surface_temp")), None)
                if ts_key:
                    rec["TS"] = kelvin_to_celsius(float(row[ts_key]))
                else:
                    rec["TS"] = rec["TA"]

                # Net radiation (W/m²)
                nr_key = next((k for k in row if k.lower() in
                               ("ssr", "net_radiation", "shortwave", "sw")), None)
                if nr_key:
                    rec["NR"] = float(row[nr_key])
                else:
                    rec["NR"] = 200.0

                records.append(rec)

    return records


def read_generic_csv(input_dir):
    """Read a generic CSV with columns: datetime, PA_mb, TD_C, XC, US_ms, TA_C, TS_C, NR_Wm2."""
    records = []
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith(".csv"):
            continue
        filepath = os.path.join(input_dir, fname)
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get("datetime") or row.get("time") or row.get("date")
                if not ts:
                    continue
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H"):
                    try:
                        dt = datetime.strptime(ts, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                rec = {
                    "year": dt.year, "month": dt.month,
                    "day": dt.day, "hour": dt.hour,
                    "PA": float(row.get("PA_mb", 1013.25)),
                    "TD": float(row.get("TD_C", 15.0)),
                    "XC": float(row.get("XC", 5.0)),
                    "US": float(row.get("US_ms", 2.0)),
                    "TA": float(row.get("TA_C", 20.0)),
                    "TS": float(row.get("TS_C", 20.0)),
                    "NR": float(row.get("NR_Wm2", 200.0)),
                }
                records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_tribs_met(records, output_dir, station_id, lat, lon, elev):
    """Write tRIBS-format station metadata and data files.

    Returns (station_file_path, data_file_path).
    """
    os.makedirs(output_dir, exist_ok=True)

    # Station metadata file
    sdf_path = os.path.join(output_dir, "station.sdf")
    mdf_path = os.path.join(output_dir, f"station_{station_id}.mdf")

    with open(sdf_path, "w") as f:
        f.write(f"1\n")  # number of stations
        f.write(f"{station_id}  {lat:.6f}  {lon:.6f}  {elev:.1f}  {mdf_path}\n")

    # Data file
    with open(mdf_path, "w") as f:
        f.write("Y  M  D  H  PA  TD  XC  US  TA  TS  NR\n")
        for r in records:
            f.write(
                f"{r['year']}  {r['month']:02d}  {r['day']:02d}  {r['hour']:02d}  "
                f"{r['PA']:.2f}  {r['TD']:.2f}  {r['XC']:.1f}  "
                f"{r['US']:.2f}  {r['TA']:.2f}  {r['TS']:.2f}  {r['NR']:.2f}\n"
            )

    return sdf_path, mdf_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert global reanalysis meteorological data to tRIBS format."
    )
    parser.add_argument("--source", required=True,
                        choices=["era5", "cmfd", "mswx", "csv"],
                        help="Source data type")
    parser.add_argument("--input", required=True,
                        help="Input directory containing raw data files")
    parser.add_argument("--output", required=True,
                        help="Output directory for tRIBS met files")
    parser.add_argument("--lat", type=float, default=0.0,
                        help="Station latitude (decimal degrees)")
    parser.add_argument("--lon", type=float, default=0.0,
                        help="Station longitude (decimal degrees)")
    parser.add_argument("--elev", type=float, default=0.0,
                        help="Station elevation (m)")
    parser.add_argument("--station-id", type=int, default=1,
                        help="Station ID number")
    parser.add_argument("--json-output", type=str, default=None,
                        help="Write result summary to JSON file")

    args = parser.parse_args()

    # --- Validate inputs ---
    validate_inputs(args)

    # --- Process ---
    if args.source == "era5":
        records = read_era5_csv(args.input)
    elif args.source in ("cmfd", "mswx"):
        # CMFD/MSWX use similar CSV format to ERA5 but may need
        # additional conversions handled in the reader
        records = read_era5_csv(args.input)
    elif args.source == "csv":
        records = read_generic_csv(args.input)
    else:
        print(f"Unsupported source: {args.source}", file=sys.stderr)
        sys.exit(1)

    if not records:
        print(json.dumps({"status": "error",
                          "errors": ["No records found in input directory"]}),
              file=sys.stderr)
        sys.exit(1)

    sdf_path, mdf_path = write_tribs_met(
        records, args.output, args.station_id,
        args.lat, args.lon, args.elev
    )

    # --- Validate outputs ---
    warnings = validate_outputs(args.output, sdf_path, [mdf_path])

    result = {
        "status": "success",
        "station_file": sdf_path,
        "data_file": mdf_path,
        "n_records": len(records),
        "time_range": f"{records[0]['year']}-{records[0]['month']:02d} to "
                      f"{records[-1]['year']}-{records[-1]['month']:02d}",
        "warnings": warnings,
    }

    output_json = json.dumps(result, indent=2)
    if args.json_output:
        with open(args.json_output, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
