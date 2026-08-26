#!/usr/bin/env python3
"""water_balance.py -- close P - ET - Q - dS on the wflow active basin mask.

docs/s5_output_skill.md lists "water balance components" as an s5 deliverable and
sets the band (line 43: "Acceptable closure error: < 5% of total precipitation"),
and s3_parameters/generate_wflow_toml.py deliberately emits actevap plus the
storage states so the closure can be MEASURED rather than assumed -- but no tool
in tools/s5_postprocess/ implemented it, so every caller hand-rolled it.

THE TWO TRAPS THIS TOOL EXISTS TO CLOSE
---------------------------------------
1. SPATIAL.  Wflow.jl writes output_grid.nc with an ASCENDING latitude axis;
   staticmaps.nc and this KI's forcing.nc use a DESCENDING y axis.  A boolean
   mask taken from staticmaps["wflow_subcatch"].values therefore selects a
   north-south MIRRORED footprint when it is used to index output_grid arrays.
   wflow writes NaN outside the domain, so np.nansum(...) / mask.sum() silently
   rescales the basin mean by (mirrored cells still inside the domain) / (cells
   in the mask) and reports a large, wholly fictitious closure residual.  On Rio
   Pelotas that was 54/80 = 0.675, turning a healthy 3.7% closure into a 24.3%
   FAIL.  Every grid here is aligned by COORDINATE VALUE, never by raw index.

2. TEMPORAL.  P comes from forcing.nc, ET/dS from output_grid.nc and Q from the
   discharge CSV -- three records with three independent time axes.  wflow
   forcing routinely covers a longer archive than was simulated (here forcing is
   1980-01-01..1990-12-31 = 4018 steps while output_grid is 1980-01-02..
   1990-12-31 = 4017: Wflow.jl advances the clock BEFORE it reads forcing, so
   the first forcing record is never consumed).  Summing each term over its own
   span accumulates P over more days than ET and Q and manufactures a residual
   -- the same silent misalignment this tool exists to close.  So the three
   records are INTERSECTED to one common window, every term is summed over that
   window only, and a non-identical set of timestamps is an error, not a note.

Usage:
    python3 water_balance.py --staticmaps staticmaps.nc --forcing forcing.nc \\
      --output_grid output_grid.nc --discharge_csv discharge.csv \\
      --area_km2 8725.7 --start 1981-01-01
"""

import argparse
import json
import os
import sys

import numpy as np

_Y_NAMES = ("y", "lat", "latitude")
_X_NAMES = ("x", "lon", "longitude")
_PRECIP_NAMES = ("precip", "P", "precipitation")
# wflow_sbm storage states, all in mm
_STORAGE_VARS = ("satwaterdepth", "ustorelayerdepth", "snow", "snowwater",
                 "canopystorage")
# the package really lives here; see references[1] of the tool summary
_KI_TOOLS_COMMON_PARENT = "KISSPATH_KI_TOOLS_COMMON"
# docs/s5_output_skill.md line 43: "Acceptable closure error: < 5% of total
# precipitation" -- this KI's documented band, and the one this tool enforces
_CLOSURE_PCT = 5.0


def _axis(ds, names):
    for n in names:
        if n in ds.coords or n in ds.variables:
            return n, np.asarray(ds[n].values, dtype="float64")
    raise ValueError("no axis among %s (have %s)" % (list(names), list(ds.coords)))


def align_mask_to_grid(mask, src_ds, dst_ds, tol=1e-4):
    """Re-express a (y, x) boolean mask defined on src_ds onto dst_ds's grid.

    Returns (mask_on_dst, note).  Matching is by coordinate value, so a reversed
    latitude axis, a different axis name (y vs lat) or a padded window are all
    handled; a coordinate with no partner within `tol` degrees raises rather
    than silently mis-selecting cells.
    """
    _, sy = _axis(src_ds, _Y_NAMES)
    _, sx = _axis(src_ds, _X_NAMES)
    _, dy = _axis(dst_ds, _Y_NAMES)
    _, dx = _axis(dst_ds, _X_NAMES)
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (len(sy), len(sx)):
        raise ValueError("mask %s does not match source grid %s"
                         % (mask.shape, (len(sy), len(sx))))

    def _map(src, dst, label):
        idx = np.abs(dst[None, :] - src[:, None]).argmin(axis=1)
        err = np.abs(dst[idx] - src)
        if err.max() > tol:
            raise ValueError("%s axes do not overlap: worst mismatch %.6g deg"
                             % (label, err.max()))
        return idx

    iy = _map(sy, dy, "latitude")
    ix = _map(sx, dx, "longitude")
    out = np.zeros((len(dy), len(dx)), dtype=bool)
    out[np.ix_(iy, ix)] = mask
    note = ""
    if not (np.array_equal(iy, np.arange(len(sy)))
            and np.array_equal(ix, np.arange(len(sx)))):
        note = ("grid order differs from staticmaps (Wflow.jl writes "
                "output_grid.nc with ASCENDING latitude) -- mask realigned "
                "by coordinate")
    return out, note


