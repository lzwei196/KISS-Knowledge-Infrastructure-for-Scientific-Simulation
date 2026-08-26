#!/usr/bin/env python3
"""
s6_post/grid_runoff_nc.py — VIC per-cell ASCII fluxes -> gridded NetCDF.

This is SKILL.md "步骤7 / step 7".  Until 2026-07-20 that step pointed at
``scripts/vic_post/process_${BASIN_NAME}.py``, a per-basin copy-and-edit script
that **did not exist anywhere in the KI** (see skill_md_issues in the
VIC_real_case_20260720 run).  Every agent needing a gridded runoff field had to
hand-roll it, and the hand-rolled versions kept reintroducing the same two bugs:

  1. **Hard-coded column indices.**  The KI's own routing recipe uses
     ``df.iloc[:, [0,1,2,3,18,16,17]]``, which is only correct for the exact
     21-OUTVAR list in the shipped global-param template.  A single reordered
     or added OUTVAR silently shifts the runoff column and you grid the wrong
     variable with no error.  This tool resolves columns **by name** from the
     flux-file header instead.
  2. **Hard-coded NX/NY/WEST/EAST.**  The old per-basin scripts asked the user
     to type the grid extent by hand.  Here the grid is inferred from the cell
     coordinates actually present in the result directory, so it cannot
     disagree with the run.

Output variable ``Runoff`` = ``OUT_RUNOFF + OUT_BASEFLOW`` (mm/day), which is
the total runoff *generated* in the cell.  That is the quantity comparable to
gridded runoff reconstructions (GRUN, ERA5-Land ``runoff``) and the quantity
CaMa-Flood / mizuRoute expect as input.  It is **not** streamflow: it has no
travel time.  Routing to a gauge is s5_routing (see SKILL.md "VIC DOES NOT
ROUTE").

Configuration is by environment variable, matching every other stage:

    VIC_BASIN_NAME     basin tag (drives outputs/<name>/...)
    VIC_OUT_ROOT       default KISSPATH_OUTPUTS
    VIC_RESULT_DIR     default <out_root>/<basin>/vic_result
    VIC_POST_OUT_DIR   default <out_root>/<basin>/cama_input
    VIC_POST_NC        default <post_out_dir>/<basin>_runoff_1d.nc
    VIC_POST_FORCE     set to 1 to rebuild an existing NetCDF

Usage:
    python s6_post/grid_runoff_nc.py
    # or:  from s6_post.grid_runoff_nc import grid_runoff; grid_runoff()
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

# Flux columns this tool needs, keyed by the VIC OUTVAR name in the header.
_RUNOFF_VARS = ("OUT_RUNOFF", "OUT_BASEFLOW")
# Carried through so the post-run water-balance check has real P, ET and a
# storage term (soil moisture layers + SWE) instead of assuming dS = 0.
_EXTRA_VARS = ("OUT_PREC", "OUT_EVAP", "OUT_SWE",
               "OUT_SOIL_MOIST_0", "OUT_SOIL_MOIST_1", "OUT_SOIL_MOIST_2")

# "<prefix>_fluxes_<LAT>_<LON>[.txt]" -> (lat, lon)
_COORD_RE = re.compile(r"_(-?\d+\.\d+)_(-?\d+\.\d+)(?:\.txt)?$")


def _env_paths():
    basin = os.environ.get("VIC_BASIN_NAME")
    if not basin:
        raise SystemExit("VIC_BASIN_NAME is not set (see SKILL.md env-var table)")
    out_root = Path(os.environ.get(
        "VIC_OUT_ROOT", "KISSPATH_OUTPUTS"))
    result_dir = Path(os.environ.get(
        "VIC_RESULT_DIR", out_root / basin / "vic_result"))
    post_dir = Path(os.environ.get(
        "VIC_POST_OUT_DIR", out_root / basin / "cama_input"))
    nc_path = Path(os.environ.get(
        "VIC_POST_NC", post_dir / f"{basin}_runoff_1d.nc"))
    return basin, result_dir, post_dir, nc_path


def _parse_coords(path: Path):
    """Return (lat, lon) parsed from a VIC flux filename, or None."""
    m = _COORD_RE.search(path.name)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _read_header(path: Path):
    """Return the OUTVAR column-name list from a VIC classic ASCII flux file.

    VIC writes two '#' comment lines then a tab-separated header beginning
    with YEAR.  Column names carry leading spaces, hence the strip().
    """
    with path.open() as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            return [c.strip() for c in line.rstrip("\n").split("\t")]
    raise ValueError(f"{path}: no header line found")


def _infer_axis(values, name):
    """Build a regular ascending axis from the distinct coordinates present.

    Resolution is the smallest positive gap between neighbouring distinct
    coordinates.  Using the *minimum* gap (not the mean) is deliberate: an
    irregular basin has interior gaps where no cell exists, and a mean would
    invent a coarser grid that mis-locates every cell.
    """
    uniq = np.unique(np.round(np.asarray(values, dtype=np.float64), 6))
    if uniq.size == 1:
        return uniq, 0.25
    gaps = np.diff(uniq)
    gaps = gaps[gaps > 1e-9]
    res = float(np.min(gaps))
    n = int(round((uniq[-1] - uniq[0]) / res)) + 1
    axis = uniq[0] + res * np.arange(n)
    # Every observed coordinate must land on the reconstructed axis.
    for v in uniq:
        if np.min(np.abs(axis - v)) > res * 1e-3:
            raise ValueError(
                f"{name} coordinate {v} does not lie on the inferred "
                f"{res} deg grid — flux filenames are not on a regular grid")
    return axis, res


def grid_runoff(verbose: bool = True) -> Path:
    """Convert every per-cell flux file into one gridded NetCDF. Returns path."""
    basin, result_dir, post_dir, nc_path = _env_paths()

    if nc_path.exists() and os.environ.get("VIC_POST_FORCE", "") not in ("1", "true", "TRUE"):
        if verbose:
            print(f"[s6_post] {nc_path} exists — skipping (VIC_POST_FORCE=1 to rebuild)")
        return nc_path

    if not result_dir.is_dir():
        raise SystemExit(f"[s6_post] result dir not found: {result_dir}")

    files = sorted(p for p in result_dir.iterdir()
                   if p.is_file() and _parse_coords(p) is not None)
    if not files:
        raise SystemExit(f"[s6_post] no VIC flux files matched in {result_dir}")
    if verbose:
        print(f"[s6_post] {len(files)} flux files in {result_dir}")

    header = _read_header(files[0])
    missing = [v for v in _RUNOFF_VARS if v not in header]
    if missing:
        raise SystemExit(
            f"[s6_post] flux header lacks {missing}. Add them to the OUTVAR "
            f"list in the global parameter file and re-run VIC. Header was:\n"
            f"  {header}")
    extras = [v for v in _EXTRA_VARS if v in header]
    wanted = list(_RUNOFF_VARS) + extras
    usecols = ["YEAR", "MONTH", "DAY"] + wanted

    lats = [_parse_coords(p)[0] for p in files]
    lons = [_parse_coords(p)[1] for p in files]
    lat_axis, lat_res = _infer_axis(lats, "lat")
    lon_axis, lon_res = _infer_axis(lons, "lon")
    if verbose:
        print(f"[s6_post] grid {lat_axis.size} lat x {lon_axis.size} lon "
              f"@ {lat_res}x{lon_res} deg "
              f"({lat_axis[0]}..{lat_axis[-1]}, {lon_axis[0]}..{lon_axis[-1]})")

    time_index = None
    fields = None

    for k, path in enumerate(files):
        hdr = _read_header(path)
        df = pd.read_csv(path, sep="\t", comment="#", header=0,
                         names=hdr, skip_blank_lines=True)
        df.columns = [c.strip() for c in df.columns]
        df = df[usecols].apply(pd.to_numeric, errors="coerce")

        t = pd.to_datetime(dict(year=df["YEAR"], month=df["MONTH"], day=df["DAY"]))

        if time_index is None:
            time_index = pd.DatetimeIndex(t)
            fields = {v: np.full((time_index.size, lat_axis.size, lon_axis.size),
                                 np.nan, dtype=np.float32)
                      for v in ("Runoff",) + tuple(extras)}
        elif not time_index.equals(pd.DatetimeIndex(t)):
            raise SystemExit(
                f"[s6_post] {path.name} has a different time axis than "
                f"{files[0].name} ({t.iloc[0]}..{t.iloc[-1]} vs "
                f"{time_index[0]}..{time_index[-1]}). VIC did not finish this "
                f"cell — re-run VIC before gridding.")

        la, lo = _parse_coords(path)
        i = int(np.argmin(np.abs(lat_axis - la)))
        j = int(np.argmin(np.abs(lon_axis - lo)))

        fields["Runoff"][:, i, j] = (df["OUT_RUNOFF"].to_numpy(np.float32)
                                     + df["OUT_BASEFLOW"].to_numpy(np.float32))
        for v in extras:
            fields[v][:, i, j] = df[v].to_numpy(np.float32)

        if verbose and (k + 1) % 200 == 0:
            print(f"[s6_post]   {k + 1}/{len(files)} cells read")

    coords = {"time": time_index, "lat": lat_axis, "lon": lon_axis}
    data_vars = {
        "Runoff": (("time", "lat", "lon"), fields["Runoff"], {
            "units": "mm/day",
            "long_name": "total runoff generated in cell (OUT_RUNOFF + OUT_BASEFLOW)",
            "note": "runoff generation, NOT routed streamflow",
        }),
    }
    _meta = {
        "OUT_PREC": ("Prec", "mm/day", "precipitation"),
        "OUT_EVAP": ("Evap", "mm/day", "evapotranspiration"),
        "OUT_SWE": ("SWE", "mm", "snow water equivalent"),
        "OUT_SOIL_MOIST_0": ("SoilMoist0", "mm", "soil moisture layer 1"),
        "OUT_SOIL_MOIST_1": ("SoilMoist1", "mm", "soil moisture layer 2"),
        "OUT_SOIL_MOIST_2": ("SoilMoist2", "mm", "soil moisture layer 3"),
    }
    for v in extras:
        name, unit, long_name = _meta[v]
        data_vars[name] = (("time", "lat", "lon"), fields[v],
                           {"units": unit, "long_name": long_name})

    ds = xr.Dataset(data_vars, coords=coords, attrs={
        "title": f"VIC gridded daily runoff — {basin}",
        "source": "VIC 5.1.0 classic driver, water-balance mode",
        "history": "created by s6_post/grid_runoff_nc.py (KI step 7)",
        "grid_resolution_deg": f"{lat_res} x {lon_res}",
        "n_active_cells": len(files),
    })
    ds["lat"].attrs.update(units="degrees_north", standard_name="latitude")
    ds["lon"].attrs.update(units="degrees_east", standard_name="longitude")

    post_dir.mkdir(parents=True, exist_ok=True)
    enc = {v: {"zlib": True, "complevel": 4, "_FillValue": np.float32(np.nan)}
           for v in ds.data_vars}
    ds.to_netcdf(nc_path, encoding=enc)

    active = int(np.isfinite(fields["Runoff"][0]).sum())
    mean_mm_yr = float(np.nanmean(ds["Runoff"].values)) * 365.25
    if verbose:
        print(f"[s6_post] wrote {nc_path}")
        print(f"[s6_post]   time {time_index[0].date()}..{time_index[-1].date()} "
              f"({time_index.size} days), active cells {active}/{len(files)}")
        print(f"[s6_post]   basin-mean total runoff {mean_mm_yr:.1f} mm/yr")
    if active != len(files):
        print(f"[s6_post] WARNING: {len(files) - active} cells are all-NaN "
              f"— check the VIC log for failed cells", file=sys.stderr)
    return nc_path


if __name__ == "__main__":
    grid_runoff()
    # xarray probes every registered backend at import, including pygmt, whose
    # libgmt is not installed here. That plugin segfaults during interpreter
    # TEARDOWN — i.e. AFTER the NetCDF is safely on disk — so the process exits
    # 139 on a fully successful run. Callers that trust the exit code then throw
    # away good output (this has burned the KI before: the VIC 唐乃亥 run and the
    # NeuralHydrology 'exit 245' incident were both post-success teardown
    # crashes). os._exit skips teardown and reports the truth.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
