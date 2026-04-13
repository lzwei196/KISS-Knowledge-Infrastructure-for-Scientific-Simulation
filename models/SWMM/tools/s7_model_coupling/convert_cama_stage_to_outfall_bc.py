#!/usr/bin/env python3
"""
Convert CaMa-Flood water surface elevation to SWMM outfall boundary condition.

Extracts the surface water elevation (sfcelv) from CaMa-Flood output at a
specified location and converts it to a SWMM TIMESERIES for use as a
TIDAL outfall boundary condition. This enables downstream coupling where
CaMa-Flood river/flood dynamics control the SWMM outfall water level.

CaMa-Flood output variable: sfcelv (surface water elevation, m above datum)
SWMM outfall type: TIDAL or TIMESERIES (stage in meters)

Inputs:
  - CaMa-Flood output directory (NetCDF files: sfcelv_YYYY.nc)
  - Lat/lon of outfall location
  - SWMM outfall ID
  - Optional datum offset (to align CaMa-Flood datum with SWMM datum)

Outputs:
  - SWMM timeseries file with stage values for outfall BC
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def find_nearest_cell(nc_path, target_lat, target_lon):
    """Find nearest CaMa-Flood grid cell to target coordinates."""
    try:
        import netCDF4 as nc
    except ImportError:
        try:
            from scipy.io import netcdf_file
            print("WARNING: Using scipy.io.netcdf (limited)", file=sys.stderr)
            return None, None, None
        except ImportError:
            print("ERROR: netCDF4 required. Install with: pip install netCDF4",
                  file=sys.stderr)
            sys.exit(1)

    ds = nc.Dataset(nc_path)

    # Try common dimension names
    lat_names = ["lat", "latitude", "y", "Y"]
    lon_names = ["lon", "longitude", "x", "X"]

    lats = None
    lons = None
    for name in lat_names:
        if name in ds.variables:
            lats = ds.variables[name][:]
            break
    for name in lon_names:
        if name in ds.variables:
            lons = ds.variables[name][:]
            break

    if lats is None or lons is None:
        print(f"WARNING: Cannot find lat/lon in {nc_path}", file=sys.stderr)
        ds.close()
        return None, None, None

    # Find nearest cell
    lat_idx = np.argmin(np.abs(lats - target_lat))
    lon_idx = np.argmin(np.abs(lons - target_lon))

    actual_lat = float(lats[lat_idx])
    actual_lon = float(lons[lon_idx])
    dist_deg = np.sqrt((actual_lat - target_lat)**2 + (actual_lon - target_lon)**2)

    ds.close()
    return lat_idx, lon_idx, dist_deg


def extract_sfcelv(cama_out_dir, lat_idx, lon_idx, start_year, end_year):
    """Extract surface elevation timeseries from CaMa-Flood output."""
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required", file=sys.stderr)
        sys.exit(1)

    cama_dir = Path(cama_out_dir)
    records = []

    for year in range(start_year, end_year + 1):
        # Try different naming conventions
        nc_candidates = [
            cama_dir / f"sfcelv_{year}.nc",
            cama_dir / f"sfcelv{year}.nc",
            cama_dir / f"o_sfcelv{year}.nc",
        ]

        nc_path = None
        for candidate in nc_candidates:
            if candidate.exists():
                nc_path = candidate
                break

        if nc_path is None:
            print(f"  WARNING: No sfcelv file for year {year}", file=sys.stderr)
            continue

        ds = nc.Dataset(nc_path)

        # Find the elevation variable
        var_names = ["sfcelv", "stage", "water_level", "WSE"]
        data_var = None
        for vn in var_names:
            if vn in ds.variables:
                data_var = ds.variables[vn]
                break

        if data_var is None:
            print(f"  WARNING: No elevation variable in {nc_path}", file=sys.stderr)
            ds.close()
            continue

        # Extract timeseries at the cell
        data = data_var[:, lat_idx, lon_idx]

        # Determine time axis
        if "time" in ds.variables:
            time_var = ds.variables["time"]
            try:
                import cftime
                times = nc.num2date(time_var[:], time_var.units,
                                    calendar=getattr(time_var, 'calendar', 'standard'))
            except (ImportError, AttributeError):
                # Assume daily starting Jan 1
                n_days = len(data)
                times = [datetime(year, 1, 1) + timedelta(days=i) for i in range(n_days)]
        else:
            n_days = len(data)
            times = [datetime(year, 1, 1) + timedelta(days=i) for i in range(n_days)]

        for t, val in zip(times, data):
            if hasattr(t, 'year'):
                dt = datetime(t.year, t.month, t.day,
                              getattr(t, 'hour', 0), getattr(t, 'minute', 0))
            else:
                dt = t
            val_float = float(val) if not np.isnan(val) else 0.0
            records.append((dt, val_float))

        ds.close()
        print(f"  Year {year}: {len(data)} timesteps, "
              f"mean={np.nanmean(data):.3f}m, max={np.nanmax(data):.3f}m")

    return records


def write_swmm_outfall_bc(records, outfall_id, datum_offset, output_path):
    """Write SWMM timeseries for outfall boundary condition."""
    ts_name = f"CaMa_{outfall_id}"

    with open(output_path, "w") as f:
        f.write(f";;CaMa-Flood surface elevation -> SWMM outfall BC\n")
        f.write(f";;Outfall: {outfall_id}, Datum offset: {datum_offset} m\n")
        f.write(f";;Generated by convert_cama_stage_to_outfall_bc.py\n")
        f.write(";;\n")

        # Timeseries section
        f.write(f"\n[TIMESERIES]\n")
        f.write(f";;Name           Date       Time       Value\n")
        for dt, stage in records:
            adjusted_stage = stage + datum_offset
            date_str = dt.strftime("%m/%d/%Y")
            time_str = dt.strftime("%H:%M:%S")
            f.write(f"{ts_name}\t{date_str}\t{time_str}\t{adjusted_stage:.4f}\n")

        # Outfall definition update hint
        f.write(f"\n;;To use this in your .inp file, set the outfall type:\n")
        f.write(f";;[OUTFALLS]\n")
        f.write(f";;{outfall_id}  <invert_elev>  TIMESERIES  {ts_name}  NO\n")

    return len(records)


def main():
    parser = argparse.ArgumentParser(
        description="Convert CaMa-Flood water surface elevation to SWMM outfall BC"
    )
    parser.add_argument("--cama_out_dir", required=True,
                        help="CaMa-Flood output directory")
    parser.add_argument("--lat", type=float, required=True,
                        help="Outfall latitude")
    parser.add_argument("--lon", type=float, required=True,
                        help="Outfall longitude")
    parser.add_argument("--outfall_id", required=True,
                        help="SWMM outfall node ID")
    parser.add_argument("--datum_offset", type=float, default=0.0,
                        help="Datum offset (m): SWMM_stage = CaMa_stage + offset")
    parser.add_argument("--output", required=True,
                        help="Output SWMM timeseries file")
    parser.add_argument("--start_year", type=int, default=None,
                        help="Start year (default: auto-detect)")
    parser.add_argument("--end_year", type=int, default=None,
                        help="End year (default: auto-detect)")
    args = parser.parse_args()

    if not os.path.isdir(args.cama_out_dir):
        print(f"ERROR: Directory not found: {args.cama_out_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting CaMa-Flood stage to SWMM outfall BC")
    print(f"  CaMa output: {args.cama_out_dir}")
    print(f"  Location: ({args.lat}, {args.lon})")
    print(f"  Outfall ID: {args.outfall_id}")
    print(f"  Datum offset: {args.datum_offset} m")

    # Find available years
    cama_dir = Path(args.cama_out_dir)
    nc_files = sorted(cama_dir.glob("*sfcelv*.nc"))
    if not nc_files:
        print("ERROR: No sfcelv NetCDF files found", file=sys.stderr)
        sys.exit(1)

    # Auto-detect year range
    import re
    years = []
    for f in nc_files:
        match = re.search(r"(\d{4})", f.name)
        if match:
            years.append(int(match.group(1)))

    if not years:
        print("ERROR: Cannot determine years from filenames", file=sys.stderr)
        sys.exit(1)

    start_year = args.start_year or min(years)
    end_year = args.end_year or max(years)
    print(f"  Period: {start_year}-{end_year}")

    # Find nearest grid cell
    lat_idx, lon_idx, dist = find_nearest_cell(str(nc_files[0]), args.lat, args.lon)
    if lat_idx is None:
        print("ERROR: Could not find grid cell", file=sys.stderr)
        sys.exit(1)
    print(f"  Nearest cell: index ({lat_idx}, {lon_idx}), distance: {dist:.4f} deg")

    # Extract timeseries
    records = extract_sfcelv(args.cama_out_dir, lat_idx, lon_idx, start_year, end_year)
    if not records:
        print("ERROR: No data extracted", file=sys.stderr)
        sys.exit(1)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_written = write_swmm_outfall_bc(records, args.outfall_id, args.datum_offset,
                                       output_path)

    stages = [r[1] + args.datum_offset for r in records]
    print(f"\nOutput written: {output_path}")
    print(f"  {n_written} timesteps")
    print(f"  Stage range: {min(stages):.3f} - {max(stages):.3f} m")


if __name__ == "__main__":
    main()
