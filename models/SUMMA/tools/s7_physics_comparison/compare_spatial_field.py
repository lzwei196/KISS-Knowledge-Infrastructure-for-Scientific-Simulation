#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      compare_spatial_field
Stage:        s7_physics_comparison
Description:  Compare a SUMMA HRU-resolved output field against a GRIDDED
              observation (obs_shape: spatial_time_series) and report the
              spatial_field_comparison metric set, with CSI as the
              determining metric.

              The sibling tool compare_physics.py compares SUMMA physics
              options against each other; it has no observation path. This
              tool is the model-vs-gridded-observation comparator.

Inputs:
  - SUMMA_OUTPUT:  one or more SUMMA output NetCDFs (time, hru).
  - ATTRIBUTES_NC: SUMMA attributes.nc -- the CANONICAL hruId order, plus
                   latitude/longitude/HRUarea used to aggregate onto the
                   observation grid.
  - OBS_NC:        gridded observation NetCDF (time, lat, lon).

Outputs:
  - OUTPUT_JSON: metrics, per-cell detail and the provenance needed to tell
    what was actually compared.

HRU ordering
------------
SUMMA writes output in the HRU order of its own settings. This tool checks
that order against attributes.nc rather than merely checking that the output
files agree with EACH OTHER: a consistently permuted run would pass the
weaker check while every HRU's runoff is area-weighted onto the wrong
observation cell, producing plausible-looking but meaningless metrics
(dt_005).

Aggregation
-----------
Each HRU is assigned to the observation cell containing its centroid, and the
cell's simulated value is the HRU-area-weighted mean. Because a basin rarely
fills a 0.5-degree cell, the fraction of each cell actually covered by HRUs is
reported per cell, and --min_cell_coverage can exclude thin edge cells whose
basin-only mean is not comparable to a whole-cell observation.

Gridded observations are compared as a FIELD and are never routed.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import json
import logging
import os
import sys

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EXIT_OK, EXIT_INPUT, EXIT_PROCESS, EXIT_OUTPUT = 0, 1, 2, 3

# Conversion of the simulated field to mm/day. Unknown units are an input
# error: silently assuming a factor is how a 86400x error becomes a metric.
TO_MM_PER_DAY = {
    "m s-1": 86400.0 * 1000.0,
    "m/s": 86400.0 * 1000.0,
    "mm s-1": 86400.0,
    "mm/s": 86400.0,
    "kg m-2 s-1": 86400.0,      # water density 1000 kg/m3 -> 1 kg/m2 == 1 mm
    "kg/m2/s": 86400.0,
    "mm/day": 1.0,
    "mm d-1": 1.0,
    "m/day": 1000.0,
}


def _open(path):
    import xarray as xr
    for eng in ("h5netcdf", None):
        try:
            return xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
        except Exception:
            continue
    return xr.open_dataset(path)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def load_attributes(path):
    from netCDF4 import Dataset
    with Dataset(path) as ds:
        for v in ("hruId", "latitude", "longitude", "HRUarea"):
            if v not in ds.variables:
                raise KeyError(f"attributes.nc missing '{v}'")
        return (np.asarray(ds.variables["hruId"][:]).astype("int64").ravel(),
                np.asarray(ds.variables["latitude"][:], dtype=float).ravel(),
                np.asarray(ds.variables["longitude"][:], dtype=float).ravel(),
                np.asarray(ds.variables["HRUarea"][:], dtype=float).ravel())


