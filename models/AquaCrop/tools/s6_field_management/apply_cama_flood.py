"""
CaMa-Flood → AquaCrop Waterlogging Coupling (C4).

Converts CaMa-Flood daily flood depth (flddph) and inundation fraction
(fldfrc) into an AquaCrop GroundWater object with time-varying water
table depth. During flood events, the water table rises to the surface,
triggering AquaCrop's built-in aeration stress module.

Works as a general tool for any basin — reads CaMa-Flood NetCDF output
and produces either:
  (a) A GroundWater object (for use in Python scripts)
  (b) A daily water table CSV (for external use / validation)

Logic:
  If fldfrc > threshold AND flddph > min_depth:
    → water table at surface (0 m) — full waterlogging stress
  If flddph > 0 but below threshold:
    → water table = max(0, profile_depth - flddph * 100)
  Otherwise:
    → water table at default depth (no stress)

Usage:
    python apply_cama_flood.py \
        --cama_out model/cmf_v420_pkg/out/<run_name> \
        --lat 33.125 --lon 117.125 \
        --start_date 2005-01-01 --end_date 2005-12-31 \
        --output outputs/<basin>/aquacrop/flood_gw.csv

    # In Python (import as module):
    from apply_cama_flood import build_groundwater_from_cama
    gw = build_groundwater_from_cama(cama_out_dir, lat, lon, start_date, end_date)
    model = AquaCropModel(..., groundwater=gw)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("apply_cama_flood")

# Defaults
DEFAULT_NONSTRESS_WTD = 3.0     # m below surface when no flooding
FLOOD_FRACTION_THRESHOLD = 0.1  # fldfrc > 10% = flood event
FLOOD_DEPTH_MIN = 0.05          # m — ignore very shallow flooding
PROFILE_DEPTH = 2.0             # m — assumed soil profile depth


def extract_cama_timeseries(
    cama_out_dir: str,
    lat: float, lon: float,
    start_date: str, end_date: str,
) -> pd.DataFrame:
    """
    Extract daily CaMa-Flood flddph and fldfrc for a single grid cell.

    Returns DataFrame with columns: date, flddph, fldfrc
    """
    import xarray as xr

    cama_dir = Path(cama_out_dir)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    records = []
    for year in range(start.year, end.year + 1):
        flddph_file = cama_dir / f"o_flddph{year}.nc"
        fldfrc_file = cama_dir / f"o_fldfrc{year}.nc"

        if not flddph_file.exists():
            logger.warning("CaMa flood depth file not found: %s", flddph_file)
            continue

        ds_depth = xr.open_dataset(flddph_file)
        cama_lats = ds_depth['lat'].values
        cama_lons = ds_depth['lon'].values

        # Find nearest cell
        ci = int(np.argmin(np.abs(cama_lats - lat)))
        cj = int(np.argmin(np.abs(cama_lons - lon)))

        flddph = ds_depth['flddph'][:, ci, cj].values
        n_days = len(flddph)
        ds_depth.close()

        # Get flood fraction if available
        if fldfrc_file.exists():
            ds_frac = xr.open_dataset(fldfrc_file)
            fldfrc = ds_frac['fldfrc'][:, ci, cj].values
            ds_frac.close()
        else:
            # Estimate: any flood depth > 0 = fraction 1.0
            fldfrc = np.where(flddph > 0.01, 1.0, 0.0)

        year_start = pd.Timestamp(f"{year}-01-01")
        for d in range(n_days):
            date = year_start + timedelta(days=d)
            if start <= date <= end:
                records.append({
                    "date": date,
                    "flddph": float(flddph[d]) if not np.isnan(flddph[d]) else 0.0,
                    "fldfrc": float(fldfrc[d]) if not np.isnan(fldfrc[d]) else 0.0,
                })

    if not records:
        logger.error("No CaMa-Flood data found for (%.3f, %.3f) %s to %s",
                      lat, lon, start_date, end_date)
        return pd.DataFrame(columns=["date", "flddph", "fldfrc"])

    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    logger.info("Extracted %d days of CaMa data for (%.3f, %.3f)", len(df), lat, lon)
    return df


def compute_water_table_depth(
    df: pd.DataFrame,
    nonstress_wtd: float = DEFAULT_NONSTRESS_WTD,
    flood_frac_threshold: float = FLOOD_FRACTION_THRESHOLD,
    flood_depth_min: float = FLOOD_DEPTH_MIN,
    profile_depth: float = PROFILE_DEPTH,
) -> pd.DataFrame:
    """
    Convert CaMa-Flood data to daily water table depth for AquaCrop.

    Adds 'wtd_m' column (water table depth in meters below surface).
    """
    wtd = np.full(len(df), nonstress_wtd)

    for i, row in df.iterrows():
        flddph = row['flddph']
        fldfrc = row['fldfrc']

        if fldfrc > flood_frac_threshold and flddph > flood_depth_min:
            # Significant flooding — water table at/above surface
            wtd[i] = 0.0
        elif flddph > 0.01:
            # Minor flooding — shallow water table
            wtd[i] = max(0.1, profile_depth - flddph)
        # else: keep default (deep water table, no stress)

    df = df.copy()
    df['wtd_m'] = wtd
    return df


def build_groundwater_from_cama(
    cama_out_dir: str,
    lat: float, lon: float,
    start_date: str, end_date: str,
    nonstress_wtd: float = DEFAULT_NONSTRESS_WTD,
    flood_frac_threshold: float = FLOOD_FRACTION_THRESHOLD,
    flood_depth_min: float = FLOOD_DEPTH_MIN,
):
    """
    Build an AquaCrop GroundWater object from CaMa-Flood output.

    Returns:
        aquacrop.entities.groundWater.GroundWater object with daily water table
        pd.DataFrame with daily data (for validation/plotting)
    """
    from aquacrop import GroundWater

    # Extract CaMa data
    df = extract_cama_timeseries(cama_out_dir, lat, lon, start_date, end_date)
    if df.empty:
        logger.warning("No CaMa data — returning no-groundwater object")
        return GroundWater(water_table='N'), df

    # Compute water table depth
    df = compute_water_table_depth(
        df, nonstress_wtd=nonstress_wtd,
        flood_frac_threshold=flood_frac_threshold,
        flood_depth_min=flood_depth_min,
    )

    # Build GroundWater object
    dates = [d.strftime("%Y/%m/%d") for d in df['date']]
    values = df['wtd_m'].tolist()

    gw = GroundWater(
        water_table='Y',
        method='Variable',
        dates=dates,
        values=values,
    )

    # Stats
    flood_days = int((df['wtd_m'] < 0.5).sum())
    total_days = len(df)
    logger.info(
        "GroundWater object: %d days, %d flood days (%.1f%%), "
        "mean WTD=%.1f m, min WTD=%.2f m",
        total_days, flood_days, flood_days / max(total_days, 1) * 100,
        df['wtd_m'].mean(), df['wtd_m'].min(),
    )

    return gw, df


# =====================================================================
# CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CaMa-Flood → AquaCrop waterlogging coupling (C4).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cama_out", required=True, help="CaMa-Flood output directory")
    parser.add_argument("--lat", type=float, required=True, help="Target latitude")
    parser.add_argument("--lon", type=float, required=True, help="Target longitude")
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default=None, help="Output CSV path (daily water table)")
    parser.add_argument("--nonstress_wtd", type=float, default=DEFAULT_NONSTRESS_WTD,
                        help="Water table depth (m) when no flooding (default: 3.0)")
    parser.add_argument("--flood_threshold", type=float, default=FLOOD_FRACTION_THRESHOLD,
                        help="Flood fraction threshold (default: 0.1)")
    parser.add_argument("--flood_depth_min", type=float, default=FLOOD_DEPTH_MIN,
                        help="Minimum flood depth in m (default: 0.05)")
    args = parser.parse_args()

    gw, df = build_groundwater_from_cama(
        cama_out_dir=args.cama_out,
        lat=args.lat, lon=args.lon,
        start_date=args.start_date,
        end_date=args.end_date,
        nonstress_wtd=args.nonstress_wtd,
        flood_frac_threshold=args.flood_threshold,
        flood_depth_min=args.flood_depth_min,
    )

    if df.empty:
        print(json.dumps({"status": "error", "message": "No CaMa data found"}))
        sys.exit(2)

    # Save CSV
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        logger.info("Saved: %s", args.output)

    # Summary
    flood_days = int((df['wtd_m'] < 0.5).sum())
    summary = {
        "status": "ok",
        "total_days": len(df),
        "flood_days": flood_days,
        "flood_pct": round(flood_days / len(df) * 100, 1),
        "mean_wtd_m": round(float(df['wtd_m'].mean()), 2),
        "max_flood_depth_m": round(float(df['flddph'].max()), 2),
        "output_csv": args.output,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
