#!/usr/bin/env python3
"""
VERIFIER (verify_2) detached runner: TOPMODEL @ Collingwood River, Tasmania
(GRDC-Caravan Extension gauge GRDC_5803089, 277.9 km2, western Tasmania).

Faithful maritime twin of the Real-case Chemainus River (Vancouver Island):
both are small, rain-dominated, humid, no-snow maritime basins — the ideal
TOPMODEL regime. Same pipeline & recipe as the Real-case:
  - MSWX forcing 1980-1990 -> inputs.dat (convert_forcing_to_topmodel)
  - MERIT 90m DEM + Caravan basin shapefile -> subcat.dat (generate_twi_subcat)  [prebuilt]
  - real run_bmi binary, calibrated (cal 1981-85, val 1986-90, spinup 1980)
    via the shipped calibrate_topmodel.py, cal-only objective, held-out val.
  - Adopt cal-best only if val does not collapse vs robust seed-only.
Scores full/cal/val with ki_tools_common.metrics.all_metrics.
Writes verify_2/result.json in the VERIFIER schema.
RESUMABLE: skips MSWX extraction if inputs.dat exists; skips search if
calib_result.json exists.
"""
import os, sys, json, subprocess, re
from datetime import datetime, timedelta
import numpy as np

RUN_DIR = "KISSPATH_KI_ROOT/TOPMODEL/_collingwood_5803089"
KI = "KISSPATH_KI_ROOT/TOPMODEL/knowledge_infrastructure"
OUT_DIR = "KISSPATH_KI_ROOT/TOPMODEL/detached/verify_2"
BASIN = "Collingwood_5803089"
AREA_KM2 = 277.92
LAT, LON = -42.11, 145.92          # basin centroid (gauge -42.1729,145.9271)
START = "1980-01-01"
CAL = "1981-01-01:1985-12-31"
VAL = "1986-01-01:1990-12-31"
N_TRIALS = 1200
MSWX_DIR = "KISSPATH_FORCING/"

sys.path.insert(0, os.path.join(KI, "tools"))
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/validators")
from ki_tools_common.metrics import all_metrics
from standard_calval import compute_calval_metrics
import calibrate_topmodel as CT

os.makedirs(OUT_DIR, exist_ok=True)
INPUTS = os.path.join(RUN_DIR, "data/inputs.dat")
OBS = os.path.join(RUN_DIR, "obs_collingwood.txt")
BASIN_SHP = os.path.join(RUN_DIR, "basin_collingwood.shp")

tools_used = ["convert_forcing_to_topmodel.py", "generate_twi_subcat.py",
              "run_topmodel.py", "parse_topmodel_output.py", "calibrate_topmodel.py",
              "ki_tools_common.load_forcing", "ki_tools_common.metrics.all_metrics"]
tools_failed = []

# --- 0. Forcing prep (resumable: MSWX point extraction ~25 min) ---
if not (os.path.exists(INPUTS) and os.path.getsize(INPUTS) > 0):
    print("Building inputs.dat from MSWX (slow)...", flush=True)
    subprocess.run([sys.executable, os.path.join(KI, "tools/convert_forcing_to_topmodel.py"),
                    "--forcing-dir", MSWX_DIR, "--source", "mswx",
                    "--start-date", "1980-01-01", "--end-date", "1990-12-31",
                    "--lat", str(LAT), "--lon", str(LON), "--dt-hours", "24",
                    "--obs-file", OBS, "--basin-area-km2", str(AREA_KM2),
                    "--output", INPUTS], check=True)
print("inputs.dat ready:", os.path.getsize(INPUTS), "bytes", flush=True)

# --- 0b. Forcing preflight (advisory; not a gate — MSWX descending-lat clip bug) ---
pf_out = {"all_pass": None, "source": "mswx", "failures": [], "warnings": []}
try:
    from preflight_forcing import validate_forcing
    rep = validate_forcing(MSWX_DIR, source="mswx", year=1985,
                           shapefile=BASIN_SHP if os.path.exists(BASIN_SHP) else None)
    pf_out = {"all_pass": bool(rep.all_pass), "source": rep.source,
              "failures": [c for c in rep.checks if c.get("status") == "FAIL"],
              "warnings": rep.warnings}
    print(f"forcing preflight: all_pass={rep.all_pass}", flush=True)
except Exception as e:
    pf_out["warnings"].append(f"preflight could not run: {e}")
    print("forcing preflight skipped:", e, flush=True)


def parse_hyd(path):
    from parse_topmodel_output import parse_hyd_out
    ts, qs, qo = parse_hyd_out(path)
    return np.asarray(qs), np.asarray(qo)


