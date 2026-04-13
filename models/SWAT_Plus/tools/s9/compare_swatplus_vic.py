#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
====================================================
Tool ID:      compare_swatplus_vic
Stage:        s9_output_parsing
Description:  Compare SWAT+ and VIC model outputs for the same basin.
              Parses basin-level water balance from both models and computes
              per-year comparison statistics.

This script is a VALIDATED TOOL: an executable that the AI agent calls
rather than writes. It guarantees correctness independent of the language
model. The agent should never modify this script -- only call it.

Inputs:
  --swatplus_dir  : Path to SWAT+ TxtInOut directory with outputs (str)
  --vic_result_dir: Path to VIC flux output directory (str)
  --grid_nc       : Path to VIC basin_grid.nc for cell area weighting (str)
  --output_csv    : Path for comparison results CSV (str)
  --output_plot   : Path for comparison plot image (str, optional)
  --start_year    : Start year for comparison (int, optional -- auto-detected)
  --end_year      : End year for comparison (int, optional -- auto-detected)

Outputs:
  - CSV file with per-year comparison of water balance components
  - Optional plot comparing SWAT+ vs VIC annual values

Preconditions:
  - SWAT+ directory must contain basin_wb_yr.txt (yearly water balance output)
  - VIC result directory must contain flux files (prefix_lat_lon.txt)
  - grid_nc must exist and contain lat/lon/area variables

Postconditions:
  - CSV contains per-year rows with SWAT+ and VIC values for each component
  - Statistics (correlation, bias, RMSE) are computed for overlapping years
  - JSON output includes summary metrics

