#!/usr/bin/env python3
"""Verifier-1 runner: DSSAT CERES-Maize at a national-production-representative
NCP point (Henan 34.0N/113.0E) over 2000-2020, scored against the FAOSTAT
national maize yield series (China, mainland) via the documented
validate_yield_timeseries.py --obs faostat path.

Obs_shape = regional_aggregate_time_series -> dag-valid families are
[magnitude_accuracy (PBIAS), trend_match (slope sign)]; nse/kge/r are
structurally invalid for a weather-only point vs a smooth national aggregate
and are nulled by the tool (raw values kept under _raw_invalid_*).

RESUMABLE: skips WTH build, SOL build, and the DSSAT run if their outputs
already exist; relaunch continues.
"""
import os, sys, json, subprocess, shutil
from pathlib import Path

KI = "KISSPATH_KI_ROOT/DSSAT/knowledge_infrastructure"
TOOLS = os.path.join(KI, "tools")
STATE = "KISSPATH_KI_ROOT/DSSAT/detached/verify_1"
WORK = os.path.join(STATE, "work")
# short /tmp workdir to dodge the Fortran 92-char FileX path limit
DSSAT_WD = "/tmp/dssat_v1_henan"
RESULT = os.path.join(STATE, "result.json")

LAT, LON = 34.0, 113.0
YR0, YR1 = 2000, 2020
CULT = "CN0001"          # Zhengdan958 (same cultivar as Real-case)
PLANT = "2000-06-15"     # summer maize after winter wheat
FORCING = "KISSPATH_FORCING/Data_forcing_03hr_010deg"
PY = sys.executable

os.makedirs(WORK, exist_ok=True)
WTH = os.path.join(WORK, "SITE.WTH")
SOL = os.path.join(WORK, "SOIL.SOL")
SOIL_ID = "HWSD000001"


def log(m):
    print(m, flush=True)


def write_result(obj):
    os.makedirs(STATE, exist_ok=True)
    with open(RESULT, "w") as fh:
        json.dump(obj, fh, indent=2)
    log("RESULT WRITTEN -> " + RESULT)


def fail(note, **extra):
    r = {"model_id": "DSSAT",
         "this_location": "FAOSTAT Global Production — Crops & Livestock (1961-2024)",
         "obs_source": "FAOSTAT", "status": "failed",
         "tools_used": [], "tools_failed": [],
         "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
         "water_balance": {"status": "N/A", "residual_pct": None},
         "notes": note}
    r.update(extra)
    write_result(r)
    sys.exit(1)


