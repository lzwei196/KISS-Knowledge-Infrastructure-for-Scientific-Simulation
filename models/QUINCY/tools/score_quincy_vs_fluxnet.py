#!/usr/bin/env python3
"""Score parsed REAL-engine QUINCY output (quincy_daily.csv) against FLUXNET2015 tower fluxes.

Observations: <fluxnet sites>/<SITE>/FULLSET_DD.csv. In the DAILY FLUXNET files carbon fluxes are
g C m-2 day-1 (their yearly sums equal FULLSET_YY), NOT µmol m-2 s-1 as in the half-hourly files,
so they are compared with the model's *_gC columns. LE and H are W m-2 in both.

  variable  obs column (DD)        model column   QC column used
  GPP       GPP_NT_VUT_REF         GPP_gC         NEE_VUT_REF_QC
  Reco      RECO_NT_VUT_REF        Reco_gC        NEE_VUT_REF_QC
  NEE       NEE_VUT_REF            NEE_gC         NEE_VUT_REF_QC   (both: positive = source)
  LE        LE_F_MDS               LE             LE_F_MDS_QC
  H         H_F_MDS                H              H_F_MDS_QC
Daily QC in FULLSET_DD is the fraction of measured or good-quality gap-filled half hours;
days below --min_qc are dropped. Feb 29 is dropped (the engine calendar has 365 days).
Metrics: ki_tools_common.metrics.all_metrics (keys NSE, KGE, PBIAS, RMSE, r) on daily values
and on monthly means (months with >= 20 valid days), plus annual-sum bias.

Exit codes: 0 ok, 2 bad input (missing files/columns, no overlap, fewer than 30 paired days).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import finite  # noqa: E402

FLUXNET_SITES = Path("KISSPATH_OBS/fluxnet/sites")
VARS = {"GPP": ("GPP_NT_VUT_REF", "GPP_gC", "NEE_VUT_REF_QC", "g C m-2 d-1"),
        "Reco": ("RECO_NT_VUT_REF", "Reco_gC", "NEE_VUT_REF_QC", "g C m-2 d-1"),
        "NEE": ("NEE_VUT_REF", "NEE_gC", "NEE_VUT_REF_QC", "g C m-2 d-1"),
        "LE": ("LE_F_MDS", "LE", "LE_F_MDS_QC", "W m-2"),
        "H": ("H_F_MDS", "H", "H_F_MDS_QC", "W m-2")}


def clean(m):
    return {k: (None if v is None or not np.isfinite(v) else float(v)) for k, v in m.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily_csv", required=True, help="quincy_daily.csv from parse_quincy_engine_output.py")
    ap.add_argument("--site", required=True)
    ap.add_argument("--vars", default="GPP,LE,NEE,Reco,H")
    ap.add_argument("--start_year", type=int)
    ap.add_argument("--end_year", type=int)
    ap.add_argument("--min_qc", type=float, default=0.75)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--figure", help="optional PNG path (GPP and LE panels)")
    a = ap.parse_args(argv)
    try:
        qc_min = finite(a.min_qc, "min_qc", 0, 1)
        names = [v.strip() for v in a.vars.split(",") if v.strip()]
        bad = [v for v in names if v not in VARS]
        if bad:
            raise ValueError(f"unknown variables {bad}; choose from {list(VARS)}")
        sim = pd.read_csv(a.daily_csv, parse_dates=["date"]).set_index("date")
        lack = [VARS[v][1] for v in names if VARS[v][1] not in sim.columns]
        if lack:
            raise ValueError(f"{a.daily_csv} lacks model columns {lack} (use parse_quincy_engine_output.py output)")
        f = FLUXNET_SITES / a.site / "FULLSET_DD.csv"
        hdr = f.open().readline().strip().split(",")
        cols = sorted({c for v in names for c in (VARS[v][0], VARS[v][2]) if c in hdr} | {"TIMESTAMP"})
        missing = [VARS[v][0] for v in names if VARS[v][0] not in hdr]
        if missing:
            raise ValueError(f"{f} lacks {missing}")
        obs = pd.read_csv(f, usecols=cols, na_values=[-9999, -9999.0])
        obs["date"] = pd.to_datetime(obs.TIMESTAMP.astype(str), format="%Y%m%d")
        obs = obs.set_index("date")
        obs = obs[~((obs.index.month == 2) & (obs.index.day == 29))]
    except (OSError, ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    lo = pd.Timestamp(f"{a.start_year or sim.index.year.min()}-01-01")
    hi = pd.Timestamp(f"{a.end_year or sim.index.year.max()}-12-31")
    from ki_tools_common.metrics import all_metrics
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {"site": a.site, "obs_file": str(f), "sim_file": str(Path(a.daily_csv).resolve()),
              "period": [str(lo.date()), str(hi.date())], "min_qc": qc_min, "variables": {}}
    pairs_all = []
    for v in names:
        ocol, scol, qcol, unit = VARS[v]
        j = pd.DataFrame({"obs": obs[ocol], "sim": sim[scol]}).loc[lo:hi]
        if qcol in obs:
            j = j[obs[qcol].reindex(j.index) >= qc_min]
        j = j.dropna()
        if len(j) < 30:
            print(f"ERROR: {v}: only {len(j)} paired days after QC", file=sys.stderr)
            return 2
        meta = {"unit": unit, "obs_source": f"FLUXNET2015 {a.site} {ocol}", "sim_source": f"QUINCY qs.bin {scol}"}
        md = clean(all_metrics(j.obs.values, j.sim.values, dates=j.index, label=f"{v}_daily", meta=meta))
        mon = j.groupby(j.index.to_period("M")).agg(["mean", "count"])
        mon = mon[mon[("obs", "count")] >= 20]
        mm = clean(all_metrics(mon[("obs", "mean")].values, mon[("sim", "mean")].values,
                               dates=mon.index.to_timestamp(), label=f"{v}_monthly", meta=meta))
        result["variables"][v] = {"unit": unit, "n_days": int(len(j)), "daily": md,
                                  "monthly": mm, "n_months": int(len(mon)),
                                  "obs_mean": float(j.obs.mean()), "sim_mean": float(j.sim.mean())}
        if v in ("GPP", "NEE", "Reco"):
            full = pd.DataFrame({"obs": obs[ocol], "sim": sim[scol]}).loc[lo:hi].dropna()
            yr = full.groupby(full.index.year).agg(["sum", "count"])
            yr = yr[yr[("obs", "count")] >= 360]
            result["variables"][v]["annual_sum_gC"] = {
                "obs_mean": float(yr[("obs", "sum")].mean()), "sim_mean": float(yr[("sim", "sum")].mean()),
                "n_years": int(len(yr))}
        pairs_all.append(j.rename(columns={"obs": f"{v}_obs", "sim": f"{v}_sim"}))
    pd.concat(pairs_all, axis=1, sort=True).to_csv(out / "scored_pairs_daily.csv", index_label="date")
    (out / "score.json").write_text(json.dumps(result, indent=2))
    if a.figure:
        plot(result, pairs_all, names, a.figure, a.site)
    print(json.dumps({v: {"NSE_daily": r["daily"].get("NSE"), "r_daily": r["daily"].get("r"),
                          "NSE_monthly": r["monthly"].get("NSE"), "PBIAS": r["daily"].get("PBIAS")}
                      for v, r in result["variables"].items()}))
    return 0


def plot(result, pairs, names, path, site):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    show = [v for v in ("GPP", "LE", "NEE") if v in names]
    fig, axes = plt.subplots(len(show), 1, figsize=(12, 3.2 * len(show)), squeeze=False)
    for ax, v in zip(axes[:, 0], show):
        j = next(p for p in pairs if f"{v}_obs" in p)
        mon = j.groupby(j.index.to_period("M")).mean()
        x = mon.index.to_timestamp()
        ax.plot(x, mon[f"{v}_obs"], color="black", lw=1.2, label="FLUXNET2015 (monthly mean)")
        ax.plot(x, mon[f"{v}_sim"], color="#2563EB", lw=1.2, label="QUINCY qs.bin (monthly mean)")
        r = result["variables"][v]
        txt = (f"daily: NSE {r['daily']['NSE']:.2f}  r {r['daily']['r']:.2f}  PBIAS {r['daily']['PBIAS']:.1f}%\n"
               f"monthly: NSE {r['monthly']['NSE']:.2f}  KGE {r['monthly']['KGE']:.2f}  (n={r['n_days']} d)")
        ax.text(0.01, 0.97, txt, transform=ax.transAxes, va="top", fontsize=9,
                bbox=dict(boxstyle="round", fc="white", ec="0.7"))
        ax.set_ylabel(f"{v} [{r['unit']}]")
        ax.legend(loc="upper right", fontsize=8)
    axes[0, 0].set_title(f"QUINCY real engine vs FLUXNET2015 {site}")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)


if __name__ == "__main__":
    sys.exit(main())
