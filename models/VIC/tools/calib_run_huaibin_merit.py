#!/usr/bin/env python3
"""Driver for HUAIBIN (淮滨, 16,005 km²) on its MERIT-delineated domain — the reviewers'
single refuting test for the reach-loss reading.

Huaibin is the gauge immediately UPSTREAM of the Huaibin→Wangjiaba reach in which the
model-free balance finds water missing in 1982/1991. If the same untuned model
over-predicts Huaibin in those years too, the over-prediction is basin-wide (abstraction,
forcing) and the reach is a secondary cause; if Huaibin is normal while Wangjiaba blows
up, the reach-loss reading survives the shared-gauge attack.

Thin wrapper over calib_run_wangjiaba.py, same pattern as the merit wrapper: only the
case constants change. Obs envelopes are DECLARED in huaibin_obs_envelope.json (generated
once by mirroring load_obs slicing) so a changed observation file is detected, not
absorbed.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def _drop_stale_out() -> None:
    """codex structure_sync r1 #8: remove the --out metrics file BEFORE any check that can
    fail (obs sha1 at import, input/domain checks in main), so a failed retry can never
    leave an earlier success readable. The base driver repeats this; doing it twice is harmless."""
    argv = sys.argv[1:]
    for i, t in enumerate(argv):
        v = argv[i + 1] if t == "--out" and i + 1 < len(argv) else (t[6:] if t.startswith("--out=") else None)
        if v:
            try:
                Path(v).unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                sys.exit(f"[calib_run] FAIL: cannot remove stale metrics file {v!r}: {e}")


if __name__ == "__main__":
    _drop_stale_out()

_spec = importlib.util.spec_from_file_location("calib_run_wangjiaba", HERE / "calib_run_wangjiaba.py")
base = importlib.util.module_from_spec(_spec)
sys.modules["calib_run_wangjiaba"] = base
_spec.loader.exec_module(base)

# W5 (codex HIGH): the driver must not be pinned to the 0.25 artifact roots. Domain root
# and cell-file prefix come from the environment; defaults are the 0.25 build so every
# existing invocation is unchanged. For 0.1: SYS1_DOMAIN_ROOT=.../huaibin_merit_010,
# SYS1_CELL_PREFIX=huaibin_0.1deg_.
DOMAIN = os.environ.get("SYS1_DOMAIN_ROOT", f"{base.BASE}/outputs/huaibin_merit")
CELL_PREFIX = os.environ.get("SYS1_CELL_PREFIX", "huaibin_0.25deg_")
REGISTERED_AREA_KM2 = 16005.0
AREA_TOL = 0.05

# ---- case identity ---------------------------------------------------------------
base.BASIN, base.STA = "huaibin", "HB"
base.OBS_FILE = "KISSPATH_DATA/china_water_level/淮河txt/淮滨.txt"
base.TARGET_CASE = {
    "case_id": "SITE:huaibin",
    "dataset": "CNGF (china_gaugeflux) 淮河txt",
    "obs_file": base.OBS_FILE,
    "station_code": 50229350,
    "station_name": "淮滨",
    "variable": "Q", "units": "m3 s-1", "missing_sentinel": -99.0,
    "gauge_lon": 115.42, "gauge_lat": 32.44,
    "routed_station_id": "HB",
}
base.CASE_BY_STATION = {50229350: "SITE:huaibin"}

# ---- built inputs ----------------------------------------------------------------
base.SOIL_SRC = f"{DOMAIN}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
base.VEG_SRC = f"{DOMAIN}/vic_temp/veg/vic_veg_param_final.txt"
base.GP_SRC = f"{DOMAIN}/vic_temp/global_param_{Path(DOMAIN).name}.txt"
base.ROUT_SRC = f"{DOMAIN}/routing"
base.FORCING_PREFIX = CELL_PREFIX
def _routing_key(rdir: str, sta: str) -> str:      # codex W5: uh_s cache keyed on routing CONTENT
    h = hashlib.sha1()
    # codex structure_sync r2 #2: key on EVERY routing input rout reads when it builds the uh_s grid
    # (MAKE_GRID_UH folds UH.all in; staloc names the station) — not only frac/direc/xmask
    # r4: hash EXACTLY the set the base driver copies into each routing run (run_rout: every
    # <STA>_*.txt by glob, plus UH.all and rout_global.txt), name + content, so a file referenced
    # under another name (e.g. <STA>_xmask_alt.txt) is covered too.
    names = sorted(p.name for p in Path(rdir).glob(f"{sta}_*.txt")) + ["UH.all", "rout_global.txt"]
    for nm in names:
        h.update(nm.encode() + b"\0")
        h.update(Path(f"{rdir}/{nm}").read_bytes() if Path(f"{rdir}/{nm}").exists() else b"MISSING")
        h.update(b"\0")
    return h.hexdigest()[:10]


base.UH_CACHE_DIR = os.environ.get(
    "KDT_VIC_UH_CACHE", f"/dev/shm/kdt_vic_calib/uh_s_huaibin_merit_{_routing_key(f'{DOMAIN}/routing', 'HB')}")
ERA = {1980: f"{DOMAIN}/vic_temp/forcing/forcing_final_1980_1998",
       2000: f"{DOMAIN}/vic_temp/forcing/forcing_final_2000_2018"}

_ENV = json.loads((HERE / "huaibin_obs_envelope.json").read_text())
# codex (2026-08-28): a declared envelope is only fail-closed if it cannot be silently
# regenerated against a changed obs file. The envelope file records the sha1 of the obs
# file it was generated from; refuse to run if the obs file on disk is not that file.
_prov = _ENV.pop("__provenance__", None)
if not _prov or not _prov.get("obs_sha1"):
    raise base.Fail("huaibin_obs_envelope.json carries no obs_sha1 provenance — regenerate it")
_sha_now = hashlib.sha1(Path(base.OBS_FILE).read_bytes()).hexdigest()
if _sha_now != _prov["obs_sha1"]:
    raise base.Fail(f"obs file {base.OBS_FILE} sha1 {_sha_now[:12]} != envelope's "
                    f"{_prov['obs_sha1'][:12]} — the observed series changed; re-declare")
base.OBS_ENVELOPE = _ENV                                   # declared, not recomputed
base.SPLITS = {y: {"sim": (int(y) - 2, int(y)), "score": (f"{y}-01-01", f"{y}-12-31")}
               for y in _ENV}

split = os.environ.get("KDT_CALIB_SPLIT", "")
# DECLARED YEAR SETS (System 1 holdout v2, 2026-08-30): KDT_CALIB_SPLIT=calibration|holdout scores every
# year named in KDT_CALIB_SPLIT_SETS (JSON from the contract's strategy.holdout), one full VIC+routing run
# per year, and returns aggregated metrics (nse = mean NSE, pbias = mean |PBIAS|, day_bias = mean |peak-day
# error|) + per-year detail — the form the calibration kit's composite objective and holdout gate consume.
SPLIT_SETS = json.loads(os.environ.get("KDT_CALIB_SPLIT_SETS", "{}") or "{}")
MULTI = split in ("calibration", "holdout")
if MULTI:
    _years = [str(y) for y in (SPLIT_SETS.get(split) or [])]
    if not _years:
        raise base.Fail(f"KDT_CALIB_SPLIT={split} but KDT_CALIB_SPLIT_SETS declares no years for it")
    _which = split
    split = _years[0]
# W6 (2026-08-29): an alternative forcing root (MSWX era, TJ splice) may start in another year;
# FORCEYEAR must match its first record — override allowed only together with SYS1_FORCING_ROOT.
FORCEYEAR_OVERRIDE = None
if "SYS1_FORCEYEAR" in os.environ:
    if "SYS1_FORCING_ROOT" not in os.environ:
        raise base.Fail("SYS1_FORCEYEAR is only valid together with SYS1_FORCING_ROOT")
    FORCEYEAR_OVERRIDE = int(os.environ["SYS1_FORCEYEAR"])


def _era_for(y: str) -> int:
    """First forcing year (FORCEYEAR) for score year y. codex structure_sync r1 #2: an explicit
    SYS1_FORCEYEAR is the origin of the ONE alternative root for EVERY year (multi-year mode used
    to reset it to 1980/2000 per year). Without an override the default era builds are used."""
    if FORCEYEAR_OVERRIDE is not None:
        fy = FORCEYEAR_OVERRIDE
    else:
        fy = 2000 if y and int(y) >= 2000 else 1980
    if y and int(y) - 2 < fy:
        raise base.Fail(f"split {y} needs forcing from {int(y)-2} but the forcing starts {fy}")
    return fy


if MULTI and "SYS1_FORCING_ROOT" in os.environ and FORCEYEAR_OVERRIDE is None \
        and len({2000 if int(y) >= 2000 else 1980 for y in _years}) > 1:
    # one alternative root has ONE first record; letting FORCEYEAR flip 1980/2000 per year over
    # the same files would make VIC read the wrong years for one of the eras
    raise base.Fail("SYS1_FORCING_ROOT with years in both eras needs SYS1_FORCEYEAR (its first year)")
era_start = _era_for(split)
base.FORCING_SRC = os.environ.get("SYS1_FORCING_ROOT", ERA[2000 if split and int(split) >= 2000 else 1980])
base.FORCING_CACHE = f"/dev/shm/kdt_vic_calib/forcing_huaibin_merit_{hashlib.sha1(base.FORCING_SRC.encode()).hexdigest()[:10]}"

_orig_write_gp = base.write_global_param


def write_global_param(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1):
    _orig_write_gp(dst, soil, veg, veglib, constants, result_dir, forcing_prefix, y0, y1)
    out, seen = [], False
    for l in Path(dst).read_text().splitlines(keepends=True):
        tok = l.split()
        if tok and tok[0] == "FORCEYEAR" and not l.lstrip().startswith("#"):
            out.append(f"FORCEYEAR\t\t\t{era_start}\n"); seen = True
        else:
            out.append(l)
    if not seen:
        raise base.Fail("global param template has no FORCEYEAR line")
    Path(dst).write_text("".join(out))


base.write_global_param = write_global_param


def domain_gate() -> dict:
    fr = np.loadtxt(f"{base.ROUT_SRC}/HB_frac.txt", skiprows=6)
    hdr = dict(l.split() for l in open(f"{base.ROUT_SRC}/HB_frac.txt").readlines()[:6])
    cs = float(hdr["cellsize"]); n_lat = float(hdr["yllcorner"]) + int(hdr["nrows"]) * cs
    lats = np.array([n_lat - (i + 0.5) * cs for i in range(fr.shape[0])])
    routed = float((fr * (cs * 111.32 * np.cos(np.radians(lats)) * cs * 110.57)[:, None]).sum())
    rel = abs(routed - REGISTERED_AREA_KM2) / REGISTERED_AREA_KM2
    if rel > AREA_TOL:
        raise base.Fail(f"DOMAIN GATE: routed {routed:.0f} vs registered {REGISTERED_AREA_KM2:.0f} "
                        f"({100*rel:.1f}% off)")
    return {"routed_km2": round(routed), "rel_error": round(rel, 4)}


_orig_main = base.main


def _routed_series(wd: Path):
    import glob as _g, pandas as pd
    fs = _g.glob(str(wd / "run" / "routing" / "rout_out" / "*.day"))
    if not fs:
        raise base.Fail("multi-year scoring needs the routed .day file (KDT_VIC_KEEP_WORKDIR=1)")
    a = pd.read_csv(fs[0], sep=r"\s+", header=None)
    return pd.Series(a[3].values, index=pd.to_datetime(dict(year=a[0], month=a[1], day=a[2])))


def _basin_rain_mm(y: str, start: int) -> float:
    """Annual basin-mean rain (mm) over the routed cells, frac x cos(lat) weighted (same weights as
    the lumped forcing build and score_holdout), from the era's VIC per-cell forcing files."""
    import pandas as pd
    hdr = dict(l.split() for l in open(f"{base.ROUT_SRC}/HB_frac.txt").readlines()[:6])
    fr = np.loadtxt(f"{base.ROUT_SRC}/HB_frac.txt", skiprows=6)
    cs = float(hdr["cellsize"]); x0 = float(hdr["xllcorner"]); yN = float(hdr["yllcorner"]) + int(hdr["nrows"]) * cs
    soil = pd.read_csv(base.SOIL_SRC, sep=r"\s+", header=None, usecols=[2, 3], names=["lat", "lon"])
    # codex structure_sync r1 #6: timestamps are built per file from its ACTUAL record count, the
    # declared forcing origin (FORCEYEAR = start) and FORCE_STEPS_PER_DAY of the global param — no
    # fixed 19-year length. For the default 1980/2000 builds this selects exactly the same records
    # as before (same origin, same 3 h step), so the yields of earlier runs are unchanged.
    spd = None
    for l in open(base.GP_SRC):
        tok = l.split()
        if len(tok) >= 2 and tok[0] == "FORCE_STEPS_PER_DAY":
            spd = int(tok[1])
    if not spd or 24 % spd:
        raise base.Fail(f"FORCE_STEPS_PER_DAY missing or not a divisor of 24 in {base.GP_SRC}")
    y0, y1 = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31") + pd.Timedelta(hours=24 - 24 // spd)
    acc = 0.0; tot = 0.0
    for la, lo in zip(soil.lat, soil.lon):
        i, j = int((yN - la) / cs), int((lo - x0) / cs)
        f = float(fr[i, j]) if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] else 0.0
        if f <= 0:
            continue
        wt = f * np.cos(np.radians(la))
        col = np.loadtxt(f"{base.FORCING_SRC}/{CELL_PREFIX}{la:.4f}_{lo:.4f}", usecols=1, ndmin=1)
        t = pd.date_range(f"{start}-01-01", periods=len(col), freq=f"{24 // spd}h")
        if t[0] > y0 or t[-1] < y1:     # the year must be fully inside the file: no silent short sum
            raise base.Fail(f"forcing {CELL_PREFIX}{la:.4f}_{lo:.4f} covers {t[0]}..{t[-1]}, "
                            f"not the whole score year {y}")
        acc += col[t.year == int(y)].sum() * wt; tot += wt
    if tot <= 0:
        raise base.Fail("no routed VIC cell overlaps HB_frac.txt — basin rain cannot be computed")
    return float(acc / tot)


