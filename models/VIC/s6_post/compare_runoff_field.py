#!/usr/bin/env python3
"""
s6_post/compare_runoff_field.py — VIC gridded runoff vs a gridded runoff product.

Implements the ``spatial_field_comparison`` contract that ``dag.yaml`` declares
for ``OUT_RUNOFF`` against a ``spatial_time_series`` observation::

    obs_shape:         spatial_time_series
    comparison_mode:   spatial_field_comparison
    metric_families:   [spatial_pattern_match, magnitude_accuracy]
    determining_metric: csi

Before 2026-07-20 the VIC KI had no way to honour that contract: it could only
route to a gauge and score NSE on a hydrograph (``point_time_series``).  Any
attempt to compare against GRUN / ERA5-Land runoff therefore either fabricated
a scale-mismatched point-vs-region number or was abandoned.  This tool closes
that gap.

**The scale problem it solves.**  VIC runs on a 0.25 deg basin grid; GRUN is
0.5 deg global.  Comparing them cell-to-cell by nearest-neighbour would compare
a quarter-cell to a whole cell.  Instead each VIC cell is assigned to the GRUN
cell whose *edges* contain it and averaged with cos(lat) area weights — a
conservative (area-preserving) aggregation, which is the correct operator for a
flux density like runoff.  GRUN cells that the basin only partially fills are
**dropped** (``--min-coverage``, default 0.75), because there the VIC average
describes a different area than the GRUN value does.  Reporting those cells is
the single easiest way to manufacture a fake bias.

**Temporal support.**  GRUN is monthly-mean mm/day.  VIC daily mm/day is
averaged to monthly means before comparison, so both sides are the same
quantity in the same units.  No unit conversion is applied to either side.

Usage:
    python s6_post/compare_runoff_field.py \
        --vic-nc  outputs/<basin>/cama_input/<basin>_runoff_1d.nc \
        --obs-nc  /mnt/datasets/obs/grun-runoff/GRUN_v1_GSWP3_WGS84_05_1902_2014.nc \
        --obs-var Runoff --start 1981-01-01 --end 1990-12-31 \
        --json-out compare.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ki_tools_common.metrics import spatial_metrics


def _cell_edges(centers: np.ndarray) -> tuple[np.ndarray, float]:
    """Return (edges, resolution) for a regular ascending centre axis."""
    c = np.asarray(centers, dtype=np.float64)
    res = float(np.min(np.diff(c))) if c.size > 1 else 0.5
    return np.concatenate([c - res / 2.0, [c[-1] + res / 2.0]]), res


def aggregate_to_obs_grid(
    vic: xr.DataArray,
    obs_lat: np.ndarray,
    obs_lon: np.ndarray,
    min_coverage: float = 0.75,
):
    """Conservatively aggregate a fine VIC field onto the coarse obs grid.

    Returns (aggregated DataArray on (time, lat, lon) of the obs grid,
    coverage array (lat, lon) in 0..1).

    Coverage is the cos(lat)-weighted fraction of each obs cell's area that is
    covered by *valid* (non-NaN) VIC cells.
    """
    obs_lat = np.asarray(obs_lat, dtype=np.float64)
    obs_lon = np.asarray(obs_lon, dtype=np.float64)
    lat_edges, _ = _cell_edges(obs_lat)
    lon_edges, _ = _cell_edges(obs_lon)

    vlat = vic["lat"].values.astype(np.float64)
    vlon = vic["lon"].values.astype(np.float64)

    # Which obs cell does each fine cell fall into? (-1 = outside obs grid)
    i_of = np.searchsorted(lat_edges, vlat, side="right") - 1
    j_of = np.searchsorted(lon_edges, vlon, side="right") - 1
    i_of[(vlat < lat_edges[0]) | (vlat >= lat_edges[-1])] = -1
    j_of[(vlon < lon_edges[0]) | (vlon >= lon_edges[-1])] = -1

    data = vic.transpose("time", "lat", "lon").values.astype(np.float64)
    nt = data.shape[0]
    nlat, nlon = obs_lat.size, obs_lon.size

    # cos(lat) area weight of each fine cell, broadcast over lon.
    w_lat = np.cos(np.deg2rad(vlat))
    w = np.repeat(w_lat[:, None], vlon.size, axis=1)

    valid = np.isfinite(data)                       # (t, lat, lon)
    wsum = np.zeros((nt, nlat, nlon))               # sum of weights used
    vsum = np.zeros((nt, nlat, nlon))               # sum of weight*value
    wtot = np.zeros((nlat, nlon))                   # total possible weight

    for a in range(vlat.size):
        i = i_of[a]
        if i < 0:
            continue
        for b in range(vlon.size):
            j = j_of[b]
            if j < 0:
                continue
            wab = w[a, b]
            wtot[i, j] += wab
            col_valid = valid[:, a, b]
            if not col_valid.any():
                continue
            vals = np.where(col_valid, data[:, a, b], 0.0)
            vsum[:, i, j] += wab * vals
            wsum[:, i, j] += wab * col_valid

    with np.errstate(invalid="ignore", divide="ignore"):
        agg = np.where(wsum > 0, vsum / wsum, np.nan)

    # Coverage from the time-mean of the used weight relative to total weight.
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = np.where(wtot > 0, wsum.mean(axis=0) / wtot, 0.0)

    agg = np.where(cov[None, :, :] >= min_coverage, agg, np.nan)

    out = xr.DataArray(
        agg, dims=("time", "lat", "lon"),
        coords={"time": vic["time"].values, "lat": obs_lat, "lon": obs_lon},
        attrs={"units": "mm/day",
               "note": f"conservatively aggregated from {vlat.size}x{vlon.size} "
                       f"VIC grid; obs cells with coverage < {min_coverage} masked"},
    )
    return out, cov


def compare(vic_nc, obs_nc, obs_var="Runoff", vic_var="Runoff",
            start=None, end=None, min_coverage=0.75, json_out=None,
            obs_lat_name=None, obs_lon_name=None):
    vds = xr.open_dataset(vic_nc)
    ods = xr.open_dataset(obs_nc)

    # GRUN ships its axes as X / Y; ERA5-Land uses longitude / latitude.
    lat_name = obs_lat_name or next(
        (n for n in ("Y", "lat", "latitude") if n in ods.coords), None)
    lon_name = obs_lon_name or next(
        (n for n in ("X", "lon", "longitude") if n in ods.coords), None)
    if lat_name is None or lon_name is None:
        raise SystemExit(f"cannot identify lat/lon coords in {obs_nc}: {list(ods.coords)}")
    obs = ods[obs_var].rename({lat_name: "lat", lon_name: "lon"})

    vic = vds[vic_var]

    # --- temporal alignment: VIC daily -> monthly mean (GRUN is monthly mean)
    if start:
        vic = vic.sel(time=slice(start, None))
        obs = obs.sel(time=slice(start, None))
    if end:
        vic = vic.sel(time=slice(None, end))
        obs = obs.sel(time=slice(None, end))
    vic_m = vic.resample(time="MS").mean()
    obs_m = obs.resample(time="MS").mean()

    common = np.intersect1d(vic_m["time"].values, obs_m["time"].values)
    if common.size == 0:
        raise SystemExit(
            f"no temporal overlap: VIC {vic_m.time.values[0]}..{vic_m.time.values[-1]} "
            f"vs obs {obs_m.time.values[0]}..{obs_m.time.values[-1]}")
    vic_m = vic_m.sel(time=common)
    obs_m = obs_m.sel(time=common)

    # --- clip obs to the VIC bounding box (plus a cell of margin)
    vlat, vlon = vic["lat"].values, vic["lon"].values
    obs_m = obs_m.sortby("lat").sortby("lon")
    obs_m = obs_m.sel(
        lat=slice(vlat.min() - 0.5, vlat.max() + 0.5),
        lon=slice(vlon.min() - 0.5, vlon.max() + 0.5))
    if obs_m["lat"].size == 0 or obs_m["lon"].size == 0:
        raise SystemExit("obs product has no cells over the VIC domain")

    # --- spatial alignment: conservative aggregation onto the obs grid
    vic_agg, cov = aggregate_to_obs_grid(
        vic_m, obs_m["lat"].values, obs_m["lon"].values, min_coverage)

    o = obs_m.transpose("time", "lat", "lon").values.astype(np.float64)
    s = vic_agg.transpose("time", "lat", "lon").values.astype(np.float64)
    both = np.isfinite(o) & np.isfinite(s)

    n_cells = int((both.any(axis=0)).sum())
    if n_cells == 0:
        raise SystemExit("no obs cell survived the coverage mask — "
                         "domain may be smaller than one obs cell")

    m = spatial_metrics(o[both], s[both])

    # Diagnostic: correlation of the TIME-MEAN maps (pure spatial pattern).
    with np.errstate(invalid="ignore"):
        omean = np.nanmean(np.where(both, o, np.nan), axis=0)
        smean = np.nanmean(np.where(both, s, np.nan), axis=0)
    map_mask = np.isfinite(omean) & np.isfinite(smean)
    clim = spatial_metrics(omean[map_mask], smean[map_mask])

    # Diagnostic: domain-mean monthly series (regional aggregate).
    with np.errstate(invalid="ignore"):
        o_ts = np.nanmean(np.where(both, o, np.nan), axis=(1, 2))
        s_ts = np.nanmean(np.where(both, s, np.nan), axis=(1, 2))
    ts = spatial_metrics(o_ts, s_ts)

    result = {
        "vic_nc": str(vic_nc), "obs_nc": str(obs_nc), "obs_var": obs_var,
        "period": [str(pd.Timestamp(common[0]).date()),
                   str(pd.Timestamp(common[-1]).date())],
        "n_months": int(common.size),
        "n_obs_cells_compared": n_cells,
        "n_obs_cells_in_bbox": int(cov.size),
        "min_coverage": min_coverage,
        "obs_grid_deg": float(np.min(np.diff(obs_m["lat"].values))),
        "vic_grid_deg": float(np.min(np.diff(vlat))),
        "pooled_cell_month": m,
        "climatology_map": clim,
        "domain_mean_series": ts,
        "obs_mean_mm_day": float(np.nanmean(o[both])),
        "sim_mean_mm_day": float(np.nanmean(s[both])),
    }
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(json.dumps(result, indent=2, default=float))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vic-nc", required=True)
    ap.add_argument("--obs-nc", required=True)
    ap.add_argument("--obs-var", default="Runoff")
    ap.add_argument("--vic-var", default="Runoff")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--min-coverage", type=float, default=0.75)
    ap.add_argument("--json-out")
    a = ap.parse_args()
    r = compare(a.vic_nc, a.obs_nc, a.obs_var, a.vic_var,
                a.start, a.end, a.min_coverage, a.json_out)
    print(json.dumps(r, indent=2, default=float))


if __name__ == "__main__":
    main()