def load_sim(paths, sim_var, attr_hru_id):
    """Load and concatenate the simulated field, verifying HRU order.

    Returns (times, values[time, hru]).
    """
    import xarray as xr

    frames = []
    for path in sorted(paths):
        ds = _open(path)
        try:
            if sim_var not in ds.variables:
                raise KeyError(f"{os.path.basename(path)} has no variable '{sim_var}'")
            da = ds[sim_var]

            hru_dim = next((d for d in da.dims if "hru" in str(d).lower()), None)
            time_dim = next((d for d in da.dims if "time" in str(d).lower()), None)
            if hru_dim is None or time_dim is None:
                raise ValueError(
                    f"{os.path.basename(path)}: '{sim_var}' has dims {da.dims}, "
                    "expected a time and an hru dimension")

            # dt_005: the ordering guard must be against attributes.nc, not
            # against the other output files.
            if "hruId" in ds.variables:
                got = np.asarray(ds["hruId"].values).astype("int64").ravel()
                if got.size != attr_hru_id.size or not np.array_equal(got, attr_hru_id):
                    raise ValueError(
                        f"{os.path.basename(path)}: hruId order does not match "
                        f"attributes.nc. Aggregating this run would map HRUs onto "
                        f"the wrong observation cells. "
                        f"output[:5]={got[:5].tolist()} "
                        f"attributes[:5]={attr_hru_id[:5].tolist()}")
            else:
                raise ValueError(
                    f"{os.path.basename(path)} carries no hruId variable, so HRU "
                    f"order cannot be verified against attributes.nc. A matching "
                    f"HRU count is not evidence of a matching order: a permuted "
                    f"output would map every HRU onto the wrong obs cell and the "
                    f"resulting CSI would be meaningless. Add hruId to the SUMMA "
                    f"outputControl so the order can be checked.")

            frames.append(da.transpose(time_dim, hru_dim).load())
        finally:
            ds.close()

    if not frames:
        raise ValueError("no usable SUMMA output files")

    combined = xr.concat(frames, dim=frames[0].dims[0]) if len(frames) > 1 else frames[0]
    combined = combined.sortby(combined.dims[0])
    times = np.asarray(combined[combined.dims[0]].values)
    # Drop duplicated stamps from overlapping restart segments.
    _, keep = np.unique(times, return_index=True)
    combined = combined.isel({combined.dims[0]: np.sort(keep)})
    return (np.asarray(combined[combined.dims[0]].values),
            np.asarray(combined.values, dtype=float))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def cell_edges(coord):
    """Cell edges for a monotonic, regularly spaced coordinate."""
    c = np.asarray(coord, dtype=float)
    step = float(np.median(np.diff(c)))
    return c - step / 2.0, c + step / 2.0, abs(step)


def assign_hrus_to_cells(lat, lon, obs_lat, obs_lon):
    """Map each HRU centroid to an observation cell index.

    Returns (row_idx, col_idx) with -1 where the HRU falls outside the grid.
    """
    lat_lo, lat_hi, dlat = cell_edges(obs_lat)
    lon_lo, lon_hi, dlon = cell_edges(obs_lon)

    lon_adj = lon.copy()
    # Match the observation's longitude convention (-180..180 vs 0..360).
    if float(np.min(obs_lon)) < 0.0:
        lon_adj = np.where(lon_adj > 180.0, lon_adj - 360.0, lon_adj)
    else:
        lon_adj = np.where(lon_adj < 0.0, lon_adj + 360.0, lon_adj)

    rows = np.full(lat.size, -1, dtype=int)
    cols = np.full(lat.size, -1, dtype=int)
    for i in range(lat.size):
        r = np.where((lat[i] >= np.minimum(lat_lo, lat_hi)) &
                     (lat[i] < np.maximum(lat_lo, lat_hi)))[0]
        c = np.where((lon_adj[i] >= np.minimum(lon_lo, lon_hi)) &
                     (lon_adj[i] < np.maximum(lon_lo, lon_hi)))[0]
        if r.size and c.size:
            rows[i], cols[i] = int(r[0]), int(c[0])
    return rows, cols, dlat, dlon


