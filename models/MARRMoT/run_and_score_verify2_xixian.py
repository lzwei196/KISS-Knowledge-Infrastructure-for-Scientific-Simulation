#!/usr/bin/env python3
"""MARRMoT VERIFIER @ 息县 Xixian -- china_gaugeflux stcd 50225601,
upper Huai River (淮河), Henan, China (32.3428 N, 114.7350 E), 10,190 km2.

Consistency run for the 唐乃亥 Tangnaihai Real-case (upper Yellow River,
121,972 km2, cold 3,700 m plateau). Xixian is deliberately the OPPOSITE
hydroclimate -- a humid subtropical monsoon lowland-hill catchment, an order of
magnitude smaller -- so this tests whether the KI transfers across regimes
rather than re-testing a plateau twin.

IDENTICAL protocol to the Real-case and to verifier location 1 (Caravan
GRDC_3275140), so all three are strictly comparable:

  * ALL 47 shipped MARRMoT structures calibrated with the KI tool
    run_marrmot.py --calibrate --optimizer cmaes --of-name of_NSE, 6 IPOP
    restarts, per-structure eval budget 250*np clamped 800..4000, same
    14,400 s per-structure wall clock (partial-safe via the kdt_of_persist
    incremental-persistence shim);
  * winner selected by HELD-OUT validation NSE (same rule);
  * headline metric = one ki_tools_common.metrics.all_metrics call on the
    winner's held-out validation series;
  * the Real-case winner m_29_hymod_5p_5s is reported explicitly alongside.

Forcing (same recipe as the Real-case, which is China/CMFD too):
  ki_tools_common.load_forcing.load_daily_forcing('cmfd', <basin cells>) in
  AREAL (cos-weighted basin-mean) mode over the HydroBASINS lev07 upstream
  union above the gauge -> intermediate CSV -> KI tools/convert_forcing.py
  --format csv --pet-method priestley_taylor (dt_019: CMFD daily carries one
  slice per day so Tmin==Tmax and Hargreaves collapses to 0; --pres-col is
  always passed so gamma is not inflated by the sea-level fallback).

Obs: china_gaugeflux tab-separated station file (stcd, dates, z, Q, name),
Q in m3/s, -99 = missing, converted to mm/d over the PUBLISHED gauged area
(dt_010). The published area -- not the delineated one -- drives the unit
conversion; the delineated polygon is used only to average the forcing.

Period 1978-01-01..2018-12-31 (CMFD covers 1951-2024):
  1978-1979               spin-up      (excluded from the objective)
  1980-01-01..1989-12-31  calibration
  2005-01-01..2018-12-31  validation   (HELD OUT, 15-year gap from cal)
Obs are absent 1998-2001 and 2004; MARRMoT's check_and_select drops NaN /
negative obs natively, so no masking is needed.

ALL INPUTS ARE LOCAL (CMFD on KISSPATH_DATA, obs on KISSPATH_DATA,
HydroBASINS on KISSPATH_ROOT) -- the runner performs NO network fetch, and
nothing is read from the exfat disk KISSPATH_DATA.

RESUMABLE at every stage: basin cells, each CMFD year, forcing, obs, and each
structure's best_theta.json / timeseries / summary json are all skipped if
already present. A calibration whose subprocess never returned leaves no
cal_done marker and its incumbent is discarded and re-searched (an
under-searched incumbent must not masquerade as a converged one).
"""
import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
MARRMOT_SRC = "KISSPATH_KI_ROOT/MARRMoT/source/repo/MARRMoT"
MODEL_DIR = os.path.join(MARRMOT_SRC, "Models", "Model files")
STATE = ("KISSPATH_KI_ROOT/MARRMoT/detached/"
         "verify_2_c4037a0135114a14a2807548fbc73766")
VALIDATORS = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"
CMFD_DIR = "KISSPATH_FORCING/Data_forcing_01dy_010deg"
HYBAS = ("KISSPATH_DATA/awd_paper/hydrobasins/asia/"
         "hybas_as_lev07_v1c.shp")
OBS_TXT = "KISSPATH_DATA/china_water_level/淮河txt/息县.txt"

STCD = "50225601"
GAUGE_NAME = "息县 Xixian, upper Huai River (淮河), Henan, China"
GAUGE_LAT, GAUGE_LON = 32.3428, 114.7350
AREA_KM2 = 10190.0            # published gauged area of Xixian on the Huai

START_Y, END_Y = 1978, 2018
WIN = ("1978-01-01", "2018-12-31")
CAL = ("1980-01-01", "1989-12-31")
VAL = ("2005-01-01", "2018-12-31")
REALCASE_MODEL = "m_29_hymod_5p_5s"

CAL_TIMEOUT = 14400        # 4 h wall clock per structure (partial-safe)
RUN_TIMEOUT = 3600
MAX_WORKERS = 32
RESTARTS = 6

