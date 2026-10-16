#!/usr/bin/env python3
"""MARRMoT structures at 淮滨 Huaibin (16,005 km²) — System 1 W4 model-structure test.

One fail-closed driver, many structures: env SYS1_MARRMOT_MODEL names the MARRMoT model
(e.g. m_07_gr4j_4p_2s); the candidate vector comes from KDT_CALIB_PARAMS as {"x1":..,"xN":..}
(N = the model's numParams — any other set of names aborts). The REAL model runs through the
KI's own tools/run_marrmot.py (Octave), never a re-implementation.

  forcing   models/MARRMoT/huaibin/forcing/forcing_{1980_1998,2000_2018}.csv — the same basin-mean
            series as the HBV case (P, FAO-56 PET, T), i.e. the same water VIC saw.
  obs       淮河txt/淮滨.txt, stcd 50229350, sha1-pinned in models/HBV/huaibin/huaibin_obs_sha1.txt
            (shared pin: one obs file for every lumped model), converted to mm/d with 16,005 km².
  splits    KDT_CALIB_SPLIT=<year>: the era containing the year is simulated whole (≥1 spin-up
            year) and only that calendar year is scored (with day_bias peak timing and Q/P yields).
            "_both" scores the whole 2000-2018 era as one series (no annual-peak timing term).
            "calibration"/"holdout" score every year of KDT_CALIB_SPLIT_SETS (mean of per-year metrics).
  checks    forcing must be date,P,Ep,T in that order, finite, continuous daily; run_marrmot.py must
            exit 0 AND report status=success; every simulated day must be finite; every published
            metric must be finite (strict JSON). A supplied KDT_CALIB_PARAMS must be a full candidate.
  output    {"nse","kge","pbias","r","rmse","__kdt__":{...}} to --out; NOTHING on any failure.
            With KDT_VIC_KEEP_WORKDIR=1: <workdir>/run/sim_daily.csv (date,q_m3s) is kept for the
            harness' timing term.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
MARRMOT_SRC = "KISSPATH_KI_ROOT/MARRMoT/source/repo/MARRMoT"
PE = sys.executable
BASIN = Path("KISSPATH_KI_ROOT/MARRMoT/huaibin")
OBS = Path("KISSPATH_DATA/china_water_level/淮河txt/淮滨.txt")
OBS_PIN = Path("KISSPATH_KI_ROOT/HBV/huaibin/huaibin_obs_sha1.txt")
TARGET_STCD = 50229350
AREA_KM2 = 16005.0
CASE_ID = "SITE:huaibin"
ERAS = {"1980_1998": (1980, 1998), "2000_2018": (2000, 2018)}
RANGES = Path("KISSPATH_DATA/System1/offline/huai_scaleup/w4_lumped/marrmot_parranges.txt")

sys.path.insert(0, KI); sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics  # noqa: E402


def die(msg, code=1):
    print(f"[calib_run_huaibin/marrmot] FAIL: {msg}", file=sys.stderr, flush=True); sys.exit(code)


def par_ranges(model: str) -> list[tuple[float, float]]:
    for l in RANGES.read_text().splitlines():
        t = l.split()
        if t and t[0] == model and t[1] != "ERROR":
            return [tuple(map(float, s.split(","))) for s in t[3:]]
    die(f"{model} has no parameter ranges in {RANGES}")


FORCING_COLS = ["date", "P", "Ep", "T"]   # run_marrmot.py's Octave reader takes columns 2..4 BY POSITION as P, Ep, T


def _forcing_override() -> Path | None:
    """KDT_MARRMOT_FORCING_FILE: run on another forcing CSV of the same layout (e.g. a 1-year slice for a
    state-update experiment). Fail-closed: the file must exist; its full layout is checked by
    _check_forcing() before any run."""
    f = os.environ.get("KDT_MARRMOT_FORCING_FILE", "").strip()
    if not f:
        return None
    p = Path(f)
    if not p.exists():
        die(f"KDT_MARRMOT_FORCING_FILE does not exist: {p}")
    return p


def _check_forcing(p: Path) -> pd.DataFrame:
    """Fail-closed forcing contract (default AND override files). The Octave reader in run_marrmot.py
    (csvread after the header, columns 2,3,4 -> P, Ep, T; one row = one delta_t = 1 day) never looks at
    names or dates, so this is the only place they are checked:
      * columns exactly date,P,Ep,T in that order (a 'date,T,P,Ep' file would run with swapped physics);
      * every value numeric and finite, P >= 0, Ep >= 0;
      * dates parse, strictly increasing by exactly one day (a gap would silently compress model time)."""
    if not p.exists():
        die(f"forcing missing: {p}")
    fc = pd.read_csv(p, comment="#")
    cols = [str(c).strip() for c in fc.columns]
    if cols != FORCING_COLS:
        die(f"forcing {p} columns {cols} != {FORCING_COLS} (order matters: the Octave reader is positional)")
    fc.columns = cols
    if len(fc) < 2:
        die(f"forcing {p} has {len(fc)} rows")
    d = pd.to_datetime(fc["date"], format="%Y-%m-%d", errors="coerce")
    if d.isna().any():
        die(f"forcing {p}: {int(d.isna().sum())} unparseable dates (want YYYY-MM-DD)")
    step = d.diff().dropna()
    if not (step == pd.Timedelta(days=1)).all():
        bad = d[1:][(step != pd.Timedelta(days=1)).to_numpy()]
        die(f"forcing {p} is not continuous daily: {len(bad)} breaks, first at {bad.iloc[0].date()}")
    for c in ("P", "Ep", "T"):
        v = pd.to_numeric(fc[c], errors="coerce")
        if not np.isfinite(v.to_numpy(dtype=float)).all():
            die(f"forcing {p}: column {c} has missing/non-numeric/non-finite values")
        fc[c] = v.astype(float)
    if (fc["P"] < 0).any() or (fc["Ep"] < 0).any():
        die(f"forcing {p}: negative P or Ep")
    fc["date"] = d
    return fc


def _load_theta(model: str, pr, n: int):
    """Candidate from KDT_CALIB_PARAMS. Absent env -> UNTUNED range mid-point (labelled as such).
    A SUPPLIED file must hold exactly {"x1".."xN"} with finite numbers inside parRange: an empty or
    partial candidate is an error, never a silent switch to the mid-point."""
    want = [f"x{i}" for i in range(1, n + 1)]
    pf = os.environ.get("KDT_CALIB_PARAMS", "").strip()
    if pf:
        try:
            handed = json.loads(Path(pf).read_text())
        except (OSError, ValueError) as e:
            die(f"KDT_CALIB_PARAMS={pf} unreadable: {e}")
        if not isinstance(handed, dict) or sorted(handed) != sorted(want):
            die(f"{model} expects {want}, handed {sorted(handed) if isinstance(handed, dict) else type(handed).__name__}")
        try:
            theta = [float(handed[k]) for k in want]
        except (TypeError, ValueError) as e:
            die(f"KDT_CALIB_PARAMS non-numeric value: {e}")
        source = "handed (KDT_CALIB_PARAMS)"
    else:
        theta = [float(np.mean(pr[i])) for i in range(n)]
        source = "UNTUNED: mid-point of the model's own parRanges"
    for i, (v, (lo, hi)) in enumerate(zip(theta, pr)):
        if not math.isfinite(v) or not (lo <= v <= hi):
            die(f"x{i+1}={v} outside parRange [{lo},{hi}]")
    return want, theta, source


def _s0_args(model: str) -> list[str]:
    """KDT_MARRMOT_INITIAL_STORES: comma-separated initial store values (mm), one per store of the
    structure, handed to run_marrmot.py --s0. Empty = the KI's default (zeros). Fail-closed on count."""
    s = os.environ.get("KDT_MARRMOT_INITIAL_STORES", "").strip()
    if not s:
        return []
    try:
        vals = [float(v) for v in s.split(",")]
    except ValueError:
        die(f"KDT_MARRMOT_INITIAL_STORES not a comma list of numbers: {s!r}")
    if not all(math.isfinite(v) for v in vals):
        die("KDT_MARRMOT_INITIAL_STORES must be finite")
    m = re.search(r"_(\d+)s$", model)
    if m and int(m.group(1)) != len(vals):
        die(f"{model} has {m.group(1)} stores; KDT_MARRMOT_INITIAL_STORES handed {len(vals)}")
    if any(v < 0 for v in vals):
        die("KDT_MARRMOT_INITIAL_STORES must be >= 0")
    return ["--s0", json.dumps(vals)]


