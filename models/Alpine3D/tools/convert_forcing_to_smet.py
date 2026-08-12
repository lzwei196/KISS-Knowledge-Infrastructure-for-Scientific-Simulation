#!/usr/bin/env python3
"""
convert_forcing_to_smet.py — Convert meteorological forcing data to SMET format for Alpine3D.

Reads meteorological data from CSV or NetCDF (e.g., ERA5, station exports) and writes
SMET 1.1 ASCII files that Alpine3D/MeteoIO can ingest directly.

CRITICAL UNIT CONVERSIONS (Alpine3D uses MKSA/SI):
  - Temperature: Kelvin (NOT Celsius)
  - Relative humidity: fraction 0–1 (NOT percent 0–100)
  - Wind speed: m/s (NOT km/h)
  - Wind direction: degrees 0–360 (NOT radians)
  - Pressure: Pa (NOT hPa/mbar)
  - Precipitation: mm = kg/m² (NOT meters)
  - Radiation (ISWR, ILWR): W/m² (NOT MJ/m²/day)
  - Snow height: m (NOT cm)

Usage:
    python convert_forcing_to_smet.py \\
        --input era5_station.csv \\
        --output ./input/meteo/ \\
        --station-id WFJ2 \\
        --latitude 46.83 --longitude 9.81 --altitude 2540 \\
        --timezone 1 \\
        --temp-unit C --rh-unit percent --wind-unit m/s \\
        --pressure-unit hPa --precip-unit mm --radiation-unit W/m2

    python convert_forcing_to_smet.py \\
        --input era5_grid.nc \\
        --output ./input/meteo/ \\
        --format netcdf \\
        --station-id ERA5_pt1 \\
        --latitude 46.83 --longitude 9.81 --altitude 2540
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

# Optional NetCDF support
try:
    import netCDF4
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# SMET field names recognized by MeteoIO
SMET_FIELDS = [
    "timestamp", "TA", "RH", "VW", "DW", "VW_MAX",
    "ISWR", "ILWR", "PSUM", "PSUM_PH", "HS",
    "TSS", "TSG", "P"
]

# Default column mappings for common CSV formats
DEFAULT_CSV_MAPPING = {
    "timestamp": "timestamp",
    "TA": "TA",
    "RH": "RH",
    "VW": "VW",
    "DW": "DW",
    "ISWR": "ISWR",
    "ILWR": "ILWR",
    "PSUM": "PSUM",
    "HS": "HS",
    "P": "P",
}


def validate_inputs(args):
    """Validate command-line arguments before processing."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.latitude < -90 or args.latitude > 90:
        errors.append(f"Latitude out of range [-90, 90]: {args.latitude}")

    if args.longitude < -180 or args.longitude > 360:
        errors.append(f"Longitude out of range [-180, 360]: {args.longitude}")

    if args.altitude < -500 or args.altitude > 9000:
        errors.append(f"Altitude out of range [-500, 9000]: {args.altitude}")

    if args.format == "netcdf" and not HAS_NETCDF:
        errors.append("NetCDF format requested but netCDF4 package not installed")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def convert_temperature(values, source_unit):
    """Convert temperature to Kelvin."""
    if source_unit.upper() in ("C", "CELSIUS"):
        converted = [v + 273.15 if v is not None else None for v in values]
    elif source_unit.upper() in ("F", "FAHRENHEIT"):
        converted = [(v - 32) * 5.0 / 9.0 + 273.15 if v is not None else None for v in values]
    elif source_unit.upper() in ("K", "KELVIN"):
        converted = values
    else:
        raise ValueError(f"Unknown temperature unit: {source_unit}")
    return converted


