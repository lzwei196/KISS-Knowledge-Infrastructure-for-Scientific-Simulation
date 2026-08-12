#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      generate_sfincs_inp
Stage:        s6_config
Description:  Generate sfincs.inp main configuration file with all simulation parameters.
              Auto-computes stable timestep from CFL condition.

CRITICAL:
  - SFINCS reads sfincs.inp from CWD only. All file references must be relative
    to the working directory where the binary is executed.
  - dt must satisfy CFL: dt <= dx / sqrt(g * h_max). Too large dt -> NaN crash.
  - outputformat must be "net" (NetCDF) for post-processing tools to work.

Inputs:
  --grid_info:        Path to grid_info.json
  --topobathy_dir:    Directory containing sfincs.dep, sfincs.msk, sfincs.ind
  --start_date:       Simulation start (YYYYMMDD HHMMSS or YYYY-MM-DD)
  --end_date:         Simulation end
  --manning:          Uniform Manning's n (default: 0.04)
  --manning_file:     Path to sfincs.man (overrides --manning)
  --precip_file:      Path to sfincs.precip NetCDF
  --bnd_file:         Path to sfincs.bnd
  --bzs_file:         Path to sfincs.bzs
  --src_file:         Path to sfincs.src
  --dis_file:         Path to sfincs.dis
  --obs_file:         Path to sfincs.obs
  --dtout:            Output interval in seconds (default: 3600)
  --zsini:            Initial water level (default: 0.0)
  --qinf:             Infiltration rate mm/hr (default: 0.0)
  --output_dir:       Directory to write sfincs.inp

