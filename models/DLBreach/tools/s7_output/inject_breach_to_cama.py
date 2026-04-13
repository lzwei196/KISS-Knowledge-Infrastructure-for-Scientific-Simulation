#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      inject_breach_to_cama
Stage:        s7_output
Description:  Inject DLBreach breach outflow into CaMa-Flood runoff NetCDF
              at the downstream cell for flood routing of the dam-break wave.

              The breach outflow (hourly, m3/s) is converted to daily mean
              and added as additional runoff (mm/day per cell area) to the
              CaMa-Flood runoff input NetCDF.

              This enables the complete coupling:
              CaMa -> DLBreach (inflow) -> DLBreach (breach) -> CaMa (downstream flood)

Inputs:
  --breach_csv:       CSV from extract_breach_results (or casename_results.csv)
  --cama_runoff_nc:   CaMa-Flood runoff NetCDF (will be modified in-place or copied)
  --downstream_lat:   Latitude of downstream cell to inject into
  --downstream_lon:   Longitude of downstream cell to inject into
  --cell_area_m2:     Grid cell area in m2 (for mm/day conversion)
  --start_date:       Start date matching CaMa simulation (YYYY-MM-DD)
  --output_nc:        Output modified NetCDF path (if not in-place)

Outputs:
  - JSON with modified_nc_path, total_breach_volume_m3, cells_affected

Exit codes:
  0 -- success
  1 -- input file not found
  2 -- downstream cell not in CaMa grid
  3 -- NetCDF modification failed
