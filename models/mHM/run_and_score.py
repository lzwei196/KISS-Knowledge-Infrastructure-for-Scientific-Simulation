#!/usr/bin/env python3
"""
mHM VERIFIER runner -- Bengbu (Huai River, gauge 51080, 121,330 km2).

Second location for the mHM consistency check. The Real-case ran the same KI
pipeline at Wangjiaba (51030, 30,630 km2, NSE 0.8022). Bengbu is 4x larger and
sits ~180 km downstream on the same river, so it exercises the routing network
(MRM) far harder while sharing the climate and the forcing product.

Everything is driven through the KI tools in
    /mnt/disk1/Hydrocraft_server/models/mHM/knowledge_infrastructure/tools/
This script only sequences them, waits, and scores. It writes NO model input
itself.

RESUMABLE: each stage is skipped when its output artefact already exists, so a
relaunch continues where it stopped.
    setup -> runs/bengbu/input/...            + domain_info.json
    cal   -> runs/bengbu_cal/FinalParam.nml   (DDS, 1981-1985 only)
    final -> runs/bengbu_final/output_b1/daily_discharge.out (1981-1990)

PERIODS (identical split to the Real-case, so the tiers are comparable)
    spin-up      1980                        (warming_Days = 365, discarded)
    calibration  1981-01-01 .. 1985-12-31    <- the ONLY window the optimiser sees
    validation   1986-01-01 .. 1990-12-31    <- held out, never optimised on

Final result object -> detached/verify_1/result.json
"""

import os
import sys
import json
import shutil
import subprocess
import traceback
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")

from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from validators.standard_calval import compute_calval_metrics

ROOT = Path("/mnt/disk1/Hydrocraft_server")
KI = ROOT / "models/mHM/knowledge_infrastructure"
TOOLS = KI / "tools"
RUNS = ROOT / "models/mHM/runs"
BASE = RUNS / "bengbu"
CAL = RUNS / "bengbu_cal"
FINAL = RUNS / "bengbu_final"
BASIN = RUNS / "basin"
OUT = ROOT / "models/mHM/detached/verify_1"
MHM = ROOT / "model/mhm/mhm"

OBS = ROOT / "data/obs/BB/51080_bengbu.txt"
# The Huai 0.25 deg CMFD cut-out (used by the Wangjiaba Real-case) is masked to a Huai
# polygon that does NOT cover the Sha-Ying / Guo headwaters of the Bengbu catchment:
# 4 basin L1 cells come back all-NaN and s4's coverage gate rejects them. Use the SAME
# CMFD product (V0200, Data_forcing_01dy -- a daily MEAN RATE in kg m-2 s-1, so x86400,
# dt_s10) at its native national 0.1 deg extent, area-averaged onto L1.
#
# `bengbu_cmfd_01dy_010deg` is a verbatim lat/lon crop of
# `data/forcing/Data_forcing_01dy_010deg` to the domain bbox (built once; the national
# files are 409 MB/yr and a strided read of all 22 costs ~20 min every invocation).
# Same variable names, same units, same "01dy" tag so the daily-product detection fires.
FORCING = ROOT / "data/forcing/bengbu_cmfd_01dy_010deg"
DEM = ROOT / "data/dem/china_dem_90m/china_dem_90m.tif"
MERIT_DIR_TIF = BASIN / "bengbu_merit_dir.tif"

GAUGE_ID = 51080
OUTLET_LON, OUTLET_LAT = 117.390, 32.943       # published Bengbu gauge location
DRAINAGE_KM2 = 121330.0                        # documented drainage area
# max-facc L0 cell of the upscaled MERIT network (the L0->L11 outlet, SKILL error-
# handling note 7): the highest-facc L0 cell need not be the snapped MERIT pixel.
GAUGE_LON, GAUGE_LAT = 117.335, 32.955

SPINUP_YEAR = 1980
CAL_START, CAL_END = "1981-01-01", "1985-12-31"
VAL_START, VAL_END = "1986-01-01", "1990-12-31"
EVAL_START_Y, EVAL_END_Y = 1981, 1990

# FORCES mo_dds.F90 requires >= 6 function evals (below that it Fortran-STOPs with
# exit code 0 and writes nothing).
N_ITER = 2000
OPTI_METHOD = 1     # DDS
OPTI_FUNCTION = 1   # 1 - NSE  (NSE is the dag's determining_metric)

TOOLS_USED = []
TOOLS_FAILED = []

