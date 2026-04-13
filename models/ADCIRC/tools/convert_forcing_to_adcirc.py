#!/usr/bin/env python3
"""
convert_forcing_to_adcirc.py — Convert global meteorological data to ADCIRC OWI format.

Converts gridded wind and pressure data from common formats (GFS GRIB2, ERA5 netCDF,
CMFD netCDF, CSV) to ADCIRC's OWI (Oceanweather Inc.) format for NWS=12 forcing.

OWI format produces two files:
  - fort.221: Pressure field (atmospheric pressure in mb)
  - fort.222: Wind field (u,v wind velocity in m/s)

Unit conversions handled:
  - Pressure: Pa → mb (÷100), mb → m_H2O (×100/9806.65) done by ADCIRC internally
  - Wind speed: knots → m/s (×0.5144), km/h → m/s (÷3.6)
  - Coordinates: Ensures degrees format for ADCIRC spherical (ICS=2)

Usage:
    python convert_forcing_to_adcirc.py \
        --input_dir /path/to/met_data/ \
        --format era5_nc \
        --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
        --resolution 0.25 \
        --start_date 2005-08-25 --end_date 2005-09-01 \
        --output_dir ./

Output:
    fort.221 — pressure file in OWI format
    fort.222 — wind file in OWI format
    fort.22  — main control file (header referencing 221/222)
"""

