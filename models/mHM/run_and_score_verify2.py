#!/usr/bin/env python3
"""
mHM VERIFIER #2 -- Laoguan He at Xixia (GRDC 2182250, 3,418 km2).

Third location for the mHM consistency check.
    Real-case  Wangjiaba (Huai, 29,638 km2)  NSE 0.8022
    verify_1   Bengbu    (Huai, 123,211 km2) -- same river, 4x larger
    verify_2   Xixia     (Laoguan He, 3,418 km2)  <- THIS RUN

Xixia is deliberately NOT on the Huai. The Laoguan He (老鹳河) drains the southern
Qinling foothills into the Dan River -> Han River -> Yangtze. So this run changes
the river system, the relief (mountainous, not a flat leveed plain) and the basin
scale (9x smaller than the Real-case, 36x smaller than verify_1) while holding the
model, the tool-chain and the forcing product fixed. That is what makes it a test
of mHM/MPR rather than a re-test of the Huai.

Why this gauge and not a Qinghai / Wei He station: MERIT-Hydro on this machine is
only tiles n30e110 + n30e115 (110-120E, 30-35N). Step 0 of the SKILL (dt_s09,
delineate against MERIT `upa`) is mandatory and cannot be skipped, so the basin
must lie inside those tiles. Xixia does; it is the only in-tile candidate that is
a different river system from the Huai.

Basin corroboration (the dt_s09 check, done BEFORE anything else):
    GRDC documented drainage area      3,418.0 km2
    MERIT `upa` at the snapped outlet  3,420.4 km2   (+0.1%)
The raw GRDC lat/lon (111.474, 33.289) sits off-channel (upa = 0.0), so the
outlet MUST be snapped -- taking the raw pixel would silently give a 0 km2 basin.

GRID
    L0  0.01 deg   (padded square, side a multiple of the ratio -- dt_r12)
    L1 = L11  0.1 deg  -> ratio 10, ~34 active cells, and 0.1 deg is also CMFD's
    native grid, so the forcing maps 1:1 onto L1 with no regridding invention.
    (The Real-case used L1 0.25 deg; on a 3,418 km2 basin that would be ~5 cells,
    too coarse for MRM to route at all.)

PERIODS -- identical split to the Real-case, so the tiers are comparable
    spin-up      1980                       (warming_Days = 365, discarded)
    calibration  1981-01-01 .. 1985-12-31   <- the ONLY window the optimiser sees
    validation   1986-01-01 .. 1990-12-31   <- held out, never optimised on
Observed discharge is 100% complete over 1981-1990 (3652/3652 days).

FORCING: CMFD V0200 daily (`Data_forcing_01dy_010deg`), cropped to the domain.
    prec is a daily MEAN RATE in kg m-2 s-1 -> x86400, NOT x10800 (dt_s10).
    CMFD daily has tmin == tmax, so Hargreaves is identically zero -> PET = Oudin,
    processCase(5) = 0 (dt_s11).  Both handled inside the KI's s4 tool.

RESUMABLE: every stage is skipped when its output artefact already exists.
    basin   -> runs/basin/xixia_merit.shp
    forcing -> data/forcing/xixia_cmfd_01dy_010deg/*.nc   (per-file)
    setup   -> runs/xixia/input/meteo/pet/pet.nc + input/gauge/2182250.txt
    cal     -> runs/xixia_cal/FinalParam.nml               (DDS, 1981-1985 only)
    final   -> runs/xixia_final/output_b1/daily_discharge.out (1981-1990)

Final result object -> detached/verify_2/result.json

NOTE: this file is a SEPARATE script from run_and_score.py, which is verify_1's
Bengbu runner and is executing concurrently. Nothing here writes into Bengbu's
run dirs or into run_and_score.py.
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
BASE = RUNS / "xixia"
CAL = RUNS / "xixia_cal"
FINAL = RUNS / "xixia_final"
BASIN = RUNS / "basin"
OUT = ROOT / "models/mHM/detached/verify_2"

SHP = BASIN / "xixia_merit.shp"
MERIT_DIR_TIF = BASIN / "xixia_merit_dir.tif"
DEM = ROOT / "data/dem/china_dem_90m/china_dem_90m.tif"

NATIONAL_FORCING = ROOT / "data/forcing/Data_forcing_01dy_010deg"
FORCING = ROOT / "data/forcing/xixia_cmfd_01dy_010deg"
FORCING_VARS = ["prec", "temp"]

# GRDC 2182250 -> HydroCraft 5-column tab format (written by the obs adapter).
OBS = ROOT / "data/obs/GRDC/2182250_xixia.txt"
GAUGE_ID = 2182250
GAUGE_FILENAME = f"{GAUGE_ID:05d}.txt"

# Published GRDC gauge location. Off-channel in MERIT (upa = 0) -> must be snapped.
OUTLET_LON, OUTLET_LAT = 111.474, 33.289
DRAINAGE_KM2 = 3418.0
SNAP_DEG = 0.06                      # snapped outlet = (111.47917, 33.26000), upa 3420.4
DELINEATE_BBOX = (110.80, 32.95, 112.30, 34.30)
FORCING_MARGIN_DEG = 0.4

RES_L0 = 1000        # metres in the tool's API; degrees = m / 100000 -> 0.01 deg
RES_L1 = 10000       # 0.1 deg
RES_L11 = 10000      # 0.1 deg

SPINUP_YEAR = 1980
CAL_START, CAL_END = "1981-01-01", "1985-12-31"
VAL_START, VAL_END = "1986-01-01", "1990-12-31"
EVAL_START_Y, EVAL_END_Y = 1981, 1990

# FORCES mo_dds.F90 requires >= 6 function evals (below that it Fortran-STOPs with
# exit code 0 and writes nothing -- dt_r14).
N_ITER = 2000
OPTI_METHOD = 1       # DDS
OPTI_FUNCTION = 1     # 1 - NSE  (NSE is the dag's determining_metric; NOT 10, dt_r15)
BASIN_TYPE = "humid_subtropical"   # same preset as the Real-case, for comparability

TOOLS_USED = []
TOOLS_FAILED = []


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


# ------------------------------------------------- stage: basin (SKILL step 0)
def stage_basin():
    """dt_s09: establish the TRUE catchment before touching anything else."""
    if SHP.exists() and MERIT_DIR_TIF.exists():
        log("basin: xixia_merit.shp present, skipping")
        mark("delineate_basin_merit.py")
        return
    BASIN.mkdir(parents=True, exist_ok=True)
    run("s1_domain/delineate_basin_merit.py", [
        "--outlet_lon", OUTLET_LON, "--outlet_lat", OUTLET_LAT,
        "--target_area_km2", DRAINAGE_KM2,
        "--bbox", *DELINEATE_BBOX, "--snap_deg", SNAP_DEG,
        "--out_shp", SHP])


# ------------------------------------------------------------- stage: forcing
def stage_forcing():
    """Crop the national CMFD 0.1 deg daily product to the domain bbox.

    A verbatim lat/lon crop -- same variable names, same units, same `01dy` tag so
    the daily-product detection in the s4 tool fires. The national files are
    ~400 MB/yr; cropping once keeps every later invocation cheap. Resumable per
    file.
    """
    import geopandas as gpd
    import xarray as xr

    FORCING.mkdir(parents=True, exist_ok=True)
    years = list(range(SPINUP_YEAR, EVAL_END_Y + 1))
    names = [f"{v}_CMFD_V0200_B-01_01dy_010deg_{y}01-{y}12.nc"
             for v in FORCING_VARS for y in years]
    if all((FORCING / n).exists() for n in names):
        log("forcing: crop complete, skipping")
        return

    minx, miny, maxx, maxy = gpd.read_file(SHP).total_bounds
    lo_lon, hi_lon = minx - FORCING_MARGIN_DEG, maxx + FORCING_MARGIN_DEG
    lo_lat, hi_lat = miny - FORCING_MARGIN_DEG, maxy + FORCING_MARGIN_DEG
    log(f"forcing: crop bbox lon [{lo_lon:.3f},{hi_lon:.3f}] lat [{lo_lat:.3f},{hi_lat:.3f}]")

    for n in names:
        dst = FORCING / n
        if dst.exists():
            continue
        src = NATIONAL_FORCING / n
        if not src.exists():
            raise FileNotFoundError(src)
        with xr.open_dataset(src, engine="netcdf4") as d:
            # CMFD lat/lon are both ascending.
            sub = d.sel(lat=slice(lo_lat, hi_lat), lon=slice(lo_lon, hi_lon))
            if sub.sizes["lat"] < 2 or sub.sizes["lon"] < 2:
                raise RuntimeError(f"crop of {n} is degenerate: {dict(sub.sizes)}")
            sub.to_netcdf(dst)
        log(f"forcing: {n} -> {sub.sizes['lat']}x{sub.sizes['lon']}")


# --------------------------------------------------------------- stage: setup
def read_ascii_header(path):
    h = {}
    with open(path) as f:
        for _ in range(6):
            k, v = f.readline().split()
            h[k.lower()] = float(v)
    return h


def max_facc_cell():
    """SKILL error-handling note 7: place the gauge at the max-facc L0 cell.

    The published gauge lat/lon can land on a hillslope cell after rasterisation;
    the drainage outlet is the cell with the largest accumulated area.
    """
    p = BASE / "input/morph/facc.asc"
    h = read_ascii_header(p)
    a = np.loadtxt(p, skiprows=6)
    a = np.where(a == h["nodata_value"], -np.inf, a)
    r, c = np.unravel_index(np.argmax(a), a.shape)
    cs, nrows = h["cellsize"], int(h["nrows"])
    lon = h["xllcorner"] + (c + 0.5) * cs
    lat = h["yllcorner"] + (nrows - 1 - r + 0.5) * cs
    log(f"gauge: max-facc L0 cell ({r},{c}) facc={a[r, c]:.0f} -> lon {lon:.5f} lat {lat:.5f}")
    return lon, lat


SETUP_TOOLS = [
    "delineate_basin_merit.py", "configure_mhm_basin.py", "setup_mhm_domain.py",
    "generate_latlon_files.py", "prepare_morpho_data.py", "hwsd_to_mhm_soil.py",
    "glim_to_mhm_geology.py", "landcover_to_mhm_luse.py", "generate_gauge_grid.py",
    "validate_morph_grids.py", "convert_forcing_to_mhm.py", "prepare_mhm_gauge.py",
]


def stage_setup():
    if (BASE / "input/meteo/pet/pet.nc").exists() and (BASE / f"input/gauge/{GAUGE_FILENAME}").exists():
        log("setup: artefacts present, skipping")
        for t in SETUP_TOOLS:
            mark(t)
        return

    run("s0_config/configure_mhm_basin.py", [
        "--basin_name", "xixia", "--output_dir", RUNS, "--shp_path", SHP,
        "--start_year", SPINUP_YEAR, "--end_year", EVAL_END_Y,
        "--resolution_l0", RES_L0, "--resolution_l1", RES_L1, "--resolution_l11", RES_L11,
        "--forcing", "CMFD", "--pet_method", 0])

    cfg, di = BASE / "config.json", BASE / "domain_info.json"
    run("s1_domain/setup_mhm_domain.py", ["--config", cfg])
    run("s1_domain/generate_latlon_files.py", ["--config", cfg, "--domain_info", di])

    # MERIT D8 (already ArcGIS-encoded) rather than bare-earth D8 on the 90 m DEM.
    run("s2_morphology/prepare_morpho_data.py", [
        "--config", cfg, "--domain_info", di, "--dem_path", DEM,
        "--fdir_source", "merit", "--merit_dir_tif", MERIT_DIR_TIF])
    run("s2_morphology/hwsd_to_mhm_soil.py", ["--config", cfg, "--domain_info", di])
    run("s2_morphology/glim_to_mhm_geology.py", ["--config", cfg, "--domain_info", di])
    # dt_s12: the shipped AVHRR raster is UMD-legend, not IGBP.
    run("s2_morphology/landcover_to_mhm_luse.py",
        ["--config", cfg, "--domain_info", di, "--legend", "umd"])

    glon, glat = max_facc_cell()
    run("s2_morphology/generate_gauge_grid.py", [
        "--config", cfg, "--domain_info", di,
        "--gauge_lat", glat, "--gauge_lon", glon, "--gauge_id", GAUGE_ID])
    run("s2_morphology/validate_morph_grids.py", ["--morph_dir", BASE / "input/morph"])

    run("s4_forcing/convert_forcing_to_mhm.py", [
        "--config", cfg, "--domain_info", di, "--forcing_dir", FORCING, "--pet_method", 0])
    run("s5_gauge/prepare_mhm_gauge.py", [
        "--obs_file", OBS, "--gauge_id", GAUGE_ID, "--gauge_name", "Xixia",
        "--output_dir", BASE / "input/gauge",
        "--start_year", EVAL_START_Y, "--end_year", EVAL_END_Y])


def link_inputs(dst):
    """A run dir that shares BASE's inputs (symlink; mHM only reads them)."""
    dst.mkdir(parents=True, exist_ok=True)
    src = dst / "input"
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