PY = sys.executable or "/usr/bin/python3"
os.makedirs(STATE, exist_ok=True)
# KTC (the canonical ki_tools_common) must win the import race: VALIDATORS
# carries a stale vendored copy whose _load_cmfd has no AREAL (basin-mean) mode.
sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics                    # noqa: E402
from ki_tools_common.validation import validate_water_balance      # noqa: E402

import importlib.util as _ilu                                      # noqa: E402
_spec = _ilu.spec_from_file_location(
    "kdt_standard_calval", os.path.join(VALIDATORS, "validators", "standard_calval.py"))
_scv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_scv)
compute_calval_metrics = _scv.compute_calval_metrics

CELLS = os.path.join(STATE, "basin_cells.csv")
CMFD_CSV = os.path.join(STATE, "cmfd_daily.csv")
FORCING = os.path.join(STATE, "forcing.csv")
OBS_CSV = os.path.join(STATE, "obs_q.csv")
PREFLIGHT = os.path.join(STATE, "preflight.json")
AVAIL = os.path.join(STATE, "input_availability.json")
RESULT = os.path.join(STATE, "result.json")
SUMDIR = os.path.join(STATE, "per_structure")
os.makedirs(SUMDIR, exist_ok=True)

_lock = threading.Lock()
tools_used, tools_failed = set(), []
log = lambda *a: print(*a, flush=True)


def structures():
    """The 47 shipped structures, most-expensive-first (cost ~ numStores)."""
    out = []
    for fn in sorted(os.listdir(MODEL_DIR)):
        if not fn.endswith(".m"):
            continue
        m = re.match(r"(m_\d+)_(.+)_(\d+)p_(\d+)s$", fn[:-2])
        if m:
            out.append(dict(mid=m.group(1), name=m.group(2), np=int(m.group(3)),
                            ns=int(m.group(4)), model=fn[:-2]))
    out.sort(key=lambda d: (-d["ns"], -d["np"], d["mid"]))
    return out


# ---------------------------------------------------------------- stage 0
def stage_availability():
    """Every input is LOCAL, so availability is a pure existence check."""
    req = {"cmfd_daily_dir": CMFD_DIR, "hydrobasins_lev07": HYBAS,
           "china_gaugeflux_station_file": OBS_TXT, "marrmot_source": MARRMOT_SRC,
           "marrmot_model_dir": MODEL_DIR, "ki_tools_common": KTC}
    missing = [k for k, v in req.items() if not os.path.exists(v)]
    # the specific CMFD variable-years this run reads
    for var in ("prec", "temp", "srad", "lrad", "pres", "wind", "shum"):
        for yr in (START_Y, END_Y):
            f = os.path.join(CMFD_DIR,
                             f"{var}_CMFD_V0200_B-01_01dy_010deg_{yr}01-{yr}12.nc")
            if not os.path.exists(f):
                missing.append(f"cmfd_{var}_{yr}")
    res = {"all_required_reachable": not missing, "unreachable_required": missing,
           "unreachable_optional": [], "degraded_mode": None,
           "note": "every input is on local disk (CMFD on hc_ssd, obs on "
                   "KISSPATH_DATA, HydroBASINS on KISSPATH_ROOT); the runner "
                   "performs no network fetch and reads nothing from exfat "
                   "KISSPATH_DATA"}
    json.dump(res, open(AVAIL, "w"), indent=2)
    return res


# ---------------------------------------------------------------- stage 1
def stage_cells():
    """Upstream HydroBASINS lev07 union above the gauge -> CMFD 0.1deg cells."""
    if os.path.exists(CELLS):
        df = pd.read_csv(CELLS)
        log(f"[resume] basin cells: {len(df)}")
        return df
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.prepared import prep

    g = gpd.read_file(HYBAS, bbox=(112, 30, 117, 35))
    pt = Point(GAUGE_LON, GAUGE_LAT)
    hit = g[g.contains(pt)]
    if hit.empty:
        hit = g.iloc[[g.distance(pt).idxmin()]]
    seed = int(hit.iloc[0].HYBAS_ID)
    nxt = {}
    for _, r in g.iterrows():
        nxt.setdefault(int(r.NEXT_DOWN), []).append(int(r.HYBAS_ID))
    ups, stack = {seed}, [seed]
    while stack:
        c = stack.pop()
        for u in nxt.get(c, []):
            if u not in ups:
                ups.add(u)
                stack.append(u)
    sub = g[g.HYBAS_ID.isin(ups)]
    basin = sub.union_all()
    delin = float(sub.SUB_AREA.sum())
    log(f"basin: {len(ups)} lev07 units, HydroBASINS area {delin:.0f} km2 "
        f"(published gauged {AREA_KM2:.0f} km2, "
        f"{100 * (delin - AREA_KM2) / AREA_KM2:+.1f}%)")

    pb = prep(basin)
    x0, y0, x1, y1 = basin.bounds
    lats = np.round(np.arange(15.05, 55.0, 0.1), 2)   # CMFD 0.1deg cell centres
    lons = np.round(np.arange(70.05, 140.0, 0.1), 2)
    lats = lats[(lats >= y0 - 0.1) & (lats <= y1 + 0.1)]
    lons = lons[(lons >= x0 - 0.1) & (lons <= x1 + 0.1)]
    rows = [(float(la), float(lo)) for la in lats for lo in lons
            if pb.contains(Point(lo, la))]
    df = pd.DataFrame(rows, columns=["lat", "lon"])
    df.attrs["delineated_area_km2"] = delin
    df.to_csv(CELLS, index=False)
    json.dump({"delineated_area_km2": delin, "n_lev07_units": len(ups),
               "n_cells": len(df), "seed_hybas_id": seed},
              open(os.path.join(STATE, "basin_meta.json"), "w"), indent=2)
    log(f"basin cells: {len(df)} CMFD 0.1deg cells (~{len(df) * 100} km2)")
    return df