def _collapse_layers(a):
    """Sum any leading extra dim (wflow's soil `layer`) with NaN tolerance.

    A cell whose layers are only PARTLY written (wflow fills inactive soil
    layers below a cell's active layer count) must contribute its written
    layers, not NaN -- hence nansum.  A cell whose layers are ALL non-finite is
    genuinely outside the domain and is kept NaN so the caller's finiteness
    check can catch it instead of it silently becoming 0.0.
    """
    a = np.asarray(a, dtype="float64")
    while a.ndim > 3:
        all_bad = np.all(~np.isfinite(a), axis=1)
        a = np.nansum(a, axis=1)
        a[all_bad] = np.nan
    return a


def _basin_mean(arr, mask, label):
    """Basin-mean time series over `mask`; any extra dim (layer) is summed.

    A non-finite value on a masked cell is an ERROR, never a note: wflow writes
    NaN only OUTSIDE the domain, so a NaN inside the mask means the mask is
    mis-aligned, which is precisely the failure this tool exists to close.
    Averaging over the surviving cells would silently rescale the basin mean.
    """
    sel = _collapse_layers(arr)[:, mask]
    bad = int(np.sum(~np.isfinite(sel)))
    if bad:
        raise ValueError(
            "%s: %d/%d masked cell-steps are non-finite -- the mask does not "
            "lie inside the written domain, so the basin mean would be "
            "silently rescaled" % (label, bad, sel.size))
    return sel.mean(axis=1)


def _validate(P, ET, Q, dS, days, tolerance_pct=_CLOSURE_PCT):
    """Delegate the closure verdict to ki_tools_common.validate_water_balance.

    The BAND is this KI's own: docs/s5_output_skill.md line 43, "Acceptable
    closure error: < 5% of total precipitation".  validate_water_balance's
    defaults (tolerance_mm=50, tolerance_pct=10) are absolute-first and sized
    for roughly one year of totals -- on a 10-year accumulation 50 mm is 0.3%
    of P, so a textbook 3.7% closure would be reported FAIL no matter how well
    the model conserves mass.  The absolute tolerance is therefore scaled to
    the same relative band, leaving the percentage test as the operative one;
    the verdict itself is still computed by ki_tools_common, not re-implemented.
    """
    tol_mm = max(50.0, tolerance_pct / 100.0 * max(P, 0.0))
    try:
        from ki_tools_common.validation import validate_water_balance
    except Exception:
        if _KI_TOOLS_COMMON_PARENT not in sys.path:
            sys.path.insert(0, _KI_TOOLS_COMMON_PARENT)
        try:
            from ki_tools_common.validation import validate_water_balance
        except Exception:
            res = P - ET - Q - dS
            pct = (abs(res) / max(P, 1.0)) * 100.0
            out = {"residual_mm": round(res, 1),
                   "residual_pct": round(pct, 1),
                   "status": "PASS"
                             if (abs(res) < tol_mm and pct < tolerance_pct)
                             else ("WARNING"
                                   if (abs(res) < 3 * tol_mm
                                       and pct < 3 * tolerance_pct)
                                   else "FAIL"),
                   "components": {"P_mm": round(P, 1), "ET_mm": round(ET, 1),
                                  "Q_mm": round(Q, 1), "dS_mm": round(dS, 1)},
                   "diagnostics": ["ki_tools_common not importable (tried "
                                   "sys.path + %s) -- local closure check used "
                                   "with the same %.1f%% band"
                                   % (_KI_TOOLS_COMMON_PARENT,
                                      tolerance_pct)]}
            if days:
                # same key/shape contract as validate_water_balance so a caller
                # reading wb['daily_rates'] does not KeyError in this branch
                out["daily_rates"] = {"P_mm_day": round(P / days, 2),
                                      "ET_mm_day": round(ET / days, 2),
                                      "Q_mm_day": round(Q / days, 2)}
            return out
    return validate_water_balance(precip_mm=P, et_mm=ET, runoff_mm=Q,
                                  delta_storage_mm=dS, period_days=days,
                                  tolerance_mm=tol_mm,
                                  tolerance_pct=tolerance_pct)