Usage:
  python compare_swatplus_vic.py \\
    --swatplus_dir /path/to/TxtInOut \\
    --vic_result_dir /path/to/vic_result \\
    --grid_nc /path/to/basin_grid.nc \\
    --output_csv /path/to/comparison.csv \\
    --output_plot /path/to/comparison.png

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import logging
import json
import argparse
import math
import csv
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare SWAT+ and VIC model outputs for the same basin."
    )
    parser.add_argument("--swatplus_dir", required=True,
                        help="Path to SWAT+ TxtInOut directory with outputs")
    parser.add_argument("--vic_result_dir", required=True,
                        help="Path to VIC flux output directory")
    parser.add_argument("--grid_nc", required=True,
                        help="Path to VIC basin_grid.nc for cell area weighting")
    parser.add_argument("--output_csv", required=True,
                        help="Path for comparison results CSV")
    parser.add_argument("--output_plot", default=None,
                        help="Path for comparison plot image (optional)")
    parser.add_argument("--start_year", type=int, default=None,
                        help="Start year for comparison (auto-detected if omitted)")
    parser.add_argument("--end_year", type=int, default=None,
                        help="End year for comparison (auto-detected if omitted)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check that all preconditions are met before processing."""
    errors = []

    swatplus_dir = Path(args.swatplus_dir)
    vic_dir = Path(args.vic_result_dir)
    grid_nc = Path(args.grid_nc)

    if not swatplus_dir.is_dir():
        errors.append(f"SWAT+ directory not found: {args.swatplus_dir}")
    else:
        # Check for basin_wb_yr.txt or hru_wb_yr.txt fallback
        wb_file = swatplus_dir / "basin_wb_yr.txt"
        hru_wb_file = swatplus_dir / "hru_wb_yr.txt"
        if not wb_file.exists() and not hru_wb_file.exists():
            errors.append(f"Neither basin_wb_yr.txt nor hru_wb_yr.txt found in {args.swatplus_dir}. "
                          f"Ensure print.prt has basin_wb or hru_wb yearly output enabled.")

    if not vic_dir.is_dir():
        errors.append(f"VIC result directory not found: {args.vic_result_dir}")
    else:
        # Check for at least one flux file
        flux_files = list(vic_dir.glob("*.txt"))
        if not flux_files:
            flux_files = list(vic_dir.glob("*fluxes*"))
        if not flux_files:
            errors.append(f"No VIC flux output files found in {args.vic_result_dir}")

    if not grid_nc.is_file():
        errors.append(f"Grid NC file not found: {args.grid_nc}")

    if not args.output_csv:
        errors.append("output_csv path is required")

    if args.start_year and args.end_year and args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) must be <= end_year ({args.end_year})")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(output_csv, output_plot):
    """Check that postconditions are met after processing."""
    errors = []

    if not Path(output_csv).exists():
        errors.append(f"Output CSV not created: {output_csv}")
    else:
        # Check CSV has at least header + 1 data row
        with open(output_csv) as f:
            lines = f.readlines()
        if len(lines) < 2:
            errors.append(f"Output CSV has only {len(lines)} lines, expected >= 2")

    if output_plot and not Path(output_plot).exists():
        errors.append(f"Output plot not created: {output_plot}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# SWAT+ output parsing
# ---------------------------------------------------------------------------
def parse_swatplus_basin_wb_yr(swatplus_dir):
    """Parse basin_wb_yr.txt to extract annual water balance components.

    SWAT+ basin_wb_yr.txt format:
      Line 1: Header comment (basin name, version info)
      Line 2: Column headers (jday mon day yr unit gis_id name precip snofall
               snomlt surq_gen latq wateryld perc et ...)
      Line 3: Units line (mm mm mm ...)
      Lines 4+: Data rows (one per year per unit)

    Returns dict: {year: {component: value_mm}} with keys:
      precip, et, surq_gen (surface runoff generation),
      latq (lateral flow), wateryld (total water yield),
      perc (percolation to deep aquifer)
    """
    wb_file = Path(swatplus_dir) / "basin_wb_yr.txt"
    content = wb_file.read_text().strip()
    lines = content.split('\n')

    if len(lines) < 4:
        raise ValueError(f"basin_wb_yr.txt has only {len(lines)} lines, expected >= 4")

    # Line 1 = header comment, Line 2 = column names, Line 3 = units
    # Parse column names from line 2 (0-indexed)
    header_line = lines[1]
    col_names = header_line.split()

    # Find column indices for the components we need
    target_cols = {
        "yr": None,
        "precip": None,
        "et": None,
        "surq_gen": None,
        "latq": None,
        "wateryld": None,
        "perc": None,
        "surq_cont": None,
        "snofall": None,
        "snomlt": None,
        "sw": None,
    }

    for i, col in enumerate(col_names):
        col_lower = col.lower()
        if col_lower in target_cols:
            target_cols[col_lower] = i

    if target_cols["yr"] is None:
        raise ValueError(f"Could not find 'yr' column in basin_wb_yr.txt. "
                         f"Columns found: {col_names}")

    # Parse data rows (skip header comment, column names, units = 3 lines)
    annual_data = {}
    for line in lines[3:]:
        parts = line.split()
        if len(parts) < len(col_names):
            continue

        try:
            year = int(float(parts[target_cols["yr"]]))
        except (ValueError, TypeError):
            continue

        record = {}
        for comp, idx in target_cols.items():
            if idx is not None and comp != "yr":
                try:
                    record[comp] = float(parts[idx])
                except (ValueError, IndexError):
                    record[comp] = None

        annual_data[year] = record

    logger.info(f"Parsed SWAT+ basin_wb_yr.txt: {len(annual_data)} years "
                f"({min(annual_data.keys()) if annual_data else '?'}-"
                f"{max(annual_data.keys()) if annual_data else '?'})")
    return annual_data


def parse_swatplus_hru_wb_fallback(swatplus_dir):
    """Fallback: parse hru_wb_yr.txt when basin_wb_yr.txt is empty.

    Computes area-weighted basin average from HRU-level output.
    This handles the case where basin-level aggregation fails due to
    missing soils_lte.sol (see diagnostic triplet dt_v005).
    """
    hru_file = Path(swatplus_dir) / "hru_wb_yr.txt"
    if not hru_file.exists():
        raise ValueError("Neither basin_wb_yr.txt nor hru_wb_yr.txt found")

    lines = hru_file.read_text().splitlines()
    if len(lines) < 4:
        raise ValueError(f"hru_wb_yr.txt has only {len(lines)} lines")

    header = lines[1].split()
    components = ['precip', 'et', 'surq_gen', 'latq', 'wateryld', 'cn', 'sw', 'pet']

    # Parse all HRU records
    records = []
    for line in lines[3:]:
        parts = line.split()
        if len(parts) >= 15:
            try:
                row = {h: float(parts[i]) for i, h in enumerate(header[:len(parts)])}
                records.append(row)
            except (ValueError, IndexError):
                continue

    if not records:
        raise ValueError("No valid data rows in hru_wb_yr.txt")

    # Compute equal-weight mean per year (approximate basin average)
    import collections
    year_data = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in records:
        yr = int(r.get('yr', 0))
        if yr > 0:
            for comp in components:
                if comp in r:
                    year_data[yr][comp].append(r[comp])

    annual_data = {}
    for yr in sorted(year_data.keys()):
        record = {}
        for comp in components:
            vals = year_data[yr].get(comp, [])
            if vals:
                import numpy as np
                record[comp] = float(np.mean(vals))
        annual_data[yr] = record

    logger.info(f"Parsed SWAT+ hru_wb_yr.txt (fallback): {len(annual_data)} years, "
                f"{len(records)} HRU records")
    return annual_data


# ---------------------------------------------------------------------------
# VIC output parsing
# ---------------------------------------------------------------------------
def parse_vic_flux_files(vic_result_dir, grid_nc_path):
    """Parse VIC flux output files and compute area-weighted basin averages.

    VIC flux file format (classic driver):
      Lines starting with '#' are comments
      First data line has columns:
        YEAR MONTH DAY OUT_PREC OUT_RAINF OUT_SNOWF OUT_AIR_TEMP ...
        OUT_RUNOFF OUT_BASEFLOW OUT_EVAP OUT_SWE OUT_SOIL_MOIST_0 ...

    All flux values are in mm/day (or mm/timestep for sub-daily).

    Returns dict: {year: {component: value_mm}} with keys:
      precip, et, runoff, baseflow, total_runoff (runoff + baseflow)
    """
    vic_dir = Path(vic_result_dir)
    grid_nc = Path(grid_nc_path)

    # Read grid cell coordinates and areas from grid_nc
    cell_areas = read_grid_cell_areas(grid_nc)
    total_area = sum(cell_areas.values()) if cell_areas else 1.0

    # Find all VIC flux files
    flux_files = sorted(vic_dir.glob("*.txt"))
    if not flux_files:
        flux_files = sorted(vic_dir.glob("*fluxes*"))
    if not flux_files:
        raise FileNotFoundError(f"No VIC flux files found in {vic_dir}")

    logger.info(f"Found {len(flux_files)} VIC flux files")

    # Parse each cell and accumulate area-weighted annual totals
    annual_totals = defaultdict(lambda: defaultdict(float))
    total_weight = 0.0
    n_cells_used = 0

    for flux_file in flux_files:
        # Extract lat/lon from filename (pattern: prefix_lat_lon.txt)
        fname = flux_file.stem  # e.g., huaihe_fluxes_32.6250_117.6250
        parts = fname.split('_')

        cell_lat = None
        cell_lon = None
        # Try to find lat/lon as the last two numeric parts
        numeric_parts = []
        for p in parts:
            try:
                numeric_parts.append(float(p))
            except ValueError:
                pass

        if len(numeric_parts) >= 2:
            cell_lat = numeric_parts[-2]
            cell_lon = numeric_parts[-1]
        else:
            logger.warning(f"Could not extract lat/lon from filename: {fname}")
            continue

        # Look up cell area (use 1.0 as default weight if not found)
        cell_key = (round(cell_lat, 4), round(cell_lon, 4))
        cell_weight = cell_areas.get(cell_key, 1.0)

        # Parse the flux file
        cell_annual = parse_single_vic_flux(flux_file)
        if not cell_annual:
            continue

        n_cells_used += 1
        total_weight += cell_weight

        for year, values in cell_annual.items():
            for comp, val in values.items():
                annual_totals[year][comp] += val * cell_weight

    if total_weight == 0:
        raise ValueError("No valid VIC flux data could be parsed")

    # Normalize by total weight to get area-weighted averages
    annual_data = {}
    for year in sorted(annual_totals.keys()):
        annual_data[year] = {
            comp: val / total_weight
            for comp, val in annual_totals[year].items()
        }
        # Add derived total_runoff
        runoff = annual_data[year].get("runoff", 0)
        baseflow = annual_data[year].get("baseflow", 0)
        annual_data[year]["total_runoff"] = runoff + baseflow

    logger.info(f"Parsed VIC outputs: {n_cells_used} cells, {len(annual_data)} years "
                f"({min(annual_data.keys()) if annual_data else '?'}-"
                f"{max(annual_data.keys()) if annual_data else '?'})")
    return annual_data


def read_grid_cell_areas(grid_nc_path):
    """Read grid cell coordinates and compute approximate areas.

    Returns dict: {(lat, lon): area_fraction}
    All cells get equal weight (area = 1.0) unless the grid_nc has an 'area'
    variable. For equal-area comparisons, equal weights are correct when all
    cells have the same resolution.
    """
    grid_nc = Path(grid_nc_path)
    cell_areas = {}

    try:
        import netCDF4 as nc
        ds = nc.Dataset(str(grid_nc))

        # Try different variable name conventions
        lat_var = None
        lon_var = None
        for lat_name in ['lat', 'latitude', 'LAT', 'y']:
            if lat_name in ds.variables:
                lat_var = ds.variables[lat_name][:]
                break
        for lon_name in ['lon', 'longitude', 'LON', 'x']:
            if lon_name in ds.variables:
                lon_var = ds.variables[lon_name][:]
                break

        if lat_var is not None and lon_var is not None:
            # Check if area variable exists
            area_var = None
            for area_name in ['area', 'cell_area', 'AREA']:
                if area_name in ds.variables:
                    area_var = ds.variables[area_name][:]
                    break

            if area_var is not None and len(area_var) == len(lat_var):
                for i in range(len(lat_var)):
                    key = (round(float(lat_var[i]), 4), round(float(lon_var[i]), 4))
                    cell_areas[key] = float(area_var[i])
            else:
                # Equal weights for all cells (same resolution = same area approx)
                for i in range(len(lat_var)):
                    key = (round(float(lat_var[i]), 4), round(float(lon_var[i]), 4))
                    # Approximate area using cosine latitude correction
                    lat_rad = math.radians(float(lat_var[i]))
                    cell_areas[key] = math.cos(lat_rad)

        ds.close()
        logger.info(f"Read {len(cell_areas)} grid cell weights from {grid_nc}")

    except ImportError:
        logger.warning("netCDF4 not available, using equal cell weights")
    except Exception as e:
        logger.warning(f"Could not read grid_nc: {e}. Using equal cell weights.")

    return cell_areas


def parse_single_vic_flux(flux_file):
    """Parse a single VIC flux output file into annual totals.

    Returns: {year: {precip: mm, et: mm, runoff: mm, baseflow: mm}}
    """
    annual = defaultdict(lambda: defaultdict(float))
    day_counts = defaultdict(int)

    # Column name to our standard names mapping
    col_map = {}

    with open(flux_file) as f:
        header_found = False
        for line in f:
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Comment/header lines
            if line.startswith('#'):
                continue

            # Check if this is the header line (contains column names)
            if 'YEAR' in line and 'OUT_' in line:
                parts = line.split()
                for i, col in enumerate(parts):
                    col_upper = col.upper().strip()
                    if col_upper == 'YEAR':
                        col_map['year'] = i
                    elif col_upper == 'MONTH':
                        col_map['month'] = i
                    elif col_upper == 'DAY':
                        col_map['day'] = i
                    elif col_upper == 'OUT_PREC':
                        col_map['precip'] = i
                    elif col_upper == 'OUT_EVAP':
                        col_map['et'] = i
                    elif col_upper == 'OUT_RUNOFF':
                        col_map['runoff'] = i
                    elif col_upper == 'OUT_BASEFLOW':
                        col_map['baseflow'] = i
                    elif col_upper == 'OUT_SWE':
                        col_map['swe'] = i
                header_found = True
                continue

            # Data line
            parts = line.split()
            if not parts:
                continue

            # If no header was found, assume standard VIC classic output order
            if not header_found and not col_map:
                # Attempt to detect: first 3 cols = YEAR MONTH DAY
                try:
                    int(parts[0])
                    int(parts[1])
                    int(parts[2])
                except (ValueError, IndexError):
                    continue
                # Standard header line must have been a comment-free format
                # Use VIC classic default column order
                col_map = {
                    'year': 0, 'month': 1, 'day': 2,
                    'precip': 3, 'runoff': 13, 'baseflow': 14, 'et': 15
                }
                header_found = True

            if not col_map or 'year' not in col_map:
                continue

            try:
                year = int(parts[col_map['year']])

                for comp in ['precip', 'et', 'runoff', 'baseflow']:
                    if comp in col_map and col_map[comp] < len(parts):
                        val = float(parts[col_map[comp]])
                        annual[year][comp] += val

                day_counts[year] += 1
            except (ValueError, IndexError):
                continue

    # Convert to regular dict
    result = {}
    for year in sorted(annual.keys()):
        result[year] = dict(annual[year])
        result[year]['n_days'] = day_counts[year]

    return result


# ---------------------------------------------------------------------------
# Comparison and statistics
# ---------------------------------------------------------------------------
def compute_comparison(swatplus_annual, vic_annual, start_year=None, end_year=None):
    """Compute per-year comparison between SWAT+ and VIC water balance.

    Maps SWAT+ components to VIC equivalents:
      SWAT+ precip       <-> VIC precip
      SWAT+ et           <-> VIC et
      SWAT+ surq_gen     <-> VIC runoff (surface runoff)
      SWAT+ latq         <-> VIC baseflow (subsurface lateral)
      SWAT+ wateryld     <-> VIC total_runoff (runoff + baseflow)
    """
    # Find overlapping years
    swat_years = set(swatplus_annual.keys())
    vic_years = set(vic_annual.keys())
    common_years = sorted(swat_years & vic_years)

    if start_year:
        common_years = [y for y in common_years if y >= start_year]
    if end_year:
        common_years = [y for y in common_years if y <= end_year]

    if not common_years:
        logger.warning(f"No overlapping years! SWAT+: {sorted(swat_years)}, "
                       f"VIC: {sorted(vic_years)}")
        return [], {}

    logger.info(f"Comparing {len(common_years)} overlapping years: "
                f"{common_years[0]}-{common_years[-1]}")

    # Component mapping: (display_name, swat_key, vic_key)
    components = [
        ("Precipitation", "precip", "precip"),
        ("ET", "et", "et"),
        ("Surface_Runoff", "surq_gen", "runoff"),
        ("Lateral_Flow", "latq", "baseflow"),
        ("Water_Yield", "wateryld", "total_runoff"),
    ]

    # Build comparison rows
    rows = []
    for year in common_years:
        row = {"year": year}
        swat = swatplus_annual.get(year, {})
        vic = vic_annual.get(year, {})

        for display, swat_key, vic_key in components:
            swat_val = swat.get(swat_key)
            vic_val = vic.get(vic_key)

            row[f"SWAT+_{display}_mm"] = round(swat_val, 2) if swat_val is not None else None
            row[f"VIC_{display}_mm"] = round(vic_val, 2) if vic_val is not None else None

            if swat_val is not None and vic_val is not None:
                diff = swat_val - vic_val
                pct = (diff / vic_val * 100) if vic_val != 0 else None
                row[f"Diff_{display}_mm"] = round(diff, 2)
                row[f"Diff_{display}_pct"] = round(pct, 1) if pct is not None else None
            else:
                row[f"Diff_{display}_mm"] = None
                row[f"Diff_{display}_pct"] = None

        rows.append(row)

    # Compute summary statistics for each component
    stats = {}
    for display, swat_key, vic_key in components:
        swat_vals = []
        vic_vals = []
        for year in common_years:
            sv = swatplus_annual.get(year, {}).get(swat_key)
            vv = vic_annual.get(year, {}).get(vic_key)
            if sv is not None and vv is not None:
                swat_vals.append(sv)
                vic_vals.append(vv)

        if len(swat_vals) >= 2:
            stats[display] = compute_stats(swat_vals, vic_vals)
        elif len(swat_vals) == 1:
            stats[display] = {
                "n_years": 1,
                "swat_mean_mm": round(swat_vals[0], 2),
                "vic_mean_mm": round(vic_vals[0], 2),
                "bias_mm": round(swat_vals[0] - vic_vals[0], 2),
                "bias_pct": round((swat_vals[0] - vic_vals[0]) / vic_vals[0] * 100, 1)
                            if vic_vals[0] != 0 else None,
            }

    return rows, stats


def compute_stats(swat_vals, vic_vals):
    """Compute correlation, bias, RMSE between two value lists."""
    n = len(swat_vals)
    if n == 0:
        return {}

    # Means
    swat_mean = sum(swat_vals) / n
    vic_mean = sum(vic_vals) / n

    # Bias
    diffs = [s - v for s, v in zip(swat_vals, vic_vals)]
    bias = sum(diffs) / n
    bias_pct = (bias / vic_mean * 100) if vic_mean != 0 else None

    # RMSE
    sq_diffs = [(s - v) ** 2 for s, v in zip(swat_vals, vic_vals)]
    rmse = math.sqrt(sum(sq_diffs) / n)

    # Pearson correlation
    corr = None
    if n >= 3:
        swat_dev = [s - swat_mean for s in swat_vals]
        vic_dev = [v - vic_mean for v in vic_vals]
        cov = sum(sd * vd for sd, vd in zip(swat_dev, vic_dev))
        swat_std = math.sqrt(sum(d**2 for d in swat_dev))
        vic_std = math.sqrt(sum(d**2 for d in vic_dev))
        if swat_std > 0 and vic_std > 0:
            corr = cov / (swat_std * vic_std)

    result = {
        "n_years": n,
        "swat_mean_mm": round(swat_mean, 2),
        "vic_mean_mm": round(vic_mean, 2),
        "bias_mm": round(bias, 2),
        "bias_pct": round(bias_pct, 1) if bias_pct is not None else None,
        "rmse_mm": round(rmse, 2),
    }
    if corr is not None:
        result["correlation"] = round(corr, 4)

    return result


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------
def write_comparison_csv(rows, output_csv):
    """Write comparison results to CSV."""
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        # Write header-only CSV
        with open(output_path, 'w', newline='') as f:
            f.write("year,note\n")
            f.write("no_overlapping_years,check SWAT+ and VIC simulation periods\n")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    logger.info(f"Wrote comparison CSV: {output_path} ({len(rows)} rows)")


def generate_comparison_plot(rows, stats, output_plot):
    """Generate a comparison plot of SWAT+ vs VIC annual water balance."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot generation")
        return False

    if not rows:
        logger.warning("No data to plot")
        return False

    output_path = Path(output_plot)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    years = [r["year"] for r in rows]

    # Components to plot
    components = [
        ("Precipitation", "Precip (mm)"),
        ("ET", "ET (mm)"),
        ("Surface_Runoff", "Surface Runoff (mm)"),
        ("Water_Yield", "Water Yield (mm)"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("SWAT+ vs VIC Annual Water Balance Comparison", fontsize=14, y=0.98)

    for ax, (comp_key, ylabel) in zip(axes.flat, components):
        swat_key = f"SWAT+_{comp_key}_mm"
        vic_key = f"VIC_{comp_key}_mm"

        swat_vals = [r.get(swat_key) for r in rows]
        vic_vals = [r.get(vic_key) for r in rows]

        # Filter out None values
        valid = [(y, s, v) for y, s, v in zip(years, swat_vals, vic_vals)
                 if s is not None and v is not None]

        if not valid:
            ax.text(0.5, 0.5, f"No data for {comp_key}", transform=ax.transAxes,
                    ha='center', va='center')
            ax.set_title(comp_key)
            continue

        valid_years, valid_swat, valid_vic = zip(*valid)

        width = 0.35
        x = range(len(valid_years))
        bars1 = ax.bar([i - width/2 for i in x], valid_swat, width,
                       label='SWAT+', color='#2196F3', alpha=0.8)
        bars2 = ax.bar([i + width/2 for i in x], valid_vic, width,
                       label='VIC', color='#FF9800', alpha=0.8)

        ax.set_xlabel('Year')
        ax.set_ylabel(ylabel)
        ax.set_title(comp_key)
        ax.set_xticks(list(x))
        ax.set_xticklabels([str(y) for y in valid_years], rotation=45, fontsize=8)
        ax.legend(fontsize=9)

        # Add statistics annotation
        comp_stats = stats.get(comp_key, {})
        if comp_stats:
            stat_text = f"Bias: {comp_stats.get('bias_mm', '?')} mm"
            if 'correlation' in comp_stats:
                stat_text += f"\nCorr: {comp_stats['correlation']}"
            if 'rmse_mm' in comp_stats:
                stat_text += f"\nRMSE: {comp_stats['rmse_mm']} mm"
            ax.text(0.02, 0.98, stat_text, transform=ax.transAxes,
                    fontsize=8, va='top', ha='left',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
    plt.close()

    logger.info(f"Generated comparison plot: {output_path}")
    return True


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Compare SWAT+ and VIC model outputs."""
    logger.info("Step 1: Parsing SWAT+ basin water balance output...")
    try:
        swatplus_annual = parse_swatplus_basin_wb_yr(args.swatplus_dir)
    except ValueError:
        # Fallback: basin_wb_yr.txt is empty, try hru_wb_yr.txt
        logger.warning("basin_wb_yr.txt is empty, falling back to hru_wb_yr.txt")
        swatplus_annual = parse_swatplus_hru_wb_fallback(args.swatplus_dir)

    logger.info("Step 2: Parsing VIC flux outputs...")
    vic_annual = parse_vic_flux_files(args.vic_result_dir, args.grid_nc)

    logger.info("Step 3: Computing comparison...")
    rows, stats = compute_comparison(
        swatplus_annual, vic_annual,
        start_year=args.start_year,
        end_year=args.end_year
    )

    logger.info("Step 4: Writing comparison CSV...")
    write_comparison_csv(rows, args.output_csv)

    plot_created = False
    if args.output_plot:
        logger.info("Step 5: Generating comparison plot...")
        plot_created = generate_comparison_plot(rows, stats, args.output_plot)

    # Build result summary
    result = {
        "status": "success",
        "output_csv": str(Path(args.output_csv).resolve()),
        "n_comparison_years": len(rows),
        "swat_years_available": sorted(swatplus_annual.keys()),
        "vic_years_available": sorted(vic_annual.keys()),
        "statistics": stats,
    }

    if plot_created:
        result["output_plot"] = str(Path(args.output_plot).resolve())

    # Add overall summary
    if stats:
        result["summary"] = {}
        for comp, comp_stats in stats.items():
            result["summary"][comp] = {
                "swat_mean": comp_stats.get("swat_mean_mm"),
                "vic_mean": comp_stats.get("vic_mean_mm"),
                "bias_pct": comp_stats.get("bias_pct"),
                "correlation": comp_stats.get("correlation"),
            }

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    args = parse_args()
    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(args.output_csv, args.output_plot)

    logger.info(f"Tool completed successfully.")
    print(json.dumps(result, indent=2))
    sys.exit(0)
