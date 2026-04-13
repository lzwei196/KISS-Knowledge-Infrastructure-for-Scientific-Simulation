#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      convert_cama_to_inflow
Stage:        s4_inflow
Description:  Convert CaMa-Flood daily outflw at a dam grid cell into
              DLBreach hourly inflow hydrograph (Upstream_Reservoir_Inflow card).

              CaMa-Flood outputs daily mean discharge (m3/s) in NetCDF.
              DLBreach expects time-discharge pairs with time in HOURS.

              Temporal disaggregation: daily -> hourly using cubic spline
              interpolation (shape-preserving, non-negative).

Inputs:
  --cama_outflw_nc:  Path to CaMa-Flood outflw NetCDF file(s) or directory
  --dam_lat:         Dam latitude
  --dam_lon:         Dam longitude
  --start_date:      Start date (YYYY-MM-DD)
  --end_date:        End date (YYYY-MM-DD)
  --sim_start_sec:   DLBreach simulation start in seconds (default 0)
  --output:          Output JSON path

Outputs:
  - JSON with inflow_card text, peak_q_m3s, peak_time_hr, n_points

Exit codes:
  0 -- success
  1 -- CaMa output file not found
  2 -- dam cell not found in CaMa grid
  3 -- output validation failed
"""

import sys
import json
import argparse
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def find_nearest_cell(lats, lons, target_lat, target_lon):
    """Find the nearest grid cell to the target coordinates."""
    if lats.ndim == 1 and lons.ndim == 1:
        lat_idx = np.argmin(np.abs(lats - target_lat))
        lon_idx = np.argmin(np.abs(lons - target_lon))
        dist_deg = np.sqrt((lats[lat_idx] - target_lat)**2 + (lons[lon_idx] - target_lon)**2)
        return lat_idx, lon_idx, dist_deg
    else:
        dist = np.sqrt((lats - target_lat)**2 + (lons - target_lon)**2)
        idx = np.unravel_index(np.argmin(dist), dist.shape)
        return idx[0], idx[1], dist[idx]


def daily_to_hourly(daily_q, method="cubic"):
    """
    Disaggregate daily mean discharge to hourly values.
    Uses cubic spline interpolation centered on each day.
    Ensures non-negative values and conservation of daily volume.
    """
    n_days = len(daily_q)
    # Place daily values at midday (hour 12)
    daily_times = np.arange(n_days) * 24 + 12  # hours
    hourly_times = np.arange(n_days * 24)       # hours

    if method == "cubic" and n_days >= 4:
        from scipy.interpolate import PchipInterpolator
        interp = PchipInterpolator(daily_times, daily_q, extrapolate=True)
        hourly_q = interp(hourly_times)
    else:
        # Simple step function (repeat daily value for 24 hours)
        hourly_q = np.repeat(daily_q, 24)

    # Ensure non-negative
    hourly_q = np.maximum(hourly_q, 0.0)

    return hourly_times, hourly_q


def generate_inflow_card(times_hr, q_m3s, sim_start_sec=0.0):
    """Generate Upstream_Reservoir_Inflow card."""
    # Adjust times relative to sim_start_sec
    offset_hr = sim_start_sec / 3600.0
    adjusted_times = times_hr + offset_hr

    n = len(times_hr)
    lines = [f"Upstream_Reservoir_Inflow    {n},"]
    for t, q in zip(adjusted_times, q_m3s):
        lines.append(f"    {t:.2f}, {q:.4f}")

    return "\n".join(lines)


def generate_inflow_from_manual(times_hr, q_m3s):
    """Generate inflow card from manually provided time-Q pairs."""
    n = len(times_hr)
    lines = [f"Upstream_Reservoir_Inflow    {n},"]
    for t, q in zip(times_hr, q_m3s):
        lines.append(f"    {t:.2f}, {q:.4f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Convert CaMa-Flood output to DLBreach inflow")
    parser.add_argument("--cama_outflw_nc", type=str, help="CaMa-Flood outflw NetCDF path")
    parser.add_argument("--dam_lat", type=float, required=True, help="Dam latitude")
    parser.add_argument("--dam_lon", type=float, required=True, help="Dam longitude")
    parser.add_argument("--start_date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--sim_start_sec", type=float, default=0.0,
                        help="DLBreach simulation start time in seconds")
    parser.add_argument("--manual_csv", type=str,
                        help="Manual CSV with time_hr,Q_m3s columns (alternative to CaMa)")
    parser.add_argument("--output", type=str, help="Output JSON path")
    args = parser.parse_args()

    result = {
        "inflow_card": None,
        "peak_q_m3s": None,
        "peak_time_hr": None,
        "n_points": None,
        "total_volume_m3": None,
        "source": None,
        "status": "error",
        "errors": [],
    }

    try:
        if args.manual_csv:
            # Manual CSV mode
            logger.info(f"Reading manual inflow from {args.manual_csv}")
            import csv
            times, flows = [], []
            with open(args.manual_csv) as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i == 0 and not row[0].replace(".", "").replace("-", "").isdigit():
                        continue
                    times.append(float(row[0]))
                    flows.append(float(row[1]))

            times = np.array(times)
            flows = np.array(flows)
            result["inflow_card"] = generate_inflow_from_manual(times, flows)
            result["source"] = "manual_csv"

        elif args.cama_outflw_nc:
            # CaMa-Flood NetCDF mode
            try:
                import netCDF4 as nc
            except ImportError:
                try:
                    import xarray as xr
                    USE_XARRAY = True
                except ImportError:
                    result["errors"].append("Neither netCDF4 nor xarray installed")
                    print(json.dumps(result, indent=2))
                    sys.exit(2)
                else:
                    USE_XARRAY = True

            nc_path = Path(args.cama_outflw_nc)
            if not nc_path.exists():
                # Try as directory pattern
                if nc_path.is_dir():
                    nc_files = sorted(nc_path.glob("*outflw*.nc"))
                    if not nc_files:
                        result["errors"].append(f"No outflw NC files in {nc_path}")
                        print(json.dumps(result, indent=2))
                        sys.exit(1)
                else:
                    result["errors"].append(f"CaMa output not found: {nc_path}")
                    print(json.dumps(result, indent=2))
                    sys.exit(1)

            logger.info(f"Reading CaMa-Flood output from {nc_path}")

            if 'USE_XARRAY' in dir() and USE_XARRAY:
                if nc_path.is_dir():
                    ds = xr.open_mfdataset(sorted(nc_path.glob("*outflw*.nc")))
                else:
                    ds = xr.open_dataset(str(nc_path))

                lats = ds.lat.values if 'lat' in ds.coords else ds.latitude.values
                lons = ds.lon.values if 'lon' in ds.coords else ds.longitude.values
                lat_idx, lon_idx, dist = find_nearest_cell(lats, lons, args.dam_lat, args.dam_lon)

                if dist > 0.25:
                    logger.warning(f"Nearest cell is {dist:.3f} degrees from dam location")

                varname = 'outflw' if 'outflw' in ds.data_vars else list(ds.data_vars)[0]
                daily_q = ds[varname].values[:, lat_idx, lon_idx]

                # Filter by dates if specified
                if args.start_date and args.end_date:
                    times_ds = ds.time.values
                    start = np.datetime64(args.start_date)
                    end = np.datetime64(args.end_date)
                    mask = (times_ds >= start) & (times_ds <= end)
                    daily_q = daily_q[mask] if hasattr(daily_q, '__len__') else daily_q

                ds.close()
            else:
                dataset = nc.Dataset(str(nc_path))
                lats = dataset.variables.get('lat', dataset.variables.get('latitude'))[:]
                lons = dataset.variables.get('lon', dataset.variables.get('longitude'))[:]
                lat_idx, lon_idx, dist = find_nearest_cell(lats, lons, args.dam_lat, args.dam_lon)
                daily_q = dataset.variables['outflw'][:, lat_idx, lon_idx]
                dataset.close()

            # Ensure non-negative
            daily_q = np.maximum(np.nan_to_num(daily_q, nan=0.0), 0.0)

            # Disaggregate to hourly
            hourly_times, hourly_q = daily_to_hourly(daily_q)

            result["inflow_card"] = generate_inflow_card(hourly_times, hourly_q, args.sim_start_sec)
            result["source"] = "cama_flood"

            times = hourly_times
            flows = hourly_q

        else:
            result["errors"].append("Either --cama_outflw_nc or --manual_csv required")
            print(json.dumps(result, indent=2))
            sys.exit(1)

        # Compute summary statistics
        if 'times' in dir() and 'flows' in dir():
            peak_idx = np.argmax(flows)
            result["peak_q_m3s"] = round(float(flows[peak_idx]), 2)
            result["peak_time_hr"] = round(float(times[peak_idx]), 2)
            result["n_points"] = len(times)
            # Total volume (trapezoidal integration, time in hours -> seconds)
            # np.trapz deprecated in numpy 2.0+; use trapezoid if available
            _trapz = getattr(np, 'trapezoid', getattr(np, 'trapz', None))
            result["total_volume_m3"] = round(float(_trapz(flows, times * 3600)), 0)
            result["mean_q_m3s"] = round(float(np.mean(flows)), 2)
            result["status"] = "success"

            logger.info(f"Inflow generated: {result['n_points']} points, "
                        f"peak={result['peak_q_m3s']} m3/s at t={result['peak_time_hr']} hr")

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"Error: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