def convert_rh(values, source_unit):
    """Convert relative humidity to fraction 0–1."""
    if source_unit.lower() in ("percent", "%", "pct"):
        converted = [v / 100.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("fraction", "frac", "0-1"):
        converted = values
    else:
        raise ValueError(f"Unknown RH unit: {source_unit}")
    return converted


def convert_wind(values, source_unit):
    """Convert wind speed to m/s."""
    if source_unit.lower() in ("km/h", "kmh", "kph"):
        converted = [v / 3.6 if v is not None else None for v in values]
    elif source_unit.lower() in ("m/s", "ms"):
        converted = values
    elif source_unit.lower() in ("kt", "knots"):
        converted = [v * 0.514444 if v is not None else None for v in values]
    elif source_unit.lower() in ("mph",):
        converted = [v * 0.44704 if v is not None else None for v in values]
    else:
        raise ValueError(f"Unknown wind unit: {source_unit}")
    return converted


def convert_wind_direction(values, source_unit):
    """Convert wind direction to degrees 0–360."""
    import math
    if source_unit.lower() in ("rad", "radians"):
        converted = [v * 180.0 / math.pi if v is not None else None for v in values]
    elif source_unit.lower() in ("deg", "degrees"):
        converted = values
    else:
        raise ValueError(f"Unknown wind direction unit: {source_unit}")
    return converted


def convert_pressure(values, source_unit):
    """Convert pressure to Pa."""
    if source_unit.lower() in ("hpa", "mbar"):
        converted = [v * 100.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("pa",):
        converted = values
    elif source_unit.lower() in ("kpa",):
        converted = [v * 1000.0 if v is not None else None for v in values]
    else:
        raise ValueError(f"Unknown pressure unit: {source_unit}")
    return converted


def convert_precip(values, source_unit):
    """Convert precipitation to mm (kg/m²)."""
    if source_unit.lower() in ("m", "meters"):
        converted = [v * 1000.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("mm", "kg/m2"):
        converted = values
    elif source_unit.lower() in ("cm",):
        converted = [v * 10.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("in", "inch", "inches"):
        # US networks (NRCS SNOTEL, NWS COOP) report precipitation in inches
        converted = [v * 25.4 if v is not None else None for v in values]
    else:
        raise ValueError(f"Unknown precipitation unit: {source_unit}")
    return converted


def apply_precip_undercatch(values, factor):
    """Multiply precipitation by a gauge-undercatch / orographic correction factor.

    Unshielded SNOTEL and weighing gauges systematically under-read solid
    precipitation; the deficit is severe (factor 1.5-2.3) at windy, deep
    MARITIME snow sites where a single station also misses orographic
    enhancement. Symptom: simulated peak SWE is a small fraction of an
    observed snow pillow (strong negative SWE PBIAS) even though timing
    (r) is reasonable. MeteoIO's `undercatch_wmo` filter only corrects a
    modest wind-dependent fraction and cannot recover this gap, so a direct
    multiplicative correction on the forcing is the documented remedy.
    See SKILL.md "Maritime sites" and triplets dt_020/dt_023.

    factor = 1.0 is a no-op (continental sites usually need none).
    """
    if factor == 1.0:
        return values
    return [v * factor if v is not None else None for v in values]


def disaggregate_daily_to_hourly(data, diurnal_amp=6.0, nodata=-999):
    """Expand DAILY records to the hourly SMET series Alpine3D needs.

    SNOWPACK integrates the surface energy balance sub-hourly, so a daily
    forcing series cannot be fed to Alpine3D directly. This implements the
    KI's validated single-station SNOTEL disaggregation (SKILL.md "Validated
    Test Cases"; the recipe previously lived only in the out-of-KI driver
    t3_runs/build_site.py, which is why every SNOTEL run had to bypass this
    tool):

      TA    sinusoidal cycle, min at 04:00 / max at 16:00, half-amplitude
            `diurnal_amp` K about the daily mean. `diurnal_amp` is CLIMATE
            DEPENDENT: ~6 K for continental sites, ~2.5 K for cloudy maritime
            ones, where 6 K pushes afternoon TA over the rain/snow threshold
            and melts the pack out months early (triplet dt_023).
      PSUM  daily total spread evenly over the 24 h (kg/m² per hour).
      RH    if absent, derived from the within-day TA excursion
            (0.95 - 0.07*(TA_h - TA_min), clipped to 0.30-0.95): moist at the
            cold night minimum, drier at the afternoon peak.
      VW    if absent, seasonal cycle 3.5 +/- 1.5 m/s peaking mid-January —
            this is what gives `undercatch_wmo` a realistic winter wind.
      DW    if absent, constant 270 deg.
      any other field is held constant across the 24 h of its day.

    Timestamps must be daily and ISO-8601 (YYYY-MM-DD[Thh:mm]). Returns a new
    data dict with 24x the records.
    """
    import math

    n_days = len(data["timestamp"])
    out = {f: [] for f in data}

    for d in range(n_days):
        ts_str = data["timestamp"][d].strip().replace(" ", "T")
        day = datetime.strptime(ts_str[:10], "%Y-%m-%d")

        ta_base = data.get("TA", [None] * n_days)[d] if data.get("TA") else None
        if ta_base is not None and ta_base != nodata:
            ta_day = [ta_base + diurnal_amp * math.sin(2 * math.pi * (h - 4) / 24.0 - math.pi / 2)
                      for h in range(24)]
            ta_min = min(ta_day)
        else:
            ta_day = [None] * 24
            ta_min = None

        psum_d = data.get("PSUM", [None] * n_days)[d] if data.get("PSUM") else None
        psum_h = (psum_d / 24.0) if (psum_d is not None and psum_d != nodata) else None

        doy = day.timetuple().tm_yday
        vw_seasonal = 3.5 + 1.5 * math.cos(2 * math.pi * (doy - 15) / 365.0)

        for h in range(24):
            out["timestamp"].append((day + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S"))
            for field in data:
                if field == "timestamp":
                    continue
                src = data[field]
                v = src[d] if d < len(src) else None
                if field == "TA":
                    out[field].append(ta_day[h])
                elif field == "PSUM":
                    out[field].append(psum_h)
                elif field == "RH" and v is None:
                    if ta_day[h] is None or ta_min is None:
                        out[field].append(0.7)
                    else:
                        out[field].append(max(0.30, min(0.95, 0.95 - 0.07 * (ta_day[h] - ta_min))))
                elif field == "VW" and v is None:
                    out[field].append(round(vw_seasonal, 3))
                elif field == "DW" and v is None:
                    out[field].append(270.0)
                else:
                    out[field].append(v)

    return out


def convert_radiation(values, source_unit):
    """Convert radiation to W/m²."""
    if source_unit.lower() in ("mj/m2/day", "mj/m2d"):
        converted = [v * 1e6 / 86400.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("w/m2", "wm2"):
        converted = values
    elif source_unit.lower() in ("kj/m2/h", "kj/m2h"):
        converted = [v * 1000.0 / 3600.0 if v is not None else None for v in values]
    else:
        raise ValueError(f"Unknown radiation unit: {source_unit}")
    return converted


def convert_snow_height(values, source_unit):
    """Convert snow height to meters."""
    if source_unit.lower() in ("cm",):
        converted = [v / 100.0 if v is not None else None for v in values]
    elif source_unit.lower() in ("m", "meters"):
        converted = values
    elif source_unit.lower() in ("mm",):
        converted = [v / 1000.0 if v is not None else None for v in values]
    else:
        raise ValueError(f"Unknown snow height unit: {source_unit}")
    return converted


def validate_output(data, nodata=-999):
    """Validate converted data for physical plausibility."""
    warnings = []

    if "TA" in data and data["TA"]:
        ta_valid = [v for v in data["TA"] if v is not None and v != nodata]
        if ta_valid:
            if min(ta_valid) < 200:
                warnings.append(f"TA min={min(ta_valid):.1f} K — likely still in Celsius!")
            if max(ta_valid) > 340:
                warnings.append(f"TA max={max(ta_valid):.1f} K — unrealistically high")

    if "RH" in data and data["RH"]:
        rh_valid = [v for v in data["RH"] if v is not None and v != nodata]
        if rh_valid:
            if max(rh_valid) > 1.5:
                warnings.append(f"RH max={max(rh_valid):.2f} — likely still in percent!")
            if min(rh_valid) < 0:
                warnings.append(f"RH min={min(rh_valid):.2f} — negative RH not physical")

    if "VW" in data and data["VW"]:
        vw_valid = [v for v in data["VW"] if v is not None and v != nodata]
        if vw_valid and max(vw_valid) > 50:
            warnings.append(f"VW max={max(vw_valid):.1f} m/s — likely still in km/h!")

    if "DW" in data and data["DW"]:
        dw_valid = [v for v in data["DW"] if v is not None and v != nodata]
        if dw_valid and max(dw_valid) < 10:
            warnings.append(f"DW max={max(dw_valid):.2f} — likely still in radians!")

    if "P" in data and data["P"]:
        p_valid = [v for v in data["P"] if v is not None and v != nodata]
        if p_valid and max(p_valid) < 2000:
            warnings.append(f"P max={max(p_valid):.0f} Pa — likely still in hPa!")

    if "ISWR" in data and data["ISWR"]:
        iswr_valid = [v for v in data["ISWR"] if v is not None and v != nodata]
        if iswr_valid and max(iswr_valid) < 50 and max(iswr_valid) > 0:
            warnings.append(f"ISWR max={max(iswr_valid):.1f} — likely in MJ/m²/day!")

    if "ILWR" in data and data["ILWR"]:
        ilwr_valid = [v for v in data["ILWR"] if v is not None and v != nodata]
        if ilwr_valid:
            mean_ilwr = sum(ilwr_valid) / len(ilwr_valid)
            if mean_ilwr < 100:
                warnings.append(f"ILWR mean={mean_ilwr:.1f} — likely in MJ/m²/day!")

    if "PSUM" in data and data["PSUM"]:
        psum_valid = [v for v in data["PSUM"] if v is not None and v != nodata and v > 0]
        if psum_valid and max(psum_valid) > 200:
            warnings.append(f"PSUM max={max(psum_valid):.1f} mm — check units!")

    return warnings


def read_csv_data(filepath, column_mapping=None):
    """Read meteorological data from a CSV file."""
    mapping = column_mapping or DEFAULT_CSV_MAPPING
    data = {field: [] for field in SMET_FIELDS}
    timestamps = []

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row.get(mapping.get("timestamp", "timestamp"), "")
            timestamps.append(ts_str)
            for field in SMET_FIELDS:
                if field == "timestamp":
                    continue
                col = mapping.get(field, field)
                if col in row and row[col].strip():
                    try:
                        data[field].append(float(row[col]))
                    except (ValueError, TypeError):
                        data[field].append(None)
                else:
                    data[field].append(None)

    data["timestamp"] = timestamps
    return data


def write_smet(filepath, station_id, latitude, longitude, altitude, timezone,
               fields, data, nodata=-999):
    """Write data to SMET 1.1 ASCII format."""
    # A column absent from the source CSV is still present in `data` as a
    # full-length list of None (read_csv_data pads every SMET_FIELD). Such a
    # list is TRUTHY, so the old `data[f]` test declared ~9 phantom fields in
    # the header and wrote a column of pure -999 for each. Require at least
    # one real value instead.
    active_fields = ["timestamp"] + [
        f for f in fields
        if f != "timestamp" and f in data and any(v is not None for v in data[f])
    ]

    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    with open(filepath, "w") as f:
        f.write("SMET 1.1 ASCII\n")
        f.write("[HEADER]\n")
        f.write(f"station_id       = {station_id}\n")
        f.write(f"latitude         = {latitude}\n")
        f.write(f"longitude        = {longitude}\n")
        f.write(f"altitude         = {altitude}\n")
        f.write(f"nodata           = {nodata}\n")
        f.write(f"tz               = {timezone}\n")
        f.write(f"fields           = {' '.join(active_fields)}\n")
        f.write("[DATA]\n")

        n_records = len(data["timestamp"])
        for i in range(n_records):
            ts = data["timestamp"][i]
            # Normalize timestamp to ISO 8601
            if " " in ts and "T" not in ts:
                ts = ts.replace(" ", "T")
            vals = [ts]
            for field in active_fields[1:]:
                v = data[field][i] if i < len(data[field]) else None
                if v is None:
                    vals.append(str(nodata))
                else:
                    vals.append(f"{v:.6f}")
            f.write(" ".join(vals) + "\n")


def process(args):
    """Main processing: read input, convert units, validate, write SMET."""
    # Read data
    if args.format == "csv":
        data = read_csv_data(args.input)
    elif args.format == "netcdf":
        raise NotImplementedError("NetCDF reading requires custom variable mapping. "
                                  "Use CSV intermediate format or extend this tool.")
    else:
        raise ValueError(f"Unknown format: {args.format}")

    # Apply unit conversions
    if data.get("TA") and any(v is not None for v in data["TA"]):
        data["TA"] = convert_temperature(data["TA"], args.temp_unit)

    if data.get("RH") and any(v is not None for v in data["RH"]):
        data["RH"] = convert_rh(data["RH"], args.rh_unit)

    if data.get("VW") and any(v is not None for v in data["VW"]):
        data["VW"] = convert_wind(data["VW"], args.wind_unit)

    if data.get("DW") and any(v is not None for v in data["DW"]):
        data["DW"] = convert_wind_direction(data["DW"], args.dw_unit)

    if data.get("P") and any(v is not None for v in data["P"]):
        data["P"] = convert_pressure(data["P"], args.pressure_unit)

    if data.get("PSUM") and any(v is not None for v in data["PSUM"]):
        data["PSUM"] = convert_precip(data["PSUM"], args.precip_unit)
        if getattr(args, "precip_undercatch_factor", 1.0) != 1.0:
            data["PSUM"] = apply_precip_undercatch(data["PSUM"], args.precip_undercatch_factor)
            print(f"Applied precip undercatch factor {args.precip_undercatch_factor} "
                  f"(maritime gauge/orographic correction)", file=sys.stderr)

    if data.get("ISWR") and any(v is not None for v in data["ISWR"]):
        data["ISWR"] = convert_radiation(data["ISWR"], args.radiation_unit)

    if data.get("ILWR") and any(v is not None for v in data["ILWR"]):
        data["ILWR"] = convert_radiation(data["ILWR"], args.radiation_unit)

    if data.get("HS") and any(v is not None for v in data["HS"]):
        data["HS"] = convert_snow_height(data["HS"], args.hs_unit)

    # Daily -> hourly disaggregation (must come AFTER unit conversion so the
    # RH derivation sees TA in Kelvin)
    if getattr(args, "daily_disaggregate", False):
        n_daily = len(data["timestamp"])
        data = disaggregate_daily_to_hourly(data, diurnal_amp=args.diurnal_amp,
                                            nodata=args.nodata)
        print(f"Disaggregated {n_daily} daily records -> {len(data['timestamp'])} hourly "
              f"(diurnal TA half-amplitude {args.diurnal_amp} K)", file=sys.stderr)

    # Validate output
    warnings = validate_output(data)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    # Write SMET file
    outpath = os.path.join(args.output, f"{args.station_id}.smet")
    write_smet(
        filepath=outpath,
        station_id=args.station_id,
        latitude=args.latitude,
        longitude=args.longitude,
        altitude=args.altitude,
        timezone=args.timezone,
        fields=SMET_FIELDS,
        data=data,
        nodata=args.nodata,
    )

    n_records = len(data["timestamp"])
    result = {
        "status": "success",
        "output": outpath,
        "n_records": n_records,
        "warnings": warnings,
        "fields_written": [f for f in SMET_FIELDS if f in data and data[f]],
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to SMET format for Alpine3D",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python convert_forcing_to_smet.py --input data.csv "
               "--output ./meteo/ --station-id WFJ2 --latitude 46.83 "
               "--longitude 9.81 --altitude 2540 --temp-unit C --rh-unit percent",
    )
    parser.add_argument("--input", required=True, help="Input file path (CSV or NetCDF)")
    parser.add_argument("--output", required=True, help="Output directory for SMET files")
    parser.add_argument("--format", default="csv", choices=["csv", "netcdf"],
                        help="Input format (default: csv)")
    parser.add_argument("--station-id", required=True, help="Station identifier")
    parser.add_argument("--latitude", type=float, required=True, help="Station latitude (WGS84)")
    parser.add_argument("--longitude", type=float, required=True, help="Station longitude (WGS84)")
    parser.add_argument("--altitude", type=float, required=True, help="Station altitude (m a.s.l.)")
    parser.add_argument("--timezone", type=float, default=0, help="Timezone offset from UTC")
    parser.add_argument("--nodata", type=float, default=-999, help="Nodata value (default: -999)")

    # Unit specification
    parser.add_argument("--temp-unit", default="K", choices=["K", "C", "F"],
                        help="Input temperature unit (default: K)")
    parser.add_argument("--rh-unit", default="fraction", choices=["fraction", "percent"],
                        help="Input RH unit (default: fraction)")
    parser.add_argument("--wind-unit", default="m/s", choices=["m/s", "km/h", "kt", "mph"],
                        help="Input wind speed unit (default: m/s)")
    parser.add_argument("--dw-unit", default="deg", choices=["deg", "rad"],
                        help="Input wind direction unit (default: deg)")
    parser.add_argument("--pressure-unit", default="Pa", choices=["Pa", "hPa", "kPa"],
                        help="Input pressure unit (default: Pa)")
    parser.add_argument("--precip-unit", default="mm", choices=["mm", "m", "cm", "in"],
                        help="Input precipitation unit (default: mm). Use 'in' for "
                             "US networks such as NRCS SNOTEL.")
    parser.add_argument("--precip-undercatch-factor", type=float, default=1.0,
                        help="Multiplicative gauge-undercatch/orographic correction on PSUM "
                             "(1.0 = none; maritime deep-snow sites typically need 1.5-2.3). "
                             "See triplets dt_020/dt_023.")
    parser.add_argument("--daily-disaggregate", action="store_true",
                        help="Input rows are DAILY: expand each to 24 hourly SMET "
                             "records (sinusoidal TA, PSUM spread evenly, RH/VW/DW "
                             "synthesised when absent). Alpine3D cannot run on daily "
                             "forcing. See disaggregate_daily_to_hourly().")
    parser.add_argument("--diurnal-amp", type=float, default=6.0,
                        help="Half-amplitude (K) of the synthetic diurnal TA cycle used "
                             "by --daily-disaggregate. ~6 for continental, ~2.5 for "
                             "cloudy maritime sites (triplet dt_023).")
    parser.add_argument("--radiation-unit", default="W/m2",
                        choices=["W/m2", "MJ/m2/day", "kJ/m2/h"],
                        help="Input radiation unit (default: W/m2)")
    parser.add_argument("--hs-unit", default="m", choices=["m", "cm", "mm"],
                        help="Input snow height unit (default: m)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
