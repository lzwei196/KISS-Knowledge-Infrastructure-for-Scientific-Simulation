#!/usr/bin/env python3
"""
parse_wasp_engine_output.py -- REAL-engine results: BMD2_Extract CSV -> daily series -> obs scores.

Reads <run-dir>/<model>_extract.csv written by tools/run_wasp_engine.py (EPA BMD2_Extract.exe;
columns Date_Time "MM/DD/YYYY HH:MM", Segment, Station_ID, one padded column per variable, a
trailing empty column). Writes <out-dir>/sim_daily_seg<N>.csv (daily means of every variable).

Optional scoring against obs from prepare_wqp_lake_obs.py:
  --obs-do / --obs-temp   CSV with date,value (mg/L, deg C); each obs row is paired with the box value
  of that day (a 0-D box gives the same value to every station). The support label is READ from the
  obs file's 'support' column (station_day or network_mean_variable), never assumed; repeated
  (date, station_id) rows are refused (exit 1), so no station-day is counted twice.
  DO is reported twice, from the two columns prepare_wqp_lake_obs.py writes side by side:
    do_all        'value' of every row: ALL data, no cruise QC. This is the HEADLINE
                  (headline = 'do_all.pooled'), always.
    do_sensor_qc  'value_qc' of the rows that have one (cruises with an excluding sensor flag left
                  out). Reported, NOT claimed: it is a subset chosen by a QC rule.
  Each has 'pooled' (all pairs) and 'per_station' (median over stations with n >= --min-station-n).
  A DO file without a value_qc column (an older date,value file) is scored as do_all only and
  qc_note says so; no QC subset is claimed.
  flagged_cruises (cruise -> excluding flags) and diagnostic_cruises (cruise -> diagnostic flags) are
  copied ONLY from the sidecar <obs-do stem>.cruise_qc.json that prepare_wqp_lake_obs.py writes.
  Without it, per-cruise attribution is NOT inferred from the rows (a row lists several ';'-joined
  cruises): flagged_cruises is null, flagged_cruises_note says why, and flagged_rows lists each row
  with an excluding flag as written (date, station_id, cruises_qc_excluded, qc_flag).
  Sensor QC comes from the OBS file, never from this tool and never from model output.
  DO saturation (APHA 1992, standard atmosphere at --elev) of the simulated water temperature (and
  of the observed temperature, with --obs-temp) is written to pairs_do.csv as a diagnostic only; it
  filters nothing. It needs 'Water Temperature' in the extract; without it DO is still scored and
  sim_do_sat_note says the diagnostic was skipped. Metrics: ki_tools_common.metrics.all_metrics
  (found on $KI_TOOLS_COMMON, else KISSPATH_KI_TOOLS_COMMON, else the
  installed package).
  --figure writes the validation figure (observed black, simulated #2563EB, metrics box).
Exit codes: 0 ok; 1 unreadable/empty extract or no pairs; 2 bad command line.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_KTC = Path(os.environ.get("KI_TOOLS_COMMON") or "KISSPATH_KI_TOOLS_COMMON"
            ).expanduser().absolute()
if _KTC.is_dir() and str(_KTC) not in sys.path:
    sys.path.insert(0, str(_KTC))
from ki_tools_common.metrics import all_metrics  # noqa: E402

DO_COL, T_COL = "Dissolved Oxygen", "Water Temperature"


def read_extract(path, segment):
    d = pd.read_csv(path)
    d.columns = [str(c).strip() for c in d.columns]
    d = d.loc[:, [c for c in d.columns if c and not c.startswith("Unnamed")]]
    d["time"] = pd.to_datetime(d["Date_Time"].astype(str).str.strip(), format="%m/%d/%Y %H:%M")
    d = d[pd.to_numeric(d["Segment"], errors="coerce") == segment]
    if d.empty:
        raise ValueError(f"segment {segment} not in {path}")
    num = d.drop(columns=["Date_Time", "Segment", "Station_ID"], errors="ignore")
    return num.set_index("time").apply(pd.to_numeric, errors="coerce").resample("D").mean()


def do_sat_mgl(t_c, elev_m):
    """APHA (1992) fresh-water DO saturation, mg/L, times p/p0 from the standard atmosphere."""
    tk = np.asarray(t_c, float) + 273.15
    ln = (-139.34411 + 1.575701e5 / tk - 6.642308e7 / tk ** 2 + 1.243800e10 / tk ** 3
          - 8.621949e11 / tk ** 4)
    return np.exp(ln) * (1 - 2.25577e-5 * elev_m) ** 5.25588


def score(sim, obs_csv, col):
    """Obs rows paired with the box value of the same day; index = date (repeats for stations).
    Returns (pairs, qc_known, support); qc_known = the file has a value_qc column."""
    if col not in sim:
        raise KeyError(f"the extract has no {col!r} column; extract it with run_wasp_engine.py "
                       f"--extract {col!r}")
    o = pd.read_csv(obs_csv, parse_dates=["date"],
                    dtype={"qc_flag": str, "qc_diag": str, "cruise": str, "cruises_qc_excluded": str})
    if "station_id" not in o:
        o["station_id"] = "network"
    dup = o.duplicated(["date", "station_id"])
    if dup.any():
        raise ValueError(f"{obs_csv}: {int(dup.sum())} repeated (date, station_id) rows - not one row "
                         "per station-day; rebuild it with prepare_wqp_lake_obs.py")
    qc_known = "value_qc" in o
    for c in ("qc_flag", "qc_diag", "cruises_qc_excluded"):
        o[c] = o[c].fillna("") if c in o else ""
    if not qc_known:
        o["value_qc"] = np.nan
    support = (sorted(o["support"].dropna().astype(str).unique()) if "support" in o
               else ["unlabelled (no support column)"])
    p = o.merge(sim[[col]], left_on="date", right_index=True, how="inner")
    return p.dropna(subset=["value", col]).set_index("date").sort_index(), qc_known, support


def metrics(p, col, label, unit):
    if len(p) < 3:
        return {"n": int(len(p))}
    m = all_metrics(p["value"].values, p[col].values, dates=p.index.values, label=label,
                    meta={"unit": unit})
    m = {k: (None if (isinstance(v, float) and math.isnan(v)) else round(float(v), 4)) for k, v in m.items()}
    m["n"] = int(len(p))
    m["obs_mean"], m["sim_mean"] = round(float(p["value"].mean()), 3), round(float(p[col].mean()), 3)
    return m


def fixed_support_metrics(p, col, label, unit, min_n):
    """'pooled' = all station-day pairs; 'per_station' = all_metrics per station (n >= min_n) and
    the median of NSE/KGE/PBIAS/r across those stations."""
    res = {"pooled": metrics(p, col, f"{label}_pooled", unit), "per_station": {}}
    per = {}
    for sid, g in p.groupby("station_id"):
        if len(g) >= min_n:
            per[sid] = metrics(g, col, f"{label}_{sid}", unit)
    med = {}
    for k in ("NSE", "KGE", "PBIAS", "r"):
        vals = [m[k] for m in per.values() if m.get(k) is not None]
        med[f"median_{k}"] = round(float(np.median(vals)), 4) if vals else None
    res["per_station"] = {"min_n": min_n, "n_stations": len(per), **med,
                          "stations": {s: {k: m.get(k) for k in ("n", "NSE", "KGE", "PBIAS", "r")}
                                       for s, m in per.items()}}
    return res


def figure(path, sim, pairs, mets, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(pairs), 1, figsize=(12, 3.6 * len(pairs)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (key, col, unit, p) in zip(axes, pairs):
        ax.plot(sim.index, sim[col], color="#2563EB", lw=0.9, label=f"WASP 8.5 simulated {col}")
        bad = p["qc_flag"].astype(str) != ""
        ax.scatter(p.index[~bad], p.loc[~bad, "value"], color="black", s=12, zorder=3,
                   label="observed (station-day, all data)")
        if bad.any():
            ax.scatter(p.index[bad], p.loc[bad, "value"], facecolors="none", edgecolors="black", s=22,
                       zorder=3, label="observed, includes a cruise with an excluding sensor flag")
        lines = []
        for k in mets:
            if k.startswith(key):
                pm = mets[k].get("pooled", mets[k])
                lines.append(f"{k} pooled: " + ", ".join(f"{m}={v}" for m, v in pm.items()
                                                         if m in ("n", "NSE", "r", "KGE", "PBIAS", "RMSE")))
                ps = mets[k].get("per_station")
                if ps:
                    lines.append(f"{k} per-station median ({ps['n_stations']} st): NSE={ps['median_NSE']}, "
                                 f"KGE={ps['median_KGE']}, PBIAS={ps['median_PBIAS']}")
        ax.text(0.01, 0.03, "\n".join(lines), transform=ax.transAxes, fontsize=7.5, va="bottom",
                bbox=dict(facecolor="white", alpha=0.85, edgecolor="0.7"))
        ax.set_ylabel(f"{col} ({unit})")
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_title(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--extract", required=True, help="<model>_extract.csv from run_wasp_engine.py")
    ap.add_argument("--segment", type=int, default=1)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--obs-do")
    ap.add_argument("--obs-temp")
    ap.add_argument("--elev", type=float, default=0.0, help="water surface elevation m (DO sat)")
    ap.add_argument("--qc-min-sat", type=float, default=None,
                    help="DEPRECATED no-op: sensor QC now comes from the obs file's qc_flag")
    ap.add_argument("--min-station-n", type=int, default=5,
                    help="per-station metrics only for stations with at least this many pairs")
    ap.add_argument("--score-start", help="ignore pairs before this date (spin-up)")
    ap.add_argument("--figure")
    ap.add_argument("--title", default="EPA WASP 8.5 (real engine) vs observations")
    a = ap.parse_args()
    if a.qc_min_sat is not None:
        print("WARNING: --qc-min-sat is deprecated and ignored; DO sensor QC is the cruise-level "
              "qc_flag written by prepare_wqp_lake_obs.py", file=sys.stderr)
    try:
        sim = read_extract(a.extract, a.segment)
    except Exception as e:
        print(f"ERROR: cannot read extract: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sim.to_csv(out / f"sim_daily_seg{a.segment}.csv", float_format="%.5f")
    res = {"extract": a.extract, "segment": a.segment, "sim_days": int(sim.notna().any(axis=1).sum()),
           "sim_variables": list(sim.columns), "metrics": {}}
    pairs, start = [], pd.Timestamp(a.score_start) if a.score_start else None
    stations, supports, tobs = set(), set(), None
    try:
        if a.obs_temp:
            pt, _, sup = score(sim, a.obs_temp, T_COL)
            supports |= {f"temperature: {x}" for x in sup}
        if a.obs_do:
            pd_, qc_known, sup = score(sim, a.obs_do, DO_COL)
            supports |= {f"do: {x}" for x in sup}
    except (ValueError, KeyError) as e:
        print(f"ERROR: cannot score (bad obs file or missing extract variable): {e}", file=sys.stderr)
        return 1
    if a.obs_temp:
        pt = pt[pt.index >= start] if start is not None else pt
        tobs = pt.reset_index().groupby(["date", "station_id"])["value"].mean().rename("t_obs")
        stations |= set(pt["station_id"])
        res["metrics"]["temperature_all"] = fixed_support_metrics(pt, T_COL, "temperature_all", "degC",
                                                                  a.min_station_n)
        pt.to_csv(out / "pairs_temperature.csv")
        pairs.append(("temperature", T_COL, "deg C", pt))
    if a.obs_do:
        pd_ = pd_[pd_.index >= start] if start is not None else pd_
        stations |= set(pd_["station_id"])
        if T_COL in sim:
            pd_["sim_do_sat"] = do_sat_mgl(sim[T_COL].reindex(pd_.index).values, a.elev)
            res["sim_do_over_sat_mean"] = round(float((pd_[DO_COL] / pd_["sim_do_sat"]).mean()), 4)
        else:
            res["sim_do_over_sat_mean"] = None
            res["sim_do_sat_note"] = (f"{T_COL!r} not in the extract: the DO saturation diagnostic was "
                                      "skipped (DO is still scored)")
        if tobs is not None:
            pd_ = pd_.join(tobs, on=["date", "station_id"], how="left")
            pd_["obs_do_sat"] = do_sat_mgl(pd_["t_obs"], a.elev)  # diagnostic only, filters nothing
        excl = pd_["qc_flag"].astype(str) != ""
        res["metrics"]["do_all"] = fixed_support_metrics(pd_, DO_COL, "do_all", "mg/L", a.min_station_n)
        res["headline"] = "do_all.pooled"
        if qc_known:
            pq = pd_[pd_["value_qc"].notna()].copy()
            pq["value"] = pq["value_qc"]
            res["metrics"]["do_sensor_qc"] = fixed_support_metrics(pq, DO_COL, "do_sensor_qc",
                                                                   "mg/L", a.min_station_n)
            res["qc_subset_note"] = ("do_sensor_qc = value_qc (cruises with an excluding sensor flag "
                                     "left out); reported, not claimed - the headline is do_all")
        else:
            res["qc_note"] = ("obs DO file has no value_qc column: no sensor-QC subset is computed; "
                              "rebuild it with prepare_wqp_lake_obs.py for the cruise QC")
        # every flagged cruise, also dead-sensor ones whose values are all out of range (no pairs)
        qc_json = Path(a.obs_do).with_name(Path(a.obs_do).stem + ".cruise_qc.json")
        if qc_json.is_file():
            cr = json.loads(qc_json.read_text()).get("cruises", {})
            res["flagged_cruises"] = {c: r["flags"] for c, r in cr.items() if r.get("flags")}
            res["diagnostic_cruises"] = {c: r.get("diagnostic_flags") for c, r in cr.items()
                                         if r.get("diagnostic_flags")}
            res["cruise_qc"] = str(qc_json)
        elif qc_known:
            # rows carry ';'-joined cruise lists: per-cruise attribution cannot be recovered from
            # them, so report the rows with an excluding flag as written and claim nothing
            res["flagged_cruises"] = None
            res["flagged_cruises_note"] = (f"per-cruise attribution unavailable: {qc_json} not found; "
                                           "flagged_rows lists the obs rows with an excluding flag as written")
            fr = pd_.loc[excl].reset_index()
            res["flagged_rows"] = [{"date": str(r["date"].date()), "station_id": str(r["station_id"]),
                                    "cruises_qc_excluded": str(r["cruises_qc_excluded"]),
                                    "qc_flag": str(r["qc_flag"])} for _, r in fr.iterrows()]
        res["n_obs_rows_with_excluded_cruise"] = int(excl.sum()) if qc_known else None
        pd_.to_csv(out / "pairs_do.csv")
        pairs.insert(0, ("do", DO_COL, "mg/L", pd_))
    res["support"] = (f"{'; '.join(sorted(supports))} (from the obs files); 0-D box value of the "
                      f"day paired with each obs row; stations={sorted(stations)}")
    if pairs and not any(m["pooled"].get("n", 0) for m in res["metrics"].values()):
        print("ERROR: no simulated/observed pairs", file=sys.stderr)
        return 1
    if a.figure and pairs:
        figure(a.figure, sim, pairs, res["metrics"], a.title)
        res["figure"] = a.figure
    (out / "scores.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res["metrics"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