def _run_theta(model: str, theta: list[float], forcing: Path, wd: Path) -> pd.Series:
    """One real MARRMoT run over a checked forcing file; returns the daily sim series (mm/d).
    Fail-closed: run_marrmot.py must exit 0 AND report status=success in its run.json, and every
    simulated value must be finite (a solver failure must never shrink the scored sample)."""
    fc = _check_forcing(forcing)
    shutil.rmtree(wd, ignore_errors=True); wd.mkdir(parents=True)
    run_json = wd / "run.json"; ts_csv = wd / "marrmot_timeseries.csv"
    # Octave gets a CANONICAL copy written from the checked frame (plain unquoted numbers, %.10g), never
    # the raw file: Octave's csvread reads e.g. a quoted "3" as 0, so the raw file could differ from what
    # was checked and from the P used for yields. What is validated is exactly what is simulated.
    canon = wd / "forcing_checked.csv"
    out_fc = fc.copy(); out_fc["date"] = out_fc["date"].dt.strftime("%Y-%m-%d")
    out_fc.to_csv(canon, index=False, float_format="%.10g")
    r = subprocess.run([PE, f"{KI}/tools/run_marrmot.py", "--forcing", str(canon), "--model", model,
                        "--theta", json.dumps(theta), "--marrmot-path", MARRMOT_SRC,
                        "--output", str(run_json), "--timeout", "600"] + _s0_args(model), capture_output=True, text=True)
    if r.returncode != 0 or not ts_csv.exists() or not run_json.exists():
        die(f"run_marrmot failed rc={r.returncode}: {(r.stderr or r.stdout)[-400:]}")
    try:
        rj = json.loads(run_json.read_text())
    except ValueError as e:
        die(f"run_marrmot run.json unreadable: {e}")
    if rj.get("status") != "success" or rj.get("return_code", 0) != 0:
        die(f"run_marrmot reported status={rj.get('status')!r} rc={rj.get('return_code')}: {rj.get('errors')}")
    ts = pd.read_csv(ts_csv)
    if len(ts) != len(fc) or "Q_mm_d" not in ts.columns:
        die(f"timeseries length {len(ts)} != forcing {len(fc)} (or no Q_mm_d column)")
    q = pd.to_numeric(ts["Q_mm_d"], errors="coerce").to_numpy(dtype=float)
    bad = ~np.isfinite(q)
    if bad.any():
        die(f"simulated Q has {int(bad.sum())} non-finite days of {len(q)} (first {fc['date'][bad].iloc[0].date()}) — solver failure")
    return pd.Series(q, index=pd.DatetimeIndex(fc["date"]))