def _open(path):
    """xr.open_dataset with an h5netcdf fallback.

    KISSPATH_PYTHON_ENV's netCDF4/libhdf5 pairing raises
    `OSError: [Errno -101] NetCDF: HDF error` under xarray on files that
    engine="h5netcdf" -- and a bare netCDF4.Dataset -- open without complaint
    (reproduced 2026-08-06 on this project's staticmaps.nc / forcing.nc /
    output_grid.nc; the system python3 the runner uses is unaffected).  Falling
    back keeps an interpreter-specific packaging problem from being reported as
    a missing water balance.
    """
    import xarray as xr
    first = None
    for engine in (None, "h5netcdf", "netcdf4"):
        try:
            return xr.open_dataset(path) if engine is None \
                else xr.open_dataset(path, engine=engine)
        except Exception as e:  # noqa: BLE001 - re-raised below
            first = first or e
    raise first


def _window(times, start, end):
    """Boolean keep-mask + the kept timestamps, normalised to whole days."""
    import pandas as pd
    t = pd.to_datetime(times).normalize()
    keep = np.ones(len(t), dtype=bool)
    if start is not None:
        keep &= np.asarray(t >= pd.Timestamp(start))
    if end is not None:
        keep &= np.asarray(t <= pd.Timestamp(end))
    return keep, t


