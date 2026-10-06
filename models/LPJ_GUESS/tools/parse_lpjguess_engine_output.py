#!/usr/bin/env python3
"""
parse_lpjguess_engine_output.py -- read the REAL LPJ-GUESS engine's .out
tables (written by run_lpjguess_engine.py) and, optionally, score them
against FLUXNET2015 monthly data. (parse_output_lpjguess.py reads the
SURROGATE's CSV, not these files.)

Engine tables are whitespace columns "Lon Lat Year ..." (one row per grid
cell per year; Lon/Lat printed with 2 decimals). Monthly tables have Jan..Dec
columns; annual tables have one column per PFT plus Total (cmass, lai, fpc,
agpp, anpp, aaet) or their own columns (cflux: Veg Repr Soil Fire Est NEE;
cpool: VegC LitterC SoilC Total; tot_runoff: Surf Drain Base Total).
annual.csv keeps EVERY annual table in run_dir (every *.out without Jan..Dec
columns: cmass, agpp, anpp, lai, fpc, aaet, cflux, cpool, tot_runoff, dens,
doc, cton_leaf, nflux, ngases, nmass, npool, nsources, soil_nflux, soil_npool,
...) and EVERY column of each, named <table>_<column> (e.g. cmass_BNE,
cmass_Total, cflux_Fire, dens_TeBS, npool_SoilN). A table that has no
Lon/Lat/Year columns is listed in summary.json annual_tables_skipped (with the
reason), never dropped silently.

Cells: monthly_long.csv / annual.csv keep all cells (Lon, Lat columns).
Scoring against one tower and the water-balance check need ONE cell: if the
run has more than one cell, pass --cell LON LAT (matched to the 2-decimal
Lon/Lat of the tables); otherwise the tool stops with exit 2. Cells are never
averaged.

Native units (LPJ-GUESS 4.1.1, modules/commonoutput.cpp):
  mgpp, mnpp, mra, mrh, mnee   kgC m-2 month-1   (mnee = mrh - mnpp; + = source,
                               fire C NOT included; mgpp = GPP minus leaf
                               respiration, so a little below tower GPP)
  maet, mevap, mintercep, mrunoff, mpet   mm month-1  (maet = plant
                               TRANSPIRATION only; total ET = maet + mevap +
                               mintercep -- soil.cpp / canexch.cpp)
  mlai                          m2 m-2
  cmass kgC m-2; agpp/anpp kgC m-2 yr-1; lai m2 m-2; aaet mm yr-1
This tool adds per-day columns: carbon x1000/days-in-month -> gC m-2 d-1
(same unit as FLUXNET2015 MM GPP/NEE/RECO) and umol_m2_s (x 1e6/12.011/86400
= 0.9636, the unit dag.yaml declares), water /days-in-month -> mm d-1.

Scoring (--fluxnet_dir with FULLSET_MM.csv): GPP vs GPP_NT_VUT_REF, NEE vs
NEE_VUT_REF, RECO (mra+mrh) vs RECO_NT_VUT_REF, ET (maet+mevap+mintercep)
vs LE_F_MDS converted
with 1 W m-2 = 0.0864/2.45 mm d-1. -9999 -> NaN; months whose NEE_VUT_REF_QC
(fraction of good data) is below --min_qc are dropped for every variable.

Exit codes: 0 ok, 2 bad input (incl. several cells without --cell, or a
--cell not in the tables), 4 no usable rows / no overlap with obs.

Usage:
  python parse_lpjguess_engine_output.py --run_dir run/ --out_dir parsed/ \
      [--fluxnet_dir .../fluxnet/sites/DE-Tha] [--forcing_meta forcing_meta.json] \
      [--figure s8_validation.png] [--cell 13.57 50.96]
"""
import argparse
import calendar
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

MONTHLY = {"mgpp": "carbon", "mnpp": "carbon", "mra": "carbon", "mrh": "carbon",
           "mnee": "carbon", "maet": "water", "mevap": "water", "mintercep": "water",
           "mrunoff": "water", "mpet": "water", "mlai": "state"}
ANNUAL = ["cmass", "agpp", "anpp", "lai", "aaet", "cflux", "tot_runoff", "cpool", "fpc"]
MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]
LE_TO_MM_D = 0.0864 / 2.45
GC_D_TO_UMOL_S = 1e6 / 12.011 / 86400.0   # gC m-2 d-1 -> umol CO2 m-2 s-1


def read_out(path):
    df = pd.read_csv(path, sep=r"\s+")
    if "Year" not in df.columns:
        raise ValueError(f"{path}: no Year column")
    return df