# ----------------------------------------------------------- stage: calibrate
def stage_calibrate():
    final_param = CAL / "FinalParam.nml"
    if final_param.exists():
        log("calibration: FinalParam.nml present, skipping")
        for t in ["generate_mhm_namelists.py", "setup_mhm_calibration.py"]:
            mark(t)
        return final_param

    link_inputs(CAL)
    clone_config(CAL)

    # The optimiser sees the CALIBRATION window only (1981-1985); 1980 is warm-up.
    run("s6_namelist/generate_mhm_namelists.py", [
        "--config", CAL / "config.json", "--domain_info", CAL / "domain_info.json",
        "--gauge_id", GAUGE_ID, "--gauge_filename", GAUGE_FILENAME,
        "--warmup_days", 365,
        "--eval_start_year", 1981, "--eval_end_year", 1985,
        "--optimize", "--opti_method", OPTI_METHOD,
        "--opti_function", OPTI_FUNCTION, "--n_iterations", N_ITER])

    run("s9_calibration/setup_mhm_calibration.py", [
        "--run_dir", CAL, "--opti_method", OPTI_METHOD,
        "--opti_function", OPTI_FUNCTION, "--n_iterations", N_ITER,
        "--basin_type", BASIN_TYPE])

    # dt_r16: --execute used to stamp argparse defaults back into mhm.nml. Assert the
    # configured values actually stuck BEFORE burning an hour of DDS on the wrong ones.
    nml = (CAL / "mhm.nml").read_text()
    for want in (f"opti_function = {OPTI_FUNCTION}", f"nIterations = {N_ITER}",
                 "optimize = .TRUE.", "eval_Per(1)%yEnd = 1985"):
        if want not in nml:
            raise RuntimeError(f"mhm.nml does not contain '{want}' (dt_r16)")

    log(f"calibration: launching DDS, {N_ITER} iterations")
    run("s9_calibration/setup_mhm_calibration.py", ["--run_dir", CAL, "--execute"],
        timeout=None)
    run("s9_calibration/setup_mhm_calibration.py", ["--run_dir", CAL, "--parse_results"])

    # dt_r14: a Fortran `stop` exits 0. Never trust the return code alone.
    if not final_param.exists():
        raise RuntimeError("calibration finished but FinalParam.nml was not written")
    return final_param


