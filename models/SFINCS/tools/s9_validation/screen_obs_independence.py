#!/usr/bin/env python3
"""Screen a candidate SFINCS observation series for independence from the
prescribed boundary condition.

Motivation (dt_v024, Fraser Hope -> Agassiz, 2026-08-05)
--------------------------------------------------------
SFINCS was scored on point_zs at HYDAT 08MF035 (Agassiz) while the discharge
boundary condition was HYDAT 08MF005 (Hope) -- the same channel, no unforced
tributary between them, +0.5% drainage area.  The reported NSE of 0.9744 was
therefore not a measure of the hydraulics: a three-parameter power-law rating
h = a*Q^b + c, fitted on 2021 and applied unchanged to 2022 with ZERO
hydraulics, scores NSE 0.9993 -- above the model.  The metric measured the
stage-discharge rating, which the boundary condition already contains.

SKILL.md's "use two different stations on the same river" rule is necessary
but NOT sufficient: the downstream gauge must add *information*, not just a
different station name.  This tool makes that test executable and refuses --
by exiting non-zero -- to let a degenerate target be scored silently.

It also flags a second, compounding failure mode: a constant infiltration rate
(qinf) set above the mean rainfall intensity deletes the pluvial term entirely,
leaving the prescribed hydrograph as the sole driver of the solution.

Outputs
-------
<output_dir>/obs_independence.json

Exit codes
----------
0  at least one candidate is INDEPENDENT (and, if --scoring_target was named,
   that target is INDEPENDENT)
1  the scoring target is DEGENERATE -- do NOT report a metric for it; the run
   must emit a NULL metric with reason 'no_independent_obs_target'
2  usage / input error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Thresholds.  r is a heuristic screen; the NSE comparison is the hard test.
# --------------------------------------------------------------------------
DEFAULT_R_THRESHOLD = 0.95
# qinf above this fraction of the mean rainfall intensity suppresses the
# pluvial term to the point where it can no longer influence the solution.
PLUVIAL_WARN_FRACTION = 0.5


# ==========================================================================
# small helpers
# ==========================================================================
def _parse_period(text, label):
    """'2021-03-01..2021-08-24' -> (Timestamp, Timestamp)."""
    if ".." not in text:
        raise SystemExit(f"[error] --{label} must look like YYYY-MM-DD..YYYY-MM-DD, got {text!r}")
    a, b = text.split("..", 1)
    return pd.Timestamp(a.strip()), pd.Timestamp(b.strip())


def _read_tref(inp_path):
    """Pull `tref = YYYYMMDD HHMMSS` out of a sfincs.inp."""
    text = Path(inp_path).read_text(errors="replace")
    m = re.search(r"^\s*tref\s*=\s*(\d{8})\s+(\d{6})", text, re.M)
    if not m:
        m = re.search(r"^\s*tref\s*=\s*(\d{8})", text, re.M)
        if not m:
            raise SystemExit(f"[error] no tref found in {inp_path}")
        return pd.to_datetime(m.group(1), format="%Y%m%d")
    return pd.to_datetime(m.group(1) + m.group(2), format="%Y%m%d%H%M%S")


def _read_inp_scalar(inp_path, key):
    text = Path(inp_path).read_text(errors="replace")
    m = re.search(rf"^\s*{key}\s*=\s*([-\d.eE+]+)", text, re.M)
    return float(m.group(1)) if m else None


def _read_bc_layout(run_dir, n_columns):
    """Resolve what each sfincs.dis column IS, from the deck's own provenance file.

    The sfincs.dis column count is sum-over-flow-stations of THAT station's n_src
    cells, so it can NOT be read back as --n_src and it is NOT the station count.
    hydat_to_sfincs_boundary.py records the real mapping in
    hydat_boundary_summary.json (flow_stations[].n_src_cells and n_src_cells_total,
    written at hydat_to_sfincs_boundary.py lines ~289-304); this reads it, so the
    JSON DESCRIBES the boundary instead of guessing from a column count.

    UNKNOWN IS NOT MISMATCH -- and the TOTAL is resolved SEPARATELY from the
    per-station widths, so the two can be known independently.  A station entry
    that is a legacy `flow_station` bare station-id string, or a dict written
    before n_src_cells existed, records THAT STATION's width as NULL, never 0.
    The total is taken from an explicit n_src_cells_total key when the summary
    carries one, and is summed from the per-station widths only as a fallback;
    n_src_cells_total and columns_match_src_cells are therefore NULL exactly when
    the TOTAL ITSELF is unknown -- NOT merely because the per-station widths are.
    When the total IS known the flag is a real True/False, and a False means a
    REAL disagreement between that known total and the sfincs.dis column count,
    never a fabricated one.  Any unexpected structure degrades to the
    column_count_only layout; this helper is provenance only and must never
    raise, because a screen that aborts here would suppress the degeneracy
    verdict it exists to deliver -- hence the deliberately broad guard below.
    """
    layout = {
        "n_columns": int(n_columns),
        "source": "column_count_only (no hydat_boundary_summary.json alongside sfincs.dis)",
        "flow_stations": None,
        "n_src_cells_total": None,
        "columns_match_src_cells": None,
    }
    summary = Path(run_dir) / "hydat_boundary_summary.json"
    if not summary.exists():
        return layout
    try:
        meta = json.loads(summary.read_text())
        if not isinstance(meta, dict):
            return layout
        stations = meta.get("flow_stations")
        if not stations and meta.get("flow_station"):
            stations = [meta["flow_station"]]
        if not isinstance(stations, list) or not stations:
            return layout

        norm = []
        for st in stations:
            if isinstance(st, dict):
                sid, n = st.get("station_id"), st.get("n_src_cells")
            else:
                sid, n = str(st), None      # bare id: this station's width is UNKNOWN
            norm.append({
                "station_id": sid,
                "n_src_cells": int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else None,
            })

        source = str(summary)
        total = meta.get("n_src_cells_total")
        if total is None and all(s["n_src_cells"] is not None for s in norm):
            total = sum(s["n_src_cells"] for s in norm)
        if total is None:
            source += " (per-station n_src_cells absent: column mapping UNKNOWN)"
            return {**layout, "source": source, "flow_stations": norm}
        return {
            **layout,
            "source": source,
            "flow_stations": norm,
            "n_src_cells_total": int(total),
            "columns_match_src_cells": int(total) == int(n_columns),
        }
    except Exception:
        # Provenance only: NEVER let a malformed summary abort the screen.  The
        # clause is deliberately broad rather than a tuple, because the reachable
        # failures are not enumerable in advance: json.loads accepts the bare
        # non-standard Infinity / -Infinity literals, so `int(n)` in the norm loop
        # above and `int(total)` below raise OverflowError, which no narrow tuple
        # here anticipated.  The sole caller (the provenance loop that builds
        # "bc_column_layout") is unguarded, so ANY escape kills the run before
        # obs_independence.json is written and exits non-zero -- the same exit
        # code as the DEGENERATE verdict, making a crash indistinguishable from
        # the finding this tool exists to deliver.
        return layout


def _load_bc_daily(dis_path, tref):
    """Total prescribed inflow from sfincs.dis, as a daily mean series.

    sfincs.dis layout: column 0 is seconds since tref; every remaining column is
    the m3/s delivered to ONE source cell, in sfincs.src ROW ORDER.  With the
    comma-list --flow_station of hydat_to_sfincs_boundary.py the columns are
    CONCATENATED per station: station k owns a contiguous block of
    n_src_cells[k] columns, each carrying Q_k / n_src_cells[k].  Therefore the
    column count is sum_k n_src_cells[k] -- NOT --n_src, and NOT the number of
    stations -- and the columns are identical only WITHIN one station's block.

    The ROW SUM is nevertheless the TOTAL prescribed inflow across all stations,
    because sum_k n_src_cells[k] * (Q_k / n_src_cells[k]) = sum_k Q_k, whatever
    the grouping.  That total is the quantity this screen needs.  For the
    per-station breakdown use _read_bc_layout(); never infer it from the count.
    """
    arr = np.loadtxt(dis_path)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    q = arr[:, 1:].sum(axis=1)
    t = tref + pd.to_timedelta(arr[:, 0], unit="s")
    return pd.Series(q, index=t).resample("D").mean().dropna(), arr.shape[1] - 1


def _load_obs_daily(csv_path):
    df = pd.read_csv(csv_path)
    date_col = next((c for c in df.columns if c.lower() in ("date", "time", "datetime")), df.columns[0])
    val_col = next(
        (c for c in df.columns if c.lower() in ("level_m", "level", "value", "zs", "stage_m")),
        df.columns[-1],
    )
    s = pd.Series(
        pd.to_numeric(df[val_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col]),
    ).dropna()
    return s.resample("D").mean().dropna()


def _load_sim_daily(his_path, station_index=0):
    """point_zs(time, stations) from sfincs_his.nc -> daily mean series."""
    try:
        import netCDF4 as nc
    except ImportError:
        raise SystemExit("[error] netCDF4 is required to read --sim_his")
    with nc.Dataset(his_path) as ds:
        if "point_zs" not in ds.variables:
            raise SystemExit(f"[error] {his_path} has no point_zs variable")
        tv = ds.variables["time"]
        times = nc.num2date(
            tv[:], tv.units, only_use_cftime_datetimes=False, only_use_python_datetimes=True
        )
        zs = np.asarray(ds.variables["point_zs"][:])
        if zs.ndim == 2:
            zs = zs[:, station_index]
        idx = pd.to_datetime([pd.Timestamp(str(t)) for t in times])
    return pd.Series(np.asarray(zs, dtype=float), index=idx).resample("D").mean().dropna()


def _nse(pred, obs):
    pred = np.asarray(pred, dtype=float)
    obs = np.asarray(obs, dtype=float)
    denom = float(((obs - obs.mean()) ** 2).sum())
    if denom <= 0:
        return None
    return float(1.0 - ((pred - obs) ** 2).sum() / denom)


def _rmse(pred, obs):
    return float(np.sqrt(np.mean((np.asarray(pred, float) - np.asarray(obs, float)) ** 2)))


def _fit_power_rating(q, h):
    """h = a*Q^b + c.  scipy if available, otherwise a c-grid + log-log fit."""
    q = np.asarray(q, dtype=float)
    h = np.asarray(h, dtype=float)
    p0 = [0.03, 0.57, float(np.min(h)) - 1.0]
    try:
        from scipy.optimize import curve_fit

        popt, _ = curve_fit(
            lambda x, a, b, c: a * np.power(x, b) + c, q, h, p0=p0, maxfev=200000
        )
        return [float(v) for v in popt]
    except Exception:
        best, best_sse = None, np.inf
        for c in np.linspace(np.min(h) - 5.0, np.min(h) - 0.01, 400):
            y = h - c
            if np.any(y <= 0):
                continue
            b, loga = np.polyfit(np.log(q), np.log(y), 1)
            a = float(np.exp(loga))
            sse = float(((a * q**b + c - h) ** 2).sum())
            if sse < best_sse:
                best_sse, best = sse, [a, float(b), float(c)]
        if best is None:
            raise SystemExit("[error] rating fit failed on the calibration period")
        return best


# ==========================================================================
# period assembly
# ==========================================================================
def _discover_run_units(primary_dir, station_id, primary_obs_csv):
    """Collect (dir, dis, inp, obs_csv) for the primary run and its siblings.

    The independence screen needs BOTH periods: the naive rating is fitted on
    the calibration period and applied to the validation period, exactly
    mirroring how the model's own datum offset was fitted, so the two are
    compared on equal footing.  A single run directory normally holds only one
    period, so sibling run directories under the same parent are picked up.
    """
    primary_dir = Path(primary_dir)
    units = []
    seen = set()

    def add(d, obs_csv):
        d = Path(d)
        if d in seen:
            return
        dis, inp = d / "sfincs.dis", d / "sfincs.inp"
        if not (dis.exists() and inp.exists() and obs_csv and Path(obs_csv).exists()):
            return
        seen.add(d)
        units.append({"dir": str(d), "dis": str(dis), "inp": str(inp), "obs_csv": str(obs_csv)})

    add(primary_dir, primary_obs_csv)
    for sib in sorted(primary_dir.parent.iterdir()):
        if sib.is_dir() and sib != primary_dir:
            add(sib, sib / f"obs_levels_{station_id}.csv")
    return units


def _assemble(units):
    """Merge every run unit into one daily (bc, obs) frame."""
    bc_parts, obs_parts, provenance, n_src_columns = [], [], [], None
    for u in units:
        tref = _read_tref(u["inp"])
        bc, ncols = _load_bc_daily(u["dis"], tref)
        obs = _load_obs_daily(u["obs_csv"])
        n_src_columns = n_src_columns or ncols
        bc_parts.append(bc)
        obs_parts.append(obs)
        provenance.append(
            {
                "dir": u["dir"],
                "tref": str(tref),
                "bc_span": [str(bc.index.min().date()), str(bc.index.max().date())],
                "obs_span": [str(obs.index.min().date()), str(obs.index.max().date())],
                "n_src_columns": ncols,
                "bc_column_layout": _read_bc_layout(u["dir"], ncols),
            }
        )
    bc = pd.concat(bc_parts).groupby(level=0).mean().sort_index()
    obs = pd.concat(obs_parts).groupby(level=0).mean().sort_index()
    return bc, obs, provenance, n_src_columns


# ==========================================================================
# the screen itself
# ==========================================================================
def screen_candidate(station_id, bc, obs, cal, val, sim, r_threshold):
    out = {"station_id": station_id}

    joined = pd.concat([bc.rename("q"), obs.rename("h")], axis=1, sort=True).dropna()
    if len(joined) < 5:
        out.update(verdict="INSUFFICIENT_DATA", n_overlap=int(len(joined)))
        return out

    r_all = float(np.corrcoef(joined.q, joined.h)[0, 1])
    out["r"] = r_all
    out["r2"] = float(r_all**2)
    out["n_overlap"] = int(len(joined))

    r_by_period = {}
    for label, (a, b) in (("cal", cal), ("val", val)):
        sub = joined.loc[a:b]
        r_by_period[label] = (
            {"n": int(len(sub)), "r": float(np.corrcoef(sub.q, sub.h)[0, 1])}
            if len(sub) >= 5
            else {"n": int(len(sub)), "r": None}
        )
    out["r_by_period"] = r_by_period

    cal_j, val_j = joined.loc[cal[0] : cal[1]], joined.loc[val[0] : val[1]]
    out["cal_period"] = [str(cal[0].date()), str(cal[1].date())]
    out["val_period"] = [str(val[0].date()), str(val[1].date())]
    out["n_cal"] = int(len(cal_j))
    out["n_val"] = int(len(val_j))

    # -- baseline 1: zero-hydraulics power-law rating, fitted on cal only -----
    if len(cal_j) >= 5 and len(val_j) >= 5:
        a, b, c = _fit_power_rating(cal_j.q.values, cal_j.h.values)
        out["rating_params"] = {"a": a, "b": b, "c": c}
        pred_val = a * np.power(val_j.q.values, b) + c
        out["nse_naive_rating"] = _nse(pred_val, val_j.h.values)
        out["rmse_naive_rating_m"] = _rmse(pred_val, val_j.h.values)
        pred_cal = a * np.power(cal_j.q.values, b) + c
        out["nse_naive_rating_cal"] = _nse(pred_cal, cal_j.h.values)
    else:
        out["rating_params"] = None
        out["nse_naive_rating"] = None
        out["rmse_naive_rating_m"] = None
        out["note_rating"] = (
            "calibration and/or validation period not covered by the supplied "
            "boundary/observation series -- the rating baseline could not be fitted"
        )

    # -- baseline 2: lag-1 persistence ---------------------------------------
    if len(val_j) >= 5:
        h = obs.loc[val[0] : val[1]]
        prev = obs.shift(1).reindex(h.index)
        ok = prev.notna()
        out["nse_naive_persistence"] = (
            _nse(prev[ok].values, h[ok].values) if int(ok.sum()) >= 5 else None
        )
    else:
        out["nse_naive_persistence"] = None

    # -- the model -----------------------------------------------------------
    out["nse_model"] = None
    out["nse_model_raw"] = None
    if sim is not None:
        sj = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1, sort=True).dropna().loc[val[0] : val[1]]
        if len(sj) >= 5:
            out["n_val_model"] = int(len(sj))
            out["nse_model_raw"] = _nse(sj.sim.values, sj.obs.values)
            # Most-generous constant vertical registration: the offset that
            # zeroes the bias against the obs themselves.  This is deliberately
            # the BEST case the model can achieve with a constant offset -- if
            # it still loses to the naive rating, degeneracy is unambiguous.
            offset = float(sj.obs.mean() - sj.sim.mean())
            out["best_case_offset_m"] = offset
            out["best_case_offset_is_obs_fitted"] = True
            out["nse_model"] = _nse(sj.sim.values + offset, sj.obs.values)
            out["rmse_model_m"] = _rmse(sj.sim.values + offset, sj.obs.values)
            out["r_model"] = float(np.corrcoef(sj.sim, sj.obs)[0, 1])

    # -- information gain and verdict ----------------------------------------
    nse_naive = max(
        [v for v in (out.get("nse_naive_rating"), out.get("nse_naive_persistence")) if v is not None],
        default=None,
    )
    out["nse_naive_best"] = nse_naive
    out["information_gain"] = (
        float(out["nse_model"] - nse_naive)
        if (out.get("nse_model") is not None and nse_naive is not None)
        else None
    )

    reasons = []
    if r_all > r_threshold:
        reasons.append(
            f"r(BC, obs) = {r_all:.4f} > {r_threshold}: the observation is a near-monotone "
            f"transform of the prescribed boundary condition"
        )
    if out.get("nse_model") is not None and nse_naive is not None and out["nse_model"] <= nse_naive:
        reasons.append(
            f"NSE_model ({out['nse_model']:.4f}) <= NSE_naive ({nse_naive:.4f}): a zero-hydraulics "
            f"baseline beats the model, so the metric measures the rating curve, not the hydraulics"
        )
    out["degeneracy_reasons"] = reasons
    out["verdict"] = "DEGENERATE" if reasons else "INDEPENDENT"
    return out


def check_pluvial(inp_file, precip_file):
    res = {"qinf_mm_hr": None, "mean_precip_mm_hr": None, "ratio": None, "warn": False}
    if inp_file:
        res["qinf_mm_hr"] = _read_inp_scalar(inp_file, "qinf")
    if precip_file and Path(precip_file).exists():
        arr = np.loadtxt(precip_file)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        res["mean_precip_mm_hr"] = float(np.mean(arr[:, 1]))
        res["total_precip_mm"] = float(
            np.trapezoid(arr[:, 1], arr[:, 0] / 3600.0)
            if hasattr(np, "trapezoid")
            else np.trapz(arr[:, 1], arr[:, 0] / 3600.0)
        )
    q, p = res["qinf_mm_hr"], res["mean_precip_mm_hr"]
    if q is not None and p:
        res["ratio"] = float(q / p)
        res["warn"] = bool(q > PLUVIAL_WARN_FRACTION * p)
        if res["warn"]:
            res["message"] = (
                f"qinf = {q:.4g} mm/hr exceeds {PLUVIAL_WARN_FRACTION} x the mean rainfall "
                f"intensity ({p:.4g} mm/hr, ratio {res['ratio']:.1f}x). The pluvial term is "
                f"suppressed and the prescribed hydrograph is effectively the sole driver."
            )
    return res


def suggest_alternatives(hydat_db, bbox, start, end):
    """Optional: list in-domain gauges the boundary condition does NOT force.

    Non-degenerate targets normally DO exist and are simply never wired in
    (Fraser: the Harrison system, and the intermediate longitudinal profile
    gauges).  This is advisory only and never changes the exit code.
    """
    import sqlite3

    out = []
    try:
        con = sqlite3.connect(f"file:{hydat_db}?mode=ro&immutable=1", uri=True)
        w, s, e, n = bbox
        rows = con.execute(
            "SELECT STATION_NUMBER, STATION_NAME, LATITUDE, LONGITUDE, DRAINAGE_AREA_GROSS "
            "FROM STATIONS WHERE LONGITUDE BETWEEN ? AND ? AND LATITUDE BETWEEN ? AND ?",
            (w, e, s, n),
        ).fetchall()
        y0, y1 = pd.Timestamp(start).year, pd.Timestamp(end).year
        for sid, name, lat, lon, area in rows:
            nl = con.execute(
                "SELECT COUNT(*) FROM DLY_LEVELS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?",
                (sid, y0, y1),
            ).fetchone()[0]
            nf = con.execute(
                "SELECT COUNT(*) FROM DLY_FLOWS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?",
                (sid, y0, y1),
            ).fetchone()[0]
            if nl or nf:
                out.append(
                    {
                        "station_id": sid,
                        "station_name": name,
                        "lat": lat,
                        "lon": lon,
                        "drainage_area_km2": area,
                        "level_months_in_window": nl,
                        "flow_months_in_window": nf,
                    }
                )
        con.close()
    except Exception as exc:  # advisory only
        return [{"error": f"{type(exc).__name__}: {exc}"}]
    return sorted(out, key=lambda d: -(d["level_months_in_window"] + d["flow_months_in_window"]))


# ==========================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Refuse to score a SFINCS obs target that the boundary condition determines."
    )
    ap.add_argument("--dis_file", required=True, help="sfincs.dis of the validation run")
    ap.add_argument("--src_file", help="sfincs.src (reported for provenance)")
    ap.add_argument("--inp_file", help="sfincs.inp (tref, qinf)")
    ap.add_argument("--precip_file", help="sfincs.precip (mm/hr)")
    ap.add_argument(
        "--candidates",
        required=True,
        help="comma-separated station_id:levels_csv pairs, e.g. 08MF035:/path/obs_levels_08MF035.csv",
    )
    ap.add_argument("--cal_period", required=True, help="YYYY-MM-DD..YYYY-MM-DD")
    ap.add_argument("--val_period", required=True, help="YYYY-MM-DD..YYYY-MM-DD")
    ap.add_argument("--sim_his", help="sfincs_his.nc of the validation run (optional)")
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--scoring_target", help="station id actually used for scoring (default: all)")
    ap.add_argument("--r_threshold", type=float, default=DEFAULT_R_THRESHOLD)
    ap.add_argument(
        "--no_auto_discover_periods",
        action="store_true",
        help="do not pull sibling run directories in for the calibration period",
    )
    ap.add_argument("--hydat_db", help="optional: suggest independent in-domain alternatives")
    ap.add_argument("--bbox", help="optional: west,south,east,north for --hydat_db")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cal = _parse_period(args.cal_period, "cal_period")
    val = _parse_period(args.val_period, "val_period")

    candidates = {}
    for token in args.candidates.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise SystemExit(f"[error] --candidates entry must be station_id:csv, got {token!r}")
        sid, csv = token.split(":", 1)
        candidates[sid.strip()] = csv.strip()

    inp_file = args.inp_file or str(Path(args.dis_file).with_name("sfincs.inp"))
    primary_dir = Path(args.dis_file).parent

    sim = _load_sim_daily(args.sim_his) if args.sim_his else None

    result = {
        "tool": "screen_obs_independence.py",
        "purpose": (
            "Refuse to score an obs target that the prescribed boundary condition already "
            "determines. Reports information_gain = NSE_model - NSE_naive, which MUST be "
            "quoted alongside any headline metric."
        ),
        "inputs": {
            "dis_file": args.dis_file,
            "src_file": args.src_file,
            "inp_file": inp_file,
            "precip_file": args.precip_file,
            "sim_his": args.sim_his,
        },
        "thresholds": {
            "r_degenerate_above": args.r_threshold,
            "pluvial_warn_fraction": PLUVIAL_WARN_FRACTION,
        },
        "candidates": {},
    }

    if args.src_file and Path(args.src_file).exists():
        src = np.loadtxt(args.src_file)
        # rows of sfincs.src = source CELLS with every flow station concatenated,
        # which is exactly the number of discharge COLUMNS in sfincs.dis.
        result["inputs"]["n_src_points"] = int(src.shape[0] if src.ndim == 2 else 1)

    for sid, csv in candidates.items():
        if not Path(csv).exists():
            result["candidates"][sid] = {"verdict": "MISSING_OBS", "levels_csv": csv}
            continue
        units = (
            [{"dir": str(primary_dir), "dis": args.dis_file, "inp": inp_file, "obs_csv": csv}]
            if args.no_auto_discover_periods
            else _discover_run_units(primary_dir, sid, csv)
        )
        bc, obs, provenance, n_src_columns = _assemble(units)
        entry = screen_candidate(sid, bc, obs, cal, val, sim, args.r_threshold)
        entry["levels_csv"] = csv
        entry["period_sources"] = provenance
        entry["n_src_columns"] = n_src_columns
        result["candidates"][sid] = entry

    result["pluvial_suppression"] = check_pluvial(inp_file, args.precip_file)

    independent = [s for s, c in result["candidates"].items() if c.get("verdict") == "INDEPENDENT"]
    result["usable_targets"] = independent

    targets = [args.scoring_target] if args.scoring_target else list(result["candidates"])
    degenerate = [
        s for s in targets if result["candidates"].get(s, {}).get("verdict") == "DEGENERATE"
    ]
    result["scoring_targets_checked"] = targets
    result["degenerate_targets"] = degenerate

    if not independent:
        result["required_metric_status"] = "null"
        result["required_metric_reason"] = "no_independent_obs_target"
        result["guidance"] = (
            "No candidate adds information over the boundary condition. Report a NULL metric "
            "with reason 'no_independent_obs_target' -- do NOT report a number. Prefer a target "
            "the BC does not determine: a gauge below an unforced tributary confluence, a "
            "multi-gauge longitudinal water-surface profile, an off-channel/floodplain gauge, or "
            "the flood-hazard target (hmax/extent vs a SAR mask, scored with CSI)."
        )
    else:
        result["required_metric_status"] = "ok"

    if args.hydat_db and args.bbox:
        bbox = [float(v) for v in args.bbox.split(",")]
        result["independent_alternatives_in_domain"] = suggest_alternatives(
            args.hydat_db, bbox, cal[0], val[1]
        )

    out_path = out_dir / "obs_independence.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    for sid, c in result["candidates"].items():
        print(
            f"[{c.get('verdict')}] {sid}  r={c.get('r')}  "
            f"NSE_naive_rating={c.get('nse_naive_rating')}  NSE_model={c.get('nse_model')}  "
            f"information_gain={c.get('information_gain')}"
        )
        for reason in c.get("degeneracy_reasons", []):
            print(f"    - {reason}")
    if result["pluvial_suppression"].get("warn"):
        print(f"[WARN] {result['pluvial_suppression']['message']}")
    print(f"[written] {out_path}")

    if degenerate:
        print(
            f"[FAIL] degenerate scoring target(s): {', '.join(degenerate)} -- "
            f"the metric must be reported as NULL, not as a number.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
