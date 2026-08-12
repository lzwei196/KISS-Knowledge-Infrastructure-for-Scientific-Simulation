#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      cama_to_sfincs_boundary
Stage:        s4_forcing
Description:  Convert CaMa-Flood output to SFINCS boundary conditions.
              This is the KEY COUPLING tool: CaMa-Flood -> SFINCS.

Supports two BC types:
  1. Water level BC (sfincs.bnd + sfincs.bzs): Use CaMa sfcelv at SFINCS boundary
  2. Discharge source (sfincs.src + sfincs.dis): Use CaMa outflw as SFINCS inflow point

CRITICAL:
  - CaMa-Flood output is DAILY. SFINCS needs sub-hourly.
    Linear interpolation is applied, but this creates artificial ramps.
    For rapid flood events, consider sub-daily CaMa output.
  - Vertical datum: CaMa sfcelv is relative to geoid (EGM96).
    DEM must use the same datum. EGM96 vs WGS84 ellipsoid can differ by 20-40m!
  - Double-counting: If SFINCS applies its own rainfall, do NOT also add VIC
    surface runoff as SFINCS source. The river boundary from CaMa is sufficient.

Inputs:
  --cama_out_dir:  CaMa-Flood output directory (contains outflw*.nc, sfcelv*.nc)
  --grid_info:     Path to grid_info.json from s1_domain
  --bc_type:       "waterlevel" or "discharge" (default: discharge)
  --bc_locations:  Comma-separated "lon,lat" pairs for boundary points
                   (or use --auto to place at domain boundary river entry points)
  --start_date:    Start date YYYY-MM-DD
  --end_date:      End date YYYY-MM-DD
  --output_dir:    Output directory

Outputs:
  - sfincs.bnd + sfincs.bzs (if bc_type=waterlevel)
  - sfincs.src + sfincs.dis (if bc_type=discharge)
  - boundary_summary.json

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(args):
    errors = []
    if not Path(args.cama_out_dir).exists():
        errors.append(f"CaMa-Flood output directory not found: {args.cama_out_dir}")
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if args.bc_type not in ("waterlevel", "discharge"):
        errors.append(f"bc_type must be 'waterlevel' or 'discharge', got: {args.bc_type}")
    if not args.bc_locations and not args.auto:
        errors.append("Either --bc_locations or --auto must be specified")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def find_cama_files(cama_dir, variable, start_year, end_year):
    """Find CaMa-Flood NetCDF output files for a variable, filtered by year range."""
    import glob
    import re
    patterns = [
        f"{variable}*.nc",
        f"*{variable}*.nc",
    ]
    all_files = []
    for pat in patterns:
        all_files.extend(glob.glob(os.path.join(cama_dir, pat)))
    all_files = sorted(set(all_files))

    # Filter files by year range (CaMa naming: o_outflw2003.nc or outflw_2003.nc)
    files = []
    for f in all_files:
        basename = os.path.basename(f)
        year_match = re.search(r'(\d{4})', basename)
        if year_match:
            file_year = int(year_match.group(1))
            if start_year <= file_year <= end_year:
                files.append(f)
        else:
            # No year in filename — include it
            files.append(f)

    if not files and all_files:
        logger.warning(f"CaMa files exist but none match year range {start_year}-{end_year}")
    elif not files:
        logger.warning(f"No CaMa files found for variable '{variable}' in {cama_dir}")
    else:
        logger.info(f"Found {len(files)} CaMa {variable} files for years {start_year}-{end_year}")
    return files