# ---------------------------------------------------------------- stage 2
def stage_cmfd(cells):
    """Basin-mean daily CMFD via load_forcing AREAL mode. Cached per year."""
    tools_used.add("ki_tools_common.load_forcing.load_daily_forcing")
    if os.path.exists(CMFD_CSV):
        log("[resume] cmfd_daily.csv present")
        return
    from ki_tools_common.load_forcing import load_daily_forcing
    la, lo = cells.lat.tolist(), cells.lon.tolist()
    parts = []
    for yr in range(START_Y, END_Y + 1):
        cache = os.path.join(STATE, f"cmfd_{yr}.csv")
        if not os.path.exists(cache):
            d = load_daily_forcing("cmfd", la, lo, yr, yr, forcing_dir=CMFD_DIR)
            tmp = cache + ".part"
            pd.DataFrame({
                "date": pd.to_datetime(d["dates"]).strftime("%Y-%m-%d"),
                "precip_mm_d": np.asarray(d["precip_mm"], float),
                "temp_c": np.asarray(d["temp_mean_c"], float),
                "srad_wm2": np.asarray(d["srad_wm2"], float),
                "lrad_wm2": np.asarray(d["lrad_wm2"], float),
                "pres_pa": np.asarray(d["pres_pa"], float),
                "wind_ms": np.asarray(d["wind_ms"], float),
                "shum_kgkg": np.asarray(d["shum_kgkg"], float),
            }).to_csv(tmp, index=False)
            os.replace(tmp, cache)          # never leave a half-written year
            log(f"  CMFD {yr} done")
        parts.append(pd.read_csv(cache))
    df = pd.concat(parts).sort_values("date").drop_duplicates("date")
    df.to_csv(CMFD_CSV, index=False)
    log(f"CMFD basin-mean: {len(df)} days, P={df.precip_mm_d.mean():.2f} mm/d, "
        f"T={df.temp_c.mean():.2f} C")


# ---------------------------------------------------------------- stage 3
def forcing_is_current():
    """Resume only on a forcing.csv actually built for THIS gauge/window.

    Scoring this gauge's obs against another basin's cached forcing would be a
    silent, catastrophic error, so the header Period stamp is checked before
    the stage is skipped.
    """
    if not os.path.exists(FORCING):
        return False
    want = f"# Period: {WIN[0]} to {WIN[1]}"
    with open(FORCING) as fh:
        head = [next(fh, "") for _ in range(6)]
    if not any(line.strip() == want for line in head):
        log(f"[stale] forcing.csv is not {want!r} -- rebuilding")
        return False
    return True


def stage_forcing(cells):
    tools_used.add("convert_forcing.py")
    if forcing_is_current():
        log("[resume] forcing.csv already present for this gauge/window")
        return
    clat = float(cells.lat.mean())
    r = subprocess.run(
        [PY, os.path.join(KI, "tools/convert_forcing.py"),
         "--format", "csv", "--input", CMFD_CSV,
         "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
         "--pet-method", "priestley_taylor",
         "--srad-col", "srad_wm2", "--lrad-col", "lrad_wm2",
         "--pres-col", "pres_pa", "--lat", str(clat),
         "--start", WIN[0], "--end", WIN[1],
         "--output", FORCING], capture_output=True, text=True)
    log(r.stdout[-2000:])
    if r.returncode != 0 or not os.path.exists(FORCING):
        tools_failed.append(f"convert_forcing.py: {r.stderr[-500:]}")
        raise SystemExit("convert_forcing failed")


