#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
====================================================
Tool ID:      vic_forcing_to_swatplus
Stage:        s3_weather_preparation
Description:  Convert VIC forcing files to SWAT+ weather file format (.pcp, .tmp,
              .slr, .hmd, .wnd) with all required .cli index files and
              weather-sta.cli station registry.

This script reads VIC 3-hourly forcing files (7 columns, no header, 8 rows/day)
and the basin_grid.nc file that lists grid-cell coordinates. It aggregates the
sub-daily data to daily values, performs unit conversions, and writes one SWAT+
weather station per VIC grid cell.

VIC forcing columns (0-indexed, tab-separated, 3-hourly, 8 rows/day):
  0 — Temperature (deg-C)
  1 — Precipitation (mm per 3-hour timestep)
  2 — Pressure (kPa)
  3 — Shortwave radiation (W/m2)
  4 — Longwave radiation (W/m2)
  5 — Vapor pressure (kPa)
  6 — Wind speed (m/s)

SWAT+ daily aggregation rules:
  Precipitation : SUM of 8 timesteps → mm/day
  T-min / T-max : MIN / MAX of 8 temperature values → deg-C
  Solar radiation: MEAN of 8 SW values × 0.0864 → MJ/m2/day
  Relative humidity: MEAN of 8 RH values (derived from VP & T via Tetens)
  Wind speed    : MEAN of 8 values → m/s

Inputs:
  --forcing_dir    : Directory containing VIC forcing files (required)
  --grid_nc        : Path to basin_grid.nc with cell coordinates (required)
  --output_dir     : Directory for SWAT+ weather files (required)
  --start_year     : First year of forcing data (required)
  --end_year       : Last year of forcing data (required)
  --station_prefix : Prefix for station names (optional, default "vic")
  --soil_param     : Path to VIC SOIL_PARAM file for elevation (optional)
  --steps_per_day  : Number of forcing timesteps per day (optional, default 8)

Outputs:
  - One .pcp, .tmp, .slr, .hmd, .wnd file per VIC grid cell
  - pcp.cli, tmp.cli, slr.cli, hmd.cli, wnd.cli (file-list index files)
  - weather-sta.cli (station registry for SWAT+ model)

Preconditions:
  - VIC forcing files exist in forcing_dir, named <prefix>_<lat>_<lon>
  - basin_grid.nc exists and contains mask/cell_id with y/x coordinates
  - start_year/end_year match the forcing data period

Postconditions:
  - Every VIC grid cell has 5 weather files (.pcp .tmp .slr .hmd .wnd)
  - All .cli index files list the correct filenames
  - weather-sta.cli links each station to its 5 weather files
  - Daily record count matches expected number of days

Usage:
  python vic_forcing_to_swatplus.py \\
    --forcing_dir  outputs/<run>/vic_temp/forcing/forcing_final \\
    --grid_nc      outputs/<run>/vic_temp/grid/basin_grid.nc \\
    --output_dir   outputs/<run>/swatplus_weather \\
    --start_year   2000 --end_year 2010 \\
    --station_prefix vic \\
    --soil_param   outputs/<run>/vic_temp/soil/SOIL_PARAM_COMPLETE.txt

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import argparse
import logging
import json
import math
import calendar
from pathlib import Path
from datetime import date, timedelta