SETUP_TOOLS = [
    "delineate_basin_merit.py", "configure_mhm_basin.py", "setup_mhm_domain.py",
    "generate_latlon_files.py", "prepare_morpho_data.py", "hwsd_to_mhm_soil.py",
    "glim_to_mhm_geology.py", "landcover_to_mhm_luse.py", "generate_gauge_grid.py",
    "validate_morph_grids.py", "convert_forcing_to_mhm.py", "prepare_mhm_gauge.py",
]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def mark(name):
    if name not in TOOLS_USED:
        TOOLS_USED.append(name)


def run(tool_rel, args, tool_name=None, cwd=None, timeout=None):
    """Invoke a KI tool; record it; raise on failure."""
    name = tool_name or Path(tool_rel).name
    cmd = [sys.executable, str(TOOLS / tool_rel)] + [str(a) for a in args]
    log(f"TOOL {name}")
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout)[-1500:]
        TOOLS_FAILED.append(f"{name}: rc={p.returncode} :: {tail[-400:]}")
        raise RuntimeError(f"{name} failed (rc={p.returncode})\n{tail}")
    mark(name)
    return p.stdout


# ---------------------------------------------------------------- stage: setup
def stage_setup():
    if (BASE / "input/meteo/pet/pet.nc").exists() and (BASE / "input/gauge/51080.txt").exists():
        log("setup: artefacts present, skipping")
        for t in SETUP_TOOLS:
            mark(t)
        return

    shp = BASIN / "bengbu_merit.shp"
    if not shp.exists():
        # Step 0 (dt_s09): verify the basin BEFORE anything else. A truncated domain
        # is unfixable downstream -- good timing, stubborn PBIAS ~ -50%.
        run("s1_domain/delineate_basin_merit.py", [
            "--outlet_lon", OUTLET_LON, "--outlet_lat", OUTLET_LAT,
            "--target_area_km2", DRAINAGE_KM2,
            "--bbox", 111.8, 30.8, 117.7, 35.0, "--snap_deg", 0.08,
            "--out_shp", shp])
    else:
        mark("delineate_basin_merit.py")

    run("s0_config/configure_mhm_basin.py", [
        "--basin_name", "bengbu", "--output_dir", RUNS, "--shp_path", shp,
        "--start_year", SPINUP_YEAR, "--end_year", EVAL_END_Y,
        "--resolution_l0", 1000, "--resolution_l1", 25000, "--resolution_l11", 25000,
        "--forcing", "CMFD", "--pet_method", 0])

    cfg, di = BASE / "config.json", BASE / "domain_info.json"
    run("s1_domain/setup_mhm_domain.py", ["--config", cfg])
    run("s1_domain/generate_latlon_files.py", ["--config", cfg, "--domain_info", di])
    run("s2_morphology/prepare_morpho_data.py", [
        "--config", cfg, "--domain_info", di, "--dem_path", DEM,
        "--fdir_source", "merit", "--merit_dir_tif", MERIT_DIR_TIF])
    run("s2_morphology/hwsd_to_mhm_soil.py", ["--config", cfg, "--domain_info", di])
    run("s2_morphology/glim_to_mhm_geology.py", ["--config", cfg, "--domain_info", di])
    run("s2_morphology/landcover_to_mhm_luse.py",
        ["--config", cfg, "--domain_info", di, "--legend", "umd"])
    run("s2_morphology/generate_gauge_grid.py", [
        "--config", cfg, "--domain_info", di,
        "--gauge_lat", GAUGE_LAT, "--gauge_lon", GAUGE_LON, "--gauge_id", GAUGE_ID])
    run("s2_morphology/validate_morph_grids.py", ["--morph_dir", BASE / "input/morph"])
    run("s4_forcing/convert_forcing_to_mhm.py", [
        "--config", cfg, "--domain_info", di, "--forcing_dir", FORCING, "--pet_method", 0])
    run("s5_gauge/prepare_mhm_gauge.py", [
        "--obs_file", OBS, "--gauge_id", GAUGE_ID, "--gauge_name", "Bengbu",
        "--output_dir", BASE / "input/gauge",
        "--start_year", EVAL_START_Y, "--end_year", EVAL_END_Y])


def link_inputs(dst):
    """Create a run dir that shares BASE's inputs (symlink; mHM only reads them)."""
    dst.mkdir(parents=True, exist_ok=True)
    src = (dst / "input")
    if not src.exists():
        os.symlink(BASE / "input", src)
    for d in ("output_b1", "restart"):
        (dst / d).mkdir(exist_ok=True)


def clone_config(dst):
    shutil.copy2(BASE / "config.json", dst / "config.json")
    cfg = json.load(open(dst / "config.json"))
    cfg["output_dir"] = str(dst)
    json.dump(cfg, open(dst / "config.json", "w"), indent=2)
    shutil.copy2(BASE / "domain_info.json", dst / "domain_info.json")


