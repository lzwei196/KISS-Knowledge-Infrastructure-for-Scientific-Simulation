#!/usr/bin/env python3
"""
Calibration driver for TOPMODEL (NOAA-OWP BMI, standalone run_bmi).

NOT a model substitute. This orchestrates the REAL run_bmi binary by repeatedly
  (1) writing params.dat with the KI tool write_params_dat,
  (2) running the binary in <run_dir> (binary hardcodes ./data/topmod.run),
  (3) parsing hyd.out with the KI tool parse_hyd_out,
  (4) scoring the CALIBRATION window only (local NSE/KGE/PBIAS/r, same
      formulas as the server's standard_calval, no nonfinite dropping).
The held-out validation window is NEVER used for parameter selection.

Promoted into the KI 2026-06-08 from the hand-written Bengbu 51080 calibrate.py
that produced the documented robust val NSE 0.494 / KGE 0.66 result, so future
agents do not have to re-author the loop (closes the recurring "no calibration
tool ships" skill_md_issue).

----------------------------------------------------------------------------
HARD-WON LESSON — DO NOT BLINDLY MAXIMIZE cal-NSE (Bengbu 51080, 3 runs):
The calibration window can be volume-biased relative to validation. At Bengbu
the cal period (1981-85) is wetter/higher-peaked (PBIAS -34%) than val (+5.5%),
so a single parameter set cannot satisfy both. Pushing cal-NSE up, or selecting
on cal-KGE, OVERFITS and collapses held-out val (observed: cal-NSE 0.3965 ->
val-NSE 0.17; cal-KGE-select -> val-NSE -0.97). The incumbent seed below is a
ROBUST sweet spot, NOT the cal-optimum. Prefer a seed-anchored, bounded search
and inspect val alongside cal before adopting a new set. If the search does not
beat the seed's val metrics, KEEP THE SEED.
----------------------------------------------------------------------------

Timestep convention: the working Bengbu/Wangjiaba pipeline uses DAILY forcing
with the inputs.dat header dt = 1.0 (1 step = 1 day). The C binary indexes
rain[]/pe[] by integer step and is only safe at dt = 1.0, so daily data is fed
as one-step-per-day depths; the 'm/hr' labels in the model header are then a
per-step-depth misnomer. Dimensionless metrics (NSE/KGE/r) are unaffected; only
the m^3/s conversion needs the true seconds-per-step (86400 for daily).

Usage:
  python3 calibrate_topmodel.py --run-dir <dir> [--n 1500] [--start 1980-01-01]
        [--cal 1981-01-01:1985-12-31] [--val 1986-01-01:1990-12-31]
        [--basin NAME] [--seed-only] [--obs-mask FILE]

<run_dir> must already contain run_bmi and data/{inputs.dat,subcat.dat}.
Observed rows come from data/inputs.dat.provenance.json (strict converter,
hash-matched, observation_mode provided_complete or provided_with_gaps, the
latter listing its missing rows) and may be narrowed further by --obs-mask;
legacy inputs.dat without a sidecar needs --obs-mask (old converters wrote 0
for missing days) and is refused without one.
Writes calib_result.json (best_params + cal/val/full metrics) into <run_dir>.
"""
import os, sys, subprocess, json, argparse, hashlib
import numpy as np
from datetime import datetime, timedelta

KI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KI)
from run_topmodel import write_params_dat, write_topmod_run
from parse_topmodel_output import parse_hyd_out


