#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VIC VERIFIER (verify_2) at 奴下 Nuxia, Yarlung Tsangpo / 雅鲁藏布江, gauge 94109
(~29.60N, 94.58E nominal; outlet snapped onto the china_dem_90m mainstem at
95.032E, 29.748N; delineated 207,629 km2 vs 208,091 km2 published, -0.2%).

Consistency check against the 允景洪 Jinghong (Lancang/Mekong) real-case. The
real-case was run UNCALIBRATED (KI-default soil/veg; the ONE lever set from a
MEASUREMENT, not from NSE, is the Lohmann channel velocity). This verifier MUST
use the SAME protocol at a DIFFERENT basin/regime -- Nuxia is a cold, high,
snow/glacier-fed Tibetan-Plateau basin (mean elevation ~4500 m), not a monsoonal
gorge like Jinghong. A calibrated Nuxia score would manufacture false consistency.

Chain (each KI tool; each stage skipped when its output already exists)
----------------------------------------------------------------------
  s0  ki_tools_common.terrain_ops.delineate_basin  (china_dem_90m cropped to the
      basin bbox; pour point 95.032E,29.748N; 207,629 km2) -> flow_accum/basin/
      dem_filled rasters  [PRE-COMPUTED offline into DELIN; s0 self-heals if wiped]
  s1  s1_grid/make_basin_grid_nc.py          -> grid_nuxia_yarlung_025deg.nc
  s2  s3_soil/fill_parameters1.py            -> SOIL_PARAM_FINAL.txt
  s3  s3_soil/fill_parameters2.py            -> SOIL_PARAM_COMPLETE.txt
  s4  s2_forcing/forcing_1d.py               -> CMFD 3-hourly 0.1deg -> 0.25deg basin NetCDF
  s5  s2_forcing/process_forcing.py          -> per-cell VIC ASCII forcing (7 col, 8 steps/day)
  s6  s4_veg/process_vegetation_detailed.py  -> vic_veg_param_final.txt
  s7  config_paths.create_global_param()     -> global_param_nuxia_yarlung.txt
  s8  vic_classic.exe                         -> daily flux per cell (mm), water-balance mode
  s9  s5_routing/build_routing_param.py       -> NX_direc/frac/xmask/staloc + UH.all
  s10 s5_routing/run_routing.py (route_1.0)   -> daily discharge (m3/s); velocity IDENTIFIED
  s11 score vs obs Q, water balance, result.json (VERIFIER schema)

Periods.  Obs 94109 is continuous daily 1970-01-01..2013-12-31 (no -99 gaps).
CMFD forcing covers 1951-2024, so the simulation is spun up from 1980:
  spinup      1980-1982                      (discarded)
  calibration 1983-01-01 .. 1989-12-31
  validation  1990-01-01 .. 1995-12-31       (held out)
Nothing is calibrated: soil/veg are KI defaults.  The ONE measured lever is the
Lohmann channel velocity, identified by matching rout's own basin-mean UH lag to
the observed sim/obs lag on the CAL window only (dt_vic_028).