# ------------------------------------------------------------ stage: calibrate
def stage_calibrate():
    final_param = CAL / "FinalParam.nml"
    if final_param.exists():
        log("calibration: FinalParam.nml present, skipping")
        for t in ["generate_mhm_namelists.py", "setup_mhm_calibration.py"]:
            mark(t)
        return final_param

    link_inputs(CAL)
    clone_config(CAL)

    # Optimiser sees the CALIBRATION window only (1981-1985); 1980 is warm-up.
    run("s6_namelist/generate_mhm_namelists.py", [
        "--config", CAL / "config.json", "--domain_info", CAL / "domain_info.json",
        "--gauge_id", GAUGE_ID, "--gauge_filename", "51080.txt",
        "--warmup_days", 365,
        "--eval_start_year", 1981, "--eval_end_year", 1985,
        "--optimize", "--opti_method", OPTI_METHOD,
        "--opti_function", OPTI_FUNCTION, "--n_iterations", N_ITER])

    run("s9_calibration/setup_mhm_calibration.py", [
        "--run_dir", CAL, "--opti_method", OPTI_METHOD,
        "--opti_function", OPTI_FUNCTION, "--n_iterations", N_ITER,
        "--basin_type", "humid_subtropical"])

    # dt_r16: assert the configure call actually stuck before burning hours on DDS.
    nml = (CAL / "mhm.nml").read_text()
    for want in (f"opti_function = {OPTI_FUNCTION}", f"nIterations = {N_ITER}",
                 "optimize = .TRUE.", "eval_Per(1)%yEnd = 1985"):
        if want not in nml:
            raise RuntimeError(f"mhm.nml does not contain '{want}' (dt_r16)")

    log(f"calibration: launching DDS, {N_ITER} iterations (hours)")
    run("s9_calibration/setup_mhm_calibration.py", ["--run_dir", CAL, "--execute"],
        timeout=None)
    run("s9_calibration/setup_mhm_calibration.py", ["--run_dir", CAL, "--parse_results"])

    # dt_r14: mHM exits 0 having done nothing when a Fortran `stop` fires.
    if not final_param.exists():
        raise RuntimeError("calibration finished but FinalParam.nml was not written")
    return final_param


# ----------------------------------------------------------------- stage: final
def stage_final(param_nml):
    dd = FINAL / "output_b1/daily_discharge.out"
    if dd.exists():
        log("final run: daily_discharge.out present, skipping")
        return dd

    link_inputs(FINAL)
    clone_config(FINAL)

    # Forward run over cal+val with the calibrated parameters. optimize=.FALSE.
    run("s6_namelist/generate_mhm_namelists.py", [
        "--config", FINAL / "config.json", "--domain_info", FINAL / "domain_info.json",
        "--gauge_id", GAUGE_ID, "--gauge_filename", "51080.txt",
        "--warmup_days", 365,
        "--eval_start_year", EVAL_START_Y, "--eval_end_year", EVAL_END_Y,
        "--param_nml", param_nml])

    run("s7_execute/run_mhm.py", ["--run_dir", FINAL, "--timeout", 14400], timeout=15000)
    if not dd.exists():
        raise RuntimeError("final run produced no daily_discharge.out")
    return dd


# ------------------------------------------------------------------- scoring
def read_discharge(path):
    df = pd.read_csv(path, sep=r"\s+")
    dates = pd.to_datetime(dict(year=df.Year, month=df.Mon, day=df.Day))
    obs = df[f"Qobs_{GAUGE_ID:010d}"].values.astype(float)
    sim = df[f"Qsim_{GAUGE_ID:010d}"].values.astype(float)
    ok = (obs > -9990) & (sim > -9990) & np.isfinite(obs) & np.isfinite(sim)
    return dates[ok].reset_index(drop=True), obs[ok], sim[ok]


