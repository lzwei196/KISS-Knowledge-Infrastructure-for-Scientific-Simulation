#!/usr/bin/env python3
"""
CWatM VERIFIER runner — daily discharge at 蚌埠 (Bengbu) gauge 51080, Huai River.

Second location for the CWatM consistency check (real case was 九江 on the
Yangtze).  Chains the same KI tools end-to-end and is RESUMABLE: every stage
checks for its own outputs and skips if present.

  s2  tools/build_cwatm_static.py       MERIT-Hydro + ESA-CCI-LC -> the model grid
      tools/convert_soil_to_cwatm.py    HWSD -> van Genuchten stack
      tools/build_cwatm_ancillary.py    crop coefficients, intercept caps, dzRel
  s1  tools/convert_forcing_to_cwatm.py CMFD daily 0.1deg -> 0.25deg CWatM NetCDF
                                        (+ real tmin/tmax from the 3-hourly archive)
  s3  tools/run_cwatm_wrapper.py        run the real CWatM (source/repo/run_cwatm.py)
  s4  ki_tools_common.metrics.all_metrics   NSE / KGE / R / PBIAS / RMSE

Calibration follows the real case exactly: if the calibration-period PBIAS
exceeds --pbias_tol, `crop_correct` (the HIGH-sensitivity ET multiplier,
range 0.8-1.5) is stepped and the model re-run, up to MAX_ITER times.  Every
iteration's output is kept under output_iter<N>/ so a relaunch reuses it.

Writes the verifier result object to detached/verify_1/result.json.
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
CASE = f"{ROOT}/cwatm_bengbu"
CWATM_DIR = f"{ROOT}/source/repo"
PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
STATE = f"{ROOT}/detached/verify_1"

OBS = "/mnt/disk1/Hydrocraft_server/data/obs/BB/51080_bengbu.txt"
MERIT = "/mnt/disk1/Hydrocraft_server/data/merit_hydro"
ESA_LC = "/mnt/datasets/vegetation/ESA_CCI_LC_global/ESA_CCI_LC_global_2015_01deg.tif"
HWSD = "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER"
CMFD_DAILY = "/media/server/hc_ssd/forcing/Data_forcing_01dy_010deg"
CMFD_3HR_TEMP = "/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg/Temp"

GAUGE_LON, GAUGE_LAT = 117.3758, 32.9633
EXPECTED_AREA_KM2 = 121330.0
BBOX = ["30.75", "35.0", "111.75", "117.75"]
RES = 0.25
SPINUP_START, RUN_START, RUN_END = "1979-01-01", "1982-01-01", "1997-12-31"
CAL = ("1982-01-01", "1989-12-31")
VAL = ("1990-01-01", "1997-12-31")

# GDAL in this env needs libstdc++ preloaded (TLS static block).
ENV = dict(os.environ, LD_PRELOAD="/lib/x86_64-linux-gnu/libstdc++.so.6")

MAX_ITER = int(os.environ.get("CWATM_MAX_ITER", "3"))
PBIAS_TOL = 12.0

TOOLS_USED, TOOLS_FAILED = [], []


def log(*a):
    print(f"[{datetime.now():%H:%M:%S}]", *a, flush=True)


def sh(cmd, tool):
    log("RUN", " ".join(str(c) for c in cmd))
    p = subprocess.run([str(c) for c in cmd], env=ENV, text=True, capture_output=True)
    if p.returncode != 0:
        log("STDOUT tail:", p.stdout[-3000:])
        log("STDERR tail:", p.stderr[-3000:])
        TOOLS_FAILED.append(f"{tool}: exit {p.returncode}")
        raise SystemExit(f"command failed ({p.returncode}): {cmd[0]}")
    if tool not in TOOLS_USED:
        TOOLS_USED.append(tool)
    return p.stdout


# ----------------------------------------------------------------- s2 static
def stage_static():
    if os.path.exists(f"{CASE}/static/static_meta.json"):
        log("s2 static: complete, skipping")
        TOOLS_USED.append("build_cwatm_static.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_static.py",
        "--gauge_lon", GAUGE_LON, "--gauge_lat", GAUGE_LAT,
        "--bbox", *BBOX, "--res", RES,
        "--merit_dir", MERIT, "--esa_lc", ESA_LC,
        "--expected_area_km2", EXPECTED_AREA_KM2,
        "--out_dir", f"{CASE}/static"], "build_cwatm_static.py")


def stage_soil():
    if os.path.exists(f"{CASE}/soil/percolationImp.nc"):
        log("s2 soil: complete, skipping")
        TOOLS_USED.append("convert_soil_to_cwatm.py")
        return
    sh([PY, f"{TOOLS}/convert_soil_to_cwatm.py", "--source", "hwsd",
        "--input_dir", HWSD, "--bbox", *BBOX, "--resolution", RES,
        "--output_dir", f"{CASE}/soil"], "convert_soil_to_cwatm.py")


def stage_ancillary():
    if os.path.exists(f"{CASE}/ancillary/relativeElevation.nc"):
        log("s2 ancillary: complete, skipping")
        TOOLS_USED.append("build_cwatm_ancillary.py")
        return
    sh([PY, f"{TOOLS}/build_cwatm_ancillary.py",
        "--static_dir", f"{CASE}/static", "--output_dir", f"{CASE}/ancillary"],
       "build_cwatm_ancillary.py")


# ---------------------------------------------------------------- s1 forcing
def stage_forcing():
    out = f"{CASE}/forcing"
    need = ["precipitation", "tavg", "qair", "psurf", "wind", "rsds", "rsdl", "tmin", "tmax"]
    if all(os.path.exists(f"{out}/{v}.nc") for v in need):
        log("s1 forcing: complete, skipping")
        TOOLS_USED.append("convert_forcing_to_cwatm.py")
        return
    sh([PY, f"{TOOLS}/convert_forcing_to_cwatm.py",
        "--forcing_dir", CMFD_DAILY, "--forcing_type", "cmfd", "--bbox", *BBOX,
        "--start_date", SPINUP_START, "--end_date", RUN_END,
        "--target_res", RES, "--resume",
        "--tminmax_3hr_dir", CMFD_3HR_TEMP,
        "--output_dir", out], "convert_forcing_to_cwatm.py")
    missing = [v for v in need if not os.path.exists(f"{out}/{v}.nc")]
    if missing:
        raise SystemExit(f"forcing incomplete: {missing}")


# ------------------------------------------------------- grid sanity preflight
def check_grids():
    import netCDF4 as nc
    ref = nc.Dataset(f"{CASE}/static/MaskMap.nc")
    rlat, rlon = np.array(ref["lat"][:]), np.array(ref["lon"][:])
    ref.close()
    for d, files in ((f"{CASE}/forcing", ["precipitation.nc", "tavg.nc", "tmin.nc", "tmax.nc",
                                          "qair.nc", "psurf.nc", "wind.nc", "rsds.nc", "rsdl.nc"]),
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


# -------------------------------------------------------------------- s3 run
def write_settings(crop_correct, out_dir):
    src = open(f"{CASE}/settings_bengbu.ini").read()
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
        return csv
    os.makedirs(out_dir, exist_ok=True)
    settings = write_settings(crop_correct, out_dir)
    sh([PY, f"{TOOLS}/run_cwatm_wrapper.py", "--settings", settings,
        "--cwatm_dir", CWATM_DIR, "--flags=-q"], "run_cwatm_wrapper.py")
    if not os.path.exists(csv):
        raise SystemExit(f"CWatM produced no {csv}")
    return csv


# ------------------------------------------------------------------ s4 score
def read_sim(csv):
    """CWatM TSS csv: 3 preamble lines, then Date,G1 with DD/MM/YYYY."""
    df = pd.read_csv(csv, skiprows=3)
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    return pd.Series(df.iloc[:, 1].astype(float).values, index=df["Date"], name="sim")


def read_obs():
    """51080 Bengbu daily Q (m3/s). Missing days are coded -99.9."""
    df = pd.read_csv(OBS, sep="\t", encoding="latin-1")
    df["dates"] = pd.to_datetime(df["dates"])
    df = df[df["Q"] > -90]
    return pd.Series(df["Q"].astype(float).values, index=df["dates"], name="obs")


def score(sim, obs, a, b):
    from ki_tools_common.metrics import all_metrics
    j = pd.concat([sim, obs], axis=1).dropna().loc[a:b]
    if len(j) < 2:
        return None, 0
    # all_metrics returns UPPERCASE keys ('NSE','KGE','PBIAS','RMSE') plus
    # lowercase 'r'; this driver indexes lowercase everywhere, so normalise once.
    m = all_metrics(j["obs"].values, j["sim"].values)
    return {k.lower(): (None if not np.isfinite(v) else round(float(v), 4))
            for k, v in m.items()}, len(j)


def water_balance(out_dir):
    """Basin-mean P, ET, runoff from the monthly maps (mm/yr) + closure residual."""
    import netCDF4 as nc
    try:
        mask = np.array(nc.Dataset(f"{CASE}/static/MaskMap.nc")["MaskMap"][:]) == 1
        area = np.array(nc.Dataset(f"{CASE}/static/CellArea.nc")["CellArea"][:])
        area = np.where(mask, area, 0.0)
        tot = area.sum()

        def mean_mm_per_day(f, v):
            ds = nc.Dataset(f"{out_dir}/{f}")
            a = np.array(ds.variables[v][:], dtype=float)
            a = np.where(np.isfinite(a), a, 0.0)
            w = (a * area[None, :, :]).sum(axis=(1, 2)) / tot
            return float(np.mean(w)) * 1000.0

        p = mean_mm_per_day("Precipitation_monthavg.nc", "Precipitation")
        et = mean_mm_per_day("totalET_monthavg.nc", "totalET")
        ro = mean_mm_per_day("runoff_monthavg.nc", "runoff")
        res = p - et - ro
        return {"status": "PASS" if abs(res) < 0.05 * max(p, 1e-9) else "WARN",
                "residual_mm": round(res * 365.25, 2),
                "residual_pct": round(100 * res / p, 2) if p else None,
                "diagnostics": [f"P={p*365.25:.0f} ET={et*365.25:.0f} "
                                f"runoff={ro*365.25:.0f} mm/yr basin-mean"]}
    except Exception as e:  # non-fatal
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": [f"water-balance maps unavailable: {e}"]}


def main():
    os.makedirs(STATE, exist_ok=True)
    os.chdir(ROOT)

    stage_static()
    stage_soil()
    stage_ancillary()
    stage_forcing()
    check_grids()
    TOOLS_USED.append("ki_tools_common.metrics.all_metrics")

    obs = read_obs()
    tried, best = [], None
    cc = 1.00
    for it in range(MAX_ITER):
        csv = stage_run(cc, it)
        sim = read_sim(csv)
        m_cal, n_cal = score(sim, obs, *CAL)
        if m_cal is None or m_cal.get("pbias") is None:
            raise SystemExit(f"iter{it}: no scorable sim/obs overlap over CAL {CAL} (n={n_cal})")
        log(f"iter{it} crop_correct={cc:.3f}  cal NSE={m_cal['nse']} "
            f"PBIAS={m_cal['pbias']} (n={n_cal})")
        tried.append({"iter": it, "crop_correct": round(cc, 3), **m_cal})
        if best is None or abs(m_cal["pbias"]) < abs(best[1]["pbias"]):
            best = (it, m_cal, cc, csv)
        if abs(m_cal["pbias"]) <= PBIAS_TOL:
            break
        # Q too high -> more ET -> raise crop_correct (and vice versa). ET responds
        # sub-linearly, so move crop_correct by ~half the fractional runoff error,
        # clipped to the documented 0.8-1.5 range.
        step = 1.0 + 0.5 * (m_cal["pbias"] / 100.0)
        cc = float(np.clip(cc * step, 0.8, 1.5))
        if any(abs(cc - t["crop_correct"]) < 0.005 for t in tried):
            log("crop_correct converged / saturated; stopping calibration")
            break

    it, _, cc, csv = best
    sim = read_sim(csv)
    out_dir = f"{CASE}/output_iter{it}"
    m_cal, n_cal = score(sim, obs, *CAL)
    m_val, n_val = score(sim, obs, *VAL)
    m_full, n_full = score(sim, obs, CAL[0], VAL[1])

    meta = json.load(open(f"{CASE}/static/static_meta.json"))
    wb = water_balance(out_dir)

    notes = (
        f"Verifier location 2 of the CWatM consistency check: Huai River at Bengbu "
        f"gauge 51080 ({GAUGE_LON}E {GAUGE_LAT}N), daily discharge, versus the "
        f"real-case Yangtze at Jiujiang. SKILL.md documents build_cwatm_static.py "
        f"and build_cwatm_ancillary.py but NEITHER EXISTS in tools/, and "
        f"convert_forcing_to_cwatm.py lacks the documented --target_res, --resume "
        f"and --tminmax_3hr_dir flags, so all three were authored/restored to the "
        f"documented interface before this run. The static stack self-verifies: "
        f"MERIT upa at the snapped gauge pixel = {meta['upa_outlet_km2']:,.0f} km2 and "
        f"the 3-arcsec traced basin = {meta['area_fine_km2']:,.0f} km2 against the "
        f"official 121,330 km2 (+1.6% / +2.0%); the 0.25-deg mask of "
        f"{meta['n_cells']} cells sums to {meta['area_km2']:,.0f} km2 (+4.6%), which "
        f"puts a small positive floor under PBIAS. Run 1979-1997 with a 3-year "
        f"spin-up (same recipe as Jiujiang), scored 1982-1997 on "
        f"{n_full} paired days; crop_correct calibrated on {CAL[0]}..{CAL[1]} PBIAS, "
        f"validated on {VAL[0]}..{VAL[1]}. Resolution 0.25 deg rather than the 0.5 deg "
        f"used at Jiujiang because the Huai above Bengbu is 12x smaller than the "
        f"Yangtze above Jiujiang; 0.5 deg would leave only ~48 active cells. "
        f"ESA-CCI-LC class 20 ('cropland, irrigated or post-flooding') covers 53% of "
        f"this basin, so the unchanged class mapping puts 56% of the area in "
        f"irrPaddy, which ponds up to 50 mm of rainfall before runoff."
    )

    res = {
        "model_id": "CWatM",
        "this_location": "Bengbu",
        "obs_source": "ObservedQ",
        "status": "completed",
        "tools_used": sorted(set(TOOLS_USED)),
        "tools_failed": TOOLS_FAILED,
        "metrics": {
            "nse": m_full["nse"], "kge": m_full["kge"], "pbias": m_full["pbias"],
            "r": m_full["r"], "rmse": m_full["rmse"],
            "period": f"{CAL[0]} to {VAL[1]} (spin-up {SPINUP_START})",
            "nse_cal": m_cal["nse"], "kge_cal": m_cal["kge"], "pbias_cal": m_cal["pbias"],
            "r_cal": m_cal["r"],
            "nse_val": m_val["nse"], "kge_val": m_val["kge"], "pbias_val": m_val["pbias"],
            "r_val": m_val["r"],
            "period_calibration": f"{CAL[0]} to {CAL[1]}",
            "period_validation": f"{VAL[0]} to {VAL[1]}",
        },
        "water_balance": wb,
        "n_paired_days": {"cal": n_cal, "val": n_val, "full": n_full},
        "calibration_trials": tried,
        "best_crop_correct": round(cc, 3),
        "variable": "discharge",
        "obs_shape": "point_time_series",
        "static_meta": meta,
        "sim_csv": csv,
        "notes": notes,
    }
    with open(f"{STATE}/result.json", "w") as fh:
        json.dump(res, fh, indent=2, ensure_ascii=False)
    log("WROTE", f"{STATE}/result.json")
    print(json.dumps(res["metrics"], indent=2))


if __name__ == "__main__":
    main()