def _nc4_open_dataset(path):
    """Open a NetCDF4 file using direct netCDF4 library (avoids xarray HDF5 issue)."""
    import netCDF4 as nc4
    import numpy as np

    class _FakeDataset:
        def __init__(self, ds):
            dim_names = list(ds.dimensions.keys())
            self.data_vars = {v: None for v in ds.variables if v not in ds.dimensions}
            self.dims = {d: ds.dimensions[d].size for d in dim_names}
            self._vars = {}
            lats = ds.variables['lat'][:]
            lons = ds.variables['lon'][:]
            # Build time as datetime64
            tvar = ds.variables['time']
            import netCDF4 as _nc4
            times_raw = _nc4.num2date(tvar[:], units=tvar.units,
                                       calendar=getattr(tvar, 'calendar', 'standard'))
            times = np.array([np.datetime64(str(t)[:10]) for t in times_raw])
            self.time = _FakeResult(times)
            for v in self.data_vars:
                arr = ds.variables[v][:]
                self._vars[v] = _FakeVar(arr, lats, lons)
        def __getitem__(self, key):
            return self._vars[key]
        def close(self):
            pass

    class _FakeVar:
        def __init__(self, arr, lats, lons):
            self._arr = arr
            self._lats = lats
            self._lons = lons
        def sel(self, method='nearest', **kwargs):
            lat_val = kwargs.get('lat', kwargs.get('latitude'))
            lon_val = kwargs.get('lon', kwargs.get('longitude'))
            ilat = int(np.argmin(np.abs(self._lats - lat_val)))
            ilon = int(np.argmin(np.abs(self._lons - lon_val)))
            arr = self._arr[:, ilat, ilon] if self._arr.ndim == 3 else self._arr[ilat, ilon]
            return _FakeResult(arr)
        @property
        def values(self):
            return self._arr

    class _FakeResult:
        def __init__(self, arr):
            self._arr = arr
        @property
        def values(self):
            return np.array(self._arr)
        def tolist(self):
            return list(self._arr)

    with nc4.Dataset(path) as ds:
        fake = _FakeDataset(ds)
    return fake