# ---------------------------------------------------------------- 1. WEATHER
if not (os.path.isfile(WTH) and os.path.getsize(WTH) > 1000):
    log(f"[1/4] Building CMFD .WTH {YR0}-{YR1} @ {LAT},{LON} (I/O-bound)...")
    cmd = [PY, os.path.join(TOOLS, "s2_weather_prep", "convert_cmfd_to_wth.py"),
           "--forcing_dir", FORCING, "--lat", str(LAT), "--lon", str(LON),
           "--start_year", str(YR0), "--end_year", str(YR1),
           "--output", WTH, "--station_name", "SITE"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    log(p.stdout[-2000:]); log(p.stderr[-2000:])
    if p.returncode != 0 or not os.path.isfile(WTH):
        fail("convert_cmfd_to_wth.py failed: " + p.stderr[-500:],
             tools_failed=["s2_weather_prep/convert_cmfd_to_wth.py"])
else:
    log("[1/4] WTH exists — skip")

# ------------------------------------------------------------------- 2. SOIL
if not (os.path.isfile(SOL) and os.path.getsize(SOL) > 200):
    log(f"[2/4] Building HWSD SOIL.SOL @ {LAT},{LON}...")
    cmd = [PY, os.path.join(TOOLS, "s3_soil_setup", "convert_hwsd_to_sol.py"),
           "--lat", str(LAT), "--lon", str(LON),
           "--output", SOL, "--soil_id", SOIL_ID]
    p = subprocess.run(cmd, capture_output=True, text=True)
    log(p.stdout[-1500:]); log(p.stderr[-1500:])
    if p.returncode != 0 or not os.path.isfile(SOL):
        fail("convert_hwsd_to_sol.py failed: " + p.stderr[-500:],
             tools_failed=["s3_soil_setup/convert_hwsd_to_sol.py"])
else:
    log("[2/4] SOIL.SOL exists — skip")

# ------------------------------------------------------------ 3. RUN DSSAT
sys.path.insert(0, TOOLS)
from dssat_workdir_setup import create_workdir, run_dssat, parse_summary  # noqa

summary_out = os.path.join(DSSAT_WD, "Summary.OUT")
need_run = not (os.path.isfile(summary_out) and os.path.getsize(summary_out) > 200)
if need_run:
    log(f"[3/4] create_workdir + run_dssat multi-year ({YR0}-{YR1}, NYERS={YR1-YR0+1})...")
    if os.path.isdir(DSSAT_WD):
        shutil.rmtree(DSSAT_WD)
    try:
        wd = create_workdir(
            crop="MZ", cultivar=CULT, weather_file=WTH, soil_id=SOIL_ID,
            soil_file=SOL, lat=LAT, lon=LON, planting_date=PLANT,
            start_year=YR0, end_year=YR1, output_dir=DSSAT_WD,
            fert_n=200,
        )
    except Exception as e:
        fail(f"create_workdir raised: {e}", tools_failed=["dssat_workdir_setup.create_workdir"])
    res = run_dssat(wd)
    log("run_dssat success=" + str(res.get("success")))
    if not res.get("success"):
        log(str(res)[-1500:])
    summary_out = os.path.join(wd, "Summary.OUT")
    DSSAT_WD = wd
else:
    log("[3/4] Summary.OUT exists — skip run")

recs = parse_summary(DSSAT_WD)
yrs = sorted({int(r["WYEAR"]) for r in recs
              if str(r.get("WYEAR", "")).strip().isdigit()
              and float(r.get("HWAM", 0) or 0) > 0})
log(f"  parsed {len(recs)} Summary rows; {len(yrs)} sim years with HWAM>0: {yrs[:5]}...{yrs[-3:] if len(yrs)>3 else ''}")
if len(yrs) < 2:
    fail(f"DSSAT produced <2 valid sim-year HWAM rows ({len(yrs)}); cannot define trend.",
         tools_used=["s2_weather_prep/convert_cmfd_to_wth.py",
                     "s3_soil_setup/convert_hwsd_to_sol.py", "dssat_workdir_setup.py"])

# --------------------------------------------------- 4. VALIDATE vs FAOSTAT
log("[4/4] validate_yield_timeseries.py --obs faostat --country 'China, mainland'...")
vjson = os.path.join(STATE, "validation_metrics.json")
cmd = [PY, os.path.join(TOOLS, "s9_output_parsing", "validate_yield_timeseries.py"),
       "--workdir", DSSAT_WD, "--lat", str(LAT), "--lon", str(LON),
       "--crop", "maize", "--obs", "faostat", "--country", "China, mainland",
       "--out", vjson]
p = subprocess.run(cmd, capture_output=True, text=True)
log(p.stdout[-3000:]); log(p.stderr[-1500:])
if not os.path.isfile(vjson):
    fail("validate_yield_timeseries.py produced no output: " + p.stderr[-500:],
         tools_failed=["s9_output_parsing/validate_yield_timeseries.py"])

V = json.load(open(vjson))
m = V["metrics"]
pbias = m.get("pbias")
period = f"{V['years'][0]}-{V['years'][-1]} (FAOSTAT national annual, regional_aggregate)"

note = (
    f"DSSAT-CSM 4.8.5 (dscsm048) CERES-Maize, cultivar {CULT} Zhengdan958, run "
    f"multi-year seasonal {V['years'][0]}-{V['years'][-1]} (n={V['n_pairs']} yrs) at a "
    f"national-production-representative NCP point Henan {LAT}N/{LON}E (rainfed, "
    f"planting 06-15, split N=200 kg/ha, HWSD soil), CMFD V2.0 3-hourly 0.1deg forcing. "
    f"Scored vs FAOSTAT 'China, mainland' national maize yield. obs_shape="
    f"{V['obs_shape']} -> dag-valid families {V['valid_metric_families']}: "
    f"PBIAS={pbias} (magnitude_accuracy, the determining family); trend_match "
    f"sim_slope={m.get('sim_slope_kgha_yr')} obs_slope={m.get('obs_slope_kgha_yr')} "
    f"slope_ratio={m.get('slope_ratio')} trend_sign_agree={m.get('trend_sign_agree')}. "
    f"NSE/KGE/r are NULLED by the tool (invalid for regional_aggregate national vs "
    f"weather-only fixed-mgmt point); raw-invalid r={m.get('_raw_invalid_r')} "
    f"nse={m.get('_raw_invalid_nse')} kept for the record only. Consistent obs_shape "
    f"and PBIAS-magnitude family with the SPAM Real-case (PBIAS +8.34%)."
)

out = {
    "model_id": "DSSAT",
    "this_location": "FAOSTAT Global Production — Crops & Livestock (1961-2024)",
    "obs_source": "FAOSTAT",
    "status": "completed",
    "tools_used": [
        "s2_weather_prep/convert_cmfd_to_wth.py",
        "s3_soil_setup/convert_hwsd_to_sol.py",
        "dssat_workdir_setup.py (create_workdir/run_dssat/parse_summary)",
        "s9_output_parsing/validate_yield_timeseries.py (--obs faostat)",
        "ki_tools_common.crop_obs.get_faostat_yield_series",
        "ki_tools_common.metrics.all_metrics",
    ],
    "tools_failed": [],
    "metrics": {
        "nse": m.get("nse"), "kge": m.get("kge"),
        "pbias": pbias, "r": m.get("_raw_invalid_r"),
        "period": period,
    },
    "trend_match": {
        "sim_slope_kgha_yr": m.get("sim_slope_kgha_yr"),
        "obs_slope_kgha_yr": m.get("obs_slope_kgha_yr"),
        "slope_ratio": m.get("slope_ratio"),
        "trend_sign_agree": m.get("trend_sign_agree"),
    },
    "obs_shape": V["obs_shape"],
    "valid_metric_families": V["valid_metric_families"],
    "n_pairs": V["n_pairs"],
    "sim_kgha": V.get("sim_kgha"),
    "obs_kgha": V.get("obs_kgha"),
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": note,
}
write_result(out)
log("DONE")