# ---------------------------------------------------------------- stage 4
def stage_obs():
    """china_gaugeflux station txt -> mm/d aligned 1:1 to the forcing dates."""
    fc = pd.read_csv(FORCING, comment="#")
    fc["date"] = pd.to_datetime(fc["date"])
    if os.path.exists(OBS_CSV) and len(pd.read_csv(OBS_CSV)) == len(fc):
        log("[resume] obs_q.csv present and aligned")
        return
    raw = pd.read_csv(OBS_TXT, sep="\t")
    raw["date"] = pd.to_datetime(raw["dates"], errors="coerce")
    q = pd.to_numeric(raw["Q"], errors="coerce")
    q[q <= -99] = np.nan            # china_gaugeflux missing sentinel
    q[q < 0] = np.nan
    # dt_010: m3/s -> mm/d over the PUBLISHED gauged area
    raw["Q_mm_d"] = q * 86400.0 / (AREA_KM2 * 1e6) * 1000.0
    raw = raw.dropna(subset=["date"]).drop_duplicates("date")
    aligned = raw.set_index("date")["Q_mm_d"].reindex(fc["date"])
    pd.DataFrame({"date": fc["date"].dt.strftime("%Y-%m-%d"),
                  "Q_mm_d": aligned.values}).to_csv(OBS_CSV, index=False)
    log(f"obs: {int(np.isfinite(aligned.values).sum())} finite of {len(aligned)} "
        f"days; mean {np.nanmean(aligned.values):.3f} mm/d")


# ---------------------------------------------------------------- stage 5
def stage_preflight(fc, obs):
    """Raw-source CMFD preflight PLUS the derived-forcing checks.

    validators/preflight_forcing.py cannot autodetect a MARRMoT [P, Ep, T]
    forcing.csv (dt_018), so it is pointed at the RAW CMFD directory; the unit
    traps (dt_001/002/003/006) and the dt_019 closability test
    Ep_annual >= (P - Q)_annual are then applied to the prepared forcing.
    """
    if os.path.exists(PREFLIGHT):
        return json.load(open(PREFLIGHT))
    tools_used.add("preflight_forcing.py")
    r = subprocess.run(
        [PY, os.path.join(VALIDATORS, "validators/preflight_forcing.py"),
         CMFD_DIR, "--source", "cmfd", "--year", "1985"],
        capture_output=True, text=True)
    log(r.stdout[-2500:])
    fails, warns = [], []
    for ln in r.stdout.splitlines():
        s = ln.strip()
        if s.startswith("[FAIL]"):
            fails.append("raw CMFD " + s)
        elif s.startswith("[WARN]"):
            warns.append("raw CMFD " + s)

    P, Ep, T = fc["P_mm_d"].values, fc["Ep_mm_d"].values, fc["T_degC"].values
    Q = np.asarray(obs, float)
    P_yr, Ep_yr = np.nanmean(P) * 365.25, np.nanmean(Ep) * 365.25
    Q_yr = np.nanmean(Q) * 365.25
    if not np.isfinite(P).all() or P.min() < 0 or P.max() > 500:
        fails.append(f"[FAIL] P out of plausible mm/d range: "
                     f"min={np.nanmin(P):.3f} max={np.nanmax(P):.3f}")
    if not np.isfinite(Ep).all() or Ep.min() < 0 or Ep.max() > 30:
        fails.append(f"[FAIL] Ep out of plausible mm/d range: "
                     f"min={np.nanmin(Ep):.3f} max={np.nanmax(Ep):.3f}")
    if not np.isfinite(T).all() or T.min() < -80 or T.max() > 60:
        fails.append(f"[FAIL] T out of plausible degC range (Kelvin? dt_006): "
                     f"min={np.nanmin(T):.2f} max={np.nanmax(T):.2f}")
    if np.nanmin(Q) < 0:
        fails.append("[FAIL] observed Q has negative values")
    if Ep_yr <= (P_yr - Q_yr):
        fails.append(f"[FAIL] dt_019: Ep ({Ep_yr:.0f}) <= required Ea "
                     f"({P_yr - Q_yr:.0f}) mm/yr -- balance not closable by ET")
    if Q_yr > P_yr:
        warns.append(f"[WARN] Qobs ({Q_yr:.0f}) > P ({P_yr:.0f}) mm/yr")
    res = {"all_pass": not fails,
           "source": "CMFD daily 0.1deg basin-mean (AREAL) + Priestley-Taylor PET; "
                     "obs china_gaugeflux stcd " + STCD,
           "failures": fails, "warnings": warns[:12],
           "climatology_mm_per_yr": {"P": round(float(P_yr), 1),
                                     "Ep": round(float(Ep_yr), 1),
                                     "Q_obs": round(float(Q_yr), 1),
                                     "required_Ea": round(float(P_yr - Q_yr), 1)}}
    json.dump(res, open(PREFLIGHT, "w"), indent=2)
    return res


# ---------------------------------------------------------------- per structure
def cal_indices(dates):
    i0 = int(np.argmax(dates.values >= np.datetime64(CAL[0]))) + 1   # 1-based Octave
    i1 = int(np.sum(dates.values <= np.datetime64(CAL[1])))
    return i0, i1


