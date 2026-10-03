#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      prepare_sfincs_rainfall
Stage:        s4_forcing
Description:  Build the SFINCS rainfall file straight from a precipitation source
              (CMFD or MSWX), read through the shared loader
              ki_tools_common.load_forcing.load_hourly_forcing at the domain centre.

CRITICAL UNIT CONVERSION:
  The loader gives mm accumulated in the step (3 hours for CMFD and MSWX)
  SFINCS expects: mm/hr (a rate)
  Conversion: divide by the step length in hours (3.0)

Inputs:
  --forcing_dir:   Root folder of the CMFD or MSWX store
  --grid_info:     Path to grid_info.json from s1_domain
  --start_date:    Start date (YYYY-MM-DD or YYYYMMDD)
  --end_date:      End date (YYYY-MM-DD or YYYYMMDD)
  --source:        "cmfd" (China) or "mswx" (global). Required, no default.
  --output_dir:    Output directory

Outputs:
  - sfincs.precip: ASCII, one line per step: seconds since start, mm/hr (spatially uniform)
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

# Sources the shared loader reads for this tool.
LOADER_SOURCES = ("cmfd", "mswx")


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not Path(args.forcing_dir).exists():
        errors.append(f"Forcing directory not found: {args.forcing_dir}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if args.source not in LOADER_SOURCES:
        errors.append(f"Unknown source: {args.source}. Use cmfd or mswx")
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

    if args.source in LOADER_SOURCES:
        # Rainfall is read STRAIGHT FROM THE SOURCE through the shared loader
        # (ki_tools_common.load_forcing.load_hourly_forcing), which knows each
        # store's file layout, variable names and units, and opens the files
        # whichever HDF5 library the process loaded first. This tool reads no
        # other model's forcing files and opens no source NetCDF itself.
        from ki_tools_common.load_forcing import load_hourly_forcing

        c_lon = float(np.mean(lon_grid))
        c_lat = float(np.mean(lat_grid))
        logger.info(f"Reading {args.source.upper()} precipitation at domain centre "
                    f"({c_lat:.3f}N, {c_lon:.3f}E) via ki_tools_common.load_forcing")
        if args.source == "mswx":
            logger.info("NOTE: MSWX annual files are one gzip slab per global timestep — "
                        "a single-point read still decompresses the whole year (~5 min/variable).")

        fc = load_hourly_forcing(args.source, c_lat, c_lon, start.year, end.year,
                                 forcing_dir=str(forcing_dir))
        fdates = np.asarray(fc["dates"]).astype("datetime64[s]").astype(object)
        praw = np.asarray(fc["precip_mm"], dtype=np.float64)   # mm in the step
        step_hours = float(fc["timestep_seconds"]) / 3600.0
        if not np.isfinite(step_hours) or step_hours <= 0:
            logger.error(f"{args.source}: loader gave timestep_seconds={fc['timestep_seconds']}")
            sys.exit(2)

        # Clip to the requested window (end date inclusive of its last step)
        end_incl = end + timedelta(days=1)
        sel = np.array([(d >= start) and (d < end_incl) for d in fdates])
        if not sel.any():
            logger.error(f"{args.source.upper()} has no timesteps between {start} and {end_incl}")
            sys.exit(2)
        times = [d for d, k in zip(fdates, sel) if k]
        praw = praw[sel]
        expected = np.arange(np.datetime64(start, 's'), np.datetime64(end_incl, 's'),
                             np.timedelta64(int(fc['timestep_seconds']), 's'))
        if not np.array_equal(np.asarray(times, dtype='datetime64[s]'), expected):
            raise ValueError("Forcing must cover every requested timestep in increasing order; gaps, duplicates and partial windows are refused")
        if not np.isfinite(praw).all():
            logger.error(f"{args.source.upper()}: {int((~np.isfinite(praw)).sum())} missing "
                         f"precipitation values in the window; nothing is filled in")
            sys.exit(2)

        # CRITICAL UNIT CONVERSION (dt_001): the loader gives precipitation as mm
        # accumulated in the step. SFINCS wants a RATE in mm/hr -> divide by the
        # step length in hours (3 for cmfd and mswx).
        precip_avg_mmhr = praw / step_hours
        logger.info(f"{args.source.upper()} unit conversion: mm per {step_hours:g} h step / "
                    f"{step_hours:g} -> mm/hr (max {precip_avg_mmhr.max():.3f} mm/hr, "
                    f"total {praw.sum():.1f} mm over {len(praw)} steps)")

        n_times = len(precip_avg_mmhr)
        # precipfile is spatially uniform; allocating time x rows x columns
        # wastes gigabytes and can kill an otherwise valid large-domain run.
        precip_mmhr = precip_avg_mmhr.astype(np.float32)

    else:
        logger.error(f"Unsupported source: {args.source}")
        sys.exit(2)

    # --- Validate precipitation values ---
    max_precip = float(np.max(precip_mmhr))
    mean_precip = float(np.mean(precip_mmhr))
    if max_precip > 200:
        logger.warning(f"Maximum precipitation = {max_precip:.1f} mm/hr — extremely high! "
                       "Check unit conversion. SFINCS expects mm/hr.")
    if max_precip > 500:
        logger.error(f"Maximum precipitation = {max_precip:.1f} mm/hr — likely wrong units!")
        logger.error("Common mistake: using mm/3hr instead of mm/hr. Divide by 3.")

    # Negative precip check
    neg_count = int(np.sum(precip_mmhr < 0))
    if neg_count > 0:
        raise ValueError(f"{neg_count} negative precipitation values found; repair the source data")

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
            p_mmhr = float(precip_mmhr[i])
            f.write(f"{time_seconds[i]:.1f} {p_mmhr:.6f}\n")

    logger.info(f"Wrote ASCII precipfile: {precip_path} ({n_times} timesteps)")

    # --- Summary ---
    summary = {
        "status": "success",
        "precip_file": str(precip_path),
        "source": args.source,
        "n_timesteps": n_times,
        "dt_hours": step_hours,
        "units": "mm/hr",
        "precip_max_mmhr": round(max_precip, 3),
        "precip_mean_mmhr": round(mean_precip, 4),
        "total_precip_mm": round(float(np.sum(precip_mmhr) * step_hours), 1),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "unit_conversion": f"mm per {step_hours:g} h step -> mm/hr (divided by {step_hours:g})",
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
    parser.add_argument("--forcing_dir", required=True,
                        help="Root folder of the CMFD or MSWX store")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--source", required=True, choices=list(LOADER_SOURCES),
                        help="Precipitation source, read through the shared loader: cmfd "
                             "(China) or mswx (global). No default.")
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
