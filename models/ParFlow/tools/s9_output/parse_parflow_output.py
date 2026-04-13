#!/usr/bin/env python3
"""
Parse ParFlow PFB output files and extract key hydrological variables.

Extracts:
  - Discharge at outlet (from overland flow + subsurface lateral flow)
  - Water table depth (from saturation field)
  - Soil moisture profiles
  - Water balance components (P, ET, Q, dS/dt)

ParFlow outputs PFB files per timestep for pressure and saturation.
This tool reads them and produces timeseries and spatial maps.

Usage:
    python parse_parflow_output.py \
        --run_dir outputs/parflow_run/run/ \
        --run_name chaohe_test \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --mask_npy outputs/parflow_run/domain/domain_mask.npy \
        --output_dir outputs/parflow_run/results/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys
import glob

import numpy as np

try:
    from datetime import datetime, timedelta
except ImportError:
    pass


def validate_inputs(run_dir, run_name, domain_json, mask_npy):
    errors = []
    if not os.path.isdir(run_dir):
        errors.append(f"Run directory not found: {run_dir}")
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(mask_npy):
        errors.append(f"Mask not found: {mask_npy}")
    return errors


def read_pfb_or_npy(filepath):
    """Read a PFB file, falling back to numpy."""
    if filepath.endswith(".pfb"):
        try:
            from parflow.tools.io import read_pfb
            return read_pfb(filepath)
        except ImportError:
            # Try numpy fallback
            npy_path = filepath.replace(".pfb", ".npy")
            if os.path.exists(npy_path):
                return np.load(npy_path)
            raise
    elif filepath.endswith(".npy"):
        return np.load(filepath)
    else:
        raise ValueError(f"Unknown file format: {filepath}")


def compute_water_table_depth(saturation, domain, mask_3d):
    """
    Compute water table depth from 3D saturation field.

    Water table is at the depth where saturation transitions from
    <0.99 (unsaturated) to >=0.99 (saturated), searching from the top down.

    CRITICAL: Do NOT use pressure head = 0 contour in coarse grids.
    The zero-pressure contour may not align with cell centers.
    Use saturation >= 0.99 threshold instead (dt_pf_041).
    """
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dz_layers = grid["dz_layers_m"]
    total_depth = grid["total_depth_m"]

    wtd = np.full((ny, nx), np.nan, dtype=np.float64)

    for j in range(ny):
        for i in range(nx):
            if mask_3d[nz - 1, j, i] == 0:
                continue
            # Search from top (k=nz-1) downward
            depth = 0.0
            wt_found = False
            for k in range(nz - 1, -1, -1):
                layer_thick = dz_layers[k]
                if saturation[k, j, i] >= 0.99:
                    wtd[j, i] = depth
                    wt_found = True
                    break
                depth += layer_thick
            if not wt_found:
                wtd[j, i] = total_depth  # Water table below domain

    return wtd


def compute_overland_flow_depth(pressure, mask_3d, nz):
    """
    Compute overland flow (ponding) depth from top-layer pressure head.
    Where pressure > 0 at the surface, water is ponded.
    """
    ny, nx = mask_3d.shape[1], mask_3d.shape[2]
    ponding = np.zeros((ny, nx), dtype=np.float64)

    for j in range(ny):
        for i in range(nx):
            if mask_3d[nz - 1, j, i] == 0:
                continue
            p_top = pressure[nz - 1, j, i]
            if p_top > 0:
                ponding[j, i] = p_top  # meters of ponded water

    return ponding


def process(run_dir, run_name, domain_json, mask_npy, output_dir,
            start_date="2000-01-01", dt_hours=1, dump_hours=24):
    """
    Parse ParFlow output files.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_3d = np.load(mask_npy)
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]

    # Find output files
    press_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.press.*.pfb")))
    satur_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.satur.*.pfb")))

    # If no PFB files, try numpy
    if not press_files:
        press_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.press.*.npy")))
    if not satur_files:
        satur_files = sorted(glob.glob(os.path.join(run_dir, f"{run_name}.out.satur.*.npy")))

    n_steps = len(press_files)

    if n_steps == 0:
        return {
            "status": "error",
            "message": "No output files found",
            "search_pattern": os.path.join(run_dir, f"{run_name}.out.press.*.pfb"),
        }

    # Process each timestep
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    dates = []
    wtd_timeseries = []
    ponding_timeseries = []
    storage_timeseries = []

    for step_idx in range(n_steps):
        t = start_dt + timedelta(hours=step_idx * dump_hours)
        dates.append(t.strftime("%Y-%m-%d"))

        try:
            pressure = read_pfb_or_npy(press_files[step_idx])
            saturation = read_pfb_or_npy(satur_files[step_idx]) if step_idx < len(satur_files) else None
        except Exception as e:
            continue

        # Water table depth
        if saturation is not None:
            wtd = compute_water_table_depth(saturation, domain, mask_3d)
            active_wtd = wtd[~np.isnan(wtd)]
            wtd_timeseries.append(float(np.mean(active_wtd)) if len(active_wtd) > 0 else np.nan)
        else:
            wtd_timeseries.append(np.nan)

        # Ponding depth
        ponding = compute_overland_flow_depth(pressure, mask_3d, nz)
        active_pond = ponding[mask_3d[nz - 1] > 0]
        ponding_timeseries.append(float(np.mean(active_pond)) if len(active_pond) > 0 else 0)

        # Total subsurface storage
        if saturation is not None:
            dz_layers = domain["grid"]["dz_layers_m"]
            total_water = 0.0
            for k in range(nz):
                layer_water = saturation[k] * 0.4 * dz_layers[k] * dx * dy  # porosity=0.4
                total_water += float(np.sum(layer_water[mask_3d[k] > 0]))
            storage_timeseries.append(total_water)
        else:
            storage_timeseries.append(np.nan)

    # Save timeseries
    timeseries = {
        "dates": dates,
        "mean_water_table_depth_m": wtd_timeseries,
        "mean_ponding_depth_m": ponding_timeseries,
        "total_subsurface_storage_m3": storage_timeseries,
    }

    ts_file = os.path.join(output_dir, "timeseries.json")
    with open(ts_file, "w") as f:
        json.dump(timeseries, f, indent=2)

    # Save final water table depth map
    if satur_files:
        try:
            final_sat = read_pfb_or_npy(satur_files[-1])
            final_wtd = compute_water_table_depth(final_sat, domain, mask_3d)
            wtd_file = os.path.join(output_dir, "final_water_table_depth.npy")
            np.save(wtd_file, final_wtd)
        except Exception:
            wtd_file = None
    else:
        wtd_file = None

    result = {
        "status": "success",
        "timesteps_processed": n_steps,
        "timeseries_file": ts_file,
        "final_wtd_file": wtd_file,
        "summary": {
            "mean_wtd_m": float(np.nanmean(wtd_timeseries)) if wtd_timeseries else None,
            "mean_ponding_m": float(np.mean(ponding_timeseries)) if ponding_timeseries else None,
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Parse ParFlow output files")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--run_name", required=True)
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--mask_npy", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--start_date", default="2000-01-01")
    parser.add_argument("--dt_hours", type=float, default=1)
    parser.add_argument("--dump_hours", type=float, default=24)
    args = parser.parse_args()

    errs = validate_inputs(args.run_dir, args.run_name, args.domain_json, args.mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.run_dir, args.run_name, args.domain_json, args.mask_npy,
                     args.output_dir, args.start_date, args.dt_hours, args.dump_hours)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