def _obs_mm() -> pd.Series:
    o = pd.read_csv(OBS, sep="\t"); o.columns = [c.strip() for c in o.columns]
    o["date"] = pd.to_datetime(o["dates"], format="mixed", errors="coerce"); o["Q"] = pd.to_numeric(o["Q"], errors="coerce")
    o = o[(o.Q >= 0) & o.date.notna()]
    if sorted({int(s) for s in o.stcd}) != [TARGET_STCD]:
        die("obs file is not the target gauge")
    return (o.set_index("date")["Q"] * 86400.0 / (AREA_KM2 * 1e3)).sort_index()



def _target_proof(series, split, window):
    """Shared kdt-target-proof/1 (ki_tools_common.kdt_proof) — one implementation for every KI.
    MARRMoT scores in mm/day (obs converted from m3/s by _obs_mm), so the proof declares mm/day."""
    import sys as _sys
    _sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
    from ki_tools_common.kdt_proof import target_proof
    return target_proof(series.to_numpy(), series.index, target="Q", unit="mm/day", split=split,
                        window=window, source="MARRMoT daily Q (mm/day), inner-joined to obs, scored window")

METRIC_KEYS = ("nse", "kge", "pbias", "r", "rmse")


def _paired(sim: pd.Series, obs: pd.Series, s0: str, s1: str) -> pd.DataFrame:
    """Score window frame. sim is already proven all-finite by _run_theta, so the only rows dropped
    here are days WITHOUT an observation (gauge gaps), never days where the model failed."""
    if not np.isfinite(sim.to_numpy(dtype=float)).all():
        die("non-finite simulated Q reached pairing")
    sim_w = sim.loc[s0:s1]
    want = pd.date_range(s0, s1, freq="D")
    missing = want.difference(sim_w.index)
    if len(missing):
        # the simulation must cover EVERY day of the declared score window (a truncated forcing file
        # would otherwise be scored on a few days but reported under the full window); obs gaps are allowed
        die(f"simulation covers {len(want) - len(missing)}/{len(want)} days of the score window {s0}..{s1} "
            f"(first missing {missing[0].date()}) — forcing too short")
    return pd.concat([obs.rename("obs"), sim_w.rename("sim")], axis=1, join="inner").dropna()