def _err_tail(err, n=1400):
    """Keep the actual Octave error line, not just the bottom of the stack."""
    err = err or ""
    for key in ("error:", "Error:"):
        i = err.find(key)
        if i >= 0:
            return err[i:i + n]
    return err[-n:]


def do_structure(st, i0, i1, dates, obs):
    """Calibrate + forward-run + score ONE structure. Never raises; a structure
    that cannot run for this basin returns status='skipped' with the reason."""
    label = st["model"]
    summary = os.path.join(SUMDIR, f"{label}.json")
    if os.path.exists(summary):
        try:
            return json.load(open(summary))
        except (json.JSONDecodeError, OSError):
            pass

    rec = dict(st, status="skipped", reason=None, partial=False)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1")

    wd = os.path.join(STATE, f"cal_{label}")
    os.makedirs(wd, exist_ok=True)
    best_json = os.path.join(wd, "best_theta.json")
    done_marker = os.path.join(wd, "cal_done.json")
    # best_theta.json is rewritten on EVERY improvement (kdt_of_persist shim),
    # so its presence alone does not mean the search finished. Only trust it
    # when the calibration subprocess actually returned.
    if os.path.exists(best_json) and not os.path.exists(done_marker):
        os.unlink(best_json)
    if not os.path.exists(best_json):
        budget = int(min(4000, max(800, 250 * st["np"])))
        cmd = [PY, os.path.join(KI, "tools/run_marrmot.py"),
               "--forcing", FORCING, "--observed", OBS_CSV, "--model", label,
               "--calibrate", "--optimizer", "cmaes", "--of-name", "of_NSE",
               "--restarts", str(RESTARTS), "--max-fun-evals", str(budget),
               "--cal-start", str(i0), "--cal-end", str(i1),
               "--marrmot-path", MARRMOT_SRC,
               "--output", os.path.join(wd, "calib.json"),
               "--timeout", str(CAL_TIMEOUT)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=CAL_TIMEOUT + 900, env=env)
            rec["cal_stderr_tail"] = _err_tail(r.stderr)
        except subprocess.TimeoutExpired:
            rec["cal_stderr_tail"] = "outer wall-clock cap hit"
        json.dump({"budget": budget,
                   "stderr_tail": rec.get("cal_stderr_tail", "")[-600:]},
                  open(done_marker, "w"), indent=2)
    if not os.path.exists(best_json):
        rec["reason"] = ("calibration produced no theta: " +
                         str(rec.get("cal_stderr_tail"))[-260:])
        json.dump(rec, open(summary, "w"), indent=2)
        log(f"[{label}] SKIP - {rec['reason'][:110]}")
        return rec
    bt = json.load(open(best_json))
    rec["theta"] = bt.get("theta")
    rec["cal_of"] = bt.get("cal_of")
    rec["partial"] = bool(bt.get("partial"))   # hit the wall clock

    rwd = os.path.join(STATE, f"run_{label}")
    os.makedirs(rwd, exist_ok=True)
    ts_csv = os.path.join(rwd, "marrmot_timeseries.csv")
    run_json = os.path.join(rwd, "run.json")
    if not os.path.exists(ts_csv):
        try:
            r = subprocess.run(
                [PY, os.path.join(KI, "tools/run_marrmot.py"),
                 "--forcing", FORCING, "--model", label,
                 "--theta", json.dumps(bt["theta"]),
                 "--marrmot-path", MARRMOT_SRC, "--output", run_json,
                 "--timeout", str(RUN_TIMEOUT)],
                capture_output=True, text=True, timeout=RUN_TIMEOUT + 600, env=env)
            rec["run_stderr_tail"] = _err_tail(r.stderr)
        except subprocess.TimeoutExpired:
            rec["run_stderr_tail"] = "forward run wall-clock cap hit"
    if not os.path.exists(ts_csv):
        rec["reason"] = ("forward run produced no timeseries: " +
                         str(rec.get("run_stderr_tail"))[-260:])
        json.dump(rec, open(summary, "w"), indent=2)
        log(f"[{label}] SKIP - {rec['reason'][:110]}")
        return rec

    ts = pd.read_csv(ts_csv)
    if "Q_mm_d" not in ts.columns or len(ts) == 0:
        rec["reason"] = "forward run timeseries has no Q_mm_d column"
        json.dump(rec, open(summary, "w"), indent=2)
        return rec
    sim = ts["Q_mm_d"].values
    n = min(len(sim), len(obs), len(dates))
    if not np.isfinite(sim[:n]).any():
        rec["reason"] = "simulated Q is entirely non-finite (solver failure)"
        json.dump(rec, open(summary, "w"), indent=2)
        log(f"[{label}] SKIP - non-finite Q")
        return rec

    m = compute_calval_metrics(dates.values[:n], obs[:n], sim[:n],
                               cal_start=CAL[0], cal_end=CAL[1],
                               val_start=VAL[0], val_end=VAL[1])
    g = lambda d, k: (round(float(d[k]), 4)
                      if d.get(k) is not None and np.isfinite(d[k]) else None)
    rec.update(status="completed", reason=None, ts_csv=ts_csv,
               nse_cal=g(m["calibration"], "NSE"), kge_cal=g(m["calibration"], "KGE"),
               nse_val=g(m["validation"], "NSE"), kge_val=g(m["validation"], "KGE"),
               pbias_val=g(m["validation"], "PBIAS"), r_val=g(m["validation"], "r"))
    json.dump(rec, open(summary, "w"), indent=2)
    log(f"[{label}] ns={st['ns']} np={st['np']} cal_NSE={rec['nse_cal']} "
        f"val_NSE={rec['nse_val']} pbias_val={rec['pbias_val']}"
        f"{' [budget-limited]' if rec['partial'] else ''}")
    return rec


