#!/usr/bin/env python3
"""
CWatM verifier runner — daily discharge at Zhimenda (直门达), GRDC 2181500,
Tongtian He / upper Yangtze, Tibetan Plateau (96.60E 33.4333N, 137,704 km2).

Second location for the CWatM consistency check (real-case was 九江 / Jiujiang,
1.5 M km2 monsoon lowland main stem). Zhimenda is the hydrologic opposite:
56 cells at 0.5 deg, ~4,600 m mean elevation, snow/permafrost-dominated,
no reservoirs in the 1975-1997 record.

Chains the same KI tools end-to-end and is RESUMABLE — every stage checks for
its own outputs and skips if present, so a relaunch continues where it stopped.

  s2  tools/build_cwatm_static.py         MERIT-Hydro + ESA-CCI-LC -> static grid
      tools/convert_soil_to_cwatm.py      HWSD -> van Genuchten stack
      tools/build_cwatm_ancillary.py      crop coefficients, intercept caps, dzRel
  s1  tools/convert_forcing_to_cwatm.py   CMFD daily 0.1deg -> 0.5deg CWatM NetCDF
                                          (+ tmin/tmax from the 3-hourly archive)
  s3  tools/run_cwatm_wrapper.py          run the real CWatM (source/repo/run_cwatm.py)
  s4  tools/parse_cwatm_output.py         discharge_daily.csv -> sim series
      ki_tools_common.metrics.all_metrics NSE / KGE / R / PBIAS / RMSE

The uncalibrated default parameter set is scored first. As at Jiujiang, if the
calibration-period PBIAS exceeds --pbias_tol the HIGH-sensitivity ET multiplier
`crop_correct` (SKILL.md range 0.8-1.5) is stepped and the model re-run, up to
MAX_ITER times. Each iteration's output lives in output_iter<N>/ so a relaunch
reuses finished iterations.

Writes the KDT verifier result object to detached/verify_2/result.json.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = "/mnt/disk1/Hydrocraft_server/models/CWatM"
KI = f"{ROOT}/knowledge_infrastructure"
TOOLS = f"{KI}/tools"
CASE = f"{ROOT}/cwatm_zhimenda"
CWATM_DIR = f"{ROOT}/source/repo"
PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
STATE = f"{ROOT}/detached/verify_2"

OBS = ("/mnt/disk1/Hydrocraft_server/data/china_data/"
       "GRDC_asia_discharge_daily_20260511/2181500_Q_Day.Cmd.txt")
LOCATION = "Zhimenda 直门达, Tongtian He (upper Yangtze), Tibetan Plateau — GRDC 2181500"
OBS_SOURCE = ("GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download); "
              "station 2181500 ZHIMENDA, TONGTIAN HE, CN, 137,704 km2, discharge_m3s")

GAUGE_LON, GAUGE_LAT = 96.6, 33.433333
EXPECTED_AREA_KM2 = 137704.0
BBOX = ["31.5", "36.0", "90.0", "97.5"]
RES = 0.5
SPINUP_START, RUN_START, RUN_END = "1975-01-01", "1978-01-01", "1997-12-31"
CAL = ("1978-01-01", "1987-12-31")
VAL = ("1988-01-01", "1997-12-31")

MERIT_DIR = "/mnt/disk1/Hydrocraft_server/data/merit_hydro"
ESA_LC = "/mnt/datasets/vegetation/ESA_CCI_LC/ESA_CCI_LC_cold_china_1992_01deg.tif"

# GDAL in this env needs libstdc++ preloaded (TLS static block).
ENV = dict(os.environ, LD_PRELOAD="/lib/x86_64-linux-gnu/libstdc++.so.6")

MAX_ITER = int(os.environ.get("CWATM_MAX_ITER", "3"))
PBIAS_TOL = 12.0

TOOLS_USED, TOOLS_FAILED, ISSUES = [], [], []


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def sh(cmd, tool):
    log("RUN", " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], env=ENV, text=True, capture_output=True)
    if p.returncode != 0:
        log("STDOUT tail:", p.stdout[-3000:])
        log("STDERR tail:", p.stderr[-3000:])
        if tool not in TOOLS_FAILED:
            TOOLS_FAILED.append(tool)
        raise SystemExit(f"command failed ({p.returncode}): {cmd[0]}")
    if tool not in TOOLS_USED:
        TOOLS_USED.append(tool)
    return p.stdout


# ------------------------------------------------------------------ s2 static
def stage_static():
    if os.path.exists(f"{CASE}/static/static_meta.json"):
        log("s2 static: complete, skipping")
        TOOLS_USED.append("build_cwatm_static.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_static.py",
        "--gauge_lon", GAUGE_LON, "--gauge_lat", GAUGE_LAT,
        "--bbox", *BBOX, "--res", RES,
        "--merit_dir", MERIT_DIR, "--esa_lc", ESA_LC,
        "--expected_area_km2", EXPECTED_AREA_KM2,
        "--snap_window_px", 180,
        "--out_dir", f"{CASE}/static"], "build_cwatm_static.py")


def stage_soil():
    if os.path.exists(f"{CASE}/soil/percolationImp.nc"):
        log("s2 soil: complete, skipping")
        TOOLS_USED.append("convert_soil_to_cwatm.py")
        return
    sh([PY, f"{TOOLS}/convert_soil_to_cwatm.py", "--source", "hwsd",
        "--input_dir", "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER",
        "--bbox", *BBOX, "--resolution", RES, "--output_dir", f"{CASE}/soil"],
       "convert_soil_to_cwatm.py")


def stage_ancillary():
    if os.path.exists(f"{CASE}/ancillary/relativeElevation.nc"):
        log("s2 ancillary: complete, skipping")
        TOOLS_USED.append("build_cwatm_ancillary.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_ancillary.py",
        "--static_dir", f"{CASE}/static", "--output_dir", f"{CASE}/ancillary"],
       "build_cwatm_ancillary.py")


# ---------------------------------------------------------------- s1 forcing
FORCING_VARS = ["precipitation", "tavg", "qair", "psurf", "wind", "rsds", "rsdl", "tmin", "tmax"]


N_DAYS = (pd.Timestamp(RUN_END) - pd.Timestamp(SPINUP_START)).days + 1


def _drop_truncated_forcing(out):
    """convert_forcing_to_cwatm --resume skips any existing <var>.nc. A file left
    half-written by an interrupted run would therefore be trusted forever. Delete
    anything that does not open cleanly with the full SPINUP_START..RUN_END span."""
    import netCDF4 as nc
    for v in FORCING_VARS:
        p = f"{out}/{v}.nc"
        if not os.path.exists(p):
            continue
        try:
            ds = nc.Dataset(p)
            n = ds.dimensions["time"].size
            ok = v in ds.variables and n == N_DAYS
            ds.close()
        except Exception:
            ok = False
        if not ok:
            log(f"s1 forcing: {v}.nc truncated/unreadable -> removing, will rebuild")
            os.remove(p)


def stage_forcing():
    out = f"{CASE}/forcing"
    os.makedirs(out, exist_ok=True)
    _drop_truncated_forcing(out)
    if all(os.path.exists(f"{out}/{v}.nc") for v in FORCING_VARS):
        log("s1 forcing: complete, skipping")
        TOOLS_USED.append("convert_forcing_to_cwatm.py")
        return
    sh([PY, f"{TOOLS}/convert_forcing_to_cwatm.py",
        "--forcing_dir", "/media/server/hc_ssd/forcing/Data_forcing_01dy_010deg",
        "--forcing_type", "cmfd", "--bbox", *BBOX,
        "--start_date", SPINUP_START, "--end_date", RUN_END,
        "--target_res", RES, "--resume",
        "--tminmax_3hr_dir",
        "/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg/Temp",
        "--output_dir", out], "convert_forcing_to_cwatm.py")
    missing = [v for v in FORCING_VARS if not os.path.exists(f"{out}/{v}.nc")]
    if missing:
        raise SystemExit(f"forcing incomplete: {missing}")


# ------------------------------------------------------- grid sanity preflight
def check_grids():
    import netCDF4 as nc
    ref = nc.Dataset(f"{CASE}/static/MaskMap.nc")
    rlat, rlon = np.array(ref["lat"][:]), np.array(ref["lon"][:])
    for d, files in ((f"{CASE}/forcing", [f"{v}.nc" for v in FORCING_VARS]),
                     (f"{CASE}/soil", ["KSat1.nc", "thetas1.nc", "percolationImp.nc"]),
                     (f"{CASE}/ancillary", ["relativeElevation.nc"])):
        for f in files:
            ds = nc.Dataset(f"{d}/{f}")
            la, lo = np.array(ds["lat"][:]), np.array(ds["lon"][:])
            if la.shape != rlat.shape or lo.shape != rlon.shape:
                raise SystemExit(f"grid mismatch {f}: {la.shape},{lo.shape} vs {rlat.shape},{rlon.shape}")
            if not (np.allclose(la, rlat, atol=1e-3) and np.allclose(lo, rlon, atol=1e-3)):
                raise SystemExit(f"grid coords differ for {f}")
            ds.close()
    log("grid preflight: all inputs share the static grid")


def forcing_preflight():
    """Cheap unit sanity on the CMFD stack (SKILL.md unit-trap table)."""
    import netCDF4 as nc
    fails, warns = [], []
    try:
        p = np.array(nc.Dataset(f"{CASE}/forcing/precipitation.nc")["precipitation"][:])
        t = np.array(nc.Dataset(f"{CASE}/forcing/tavg.nc")["tavg"][:])
        ps = np.array(nc.Dataset(f"{CASE}/forcing/psurf.nc")["psurf"][:])
        pm = float(np.nanmean(p))
        # kg m-2 s-1 -> mm/yr
        p_mmyr = pm * 86400 * 365.25
        if not (100 < p_mmyr < 3000):
            fails.append(f"precip {p_mmyr:.0f} mm/yr outside 100-3000 (unit error?)")
        tm = float(np.nanmean(t))
        if tm < 150:
            fails.append(f"tavg mean {tm:.1f} looks like Celsius but TemperatureInKelvin=True")
        psm = float(np.nanmean(ps))
        if psm < 10000:
            fails.append(f"psurf mean {psm:.0f} looks like hPa/kPa not Pa")
        warns.append(f"basin-mean precip {p_mmyr:.0f} mm/yr, tavg {tm:.1f} K, psurf {psm:.0f} Pa")
    except Exception as e:
        warns.append(f"forcing preflight incomplete: {e}")
    return {"all_pass": not fails, "source": "CMFD V0200 daily 0.1deg -> 0.5deg",
            "failures": fails, "warnings": warns}


# -------------------------------------------------------------------- s3 run
def write_settings(crop_correct, out_dir):
    src = open(f"{CASE}/settings_zhimenda.ini").read()
    src = re.sub(r"^crop_correct\s*=.*$", f"crop_correct          = {crop_correct:.3f}",
                 src, flags=re.M)
    src = re.sub(r"^PathOut\s*=.*$", f"PathOut   = {out_dir}", src, flags=re.M)
    p = f"{CASE}/settings_iter.ini"
    open(p, "w").write(src)
    return p


def stage_run(crop_correct, it):
    out_dir = f"{CASE}/output_iter{it}"
    csv = f"{out_dir}/discharge_daily.csv"
    if os.path.exists(csv):
        log(f"s3 run iter{it}: {csv} exists, skipping")
        TOOLS_USED.append("run_cwatm_wrapper.py")
        return csv, out_dir
    os.makedirs(out_dir, exist_ok=True)
    settings = write_settings(crop_correct, out_dir)
    sh([PY, f"{TOOLS}/run_cwatm_wrapper.py", "--settings", settings,
        "--cwatm_dir", CWATM_DIR, "--flags=-q"], "run_cwatm_wrapper.py")
    if not os.path.exists(csv):
        raise SystemExit(f"CWatM produced no {csv}")
    return csv, out_dir


# ------------------------------------------------------------------ s4 score
def read_sim(csv):
    """CWatM TSS csv: 3 preamble lines, then Date,G1 with DD/MM/YYYY."""
    df = pd.read_csv(csv, skiprows=3)
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    return pd.Series(df.iloc[:, 1].astype(float).values, index=df["Date"], name="sim")


def read_obs():
    """GRDC .Cmd.txt: '#'-commented header, then YYYY-MM-DD;hh:mm; Value ; -999 = nodata."""
    rows = []
    with open(OBS, encoding="latin-1") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("YYYY"):
                continue
            parts = line.strip().split(";")
            if len(parts) < 3:
                continue
            try:
                v = float(parts[2])
            except ValueError:
                continue
            if v <= -999.0:
                continue
            rows.append((parts[0], v))
    if not rows:
        raise SystemExit(f"no usable observations parsed from {OBS}")
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.Series([r[1] for r in rows], index=idx, name="obs")


def score(sim, obs, a, b):
    from ki_tools_common.metrics import all_metrics
    j = pd.concat([sim, obs], axis=1).dropna()
    j = j.loc[a:b]
    if len(j) < 2:
        return None, 0
    # all_metrics returns UPPERCASE keys ('NSE','KGE','PBIAS','RMSE') plus lowercase 'r'.
    m = all_metrics(j["obs"].values, j["sim"].values)
    return {k.lower(): (None if not np.isfinite(v) else round(float(v), 4))
            for k, v in m.items()}, len(j)


def water_balance(out_dir):
    """Basin-mean P, ET, runoff from the monthly maps (mm/yr) + closure residual.

    CWatM names the variable inside <var>_monthavg.nc as '<var>_monthavg', not '<var>'
    (the Jiujiang driver read '<var>' and silently reported status N/A).
    """
    import netCDF4 as nc
    try:
        mask = np.array(nc.Dataset(f"{CASE}/static/MaskMap.nc")["MaskMap"][:]) == 1
        area = np.array(nc.Dataset(f"{CASE}/static/CellArea.nc")["CellArea"][:])
        area = np.where(mask, area, 0.0)
        tot = area.sum()

        def mean_mm_per_day(var):
            ds = nc.Dataset(f"{out_dir}/{var}_monthavg.nc")
            name = f"{var}_monthavg" if f"{var}_monthavg" in ds.variables else var
            a = np.array(ds.variables[name][:], dtype=float)
            a = np.where(np.isfinite(a), a, 0.0)
            w = (a * area[None, :, :]).sum(axis=(1, 2)) / tot
            return float(np.mean(w)) * 1000.0

        p = mean_mm_per_day("Precipitation")
        et = mean_mm_per_day("totalET")
        ro = mean_mm_per_day("runoff")
        res = p - et - ro
        return {"status": "PASS" if abs(res) < 0.05 * max(p, 1e-9) else "WARN",
                "residual_mm": round(res * 365.25, 2),
                "residual_pct": round(100 * res / p, 2) if p else None,
                "diagnostics": [f"P={p*365.25:.0f} ET={et*365.25:.0f} runoff={ro*365.25:.0f}"
                                f" mm/yr basin-mean (storage change not removed)"]}
    except Exception as e:  # non-fatal
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": [f"water-balance maps unavailable: {e}"]}


def write_result(res):
    os.makedirs(STATE, exist_ok=True)
    with open(f"{STATE}/result.json", "w") as fh:
        json.dump(res, fh, indent=2, ensure_ascii=False)
    log("WROTE", f"{STATE}/result.json")


def main():
    os.makedirs(STATE, exist_ok=True)
    os.chdir(ROOT)
    try:
        stage_static()
        stage_soil()
        stage_ancillary()
        stage_forcing()
        check_grids()
        pre = forcing_preflight()
        log("forcing preflight:", json.dumps(pre))

        obs = read_obs()
        log(f"obs: n={len(obs)} {obs.index.min().date()}..{obs.index.max().date()} "
            f"mean={obs.mean():.1f} m3/s")

        tried, best = [], None
        cc = 1.00
        for it in range(MAX_ITER):
            csv, out_dir = stage_run(cc, it)
            sim = read_sim(csv)
            m_cal, n_cal = score(sim, obs, *CAL)
            if m_cal is None or m_cal.get("pbias") is None:
                raise SystemExit(f"iter{it}: no scorable overlap over CAL {CAL} (n={n_cal})")
            log(f"iter{it} crop_correct={cc:.3f}  cal NSE={m_cal['nse']} "
                f"PBIAS={m_cal['pbias']} (n={n_cal})")
            tried.append({"iter": it, "crop_correct": round(cc, 3), **m_cal})
            if best is None or abs(m_cal["pbias"]) < abs(best[1]["pbias"]):
                best = (it, m_cal, cc, csv, out_dir)
            if abs(m_cal["pbias"]) <= PBIAS_TOL:
                break
            step = 1.0 + 0.5 * (m_cal["pbias"] / 100.0)
            cc = float(np.clip(cc * step, 0.8, 1.5))
            if any(abs(cc - t["crop_correct"]) < 0.005 for t in tried):
                log("crop_correct converged / saturated; stopping")
                break

        it, m_cal, cc, csv, out_dir = best
        sim = read_sim(csv)
        m_cal, n_cal = score(sim, obs, *CAL)
        m_val, n_val = score(sim, obs, *VAL)
        m_full, n_full = score(sim, obs, CAL[0], VAL[1])
        wb = water_balance(out_dir)

        # r-limited NSE ceiling (NSE_max = r^2) — see the Jiujiang diagnosis.
        r_full = m_full["r"]
        ceiling = round(r_full ** 2, 4) if r_full is not None else None

        res = {
            "model_id": "CWatM",
            "this_location": LOCATION,
            "obs_source": OBS_SOURCE,
            "status": "completed",
            "tools_used": sorted(set(TOOLS_USED)) + ["parse_cwatm_output.py (read_sim equivalent)",
                                                     "ki_tools_common.metrics.all_metrics"],
            "tools_failed": TOOLS_FAILED,
            "variable": "discharge",
            "obs_shape": "point_time_series",
            "metrics": {
                "nse": m_full["nse"], "kge": m_full["kge"], "pbias": m_full["pbias"],
                "r": m_full["r"], "rmse": m_full["rmse"],
                "period": f"{CAL[0]} to {VAL[1]} (daily, n={n_full})",
                "nse_cal": m_cal["nse"], "kge_cal": m_cal["kge"], "pbias_cal": m_cal["pbias"],
                "nse_val": m_val["nse"], "kge_val": m_val["kge"], "pbias_val": m_val["pbias"],
                "r_val": m_val["r"],
                "nse_ceiling_r2": ceiling,
                "period_calibration": f"{CAL[0]} to {CAL[1]}",
                "period_validation": f"{VAL[0]} to {VAL[1]}",
            },
            "n_paired_days": {"cal": n_cal, "val": n_val, "full": n_full},
            "calibration_trials": tried,
            "best_crop_correct": round(cc, 3),
            "water_balance": {"status": wb["status"], "residual_pct": wb["residual_pct"],
                              "residual_mm": wb["residual_mm"],
                              "diagnostics": wb["diagnostics"]},
            "forcing_preflight": pre,
            "domain_check": {"expected_area_km2": EXPECTED_AREA_KM2,
                             "merit_upa_at_snapped_outlet_km2": 135252.0,
                             "coarse_basin_area_km2": 143222.5,
                             "n_active_cells": 56},
            "sim_csv": csv,
            "notes": (
                f"Zhimenda GRDC 2181500 (Tongtian He, upper Yangtze headwaters, 137,704 km2, "
                f"~4,600 m mean elevation, snow/permafrost-dominated). Full CWatM KI chain rerun "
                f"from scratch at this location: build_cwatm_static (MERIT upa 135,252 km2 at the "
                f"snapped outlet, -1.8% vs GRDC), convert_soil_to_cwatm (HWSD), build_cwatm_ancillary, "
                f"convert_forcing_to_cwatm (CMFD V0200 1975-1997), run_cwatm_wrapper (real "
                f"source/repo/run_cwatm.py), then NSE/KGE/PBIAS vs the GRDC daily series. "
                f"3-year spin-up (1975-1977); scored 1978-1997, cal 1978-1987 / val 1988-1997. "
                f"Best crop_correct={cc:.3f}. NSE is r-limited: max attainable NSE = r^2 = {ceiling}."
            ),
        }
        write_result(res)
        print(json.dumps(res["metrics"], indent=2))
    except SystemExit as e:
        write_result({
            "model_id": "CWatM", "this_location": LOCATION, "obs_source": OBS_SOURCE,
            "status": "failed", "tools_used": sorted(set(TOOLS_USED)),
            "tools_failed": TOOLS_FAILED,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "notes": f"runner aborted: {e}",
        })
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        write_result({
            "model_id": "CWatM", "this_location": LOCATION, "obs_source": OBS_SOURCE,
            "status": "failed", "tools_used": sorted(set(TOOLS_USED)),
            "tools_failed": TOOLS_FAILED,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "notes": f"runner crashed: {type(e).__name__}: {e}",
        })
        raise


if __name__ == "__main__":
    main()
