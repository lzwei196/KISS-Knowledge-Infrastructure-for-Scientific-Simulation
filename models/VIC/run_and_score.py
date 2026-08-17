#!/usr/bin/env python3
"""
VIC VERIFIER runner -- Bengbu (Huai River gauge 51080), verify_1.

Purpose
-------
Consistency check against the Harbin (Songhua) real-case. The real-case was run
UNCALIBRATED (default soil/veg parameters, nothing tuned on either period), so
this verifier MUST use the same protocol at Bengbu; a calibrated Bengbu score
would manufacture false "consistency".

Chain (all real binaries, KI tools) -- SKILL.md s0..s10
  s0  ki_tools_common.terrain_ops.delineate_basin  (via s5_routing/delineate_bengbu.py)
        -> basin.tif / flow_accum.tif / dem_filled.tif + bengbu_boundary.shp
  s2-6 SOIL/VEG/FORCING <- KI-prepared artefacts under outputs/bengbu_real_1980_1990/vic_temp,
        used verbatim; SOIL asserted to carry VIC defaults binfilt/Ds/Dsmax/Ws.
  s9  s5_routing/build_routing_param.py -> BB_direc/frac/xmask/staloc + UH.all
        (connectivity N/N enforced by the tool itself)
  s8  model/VIC-5.1.0/.../vic_classic.exe, water-balance mode, 210 cells @0.25deg,
        CMFD 3-hourly, 1980-1990 (1980 = spinup)
  s10 model/route_1.0/src/rout (Lohmann). VIC does NOT route; discharge at a
        gauge requires this step (SKILL.md dt_vic_019).
  D   score <- ki_tools_common.metrics.all_metrics + validators.standard_calval
        + ki_tools_common.validation.validate_water_balance

Why s0/s9 are run at all: the previous generation of this file copied BB_* routing
parameters from `detached/verify_1/sweep/baseline/routing`, which does not exist
anywhere on this server. Nothing on disk ships Bengbu routing parameters, so they
are rebuilt here with the same tool the Harbin real-case used.

Resumability
------------
  * s0  skipped if outputs/.../delineation/bengbu_boundary.shp exists.
  * s9  skipped if <routing_param>/BB_direc.txt exists.
  * s8  skipped if all 210 flux files already exist in <work>/vic_result.
  * s10 skipped if <work>/routing/rout_out/*.day already exists.
  Re-launching therefore continues instead of restarting.

Writes the verifier JSON object to detached/verify_1/result.json as its final
action, in every exit path.
"""
import os, sys, glob, json, shutil, subprocess, traceback

# NOTE: do NOT put python_env/lib/python3.12/site-packages on the path. It contains a
# Python-2-era pathlib.py backport (`from collections import Sequence`) that shadows the
# stdlib pathlib and breaks `import rasterio` in s5_routing/build_routing_param.py.
# Every package needed here is already in ~/.local for the system python3.
KDT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"
sys.path.insert(0, KDT)

import numpy as np
import pandas as pd
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from validators.standard_calval import compute_calval_metrics

BASE = "KISSPATH_ROOT"
CASE = f"{BASE}/models/VIC/detached/verify_1"
WORK = f"{CASE}/uncal"

KI       = f"{BASE}/models/VIC/knowledge_infrastructure"
VIC_EXE  = f"{BASE}/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
ROUT_EXE = f"{BASE}/model/route_1.0/src/rout"

PREP     = f"{BASE}/outputs/bengbu_real_1980_1990/vic_temp"
SOIL_SRC = f"{PREP}/soil/SOIL_PARAM_COMPLETE.txt"
VEG_SRC  = f"{PREP}/veg/vic_veg_param_final.txt"
VEGLIB   = f"{BASE}/data/vic_param/veglib.LDAS"
FORCING  = f"{PREP}/forcing/forcing_final/bengbu_0.25deg_"
OBS_FILE = f"{BASE}/data/obs/BB/51080_bengbu.txt"

DELIN    = f"{BASE}/outputs/bengbu_real_1980_1990/delineation"
ROUTPARM = f"{BASE}/outputs/bengbu_real_1980_1990/routing_param"