def water_balance_of(ts, fc, dates, n):
    win = ((dates.values[:n] >= np.datetime64(CAL[0])) &
           (dates.values[:n] <= np.datetime64(VAL[1])))
    P = fc["P_mm_d"].values[:n][win]
    ET = ts["Ea_mm_d"].values[:n][win]
    Q = ts["Q_mm_d"].values[:n][win]
    Scols = [c for c in ts.columns if c.startswith("S") and c[1:].isdigit()]
    Stot = ts[Scols].sum(axis=1).values[:n]
    idx = np.where(win)[0]
    dS = float(Stot[idx[-1]] - Stot[idx[0]])
    return validate_water_balance(precip_mm=float(P.sum()), et_mm=float(ET.sum()),
                                  runoff_mm=float(Q.sum()), delta_storage_mm=dS,
                                  period_days=int(win.sum()))


LOC = (f"{GAUGE_NAME} -- china_gaugeflux stcd {STCD} "
       f"({GAUGE_LAT}, {GAUGE_LON}), gauged area {AREA_KM2:.0f} km2")


def bail(status, notes, **extra):
    out = {"model_id": "MARRMoT", "this_location": LOC,
           "obs_source": "china_gaugeflux",
           "status": status, "tools_used": sorted(tools_used),
           "tools_failed": tools_failed,
           "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                       "period": None},
           "water_balance": {"status": "N/A", "residual_pct": None},
           "notes": notes}
    out.update(extra)
    json.dump(out, open(RESULT, "w"), indent=2, ensure_ascii=False)
    log("BAIL: " + notes)