def compute_closure(staticmaps, forcing, output_grid, sim_q_m3s, area_km2,
                    start=None, end=None, subcatch_var="wflow_subcatch",
                    tolerance_pct=_CLOSURE_PCT):
    """Closure on the active mask.  `sim_q_m3s` is a discharge CSV path or a
    DataFrame with a date column and a numeric discharge column (m3/s)."""
    import pandas as pd

    diag = []
    sds = _open(staticmaps)
    fds = _open(forcing)
    ods = _open(output_grid)
    try:
        sc = sds[subcatch_var].values
        mask = np.isfinite(sc) & (np.nan_to_num(sc) > 0)
        if not mask.any():
            raise ValueError("%s selects no active cell" % subcatch_var)

        fmask, fnote = align_mask_to_grid(mask, sds, fds)
        if fnote:
            diag.append("forcing: " + fnote)
        omask, onote = align_mask_to_grid(mask, sds, ods)
        if onote:
            diag.append("output_grid: " + onote)

        pvar = next((v for v in _PRECIP_NAMES if v in fds), None)
        if pvar is None:
            raise ValueError("no precipitation variable among %s in %s"
                             % (list(_PRECIP_NAMES), forcing))
        if "actevap" not in ods:
            raise ValueError(
                "actevap absent from %s -- add "
                "land_surface__evapotranspiration_volume_flux to "
                "[output.netcdf_grid.variables]; without it the closure is "
                "vacuous" % output_grid)

        # ── discharge record ───────────────────────────────────────────
        if hasattr(sim_q_m3s, "columns"):
            sim = sim_q_m3s.copy()
        else:
            sim = pd.read_csv(sim_q_m3s)
        tcol = next(c for c in sim.columns
                    if str(c).lower() in ("time", "date", "datetime"))
        qcol = next(c for c in sim.columns
                    if c != tcol and pd.api.types.is_numeric_dtype(sim[c]))
        sim = pd.DataFrame({"date": pd.to_datetime(sim[tcol]).dt.normalize(),
                            "q": pd.to_numeric(sim[qcol],
                                               errors="coerce")}).dropna()

        # ── TEMPORAL ALIGNMENT: intersect the three records ────────────
        fkeep, ft = _window(fds["time"].values, start, end)
        okeep, ot = _window(ods["time"].values, start, end)
        qkeep, qt = _window(sim["date"].values, start, end)
        spans = {"forcing": ft[fkeep], "output_grid": ot[okeep],
                 "discharge": qt[qkeep]}
        for name, t in spans.items():
            if len(t) == 0:
                raise ValueError(
                    "%s has no timestep inside the requested window "
                    "[%s, %s]" % (name, start, end))
        w0 = max(t.min() for t in spans.values())
        w1 = min(t.max() for t in spans.values())
        if w0 > w1:
            raise ValueError(
                "forcing / output_grid / discharge do not overlap in time: "
                + "; ".join("%s %s..%s" % (n, t.min().date(), t.max().date())
                            for n, t in spans.items()))
        if any(t.min() != w0 or t.max() != w1 for t in spans.values()):
            diag.append(
                "time spans differed -- every term summed over the common "
                "window %s..%s (per-record selected spans: %s)"
                % (w0.date(), w1.date(),
                   ", ".join("%s %s..%s [%d]" % (n, t.min().date(),
                                                 t.max().date(), len(t))
                             for n, t in spans.items())))
        fkeep &= np.asarray(ft >= w0) & np.asarray(ft <= w1)
        okeep &= np.asarray(ot >= w0) & np.asarray(ot <= w1)
        qkeep &= np.asarray(qt >= w0) & np.asarray(qt <= w1)
        fdates, odates = ft[fkeep], ot[okeep]
        sim = sim[qkeep].sort_values("date")
        qdates = pd.DatetimeIndex(sim["date"].values)
        if not (fdates.equals(odates) and fdates.equals(qdates)):
            raise ValueError(
                "forcing / output_grid / discharge do not share the same "
                "timesteps inside %s..%s (n = %d / %d / %d) -- P, ET and Q "
                "would be accumulated over different days"
                % (w0.date(), w1.date(), len(fdates), len(odates),
                   len(qdates)))
        days = int(len(fdates))

        # ── terms, all on the common window ────────────────────────────
        P = float(_basin_mean(fds[pvar].values[fkeep], fmask, pvar).sum())
        ET = float(_basin_mean(ods["actevap"].values[okeep], omask,
                               "actevap").sum())

        dS = 0.0
        used, absent = [], []
        for v in _STORAGE_VARS:
            if v in ods:
                s = _basin_mean(ods[v].values[okeep], omask, v)
                dS += float(s[-1] - s[0])
                used.append(v)
            else:
                absent.append(v)
        if absent:
            diag.append("storage states not in output_grid.nc, excluded from "
                        "dS: " + ", ".join(absent))

        Q = float(sim["q"].sum() * 86400.0 / (float(area_km2) * 1e6) * 1000.0)

        wb = dict(_validate(P, ET, Q, dS, days, tolerance_pct))
        wb["diagnostics"] = list(wb.get("diagnostics", [])) + diag
        wb["_totals_mm"] = {"P": P, "ET": ET, "Q_sim": Q, "dS": dS,
                            "days": days}
        wb["_window"] = {"start": str(w0.date()), "end": str(w1.date()),
                         "n_steps": days}
        wb["_storage_terms"] = used
        wb["_active_cells"] = int(mask.sum())
        return wb
    finally:
        sds.close()
        fds.close()
        ods.close()


def main():
    ap = argparse.ArgumentParser(
        description="Close the wflow water balance on the active basin mask")
    ap.add_argument("--staticmaps", required=True)
    ap.add_argument("--forcing", required=True)
    ap.add_argument("--output_grid", required=True)
    ap.add_argument("--discharge_csv", required=True)
    ap.add_argument("--area_km2", type=float, required=True)
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--tolerance_pct", type=float, default=_CLOSURE_PCT,
                    help="closure band, %% of P (docs/s5_output_skill.md:43)")
    ap.add_argument("--output", default="", help="optional JSON output path")
    a = ap.parse_args()
    try:
        wb = compute_closure(a.staticmaps, a.forcing, a.output_grid,
                             a.discharge_csv, a.area_km2,
                             a.start or None, a.end or None,
                             tolerance_pct=a.tolerance_pct)
        out = json.dumps(dict({"status": "success"}, **wb), indent=2,
                         default=float)
        if a.output:
            with open(a.output + ".tmp", "w") as f:
                f.write(out)
            os.replace(a.output + ".tmp", a.output)
        print(out)
        sys.stdout.flush()
        sys.stderr.flush()
        # this venv registers a broken 'gmt' xarray backend whose interpreter
        # TEARDOWN segfaults long after the work is done -- exit hard, exactly
        # as extract_discharge.py does.
        os._exit(0)
    except Exception as e:
        print(json.dumps({"status": "failed",
                          "error": "%s: %s" % (type(e).__name__, e)}, indent=2))
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(2)


if __name__ == "__main__":
    main()