def monthly_mean(times, values):
    """Collapse a (time, n) array to calendar-month means.

    SUMMA stamps output period-ending, so a sample is attributed to the month
    its interval STARTS in; otherwise the first sample of each month is
    credited to the previous one.
    """
    import pandas as pd

    idx = pd.to_datetime(times)
    if idx.size > 1:
        step = np.median(np.diff(idx.values).astype("timedelta64[s]").astype(float))
        idx = idx - pd.to_timedelta(step, unit="s")
    keys = pd.PeriodIndex(idx, freq="M")

    uniq = keys.unique().sort_values()
    out = np.full((uniq.size, values.shape[1]), np.nan, dtype=float)
    for k, period in enumerate(uniq):
        sel = np.asarray(keys == period)
        if sel.any():
            out[k] = np.nanmean(values[sel], axis=0)
    return uniq.to_timestamp().to_pydatetime(), out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_json(path, payload):
    """Write and verify the result. Raises OSError/ValueError on failure.

    Kept separate from the processing path so a write fault reports exit code
    3 (output error) rather than being folded into the generic exit 2.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)

    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise OSError(f"result JSON absent or empty after write: {path}")
    with open(path) as fh:
        back = json.load(fh)
    for key in ("metrics", "n_pairs", "provenance"):
        if key not in back:
            raise ValueError(f"result JSON is missing '{key}' after write")
    return back


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Compare a SUMMA HRU field against a gridded observation.")
    ap.add_argument("--summa_output", nargs="+", required=True)
    ap.add_argument("--attributes_nc", required=True)
    ap.add_argument("--sim_var", required=True)
    ap.add_argument("--var_units", required=True,
                    help="Units of --sim_var in the output file (e.g. 'm s-1').")
    ap.add_argument("--obs_nc", required=True)
    ap.add_argument("--obs_var", required=True)
    ap.add_argument("--obs_lat", default="lat")
    ap.add_argument("--obs_lon", default="lon")
    ap.add_argument("--obs_time", default="time")
    ap.add_argument("--obs_units", default="mm/day")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--csi_thresholds", default=None,
                    help="Comma-separated event thresholds in mm/day. Omit to "
                         "use the observed p25/p50/p75.")
    ap.add_argument("--min_cell_coverage", type=float, default=0.0,
                    help="Drop observation cells whose HRU area covers less than "
                         "this fraction of the cell (0-1).")
    ap.add_argument("--output_json", required=True)
    ap.add_argument("--output_csv", default=None,
                    help="Paired obs/sim series actually scored "
                         "(date,lat,lon,cell_coverage_fraction,obs,sim; "
                         "mm/day). Defaults to --output_json with a .csv "
                         "suffix. This is the evidence the headline metric is "
                         "re-derived from.")
    args = ap.parse_args()

    # -- input validation --
    for path in list(args.summa_output) + [args.attributes_nc, args.obs_nc]:
        if not os.path.isfile(path):
            logger.error(f"input not found: {path}")
            return EXIT_INPUT

    if args.var_units not in TO_MM_PER_DAY:
        logger.error(f"unsupported --var_units '{args.var_units}'; known: "
                     f"{sorted(TO_MM_PER_DAY)}")
        return EXIT_INPUT
    if args.obs_units not in TO_MM_PER_DAY:
        logger.error(f"unsupported --obs_units '{args.obs_units}'")
        return EXIT_INPUT
    sim_factor = TO_MM_PER_DAY[args.var_units]
    obs_factor = TO_MM_PER_DAY[args.obs_units]

    thresholds = None
    if args.csi_thresholds:
        try:
            thresholds = [float(t) for t in args.csi_thresholds.split(",") if t.strip()]
        except ValueError:
            logger.error(f"could not parse --csi_thresholds '{args.csi_thresholds}'")
            return EXIT_INPUT

    # -- processing --
    try:
        import pandas as pd
        from ki_tools_common.metrics import spatial_metrics

        hru_id, lat, lon, area = load_attributes(args.attributes_nc)
        sim_times, sim_vals = load_sim(args.summa_output, args.sim_var, hru_id)
        if sim_vals.shape[1] != hru_id.size:
            raise ValueError(f"simulated field has {sim_vals.shape[1]} HRUs, "
                             f"attributes.nc has {hru_id.size}")
        sim_vals = sim_vals * sim_factor
        logger.info(f"sim: {sim_vals.shape[0]} steps x {sim_vals.shape[1]} HRUs, "
                    f"mean {np.nanmean(sim_vals):.4g} mm/day")

        obs_ds = _open(args.obs_nc)
        try:
            for name in (args.obs_var, args.obs_lat, args.obs_lon, args.obs_time):
                if name not in obs_ds.variables and name not in obs_ds.coords:
                    raise KeyError(f"obs file has no '{name}'")
            obs_da = obs_ds[args.obs_var].sel(
                {args.obs_time: slice(args.start, args.end)})
            obs_lat = np.asarray(obs_ds[args.obs_lat].values, dtype=float)
            obs_lon = np.asarray(obs_ds[args.obs_lon].values, dtype=float)
            obs_times = np.asarray(obs_da[args.obs_time].values)
            obs_da = obs_da.transpose(args.obs_time, args.obs_lat, args.obs_lon)
            obs_vals = np.asarray(obs_da.values, dtype=float) * obs_factor
        finally:
            obs_ds.close()

        if obs_vals.shape[0] == 0:
            raise ValueError(f"observation has no time steps in "
                             f"[{args.start}, {args.end}]")

        rows, cols, dlat, dlon = assign_hrus_to_cells(lat, lon, obs_lat, obs_lon)
        inside = (rows >= 0) & (cols >= 0)
        if not inside.any():
            raise ValueError("no HRU centroid falls inside the observation grid; "
                             "check the lat/lon coordinate names and conventions")
        if not inside.all():
            logger.warning(f"{int((~inside).sum())} of {hru_id.size} HRUs fall "
                           "outside the observation grid and are dropped")

        # Restrict the simulation to the requested window, then aggregate.
        sim_idx = pd.to_datetime(sim_times)
        keep = (sim_idx >= pd.Timestamp(args.start)) & (sim_idx <= pd.Timestamp(args.end))
        if not np.any(np.asarray(keep)):
            raise ValueError(f"simulation has no steps in [{args.start}, {args.end}]")
        sim_times = sim_times[np.asarray(keep)]
        sim_vals = sim_vals[np.asarray(keep)]

        cell_keys = {}
        for i in np.where(inside)[0]:
            cell_keys.setdefault((rows[i], cols[i]), []).append(i)

        cell_list = sorted(cell_keys)
        sim_cells = np.full((sim_vals.shape[0], len(cell_list)), np.nan)
        coverage = np.zeros(len(cell_list))
        for k, key in enumerate(cell_list):
            members = np.asarray(cell_keys[key])
            w = area[members]
            if w.sum() <= 0:
                continue
            sim_cells[:, k] = np.nansum(sim_vals[:, members] * w, axis=1) / w.sum()
            r, _c = key
            cell_area = (dlat * 111320.0) * (dlon * 111320.0 *
                                             np.cos(np.radians(obs_lat[r])))
            coverage[k] = float(w.sum() / cell_area) if cell_area > 0 else 0.0

        # GRUN is monthly; collapse the simulation to the same resolution.
        sim_months, sim_monthly = monthly_mean(sim_times, sim_cells)

        obs_months = pd.PeriodIndex(pd.to_datetime(obs_times), freq="M")
        sim_period = pd.PeriodIndex(pd.to_datetime(sim_months), freq="M")
        common = sim_period.intersection(obs_months).sort_values()
        if common.size == 0:
            raise ValueError("simulation and observation share no common month "
                             f"in [{args.start}, {args.end}]")

        sim_pos = {p: i for i, p in enumerate(sim_period)}
        obs_pos = {p: i for i, p in enumerate(obs_months)}

        paired_obs, paired_sim, per_cell = [], [], []
        # Row-per-(cell, month) capture of exactly what gets scored. Without
        # this the headline metric cannot be re-derived from disk, and a metric
        # that cannot be re-derived is not evidence.
        paired_rows = []
        n_cells_dropped = 0
        for k, (r, c) in enumerate(cell_list):
            if coverage[k] < args.min_cell_coverage:
                n_cells_dropped += 1
                continue
            o_series, s_series = [], []
            for p in common:
                o = obs_vals[obs_pos[p], r, c]
                s = sim_monthly[sim_pos[p], k]
                if np.isfinite(o) and np.isfinite(s):
                    o_series.append(float(o))
                    s_series.append(float(s))
                    paired_rows.append({
                        "date": p.to_timestamp().strftime("%Y-%m-%d"),
                        "lat": float(obs_lat[r]), "lon": float(obs_lon[c]),
                        "cell_coverage_fraction": round(float(coverage[k]), 4),
                        "obs": float(o), "sim": float(s),
                    })
            if not o_series:
                continue
            paired_obs.extend(o_series)
            paired_sim.extend(s_series)
            cell_stat = {
                "lat": float(obs_lat[r]), "lon": float(obs_lon[c]),
                "n_hru": len(cell_keys[(r, c)]),
                "cell_coverage_fraction": round(float(coverage[k]), 4),
                "n_months": len(o_series),
                "obs_mean_mm_day": round(float(np.mean(o_series)), 4),
                "sim_mean_mm_day": round(float(np.mean(s_series)), 4),
            }
            per_cell.append(cell_stat)

        if not paired_obs:
            raise ValueError("no valid observation/simulation pairs after "
                             "aggregation and coverage filtering")

        metrics = spatial_metrics(np.asarray(paired_obs),
                                  np.asarray(paired_sim), thresholds)
        logger.info(f"paired {len(paired_obs)} cell-months over {len(per_cell)} "
                    f"cells: CSI={metrics.get('csi')}, NSE={metrics.get('NSE')}, "
                    f"PBIAS={metrics.get('PBIAS')}")

    except Exception as exc:
        logger.error(f"processing failed: {exc}")
        import traceback
        traceback.print_exc()
        return EXIT_PROCESS

    # ki_tools_common.all_metrics returns UPPERCASE keys (NSE/KGE/PBIAS/RMSE)
    # while the rest of the result schema is lowercase. Emit both spellings so
    # a consumer using either one never silently reads a missing metric as null.
    def _clean(v):
        if isinstance(v, float) and not np.isfinite(v):
            return None
        return v

    metrics_out = {}
    for key, val in metrics.items():
        metrics_out[key] = _clean(val)
        if key.lower() != key:
            metrics_out[key.lower()] = _clean(val)

    # -- paired series CSV: the evidence the headline metric is re-derived from
    csv_path = args.output_csv or os.path.splitext(args.output_json)[0] + ".csv"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".",
                    exist_ok=True)
        pd.DataFrame(paired_rows).sort_values(
            ["date", "lat", "lon"]).to_csv(csv_path, index=False)
        logger.info(f"paired series written: {csv_path} "
                    f"({len(paired_rows)} rows, columns date/lat/lon/obs/sim, "
                    f"units mm/day)")
    except Exception as exc:
        logger.error(f"could not write paired series CSV: {exc}")
        csv_path = None

    # -- output --
    payload = {
        "status": "success",
        "obs_shape": "spatial_time_series",
        "determining_metric": "csi",
        "metrics": metrics_out,
        "n_pairs": int(len(paired_obs)),
        "n_cells": len(per_cell),
        "per_cell": per_cell,
        "provenance": {
            "summa_output": [os.path.abspath(p) for p in sorted(args.summa_output)],
            "attributes_nc": os.path.abspath(args.attributes_nc),
            "sim_var": args.sim_var,
            "sim_units_in": args.var_units,
            "obs_nc": os.path.abspath(args.obs_nc),
            "obs_var": args.obs_var,
            "obs_units_in": args.obs_units,
            "compare_units": "mm/day",
            "period": [args.start, args.end],
            "temporal_resolution": "monthly",
            "routed": False,
            "hru_order_verified_against_attributes": True,
            "csi_thresholds": thresholds,
            "min_cell_coverage": args.min_cell_coverage,
            "n_cells_dropped_by_coverage": n_cells_dropped,
            "paired_series_csv": os.path.abspath(csv_path) if csv_path else None,
        },
    }

    try:
        write_json(args.output_json, payload)
    except Exception as exc:
        logger.error(f"output write/validation failed: {exc}")
        return EXIT_OUTPUT

    logger.info(f"Output validation passed: {args.output_json}")
    print(json.dumps({
        "status": "success",
        "csi": payload["metrics"].get("csi"),
        "nse": payload["metrics"].get("nse"),
        "kge": payload["metrics"].get("kge"),
        "pbias": payload["metrics"].get("pbias"),
        "r": payload["metrics"].get("r"),
        "n_pairs": payload["n_pairs"],
        "n_cells": payload["n_cells"],
        "output_json": os.path.abspath(args.output_json),
        "output_csv": os.path.abspath(csv_path) if csv_path else None,
        "n_cells_dropped_by_coverage": n_cells_dropped,
    }))
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_PROCESS)