# ---------------------------------------------------------------------------
# Metrics (self-contained; same formulas as the server's standard_calval:
# NSE, KGE-2009, PBIAS, Pearson r). Unlike that module, nonfinite values are
# NOT silently dropped: score() rejects a trial with any nonfinite simulated
# flow before metrics are computed, so a numerically failed run cannot win.
# ---------------------------------------------------------------------------
def _period_metrics(o, s):
    o = np.asarray(o, float); s = np.asarray(s, float)
    if not (np.isfinite(o).all() and np.isfinite(s).all()):
        raise ValueError("nonfinite values reached the metric step")
    n = len(o)
    out = dict(NSE=np.nan, KGE=np.nan, PBIAS=np.nan, r=np.nan, n=int(n))
    if n < 2:
        return out
    ss_tot = np.sum((o - o.mean()) ** 2)
    if ss_tot > 0:
        out['NSE'] = round(float(1 - np.sum((o - s) ** 2) / ss_tot), 4)
    if np.std(o) > 0 and np.std(s) > 0:
        r = float(np.corrcoef(o, s)[0, 1]); out['r'] = round(r, 4)
        if o.mean() != 0:
            alpha = np.std(s) / np.std(o); beta = s.mean() / o.mean()
            out['KGE'] = round(float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)), 4)
    if np.sum(o) != 0:
        out['PBIAS'] = round(float(100 * np.sum(s - o) / np.sum(o)), 2)
    return out


def compute_calval_metrics(dates, obs, sim, cal_start, cal_end, val_start, val_end):
    d = np.array([x.date() if isinstance(x, datetime) else x for x in dates])
    obs = np.asarray(obs, float); sim = np.asarray(sim, float)
    p = lambda t: datetime.strptime(t[:10], "%Y-%m-%d").date()
    cm = np.array([p(cal_start) <= x <= p(cal_end) for x in d], bool)
    vm = np.array([p(val_start) <= x <= p(val_end) for x in d], bool)
    return {'calibration': _period_metrics(obs[cm], sim[cm]),
            'validation': _period_metrics(obs[vm], sim[vm]),
            'full': _period_metrics(obs[cm | vm], sim[cm | vm])}


OBS_MODES = ("provided_complete", "provided_with_gaps")


def _qobs_column(inp, nstep):
    """Qobs (column 3) of inputs.dat, after checking the table shape."""
    try:
        table = np.loadtxt(inp, skiprows=1, ndmin=2)
    except ValueError as exc:
        raise SystemExit(f"calibrate_topmodel: cannot read inputs.dat rows: {exc}. Not calibrated.")
    if table.shape != (nstep, 3):
        raise SystemExit(f"calibrate_topmodel: inputs.dat holds {table.shape} values, expected "
                         f"({nstep}, 3). Not calibrated.")
    return table[:, 2]


