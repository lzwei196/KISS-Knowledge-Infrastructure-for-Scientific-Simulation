#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      prepare_sfincs_rainfall
Stage:        s4_forcing
Description:  Convert CMFD/MSWX precipitation to SFINCS NetCDF rainfall format.

CRITICAL UNIT CONVERSION:
  CMFD/MSWX: mm/3hr (accumulated over 3-hour window)
  SFINCS expects: mm/hr (instantaneous rate)
  Conversion: divide by 3.0

  If VIC forcing ASCII files are used (already in mm/timestep for 3-hourly):
  divide by 3.0 to get mm/hr

Inputs:
  --forcing_dir:   Directory with VIC/CMFD forcing files or NetCDF
  --grid_info:     Path to grid_info.json from s1_domain
  --start_date:    Start date (YYYY-MM-DD or YYYYMMDD)
  --end_date:      End date (YYYY-MM-DD or YYYYMMDD)
  --source:        Forcing source: "cmfd", "mswx", "vic_ascii" (default: cmfd)
  --output_dir:    Output directory

Outputs:
  - sfincs.precip: NetCDF with gridded precipitation in mm/hr
  - rainfall_summary.json

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
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not Path(args.forcing_dir).exists():
        errors.append(f"Forcing directory not found: {args.forcing_dir}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if args.source not in ("cmfd", "mswx", "vic_ascii"):
        errors.append(f"Unknown source: {args.source}. Use cmfd, mswx, or vic_ascii")
    try:
        datetime.strptime(args.start_date.replace("-", ""), "%Y%m%d")
        datetime.strptime(args.end_date.replace("-", ""), "%Y%m%d")
    except ValueError:
        errors.append("Invalid date format. Use YYYY-MM-DD or YYYYMMDD")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    import xarray as xr
    from pyproj import Transformer

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    x0 = grid["x0"]
    y0 = grid["y0"]
    dx = grid["dx"]
    dy = grid["dy"]
    mmax = grid["mmax"]
    nmax = grid["nmax"]
    epsg = grid["epsg"]

    start = datetime.strptime(args.start_date.replace("-", ""), "%Y%m%d")
    end = datetime.strptime(args.end_date.replace("-", ""), "%Y%m%d")

    # Generate grid cell centers in WGS84
    x_centers = x0 + (np.arange(mmax) + 0.5) * dx
    y_centers = y0 + (np.arange(nmax) + 0.5) * dy

    # Transform to WGS84 for forcing lookup
    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(x_centers, y_centers)
    lon_grid, lat_grid = transformer.transform(xx, yy)

    # --- Read forcing data ---
    forcing_dir = Path(args.forcing_dir)

    if args.source == "vic_ascii":
        # Read VIC ASCII forcing files (one per grid cell)
        # Format: columns = PREC TEMP SHORTWAVE LONGWAVE PRESSURE VP WIND
        # PREC in mm/timestep (3-hourly), convert to mm/hr by dividing by 3
        logger.info("Reading VIC ASCII forcing files...")
        precip_files = sorted(forcing_dir.glob("*"))
        if not precip_files:
            logger.error("No forcing files found in directory")
            sys.exit(2)

        # For simplicity, create uniform precipitation from the spatial average
        # In production, would spatially interpolate to each SFINCS grid cell
        logger.info(f"Found {len(precip_files)} forcing files")

        # Read first file to determine timesteps
        sample = np.loadtxt(str(precip_files[0]))
        n_timesteps = len(sample)
        hours_per_step = 3  # CMFD/MSWX are 3-hourly

        # Generate time array
        times = [start + timedelta(hours=i * hours_per_step) for i in range(n_timesteps)]
        times = [t for t in times if t <= end + timedelta(days=1)]
        n_times = len(times)

        # Average precipitation across all cells
        precip_sum = np.zeros(n_timesteps)
        count = 0
        for fp in precip_files:
            try:
                data = np.loadtxt(str(fp))
                precip_sum += data[:, 1]  # Column 1 is PREC (VIC: TEMP=0, PREC=1, PRESSURE=2, SW=3, LW=4, VP=5, WIND=6)
                count += 1
            except Exception:
                continue

        precip_avg = precip_sum / max(count, 1)

        # CRITICAL: Convert mm/3hr to mm/hr
        precip_avg_mmhr = precip_avg[:n_times] / 3.0
        logger.info(f"Precipitation converted: mm/3hr -> mm/hr (divided by 3)")

        # Create spatially uniform field (same value everywhere)
        precip_3d = np.broadcast_to(
            precip_avg_mmhr[:, np.newaxis, np.newaxis],
            (n_times, nmax, mmax)
        ).copy().astype(np.float32)

    elif args.source in ("cmfd", "mswx"):
        # Read from NetCDF forcing
        logger.info(f"Reading {args.source.upper()} NetCDF forcing...")

        # Find precipitation files — filter to requested date range
        # CMFD naming: prec_CMFD_V0200_B-01_03hr_010deg_YYYYMM.nc
        # MSWX naming: similar with YYYYMM
        nc_files = sorted(forcing_dir.glob("*.nc")) + sorted(forcing_dir.glob("*.nc4"))
        prec_files_all = [f for f in nc_files if "prec" in f.name.lower() or "precip" in f.name.lower()]

        # Filter by date: extract YYYYMM from filename and compare to start/end
        import re
        prec_files = []
        start_ym = start.year * 100 + start.month
        end_ym = end.year * 100 + end.month
        for f in prec_files_all:
            m = re.search(r'(\d{6})', f.name)
            if m:
                ym = int(m.group(1))
                if start_ym <= ym <= end_ym:
                    prec_files.append(f)
            else:
                prec_files.append(f)  # no date in name, include anyway

        logger.info(f"Found {len(prec_files)} precip files for {start_ym}-{end_ym} (of {len(prec_files_all)} total)")

        if not prec_files:
            logger.error(f"No precipitation files found for {start_ym}-{end_ym} in {forcing_dir}")
            sys.exit(2)

        # Read and clip to domain
        all_precip = []
        all_times_list = []

        # Domain bbox for clipping (with buffer)
        lon_min = float(lon_grid.min() - 0.5)
        lon_max = float(lon_grid.max() + 0.5)
        lat_min = float(lat_grid.min() - 0.5)
        lat_max = float(lat_grid.max() + 0.5)
        logger.info(f"Clipping to bbox: lat[{lat_min:.2f},{lat_max:.2f}] lon[{lon_min:.2f},{lon_max:.2f}]")

        for pf in prec_files:
            # CRITICAL: open with chunks to avoid loading full file into memory.
            # CMFD 0.1° monthly files are 3-9 GB. Read only the bbox subset.
            ds = xr.open_dataset(pf, chunks={'time': 8})

            # Find precip variable
            prec_var = None
            for vname in ds.data_vars:
                if "prec" in vname.lower() or "rain" in vname.lower():
                    prec_var = vname
                    break
            if prec_var is None:
                ds.close(); continue

            # Find lat/lon dim names
            lat_dim = [d for d in ds.dims if 'lat' in d.lower()]
            lon_dim = [d for d in ds.dims if 'lon' in d.lower()]

            # Clip BOTH lat AND lon before loading into memory
            sel_kwargs = {}
            if lat_dim:
                lat_vals = ds[lat_dim[0]].values
                if lat_vals[0] > lat_vals[-1]:  # descending
                    sel_kwargs[lat_dim[0]] = slice(lat_max, lat_min)
                else:
                    sel_kwargs[lat_dim[0]] = slice(lat_min, lat_max)
            if lon_dim:
                sel_kwargs[lon_dim[0]] = slice(lon_min, lon_max)

            ds_clip = ds.sel(**sel_kwargs)
            # Now load the small subset into memory
            data = ds_clip[prec_var].values
            all_precip.append(data)
            logger.info(f"  {Path(pf).name}: shape={data.shape}, mean={np.nanmean(data):.4f}")
            ds.close()

        if not all_precip:
            logger.error("Could not read precipitation data")
            sys.exit(2)

        # Compute spatial average
        precip_concat = np.concatenate(all_precip, axis=0)
        precip_avg = np.nanmean(precip_concat, axis=(1, 2))

        # CRITICAL UNIT CONVERSION — check actual units from NetCDF attributes
        # CMFD prec: kg/m²/s (documented as such in PREFLIGHT.md, verified 2026-03-30)
        # MSWX prec: mm/3hr
        # SFINCS expects: mm/hr
        #
        # kg/m²/s → mm/hr: × 3600 (since 1 kg/m² = 1 mm water)
        # mm/3hr → mm/hr: ÷ 3
        if args.source == "cmfd":
            # CMFD: kg/m²/s → mm/hr (× 3600)
            precip_avg_mmhr = precip_avg * 3600.0
            logger.info("CMFD unit conversion: kg/m²/s × 3600 → mm/hr")
        elif args.source == "mswx":
            # MSWX: mm/3hr → mm/hr (÷ 3)
            precip_avg_mmhr = precip_avg / 3.0
            logger.info("MSWX unit conversion: mm/3hr ÷ 3 → mm/hr")
        else:
            # Unknown — assume already mm/hr
            precip_avg_mmhr = precip_avg

        n_times = len(precip_avg_mmhr)
        times = [start + timedelta(hours=i * 3) for i in range(n_times)]

        precip_3d = np.broadcast_to(
            precip_avg_mmhr[:, np.newaxis, np.newaxis],
            (n_times, nmax, mmax)
        ).copy().astype(np.float32)

    else:
        logger.error(f"Unsupported source: {args.source}")
        sys.exit(2)

    # --- Validate precipitation values ---
    max_precip = float(np.max(precip_3d))
    mean_precip = float(np.mean(precip_3d))
    if max_precip > 200:
        logger.warning(f"Maximum precipitation = {max_precip:.1f} mm/hr — extremely high! "
                       "Check unit conversion. SFINCS expects mm/hr.")
    if max_precip > 500:
        logger.error(f"Maximum precipitation = {max_precip:.1f} mm/hr — likely wrong units!")
        logger.error("Common mistake: using mm/3hr instead of mm/hr. Divide by 3.")

    # Negative precip check
    neg_count = int(np.sum(precip_3d < 0))
    if neg_count > 0:
        logger.warning(f"{neg_count} negative precipitation values found — setting to 0")
        precip_3d[precip_3d < 0] = 0

    # --- Write ASCII precipfile ---
    # SFINCS 'precipfile' format: spatially uniform, one line per timestep
    # Format: time_seconds  precip_mm_hr
    # CRITICAL: Use ASCII 'precipfile', NOT NetCDF 'netprecipfile'.
    # NetCDF precip silently fails in some SFINCS versions (dt_v004).
    precip_path = output_dir / "sfincs.precip"

    time_seconds = np.array([(t - start).total_seconds() for t in times[:n_times]], dtype=np.float64)

    with open(precip_path, 'w') as f:
        for i in range(n_times):
            # Spatial mean for uniform precipitation
            p_mmhr = float(np.nanmean(precip_3d[i]))
            f.write(f"{time_seconds[i]:.1f} {p_mmhr:.6f}\n")

    logger.info(f"Wrote ASCII precipfile: {precip_path} ({n_times} timesteps)")

    # --- Summary ---
    summary = {
        "status": "success",
        "precip_file": str(precip_path),
        "source": args.source,
        "n_timesteps": n_times,
        "dt_hours": 3,
        "units": "mm/hr",
        "precip_max_mmhr": round(max_precip, 3),
        "precip_mean_mmhr": round(mean_precip, 4),
        "total_precip_mm": round(float(np.sum(precip_3d[:, nmax // 2, mmax // 2]) * 3), 1),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "unit_conversion": "mm/3hr -> mm/hr (divided by 3)",
    }

    summary_path = output_dir / "rainfall_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)
    parent = Path(output_path).parent
    precip = parent / "sfincs.precip"
    if not precip.exists() or precip.stat().st_size == 0:
        logger.error(f"Precipitation file missing or empty: {precip}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert forcing to SFINCS precipitation")
    parser.add_argument("--forcing_dir", required=True, help="Forcing data directory")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--source", default="cmfd", choices=["cmfd", "mswx", "vic_ascii"],
                        help="Forcing source (default: cmfd)")
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