def water_balance(run_dir):
    """Basin-mean P, aET, Q, dStorage over the eval period, on the active L1 cells."""
    import xarray as xr
    fs = xr.open_dataset(run_dir / "output_b1/mHM_Fluxes_States.nc", engine="netcdf4")
    cell = ~np.isnan(fs["aET"].isel(time=0).values)

    et = float(np.nansum(fs["aET"].values[:, cell].mean(axis=1)))
    q = float(np.nansum(fs["Q"].values[:, cell].mean(axis=1)))

    stores = ["interception", "snowpack", "SWC_L01", "SWC_L02",
              "sealedSTW", "unsatSTW", "satSTW"]
    s0 = sum(float(np.nanmean(fs[v].values[0][cell])) for v in stores)
    s1 = sum(float(np.nanmean(fs[v].values[-1][cell])) for v in stores)
    dS = s1 - s0

    t = pd.to_datetime(fs.time.values)
    pre = xr.open_dataset(BASE / "input/meteo/pre/pre.nc", engine="netcdf4")
    p = pre["pre"].sel(time=slice(f"{EVAL_START_Y}-01-01", f"{EVAL_END_Y}-12-31")).values
    p = float(np.nansum(np.nanmean(p[:, cell], axis=1)))     # same L1 cells

    days = int((t[-1] + pd.offsets.MonthEnd(0) - t[0]).days) + 1
    wb = validate_water_balance(precip_mm=p, et_mm=et, runoff_mm=q,
                                delta_storage_mm=dS, period_days=days)
    wb["_totals_mm"] = {"P": round(p, 1), "aET": round(et, 1),
                        "Q": round(q, 1), "dS": round(dS, 1), "days": days}
    return wb


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "model_id": "mHM",
        "this_location": "Bengbu",
        "obs_source": "ObservedQ",
        "status": "failed",
        "tools_used": [],
        "tools_failed": [],
        "metrics": {k: None for k in
                    ["nse", "kge", "pbias", "r", "period",
                     "nse_cal", "kge_cal", "nse_val", "kge_val", "pbias_val",
                     "period_calibration", "period_validation"]},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": "",
    }
    try:
        stage_setup()
        param = stage_calibrate()
        dd = stage_final(param)

        dates, obs, sim = read_discharge(dd)
        full = all_metrics(obs, sim)          # NOTE: UPPERCASE keys, except 'r'
        cv = compute_calval_metrics(dates, obs, sim,
                                    cal_start=CAL_START, cal_end=CAL_END,
                                    val_start=VAL_START, val_end=VAL_END)
        c, v = cv["calibration"], cv["validation"]

        result["metrics"] = {
            "nse": round(float(full["NSE"]), 4), "r": round(float(full["r"]), 4),
            "kge": round(float(full["KGE"]), 4), "pbias": round(float(full["PBIAS"]), 4),
            "period": f"{CAL_START} to {VAL_END}",
            "nse_cal": round(float(c["NSE"]), 4), "kge_cal": round(float(c["KGE"]), 4),
            "nse_val": round(float(v["NSE"]), 4), "kge_val": round(float(v["KGE"]), 4),
            "pbias_val": round(float(v["PBIAS"]), 4),
            "period_calibration": f"{CAL_START} to {CAL_END}",
            "period_validation": f"{VAL_START} to {VAL_END}",
        }
        result["rmse"] = round(float(full["RMSE"]), 3)
        result["n_paired_days"] = int(len(obs))
        result["obs_mean_m3s"] = round(float(obs.mean()), 2)
        result["sim_mean_m3s"] = round(float(sim.mean()), 2)

        wb = water_balance(FINAL)
        result["water_balance"] = {
            "status": wb.get("status"),
            "residual_mm": (round(float(wb["residual_mm"]), 2)
                            if wb.get("residual_mm") is not None else None),
            "residual_pct": (round(float(wb["residual_pct"]), 2)
                             if wb.get("residual_pct") is not None else None),
            "diagnostics": list(wb.get("diagnostics", [])) + [
                f"totals mm over eval period: {wb['_totals_mm']}"],
        }
        result["status"] = "completed"
    except Exception as e:
        result["status"] = "failed"
        result["notes"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
        log(f"FAILED: {e}")

    result["tools_used"] = TOOLS_USED
    result["tools_failed"] = TOOLS_FAILED
    if result["status"] == "completed":
        m = result["metrics"]
        result["notes"] = (
            f"Verifier: full mHM KI pipeline (s0-s9) on the MERIT-delineated "
            f"123,211 km2 Bengbu catchment (gauge 51080, documented 121,330 km2, "
            f"+1.5%), L0 0.01 deg (575x575, square per dt_r12) / L1 = L11 0.25 deg. "
            f"DDS ({N_ITER} it, opti_function=1 -> 1-NSE) calibrated on 1981-1985 "
            f"only; 1980 spin-up discarded (warming_Days=365). Held-out validation "
            f"NSE={m['nse_val']}, KGE={m['kge_val']}, PBIAS={m['pbias_val']}%. "
            f"Forcing: CMFD V0200 daily (kg m-2 s-1 daily mean rate -> x86400, "
            f"dt_s10) at its national 0.1 deg extent, area-averaged onto L1; "
            f"PET=Oudin with processCase(5)=0 because CMFD daily has tmin==tmax, "
            f"which makes Hargreaves identically zero (dt_s11)."
        )

    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    log(f"wrote {OUT/'result.json'} status={result['status']}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