def _check_metrics(m: dict, where: str) -> dict:
    for k in METRIC_KEYS:
        v = m.get(k)
        if v is None or not math.isfinite(v):
            die(f"non-finite {k}={v} {where} (e.g. constant simulated Q) — no score published")
    return m


def _score_window(sim: pd.Series, obs: pd.Series, s0: str, s1: str, where: str) -> tuple[dict, pd.DataFrame]:
    paired = _paired(sim, obs, s0, s1)
    if len(paired) < 30:
        die(f"too few paired days {where}: {len(paired)}")
    m = {k.lower(): float(v) for k, v in all_metrics(paired["obs"].to_numpy(), paired["sim"].to_numpy()).items()}
    _check_metrics(m, where)
    m["n_paired_days"] = int(len(paired))
    return m, paired


def _score_year(sim: pd.Series, obs: pd.Series, y: str) -> tuple[dict, pd.DataFrame]:
    m, paired = _score_window(sim, obs, f"{y}-01-01", f"{y}-12-31", f"in {y}")
    m.update(peak_timing(paired["obs"], paired["sim"]))
    return m, paired


def peak_timing(obs: pd.Series, sim: pd.Series, window_days: int = 30) -> dict:
    """Robust flood-peak timing (reviewers 2026-08-30): the annual argmax of the simulation can be a
    DIFFERENT flood than the observed one (1991: 53 d, 2017: 88 d apart with NSE fine), which makes an
    annual-argmax timing term meaningless. day_bias = |day of the simulated maximum within ±window of
    the observed annual peak − observed peak day|, bounded by the window; the raw annual-argmax
    difference is kept as day_bias_annual_argmax for the record."""
    t_obs = obs.idxmax()
    lo, hi = t_obs - pd.Timedelta(days=window_days), t_obs + pd.Timedelta(days=window_days)
    win = sim.loc[lo:hi]
    t_sim = win.idxmax() if len(win) else sim.idxmax()
    return {"day_bias": float(abs((t_sim - t_obs).days)),
            "day_bias_annual_argmax": float(abs((sim.idxmax() - t_obs).days)),
            "peak_window_days": window_days, "obs_peak_date": str(t_obs.date())}


def _yields(m: dict, paired: pd.DataFrame, fc: pd.DataFrame) -> dict:
    """Q/P (declared yield-slope criterion). P comes from the SAME forcing file that was simulated
    (default era file or KDT_MARRMOT_FORCING_FILE) and is summed over exactly the scored paired days,
    so numerator and denominator cover the same period."""
    pser = fc.set_index("date")["P"]
    missing = paired.index.difference(pser.index)
    if len(missing):
        die(f"forcing lacks P on {len(missing)} scored days")
    P = float(pser.loc[paired.index].sum())
    if not (P > 0):
        die(f"P sum over scored days = {P} — yield undefined")
    m["P_mm"] = P; m["yield_period_days"] = int(len(paired))
    m["yield_obs"] = float(paired["obs"].sum() / P); m["yield_sim"] = float(paired["sim"].sum() / P)
    return m


def _write_out(out: Path, res: dict) -> None:
    tmp = out.with_suffix(out.suffix + f".partial.{os.getpid()}")
    try:
        txt = json.dumps(res, indent=2, ensure_ascii=False, allow_nan=False)   # strict JSON: no NaN/Infinity
    except ValueError as e:
        die(f"result holds a non-finite number, not published: {e}")
    tmp.write_text(txt); os.replace(tmp, out)