"""

import sys
import json
import csv
import argparse
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def read_breach_csv(filepath):
    """Read breach results CSV, return time_hr and total flow (breach + spillway)."""
    times_hr = []
    total_flow = []

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = float(row["time_hr"])
            q_breach = float(row["breach_flow_m3s"])
            q_spill = float(row.get("spillway_gate_flow_m3s", 0))
            times_hr.append(t)
            total_flow.append(q_breach + q_spill)

    return np.array(times_hr), np.array(total_flow)


def hourly_to_daily_m3s(times_hr, flow_m3s):
    """Convert hourly flow to daily mean discharge."""
    if len(times_hr) == 0:
        return np.array([])

    # Determine number of days
    max_hr = times_hr[-1]
    n_days = int(np.ceil(max_hr / 24.0))

    daily_q = np.zeros(n_days)
    for d in range(n_days):
        t_start = d * 24.0
        t_end = (d + 1) * 24.0
        mask = (times_hr >= t_start) & (times_hr < t_end)
        if mask.any():
            daily_q[d] = np.mean(flow_m3s[mask])

    return daily_q


def m3s_to_mm_day(q_m3s, cell_area_m2):
    """Convert m3/s to mm/day for a grid cell."""
    # m3/s * 86400 s/day = m3/day
    # m3/day / cell_area_m2 = m/day
    # m/day * 1000 = mm/day
    return q_m3s * CMFD_PRECIP_KGM2S_TO_MMDAY / cell_area_m2 * 1000.0


def main():
    parser = argparse.ArgumentParser(description="Inject breach flow into CaMa-Flood runoff")
    parser.add_argument("--breach_csv", type=str, required=True,
                        help="Breach results CSV from extract_breach_results")
    parser.add_argument("--cama_runoff_nc", type=str, required=True,
                        help="CaMa-Flood runoff NetCDF to modify")
    parser.add_argument("--downstream_lat", type=float, required=True)
    parser.add_argument("--downstream_lon", type=float, required=True)
    parser.add_argument("--cell_area_m2", type=float,
                        help="Grid cell area in m2 (auto-computed if omitted)")
    parser.add_argument("--start_date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--breach_start_day", type=int, default=0,
                        help="Day index in CaMa simulation when breach starts")
    parser.add_argument("--output_nc", type=str,
                        help="Output NC path (if not modifying in-place)")
    parser.add_argument("--output", type=str, help="Output JSON metadata")
    args = parser.parse_args()

    result = {
        "modified_nc_path": None,
        "total_breach_volume_m3": None,
        "peak_daily_q_m3s": None,
        "n_days_affected": None,
        "downstream_cell": {"lat": args.downstream_lat, "lon": args.downstream_lon},
        "status": "error",
        "errors": [],
    }

    # Check inputs
    if not Path(args.breach_csv).exists():
        result["errors"].append(f"Breach CSV not found: {args.breach_csv}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    if not Path(args.cama_runoff_nc).exists():
        result["errors"].append(f"CaMa runoff NC not found: {args.cama_runoff_nc}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        import netCDF4 as nc
    except ImportError:
        try:
            import xarray as xr
            USE_XARRAY = True
        except ImportError:
            result["errors"].append("Neither netCDF4 nor xarray available")
            print(json.dumps(result, indent=2))
            sys.exit(2)
        else:
            USE_XARRAY = True

    # Read breach data
    times_hr, flow_m3s = read_breach_csv(args.breach_csv)
    daily_q = hourly_to_daily_m3s(times_hr, flow_m3s)

    total_volume = float(np.trapz(flow_m3s, times_hr * 3600))
    result["total_breach_volume_m3"] = round(total_volume, 0)
    result["peak_daily_q_m3s"] = round(float(np.max(daily_q)), 2)
    result["n_days_affected"] = int(np.sum(daily_q > 0))

    logger.info(f"Breach: {len(daily_q)} days, peak daily Q={result['peak_daily_q_m3s']} m3/s, "
                f"total volume={total_volume:.0f} m3")

    # Copy NC if output path specified
    import shutil
    if args.output_nc:
        shutil.copy2(args.cama_runoff_nc, args.output_nc)
        nc_path = args.output_nc
    else:
        nc_path = args.cama_runoff_nc

    # Modify NetCDF
    try:
        if 'USE_XARRAY' in dir() and USE_XARRAY:
            ds = xr.open_dataset(nc_path)
            lats = ds.lat.values if 'lat' in ds.coords else ds.latitude.values
            lons = ds.lon.values if 'lon' in ds.coords else ds.longitude.values

            lat_idx = int(np.argmin(np.abs(lats - args.downstream_lat)))
            lon_idx = int(np.argmin(np.abs(lons - args.downstream_lon)))

            dist = np.sqrt((lats[lat_idx] - args.downstream_lat)**2 +
                           (lons[lon_idx] - args.downstream_lon)**2)
            if dist > 0.25:
                result["errors"].append(f"Downstream cell {dist:.3f} deg from target, may be wrong")
                logger.warning(f"Nearest cell is {dist:.3f} deg from target")

            # Get runoff variable name
            runoff_var = None
            for vname in ['runoff', 'Runoff', 'RUNOFF', 'ro']:
                if vname in ds.data_vars:
                    runoff_var = vname
                    break
            if runoff_var is None:
                runoff_var = list(ds.data_vars)[0]
                logger.warning(f"No 'runoff' var found, using: {runoff_var}")

            ds.close()

            # Modify with netCDF4 for in-place editing
            dataset = nc.Dataset(nc_path, 'a')
            runoff = dataset.variables[runoff_var]

            # Compute cell area if not provided
            cell_area = args.cell_area_m2
            if cell_area is None:
                # Estimate from grid resolution
                if len(lats) > 1:
                    dlat = abs(float(lats[1] - lats[0]))
                else:
                    dlat = 0.25
                cell_area = (dlat * 111000) ** 2 * np.cos(np.radians(args.downstream_lat))
                logger.info(f"Estimated cell area: {cell_area:.0f} m2")

            # Add breach flow
            start_day = args.breach_start_day
            for d in range(len(daily_q)):
                day_idx = start_day + d
                if day_idx < runoff.shape[0]:
                    additional_mm = m3s_to_mm_day(daily_q[d], cell_area)
                    current = float(runoff[day_idx, lat_idx, lon_idx])
                    runoff[day_idx, lat_idx, lon_idx] = current + additional_mm

            dataset.close()
        else:
            dataset = nc.Dataset(nc_path, 'a')
            lats = dataset.variables.get('lat', dataset.variables.get('latitude'))[:]
            lons = dataset.variables.get('lon', dataset.variables.get('longitude'))[:]

            lat_idx = int(np.argmin(np.abs(lats - args.downstream_lat)))
            lon_idx = int(np.argmin(np.abs(lons - args.downstream_lon)))

            runoff_var = None
            for vname in ['runoff', 'Runoff', 'RUNOFF', 'ro']:
                if vname in dataset.variables:
                    runoff_var = vname
                    break
            if runoff_var is None:
                runoff_var = list(dataset.variables.keys())[-1]

            runoff = dataset.variables[runoff_var]

            cell_area = args.cell_area_m2
            if cell_area is None:
                dlat = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.25
                cell_area = (dlat * 111000) ** 2 * np.cos(np.radians(args.downstream_lat))

            start_day = args.breach_start_day
            for d in range(len(daily_q)):
                day_idx = start_day + d
                if day_idx < runoff.shape[0]:
                    additional_mm = m3s_to_mm_day(daily_q[d], cell_area)
                    current = float(runoff[day_idx, lat_idx, lon_idx])
                    runoff[day_idx, lat_idx, lon_idx] = current + additional_mm

            dataset.close()

        result["modified_nc_path"] = nc_path
        result["status"] = "success"
        logger.info(f"Breach flow injected into {nc_path} at cell ({lat_idx}, {lon_idx})")

    except Exception as e:
        result["errors"].append(f"NetCDF modification failed: {str(e)}")
        logger.error(f"Error: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(3)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