import argparse
import datetime
import logging
import os
import sys

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KNOTS_TO_MS = 0.5144444
KMH_TO_MS = 1.0 / 3.6
PA_TO_MB = 0.01
STANDARD_PRESSURE_MB = 1013.25


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate all input parameters before processing."""
    errors = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")

    try:
        sw_lat, sw_lon = [float(x) for x in args.domain_sw.split(",")]
        ne_lat, ne_lon = [float(x) for x in args.domain_ne.split(",")]
    except (ValueError, AttributeError):
        errors.append("domain_sw and domain_ne must be 'lat,lon' format")
        sw_lat = sw_lon = ne_lat = ne_lon = 0

    if sw_lat >= ne_lat:
        errors.append(f"SW lat ({sw_lat}) must be < NE lat ({ne_lat})")
    if sw_lon >= ne_lon:
        errors.append(f"SW lon ({sw_lon}) must be < NE lon ({ne_lon})")

    if args.resolution <= 0:
        errors.append(f"Resolution must be > 0, got {args.resolution}")

    try:
        start = datetime.datetime.strptime(args.start_date, "%Y-%m-%d")
        end = datetime.datetime.strptime(args.end_date, "%Y-%m-%d")
        if start >= end:
            errors.append("start_date must be before end_date")
    except ValueError as e:
        errors.append(f"Date format error: {e}")

    if args.format not in ("era5_nc", "gfs_grib2", "cmfd_nc", "csv"):
        errors.append(f"Unsupported format: {args.format}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")

    return sw_lat, sw_lon, ne_lat, ne_lon, start, end


def validate_outputs(output_dir):
    """Validate that output files are well-formed."""
    errors = []

    for fname in ("fort.221", "fort.222", "fort.22"):
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            errors.append(f"Missing output file: {fpath}")
        elif os.path.getsize(fpath) == 0:
            errors.append(f"Empty output file: {fpath}")

    # Check fort.221 pressure values are in reasonable range (900-1100 mb)
    f221 = os.path.join(output_dir, "fort.221")
    if os.path.isfile(f221):
        try:
            values = _read_owi_values(f221)
            if len(values) > 0:
                pmin, pmax = np.min(values), np.max(values)
                if pmin < 850:
                    errors.append(
                        f"Pressure too low ({pmin:.1f} mb) — "
                        f"check if input is in Pa instead of mb"
                    )
                if pmax > 1100:
                    errors.append(
                        f"Pressure too high ({pmax:.1f} mb) — "
                        f"check unit conversion"
                    )
        except Exception:
            pass

    # Check fort.222 wind values are in reasonable range
    f222 = os.path.join(output_dir, "fort.222")
    if os.path.isfile(f222):
        try:
            values = _read_owi_values(f222)
            if len(values) > 0:
                wmax = np.max(np.abs(values))
                if wmax > 120:
                    errors.append(
                        f"Wind speed too high ({wmax:.1f} m/s) — "
                        f"check if input is in knots or km/h"
                    )
        except Exception:
            pass

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} output validation error(s)")

    logger.info("Output validation passed")


def _read_owi_values(filepath):
    """Read numeric values from an OWI-format file, skipping headers."""
    values = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("iLat") or line.startswith("Basin"):
                continue
            try:
                row_vals = [float(x) for x in line.split()]
                values.extend(row_vals)
            except ValueError:
                continue
    return np.array(values)


# ---------------------------------------------------------------------------
# Data readers (one per format)
# ---------------------------------------------------------------------------
def read_era5_nc(input_dir, sw_lat, sw_lon, ne_lat, ne_lon, start, end):
    """Read ERA5 netCDF forcing data.

    Expected variables: u10, v10 (m/s), msl (Pa)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        raise ImportError("netCDF4 required: pip install netCDF4")

    files = sorted(
        f for f in os.listdir(input_dir) if f.endswith(".nc")
    )
    if not files:
        raise FileNotFoundError(f"No .nc files found in {input_dir}")

    all_times, all_u10, all_v10, all_msl = [], [], [], []
    lats = lons = None

    for fname in files:
        fpath = os.path.join(input_dir, fname)
        with nc.Dataset(fpath) as ds:
            # Determine coordinate names
            lat_name = "latitude" if "latitude" in ds.variables else "lat"
            lon_name = "longitude" if "longitude" in ds.variables else "lon"

            lat = ds.variables[lat_name][:]
            lon = ds.variables[lon_name][:]

            # Subset domain
            lat_idx = np.where((lat >= sw_lat) & (lat <= ne_lat))[0]
            lon_idx = np.where((lon >= sw_lon) & (lon <= ne_lon))[0]
            if len(lat_idx) == 0 or len(lon_idx) == 0:
                continue

            if lats is None:
                lats = lat[lat_idx]
                lons = lon[lon_idx]

            # Read time
            time_var = ds.variables["time"]
            times = nc.num2date(time_var[:], time_var.units)

            # Read fields, subset to domain
            u10_key = "u10" if "u10" in ds.variables else "U10"
            v10_key = "v10" if "v10" in ds.variables else "V10"
            msl_key = "msl" if "msl" in ds.variables else "sp"

            u10 = ds.variables[u10_key][:, lat_idx[0]:lat_idx[-1]+1,
                                        lon_idx[0]:lon_idx[-1]+1]
            v10 = ds.variables[v10_key][:, lat_idx[0]:lat_idx[-1]+1,
                                        lon_idx[0]:lon_idx[-1]+1]
            msl = ds.variables[msl_key][:, lat_idx[0]:lat_idx[-1]+1,
                                        lon_idx[0]:lon_idx[-1]+1]

            # Unit conversion: ERA5 msl is Pa → convert to mb
            msl = msl * PA_TO_MB

            all_times.extend(times)
            all_u10.append(u10)
            all_v10.append(v10)
            all_msl.append(msl)

    if lats is None:
        raise ValueError("No data found in domain")

    u10 = np.concatenate(all_u10, axis=0)
    v10 = np.concatenate(all_v10, axis=0)
    msl = np.concatenate(all_msl, axis=0)

    # Ensure lats are ascending (south to north) for OWI
    if lats[0] > lats[-1]:
        lats = lats[::-1]
        u10 = u10[:, ::-1, :]
        v10 = v10[:, ::-1, :]
        msl = msl[:, ::-1, :]

    logger.info(
        f"Loaded ERA5: {len(all_times)} timesteps, "
        f"grid {len(lats)}x{len(lons)}, "
        f"pressure range {np.min(msl):.1f}-{np.max(msl):.1f} mb"
    )
    return all_times, lats, lons, u10, v10, msl