DAY_BIAS_DEFINITION = ("windowed peak-day error: |day of the simulated maximum within ±30 d of the observed "
                       "annual peak - day of the observed annual peak| (days), mean over declared years; "
                       "day_bias_annual_argmax = |sim annual argmax day - obs annual peak day|")


def main_multi(years: list[str], which: str) -> int:
    """One full driver run per declared year (every fail-closed check kept), then aggregate."""
    global split, era_start
    import pandas as pd, time as _t
    ap = base.argparse.ArgumentParser(); ap.add_argument("--workdir"); ap.add_argument("--out")
    a, _ = ap.parse_known_args()
    out = Path(a.out)
    try:
        out.unlink()
    except FileNotFoundError:
        pass
    os.environ["KDT_VIC_KEEP_WORKDIR"] = "1"
    o = pd.read_csv(base.OBS_FILE, sep="\t"); o.columns = [c.strip() for c in o.columns]
    o["d"] = pd.to_datetime(o["dates"], format="mixed"); q = pd.to_numeric(o["Q"], errors="coerce")
    obs = o.assign(q=q)[q > -90].set_index("d")["q"]
    per, t0 = {}, _t.time()
    _scored_series = []   # kdt-target-proof/1 accumulator
    for y in years:
        split = y; era_start = _era_for(y)
        base.FORCING_SRC = os.environ.get("SYS1_FORCING_ROOT", ERA[2000 if int(y) >= 2000 else 1980])
        base.FORCING_CACHE = f"/dev/shm/kdt_vic_calib/forcing_huaibin_merit_{hashlib.sha1(base.FORCING_SRC.encode()).hexdigest()[:10]}"
        os.environ["KDT_CALIB_SPLIT"] = y
        wd_y = Path(a.workdir).resolve() / "years" / y; wd_y.mkdir(parents=True, exist_ok=True)
        sys.argv = [sys.argv[0], "--workdir", str(wd_y), "--out", str(wd_y / "metrics.json")]
        rc = main()
        if rc not in (0, None) or not (wd_y / "metrics.json").exists():
            raise base.Fail(f"year {y}: driver returned {rc} / no metrics")
        m = json.loads((wd_y / "metrics.json").read_text())
        s = _routed_series(wd_y).loc[y]; ob = obs.loc[y]
        # robust peak timing (reviewers 2026-08-30): simulated maximum within ±30 d of the OBSERVED annual
        # peak, bounded; the raw annual-argmax difference is kept for the record
        t_obs = ob.idxmax(); win = s.loc[t_obs - pd.Timedelta(days=30): t_obs + pd.Timedelta(days=30)]
        t_sim = win.idxmax() if len(win) else s.idxmax()
        m["day_bias"] = float(abs((t_sim - t_obs).days)); m["day_bias_annual_argmax"] = float(abs((s.idxmax() - t_obs).days))
        # codex structure_sync r1 #7: day_bias is the WINDOWED metric (declared as such in dag.yaml
        # OUT_DISCHARGE timing_accuracy); the math is unchanged so earlier Huai results reproduce.
        # A simulated annual peak outside the ±30 d window is FLAGGED, never hidden.
        m["peak_outside_window"] = bool(m["day_bias_annual_argmax"] > 30)
        # yields (Q/P) per year for the declared yield-slope criterion: P = frac x cos(lat) weighted
        # basin-mean rain of the VIC cells (mm), Q in mm over the registered area
        P = _basin_rain_mm(y, era_start)
        pq = pd.concat([ob.rename("obs"), s.rename("sim")], axis=1).dropna()
        to_mm = 86400.0 / (REGISTERED_AREA_KM2 * 1e3)
        m["P_mm"] = P; m["yield_obs"] = float(pq["obs"].sum() * to_mm / P) if P > 0 else None
        m["yield_sim"] = float(pq["sim"].sum() * to_mm / P) if P > 0 else None
        per[y] = {k: m[k] for k in ("nse", "kge", "pbias", "r", "rmse", "day_bias", "day_bias_annual_argmax", "peak_outside_window", "P_mm", "yield_obs", "yield_sim") if k in m}
        per[y]["run_health"] = m.get("__kdt__", {}).get("run_health")
        _scored_series.append(pq["sim"])         # kdt-target-proof/1: exactly what this year scored
    import numpy as _np
    agg = {"nse": float(_np.mean([per[y]["nse"] for y in years])),
           "pbias": float(_np.mean([abs(per[y]["pbias"]) for y in years])),
           "pbias_signed_mean": float(_np.mean([per[y]["pbias"] for y in years])),
           "day_bias": float(_np.mean([per[y]["day_bias"] for y in years])),
           # reported beside day_bias (not part of the objective): the plain annual-argmax error and
           # how many years had their simulated annual peak outside the ±30 d window
           "day_bias_annual_argmax": float(_np.mean([per[y]["day_bias_annual_argmax"] for y in years])),
           "n_peak_outside_window": int(sum(per[y]["peak_outside_window"] for y in years)),
           "kge": float(_np.mean([per[y]["kge"] for y in years])), "r": float(_np.mean([per[y].get("r") or 0 for y in years])),
           "rmse": float(_np.mean([per[y].get("rmse") or 0 for y in years]))}
    last = json.loads((Path(a.workdir).resolve() / "years" / years[-1] / "metrics.json").read_text())["__kdt__"]
    res = {**agg, "__kdt__": {**{k: last.get(k) for k in ("applied_params", "case_id", "scored_obs", "domain", "setup_fp")},
                              "run_health": {**last.get("run_health", {}), "aggregated_over_years": len(years)},
                              "split": which, "years": years, "per_year": per, "aggregation": "mean over declared years",
                              "day_bias_definition": DAY_BIAS_DEFINITION,
                              "wallclock_s": round(_t.time() - t0, 1),
                              # kdt-target-proof/1 (2026-09-15): the RAW scored series, concatenated over
                              # the declared years in order — one proof per calibration target.
                              "target_proofs": [_target_proof(pd.concat(_scored_series), which, years)]}}
    out.parent.mkdir(parents=True, exist_ok=True)     # codex structure_sync r2 #5: as the base driver
    tmp = out.with_suffix(out.suffix + f".partial.{os.getpid()}")
    tmp.write_text(json.dumps(res, indent=2, ensure_ascii=False)); os.replace(tmp, out)
    print(f"[huaibin] split={which} years={len(years)} mean nse={agg['nse']:.4f} mean|pbias|={agg['pbias']:.2f}% "
          f"day_bias={agg['day_bias']:.1f}d ({res['__kdt__']['wallclock_s']}s)", flush=True)
    return 0