# --------------------------------------------------------------- stage: final
def stage_final(param_nml):
    dd = FINAL / "output_b1/daily_discharge.out"
    if dd.exists():
        log("final run: daily_discharge.out present, skipping")
        return dd

    link_inputs(FINAL)
    clone_config(FINAL)

    # Forward run over cal+val with the calibrated parameters. optimize = .FALSE.
    run("s6_namelist/generate_mhm_namelists.py", [
        "--config", FINAL / "config.json", "--domain_info", FINAL / "domain_info.json",
        "--gauge_id", GAUGE_ID, "--gauge_filename", GAUGE_FILENAME,
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
        "this_location": "Xixia (Laoguan He, GRDC 2182250) -- GRDC Asia-Region Daily Discharge Export",
        "obs_source": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
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
        stage_basin()
        stage_forcing()
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
            f"Verifier #2: full mHM KI pipeline (s0-s9) on the MERIT-delineated "
            f"Laoguan He catchment at Xixia (GRDC 2182250; MERIT upa 3420.4 km2 vs "
            f"documented 3418 km2, +0.1%; the raw GRDC pixel is off-channel with "
            f"upa=0 and must be snapped). Different river system from the Real-case "
            f"(Han/Yangtze via the Dan, not the Huai) and 9x smaller. "
            f"L0 0.01 deg (square, dt_r12) / L1 = L11 0.1 deg = CMFD's native grid. "
            f"DDS ({N_ITER} it, opti_function=1 -> 1-NSE) calibrated on 1981-1985 "
            f"only; 1980 spin-up discarded (warming_Days=365). Held-out validation "
            f"NSE={m['nse_val']}, KGE={m['kge_val']}, PBIAS={m['pbias_val']}%. "
            f"Obs 100% complete (3652/3652 days). Forcing: CMFD V0200 daily "
            f"(kg m-2 s-1 daily mean rate -> x86400, dt_s10); PET=Oudin with "
            f"processCase(5)=0 because CMFD daily has tmin==tmax, making Hargreaves "
            f"identically zero (dt_s11)."
        )

    (OUT / "result.json").write_text(json.dumps(result, indent=2))
    log(f"wrote {OUT/'result.json'} status={result['status']}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