def read_csv(input_dir, sw_lat, sw_lon, ne_lat, ne_lon, start, end):
    """Read CSV forcing data with columns: time, lat, lon, u10, v10, pressure.

    Pressure assumed in mb. Wind in m/s.
    """
    import pandas as pd

    files = sorted(f for f in os.listdir(input_dir) if f.endswith(".csv"))
    if not files:
        raise FileNotFoundError(f"No .csv files found in {input_dir}")

    frames = []
    for fname in files:
        fpath = os.path.join(input_dir, fname)
        df = pd.read_csv(fpath, parse_dates=["time"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    # Filter domain and time
    mask = (
        (df["lat"] >= sw_lat) & (df["lat"] <= ne_lat) &
        (df["lon"] >= sw_lon) & (df["lon"] <= ne_lon) &
        (df["time"] >= start) & (df["time"] <= end)
    )
    df = df[mask].copy()

    if df.empty:
        raise ValueError("No data found in domain/time range")

    # Build regular grid
    lats = np.sort(df["lat"].unique())
    lons = np.sort(df["lon"].unique())
    times = sorted(df["time"].unique())

    nt, nlat, nlon = len(times), len(lats), len(lons)
    u10 = np.full((nt, nlat, nlon), np.nan)
    v10 = np.full((nt, nlat, nlon), np.nan)
    msl = np.full((nt, nlat, nlon), STANDARD_PRESSURE_MB)

    for ti, t in enumerate(times):
        tdf = df[df["time"] == t]
        for _, row in tdf.iterrows():
            li = np.searchsorted(lats, row["lat"])
            lj = np.searchsorted(lons, row["lon"])
            if li < nlat and lj < nlon:
                u10[ti, li, lj] = row["u10"]
                v10[ti, li, lj] = row["v10"]
                if "pressure" in row.index:
                    msl[ti, li, lj] = row["pressure"]

    # Fill NaN with standard atmosphere
    u10 = np.nan_to_num(u10, nan=0.0)
    v10 = np.nan_to_num(v10, nan=0.0)
    msl = np.nan_to_num(msl, nan=STANDARD_PRESSURE_MB)

    logger.info(f"Loaded CSV: {nt} timesteps, grid {nlat}x{nlon}")
    return [t for t in times], lats, lons, u10, v10, msl


# ---------------------------------------------------------------------------
# OWI writer
# ---------------------------------------------------------------------------
def write_owi_header(f, basin_name, start, end):
    """Write OWI file header line."""
    f.write(
        f"Basin Scale Fields for {basin_name} "
        f"starting at {start:%Y%m%d%H} "
        f"ending at {end:%Y%m%d%H}\n"
    )


def write_owi_snapshot(f, dt_obj, lats, lons, field, values_per_line=8):
    """Write one time snapshot in OWI format.

    Header line format:
        iLat iLong dx dy SWLat SWLon DT
    Then field values, 8 per line.
    """
    ilat = len(lats)
    ilon = len(lons)
    dx = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.25
    dy = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.25
    sw_lat = float(lats[0])
    sw_lon = float(lons[0])
    dt_str = dt_obj.strftime("%Y%m%d%H%M")

    f.write(
        f"iLat={ilat:4d}iLong={ilon:4d}DX={dx:6.4f}DY={dy:6.4f}"
        f"SWLat={sw_lat:8.4f}SWLon={sw_lon:9.4f}DT={dt_str}\n"
    )

    # Write field values row by row (south to north, west to east)
    values = field.flatten()
    for i in range(0, len(values), values_per_line):
        chunk = values[i:i + values_per_line]
        line = "".join(f"{v:10.4f}" for v in chunk)
        f.write(line + "\n")


def write_fort22_control(output_dir, start, end, n_snapshots):
    """Write the fort.22 control file for NWS=12 OWI format."""
    fpath = os.path.join(output_dir, "fort.22")
    with open(fpath, "w") as f:
        f.write(f"1\n")  # Number of basin-scale sets
        f.write(f"1\n")  # Number of region-scale sets (0 if none)
        f.write(f"fort.221\n")  # Pressure filename
        f.write(f"fort.222\n")  # Wind filename
    logger.info(f"Wrote {fpath}")


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------
def process(args):
    """Main processing: validate → read → convert → write → validate."""

    # Step 1: Validate inputs
    sw_lat, sw_lon, ne_lat, ne_lon, start, end = validate_inputs(args)

    # Step 2: Read source data
    logger.info(f"Reading {args.format} data from {args.input_dir}")
    if args.format == "era5_nc":
        times, lats, lons, u10, v10, msl = read_era5_nc(
            args.input_dir, sw_lat, sw_lon, ne_lat, ne_lon, start, end
        )
    elif args.format == "csv":
        times, lats, lons, u10, v10, msl = read_csv(
            args.input_dir, sw_lat, sw_lon, ne_lat, ne_lon, start, end
        )
    else:
        raise NotImplementedError(
            f"Format {args.format} reader not yet implemented. "
            f"Supported: era5_nc, csv"
        )

    # Step 3: Apply unit corrections
    # Wind — check if likely in knots (max > 80 m/s is suspicious)
    wmax = max(np.max(np.abs(u10)), np.max(np.abs(v10)))
    if wmax > 80:
        logger.warning(
            f"Max wind {wmax:.1f} m/s is very high — "
            f"assuming knots, converting to m/s"
        )
        u10 *= KNOTS_TO_MS
        v10 *= KNOTS_TO_MS

    # Pressure — check if in Pa (values > 50000 are Pa, not mb)
    pmax = np.max(msl)
    if pmax > 50000:
        logger.warning(
            f"Max pressure {pmax:.0f} — assuming Pa, converting to mb"
        )
        msl *= PA_TO_MB

    # Step 4: Write OWI files
    os.makedirs(args.output_dir, exist_ok=True)

    # Write pressure file (fort.221)
    f221_path = os.path.join(args.output_dir, "fort.221")
    with open(f221_path, "w") as f:
        write_owi_header(f, "ADCIRC_Basin", start, end)
        for ti, t in enumerate(times):
            dt_obj = t if isinstance(t, datetime.datetime) else \
                datetime.datetime.utcfromtimestamp(
                    (t - np.datetime64("1970-01-01T00:00:00")) /
                    np.timedelta64(1, "s")
                )
            write_owi_snapshot(f, dt_obj, lats, lons, msl[ti])
    logger.info(f"Wrote {f221_path} ({len(times)} snapshots)")

    # Write wind file (fort.222)
    f222_path = os.path.join(args.output_dir, "fort.222")
    with open(f222_path, "w") as f:
        write_owi_header(f, "ADCIRC_Basin", start, end)
        for ti, t in enumerate(times):
            dt_obj = t if isinstance(t, datetime.datetime) else \
                datetime.datetime.utcfromtimestamp(
                    (t - np.datetime64("1970-01-01T00:00:00")) /
                    np.timedelta64(1, "s")
                )
            # Write u-component then v-component for each snapshot
            write_owi_snapshot(f, dt_obj, lats, lons, u10[ti])
            write_owi_snapshot(f, dt_obj, lats, lons, v10[ti])
    logger.info(f"Wrote {f222_path} ({len(times)} snapshots)")

    # Write control file
    write_fort22_control(args.output_dir, start, end, len(times))

    # Step 5: Validate outputs
    validate_outputs(args.output_dir)

    logger.info(
        f"Conversion complete: {len(times)} timesteps, "
        f"grid {len(lats)}×{len(lons)}, "
        f"pressure {np.min(msl):.1f}-{np.max(msl):.1f} mb, "
        f"max wind {np.max(np.sqrt(u10**2 + v10**2)):.1f} m/s"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to ADCIRC OWI format (NWS=12)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input_dir", required=True,
                        help="Directory containing input met data files")
    parser.add_argument("--format", required=True,
                        choices=["era5_nc", "gfs_grib2", "cmfd_nc", "csv"],
                        help="Input data format")
    parser.add_argument("--domain_sw", required=True,
                        help="SW corner: 'lat,lon' (degrees)")
    parser.add_argument("--domain_ne", required=True,
                        help="NE corner: 'lat,lon' (degrees)")
    parser.add_argument("--resolution", type=float, default=0.25,
                        help="Grid resolution in degrees (default: 0.25)")
    parser.add_argument("--start_date", required=True,
                        help="Start date: YYYY-MM-DD")
    parser.add_argument("--end_date", required=True,
                        help="End date: YYYY-MM-DD")
    parser.add_argument("--output_dir", default=".",
                        help="Output directory (default: current)")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
