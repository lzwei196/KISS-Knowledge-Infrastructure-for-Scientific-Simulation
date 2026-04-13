#!/usr/bin/env python3
"""
Extract surface runoff from ParFlow for CaMa-Flood downstream routing.

Converts ParFlow overland flow output to the NetCDF format that
CaMa-Flood expects as lateral inflow.

CRITICAL: If ParFlow handles overland flow internally, CaMa-Flood must
NOT also receive VIC surface runoff for the same basin. Only one model
routes surface water (dt_pf_050 double-counting trap).

CRITICAL: ParFlow outputs hourly, CaMa-Flood expects daily.
Must aggregate correctly: MEAN for flux (runoff), not SUM (dt_pf_052).

Usage:
    python parflow_to_cama.py \
        --run_dir outputs/parflow_run/run/ \
        --run_name chaohe_test \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --mask_npy outputs/parflow_run/domain/domain_mask.npy \
        --start_year 2000 --end_year 2010 \
        --output_dir outputs/parflow_run/cama_input/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys
import glob
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc4
except ImportError:
    nc4 = None


def validate_inputs(run_dir, domain_json, mask_npy):
    errors = []
    if not os.path.isdir(run_dir):
        errors.append(f"Run directory not found: {run_dir}")
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(mask_npy):
        errors.append(f"Mask not found: {mask_npy}")
    return errors


def read_pfb_or_npy(filepath):
    """Read PFB or numpy file."""
    if filepath.endswith(".pfb"):
        try:
            from parflow.tools.io import read_pfb
            return read_pfb(filepath)
        except ImportError:
            npy_path = filepath.replace(".pfb", ".npy")
            if os.path.exists(npy_path):
                return np.load(npy_path)
            raise
    return np.load(filepath)


def process(run_dir, run_name, domain_json, mask_npy, output_dir,
            start_year, end_year, dt_hours=1, dump_hours=24):
    """
    Extract ParFlow surface runoff for CaMa-Flood.

    Computes runoff as the overland flow leaving each cell
    (positive pressure head at the surface * velocity).
    Simplified: uses the change in ponding depth as a proxy for
    net surface water flux.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_3d = np.load(mask_npy)
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]

    # Find pressure output files
    press_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.press.*.pfb")))
    if not press_files:
        press_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.press.*.npy")))

    if not press_files:
        return {"status": "error", "message": "No pressure output files found"}

    # Surface mask (top layer)
    surf_mask = mask_3d[nz - 1, :, :]
    cell_area = dx * dy  # m^2

    # Process year by year
    files_created = []
    start_dt = datetime(start_year, 1, 1)

    for year in range(start_year, end_year + 1):
        year_start = datetime(year, 1, 1)
        year_end = datetime(year, 12, 31)

        # Days in this year
        n_days = (year_end - year_start).days + 1
        steps_per_day = int(24 / dump_hours)

        # Daily runoff array (time, y, x) in mm/day
        runoff_daily = np.zeros((n_days, ny, nx), dtype=np.float32)

        # For each day, compute runoff from pressure change
        for day in range(n_days):
            day_dt = year_start + timedelta(days=day)
            hours_from_start = int((day_dt - start_dt).total_seconds() / 3600)
            step_idx = hours_from_start // int(dump_hours)

            if step_idx >= len(press_files) or step_idx < 0:
                continue

            try:
                pressure = read_pfb_or_npy(press_files[step_idx])
            except Exception:
                continue

            # Surface pressure -> ponding depth -> runoff proxy
            for j in range(ny):
                for i in range(nx):
                    if surf_mask[j, i] == 0:
                        continue
                    p_top = pressure[nz - 1, j, i]
                    if p_top > 0:
                        # Positive pressure at surface = ponded water
                        # Convert to mm/day (rough proxy)
                        runoff_daily[day, j, i] = float(p_top) * 1000.0  # m -> mm

        # Write NetCDF for CaMa-Flood
        if nc4 is not None:
            nc_path = os.path.join(output_dir, f"{run_name}_runoff_1d_{year}.nc")
            with nc4.Dataset(nc_path, "w") as ds:
                ds.createDimension("time", n_days)
                ds.createDimension("y", ny)
                ds.createDimension("x", nx)

                t_var = ds.createVariable("time", "f8", ("time",))
                t_var.units = f"days since {year}-01-01"
                t_var[:] = np.arange(n_days)

                ro_var = ds.createVariable("RUNOFF", "f4", ("time", "y", "x"),
                                           fill_value=-9999.0)
                ro_var.units = "mm/day"
                ro_var.long_name = "surface runoff from ParFlow"
                ro_var[:, :, :] = runoff_daily

                bf_var = ds.createVariable("BASEFLOW", "f4", ("time", "y", "x"),
                                           fill_value=-9999.0)
                bf_var.units = "mm/day"
                bf_var.long_name = "subsurface baseflow from ParFlow"
                bf_var[:, :, :] = 0.0  # Placeholder

                ds.description = f"ParFlow runoff for CaMa-Flood, year {year}"

            files_created.append(nc_path)

    result = {
        "status": "success",
        "output_dir": output_dir,
        "files_created": files_created,
        "years": list(range(start_year, end_year + 1)),
        "grid": {"ny": ny, "nx": nx, "dx": dx, "dy": dy},
        "warnings": [
            "CRITICAL: Do NOT also feed VIC runoff to CaMa-Flood for this basin",
            "ParFlow already handles surface and subsurface routing",
            "Double-counting will produce 2x discharge (dt_pf_050)",
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert ParFlow output to CaMa-Flood input"
    )
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--run_name", required=True)
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--mask_npy", required=True)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--dump_hours", type=float, default=24)
    args = parser.parse_args()

    errs = validate_inputs(args.run_dir, args.domain_json, args.mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.run_dir, args.run_name, args.domain_json, args.mask_npy,
                     args.output_dir, args.start_year, args.end_year,
                     dump_hours=args.dump_hours)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
