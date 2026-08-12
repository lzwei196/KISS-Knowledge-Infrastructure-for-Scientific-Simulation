#!/usr/bin/env python3
"""
convert_forcing_to_anuga.py — Convert CMFD/MSWX/NASA POWER forcing data to
ANUGA-compatible rainfall and inflow boundary time series.

ANUGA needs rainfall as a rate in m/s applied via Rate_operator. This script:
  1. Loads sub-daily precipitation from CMFD (3-hourly) or daily from any source
  2. Converts mm/timestep → m/s
  3. Writes a two-column CSV (time_seconds, rainfall_m_per_s) for use in run_anuga.py

Unit conversions:
  - CMFD precip: kg/m²/s (raw) → mm/timestep (load_hourly_forcing) → m/s (÷1000 ÷ timestep_s)
  - MSWX precip: mm/3hr → m/s (÷1000 ÷ 10800)
  - NASA POWER precip: mm/hr → m/s (÷1000 ÷ 3600)
  - Daily sources: mm/day → m/s (÷1000 ÷ 86400)

Usage:
    python convert_forcing_to_anuga.py \
        --source cmfd \
        --lat 32.9 --lon 117.4 \
        --start_year 2005 --end_year 2005 \
        --output_dir ./forcing/

Output:
    rainfall_timeseries.csv  — columns: time_seconds, rainfall_m_per_s
    forcing_summary.json     — metadata (n_timesteps, total_precip_mm, etc.)
"""

import argparse
import csv
import json
import logging
import os
import sys

import numpy as np

# Ensure ki_tools_common is importable
_ki_common = "/mnt/disk1/Hydrocraft_server/models/ki_tools_common"
if _ki_common not in sys.path:
    sys.path.insert(0, _ki_common)

from ki_tools_common.load_forcing import load_daily_forcing, load_hourly_forcing

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate input parameters."""
    errors = []

    if args.source not in ("cmfd", "mswx", "nasa_power"):
        errors.append(f"Unknown source: {args.source}. Use cmfd, mswx, or nasa_power")

    if not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if not (-180 <= args.lon <= 180):
        errors.append(f"Longitude out of range: {args.lon}")

    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")


def validate_outputs(output_dir):
    """Validate output files."""
    errors = []

    csv_path = os.path.join(output_dir, "rainfall_timeseries.csv")
    if not os.path.isfile(csv_path):
        errors.append(f"Missing output: {csv_path}")
    else:
        with open(csv_path) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            rows = list(reader)
        if len(rows) == 0:
            errors.append("rainfall_timeseries.csv has no data rows")
        else:
            # Check for negative rainfall rates
            rates = [float(r[1]) for r in rows if len(r) >= 2]
            if any(r < 0 for r in rates):
                errors.append("Negative rainfall rates found — check unit conversion")
            # Check for unrealistically high rates (> 0.01 m/s = 36 mm/hr)
            max_rate = max(rates) if rates else 0
            if max_rate > 0.01:
                logger.warning(
                    f"Max rainfall rate {max_rate:.6f} m/s = {max_rate*3600*1000:.1f} mm/hr "
                    f"is very high — verify source data"
                )

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} output validation error(s)")

    logger.info("Output validation passed")


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → load → convert → write → validate."""

    # Step 1: Validate inputs
    validate_inputs(args)

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 2: Load forcing data
    logger.info(f"Loading {args.source} forcing at ({args.lat}, {args.lon}) "
                f"for {args.start_year}-{args.end_year}")

    try:
        # Try sub-daily first (preferred for flood modeling)
        data = load_hourly_forcing(
            args.source, args.lat, args.lon,
            args.start_year, args.end_year,
            forcing_dir=args.forcing_dir,
        )
        timestep_s = data["timestep_seconds"]
        precip_mm = data["precip_mm"]  # mm per timestep
        dates = data["dates"]
        # An EMPTY sub-daily load (forcing_dir points at a daily store, or the
        # sub-daily archive lacks coverage for this point/period) is NOT success:
        # it must fall back to daily, else a 0-row rainfall CSV is written and the
        # simulation runs on a rainfall series with no timesteps. (KI bug fix.)
        if len(dates) == 0 or len(precip_mm) == 0:
            raise ValueError("sub-daily load returned 0 timesteps")
        logger.info(f"Loaded sub-daily forcing: {len(dates)} timesteps, "
                    f"dt={timestep_s}s")
    except Exception as e:
        logger.warning(f"Sub-daily loading unavailable ({e}), falling back to daily")
        data = load_daily_forcing(
            args.source, args.lat, args.lon,
            args.start_year, args.end_year,
            forcing_dir=args.forcing_dir,
        )
        timestep_s = 86400
        precip_mm = data["precip_mm"]  # mm/day
        dates = data["dates"]
        logger.info(f"Loaded daily forcing: {len(dates)} timesteps")
        if len(dates) == 0 or len(precip_mm) == 0:
            raise ValueError(
                "Both sub-daily and daily forcing loads returned 0 timesteps for "
                f"({args.lat},{args.lon}) {args.start_year}-{args.end_year}; check "
                "forcing_dir coverage for this point/period."
            )

    # Step 3: Convert mm/timestep → m/s
    # mm → m: divide by 1000
    # per timestep → per second: divide by timestep_s
    rainfall_m_per_s = np.maximum(precip_mm, 0) / 1000.0 / timestep_s

    # Build time axis in seconds from start
    n = len(rainfall_m_per_s)
    time_seconds = np.arange(n, dtype=np.float64) * timestep_s

    # Step 4: Write rainfall CSV
    csv_path = os.path.join(args.output_dir, "rainfall_timeseries.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_seconds", "rainfall_m_per_s"])
        for t, r in zip(time_seconds, rainfall_m_per_s):
            writer.writerow([f"{t:.0f}", f"{r:.10e}"])

    logger.info(f"Wrote {csv_path} ({n} timesteps)")

    # Step 5: Write summary JSON
    total_precip_mm = float(np.nansum(precip_mm))
    summary = {
        "source": args.source,
        "lat": args.lat,
        "lon": args.lon,
        "start_year": args.start_year,
        "end_year": args.end_year,
        "n_timesteps": n,
        "timestep_seconds": timestep_s,
        "total_duration_seconds": float(time_seconds[-1]) if n > 0 else 0,
        "total_precip_mm": round(total_precip_mm, 2),
        "mean_precip_mm_per_day": round(total_precip_mm / max(1, n * timestep_s / 86400), 2),
        "max_rainfall_m_per_s": float(np.max(rainfall_m_per_s)) if n > 0 else 0,
        "output_csv": csv_path,
    }

    summary_path = os.path.join(args.output_dir, "forcing_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Wrote {summary_path}")

    # Step 6: Validate outputs
    validate_outputs(args.output_dir)

    logger.info(
        f"Conversion complete: {n} timesteps, "
        f"total precip {total_precip_mm:.1f} mm, "
        f"max rate {np.max(rainfall_m_per_s):.2e} m/s"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to ANUGA rainfall time series",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", required=True,
                        choices=["cmfd", "mswx", "nasa_power"],
                        help="Forcing data source")
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude (degrees N)")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude (degrees E)")
    parser.add_argument("--start_year", type=int, required=True,
                        help="Start year (inclusive)")
    parser.add_argument("--end_year", type=int, required=True,
                        help="End year (inclusive)")
    parser.add_argument("--forcing_dir", default=None,
                        help="Override default forcing data directory")
    parser.add_argument("--output_dir", default=".",
                        help="Output directory (default: current)")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