def monthly_long(run_dir):
    frames = []
    for name, kind in MONTHLY.items():
        p = os.path.join(run_dir, f"{name}.out")
        if not os.path.isfile(p):
            continue
        df = read_out(p).melt(id_vars=["Lon", "Lat", "Year"], value_vars=MONTHS,
                              var_name="mon", value_name="value")
        df["month"] = df["mon"].map({m: i + 1 for i, m in enumerate(MONTHS)})
        df["var"] = name
        nd = np.array([calendar.monthrange(int(y), int(m))[1]
                       for y, m in zip(df["Year"], df["month"])])
        if kind == "carbon":
            df["per_day"], df["per_day_unit"] = df["value"] * 1000.0 / nd, "gC m-2 d-1"
            df["unit"] = "kgC m-2 month-1"
            df["umol_m2_s"] = df["per_day"] * GC_D_TO_UMOL_S
        elif kind == "water":
            df["per_day"], df["per_day_unit"] = df["value"] / nd, "mm d-1"
            df["unit"] = "mm month-1"
        else:
            df["per_day"], df["per_day_unit"], df["unit"] = df["value"], "m2 m-2", "m2 m-2"
        frames.append(df.drop(columns="mon"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_values(["Lon", "Lat", "var", "Year", "month"])


def annual_tables(run_dir):
    """Names of the annual .out tables in run_dir: the known ones first, then any other
    *.out that is not a monthly table (no Jan..Dec columns)."""
    names = []
    for p in sorted(glob.glob(os.path.join(run_dir, "*.out"))):
        name = os.path.basename(p)[:-4]
        if name in MONTHLY:
            continue
        with open(p) as f:
            head = f.readline().split()
        if set(MONTHS) <= set(head):
            continue
        names.append(name)
    return sorted(names, key=lambda n: (ANNUAL.index(n) if n in ANNUAL else len(ANNUAL), n))


def annual_wide(run_dir, skipped=None):
    """Every column of every annual table, renamed <table>_<column>, one row per cell-year.
    Tables without Lon/Lat/Year are recorded in `skipped` (name -> reason)."""
    out = []
    skipped = {} if skipped is None else skipped
    for name in annual_tables(run_dir):
        p = os.path.join(run_dir, f"{name}.out")
        if os.path.isfile(p):
            df = pd.read_csv(p, sep=r"\s+")
            if df.empty:
                skipped[name] = "no rows"
                continue
            if not {"Lon", "Lat", "Year"} <= set(df.columns):
                skipped[name] = f"no Lon/Lat/Year columns (header {list(df.columns)[:6]})"
                continue
            keep = [c for c in df.columns if c not in ("Lon", "Lat", "Year")]
            if df.duplicated(["Lon", "Lat", "Year"]).any():
                raise ValueError(f"{p}: more than one row per Lon/Lat/Year")
            out.append(df[["Lon", "Lat", "Year"] + keep]
                       .rename(columns={c: f"{name}_{c}" for c in keep}))
    if not out:
        return pd.DataFrame()
    res = out[0]
    for df in out[1:]:
        res = res.merge(df, on=["Lon", "Lat", "Year"], how="outer")
    return res


def cells(df):
    return sorted({(float(a), float(b)) for a, b in zip(df["Lon"], df["Lat"])})


def pick_cell(df, cell):
    """Rows of ONE cell. cell=None is allowed only when the table has one cell."""
    have = cells(df)
    if cell is None:
        if len(have) != 1:
            raise ValueError(f"run has {len(have)} cells {have[:5]}...; pass --cell LON LAT "
                             "(cells are never averaged)")
        return df
    lon, lat = cell
    hit = [c for c in have if abs(c[0] - lon) <= 0.005 + 1e-9 and abs(c[1] - lat) <= 0.005 + 1e-9]
    if len(hit) != 1:
        raise ValueError(f"--cell {lon} {lat} matches {len(hit)} cells of {have[:5]}")
    return df[(df["Lon"] == hit[0][0]) & (df["Lat"] == hit[0][1])]


def load_fluxnet_mm(site_dir, min_qc):
    df = pd.read_csv(os.path.join(site_dir, "FULLSET_MM.csv")).replace(-9999, np.nan)
    df["Year"], df["month"] = df["TIMESTAMP"] // 100, df["TIMESTAMP"] % 100
    if "NEE_VUT_REF_QC" in df.columns:
        df = df[df["NEE_VUT_REF_QC"] >= min_qc]
    obs = pd.DataFrame({"Year": df["Year"], "month": df["month"]})
    for key, col in [("GPP", "GPP_NT_VUT_REF"), ("NEE", "NEE_VUT_REF"),
                     ("RECO", "RECO_NT_VUT_REF")]:
        obs[key] = df[col] if col in df.columns else np.nan
    obs["ET"] = df["LE_F_MDS"] * LE_TO_MM_D if "LE_F_MDS" in df.columns else np.nan
    return obs


def score(mon, obs):
    """mon must hold ONE cell (pick_cell); duplicates are an error, never averaged."""
    from ki_tools_common.metrics import all_metrics
    if len(cells(mon)) != 1:
        raise ValueError("score() needs exactly one cell")
    if mon.duplicated(["var", "Year", "month"]).any():
        raise ValueError("duplicate var/Year/month rows in one cell")
    piv = mon.pivot(index=["Year", "month"], columns="var", values="per_day").reset_index()
    sim = pd.DataFrame({"Year": piv["Year"], "month": piv["month"], "GPP": piv.get("mgpp"),
                        "NEE": piv.get("mnee")})
    if {"maet", "mevap", "mintercep"} <= set(piv.columns):
        sim["ET"] = piv["maet"] + piv["mevap"] + piv["mintercep"]
    if "mra" in piv and "mrh" in piv:
        sim["RECO"] = piv["mra"] + piv["mrh"]
    m = obs.merge(sim, on=["Year", "month"], suffixes=("_obs", "_sim"))
    res = {}
    for k in ["GPP", "NEE", "RECO", "ET"]:
        if f"{k}_sim" not in m:
            continue
        ok = m[[f"{k}_obs", f"{k}_sim"]].dropna()
        if len(ok) < 12:
            continue
        # pass the month-start dates so the captured evidence carries a real time axis
        dates = pd.to_datetime(dict(year=m.loc[ok.index, "Year"], month=m.loc[ok.index, "month"],
                                    day=1)).values
        mt = all_metrics(ok[f"{k}_obs"].values, ok[f"{k}_sim"].values, dates=dates,
                         label=k,
                         meta={"unit": "mm/day" if k == "ET" else "gC m-2 d-1"})
        mt = {kk: (round(float(v), 4) if v is not None else None) for kk, v in mt.items()}
        mt.update(n_months=int(len(ok)), obs_mean=round(float(ok[f"{k}_obs"].mean()), 4),
                  sim_mean=round(float(ok[f"{k}_sim"].mean()), 4),
                  years=[int(m.loc[ok.index, "Year"].min()), int(m.loc[ok.index, "Year"].max())])
        res[k] = mt
    return res, m


def water_balance(mon, meta):
    """P (forcing) vs total ET (maet+mevap+mintercep) + runoff, over the forcing years.
    ONE cell only: mon must hold one cell and the gridlist one line; P is read at
    that line's (x, y) indices."""
    from ki_tools_common.validation import validate_water_balance
    import netCDF4
    if len(cells(mon)) != 1:
        raise ValueError("water balance needs exactly one cell")
    with open(meta["gridlist"]) as f:
        grid = [ln.split() for ln in f if ln.strip()]
    if len(grid) != 1:
        raise ValueError(f"water balance needs a one-line gridlist ({meta['gridlist']} has {len(grid)})")
    xi, yi = int(grid[0][0]), int(grid[0][1])
    pv = meta["files"]["prec"]
    with netCDF4.Dataset(pv["file"]) as nc:
        var = nc[pv.get("variable", "prec")]
        idx = {"lon": xi, "lat": yi}
        dims = var.dimensions
        if set(dims) != {"lon", "lat", "time"}:
            raise ValueError(f"prec dims {dims}: expected lat, lon, time")
        sl = tuple(idx[d] if d in idx else slice(None) for d in dims)
        p = np.asarray(var[sl], float) * 86400.0
        n_days = len(p)
    sel = mon[(mon["Year"] >= meta["start_year"]) & (mon["Year"] <= meta["end_year"])]
    et = float(sel[sel["var"].isin(["maet", "mevap", "mintercep"])]["value"].sum())
    q = float(sel[sel["var"] == "mrunoff"]["value"].sum())
    wb = validate_water_balance(float(p.sum()), et, q, period_days=n_days)
    return {k: (v if isinstance(v, (int, float, str, bool, type(None), list)) else str(v))
            for k, v in dict(wb).items()}


def figure(m, metrics, path, site):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    keys = [k for k in ["GPP", "NEE", "ET"] if k in metrics]
    fig, axes = plt.subplots(len(keys), 1, figsize=(11, 3.2 * len(keys)), squeeze=False)
    t = pd.to_datetime(dict(year=m["Year"], month=m["month"], day=15))
    unit = {"GPP": "gC m$^{-2}$ d$^{-1}$", "NEE": "gC m$^{-2}$ d$^{-1}$", "ET": "mm d$^{-1}$"}
    for ax, k in zip(axes[:, 0], keys):
        ax.plot(t, m[f"{k}_obs"], color="black", lw=1.2, label=f"FLUXNET2015 {site}")
        ax.plot(t, m[f"{k}_sim"], color="#2563EB", lw=1.2, label="LPJ-GUESS 4.1.1 (real engine)")
        mt = metrics[k]
        ax.text(0.01, 0.97, f"NSE {mt['NSE']:.2f}  KGE {mt['KGE']:.2f}  r {mt['r']:.2f}\n"
                f"PBIAS {mt['PBIAS']:.1f}%  RMSE {mt['RMSE']:.2f}  n={mt['n_months']}",
                transform=ax.transAxes, va="top", fontsize=9,
                bbox=dict(boxstyle="round", fc="white", ec="0.7"))
        ax.set_ylabel(f"monthly {k}\n({unit[k]})")
        ax.legend(loc="upper right", fontsize=8)
    axes[0, 0].set_title(f"LPJ-GUESS real engine vs FLUXNET2015 at {site} (monthly means)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--fluxnet_dir", help="site dir holding FULLSET_MM.csv")
    ap.add_argument("--min_qc", type=float, default=0.5,
                    help="minimum NEE_VUT_REF_QC (fraction good data) to keep a month")
    ap.add_argument("--forcing_meta", help="forcing_meta.json -> water-balance check")
    ap.add_argument("--figure", help="PNG path for the obs-vs-sim figure")
    ap.add_argument("--site", default="", help="label for the figure")
    ap.add_argument("--cell", nargs=2, type=float, metavar=("LON", "LAT"),
                    help="cell to score / water-balance (2-decimal Lon Lat of the tables); "
                         "required when the run has more than one cell")
    a = ap.parse_args()
    if not os.path.isdir(a.run_dir):
        print(f"ERROR: run_dir not found: {a.run_dir}", file=sys.stderr)
        return 2
    skipped = {}
    try:
        mon, ann = monthly_long(a.run_dir), annual_wide(a.run_dir, skipped)
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as e:
        print(f"ERROR: unreadable .out table: {e}", file=sys.stderr)
        return 2
    if mon.empty and ann.empty:
        print("ERROR: no LPJ-GUESS .out tables with rows in run_dir", file=sys.stderr)
        return 4
    need_one = bool(a.forcing_meta or a.fluxnet_dir)
    mon1 = None
    if need_one and not mon.empty:
        try:
            mon1 = pick_cell(mon, a.cell)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
    os.makedirs(a.out_dir, exist_ok=True)
    summary = {"status": "success", "run_dir": a.run_dir,
               "annual_tables_skipped": skipped}
    if mon1 is not None:
        summary["cell"] = list(cells(mon1)[0])
    if not mon.empty:
        mon.to_csv(os.path.join(a.out_dir, "monthly_long.csv"), index=False)
        summary["monthly_vars"] = sorted(mon["var"].unique().tolist())
        summary["n_cells"] = len(cells(mon))
    if not ann.empty:
        ann.to_csv(os.path.join(a.out_dir, "annual.csv"), index=False)
        summary["annual_tables"] = [n for n in annual_tables(a.run_dir) if n not in skipped]
        last = ann[ann["Year"] == ann["Year"].max()]
        summary["last_year"] = int(ann["Year"].max())
        tot = [c for c in last.columns if c.endswith("_Total") or c == "cflux_NEE"]
        summary["last_year_totals_by_cell"] = {
            f"{r.Lon},{r.Lat}": {c: round(float(getattr(r, c)), 4) for c in tot}
            for r in last.itertuples(index=False)}
    if a.forcing_meta and mon1 is not None:
        try:
            summary["water_balance"] = water_balance(mon1, json.load(open(a.forcing_meta)))
        except (ValueError, KeyError, OSError) as e:
            print(f"ERROR: water balance: {e}", file=sys.stderr)
            return 2
    if a.fluxnet_dir:
        if mon.empty:
            print("ERROR: scoring needs monthly tables (mgpp/mnee/maet...)", file=sys.stderr)
            return 4
        try:
            metrics, m = score(mon1, load_fluxnet_mm(a.fluxnet_dir, a.min_qc))
        except (OSError, KeyError, ValueError, pd.errors.ParserError) as e:
            print(f"ERROR: FLUXNET data or scoring input unusable ({a.fluxnet_dir}): {e!r}",
                  file=sys.stderr)
            return 2
        if not metrics:
            print("ERROR: no overlap (>=12 months) between engine output and FLUXNET",
                  file=sys.stderr)
            return 4
        m.to_csv(os.path.join(a.out_dir, "paired_monthly.csv"), index=False)
        summary["metrics"] = metrics
        if a.figure:
            figure(m, metrics, a.figure, a.site or os.path.basename(a.fluxnet_dir.rstrip("/")))
            summary["figure"] = a.figure
    with open(os.path.join(a.out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