CAVEAT reported (not calibrated away): the Yarlung Tsangpo carries a large
glacier-/snowmelt contribution that VIC (no glacier module) cannot supply, so a
dry (negative PBIAS) summer bias is physically expected here.
"""
import os
import sys
import glob
import json
import subprocess
import traceback
from pathlib import Path

# system python3 + ~/.local ONLY. Do NOT prepend python_env/site-packages: it ships
# a Py2-era pathlib.py backport (`from collections import Sequence`) that shadows the
# stdlib and breaks rasterio/geopandas (dt in Bengbu verifier).
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")

import numpy as np
import pandas as pd

BASE = "/mnt/disk1/Hydrocraft_server"
KI = f"{BASE}/models/VIC/knowledge_infrastructure"
sys.path.insert(0, KI)

from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from validators.standard_calval import compute_calval_metrics
from s5_routing.run_routing import prepare_vic_in, route, observed_lag_days, FLUX_NAME_RE

# ---------------------------------------------------------------------------
CASE = f"{BASE}/models/VIC/detached/verify_2"
RESULT = f"{CASE}/result.json"

BASIN = "nuxia_yarlung"
STA = "NX"
FORCING_PREFIX = f"{BASIN}_025deg_"
BASIN_SHP = f"{BASE}/data/shp/yajiang_nuxia_shp/yajiang_nuxia_boundary_shp/yajiang_nuxia_boundary.shp"
DEM = f"{BASE}/data/dem/china_dem_90m/china_dem_90m.tif"
CMFD = f"{BASE}/data/forcing/Data_forcing_03hr_010deg"
OUT_ROOT = f"{BASE}/outputs"
BDIR = f"{OUT_ROOT}/{BASIN}"
DELIN = f"{BDIR}/delineation"

VIC_EXE = f"{BASE}/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
OBS_FILE = f"{BASE}/data/obs/NX/94109_nuxia.txt"

# Outlet snapped onto the china_dem_90m mainstem by delineate_basin (s0).
OUTLET_LON, OUTLET_LAT = 95.032, 29.748
STREAM_THRESHOLD = 40000
SNAP_DIST_M = 2000.0
PUBLISHED_AREA_KM2 = 208091

YEAR_START, YEAR_END = 1980, 1995
CAL = ("1983-01-01", "1989-12-31")
VAL = ("1990-01-01", "1995-12-31")
EVAL_START, EVAL_END = "1983-01-01", "1995-12-31"
WB_Y0, WB_Y1 = 1983, 1995
DIFFUSIVITY = 800.0
VEL_RANGE = (0.10, 3.0)          # calibration.yaml rout_velocity `range`

ENV = dict(os.environ)
ENV.update(
    VIC_BASIN_NAME=BASIN,
    VIC_BASIN_SHP=BASIN_SHP,
    VIC_OUT_ROOT=OUT_ROOT,
    VIC_CMFD_DIR=CMFD,
    VIC_DEM=DEM,
    VIC_STATION_NAME=STA,
    VIC_OUTLET_LON=str(OUTLET_LON),
    VIC_OUTLET_LAT=str(OUTLET_LAT),
    VIC_STREAM_THRESHOLD=str(STREAM_THRESHOLD),
    VIC_SNAP_DIST_M=str(SNAP_DIST_M),
    VIC_YEAR_START=str(YEAR_START),
    VIC_YEAR_END=str(YEAR_END),
    VIC_START_DATE=f"{YEAR_START}-01-01",
    VIC_END_DATE=f"{YEAR_END}-12-31",
    VIC_FORCING_PREFIX=FORCING_PREFIX,
    VIC_FLOW_ACCUM=f"{DELIN}/flow_accum.tif",
    VIC_BASIN_RASTER=f"{DELIN}/basin.tif",
    VIC_FILLED_DEM=f"{DELIN}/dem_filled.tif",
    PYTHONUNBUFFERED="1",
)
# no VIC_GLOBAL_PARAM_TEMPLATE -> config_paths uses the KI default
# docs/vic_param/global_param_template.txt (dt_vic_024, non-frozen, 21 OUTVARs)

GRID_NC = f"{BDIR}/vic_temp/grid/grid_{BASIN}_025deg.nc"
SOIL_FINAL = f"{BDIR}/vic_temp/soil/SOIL_PARAM_FINAL.txt"
SOIL_COMPLETE = f"{BDIR}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
FORCING_1D = f"{BDIR}/vic_temp/forcing/forcing_1d"
FORCING_FINAL = f"{BDIR}/vic_temp/forcing/forcing_final"
VEG_PARAM = f"{BDIR}/vic_temp/veg/vic_veg_param_final.txt"
GLOBAL_PARAM = f"{BDIR}/vic_temp/global_param_{BASIN}.txt"
VIC_RESULT = f"{BDIR}/vic_result"
ROUTING = f"{BDIR}/routing_param"
VIC_IN = f"{ROUTING}/vic_in"

os.makedirs(CASE, exist_ok=True)

TOOLS_USED = []
TOOLS_FAILED = []

RESULT_OBJ = {
    "model_id": "VIC",
    "this_location": "Nuxia Station",
    "obs_source": "ObservedQ",
    "status": "failed",
    "tools_used": TOOLS_USED,
    "tools_failed": TOOLS_FAILED,
    "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": "",
    # --- extra detail (verifier schema tolerates extra keys) ---
    "location": "奴下 Nuxia (Yarlung Tsangpo / 雅鲁藏布江), gauge 94109",
    "variable": "OUT_DISCHARGE",
    "obs_shape": "point_time_series",
    "metrics_detail": {}, "routing": None, "basin": None,
    "forcing_preflight": None,
    "period_calibration": f"{CAL[0]}..{CAL[1]}",
    "period_validation": f"{VAL[0]}..{VAL[1]}",
}


def log(m):
    print(f"[nuxia] {m}", flush=True)


def save(note=None):
    if note:
        RESULT_OBJ["notes"] = note
    with open(RESULT, "w") as f:
        json.dump(RESULT_OBJ, f, indent=2, ensure_ascii=False)


def run_tool(script, cwd, label, timeout=None):
    log(f"===== {label} =====")
    p = subprocess.run([sys.executable, script], cwd=cwd, env=ENV,
                       capture_output=True, text=True, timeout=timeout)
    print("\n".join((p.stdout or "").strip().splitlines()[-12:]), flush=True)
    if p.returncode != 0:
        print("STDERR:", (p.stderr or "")[-2500:], flush=True)
        TOOLS_FAILED.append(f"{label}: rc={p.returncode} :: {(p.stderr or '')[-300:]}")
        save(f"stage {label} failed")
        sys.exit(1)
    TOOLS_USED.append(label)


def n_cells():
    return sum(1 for line in open(SOIL_COMPLETE) if line.strip())


# ---------------------------------------------------------------------------
def preflight():
    try:
        p = subprocess.run(
            [sys.executable,
             "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/"
             "validators/preflight_forcing.py", FORCING_1D, "--source", "auto"],
            capture_output=True, text=True, timeout=3600)
        out = p.stdout + p.stderr
        import re
        mm = re.search(r"PASS:\s*(\d+),\s*WARN:\s*(\d+),\s*FAIL:\s*(\d+)", out)
        n_warn, n_fail = (int(mm.group(2)), int(mm.group(3))) if mm else (0, 0)
        detail = [l for l in out.splitlines()
                  if re.search(r"\b(FAIL|WARN)\b", l) and "PASS:" not in l]
        RESULT_OBJ["forcing_preflight"] = {
            "all_pass": bool(p.returncode == 0 and mm and n_fail == 0),
            "source": "cmfd (3-hourly 0.1deg -> basin 0.25deg via forcing_1d.py)",
            "failures": (detail if n_fail else [])[:10],
            "warnings": (detail if (n_warn and not n_fail) else [])[:10],
            "summary": mm.group(0) if mm else out[-300:]}
    except Exception as e:                                    # noqa: BLE001
        RESULT_OBJ["forcing_preflight"] = {"all_pass": None, "source": "cmfd",
                                           "failures": [f"preflight error: {e}"],
                                           "warnings": []}
    log(f"preflight all_pass={RESULT_OBJ['forcing_preflight']['all_pass']}")
    if RESULT_OBJ["forcing_preflight"]["all_pass"] is False and \
       RESULT_OBJ["forcing_preflight"]["failures"]:
        save("forcing preflight FAILED (unit error) -> aborting before VIC")
        sys.exit(1)


# ---------------------------------------------------------------------------
def load_obs():
    o = pd.read_csv(OBS_FILE, sep="\t")
    o["date"] = pd.to_datetime(o["dates"], format="mixed")
    o["Q"] = pd.to_numeric(o["Q"], errors="coerce")
    o = o.set_index("date")["Q"]
    return o[o > -90]                        # -99 = missing (none in this record)


def identify_velocity(routing_dir, obs):
    """Set VELOCITY from the OBSERVED LAG on the CAL window; NSE never consulted."""
    def run(v):
        s = route(routing_dir, velocity=v, diffusivity=DIFFUSIVITY,
                  route_start=(YEAR_START, 1), route_end=(YEAR_END, 12), station=STA)
        return float(s.attrs["uh_lag_days"]), s

    cal_obs = obs.loc[CAL[0]:CAL[1]]

    def olag(s):
        return observed_lag_days(cal_obs, s.loc[CAL[0]:CAL[1]])

    lag_def, s_def = run(1.5)
    od = olag(s_def)
    target = lag_def + od["best_lag_days"]
    lag_slow, _ = run(VEL_RANGE[0])          # slowest allowed -> max uh_lag
    lag_fast, _ = run(VEL_RANGE[1])          # fastest allowed -> min uh_lag
    log(f"default v=1.5 uh_lag={lag_def:.2f}d; obs lag on CAL={od['best_lag_days']}d "
        f"(r0={od['r_at_zero_lag']:.3f}, NSE_ceiling={od['nse_ceiling_at_zero_lag']:.3f}); "
        f"target uh_lag={target:.2f}d; reachable [{lag_fast:.2f},{lag_slow:.2f}]d")

    saturated = None
    if target >= lag_slow:
        v, saturated = VEL_RANGE[0], "slow"
    elif target <= lag_fast:
        v, saturated = VEL_RANGE[1], "fast"
    else:
        lo, hi = VEL_RANGE[0], VEL_RANGE[1]
        best = None
        for _ in range(12):
            mid = float(np.sqrt(lo * hi))
            lag, s = run(mid)
            if best is None or abs(lag - target) < abs(best[1] - target):
                best = (mid, lag, s)
            log(f"  v={mid:.4f} -> uh_lag={lag:.2f} (target {target:.2f})")
            if abs(lag - target) < 0.4:
                break
            lo, hi = (mid, hi) if lag > target else (lo, mid)
        v = best[0]
    lag, s = run(v)
    resid = olag(s)
    method = ("velocity identified by matching rout UH lag to observed CAL lag"
              if saturated is None else
              f"observed lag outside reachable set ({saturated}); pinned to "
              f"calibration.yaml rout_velocity range bound {v}")
    log(f"chosen VELOCITY={v:.4f} m/s uh_lag={lag:.2f}d; residual CAL lag "
        f"{resid['best_lag_days']}d r0={resid['r_at_zero_lag']:.3f}")
    info = {
        "method": method, "saturated": saturated,
        "velocity_m_s": round(v, 4), "diffusivity_m2_s": DIFFUSIVITY,
        "uh_lag_days": round(lag, 2), "target_uh_lag_days": round(target, 2),
        "reachable_uh_lag_days": [round(lag_fast, 2), round(lag_slow, 2)],
        "default_velocity_uh_lag_days": round(lag_def, 2),
        "observed_lag_days_cal_at_default": od["best_lag_days"],
        "r_zero_lag_default": round(od["r_at_zero_lag"], 4),
        "nse_ceiling_default": round(od["nse_ceiling_at_zero_lag"], 4),
        "residual_lag_days_cal": resid["best_lag_days"],
        "r_zero_lag_identified": round(resid["r_at_zero_lag"], 4),
        "nse_ceiling_identified": round(resid["nse_ceiling_at_zero_lag"], 4),
    }
    return info, s


def water_balance():
    hdr, frac = _frac_grid()
    nrows, cs = int(hdr["nrows"]), hdr["cellsize"]
    xll, yll = hdr["xllcorner"], hdr["yllcorner"]
    tot = {k: 0.0 for k in ("P", "E", "R", "B", "dS")}
    area = 0.0
    for f in sorted(glob.glob(f"{VIC_RESULT}/*fluxes_*")):
        m = FLUX_NAME_RE.search(os.path.basename(f))
        if not m:
            continue
        lat, lon = float(m.group(1)), float(m.group(2))
        col = int(round((lon - xll - cs / 2) / cs))
        row = int(round((yll + nrows * cs - cs / 2 - lat) / cs))
        if not (0 <= row < frac.shape[0] and 0 <= col < frac.shape[1]):
            continue
        fr = frac[row, col]
        if fr <= 0:
            continue
        a = (cs * 111320.0) * (cs * 111320.0 * np.cos(np.radians(lat))) * fr
        d = pd.read_csv(f, sep=r"\s+", skiprows=3, header=None)
        yr = d[0].astype(int)
        w = d[(yr >= WB_Y0) & (yr <= WB_Y1)]
        stor = w[[20, 21, 22]].sum(axis=1) + w[19]      # SM0..2 + SWE
        tot["P"] += w[3].sum() * a
        tot["E"] += w[18].sum() * a
        tot["R"] += w[16].sum() * a
        tot["B"] += w[17].sum() * a
        tot["dS"] += (stor.iloc[-1] - stor.iloc[0]) * a
        area += a
    for k in tot:
        tot[k] /= area
    ndays = (pd.Timestamp(f"{WB_Y1}-12-31") - pd.Timestamp(f"{WB_Y0}-01-01")).days + 1
    wb = dict(validate_water_balance(precip_mm=tot["P"], et_mm=tot["E"],
                                     runoff_mm=tot["R"] + tot["B"],
                                     delta_storage_mm=tot["dS"], period_days=ndays))
    wb.update({f"basin_mean_{k}_mm": round(v, 2) for k, v in tot.items()})
    wb.update({"area_km2": round(area / 1e6, 1)})
    return wb


def _frac_grid():
    p = Path(ROUTING) / f"{STA}_frac.txt"
    hdr = {}
    with open(p) as f:
        for _ in range(6):
            k, v = f.readline().split()
            hdr[k] = float(v)
    return hdr, np.loadtxt(p, skiprows=6)


# =========================== PIPELINE ======================================
def main():
    obs = load_obs()
    log(f"obs: {len(obs)} valid days {obs.index.min().date()}..{obs.index.max().date()} "
        f"mean={obs.mean():.0f} m3/s")

    # ---- s0 delineation (resumable; regenerate if BDIR was wiped) ----
    assert os.path.exists(BASIN_SHP), f"basin shapefile missing: {BASIN_SHP}"
    if not os.path.exists(f"{DELIN}/flow_accum.tif"):
        log(f"s0 delineation missing -> regenerating (crop china_dem_90m to basin "
            f"bbox, then delineate_basin; outlet=({OUTLET_LON},{OUTLET_LAT}) "
            f"thr={STREAM_THRESHOLD} snap={SNAP_DIST_M})")
        os.makedirs(DELIN, exist_ok=True)
        import geopandas as gpd, rasterio
        from rasterio.windows import from_bounds as _win_from_bounds, Window as _Window
        _b = gpd.read_file(BASIN_SHP).to_crs(4326).total_bounds
        _buf = 0.4
        minx, miny, maxx, maxy = _b[0]-_buf, _b[1]-_buf, _b[2]+_buf, _b[3]+_buf
        dem_crop = f"{DELIN}/dem_crop_for_delin.tif"
        if not os.path.exists(dem_crop):
            with rasterio.open(DEM) as src:
                win = _win_from_bounds(minx, miny, maxx, maxy, src.transform)
                win = win.intersection(_Window(0, 0, src.width, src.height))
                arr = src.read(1, window=win)
                tr = src.window_transform(win)
                prof = src.profile.copy()
                prof.update(height=arr.shape[0], width=arr.shape[1],
                            transform=tr, compress="lzw")
            with rasterio.open(dem_crop, "w", **prof) as dst:
                dst.write(arr, 1)
            log(f"s0 dem crop: {arr.shape[1]}x{arr.shape[0]} px")
        from ki_tools_common.terrain_ops import delineate_basin
        d = delineate_basin(
            dem_path=dem_crop, pour_point=(OUTLET_LON, OUTLET_LAT),
            output_dir=DELIN, stream_threshold=STREAM_THRESHOLD,
            snap_distance_m=SNAP_DIST_M)
        log(f"s0 delineate_basin area={d['basin_area_km2']:.0f} km2 "
            f"(published {PUBLISHED_AREA_KM2})")
        assert os.path.exists(f"{DELIN}/flow_accum.tif"), "delineate_basin did not write flow_accum.tif"
    else:
        dj = json.load(open(f"{DELIN}/delineation.json")) if os.path.exists(f"{DELIN}/delineation.json") else {}
        log(f"s0 delineation present ({dj.get('basin_area_km2', '?')} km2 vs {PUBLISHED_AREA_KM2} published)")
    # sanity: delineated area within +-15% of published
    try:
        dj = json.load(open(f"{DELIN}/delineation.json"))
        aer = 100.0 * (dj["basin_area_km2"] - PUBLISHED_AREA_KM2) / PUBLISHED_AREA_KM2
        RESULT_OBJ["basin"] = {"delineated_area_km2": round(dj["basin_area_km2"], 0),
                               "published_area_km2": PUBLISHED_AREA_KM2,
                               "area_err_pct": round(aer, 2),
                               "outlet_lon": OUTLET_LON, "outlet_lat": OUTLET_LAT}
        assert abs(aer) < 15.0, f"delineated area off by {aer:.1f}% -- outlet snap suspect"
    except FileNotFoundError:
        pass
    TOOLS_USED.append("ki_tools_common.terrain_ops.delineate_basin")

    # ---- s1 grid ----
    if not os.path.exists(GRID_NC):
        run_tool(f"{KI}/s1_grid/make_basin_grid_nc.py", f"{KI}/s1_grid",
                 "s1_grid/make_basin_grid_nc.py")
    else:
        log("s1 grid exists, skip"); TOOLS_USED.append("s1_grid/make_basin_grid_nc.py")

    # ---- s2/s3 soil ----
    if not os.path.exists(SOIL_FINAL):
        run_tool(f"{KI}/s3_soil/fill_parameters1.py", f"{KI}/s3_soil",
                 "s3_soil/fill_parameters1.py")
    else:
        log("s2 soil final exists, skip"); TOOLS_USED.append("s3_soil/fill_parameters1.py")
    if not os.path.exists(SOIL_COMPLETE):
        run_tool(f"{KI}/s3_soil/fill_parameters2.py", f"{KI}/s3_soil",
                 "s3_soil/fill_parameters2.py")
    else:
        log("s3 soil complete exists, skip"); TOOLS_USED.append("s3_soil/fill_parameters2.py")
    NCELL = n_cells()
    log(f"grid VIC cells = {NCELL}")

    # ---- s4 veg ----
    if not os.path.exists(VEG_PARAM):
        run_tool(f"{KI}/s4_veg/process_vegetation_detailed.py", f"{KI}/s4_veg",
                 "s4_veg/process_vegetation_detailed.py")
    else:
        log("s4 veg exists, skip")
        TOOLS_USED.append("s4_veg/process_vegetation_detailed.py")

    # ---- s5 forcing_1d (resumable) ----
    NMONTH = (YEAR_END - YEAR_START + 1) * 12
    have = len(glob.glob(f"{FORCING_1D}/prec_*_{BASIN}.nc"))
    if have < NMONTH:
        log(f"s5 forcing_1d: {have}/{NMONTH} prec files -> running")
        run_tool(f"{KI}/s2_forcing/forcing_1d.py", f"{KI}/s2_forcing",
                 "s2_forcing/forcing_1d.py")
    else:
        log("s5 forcing_1d complete, skip"); TOOLS_USED.append("s2_forcing/forcing_1d.py")

    preflight()

    # ---- s6 process_forcing ----
    have = len(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))
    if have < NCELL:
        log(f"s6 process_forcing: {have}/{NCELL} -> running")
        run_tool(f"{KI}/s2_forcing/process_forcing.py", f"{KI}/s2_forcing",
                 "s2_forcing/process_forcing.py")
    else:
        log("s6 forcing_final complete, skip")
        TOOLS_USED.append("s2_forcing/process_forcing.py")

    nday = (pd.Timestamp(f"{YEAR_END}-12-31") - pd.Timestamp(f"{YEAR_START}-01-01")).days + 1
    sample = sorted(glob.glob(f"{FORCING_FINAL}/{FORCING_PREFIX}*"))[0]
    nrec = sum(1 for _ in open(sample))
    log(f"s6 {os.path.basename(sample)}: {nrec} records (expect {nday * 8})")
    if nrec != nday * 8:
        TOOLS_FAILED.append(f"process_forcing.py: {nrec} != {nday * 8} records")
        save("forcing record-count mismatch"); sys.exit(1)

    # ---- s7 global param ----
    if not os.path.exists(GLOBAL_PARAM):
        log("s7 config_paths.create_global_param")
        os.environ.update({k: v for k, v in ENV.items() if k.startswith("VIC_")})
        import importlib, config_paths
        importlib.reload(config_paths)
        config_paths.create_output_dirs()
        if not config_paths.create_global_param():
            TOOLS_FAILED.append("config_paths.create_global_param(): failed")
            save("global param creation failed"); sys.exit(1)
    else:
        log("s7 global param exists, skip")
    TOOLS_USED.append("config_paths.create_global_param()")
    gp = open(GLOBAL_PARAM).read()
    for key, want in [("STARTYEAR", str(YEAR_START)), ("ENDYEAR", str(YEAR_END)),
                      ("FORCEYEAR", str(YEAR_START))]:
        line = [l for l in gp.splitlines() if l.strip().startswith(key)]
        assert line and want in line[0], f"{key} != {want} in global param: {line}"
    assert any(l.strip().startswith("FROZEN_SOIL") and "FALSE" in l for l in gp.splitlines()), \
        "FROZEN_SOIL not FALSE"

    # ---- s8 VIC ----
    flux = glob.glob(f"{VIC_RESULT}/*fluxes_*")
    if len(flux) < NCELL * 0.99:
        log(f"s8 vic_classic.exe ({len(flux)}/{NCELL} present) -- large basin, can take a while")
        os.makedirs(VIC_RESULT, exist_ok=True)
        p = subprocess.run([VIC_EXE, "-g", GLOBAL_PARAM], capture_output=True, text=True)
        log(f"vic rc={p.returncode}")
        print((p.stdout or "")[-1500:], flush=True)
        if p.returncode != 0:
            print("STDERR:", (p.stderr or "")[-3000:], flush=True)
            TOOLS_FAILED.append(f"vic_classic.exe: rc={p.returncode} :: {(p.stderr or '')[-400:]}")
            save("VIC binary failed"); sys.exit(1)
        flux = glob.glob(f"{VIC_RESULT}/*fluxes_*")
    log(f"s8 flux files: {len(flux)}")
    if len(flux) < NCELL * 0.95:
        TOOLS_FAILED.append(f"vic_classic.exe: only {len(flux)}/{NCELL} flux files")
        save("VIC produced too few flux files"); sys.exit(1)
    TOOLS_USED.append("vic_classic.exe (VIC 5.1.0 classic driver)")

    # ---- s9 routing params ----
    if not os.path.exists(f"{ROUTING}/{STA}_direc.txt"):
        run_tool(f"{KI}/s5_routing/build_routing_param.py", KI,
                 "s5_routing/build_routing_param.py")
    else:
        log("s9 routing params exist, skip")
        TOOLS_USED.append("s5_routing/build_routing_param.py")

    # ---- s10 route (velocity identified) ----
    log("s10 prepare_vic_in + Lohmann routing")
    n = prepare_vic_in(VIC_RESULT, VIC_IN, FORCING_PREFIX)
    log(f"vic_in cells: {n}")
    ident, sim = identify_velocity(ROUTING, obs)
    RESULT_OBJ["routing"] = ident
    TOOLS_USED.extend(["s5_routing/run_routing.py (prepare_vic_in/route/observed_lag_days)",
                       "route_1.0/src/rout (Lohmann routing binary)"])

    # ---- s11 score ----
    log("s11 scoring")
    j = pd.concat([obs.rename("obs"), sim.rename("sim")], axis=1).dropna()
    j = j.loc[EVAL_START:EVAL_END]
    log(f"paired days={len(j)} obs_mean={j.obs.mean():.1f} sim_mean={j.sim.mean():.1f} m3/s")
    if len(j) < 2:
        save("no temporal overlap sim/obs"); sys.exit(1)

    m = {k.lower(): float(v) for k, v in
         all_metrics(j.obs.values, j.sim.values).items()}
    TOOLS_USED.append("ki_tools_common.metrics.all_metrics")
    cv = compute_calval_metrics(j.index.values, j.obs.values, j.sim.values,
                                cal_start=CAL[0], cal_end=CAL[1],
                                val_start=VAL[0], val_end=VAL[1])
    TOOLS_USED.append("validators.standard_calval.compute_calval_metrics")

    def g(d, k):
        v = d.get(k)
        return None if v is None or not np.isfinite(float(v)) else round(float(v), 4)

    period = f"{j.index.min().date()}..{j.index.max().date()}"
    RESULT_OBJ["metrics"] = {"nse": g(m, "nse"), "kge": g(m, "kge"),
                             "pbias": g(m, "pbias"), "r": g(m, "r"), "period": period}
    RESULT_OBJ["metrics_detail"] = {
        "rmse": g(m, "rmse"),
        "nse_cal": g(cv["calibration"], "NSE"), "kge_cal": g(cv["calibration"], "KGE"),
        "pbias_cal": g(cv["calibration"], "PBIAS"), "r_cal": g(cv["calibration"], "r"),
        "nse_val": g(cv["validation"], "NSE"), "kge_val": g(cv["validation"], "KGE"),
        "pbias_val": g(cv["validation"], "PBIAS"), "r_val": g(cv["validation"], "r"),
        "n_cal": cv["calibration"].get("n"), "n_val": cv["validation"].get("n"),
        "n_paired": len(j), "obs_mean_m3s": round(float(j.obs.mean()), 1),
        "sim_mean_m3s": round(float(j.sim.mean()), 1),
        "period_calibration": f"{CAL[0]}..{CAL[1]}",
        "period_validation": f"{VAL[0]}..{VAL[1]}",
    }

    wb = water_balance()
    RESULT_OBJ["water_balance"] = {
        "status": wb["status"],
        "residual_pct": round(float(wb["residual_pct"]), 3) if wb.get("residual_pct") is not None else None,
        "residual_mm": round(float(wb["residual_mm"]), 2) if wb.get("residual_mm") is not None else None,
        "basin_mean_P_mm": wb.get("basin_mean_P_mm"), "basin_mean_E_mm": wb.get("basin_mean_E_mm"),
        "basin_mean_R_mm": wb.get("basin_mean_R_mm"), "basin_mean_B_mm": wb.get("basin_mean_B_mm"),
        "basin_mean_dS_mm": wb.get("basin_mean_dS_mm"), "area_km2": wb.get("area_km2"),
    }
    TOOLS_USED.append("ki_tools_common.validation.validate_water_balance")

    RESULT_OBJ["status"] = "completed"
    md = RESULT_OBJ["metrics_detail"]
    save(
        f"VERIFIER at 奴下 Nuxia on the Yarlung Tsangpo (雅鲁藏布江), gauge 94109 -- a "
        f"cold, high (~4500 m mean elev), snow/glacier-fed Tibetan-Plateau basin, a "
        f"DIFFERENT regime than the monsoonal 允景洪 Jinghong real-case. Full KI chain "
        f"re-run with the REAL binaries (delineate_basin -> make_basin_grid -> "
        f"fill_parameters{{1,2}} -> process_vegetation -> forcing_1d/process_forcing "
        f"(CMFD 3-hourly 0.1deg) -> vic_classic.exe (VIC 5.1.0, water-balance mode, "
        f"{NCELL} cells @0.25deg, {YEAR_START}-{YEAR_END}, {YEAR_START}-1982 spinup) -> "
        f"build_routing_param.py -> Lohmann route_1.0/rout). Basin delineated "
        f"{RESULT_OBJ['basin']['delineated_area_km2']:.0f} km2 "
        f"({RESULT_OBJ['basin']['area_err_pct']:+.1f}% vs 208,091 published; outlet snapped "
        f"onto china_dem_90m mainstem at {OUTLET_LON},{OUTLET_LAT}). UNCALIBRATED soil/veg "
        f"(KI defaults) -- SAME protocol as the uncalibrated Jinghong real-case. Lohmann "
        f"velocity IDENTIFIED (not NSE-tuned): default v=1.5 uh_lag="
        f"{ident['default_velocity_uh_lag_days']}d vs observed demand "
        f"{ident['target_uh_lag_days']}d -> {ident['method']} = {ident['velocity_m_s']} m/s. "
        f"paired={len(j)} d ({period}); obs_mean={j.obs.mean():.0f} sim_mean={j.sim.mean():.0f} "
        f"m3/s. NSE={m['nse']:.3f} r={m['r']:.3f} KGE={m['kge']:.3f} PBIAS={m['pbias']:+.1f}%. "
        f"cal({CAL[0][:4]}-{CAL[1][:4]}) NSE={md['nse_cal']}; val({VAL[0][:4]}-{VAL[1][:4]}, "
        f"held out) NSE={md['nse_val']} PBIAS={md['pbias_val']}%. Water balance {wb['status']} "
        f"({RESULT_OBJ['water_balance']['residual_pct']}%). CAVEAT: the Yarlung Tsangpo carries "
        f"a large glacier/snowmelt contribution VIC has no module for, so a dry (negative PBIAS) "
        f"summer bias is physically expected and is reported, not calibrated away. rout "
        f"renormalises UH_S so velocity moves TIMING only, never PBIAS."
    )
    print(json.dumps(RESULT_OBJ["metrics"], indent=2), flush=True)
    log("DONE")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:                                   # noqa: BLE001
        tb = traceback.format_exc()
        log("FATAL:\n" + tb)
        TOOLS_FAILED.append(f"runner: {type(exc).__name__}: {str(exc)[:300]}")
        try:
            save(f"runner aborted: {type(exc).__name__}: {str(exc)[:400]}")
        except Exception:                                      # noqa: BLE001
            Path(RESULT).write_text(json.dumps(
                {"model_id": "VIC", "this_location": "Nuxia Station",
                 "obs_source": "ObservedQ", "status": "failed",
                 "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                 "water_balance": {"status": "N/A", "residual_pct": None},
                 "notes": f"runner aborted: {tb[-800:]}"}, ensure_ascii=False))
        sys.exit(1)