def main() -> int:
    _drop_stale_out()        # codex structure_sync r1 #8: before every fallible check
    if MULTI and os.environ.get("KDT_CALIB_SPLIT") in ("calibration", "holdout"):
        return main_multi(_years, _which)
    if split not in base.SPLITS:
        raise base.Fail(f"KDT_CALIB_SPLIT={split!r} has no Huaibin obs envelope "
                        f"(available: {sorted(base.SPLITS)})")
    for p in (base.SOIL_SRC, base.VEG_SRC, base.GP_SRC, base.FORCING_SRC,
              f"{base.ROUT_SRC}/HB_frac.txt", f"{base.ROUT_SRC}/HB_direc.txt"):
        if not Path(p).exists():
            raise base.Fail(f"huaibin input missing: {p}")
    g = domain_gate()
    print(f"[huaibin] domain gate PASS: routed {g['routed_km2']} km2 vs {REGISTERED_AREA_KM2:.0f} "
          f"({100*g['rel_error']:.1f}% off); forcing {base.FORCING_SRC} (FORCEYEAR {era_start})", flush=True)
    return _orig_main()



def _target_proof(series, split, years):
    """Shared kdt-target-proof/1 (ki_tools_common.kdt_proof) — one implementation for every KI."""
    import sys as _sys
    _sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
    from ki_tools_common.kdt_proof import target_proof
    return target_proof(series.to_numpy(), series.index, target="OUT_DISCHARGE", unit="m3/s", split=split,
                        window=(f"{years[0]}-01-01", f"{years[-1]}-12-31"),
                        source=f"VIC Huaibin MERIT wrapper: routed daily discharge at the gauge, inner-joined to obs, years {list(years)} concatenated")

if __name__ == "__main__":
    sys.exit(main())