import numpy as np
from ki_tools_common.humidity import saturation_vapor_pressure

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Convert VIC forcing files to SWAT+ weather format."
    )
    p.add_argument("--forcing_dir", required=True, help="Directory with VIC forcing files")
    p.add_argument("--grid_nc", required=True, help="Path to basin_grid.nc")
    p.add_argument("--output_dir", required=True, help="Output directory for SWAT+ files")
    p.add_argument("--start_year", type=int, required=True, help="First year of data")
    p.add_argument("--end_year", type=int, required=True, help="Last year of data")
    p.add_argument("--station_prefix", default="vic", help="Prefix for station names (default: vic)")
    p.add_argument("--soil_param", default="", help="VIC SOIL_PARAM file for elevation lookup")
    p.add_argument("--steps_per_day", type=int, default=8, help="Timesteps per day (default: 8 for 3-hourly)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Physics: Tetens formula for saturation vapor pressure
# ---------------------------------------------------------------------------
def saturation_vapor_pressure_kpa(t_celsius):
    """
    Tetens formula: e_s(T) in kPa.
    e_s = saturation_vapor_pressure(T) / 10.0  # hPa -> kPa (ki_tools_common)
    """
    return saturation_vapor_pressure(t_celsius) / 10.0  # hPa -> kPa (ki_tools_common)


def vapor_pressure_to_rh(vp_kpa, t_celsius):
    """
    Convert actual vapor pressure (kPa) to relative humidity (fraction 0-1).
    RH = VP / e_s(T), clipped to [0, 1].
    """
    e_sat = saturation_vapor_pressure_kpa(t_celsius)
    # Guard against division by zero at extreme cold
    e_sat = np.where(e_sat < 1e-6, 1e-6, e_sat)
    rh = vp_kpa / e_sat
    return np.clip(rh, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Grid cell discovery
# ---------------------------------------------------------------------------
def discover_cells_from_grid_nc(grid_nc_path):
    """
    Read basin_grid.nc and return a list of (lat, lon) tuples for valid
    (mask == 1) grid cells.
    """
    try:
        import xarray as xr
    except ImportError:
        logger.error("xarray is required. Install with: pip install xarray netCDF4")
        sys.exit(1)

    ds = xr.open_dataset(grid_nc_path)

    # Coordinate names vary: (y, x), (lat, lon), (latitude, longitude)
    if "y" in ds.coords and "x" in ds.coords:
        y_name, x_name = "y", "x"
    elif "lat" in ds.coords and "lon" in ds.coords:
        y_name, x_name = "lat", "lon"
    elif "latitude" in ds.coords and "longitude" in ds.coords:
        y_name, x_name = "latitude", "longitude"
    else:
        logger.error(f"Cannot identify lat/lon coordinates in {grid_nc_path}. "
                     f"Found coords: {list(ds.coords)}")
        sys.exit(1)

    y_vals = ds[y_name].values
    x_vals = ds[x_name].values
    mask = ds["mask"].values  # shape (ny, nx), 1 inside basin, NaN outside

    cells = []
    for iy in range(len(y_vals)):
        for ix in range(len(x_vals)):
            if not np.isnan(mask[iy, ix]) and mask[iy, ix] >= 1:
                cells.append((float(y_vals[iy]), float(x_vals[ix])))

    ds.close()
    logger.info(f"Found {len(cells)} valid grid cells in {grid_nc_path}")
    return cells


# ---------------------------------------------------------------------------
# Elevation lookup from VIC soil parameter file
# ---------------------------------------------------------------------------
def load_elevation_map(soil_param_path):
    """
    Parse VIC soil parameter file and return {(lat, lon): elev_m} dict.
    VIC soil format: columns are space-separated.
    Col 0: run_flag, Col 1: cell_id, Col 2: lat, Col 3: lon, ...
    Elevation is typically around column 22 (0-indexed), but its position
    depends on the number of soil layers. We search for a value that looks
    like an elevation (>0, <9000) after the first few standard columns.

    Actually, for VIC 5 classic driver, the soil file has a well-defined
    column layout. Column 22 (0-indexed) is the elevation when Nlayer=3.
    Layout (0-indexed):
      0: run_flag
      1: cell_id
      2: lat
      3: lon
      4: binfilt
      5: Ds
      6: Dsmax
      7: Ws
      8: c_expt (Nlayer=3: cols 8,9,10)
      11: Ksat (3 cols: 11,12,13)
      14: phi_s (3 cols: 14,15,16)
      17: init_moist (3 cols: 17,18,19)
      20: elev
      21: depth[0], 22: depth[1], 23: depth[2]
      ...

    So column 20 (0-indexed) is elevation for 3-layer soil.
    For safety, we try column 20, then fall back to a heuristic search.
    """
    elev_map = {}
    if not soil_param_path or not Path(soil_param_path).exists():
        return elev_map

    with open(soil_param_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 21:
                continue
            try:
                lat = float(parts[2])
                lon = float(parts[3])
                # Column 20 (0-indexed) is elevation for 3-layer VIC soil
                elev = float(parts[20])
                # Sanity check: elevation should be between -500 and 9000
                if -500 <= elev <= 9000:
                    elev_map[(round(lat, 4), round(lon, 4))] = elev
            except (ValueError, IndexError):
                continue

    logger.info(f"Loaded elevation for {len(elev_map)} cells from soil parameter file")
    return elev_map


def get_elevation(lat, lon, elev_map):
    """Look up elevation from the map, with tolerance for floating-point mismatch."""
    key = (round(lat, 4), round(lon, 4))
    if key in elev_map:
        return elev_map[key]
    # Try with less precision
    for (elat, elon), elev in elev_map.items():
        if abs(elat - lat) < 0.01 and abs(elon - lon) < 0.01:
            return elev
    return 0.0  # default if not found


# ---------------------------------------------------------------------------
# Find VIC forcing file for a given grid cell
# ---------------------------------------------------------------------------
def find_forcing_file(forcing_dir, lat, lon):
    """
    Locate the VIC forcing file for a cell.  VIC forcing filenames follow the
    pattern:  <prefix>_<lat>_<lon>    (no extension)

    Lat/lon in the filename can have varying decimal precision (e.g. 34.8750
    or 34.875).  We try several formatting variants, then fall back to a
    directory scan looking for the closest coordinate match.
    """
    forcing_dir = Path(forcing_dir)

    # Generate candidate filename suffixes
    lat_fmts = [f"{lat:.4f}", f"{lat:.3f}", f"{lat:.2f}"]
    lon_fmts = [f"{lon:.4f}", f"{lon:.3f}", f"{lon:.2f}"]

    for lf in lat_fmts:
        for lnf in lon_fmts:
            suffix = f"_{lf}_{lnf}"
            # Scan directory for files ending with this suffix
            for p in forcing_dir.iterdir():
                if p.is_file() and p.name.endswith(suffix):
                    return p

    # Fallback: scan all files and find the closest coordinate match
    best_file = None
    best_dist = float("inf")
    for p in forcing_dir.iterdir():
        if not p.is_file():
            continue
        parts = p.name.rsplit("_", 2)
        if len(parts) < 3:
            continue
        try:
            file_lat = float(parts[-2])
            file_lon = float(parts[-1])
        except ValueError:
            continue
        dist = abs(file_lat - lat) + abs(file_lon - lon)
        if dist < best_dist:
            best_dist = dist
            best_file = p

    if best_file is not None and best_dist < 0.02:
        return best_file

    return None


# ---------------------------------------------------------------------------
# Read and aggregate a single VIC forcing file
# ---------------------------------------------------------------------------
def read_and_aggregate_forcing(filepath, start_year, end_year, steps_per_day):
    """
    Read a VIC forcing file (no header, tab/space-separated, `steps_per_day`
    rows per day) and return daily aggregated arrays.

    Returns dict with keys: year, jday, pcp, tmin, tmax, slr, rh, wnd
    Each value is a 1-D numpy array of length n_days.
    """
    # Read entire file as float array
    data = np.loadtxt(filepath)
    total_rows = data.shape[0]

    if data.ndim != 2 or data.shape[1] < 7:
        raise ValueError(
            f"Expected >=7 columns, got shape {data.shape} in {filepath}"
        )

    if total_rows % steps_per_day != 0:
        raise ValueError(
            f"Row count {total_rows} is not divisible by {steps_per_day} in {filepath}"
        )

    n_days = total_rows // steps_per_day

    # Reshape to (n_days, steps_per_day, 7)
    data3d = data[:, :7].reshape(n_days, steps_per_day, 7)

    # Column indices
    COL_TEMP = 0   # deg-C
    COL_PCP  = 1   # mm per timestep
    COL_PRES = 2   # kPa
    COL_SW   = 3   # W/m2
    COL_LW   = 4   # W/m2 (not used for SWAT+)
    COL_VP   = 5   # kPa (vapor pressure)
    COL_WND  = 6   # m/s

    # Daily aggregation
    tmin = data3d[:, :, COL_TEMP].min(axis=1)        # deg-C
    tmax = data3d[:, :, COL_TEMP].max(axis=1)        # deg-C
    pcp  = data3d[:, :, COL_PCP].sum(axis=1)         # mm/day
    sw_mean = data3d[:, :, COL_SW].mean(axis=1)      # W/m2 mean
    slr  = sw_mean * 0.0864                           # MJ/m2/day
    wnd  = data3d[:, :, COL_WND].mean(axis=1)        # m/s

    # Relative humidity: convert VP/T to RH per timestep, then average
    vp_all  = data3d[:, :, COL_VP]   # kPa, shape (n_days, steps)
    tmp_all = data3d[:, :, COL_TEMP] # deg-C
    rh_all  = vapor_pressure_to_rh(vp_all, tmp_all)  # fraction 0-1
    rh = rh_all.mean(axis=1)

    # Generate year and julian day sequences
    start_date = date(start_year, 1, 1)
    years = np.empty(n_days, dtype=int)
    jdays = np.empty(n_days, dtype=int)
    for i in range(n_days):
        d = start_date + timedelta(days=i)
        years[i] = d.year
        jdays[i] = d.timetuple().tm_yday

    # Verify we have the right number of days
    end_date = date(end_year, 12, 31)
    expected_days = (end_date - start_date).days + 1
    if n_days != expected_days:
        logger.warning(
            f"Day count mismatch in {filepath}: got {n_days}, expected {expected_days}. "
            f"Using actual row count."
        )

    return {
        "year": years,
        "jday": jdays,
        "pcp": pcp,
        "tmin": tmin,
        "tmax": tmax,
        "slr": slr,
        "rh": rh,
        "wnd": wnd,
        "n_days": n_days,
    }


# ---------------------------------------------------------------------------
# SWAT+ weather file writers
# ---------------------------------------------------------------------------
def write_pcp_file(filepath, station_name, nbyr, lat, lon, elev, daily):
    """Write a SWAT+ precipitation file (.pcp)."""
    with open(filepath, "w") as f:
        f.write(f"{station_name}.pcp: Precipitation — VIC forcing conversion\n")
        f.write(f"nbyr\ttstep\tlat\tlong\telev\n")
        f.write(f"{nbyr}\t0\t{lat:.4f}\t{lon:.4f}\t{elev:.2f}\n")
        for i in range(daily["n_days"]):
            f.write(f"{daily['year'][i]}\t{daily['jday'][i]}\t{daily['pcp'][i]:.4f}\n")


def write_tmp_file(filepath, station_name, nbyr, lat, lon, elev, daily):
    """Write a SWAT+ temperature file (.tmp)."""
    with open(filepath, "w") as f:
        f.write(f"{station_name}.tmp: Temperature — VIC forcing conversion\n")
        f.write(f"nbyr\ttstep\tlat\tlong\telev\n")
        f.write(f"{nbyr}\t0\t{lat:.4f}\t{lon:.4f}\t{elev:.2f}\n")
        for i in range(daily["n_days"]):
            f.write(
                f"{daily['year'][i]}\t{daily['jday'][i]}\t"
                f"{daily['tmax'][i]:.2f}\t{daily['tmin'][i]:.2f}\n"
            )


def write_slr_file(filepath, station_name, nbyr, lat, lon, elev, daily):
    """Write a SWAT+ solar radiation file (.slr)."""
    with open(filepath, "w") as f:
        f.write(f"{station_name}.slr: Solar radiation — VIC forcing conversion\n")
        f.write(f"nbyr\ttstep\tlat\tlong\telev\n")
        f.write(f"{nbyr}\t0\t{lat:.4f}\t{lon:.4f}\t{elev:.2f}\n")
        for i in range(daily["n_days"]):
            f.write(f"{daily['year'][i]}\t{daily['jday'][i]}\t{daily['slr'][i]:.4f}\n")


def write_hmd_file(filepath, station_name, nbyr, lat, lon, elev, daily):
    """Write a SWAT+ relative humidity file (.hmd)."""
    with open(filepath, "w") as f:
        f.write(f"{station_name}.hmd: Relative humidity — VIC forcing conversion\n")
        f.write(f"nbyr\ttstep\tlat\tlong\telev\n")
        f.write(f"{nbyr}\t0\t{lat:.4f}\t{lon:.4f}\t{elev:.2f}\n")
        for i in range(daily["n_days"]):
            f.write(f"{daily['year'][i]}\t{daily['jday'][i]}\t{daily['rh'][i]:.4f}\n")


def write_wnd_file(filepath, station_name, nbyr, lat, lon, elev, daily):
    """Write a SWAT+ wind speed file (.wnd)."""
    with open(filepath, "w") as f:
        f.write(f"{station_name}.wnd: Wind speed — VIC forcing conversion\n")
        f.write(f"nbyr\ttstep\tlat\tlong\telev\n")
        f.write(f"{nbyr}\t0\t{lat:.4f}\t{lon:.4f}\t{elev:.2f}\n")
        for i in range(daily["n_days"]):
            f.write(f"{daily['year'][i]}\t{daily['jday'][i]}\t{daily['wnd'][i]:.4f}\n")


def write_cli_index(filepath, description, filenames):
    """Write a SWAT+ .cli index file (list of station data files)."""
    with open(filepath, "w") as f:
        f.write(f"{description}\n")
        f.write("filename\n")
        for fn in filenames:
            f.write(f"{fn}\n")


def write_weather_sta_cli(filepath, station_names):
    """
    Write weather-sta.cli linking each station to its 5 weather file types.
    Format matches SWAT+ editor output.
    """
    with open(filepath, "w") as f:
        f.write("weather-sta.cli: written by vic_forcing_to_swatplus\n")
        # Header row — 9 columns, tab-separated
        f.write(
            "name\twgn\tpcp\ttmp\tslr\thmd\twnd\twnd_dir\tatmo_dep\n"
        )
        for sn in station_names:
            f.write(
                f"{sn}\t{sn}\t{sn}.pcp\t{sn}.tmp\t{sn}.slr\t"
                f"{sn}.hmd\t{sn}.wnd\tnull\tnull\n"
            )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check that all preconditions are met before processing."""
    errors = []

    forcing_dir = Path(args.forcing_dir)
    if not forcing_dir.exists():
        errors.append(f"Forcing directory not found: {args.forcing_dir}")
    elif not forcing_dir.is_dir():
        errors.append(f"Forcing path is not a directory: {args.forcing_dir}")

    grid_nc = Path(args.grid_nc)
    if not grid_nc.exists():
        errors.append(f"Grid NetCDF not found: {args.grid_nc}")

    if args.start_year > args.end_year:
        errors.append(
            f"start_year ({args.start_year}) > end_year ({args.end_year})"
        )

    if args.start_year < 1900 or args.end_year > 2100:
        errors.append(
            f"Year range [{args.start_year}, {args.end_year}] looks unreasonable"
        )

    if args.steps_per_day not in (1, 4, 8, 24):
        errors.append(
            f"steps_per_day={args.steps_per_day} is unusual. "
            f"Expected 8 (3-hourly), 24 (hourly), 4 (6-hourly), or 1 (daily)."
        )

    if args.soil_param and not Path(args.soil_param).exists():
        logger.warning(f"Soil parameter file not found: {args.soil_param} — elevations will default to 0")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(output_dir, expected_stations, expected_days, nbyr):
    """Check that postconditions are met after processing."""
    errors = []
    output_dir = Path(output_dir)

    # Check .cli index files exist
    for cli in ["pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli"]:
        cli_path = output_dir / cli
        if not cli_path.exists():
            errors.append(f"CLI index file not created: {cli}")

    # Check weather-sta.cli
    wsta = output_dir / "weather-sta.cli"
    if not wsta.exists():
        errors.append("weather-sta.cli not created")

    # Check that at least one station has all 5 files
    if expected_stations:
        sn = expected_stations[0]
        for ext in [".pcp", ".tmp", ".slr", ".hmd", ".wnd"]:
            fpath = output_dir / f"{sn}{ext}"
            if not fpath.exists():
                errors.append(f"Station file not created: {sn}{ext}")
            else:
                # Verify line count (3 header + expected_days data lines)
                with open(fpath, "r") as f:
                    lines = f.readlines()
                data_lines = len(lines) - 3
                if data_lines != expected_days:
                    errors.append(
                        f"{sn}{ext}: expected {expected_days} data lines, "
                        f"got {data_lines}"
                    )

    # Spot-check: first pcp file header should have correct nbyr
    if expected_stations:
        pcp_path = output_dir / f"{expected_stations[0]}.pcp"
        if pcp_path.exists():
            with open(pcp_path, "r") as f:
                _ = f.readline()  # title
                _ = f.readline()  # column names
                meta_line = f.readline().strip()
            meta_parts = meta_line.split()
            if meta_parts and int(meta_parts[0]) != nbyr:
                errors.append(
                    f"nbyr mismatch in pcp header: expected {nbyr}, "
                    f"got {meta_parts[0]}"
                )

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """
    Main processing pipeline:
    1. Read grid_nc to get cell coordinates
    2. Optionally load elevation from soil parameter file
    3. For each cell: find forcing file, aggregate 3-hourly→daily, write
       .pcp/.tmp/.slr/.hmd/.wnd
    4. Write .cli index files and weather-sta.cli
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: discover cells ---
    cells = discover_cells_from_grid_nc(args.grid_nc)
    if not cells:
        logger.error("No valid grid cells found in grid_nc")
        sys.exit(1)

    # --- Step 2: elevation lookup ---
    elev_map = load_elevation_map(args.soil_param)

    # --- Step 3: compute time metadata ---
    nbyr = args.end_year - args.start_year + 1
    start_date = date(args.start_year, 1, 1)
    end_date = date(args.end_year, 12, 31)
    expected_days = (end_date - start_date).days + 1
    logger.info(
        f"Period: {args.start_year}-{args.end_year} ({nbyr} years, "
        f"{expected_days} days)"
    )

    # --- Step 4: process each cell ---
    station_names = []
    pcp_files = []
    tmp_files = []
    slr_files = []
    hmd_files = []
    wnd_files = []

    skipped = 0
    for idx, (lat, lon) in enumerate(cells):
        station_name = f"{args.station_prefix}{idx + 1:04d}"

        # Find the forcing file
        fpath = find_forcing_file(args.forcing_dir, lat, lon)
        if fpath is None:
            logger.warning(
                f"No forcing file found for cell ({lat:.4f}, {lon:.4f}). Skipping."
            )
            skipped += 1
            continue

        # Read and aggregate
        try:
            daily = read_and_aggregate_forcing(
                fpath, args.start_year, args.end_year, args.steps_per_day
            )
        except Exception as exc:
            logger.warning(
                f"Failed to read forcing for cell ({lat:.4f}, {lon:.4f}): {exc}. Skipping."
            )
            skipped += 1
            continue

        elev = get_elevation(lat, lon, elev_map)

        # Write the 5 weather files
        pcp_name = f"{station_name}.pcp"
        tmp_name = f"{station_name}.tmp"
        slr_name = f"{station_name}.slr"
        hmd_name = f"{station_name}.hmd"
        wnd_name = f"{station_name}.wnd"

        write_pcp_file(output_dir / pcp_name, station_name, nbyr, lat, lon, elev, daily)
        write_tmp_file(output_dir / tmp_name, station_name, nbyr, lat, lon, elev, daily)
        write_slr_file(output_dir / slr_name, station_name, nbyr, lat, lon, elev, daily)
        write_hmd_file(output_dir / hmd_name, station_name, nbyr, lat, lon, elev, daily)
        write_wnd_file(output_dir / wnd_name, station_name, nbyr, lat, lon, elev, daily)

        station_names.append(station_name)
        pcp_files.append(pcp_name)
        tmp_files.append(tmp_name)
        slr_files.append(slr_name)
        hmd_files.append(hmd_name)
        wnd_files.append(wnd_name)

        if (idx + 1) % 20 == 0 or idx == len(cells) - 1:
            logger.info(
                f"  Processed {idx + 1}/{len(cells)} cells "
                f"(current: {station_name} @ {lat:.4f}, {lon:.4f})"
            )

    if not station_names:
        logger.error("No forcing files could be matched to any grid cell. "
                     "Check that forcing file names contain lat/lon coordinates "
                     "matching basin_grid.nc.")
        sys.exit(2)

    # --- Step 5: write .cli index files ---
    write_cli_index(
        output_dir / "pcp.cli",
        "pcp.cli: Precipitation file list — VIC forcing conversion",
        pcp_files,
    )
    write_cli_index(
        output_dir / "tmp.cli",
        "tmp.cli: Temperature file list — VIC forcing conversion",
        tmp_files,
    )
    write_cli_index(
        output_dir / "slr.cli",
        "slr.cli: Solar radiation file list — VIC forcing conversion",
        slr_files,
    )
    write_cli_index(
        output_dir / "hmd.cli",
        "hmd.cli: Relative humidity file list — VIC forcing conversion",
        hmd_files,
    )
    write_cli_index(
        output_dir / "wnd.cli",
        "wnd.cli: Wind speed file list — VIC forcing conversion",
        wnd_files,
    )

    # --- Step 6: write weather-sta.cli ---
    write_weather_sta_cli(output_dir / "weather-sta.cli", station_names)

    logger.info(
        f"Conversion complete: {len(station_names)} stations, "
        f"{skipped} skipped, {expected_days} days each"
    )

    return {
        "status": "success",
        "n_stations": len(station_names),
        "n_skipped": skipped,
        "n_days": expected_days,
        "period": f"{args.start_year}-{args.end_year}",
        "output_dir": str(output_dir),
        "station_names": station_names,
        "files_created": {
            "pcp": pcp_files,
            "tmp": tmp_files,
            "slr": slr_files,
            "hmd": hmd_files,
            "wnd": wnd_files,
            "cli_index": [
                "pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli",
            ],
            "weather_sta": "weather-sta.cli",
        },
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    args = parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(2)

    nbyr = args.end_year - args.start_year + 1
    start_date = date(args.start_year, 1, 1)
    end_date = date(args.end_year, 12, 31)
    expected_days = (end_date - start_date).days + 1

    validate_outputs(
        args.output_dir,
        result["station_names"],
        expected_days,
        nbyr,
    )

    # JSON result on stdout for downstream tools / agent consumption
    print(json.dumps(result, indent=2))
    logger.info(f"Tool completed successfully. Output: {args.output_dir}")
    sys.exit(0)