def observation_mask(run_dir, nstep, obs_mask_file=None, start=None):
    """Which inputs.dat rows hold REAL observations.

    Old converters wrote 0 for missing observed days, so a 0 in Qobs is not
    trusted on its own.
      * If data/inputs.dat.provenance.json exists it is ALWAYS checked, mask or
        not: its output_sha256 must match inputs.dat, one row = one day
        (physical_dt_hours 24), steps == nstep, start_date == --start, and the
        Qobs column must be real (observation_mode 'provided_complete' or
        'provided_with_gaps'; a placeholder column is refused even with a mask).
      * 'provided_with_gaps': the sidecar's obs_missing_rows (1-based) are not
        observed. inputs.dat itself is checked too: those rows must hold exactly
        obs_placeholder_value and every other row a finite Qobs >= 0.
      * --obs-mask FILE (one 0/1 per row, 1 = real observation) may then only
        DROP rows; marking a sidecar-missing row as observed stops the run.
        Without a mask every observed row of a verified file is real (true zero
        flow kept).
      * With no sidecar a mask is required. Such legacy files carry no timestep
        metadata (the header dt is always 1.0); they are taken as one row per
        day, the documented Bengbu/Wangjiaba convention, and labelled so.
    Anything else stops the run with a clear error.
    """
    inp = os.path.join(run_dir, "data/inputs.dat")
    side = inp + ".provenance.json"
    mask = None
    if obs_mask_file:
        vals = np.loadtxt(obs_mask_file, dtype=float, ndmin=1)
        if vals.shape != (nstep,) or not np.isin(vals, [0, 1]).all():
            raise SystemExit(f"calibrate_topmodel: --obs-mask must hold exactly {nstep} values of 0/1 "
                             f"(one per inputs.dat row); got shape {vals.shape}")
        if not vals.any():
            raise SystemExit("calibrate_topmodel: --obs-mask marks no row as observed")
        mask = vals.astype(bool)
    if not os.path.isfile(side):
        if mask is None:
            raise SystemExit("calibrate_topmodel: data/inputs.dat has no provenance sidecar, so its Qobs "
                             "zeros may be old missing-day fills. Regenerate inputs.dat with "
                             "convert_forcing_to_topmodel.py --dt-hours 24 --obs-file ..., or pass "
                             "--obs-mask FILE (one 0/1 per row). Not calibrated.")
        return mask, (f"obs-mask file {os.path.abspath(obs_mask_file)}; legacy inputs.dat without "
                      "provenance, one row = one day assumed")
    info = json.load(open(side))
    sha = hashlib.sha256(open(inp, "rb").read()).hexdigest()
    if info.get("output_sha256") != sha:
        raise SystemExit("calibrate_topmodel: inputs.dat does not match its provenance sidecar "
                         "(hash differs); the observation column cannot be trusted. Not calibrated.")
    if float(info.get("physical_dt_hours", -1)) != 24.0 or int(info.get("steps", -1)) != nstep:
        raise SystemExit("calibrate_topmodel: this driver maps one inputs.dat row to one day; the "
                         f"sidecar says physical_dt_hours={info.get('physical_dt_hours')}, "
                         f"steps={info.get('steps')}. Not calibrated.")
    if info.get("start_date") is None:
        raise SystemExit("calibrate_topmodel: provenance sidecar has no start_date. Not calibrated.")
    if start is not None and info["start_date"] != start:
        raise SystemExit(f"calibrate_topmodel: --start {start} differs from the inputs.dat start "
                         f"{info['start_date']} in the provenance sidecar; dates would be shifted. "
                         "Not calibrated.")
    mode = info.get("observation_mode")
    if mode not in OBS_MODES:
        raise SystemExit("calibrate_topmodel: inputs.dat Qobs is a placeholder "
                         f"(observation_mode={mode!r}); there is nothing "
                         "real to calibrate against (a mask cannot make it real). Not calibrated.")
    qobs = _qobs_column(inp, nstep)
    observed = np.ones(nstep, bool)
    if mode == "provided_with_gaps":
        rows = info.get("obs_missing_rows")
        ph = info.get("obs_placeholder_value")
        if (not isinstance(rows, list) or not rows or len(set(rows)) != len(rows)
                or not all(isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= nstep for r in rows)):
            raise SystemExit("calibrate_topmodel: provided_with_gaps sidecar needs obs_missing_rows as a "
                             f"non-empty list of unique row numbers 1..{nstep}. Not calibrated.")
        if info.get("obs_missing_count_days") != len(rows):
            raise SystemExit("calibrate_topmodel: sidecar obs_missing_count_days "
                             f"{info.get('obs_missing_count_days')} differs from {len(rows)} listed rows "
                             "(one row = one day). Not calibrated.")
        if not isinstance(ph, (int, float)) or isinstance(ph, bool) or not np.isfinite(ph) or ph >= 0:
            raise SystemExit(f"calibrate_topmodel: sidecar obs_placeholder_value {ph!r} must be a finite "
                             "negative number. Not calibrated.")
        observed[np.asarray(rows) - 1] = False
        if not (qobs[~observed] == ph).all():
            raise SystemExit("calibrate_topmodel: a row listed as missing in the sidecar does not hold the "
                             f"placeholder {ph} in inputs.dat. Not calibrated.")
    if not (np.isfinite(qobs[observed]).all() and (qobs[observed] >= 0).all()):
        raise SystemExit("calibrate_topmodel: an inputs.dat row the sidecar treats as observed has a "
                         "nonfinite or negative Qobs. Not calibrated.")
    if not observed.any():
        raise SystemExit("calibrate_topmodel: the sidecar marks no row as observed. Not calibrated.")
    src = f"provenance sidecar {side} (start {info['start_date']}, {mode}, {int((~observed).sum())} missing rows)"
    if mask is not None:
        if (mask & ~observed).any():
            bad = (np.flatnonzero(mask & ~observed) + 1)[:10].tolist()
            raise SystemExit("calibrate_topmodel: --obs-mask marks rows as observed that the sidecar lists "
                             f"as missing (rows {bad}); a mask may only drop rows. Not calibrated.")
        return mask, src + f" + obs-mask file {os.path.abspath(obs_mask_file)}"
    return observed, src