def run_with(params):
    CT.write_params_dat(os.path.join(RUN_DIR, "data/params.dat"), params, BASIN)
    r = subprocess.run([os.path.join(RUN_DIR, "run_bmi")], cwd=RUN_DIR,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("run_bmi failed: " + r.stderr[-400:])
    return parse_hyd(os.path.join(RUN_DIR, "hyd.out"))


# --- 1. Calibration (resumable) ---
calib_json = os.path.join(RUN_DIR, "calib_result.json")
if not os.path.exists(calib_json):
    subprocess.run([sys.executable, os.path.join(KI, "tools/calibrate_topmodel.py"),
                    "--run-dir", RUN_DIR, "--basin", BASIN,
                    "--start", START, "--cal", CAL, "--val", VAL,
                    "--n", str(N_TRIALS)],
                   check=True)
cal_res = json.load(open(calib_json))
cal_best = cal_res["best_params"]
cal_best_m = cal_res["metrics"]

# --- 2. Overfitting guard: cal-best val vs robust seed-only ---
seed = dict(CT.INCUMBENT)
nstep, dates = CT.build_dates(RUN_DIR, datetime.strptime(START, "%Y-%m-%d"))
seed_m = CT.score(RUN_DIR, seed, dates, BASIN)
cb_val = (cal_best_m or {}).get("validation", {}).get("NSE")
sd_val = (seed_m or {}).get("validation", {}).get("NSE")
adopt = cal_best
adopt_reason = "cal-best adopted (val did not collapse)"
if cb_val is None or (sd_val is not None and cb_val < sd_val - 0.05 and sd_val > 0):
    adopt = seed
    adopt_reason = f"kept robust seed (cal-best val {cb_val} < seed val {sd_val})"

# --- 3. Final run with adopted params ---
qs, qo = run_with(adopt)
n = min(len(qs), len(dates))
qs, qo, dd = qs[:n], qo[:n], dates[:n]
valid = qo > 0
dd_v = [d for d, v in zip(dd, valid) if v]
qo_v, qs_v = qo[valid], qs[valid]

full_m = all_metrics(qo_v, qs_v)
cv = compute_calval_metrics(dd_v, qo_v, qs_v)

# --- 4. Water balance from TOPMODEL SUMP/SUMAE/SUMQ (m -> mm) ---
sump = sumae = sumq = bal = None
runoff_coef = None
try:
    m = re.search(r"SUMP\s+SUMAE\s+SUMQ.*?\n\s*([0-9eE.+-]+)\s+([0-9eE.+-]+)\s+([0-9eE.+-]+)\s+"
                  r"([0-9eE.+-]+)\s+([0-9eE.+-]+)\s+([0-9eE.+-]+)\s+([0-9eE.+-]+)",
                  open(os.path.join(RUN_DIR, "topmod.out")).read(), re.S)
    if m:
        sump, sumae, sumq, sumrz, sumuz, sbar_f, bal = [float(x) for x in m.groups()]
    total_P, total_ET, total_Q = sump*1000.0, sumae*1000.0, sumq*1000.0
    runoff_coef = sumq/sump if sump else None
    from ki_tools_common.validation import validate_water_balance
    dS = (sump - sumae - sumq - bal) * 1000.0
    wb = validate_water_balance(precip_mm=total_P, et_mm=total_ET, runoff_mm=total_Q,
                                delta_storage_mm=dS, period_days=n)
    wb_out = {"status": wb.get("status"), "residual_pct": wb.get("residual_pct"),
              "residual_mm": wb.get("residual_mm"),
              "diagnostics": [
                  f"SUMP={total_P:.0f}mm SUMAE={total_ET:.0f}mm SUMQ={total_Q:.0f}mm "
                  f"runoff_coef={runoff_coef:.2f} model_BAL={bal*1000:.0f}mm",
                  "TOPMODEL standalone BAL is a deficit-accounting closure term; "
                  "runoff_coef is the meaningful maritime sanity metric."]}
except Exception as e:
    wb_out = {"status": "N/A", "residual_pct": None, "residual_mm": None,
              "diagnostics": [f"wb error: {e}", f"runoff_coef={runoff_coef}"]}

result = {
    "model_id": "TOPMODEL",
    "this_location": "GRDC-Caravan Extension GRDC_5803089 COLLINGWOOD RIVER (HRS B/L ALMA), "
                     "western Tasmania AU (-42.173N, 145.927E, 277.9 km2)",
    "obs_source": "GRDC",
    "status": "completed",
    "tools_used": tools_used,
    "tools_failed": tools_failed,
    "metrics": {
        "nse": full_m["NSE"], "kge": full_m["KGE"], "pbias": full_m["PBIAS"],
        "r": full_m["r"],
        "nse_cal": cv["calibration"]["NSE"], "kge_cal": cv["calibration"]["KGE"],
        "nse_val": cv["validation"]["NSE"], "kge_val": cv["validation"]["KGE"],
        "pbias_val": cv["validation"]["PBIAS"],
        "period": "1981-01-01:1990-12-31 (cal 1981-85 / val 1986-90, spinup 1980)"},
    "water_balance": {"status": wb_out["status"], "residual_pct": wb_out["residual_pct"],
                      "residual_mm": wb_out.get("residual_mm"),
                      "diagnostics": wb_out.get("diagnostics", [])},
    "forcing_preflight": pf_out,
    "adopted_params": adopt,
    "adopt_reason": adopt_reason,
    "notes": ("TOPMODEL verify_2 on a rain-dominated, humid, no-snow maritime Tasmanian basin "
              "(Collingwood R.), a faithful twin of the Real-case Chemainus R. (Vancouver Island). "
              "Obs = GRDC-Caravan Extension streamflow (mm/day -> m3/s via area 277.9 km2, sentinel "
              "days masked). MSWX forcing 1980-1990, MERIT 90m DEM + Caravan basin shapefile TWI. "
              "Calibrated via real run_bmi; val held out. " + adopt_reason)}
json.dump(result, open(os.path.join(OUT_DIR, "result.json"), "w"), indent=2, default=float)
print("WROTE", os.path.join(OUT_DIR, "result.json"))
print(json.dumps(result["metrics"], indent=2, default=float))