Outputs:
  - sfincs.inp: Main configuration file

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
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_datetime(s):
    """Parse date string in various formats."""
    s = s.strip()
    for fmt in ["%Y%m%d %H%M%S", "%Y%m%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s}")


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    try:
        parse_datetime(args.start_date)
        parse_datetime(args.end_date)
    except ValueError as e:
        errors.append(str(e))
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    mmax = grid["mmax"]
    nmax = grid["nmax"]
    dx = grid["dx"]
    dy = grid["dy"]
    x0 = grid["x0"]
    y0 = grid["y0"]
    epsg = grid["epsg"]

    tstart = parse_datetime(args.start_date)
    tstop = parse_datetime(args.end_date)

    # --- Compute stable timestep ---
    # dt_009: the CFL limit is set by the DEEPEST standing water in the domain, not by a
    # nominal 10 m flood. A coastal/fjord domain whose bed reaches -135 m carries
    # h = zsini - bed = 135 m of water from t=0, where dx/sqrt(g*h) is 2.7 s, not 10.1 s —
    # so a hard-coded h_max=10 writes a dt ~4x above the true limit. Read the real
    # bathymetry from s2's topobathy_summary.json whenever it is available.
    g = 9.81
    h_max = 10.0  # fallback: assumed max flood depth
    h_max_source = "default (assumed 10 m flood depth)"
    if getattr(args, "h_max", None) is not None:
        h_max = float(args.h_max)
        h_max_source = "--h_max"
    elif args.topobathy_dir:
        summary_file = Path(args.topobathy_dir) / "topobathy_summary.json"
        if summary_file.exists():
            try:
                with open(summary_file) as f:
                    tb = json.load(f)
                elev_min = tb.get("elevation_min")
                if elev_min is not None:
                    h_std = float(args.zsini) - float(elev_min)   # standing water depth
                    h_max = max(10.0, h_std)
                    h_max_source = (f"topobathy_summary.json (elevation_min={float(elev_min):.1f} m, "
                                    f"zsini={float(args.zsini):.2f} m)")
            except Exception as e:
                logger.warning(f"Could not read {summary_file} for CFL h_max: {e}")
    logger.info(f"CFL h_max = {h_max:.1f} m from {h_max_source}")
    dt_cfl = dx / np.sqrt(g * h_max)
    dt = max(0.5, min(dt_cfl * 0.75, 30.0))  # Safety factor 0.75

    # Round to convenient value
    if dt >= 10:
        dt = int(dt / 5) * 5  # Round to nearest 5
    elif dt >= 2:
        dt = int(dt)
    else:
        dt = round(dt, 1)

    dt = max(0.1, dt)
    logger.info(f"CFL dt_max = {dt_cfl:.2f}s, using dt = {dt}s")

    # --- Format dates for sfincs.inp ---
    tref_str = tstart.strftime("%Y%m%d %H%M%S")
    tstart_str = tstart.strftime("%Y%m%d %H%M%S")
    tstop_str = tstop.strftime("%Y%m%d %H%M%S")

    # --- Build sfincs.inp ---
    lines = []
    lines.append("! ============================================")
    lines.append("! SFINCS configuration file")
    lines.append(f"! Generated by HydroCraft on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("! ============================================")
    lines.append("")

    # Grid
    lines.append("! --- Grid definition ---")
    lines.append(f"mmax           = {mmax}")
    lines.append(f"nmax           = {nmax}")
    lines.append(f"dx             = {dx:.1f}")
    lines.append(f"dy             = {dy:.1f}")
    lines.append(f"x0             = {x0:.1f}")
    lines.append(f"y0             = {y0:.1f}")
    lines.append("rotation       = 0.0")
    lines.append(f"epsg           = {epsg}")
    lines.append("")

    # Time
    lines.append("! --- Time ---")
    lines.append(f"tref           = {tref_str}")
    lines.append(f"tstart         = {tstart_str}")
    lines.append(f"tstop          = {tstop_str}")
    lines.append(f"dt             = {dt}")
    lines.append(f"dtout          = {args.dtout:.1f}")
    lines.append(f"dthisout       = {min(args.dtout, args.dthisout):.1f}")
    # dtmaxout controls the hmax/zsmax ("maximum-over-window") fields that s8 needs.
    # Setting it to the FULL simulation length gives exactly one hmax field covering the
    # whole event, which is what extract_sfincs_results.py reads (dt_v007).
    if args.dtmaxout is not None:
        dtmaxout = args.dtmaxout if args.dtmaxout > 0 else (tstop - tstart).total_seconds()
        lines.append(f"dtmaxout       = {dtmaxout:.1f}")
    lines.append("")

    # Physics
    lines.append("! --- Physics ---")
    if args.manning_file and Path(args.manning_file).exists():
        lines.append(f"manningfile    = sfincs.man")
    else:
        lines.append(f"manning        = {args.manning:.4f}")
    lines.append(f"zsini          = {args.zsini:.2f}")
    lines.append(f"qinf           = {args.qinf:.2f}")
    # advection: 0 = friction-dominated (pluvial/overland, SFINCS default here);
    # 1 = include the momentum advection terms — needed for FLUVIAL reaches where the
    # velocity head is not negligible (Fraser at 2-3 m/s), otherwise a constriction
    # builds an unphysically deep backwater.
    lines.append(f"advection      = {int(args.advection)}")
    lines.append(f"alpha          = {args.alpha:.2f}")
    lines.append("")

    # Subgrid / topobathy
    lines.append("! --- Topography and mask ---")
    lines.append("depfile        = sfincs.dep")
    lines.append("mskfile        = sfincs.msk")
    lines.append("indexfile      = sfincs.ind")
    lines.append("")

    # Boundaries
    has_bc = False
    lines.append("! --- Boundary conditions ---")
    # Helper: check if file exists relative to cwd OR output_dir
    def _file_exists(fname):
        if not fname: return False
        return Path(fname).exists() or (output_dir / Path(fname).name).exists()

    if _file_exists(args.bnd_file):
        lines.append("bndfile        = sfincs.bnd")
        has_bc = True
    if _file_exists(args.bzs_file):
        lines.append("bzsfile        = sfincs.bzs")
    if _file_exists(args.src_file):
        lines.append("srcfile        = sfincs.src")
        has_bc = True
    if _file_exists(args.dis_file):
        lines.append("disfile        = sfincs.dis")
    lines.append("")

    # Precipitation
    # CRITICAL: Use 'precipfile' (ASCII format) NOT 'netprecipfile' (NetCDF).
    # NetCDF precip via netprecipfile silently fails in some SFINCS versions (dt_v004).
    # ASCII format (time_seconds precip_mmhr) is reliable across all versions.
    if _file_exists(args.precip_file):
        lines.append("! --- Precipitation ---")
        lines.append("precipfile     = sfincs.precip")
        lines.append("")

    # Observation points
    if args.obs_file and Path(args.obs_file).exists():
        lines.append("! --- Observation points ---")
        lines.append("obsfile        = sfincs.obs")
        lines.append("")

    # Output
    lines.append("! --- Output ---")
    lines.append("outputformat   = net")
    lines.append("")

    # Write file
    inp_path = output_dir / "sfincs.inp"
    with open(inp_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"Wrote: {inp_path}")

    # Warn if no forcing at all
    if not has_bc and not (args.precip_file and Path(args.precip_file).exists()):
        logger.warning("No boundary conditions or precipitation specified. "
                       "SFINCS will run with no water input — output will be all zeros!")

    # --- Summary ---
    summary = {
        "status": "success",
        "inp_file": str(inp_path),
        "grid": f"{mmax}x{nmax}",
        "dx": dx,
        "dt": dt,
        "dt_cfl_max": round(dt_cfl, 2),
        "tstart": tstart_str,
        "tstop": tstop_str,
        "dtout": args.dtout,
        "manning": args.manning if not args.manning_file else "from file",
        "has_precipitation": bool(args.precip_file and Path(args.precip_file).exists()),
        "has_boundary_wl": bool(args.bnd_file and Path(args.bnd_file).exists()),
        "has_discharge_src": bool(args.src_file and Path(args.src_file).exists()),
    }

    print(json.dumps(summary, indent=2))
    return str(inp_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"sfincs.inp not created: {output_path}")
        sys.exit(3)
    # Check file has content
    content = Path(output_path).read_text()
    if "mmax" not in content or "nmax" not in content:
        logger.error("sfincs.inp is missing grid parameters")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SFINCS configuration file")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--topobathy_dir", default=None, help="Dir with sfincs.dep/msk/ind")
    parser.add_argument("--start_date", required=True, help="Start date")
    parser.add_argument("--end_date", required=True, help="End date")
    parser.add_argument("--manning", type=float, default=0.04, help="Uniform Manning's n")
    parser.add_argument("--manning_file", default=None, help="Path to sfincs.man")
    parser.add_argument("--precip_file", default=None, help="Path to sfincs.precip")
    parser.add_argument("--bnd_file", default=None, help="Path to sfincs.bnd")
    parser.add_argument("--bzs_file", default=None, help="Path to sfincs.bzs")
    parser.add_argument("--src_file", default=None, help="Path to sfincs.src")
    parser.add_argument("--dis_file", default=None, help="Path to sfincs.dis")
    parser.add_argument("--obs_file", default=None, help="Path to sfincs.obs")
    parser.add_argument("--dtout", type=float, default=3600.0, help="Map output interval (seconds)")
    parser.add_argument("--dthisout", type=float, default=600.0,
                        help="Observation-point (sfincs_his.nc) output interval in seconds. "
                             "The written value is min(dtout, dthisout).")
    parser.add_argument("--dtmaxout", type=float, default=None,
                        help="Interval (s) for the hmax/zsmax maximum fields. Pass 0 for "
                             "'one field over the whole simulation' (what s8 expects). "
                             "Omit to leave dtmaxout out of sfincs.inp entirely.")
    parser.add_argument("--zsini", type=float, default=0.0, help="Initial water level (m)")
    parser.add_argument("--qinf", type=float, default=0.0, help="Infiltration rate (mm/hr)")
    parser.add_argument("--advection", type=int, default=0, choices=[0, 1],
                        help="0 = friction-dominated (pluvial, default); 1 = include "
                             "momentum advection (fluvial reaches with fast flow)")
    parser.add_argument("--alpha", type=float, default=0.75,
                        help="SFINCS CFL safety factor for its adaptive timestep")
    parser.add_argument("--h_max", type=float, default=None,
                        help="Max water depth (m) used for the CFL timestep. Default: "
                             "derived from --topobathy_dir/topobathy_summary.json "
                             "(zsini - elevation_min), else 10 m.")
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
