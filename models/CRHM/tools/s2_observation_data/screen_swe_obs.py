#!/usr/bin/env python3
"""screen_swe_obs.py -- admissibility screen for a satellite SWE observation series.

Decides, BEFORE any CRHM parameter is touched, whether a remotely-sensed SWE
series may be scored against a CRHM run at daily resolution.  The test is
mass-budget consistency of the OBS against the SAME forcing that drives the
model: on a cold-season day the observed snowpack cannot gain more water than
that day's precipitation, and cannot lose water when no melt energy exists.

A passive-microwave SWE retrieval that fails this test is not wrong to use --
it is wrong to use DAILY.  Score it at the aggregation the retrieval supports.
"""
import argparse, glob, json, sys
import numpy as np
import pandas as pd


def read_crhm_obs(paths):
    """Parse CRHM .obs files -> DataFrame indexed by timestamp.

    Layout per docs/format_spec.yaml inputs.forcing: header lines of the form
    'name N (unit)', a '######' delimiter, then rows of
    YYYY M D H MIN followed by the declared variables in header order.
    """
    names, rows = None, []
    for p in sorted(paths):
        lines = open(p, errors="replace").read().split("\n")
        cut = [i for i, l in enumerate(lines) if l.startswith("####")]
        if not cut:
            raise SystemExit("no '######' delimiter in %s" % p)
        cut = cut[0]
        hdr = []
        for l in lines[1:cut]:
            tok = l.split()
            if len(tok) >= 2 and tok[1].isdigit():
                hdr.append(tok[0])
        if names is None:
            names = hdr
        elif names != hdr:
            raise SystemExit("header mismatch between forcing files: %s" % p)
        rows += [l.split() for l in lines[cut + 1:] if l.strip()]
    a = np.asarray(rows, dtype=float)
    idx = pd.to_datetime(dict(year=a[:, 0].astype(int),
                              month=a[:, 1].astype(int),
                              day=a[:, 2].astype(int)))
    return pd.DataFrame({n: a[:, 5 + k] for k, n in enumerate(names)}, index=idx)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--obs_csv", required=True, help="candidate SWE obs series (csv)")
    ap.add_argument("--forcing_obs", required=True,
                    help="CRHM .obs path or glob of the forcing driving the run")
    ap.add_argument("--date_col", default="date")
    ap.add_argument("--swe_col", default="obs_swe_mm")
    ap.add_argument("--cold_months", default="12,1,2")
    ap.add_argument("--melt_temp_c", type=float, default=-5.0,
                    help="Tmax below which melt is taken as impossible")
    ap.add_argument("--min_change_mm", type=float, default=3.0,
                    help="ignore changes smaller than this (retrieval quantisation)")
    ap.add_argument("--precip_tol_mm", type=float, default=1.0)
    ap.add_argument("--max_violation_pct", type=float, default=2.0,
                    help="above this, daily-resolution scoring is inadmissible")
    ap.add_argument("--out_json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when daily scoring is inadmissible")
    a = ap.parse_args()

    obs = pd.read_csv(a.obs_csv, parse_dates=[a.date_col]).set_index(a.date_col)[a.swe_col]
    fr = read_crhm_obs(glob.glob(a.forcing_obs) or [a.forcing_obs])
    if "p" not in fr or "t" not in fr:
        raise SystemExit("forcing must declare 't' and 'p'; found %s" % list(fr.columns))
    day = pd.DataFrame({"P": fr["p"].resample("D").sum(),
                        "Tmax": fr["t"].resample("D").max()})

    j = pd.concat([obs.rename("obs"), day], axis=1, sort=True).dropna()
    j["dobs"] = j["obs"].diff()
    j = j[j.index.to_series().diff().dt.days.eq(1)]
    cold = [int(m) for m in a.cold_months.split(",")]
    j = j[j.index.month.isin(cold)]
    if j.empty:
        raise SystemExit("no overlapping cold-season days between obs and forcing")

    gain = j[(j.dobs > j.P + a.precip_tol_mm) & (j.dobs > a.min_change_mm)]
    loss = j[(j.dobs < -a.min_change_mm) & (j.Tmax < a.melt_temp_c)]
    n_bad = len(gain) + len(loss)
    pct = 100.0 * n_bad / len(j)
    admissible = pct <= a.max_violation_pct

    rep = {
        "obs_csv": a.obs_csv,
        "cold_season_days_tested": int(len(j)),
        "unsupported_gain_days": int(len(gain)),
        "impossible_loss_days": int(len(loss)),
        "mass_inconsistent_pct": round(pct, 2),
        "threshold_pct": a.max_violation_pct,
        "worst_unsupported_gain_mm_per_day": None if gain.empty else round(float(gain.dobs.max()), 2),
        "worst_impossible_loss_mm_per_day": None if loss.empty else round(float(loss.dobs.min()), 2),
        "obs_mean_mm": round(float(obs.mean()), 2),
        "obs_p95_mm": round(float(obs.quantile(0.95)), 2),
        "obs_max_mm": round(float(obs.max()), 2),
        "shallow_snow_regime": bool(obs.quantile(0.95) < 50.0),
        "daily_scoring_admissible": bool(admissible),
        "recommended_scoring_aggregation": "daily" if admissible else "monthly_mean (also report peak-SWE and snow-season mean)",
        "forcing_knobs_locked": (not admissible) or bool(obs.quantile(0.95) < 50.0),
        "note": ("SWE is a mass state: when this screen fails, ClimChng_precip and obs_elev "
                 "MUST stay at 1.0 and the forcing-source elevation. Moving them makes the "
                 "score without making the model right."),
    }
    txt = json.dumps(rep, indent=2)
    print(txt)
    if a.out_json:
        open(a.out_json, "w").write(txt + "\n")
    if a.strict and not admissible:
        sys.exit(1)


if __name__ == "__main__":
    main()