# ---------------------------------------------------------------- main
def main():
    avail = stage_availability()
    if not avail["all_required_reachable"]:
        bail("failed", "required local inputs missing -- did not launch: "
             + ", ".join(avail["unreachable_required"]),
             input_availability=avail)
        return

    cells = stage_cells()
    stage_cmfd(cells)
    stage_forcing(cells)
    stage_obs()

    fc = pd.read_csv(FORCING, comment="#")
    dates = pd.to_datetime(fc["date"])
    obs = pd.read_csv(OBS_CSV)["Q_mm_d"].values
    if len(obs) != len(fc):
        bail("failed", f"forcing/obs length mismatch {len(fc)} vs {len(obs)}",
             input_availability=avail)
        return

    pf = stage_preflight(fc, obs)
    if pf["failures"]:
        bail("failed", "forcing preflight FAIL -- stopped before model run: "
             + "; ".join(pf["failures"]),
             forcing_preflight=pf, input_availability=avail)
        return

    i0, i1 = cal_indices(dates)
    sts = structures()
    log(f"{len(sts)} structures; cal idx {i0}..{i1} ({CAL[0]}..{CAL[1]}); "
        f"held-out {VAL[0]}..{VAL[1]}; {MAX_WORKERS} workers, "
        f"{CAL_TIMEOUT}s cap each; n_forcing={len(fc)}")
    log(f"climatology {pf['climatology_mm_per_yr']}")

    recs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(do_structure, st, i0, i1, dates, obs) for st in sts]
        for f in futs:
            try:
                recs.append(f.result())
            except Exception as e:                      # never lose the campaign
                log(f"structure worker crashed: {e}")

    done = [r for r in recs if r.get("status") == "completed"
            and r.get("nse_val") is not None]
    skipped = [r for r in recs if r.get("status") != "completed"
               or r.get("nse_val") is None]
    if not done:
        bail("failed", "no structure produced a scoreable held-out series",
             forcing_preflight=pf, input_availability=avail,
             skipped_structures=[{"model_structure": r.get("model"),
                                  "reason": r.get("reason")} for r in skipped])
        return

    # ---- winner = best HELD-OUT validation NSE (same rule as the Real-case) --
    done.sort(key=lambda r: r["nse_val"], reverse=True)
    W = done[0]
    ts = pd.read_csv(W["ts_csv"])
    sim = ts["Q_mm_d"].values
    n = min(len(sim), len(obs), len(dates))

    vmask = ((dates.values[:n] >= np.datetime64(VAL[0])) &
             (dates.values[:n] <= np.datetime64(VAL[1])) &
             np.isfinite(obs[:n]) & np.isfinite(sim[:n]))
    vd, vo, vs = dates.values[:n][vmask], obs[:n][vmask], sim[:n][vmask]
    if vmask.sum() < 30:
        bail("failed", f"held-out window has only {int(vmask.sum())} paired days",
             forcing_preflight=pf, input_availability=avail)
        return

    # ---- THE single headline call: winner's HELD-OUT validation series ------
    head = all_metrics(vo, vs, dates=vd, label="headline")
    gv = lambda k: (round(float(head[k]), 4)
                    if head.get(k) is not None and np.isfinite(head[k]) else None)

    scored = os.path.join(STATE, "scored_series_headline_val.csv")
    pd.DataFrame({"date": pd.to_datetime(vd).strftime("%Y-%m-%d"),
                  "obs": vo, "sim": vs}).to_csv(scored, index=False)

    cmask = ((dates.values[:n] >= np.datetime64(CAL[0])) &
             (dates.values[:n] <= np.datetime64(CAL[1])) &
             np.isfinite(obs[:n]) & np.isfinite(sim[:n]))
    cal_m = all_metrics(obs[:n][cmask], sim[:n][cmask],
                        dates=dates.values[:n][cmask], label="cal")
    gc = lambda k: (round(float(cal_m[k]), 4)
                    if cal_m.get(k) is not None and np.isfinite(cal_m[k]) else None)

    wb = water_balance_of(ts, fc, dates, n)
    wb_status = {"WARNING": "WARN", "OK": "PASS"}.get(wb["status"], wb["status"])

    table = [{"model_structure": r["model"], "mid": r["mid"], "n_params": r["np"],
              "n_stores": r["ns"], "variable": "Q", "obs_shape": "point_time_series",
              "nse_cal": r.get("nse_cal"), "nse_val": r.get("nse_val"),
              "kge_val": r.get("kge_val"), "pbias_val": r.get("pbias_val"),
              "r_val": r.get("r_val"), "budget_limited": bool(r.get("partial")),
              "theta": r.get("theta")} for r in done]
    skiptab = [{"model_structure": r.get("model"), "n_stores": r.get("ns"),
                "status": "skipped", "reason": r.get("reason")} for r in skipped]
    lines = [f"{t['model_structure']:<26} ns={t['n_stores']} np={t['n_params']:<2} "
             f"cal_NSE={t['nse_cal']} val_NSE={t['nse_val']} "
             f"val_KGE={t['kge_val']} val_PBIAS={t['pbias_val']}"
             f"{'  [budget-limited]' if t['budget_limited'] else ''}"
             for t in table]
    n_partial = sum(1 for t in table if t["budget_limited"])

    rc = next((t for t in table if t["model_structure"] == REALCASE_MODEL), None)
    rc_skip = next((s for s in skiptab if s["model_structure"] == REALCASE_MODEL), None)
    rc_note = (f"Real-case structure {REALCASE_MODEL} here: val NSE={rc['nse_val']}, "
               f"KGE={rc['kge_val']}, PBIAS={rc['pbias_val']}%, cal NSE={rc['nse_cal']}"
               f"{' [budget-limited]' if rc['budget_limited'] else ''}."
               if rc else
               f"Real-case structure {REALCASE_MODEL} did not score here "
               f"({(rc_skip or {}).get('reason')}).")

    bmeta = {}
    bpath = os.path.join(STATE, "basin_meta.json")
    if os.path.exists(bpath):
        bmeta = json.load(open(bpath))

    out = {
        "model_id": "MARRMoT",
        "this_location": LOC,
        "obs_source": "china_gaugeflux",
        "status": "completed",
        "tools_used": sorted(tools_used) + [
            "run_marrmot.py --calibrate --optimizer cmaes",
            "run_marrmot.py",
            "standard_calval.compute_calval_metrics",
            "ki_tools_common.metrics.all_metrics",
            "ki_tools_common.validation.validate_water_balance"],
        "tools_failed": tools_failed,
        "metrics": {
            "nse": gv("NSE"), "kge": gv("KGE"), "pbias": gv("PBIAS"), "r": gv("r"),
            "period": f"{VAL[0]}..{VAL[1]} (held-out validation, n={int(vmask.sum())})",
            "nse_cal": gc("NSE"), "kge_cal": gc("KGE"),
            "nse_val": gv("NSE"), "kge_val": gv("KGE"), "pbias_val": gv("PBIAS"),
            "period_calibration": f"{CAL[0]}..{CAL[1]}",
            "period_validation": f"{VAL[0]}..{VAL[1]}",
        },
        "water_balance": {"status": wb_status,
                          "residual_mm": wb.get("residual_mm"),
                          "residual_pct": wb.get("residual_pct"),
                          "diagnostics": wb.get("diagnostics", [])},
        "forcing_preflight": pf,
        "input_availability": avail,
        "variable": "Q",
        "obs_shape": "point_time_series",
        "selected_model": W["model"],
        "selection_rule": "highest HELD-OUT validation NSE among all 47 structures "
                          "(identical to the Real-case rule)",
        "realcase_model": REALCASE_MODEL,
        "realcase_model_here": rc,
        "n_structures_total": len(sts),
        "n_structures_completed": len(done),
        "n_structures_skipped": len(skipped),
        "n_structures_budget_limited": n_partial,
        "test_runs": table,
        "skipped_structures": skiptab,
        "comparison_table": lines,
        "catchment_area_km2": AREA_KM2,
        "basin_delineation": bmeta,
        "resolved_obs": {
            "station_id": STCD, "network": "china_gaugeflux",
            "station_name": GAUGE_NAME, "lat": GAUGE_LAT, "lon": GAUGE_LON,
            "granularity": "station", "drainage_area_km2": AREA_KM2,
            "period_start": str(pd.to_datetime(vd[0]).date()),
            "period_end": str(pd.to_datetime(vd[-1]).date()),
            "unit": "mm/day", "dataset_id": "china_gaugeflux",
            "obs_variable": "discharge_m3s", "geometry": None},
        "scored_series": {
            "paths": [scored], "unit": "mm/day", "n_paired": int(vmask.sum()),
            "period_start": str(pd.to_datetime(vd[0]).date()),
            "period_end": str(pd.to_datetime(vd[-1]).date()),
            "obs_source_path": OBS_TXT, "sim_source_path": W["ts_csv"],
            "event_threshold": None},
        "notes": (
            f"VERIFIER consistency run at a DELIBERATELY CONTRASTING location: "
            f"{GAUGE_NAME} (china_gaugeflux stcd {STCD}), {AREA_KM2:.0f} km2, a humid "
            f"subtropical monsoon catchment -- the opposite hydroclimate to the "
            f"Tangnaihai Real-case (cold 3,700 m plateau, 121,972 km2) and an order of "
            f"magnitude smaller. SAME KI pipeline and SAME protocol: all 47 shipped "
            f"structures calibrated with run_marrmot.py --calibrate --optimizer cmaes "
            f"--of-name of_NSE, {RESTARTS} IPOP restarts, budget 250*np clamped "
            f"800..4000, winner by HELD-OUT validation NSE. {len(done)}/{len(sts)} "
            f"structures produced a scoreable held-out series; {len(skipped)} skipped "
            f"(reasons in skipped_structures); {n_partial} were budget-limited (hit the "
            f"{CAL_TIMEOUT}s per-structure wall clock and returned their persisted "
            f"incumbent -- a low NSE there means under-searched, not structurally "
            f"unsuitable). WINNER by held-out validation NSE = {W['model']} "
            f"(val NSE={gv('NSE')}, KGE={gv('KGE')}, PBIAS={gv('PBIAS')}%, r={gv('r')}). "
            f"{rc_note} Forcing = CMFD daily 0.1deg basin-mean over "
            f"{len(cells)} cells via load_daily_forcing AREAL mode "
            f"(HydroBASINS lev07 upstream union above the gauge, delineated "
            f"{bmeta.get('delineated_area_km2', float('nan')):.0f} km2 vs published "
            f"{AREA_KM2:.0f} km2); PET = Priestley-Taylor from CMFD srad/lrad/pres "
            f"(dt_019). Observed Q converted m3/s -> mm/d over the PUBLISHED gauged "
            f"area (dt_010). Climatology P={pf['climatology_mm_per_yr']['P']}, "
            f"Ep={pf['climatology_mm_per_yr']['Ep']}, "
            f"Qobs={pf['climatology_mm_per_yr']['Q_obs']} mm/yr; required Ea = "
            f"{pf['climatology_mm_per_yr']['required_Ea']} mm/yr. Spin-up 1978-1979 "
            f"(excluded from the objective), calibration {CAL[0]}..{CAL[1]}, held-out "
            f"validation {VAL[0]}..{VAL[1]} with a 15-year gap from calibration and "
            f"never optimised on. Obs are absent 1998-2001 and 2004; check_and_select "
            f"drops NaN obs natively. Water balance {wb_status} "
            f"(residual {wb.get('residual_pct')}%). PER-STRUCTURE TABLE:\n"
            + "\n".join(lines)
        ),
    }
    json.dump(out, open(RESULT, "w"), indent=2, ensure_ascii=False)
    log("\n".join(lines))
    log(f"\nWINNER {W['model']}  val NSE={gv('NSE')} KGE={gv('KGE')} "
        f"PBIAS={gv('PBIAS')}\nWROTE {RESULT}")


if __name__ == "__main__":
    main()