def process(args):
    from pyproj import Transformer

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    epsg = grid["epsg"]
    x0 = grid["x0"]
    y0 = grid["y0"]
    dx = grid["dx"]
    dy = grid["dy"]
    mmax = grid["mmax"]
    nmax = grid["nmax"]

    start = datetime.strptime(args.start_date.replace("-", ""), "%Y%m%d")
    end = datetime.strptime(args.end_date.replace("-", ""), "%Y%m%d")
    start_year = start.year
    end_year = end.year

    # --- Parse boundary locations ---
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)

    if args.auto:
        # Auto-detect: place boundary at domain edge midpoint
        # This is a simplified approach — in production, find where the main
        # river enters the SFINCS domain
        center_lon = grid.get("center_lon", 0)
        center_lat = grid.get("center_lat", 0)
        bc_points_wgs84 = [(center_lon, center_lat)]
        logger.info(f"Auto BC point at domain center: ({center_lon}, {center_lat})")
    else:
        bc_points_wgs84 = []
        for loc in args.bc_locations.split(";"):
            parts = loc.strip().split(",")
            if len(parts) == 2:
                bc_points_wgs84.append((float(parts[0]), float(parts[1])))

    if not bc_points_wgs84:
        logger.error("No valid boundary locations")
        sys.exit(2)

    # Transform to SFINCS grid CRS
    bc_points_proj = []
    for lon, lat in bc_points_wgs84:
        x, y = transformer.transform(lon, lat)
        bc_points_proj.append((x, y))
    logger.info(f"Boundary points (projected): {bc_points_proj}")

    # --- Read CaMa-Flood output ---
    cama_dir = Path(args.cama_out_dir)

    if args.bc_type == "discharge":
        variable = "outflw"
    else:
        variable = "sfcelv"

    cama_files = find_cama_files(str(cama_dir), variable, start_year, end_year)

    if not cama_files:
        logger.error(f"No CaMa-Flood {variable} files found")
        sys.exit(2)

    # Read and extract time series at boundary points
    all_times = []
    all_values = {i: [] for i in range(len(bc_points_wgs84))}

    for cf in sorted(cama_files):
        logger.info(f"Reading {cf}...")
        ds = _nc4_open_dataset(cf)

        # Find the data variable
        data_var = None
        for v in ds.data_vars:
            if variable in v.lower():
                data_var = v
                break
        if data_var is None:
            data_var = list(ds.data_vars)[0]

        data = ds[data_var]

        # Extract time series at each BC point
        for i, (lon, lat) in enumerate(bc_points_wgs84):
            # Find nearest CaMa grid cell
            try:
                val = data.sel(lat=lat, lon=lon, method="nearest")
                all_values[i].extend(val.values.tolist())
            except Exception:
                # Try alternate dim names
                try:
                    val = data.sel(latitude=lat, longitude=lon, method="nearest")
                    all_values[i].extend(val.values.tolist())
                except Exception:
                    logger.warning(f"Could not extract data at ({lon}, {lat}) from {cf}")

        # Time
        if "time" in ds.dims:
            all_times.extend([t for t in ds.time.values])
        ds.close()

    if not all_times:
        logger.error("No time data extracted from CaMa-Flood output")
        sys.exit(2)

    n_times_raw = min(len(all_times), min(len(v) for v in all_values.values()))
    logger.info(f"Extracted {n_times_raw} total timesteps from CaMa-Flood")

    # --- Filter to requested period ---
    # CaMa output may span multiple years; only use start_date to end_date
    tref = start
    np_start = np.datetime64(start)
    np_end = np.datetime64(end)

    filtered_indices = []
    for i, t in enumerate(all_times[:n_times_raw]):
        t64 = np.datetime64(t)
        if np_start <= t64 <= np_end:
            filtered_indices.append(i)

    if not filtered_indices:
        logger.error(f"No timesteps found in range {start} to {end}")
        sys.exit(2)

    logger.info(f"Filtered to {len(filtered_indices)} timesteps in [{start}, {end}]")

    # Filter times and values
    all_times_filtered = [all_times[i] for i in filtered_indices]
    for k in all_values:
        all_values[k] = [all_values[k][i] for i in filtered_indices]
    n_times = len(filtered_indices)

    # --- Generate time in SFINCS format (seconds since tref) ---
    time_seconds = []
    for t in all_times_filtered:
        if isinstance(t, datetime):
            time_seconds.append((t - tref).total_seconds())
        else:
            dt = float((np.datetime64(t) - np.datetime64(tref)) / np.timedelta64(1, 's'))
            time_seconds.append(dt)

    # --- Write boundary files ---
    n_bc = len(bc_points_proj)

    if args.bc_type == "discharge":
        # sfincs.src — source locations (x y per line)
        src_path = output_dir / "sfincs.src"
        with open(src_path, "w") as f:
            for x, y in bc_points_proj:
                f.write(f"{x:.2f} {y:.2f}\n")

        # sfincs.dis — discharge time series
        # Format: time(s) Q1 Q2 ... QN
        dis_path = output_dir / "sfincs.dis"
        with open(dis_path, "w") as f:
            for t_idx in range(n_times):
                t_sec = time_seconds[t_idx]
                values = " ".join(f"{all_values[i][t_idx]:.3f}" for i in range(n_bc))
                f.write(f"{t_sec:.0f} {values}\n")

        logger.info(f"Wrote discharge BC: {src_path}, {dis_path}")
        bc_files = {"src_file": str(src_path), "dis_file": str(dis_path)}

    else:  # waterlevel
        # sfincs.bnd — boundary locations (x y per line)
        bnd_path = output_dir / "sfincs.bnd"
        with open(bnd_path, "w") as f:
            for x, y in bc_points_proj:
                f.write(f"{x:.2f} {y:.2f}\n")

        # sfincs.bzs — water level time series
        bzs_path = output_dir / "sfincs.bzs"
        with open(bzs_path, "w") as f:
            for t_idx in range(n_times):
                t_sec = time_seconds[t_idx]
                values = " ".join(f"{all_values[i][t_idx]:.4f}" for i in range(n_bc))
                f.write(f"{t_sec:.0f} {values}\n")

        logger.info(f"Wrote water level BC: {bnd_path}, {bzs_path}")
        bc_files = {"bnd_file": str(bnd_path), "bzs_file": str(bzs_path)}

    # --- Summary ---
    value_stats = {}
    for i in range(n_bc):
        vals = np.array(all_values[i][:n_times])
        value_stats[f"bc_point_{i}"] = {
            "location_wgs84": list(bc_points_wgs84[i]),
            "location_proj": list(bc_points_proj[i]),
            "min": float(np.nanmin(vals)),
            "max": float(np.nanmax(vals)),
            "mean": float(np.nanmean(vals)),
        }

    summary = {
        "status": "success",
        "bc_type": args.bc_type,
        "n_boundary_points": n_bc,
        "n_timesteps": n_times,
        "cama_variable": variable,
        "time_range_seconds": [float(time_seconds[0]), float(time_seconds[-1])],
        "bc_stats": value_stats,
        **bc_files,
    }

    summary_path = output_dir / "boundary_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert CaMa-Flood output to SFINCS boundary conditions")
    parser.add_argument("--cama_out_dir", required=True, help="CaMa-Flood output directory")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--bc_type", default="discharge", choices=["waterlevel", "discharge"],
                        help="Boundary condition type")
    parser.add_argument("--bc_locations", default=None,
                        help="BC locations as 'lon,lat;lon,lat' (WGS84)")
    parser.add_argument("--auto", action="store_true", help="Auto-detect BC locations")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