def _era_of(y: int) -> str:
    era = next((e for e, (lo, hi) in ERAS.items() if lo < y <= hi), None)
    if era is None:
        die(f"year {y}: no era with >=1 spin-up year")
    return era


def main_multi(a, model: str, pr, n: int, years: list[str], split: str) -> int:
    """Score the declared year set jointly (one run per era, every year scored)."""
    out = Path(a.out)
    want, theta, theta_source = _load_theta(model, pr, n)
    t0 = time.time(); obs = _obs_mm(); per = {}
    eras = sorted({_era_of(int(y)) for y in years})
    ov = _forcing_override()
    if ov is not None and len(eras) > 1:
        die(f"KDT_MARRMOT_FORCING_FILE is one file but the declared years span eras {eras}")
    forcings = {era: (ov or BASIN / "forcing" / f"forcing_{era}.csv") for era in eras}
    sims = {era: _run_theta(model, theta, forcings[era], Path(a.workdir).resolve() / "run" / era) for era in eras}
    fcs = {era: _check_forcing(forcings[era]) for era in eras}
    _scored_series = []   # kdt-target-proof/1 accumulator: exactly the frames that were scored
    for y in years:
        era = _era_of(int(y))
        m, paired = _score_year(sims[era], obs, y)
        per[y] = _yields(m, paired, fcs[era])
        _scored_series.append(paired["sim"])
    agg = {"nse": float(np.mean([per[y]["nse"] for y in years])),
           "pbias": float(np.mean([abs(per[y]["pbias"]) for y in years])),        # magnitude family reads |pbias|
           "pbias_signed_mean": float(np.mean([per[y]["pbias"] for y in years])),
           "day_bias": float(np.mean([per[y]["day_bias"] for y in years])),
           "kge": float(np.mean([per[y]["kge"] for y in years])), "r": float(np.mean([per[y]["r"] for y in years])),
           "rmse": float(np.mean([per[y]["rmse"] for y in years]))}
    _check_metrics(agg, "in the aggregate")
    res = {**agg, "__kdt__": {"applied_params": dict(zip(want, theta)), "model": model, "case_id": CASE_ID,
                              "theta_source": theta_source,
                              "scored_obs": f"china_gaugeflux:{TARGET_STCD} @ {OBS}", "area_km2": AREA_KM2,
                              "split": split, "years": years, "per_year": per, "aggregation": "mean over declared years",
                              "n_paired_days": int(sum(per[y]["n_paired_days"] for y in years)),
                              "forcing_eras": eras, "forcing": {e: str(f) for e, f in forcings.items()},
                              "wallclock_s": round(time.time() - t0, 2),
                              # kdt-target-proof/1 (2026-09-15): the RAW scored series over the declared years
                              "target_proofs": [_target_proof(pd.concat(_scored_series), split,
                                                              (f"{years[0]}-01-01", f"{years[-1]}-12-31"))]}}
    if os.environ.get("KDT_VIC_KEEP_WORKDIR") == "1" or os.environ.get("KDT_MARRMOT_KEEP_WORKDIR") == "1":
        for era, s in sims.items():
            pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "q_m3s": s.values * AREA_KM2 * 1e3 / 86400.0}).to_csv(
                Path(a.workdir).resolve() / "run" / f"sim_daily_{era}.csv", index=False)
    else:
        shutil.rmtree(Path(a.workdir).resolve() / "run", ignore_errors=True)
    _write_out(out, res)
    print(f"[marrmot] {model} split={split} years={len(years)} mean nse={agg['nse']:.4f} mean|pbias|={agg['pbias']:.2f}% "
          f"day_bias={agg['day_bias']:.1f} ({res['__kdt__']['wallclock_s']}s)", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--workdir", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    try:
        out.unlink()
    except FileNotFoundError:
        pass
    model = os.environ.get("SYS1_MARRMOT_MODEL", "").strip()
    if not model:
        die("SYS1_MARRMOT_MODEL not set")
    pr = par_ranges(model); n = len(pr)
    sha = hashlib.sha1(OBS.read_bytes()).hexdigest()
    if not OBS_PIN.exists() or sha != OBS_PIN.read_text().strip():
        die(f"obs sha1 {sha[:12]} != pin — re-declare")
    split = os.environ.get("KDT_CALIB_SPLIT", "") or "_both"
    # DECLARED YEAR SETS (System 1 holdout v2, 2026-08-30): with KDT_CALIB_SPLIT=calibration|holdout the
    # driver scores EVERY year of the declared set (env KDT_CALIB_SPLIT_SETS, JSON from the contract's
    # strategy.holdout) and returns aggregated metrics — nse = mean NSE, pbias = mean |PBIAS| (signed mean
    # kept as pbias_signed_mean), day_bias = mean |peak-day error| — plus per-year detail in __kdt__.
    # This is what lets the calibration kit fit the composite objective and gate the sealed holdout natively.
    sets = json.loads(os.environ.get("KDT_CALIB_SPLIT_SETS", "{}") or "{}")
    if split in ("calibration", "holdout"):
        years = [str(y) for y in (sets.get(split) or [])]
        if not years:
            die(f"KDT_CALIB_SPLIT={split} but KDT_CALIB_SPLIT_SETS declares no years for it")
        return main_multi(a, model, pr, n, years, split)
    if split == "_both":
        era = "2000_2018"; s0, s1 = "2001-01-01", "2018-12-31"; year = None
    else:
        try:
            year = int(split)
        except ValueError:
            die(f"KDT_CALIB_SPLIT={split!r}: want a year, 'calibration', 'holdout' or '_both'")
        era = _era_of(year)
        s0, s1 = f"{year}-01-01", f"{year}-12-31"
    forcing = _forcing_override() or BASIN / "forcing" / f"forcing_{era}.csv"
    if not forcing.exists():
        die(f"forcing missing: {forcing} (run w4_lumped/build_huaibin_marrmot_forcing.py)")
    want, theta, theta_source = _load_theta(model, pr, n)

    wd = Path(a.workdir).resolve() / "run"
    t0 = time.time()
    sim = _run_theta(model, theta, forcing, wd)
    obs = _obs_mm()
    if year is not None:
        # a single calendar year: same scoring as the named-set branch, incl. the timing metric (day_bias)
        m, paired = _score_year(sim, obs, str(year))
        _yields(m, paired, _check_forcing(forcing))
    else:
        # _both = the whole multi-year era as one series; an annual-peak timing term is not defined for it
        # (use KDT_CALIB_SPLIT=calibration|holdout for per-year day_bias)
        m, paired = _score_window(sim, obs, s0, s1, f"on {s0}..{s1}")
    res = {k: m[k] for k in METRIC_KEYS}
    if year is not None:
        res["day_bias"] = m["day_bias"]
    res["__kdt__"] = {"applied_params": dict(zip(want, theta)), "model": model, "case_id": CASE_ID,
                      "theta_source": theta_source,
                      "scored_obs": f"china_gaugeflux:{TARGET_STCD} @ {OBS}", "area_km2": AREA_KM2,
                      "target_proofs": [_target_proof(paired["sim"], split, (s0, s1))],
                      "split": split, "score_period": [s0, s1], "n_paired_days": int(len(paired)),
                      "metrics_detail": m,
                      "forcing": str(forcing), "wallclock_s": round(time.time() - t0, 2)}
    if os.environ.get("KDT_VIC_KEEP_WORKDIR") == "1" or os.environ.get("KDT_MARRMOT_KEEP_WORKDIR") == "1":
        pd.DataFrame({"date": sim.index.strftime("%Y-%m-%d"), "q_m3s": sim.values * AREA_KM2 * 1e3 / 86400.0}).to_csv(wd / "sim_daily.csv", index=False)
    else:
        shutil.rmtree(wd, ignore_errors=True)
    _write_out(out, res)
    tb = f" day_bias={m['day_bias']:.0f}" if year is not None else ""
    print(f"[marrmot] {model} split={split} n={len(paired)} nse={m['nse']:.4f} pbias={m['pbias']:+.2f}%{tb} ({res['__kdt__']['wallclock_s']}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