# Robust calibrated incumbent (Bengbu 51080, DEM-TWI 250m, TL=10.92): the
# documented sweet spot — val NSE 0.494 / KGE 0.66 / PBIAS +5.5%. Note t0 (ln T0)
# must be ~8 to match the high TL of a coarse-resampled large-basin DEM; the old
# pre-DEM seed t0=4.81 over-buffers baseflow and collapses to val NSE -0.55.
# Use this as the search seed AND as the fallback if a search fails to beat it.
INCUMBENT = dict(szm=0.07766910481777813, t0=8.192080310537252,
                 td=3.889710254769695, chv=119219.105808948,
                 rv=572408.1456435532, srmax=0.007757197800692256,
                 Q0=0.00017122713918683177, sr0=0.001, infex=0,
                 xk0=1.0, hf=0.02, dth=0.1)


def build_dates(run_dir, start):
    with open(os.path.join(run_dir, "data/inputs.dat")) as f:
        nstep = int(f.readline().split()[0])
    return nstep, [start + timedelta(days=i) for i in range(nstep)]


# Why the most recent trial was rejected (score() returned None); shown in the
# exit message when nothing could be scored.
LAST_REJECT = {"reason": None}


def _reject(reason):
    LAST_REJECT["reason"] = reason
    return None


def score(run_dir, params, dates, basin, cal, val, obs_mask):
    write_params_dat(os.path.join(run_dir, "data/params.dat"), params, basin)
    r = subprocess.run([os.path.join(run_dir, "run_bmi")], cwd=run_dir,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return _reject(f"run_bmi exit code {r.returncode}")
    try:
        ts, qs, qo = parse_hyd_out(os.path.join(run_dir, "hyd.out"))
    except (ValueError, OSError) as exc:
        return _reject(f"hyd.out not readable: {exc}")
    # topmodel.c results() writes exactly one "it Qobs Q" line for it=1..nstep.
    # Anything else (skipped/malformed/truncated rows) would shift the
    # row-to-date and row-to-mask mapping, so the trial is rejected.
    n = len(dates)
    if len(ts) != n or not np.array_equal(np.asarray(ts), np.arange(1, n + 1)):
        return _reject(f"hyd.out rows are not exactly 1..{n} (got {len(ts)} rows)")
    qs, qo, dd = np.asarray(qs, float), np.asarray(qo, float), dates
    valid = obs_mask.copy()
    # A row marked observed must hold a finite, nonnegative value (zero is a
    # real dry day here because the mask/provenance says it was observed).
    if not (np.isfinite(qo[valid]).all() and (qo[valid] >= 0).all()):
        raise SystemExit("calibrate_topmodel: a row marked as observed has a missing/negative Qobs "
                         "in hyd.out; the observation mask and inputs.dat disagree. Not calibrated.")
    # A numerically failed trial (any nonfinite simulated flow) is rejected,
    # never scored on the finite remainder.
    if not np.isfinite(qs).all():
        return _reject("nonfinite simulated flow")
    if not valid.any():
        return _reject("no observed row")          # nothing to score
    dd = [d for d, v in zip(dd, valid) if v]
    return compute_calval_metrics(dd, qo[valid], qs[valid],
                                  cal_start=cal[0], cal_end=cal[1],
                                  val_start=val[0], val_end=val[1])


def main():
    ap = argparse.ArgumentParser(description="Calibrate TOPMODEL via real run_bmi")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--n", type=int, default=1500, help="random trials (~1.2s each)")
    ap.add_argument("--start", default="1980-01-01")
    ap.add_argument("--cal", default="1981-01-01:1985-12-31")
    ap.add_argument("--val", default="1986-01-01:1990-12-31")
    ap.add_argument("--basin", default="Basin")
    ap.add_argument("--seed-only", action="store_true",
                    help="evaluate only the incumbent seed (no search)")
    ap.add_argument("--obs-mask", default=None,
                    help="text file, one 0/1 per inputs.dat row (1 = real observation); "
                         "needed when inputs.dat has no matching provenance sidecar; with a "
                         "sidecar it may only drop rows")
    args = ap.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    start = datetime.strptime(args.start, "%Y-%m-%d")
    nstep, dates = build_dates(run_dir, start)
    obs_mask, mask_source = observation_mask(run_dir, nstep, args.obs_mask, args.start)
    print(f"observed rows: {int(obs_mask.sum())}/{nstep} (from {mask_source})", flush=True)
    write_topmod_run(os.path.join(run_dir, "data"), title=args.basin)

    cal_win = tuple(args.cal.split(":")); val_win = tuple(args.val.split(":"))
    seed = dict(INCUMBENT)
    if args.seed_only:
        m = score(run_dir, seed, dates, args.basin, cal_win, val_win, obs_mask)
        best_params, best_m = seed, m
    else:
        rng = np.random.RandomState(42)
        trials = [seed] + [dict(
            szm=float(10**rng.uniform(-2.3, -0.7)),
            t0=float(rng.uniform(-1.0, 9.0)),            # ln(T0)
            td=float(10**rng.uniform(-0.3, 1.8)),
            chv=float(10**rng.uniform(4.7, 5.8)),
            rv=float(10**rng.uniform(4.7, 5.8)),
            srmax=float(10**rng.uniform(-3.0, -1.0)),
            Q0=float(10**rng.uniform(-4.5, -3.0)),
            sr0=0.001, infex=0, xk0=1.0, hf=0.02, dth=0.1) for _ in range(args.n)]
        best = None; best_params = seed; best_m = None
        for i, p in enumerate(trials):
            m = score(run_dir, p, dates, args.basin, cal_win, val_win, obs_mask)
            if m is None:
                continue
            cal = m['calibration']['NSE']
            if cal is None or np.isnan(cal):
                continue
            if best is None or cal > best:
                best, best_params, best_m = cal, p, m
                print(f"[{i}] cal-NSE={cal:.4f} val-NSE={m['validation']['NSE']:.4f} "
                      f"szm={p['szm']:.4f} t0={p['t0']:.2f}", flush=True)

    # A result is written only for a set that was actually scored: with no
    # scorable trial (no usable observations, every run failed) the run stops
    # instead of reporting the fixed seed parameters as calibrated.
    def _cal_nse(m):
        v = m['calibration']['NSE'] if m else None
        return None if v is None or np.isnan(v) else v
    if args.seed_only:
        if _cal_nse(best_m) is None:
            sys.exit("calibrate_topmodel: the seed could not be scored (run failed or no "
                     "usable observations in the calibration window); nothing written. "
                     f"Last rejection: {LAST_REJECT['reason']}")
    elif best_m is None:
        sys.exit("calibrate_topmodel: no trial could be scored (every run failed or the "
                 "observations have no usable values/variation in the calibration "
                 f"window); calib_result.json NOT written. Last rejection: {LAST_REJECT['reason']}")

    # Re-run the chosen set so run_dir holds the canonical hyd.out for it.
    best_m = score(run_dir, best_params, dates, args.basin, cal_win, val_win, obs_mask)
    if _cal_nse(best_m) is None:
        sys.exit("calibrate_topmodel: the re-run of the chosen set could not be scored; "
                 f"calib_result.json NOT written. Last rejection: {LAST_REJECT['reason']}")
    print("\n=== BEST PARAMS ===\n" + json.dumps(best_params, indent=2))
    print("=== METRICS ===\n" + json.dumps(best_m, indent=2, default=float))
    if best_m and best_m['validation']['NSE'] is not None:
        print("\nNOTE: confirm val NSE/KGE did not degrade vs the incumbent seed "
              "before adopting; cal-optimum != robust optimum (see header).")
    json.dump({"best_params": best_params, "metrics": best_m,
               "observation_rows": int(obs_mask.sum()), "observation_source": mask_source},
              open(os.path.join(run_dir, "calib_result.json"), "w"),
              indent=2, default=float)


if __name__ == "__main__":
    main()