VIC_RESULT = f"{WORK}/vic_result"
ROUTING    = f"{WORK}/routing"
VIC_IN     = f"{ROUTING}/vic_in"
ROUT_OUT   = f"{ROUTING}/rout_out"

NCELL   = 210
Y0, Y1  = 1980, 1990          # 1980 = spinup, scored 1981-1990
EVAL0, EVAL1 = "1981-01-01", "1990-12-31"
STATION = "BB"
OUTLET_LON, OUTLET_LAT = 117.39, 32.94
PUB_AREA_KM2 = 121330.0

result = {
    "model_id": "VIC",
    "this_location": "Bengbu",
    "obs_source": "ObservedQ",
    "status": "failed",
    "tools_used": [], "tools_failed": [],
    "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": "",
}


def write_result():
    os.makedirs(CASE, exist_ok=True)
    with open(f"{CASE}/result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("[result.json written]", flush=True)


def die(msg):
    result["notes"] = msg
    write_result()
    sys.exit(1)


def score(day_file, tag):
    """Score a routed .day file against Bengbu obs over the eval window."""
    rd = pd.read_csv(day_file, sep=r"\s+", header=None,
                     names=["year", "month", "day", "Q"])
    rd["date"] = pd.to_datetime(rd[["year", "month", "day"]])
    sim = rd.set_index("date")["Q"]

    obs = pd.read_csv(OBS_FILE, sep="\t", encoding="gbk")
    obs["date"] = pd.to_datetime(obs["dates"])
    obs = obs.set_index("date")
    obs["Q"] = pd.to_numeric(obs["Q"], errors="coerce")
    obs = obs[obs["Q"] > -90]                       # -99 = missing (dt_vic_021)

    paired = pd.concat([obs.loc[EVAL0:EVAL1, "Q"].rename("obs"),
                        sim.loc[EVAL0:EVAL1].rename("sim")],
                       axis=1, sort=True).dropna()
    if len(paired) < 2:
        return None

    m = {k.lower(): float(v) for k, v in
         all_metrics(paired["obs"].values, paired["sim"].values).items()}
    cv = compute_calval_metrics(paired.index.values,
                                paired["obs"].values, paired["sim"].values)
    m["period"] = f"{paired.index.min().date()}..{paired.index.max().date()}"
    m["n"] = len(paired)
    m["obs_mean"] = float(paired["obs"].mean())
    m["sim_mean"] = float(paired["sim"].mean())
    m["cal"] = {k: float(v) for k, v in cv["calibration"].items()
                if isinstance(v, (int, float, np.floating))}
    m["val"] = {k: float(v) for k, v in cv["validation"].items()
                if isinstance(v, (int, float, np.floating))}
    print(f"[score:{tag}] n={m['n']} NSE={m['nse']:.3f} r={m['r']:.3f} "
          f"KGE={m['kge']:.3f} PBIAS={m['pbias']:+.1f}", flush=True)
    return m


try:
    os.makedirs(VIC_RESULT, exist_ok=True)
    os.makedirs(VIC_IN, exist_ok=True)
    os.makedirs(ROUT_OUT, exist_ok=True)

    # ---------------- Step s0: delineate basin + boundary shapefile ---------
    shp = f"{DELIN}/bengbu_boundary.shp"
    if os.path.exists(shp) and os.path.exists(f"{DELIN}/delineation.json"):
        print("[s0] boundary shapefile present -- skip delineation (resume)", flush=True)
    else:
        print("[s0] delineating basin ...", flush=True)
        r = subprocess.run([sys.executable, f"{KI}/s5_routing/delineate_bengbu.py"],
                           capture_output=True, text=True)
        print(r.stdout[-3000:], flush=True)
        if r.returncode != 0:
            print(r.stderr[-2000:], flush=True)
            result["tools_failed"].append("s5_routing/delineate_bengbu.py")
            die("basin delineation failed: " + r.stderr[-500:])
    delin = json.load(open(f"{DELIN}/delineation.json"))
    print(f"[s0] basin area {delin['area']:.0f} km2 "
          f"({delin.get('area_err_pct', float('nan')):+.1f}% vs published {PUB_AREA_KM2:.0f})",
          flush=True)
    result["tools_used"].append(
        "ki_tools_common.terrain_ops.delineate_basin (via s5_routing/delineate_bengbu.py)")

    # ---------------- Step A: default soil params, verbatim from KI ---------
    soil_dst = f"{WORK}/SOIL.txt"
    shutil.copy2(SOIL_SRC, soil_dst)
    sp = pd.read_csv(soil_dst, sep=r"\s+", header=None)
    binfilt, Ds, Dsmax, Ws = (sp[4].unique(), sp[5].unique(),
                              sp[6].unique(), sp[7].unique())
    print(f"[A] SOIL {len(sp)} cells; binfilt={binfilt} Ds={Ds} Dsmax={Dsmax} Ws={Ws}", flush=True)
    if len(sp) != NCELL:
        die(f"soil has {len(sp)} cells, expected {NCELL}")
    # Guard: this run must be UNCALIBRATED (VIC defaults), matching the real-case.
    if not (np.allclose(binfilt, 0.30) and np.allclose(Ds, 0.02)
            and np.allclose(Dsmax, 10.0) and np.allclose(Ws, 0.70)):
        die("SOIL params are not VIC defaults -- verifier must run uncalibrated")
    result["tools_used"] += [
        "s3_soil/fill_parameters{1,2}.py output (SOIL_PARAM_COMPLETE.txt, defaults)",
        "s4_veg/process_vegetation_detailed.py output (vic_veg_param_final.txt)",
        "s2_forcing/process_forcing.py output (CMFD 3-hourly ASCII, 8 steps/day)",
    ]

    # ---------------- Step s9: routing parameters ---------------------------
    if os.path.exists(f"{ROUTPARM}/{STATION}_direc.txt"):
        print("[s9] routing parameters present -- skip build (resume)", flush=True)
    else:
        print("[s9] building routing parameters ...", flush=True)
        env = dict(os.environ)
        env.update({
            "HYDROCRAFT_ROOT": BASE,
            "VIC_BASIN_NAME": "bengbu",
            "VIC_SOIL_PARAM": SOIL_SRC,
            "VIC_BASIN_SHP": shp,
            "VIC_ROUTING_DIR": ROUTPARM,
            "VIC_DEM": f"{DELIN}/dem_huai_90m.tif",
            "VIC_FLOW_ACCUM": delin["flow_accum"],
            "VIC_BASIN_RASTER": delin["basin_raster"],
            "VIC_FILLED_DEM": delin["filled_dem"],
            "VIC_CELL_SIZE": "0.25",
            "VIC_STATION_NAME": STATION,
            "VIC_OUTLET_LON": str(OUTLET_LON),
            "VIC_OUTLET_LAT": str(OUTLET_LAT),
            "VIC_YEAR_START": str(Y0),
            "VIC_YEAR_END": str(Y1),
            "PYTHONPATH": KDT,
        })
        r = subprocess.run([sys.executable, f"{KI}/s5_routing/build_routing_param.py"],
                           capture_output=True, text=True, env=env)
        print(r.stdout[-4000:], flush=True)
        if r.returncode != 0 or not os.path.exists(f"{ROUTPARM}/{STATION}_direc.txt"):
            print(r.stderr[-3000:], flush=True)
            result["tools_failed"].append("s5_routing/build_routing_param.py")
            die("routing parameter build failed: " + r.stderr[-500:])
    result["tools_used"].append("s5_routing/build_routing_param.py")

    # ---------------- Step s8: run VIC (resumable) --------------------------
    flux = glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*.txt")
    if len(flux) >= NCELL:
        print(f"[s8] {len(flux)} flux files present -- skip VIC (resume)", flush=True)
    else:
        gp = f"""NLAYER 3
NODES 3
MODEL_STEPS_PER_DAY 8
SNOW_STEPS_PER_DAY 8
RUNOFF_STEPS_PER_DAY 8
STARTYEAR {Y0}
STARTMONTH 01
STARTDAY 01
ENDYEAR {Y1}
ENDMONTH 12
ENDDAY 31
FULL_ENERGY FALSE
FROZEN_SOIL FALSE
FORCING1 {FORCING}
FORCE_FORMAT ASCII
FORCE_TYPE AIR_TEMP
FORCE_TYPE PREC
FORCE_TYPE PRESSURE
FORCE_TYPE SWDOWN
FORCE_TYPE LWDOWN
FORCE_TYPE VP
FORCE_TYPE WIND
FORCE_STEPS_PER_DAY 8
FORCEYEAR {Y0}
FORCEMONTH 01
FORCEDAY 01
GRID_DECIMAL 4
SOIL {soil_dst}
BASEFLOW ARNO
JULY_TAVG_SUPPLIED FALSE
ORGANIC_FRACT FALSE
VEGLIB {VEGLIB}
VEGPARAM {VEG_SRC}
ROOT_ZONES 3
VEGPARAM_LAI TRUE
LAI_SRC FROM_VEGPARAM
SNOW_BAND 1
RESULT_DIR {VIC_RESULT}/
OUTFILE bengbu_fluxes
OUT_FORMAT ASCII
AGGFREQ NHOURS 24
OUTVAR OUT_PREC
OUTVAR OUT_RAINF
OUTVAR OUT_SNOWF
OUTVAR OUT_AIR_TEMP
OUTVAR OUT_SWDOWN
OUTVAR OUT_LWDOWN
OUTVAR OUT_PRESSURE
OUTVAR OUT_WIND
OUTVAR OUT_DENSITY
OUTVAR OUT_REL_HUMID
OUTVAR OUT_QAIR
OUTVAR OUT_VP
OUTVAR OUT_VPD
OUTVAR OUT_RUNOFF
OUTVAR OUT_BASEFLOW
OUTVAR OUT_EVAP
OUTVAR OUT_SWE
OUTVAR OUT_SOIL_MOIST
OUTVAR OUT_ALBEDO
OUTVAR OUT_SOIL_TEMP
"""
        gp_path = f"{WORK}/global_param.txt"
        open(gp_path, "w").write(gp)
        print("[s8] running vic_classic.exe ...", flush=True)
        r = subprocess.run([VIC_EXE, "-g", gp_path], cwd=WORK,
                           capture_output=True, text=True)
        print(f"[s8] vic rc={r.returncode}", flush=True)
        if r.stderr:
            print("[s8] stderr tail:", r.stderr[-800:], flush=True)
        flux = glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*.txt")
        if len(flux) < NCELL:
            result["tools_failed"].append(
                f"vic_classic.exe: {len(flux)}/{NCELL} flux files (rc={r.returncode})")
            die(f"VIC produced only {len(flux)}/{NCELL} flux files")
    result["tools_used"].append("vic_classic.exe (VIC 5.1.0 classic driver, water-balance mode)")

    # ---------------- Step s10: Lohmann routing (resumable) ------------------
    day_files = [f for f in glob.glob(f"{ROUT_OUT}/*.day") if os.path.getsize(f) > 0]
    if day_files:
        print("[s10] routed .day present -- skip routing (resume)", flush=True)
    else:
        print("[s10] preprocessing flux -> 7-col rout input ...", flush=True)
        n = 0
        for fn in sorted(os.listdir(VIC_RESULT)):
            if not fn.endswith(".txt") or fn.startswith("._"):
                continue
            df = pd.read_csv(os.path.join(VIC_RESULT, fn), sep=r"\s+",
                             skiprows=3, header=None)
            # year month day prec evap runoff baseflow  (SKILL.md dt_vic_019);
            # valid only for the exact OUTVAR order written above (24 columns).
            df.iloc[:, [0, 1, 2, 3, 18, 16, 17]].to_csv(
                os.path.join(VIC_IN, fn.replace("bengbu_", "").replace(".txt", "")),
                sep="\t", header=False, index=False, float_format="%.4f")
            n += 1
        print(f"[s10] preprocessed {n} flux files", flush=True)

        for f in [f"{STATION}_direc.txt", f"{STATION}_frac.txt", f"{STATION}_xmask.txt",
                  f"{STATION}_staloc.txt", "UH.all"]:
            shutil.copy2(os.path.join(ROUTPARM, f), os.path.join(ROUTING, f))
        # Route the full record but only WRITE from Y0+1 so the spinup year is
        # never scored.
        open(f"{ROUTING}/rout_global.txt", "w").write(
            f"""# Routing Information File for {STATION}
# NAME OF FLOW DIRECTION FILE
./{STATION}_direc.txt
# NAME OF VELOCITY FILE
.false.
1.5
# NAME OF DIFF FILE
.false.
800
# NAME OF XMASK FILE
.true.
./{STATION}_xmask.txt
# NAME OF FRACTION FILE
.true.
./{STATION}_frac.txt
# NAME OF STATION FILE
./{STATION}_staloc.txt
# PATH OF INPUT FILES AND PRECISION
./vic_in/fluxes_
4
# PATH OF OUTPUT FILES
./rout_out/
# YEAR AND MONTH OF VIC OUTPUT TO ROUTE & ROUTED OUTPUT TO WRITE
{Y0} 01 {Y1} 12
{Y0+1} 01 {Y1} 12
# NAME OF UNIT HYDROGRAPH FILE
./UH.all
""")
        for f in glob.glob(f"{ROUTING}/*.uh_s"):
            os.remove(f)
        print("[s10] running Lohmann rout ...", flush=True)
        r = subprocess.run([ROUT_EXE, "rout_global.txt"], cwd=ROUTING,
                           capture_output=True, text=True, timeout=7200)
        print(f"[s10] rout rc={r.returncode}", flush=True)
        if r.stdout:
            print("[s10] stdout tail:", "\n".join(r.stdout.strip().splitlines()[-6:]), flush=True)
        if r.stderr:
            print("[s10] stderr tail:", r.stderr[-500:], flush=True)
        day_files = [f for f in glob.glob(f"{ROUT_OUT}/*.day") if os.path.getsize(f) > 0]
        if not day_files:
            result["tools_failed"].append("route_1.0/rout: no .day output")
            die("Lohmann routing produced no output")
    result["tools_used"].append("route_1.0/src/rout (Lohmann routing binary)")

    # ---------------- Step D: score -----------------------------------------
    m = score(sorted(day_files)[0], "uncal")
    if m is None:
        die("no temporal overlap between routed sim and obs")
    result["metrics"].update({"nse": m["nse"], "r": m["r"], "kge": m["kge"],
                              "pbias": m["pbias"], "period": m["period"]})
    result["tools_used"] += ["ki_tools_common.metrics.all_metrics",
                             "validators.standard_calval.compute_calval_metrics"]

    # ---------------- water balance -----------------------------------------
    print("[D] water balance ...", flush=True)
    P, ET, RO, dS = [], [], [], []
    for fn in sorted(glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*.txt")):
        df = pd.read_csv(fn, sep=r"\s+", skiprows=2)
        df["date"] = pd.to_datetime(df[["YEAR", "MONTH", "DAY"]].rename(
            columns={"YEAR": "year", "MONTH": "month", "DAY": "day"}))
        df = df[(df["date"] >= EVAL0) & (df["date"] <= EVAL1)]
        if df.empty:
            continue
        st = (df["OUT_SOIL_MOIST_0"] + df["OUT_SOIL_MOIST_1"]
              + df["OUT_SOIL_MOIST_2"] + df["OUT_SWE"])
        P.append(df["OUT_PREC"].sum()); ET.append(df["OUT_EVAP"].sum())
        RO.append((df["OUT_RUNOFF"] + df["OUT_BASEFLOW"]).sum())
        dS.append(st.iloc[-1] - st.iloc[0])

    ndays = len(pd.date_range(EVAL0, EVAL1))
    wb = validate_water_balance(precip_mm=float(np.mean(P)), et_mm=float(np.mean(ET)),
                                runoff_mm=float(np.mean(RO)),
                                delta_storage_mm=float(np.mean(dS)), period_days=ndays)
    result["water_balance"] = {
        "status": wb["status"],
        "residual_pct": float(wb["residual_pct"]) if wb.get("residual_pct") is not None else None,
        "basin_mean_P_mm": float(np.mean(P)), "basin_mean_ET_mm": float(np.mean(ET)),
        "basin_mean_Q_mm": float(np.mean(RO)), "basin_mean_dS_mm": float(np.mean(dS)),
        "n_cells": len(P),
    }
    result["tools_used"].append("ki_tools_common.validation.validate_water_balance")

    result["metrics"].update({
        "rmse": m.get("rmse"), "n_paired": m["n"],
        "obs_mean_m3s": m["obs_mean"], "sim_mean_m3s": m["sim_mean"],
        "nse_cal": m["cal"]["NSE"], "kge_cal": m["cal"]["KGE"], "pbias_cal": m["cal"]["PBIAS"],
        "nse_val": m["val"]["NSE"], "kge_val": m["val"]["KGE"], "pbias_val": m["val"]["PBIAS"],
        "r_val": m["val"]["r"],
    })
    result["basin"] = {"delineated_area_km2": delin["area"],
                       "published_area_km2": PUB_AREA_KM2,
                       "area_err_pct": delin.get("area_err_pct")}

    result["status"] = "completed"
    result["notes"] = (
        f"VERIFIER at Bengbu (Huai River gauge 51080, published {PUB_AREA_KM2:.0f} km2 lowland outlet) "
        f"-- a DIFFERENT basin/regime than the Harbin real-case (cold, snowmelt-driven Songhua). Full "
        f"KI chain re-run with the REAL binaries: delineate_basin -> build_routing_param.py -> "
        f"vic_classic.exe (VIC 5.1.0, water-balance mode, {NCELL} cells @0.25deg, CMFD 3-hourly, "
        f"1980-1990 with 1980 as spinup) -> Lohmann route_1.0/rout -> daily discharge. Delineated area "
        f"{delin['area']:.0f} km2 ({delin.get('area_err_pct', 0):+.1f}% vs published). UNCALIBRATED, "
        f"default soil parameters (binfilt=0.30, Ds=0.02, Dsmax=10, Ws=0.70) taken verbatim from the "
        f"KI's SOIL_PARAM_COMPLETE.txt -- deliberately the SAME protocol as the uncalibrated Harbin "
        f"real-case. paired={m['n']} days ({m['period']}), obs_mean={m['obs_mean']:.0f} "
        f"sim_mean={m['sim_mean']:.0f} m3/s. NSE={m['nse']:.3f} r={m['r']:.3f} KGE={m['kge']:.3f} "
        f"PBIAS={m['pbias']:+.1f}%. cal(1981-85) NSE={m['cal']['NSE']:.3f}/KGE={m['cal']['KGE']:.3f}; "
        f"val(1986-90) NSE={m['val']['NSE']:.3f}/KGE={m['val']['KGE']:.3f}/"
        f"PBIAS={m['val']['PBIAS']:+.1f}%. Water balance {wb['status']} "
        f"(residual {wb['residual_pct']:.2f}%). KI BUG found at s0: the shipped snap_distance_m=3000 "
        f"mis-snaps this gauge onto a 146 km2 tributary (the DEM channel is 5.4 km from the published "
        f"coordinate), silently delineating a 145 km2 'basin'; raising stream_threshold alone does not "
        f"fix it because the snap radius is the binding constraint. Fixed with snap=6000 m + "
        f"stream_threshold=1e6 px and guarded by a published-area assertion. Nothing on disk shipped "
        f"Bengbu routing parameters, so BB_direc/frac/xmask/staloc+UH.all were rebuilt with "
        f"s5_routing/build_routing_param.py (the same tool the Harbin real-case used). "
        f"point_time_series obs_shape -> NSE/KGE/r/PBIAS all dag-valid; determining_metric=nse."
    )
    write_result()
    print("[DONE]", flush=True)
    print(json.dumps(result["metrics"], indent=2), flush=True)

except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    result["tools_failed"].append("runner exception")
    result["notes"] = "Runner crashed: " + traceback.format_exc()[-800:]
    write_result()
    sys.exit(1)
