#!/usr/bin/env python3
"""
VIC VERIFIER runner -- Bengbu (Huai River gauge 51080), verify_1.

Consistency check against the Harbin (Songhua) real-case. The real-case ran
UNCALIBRATED soil/veg (VIC defaults) with the Lohmann routing VELOCITY identified
from the observed lag on the calibration window only (SKILL.md dt_vic_028) -- never
fitted to NSE. This verifier reproduces that exact protocol at Bengbu; anything
else would manufacture (or destroy) "consistency" artificially.

Chain (real binaries, KI tools) -- SKILL.md s0..s10
  s0  ki_tools_common.terrain_ops.delineate_basin via s5_routing/delineate_bengbu.py
  A   SOIL/VEG/FORCING from outputs/bengbu_real_1980_1990/vic_temp, used verbatim;
      SOIL asserted to carry VIC defaults binfilt/Ds/Dsmax/Ws (uncalibrated).
  s7  global param cloned from docs/vic_param/global_param_template.txt (the OUTVAR
      order that s5_routing's 7-column rout slice depends on -- dt_vic_027).
  s9  s5_routing/build_routing_param.py -> BB_direc/frac/xmask/staloc + UH.all
  s8  vic_classic.exe, water-balance mode, 210 cells @0.25deg, CMFD 3-hourly,
      1980-1990 (1980 = spinup, never scored)
  s10 s5_routing/run_routing.py -> model/route_1.0/src/rout (Lohmann). VIC does NOT
      route (dt_vic_019). Velocity identified against the observed lag.
  D   score <- ki_tools_common.metrics.all_metrics + validators.standard_calval
      + ki_tools_common.validation.validate_water_balance

Velocity identification (dt_vic_028), on the CALIBRATION window 1981-85 only:
  1. route at the KI default v=1.5 m/s -> uh_lag_ref from rout's own .uh_s
  2. probe v -> v_min (0.10) FIRST to learn the lag CEILING the scheme can reach:
     MAKE_UHM clips each cell's kernel at LE*DT=48h and renormalises, so uh_lag
     asymptotes and velocity becomes an inert knob below some threshold.
  3. signed cross-correlation lag of sim vs obs. lag > 0 => sim is EARLY.
  4. target = uh_lag_ref + signed_lag. If |signed_lag| <= 1 d keep v=1.5.
     If target exceeds the ceiling, PIN v = v_min and report the plateau
     (structural insufficiency), do not optimise inside it.
     Otherwise bisect v on uh_lag(v) ~= target. Never on NSE.
  Routing renormalises UH_S, so velocity moves TIMING and essentially not PBIAS --
  the volume bias reported here is the honest uncalibrated one at any velocity.

Resumability -- keyed on PROVENANCE, not on mere file existence
  s0  skipped if delineation/delineation.json + bengbu_boundary.shp exist
  s9  skipped if routing_param/BB_direc.txt exists
  s8  skipped ONLY if 210 flux files exist AND vic_run_stamp.json records the md5 of the
      exact global param this run would write. The detached state dir outlives runner
      generations: an earlier run_and_score.py left 210 fluxes + a routing_param/vic_in
      slice here, and an existence-only guard scores output no code in this file produced.
      On a stamp miss the fluxes, the rout input slice and the velocity cache are all
      purged together, since each is derived from the last.
  s10 each routed velocity cached as <work>/routed/v<velocity>.csv and reused
  Re-launching continues instead of restarting.

Writes the verifier JSON object to detached/verify_1/result.json on EVERY exit path.
"""
import os, sys, glob, json, shutil, subprocess, traceback, hashlib

# Do NOT put python_env/lib/python3.12/site-packages on the path: it ships a Python-2-era
# pathlib.py backport (`from collections import Sequence`) that shadows stdlib pathlib and
# breaks `import rasterio` inside s5_routing/build_routing_param.py. System python3 +
# ~/.local already has every package needed here.
KDT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"
BASE = "KISSPATH_ROOT"
KI = f"{BASE}/models/VIC/knowledge_infrastructure"
sys.path.insert(0, KDT)
sys.path.insert(0, KI)

import numpy as np
import pandas as pd

from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from validators.standard_calval import compute_calval_metrics
from s5_routing.run_routing import prepare_vic_in, route, observed_lag_days

CASE = f"{BASE}/models/VIC/detached/verify_1"
WORK = f"{CASE}/uncal"

VIC_EXE = f"{BASE}/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
TEMPLATE = f"{KI}/docs/vic_param/global_param_template.txt"

PREP = f"{BASE}/outputs/bengbu_real_1980_1990/vic_temp"
SOIL_SRC = f"{PREP}/soil/SOIL_PARAM_COMPLETE.txt"
VEG_SRC = f"{PREP}/veg/vic_veg_param_final.txt"
VEGLIB = f"{BASE}/data/vic_param/veglib.LDAS"
FORCING = f"{PREP}/forcing/forcing_final/bengbu_0.25deg_"
OBS_FILE = f"{BASE}/data/obs/BB/51080_bengbu.txt"

DELIN = f"{BASE}/outputs/bengbu_real_1980_1990/delineation"
ROUTPARM = f"{BASE}/outputs/bengbu_real_1980_1990/routing_param"

VIC_RESULT = f"{WORK}/vic_result"
ROUTED = f"{WORK}/routed"

NCELL = 210
Y0, Y1 = 1980, 1990                       # 1980 = spinup
EVAL0, EVAL1 = "1981-01-01", "1990-12-31"
CAL0, CAL1 = "1981-01-01", "1985-12-31"
VAL0, VAL1 = "1986-01-01", "1990-12-31"
STATION = "BB"
OUTLET_LON, OUTLET_LAT = 117.39, 32.94
PUB_AREA_KM2 = 121330.0

V_DEFAULT = 1.5                           # KI default -- the value tuned AT Bengbu
V_MIN, V_MAX = 0.10, 8.0                  # calibration.yaml rout_velocity range
DIFF = 800.0

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
        json.dump(result, f, indent=2, default=float)
    print("[result.json written]", flush=True)


def die(msg):
    result["notes"] = msg
    write_result()
    sys.exit(1)


def load_obs():
    obs = pd.read_csv(OBS_FILE, sep="\t", encoding="gbk")
    obs["date"] = pd.to_datetime(obs["dates"])
    obs = obs.set_index("date")
    obs["Q"] = pd.to_numeric(obs["Q"], errors="coerce")
    obs = obs[obs["Q"] > -90]              # -99 = missing (dt_vic_021)
    return obs["Q"].sort_index()


def signed_lag(obs, sim, max_lag=30):
    """Cross-correlation lag scan over BOTH signs.

    The KI's observed_lag_days() scans only L >= 0, so it can detect a simulation
    that is too EARLY but silently reports 0 for one that is too LATE. Both are
    velocity errors; scan both directions before identifying velocity.
    L > 0 => sim leads obs (routing too fast).
    """
    j = pd.DataFrame({"obs": obs, "sim": sim}).dropna()
    if len(j) < 30:
        raise ValueError(f"only {len(j)} paired days for lag scan")
    scan = {L: j.obs.corr(j.sim.shift(L)) for L in range(-max_lag, max_lag + 1)}
    best = max(scan, key=lambda k: scan[k])
    return {"best_lag_days": int(best), "r_at_best_lag": float(scan[best]),
            "r_at_zero_lag": float(scan[0]),
            "nse_ceiling_at_zero_lag": float(scan[0] ** 2)}


_route_cache = {}


def routed(v):
    """Route at velocity v (m3/s daily series), cached on disk -> resumable."""
    key = round(float(v), 4)
    if key in _route_cache:
        return _route_cache[key]
    os.makedirs(ROUTED, exist_ok=True)
    cache = f"{ROUTED}/v{key}.csv"
    meta = f"{ROUTED}/v{key}.json"
    if os.path.exists(cache) and os.path.exists(meta):
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        s.attrs.update(json.load(open(meta)))
        src = "cached"
    else:
        s = route(ROUTPARM, velocity=key, diffusivity=DIFF,
                  route_start=(Y0, 1), route_end=(Y1, 12),
                  write_start=(Y0 + 1, 1), write_end=(Y1, 12),
                  station=STATION)
        s.to_csv(cache)
        json.dump({k: (float(x) if isinstance(x, (int, float, np.floating)) else str(x))
                   for k, x in s.attrs.items()}, open(meta, "w"))
        src = "routed"
    # route() only attaches uh_lag_days when rout actually wrote a .uh_s. Without it the
    # whole velocity-identification step is meaningless, so fail loudly rather than let a
    # None propagate into a format string after VIC has already burned its runtime.
    if s.attrs.get("uh_lag_days") is None:
        die(f"rout produced no .uh_s at v={key}: cannot read the unit hydrograph lag, so "
            f"velocity cannot be identified against the observed lag (dt_vic_029)")
    print(f"[s10] v={key} {src}: n={len(s)} mean={s.mean():.1f} m3/s "
          f"uh_lag={s.attrs['uh_lag_days']:.2f} d", flush=True)
    _route_cache[key] = s
    return s


def uh_lag(v):
    return float(routed(v).attrs["uh_lag_days"])


try:
    os.makedirs(VIC_RESULT, exist_ok=True)
    os.makedirs(ROUTED, exist_ok=True)
    obs = load_obs()

    # ---------------- s0: delineation ---------------------------------------
    shp = f"{DELIN}/bengbu_boundary.shp"
    if os.path.exists(shp) and os.path.exists(f"{DELIN}/delineation.json"):
        print("[s0] boundary + delineation.json present -- skip (resume)", flush=True)
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
    area_err = abs(delin["area"] - PUB_AREA_KM2) / PUB_AREA_KM2 * 100.0
    print(f"[s0] area {delin['area']:.0f} km2 vs published {PUB_AREA_KM2:.0f} "
          f"({area_err:.1f}% err)", flush=True)
    # dt_vic_026: snap_distance_m=3000 silently delineates a 145 km2 creek here.
    if area_err > 10.0:
        die(f"delineated area {delin['area']:.0f} km2 is {area_err:.1f}% off the published "
            f"{PUB_AREA_KM2:.0f} km2 -- pour-point snap is wrong, refusing to score")
    result["tools_used"].append(
        "ki_tools_common.terrain_ops.delineate_basin (via s5_routing/delineate_bengbu.py)")

    # ---------------- A: uncalibrated soil, verbatim -------------------------
    soil_dst = f"{WORK}/SOIL.txt"
    shutil.copy2(SOIL_SRC, soil_dst)
    sp = pd.read_csv(soil_dst, sep=r"\s+", header=None)
    binfilt, Ds, Dsmax, Ws = sp[4].unique(), sp[5].unique(), sp[6].unique(), sp[7].unique()
    print(f"[A] SOIL {len(sp)} cells; binfilt={binfilt} Ds={Ds} Dsmax={Dsmax} Ws={Ws}", flush=True)
    if len(sp) != NCELL:
        die(f"soil has {len(sp)} cells, expected {NCELL}")
    if not (np.allclose(binfilt, 0.30) and np.allclose(Ds, 0.02)
            and np.allclose(Dsmax, 10.0) and np.allclose(Ws, 0.70)):
        die("SOIL params are not VIC defaults -- the verifier must run UNCALIBRATED "
            "to match the uncalibrated Harbin real-case")
    result["tools_used"] += [
        "s3_soil/fill_parameters{1,2}.py output (SOIL_PARAM_COMPLETE.txt, VIC defaults)",
        "s4_veg/process_vegetation_detailed.py output (vic_veg_param_final.txt)",
        "s2_forcing/process_forcing.py output (CMFD 3-hourly ASCII, 8 steps/day)",
    ]

    # ---------------- s9: routing parameters --------------------------------
    if os.path.exists(f"{ROUTPARM}/{STATION}_direc.txt"):
        print("[s9] routing parameters present -- skip build (resume)", flush=True)
    else:
        print("[s9] building routing parameters ...", flush=True)
        env = dict(os.environ)
        env.update({
            "HYDROCRAFT_ROOT": BASE, "VIC_BASIN_NAME": "bengbu",
            "VIC_SOIL_PARAM": SOIL_SRC, "VIC_BASIN_SHP": shp,
            "VIC_ROUTING_DIR": ROUTPARM, "VIC_DEM": f"{DELIN}/dem_huai_90m.tif",
            "VIC_FLOW_ACCUM": delin["flow_accum"], "VIC_BASIN_RASTER": delin["basin_raster"],
            "VIC_FILLED_DEM": delin["filled_dem"], "VIC_CELL_SIZE": "0.25",
            "VIC_STATION_NAME": STATION,
            "VIC_OUTLET_LON": str(OUTLET_LON), "VIC_OUTLET_LAT": str(OUTLET_LAT),
            "VIC_YEAR_START": str(Y0), "VIC_YEAR_END": str(Y1), "PYTHONPATH": KDT,
        })
        r = subprocess.run([sys.executable, f"{KI}/s5_routing/build_routing_param.py"],
                           capture_output=True, text=True, env=env)
        print(r.stdout[-4000:], flush=True)
        if r.returncode != 0 or not os.path.exists(f"{ROUTPARM}/{STATION}_direc.txt"):
            print(r.stderr[-3000:], flush=True)
            result["tools_failed"].append("s5_routing/build_routing_param.py")
            die("routing parameter build failed: " + r.stderr[-500:])
    result["tools_used"].append("s5_routing/build_routing_param.py")

    # ---------------- s7 + s8: global param from the KI template, run VIC ----
    gp = []
    for line in open(TEMPLATE):
        k = line.split()[0] if line.strip() and not line.startswith("#") else ""
        if k == "FORCING1":
            line = f"FORCING1                {FORCING}\n"
        elif k == "SOIL":
            line = f"SOIL                    {soil_dst}\n"
        elif k == "VEGPARAM":
            line = f"VEGPARAM                {VEG_SRC}\n"
        elif k == "VEGLIB":
            line = f"VEGLIB                  {VEGLIB}\n"
        elif k == "RESULT_DIR":
            line = f"RESULT_DIR              {VIC_RESULT}/\n"
        elif k == "OUTFILE":
            line = "OUTFILE                 bengbu_fluxes\n"
        elif k == "STARTYEAR":
            line = f"STARTYEAR               {Y0}\n"
        elif k == "ENDYEAR":
            line = f"ENDYEAR                 {Y1}\n"
        elif k == "FORCEYEAR":
            line = f"FORCEYEAR               {Y0}\n"
        gp.append(line)
    gp_text = "".join(gp)
    gp_md5 = hashlib.md5(gp_text.encode()).hexdigest()
    gp_path = f"{WORK}/global_param.txt"
    stamp_path = f"{WORK}/vic_run_stamp.json"
    result["tools_used"].append("docs/vic_param/global_param_template.txt (KI-shipped)")

    # Resume must be keyed on PROVENANCE, not on file existence. This state dir survives
    # across generations of runner code, and an earlier generation of run_and_score.py left
    # 210 flux files + a routing_param/vic_in slice here. A bare `if len(flux) >= NCELL`
    # guard silently scores THOSE -- output that no code in this file ever produced. Skip
    # VIC only when a stamp proves the fluxes came from this exact global param.
    stamp = {}
    if os.path.exists(stamp_path):
        try:
            stamp = json.load(open(stamp_path))
        except Exception:
            stamp = {}
    flux = glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*")
    if len(flux) >= NCELL and stamp.get("global_param_md5") == gp_md5:
        print(f"[s8] {len(flux)} flux files stamped with this global param "
              f"(md5 {gp_md5[:8]}) -- skip VIC (resume)", flush=True)
    else:
        if flux:
            print(f"[s8] discarding {len(flux)} UNSTAMPED flux files (stamp md5="
                  f"{stamp.get('global_param_md5', 'none')}, want {gp_md5[:8]}): they were "
                  f"produced by other code and must not be scored", flush=True)
        # Purge every downstream artefact derived from the orphaned fluxes, or the routed
        # slice / velocity cache would carry the old run forward under the new stamp.
        for d in (VIC_RESULT, ROUTED, f"{ROUTPARM}/vic_in", f"{ROUTPARM}/scratch"):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(VIC_RESULT, exist_ok=True)
        os.makedirs(ROUTED, exist_ok=True)

        open(gp_path, "w").write(gp_text)
        print(f"[s8] running vic_classic.exe (210 cells, 1980-1990, gp md5 {gp_md5[:8]}) ...",
              flush=True)
        r = subprocess.run([VIC_EXE, "-g", gp_path], cwd=WORK, capture_output=True, text=True)
        print(f"[s8] vic rc={r.returncode}", flush=True)
        if r.stderr:
            print("[s8] stderr tail:", r.stderr[-1000:], flush=True)
        flux = glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*")
        if len(flux) < NCELL:
            result["tools_failed"].append(
                f"vic_classic.exe: {len(flux)}/{NCELL} flux files (rc={r.returncode})")
            die(f"VIC produced only {len(flux)}/{NCELL} flux files")
        json.dump({"global_param_md5": gp_md5, "ncell": len(flux), "vic_rc": r.returncode},
                  open(stamp_path, "w"), indent=2)
    result["metrics_provenance"] = {"global_param_md5": gp_md5}
    result["tools_used"].append("vic_classic.exe (VIC 5.1.0 classic driver, water-balance mode)")

    # ---------------- s10: rout input + velocity identification --------------
    n_in = prepare_vic_in(VIC_RESULT, f"{ROUTPARM}/vic_in", "bengbu")
    print(f"[s10] vic_in ready: {n_in} cells", flush=True)
    if n_in != NCELL:
        die(f"prepare_vic_in wrote {n_in} cells, expected {NCELL}")
    result["tools_used"].append("s5_routing/run_routing.py::prepare_vic_in")

    obs_cal = obs.loc[CAL0:CAL1]

    sim_ref = routed(V_DEFAULT)
    lag_ref = uh_lag(V_DEFAULT)
    sl = signed_lag(obs_cal, sim_ref.loc[CAL0:CAL1])
    ki_lag = observed_lag_days(obs_cal, sim_ref.loc[CAL0:CAL1])
    print(f"[s10] v={V_DEFAULT}: uh_lag={lag_ref:.2f} d, signed obs lag={sl['best_lag_days']} d "
          f"(r@best={sl['r_at_best_lag']:.3f}, r@0={sl['r_at_zero_lag']:.3f}, "
          f"NSE ceiling={sl['nse_ceiling_at_zero_lag']:.3f})", flush=True)

    # Probe v -> V_MIN FIRST: learn the lag CEILING the scheme can physically reach.
    lag_ceiling = uh_lag(V_MIN)
    print(f"[s10] ceiling probe v={V_MIN}: uh_lag={lag_ceiling:.2f} d", flush=True)

    target = lag_ref + sl["best_lag_days"]
    vel_note = ""
    if abs(sl["best_lag_days"]) <= 1:
        v_use = V_DEFAULT
        vel_note = (f"observed lag {sl['best_lag_days']:+d} d against uh_lag {lag_ref:.2f} d: "
                    f"the KI default v=1.5 m/s (tuned at THIS basin) already matches the "
                    f"observed travel time, so velocity was left untouched")
    elif target >= lag_ceiling:
        v_use = V_MIN
        vel_note = (f"target lag {target:.1f} d exceeds the scheme's ceiling {lag_ceiling:.1f} d "
                    f"(MAKE_UHM clips each kernel at LE*DT=48h and renormalises), so velocity is "
                    f"inert below ~{V_MIN} m/s; pinned at the calibration.yaml lower bound and the "
                    f"plateau reported rather than optimised")
    else:
        lo, hi = V_MIN, V_MAX                     # uh_lag decreases monotonically in v
        for _ in range(8):
            mid = 0.5 * (lo + hi)
            if uh_lag(mid) > target:
                lo = mid
            else:
                hi = mid
            if abs(uh_lag(mid) - target) < 0.25:
                break
        v_use = round(0.5 * (lo + hi), 3)
        vel_note = (f"sim was {sl['best_lag_days']:+d} d off; velocity IDENTIFIED by bisecting "
                    f"uh_lag(v) onto the observed lag target {target:.1f} d (cal window only, "
                    f"never on NSE) -> v={v_use} m/s, uh_lag={uh_lag(v_use):.2f} d")
    print(f"[s10] velocity in use: {v_use} m/s -- {vel_note}", flush=True)

    sim = routed(v_use)
    result["tools_used"] += ["s5_routing/run_routing.py::route (Lohmann route_1.0/src/rout)",
                             "s5_routing/run_routing.py::observed_lag_days"]

    # ---------------- D: score ----------------------------------------------
    paired = pd.concat([obs.loc[EVAL0:EVAL1].rename("obs"),
                        sim.loc[EVAL0:EVAL1].rename("sim")], axis=1).dropna()
    if len(paired) < 2:
        die("no temporal overlap between routed sim and obs")

    m = {k.lower(): float(v) for k, v in
         all_metrics(paired["obs"].values, paired["sim"].values).items()}
    cv = compute_calval_metrics(paired.index.values, paired["obs"].values,
                                paired["sim"].values,
                                cal_start=CAL0, cal_end=CAL1,
                                val_start=VAL0, val_end=VAL1)
    cal, val = cv["calibration"], cv["validation"]   # UPPERCASE keys
    period = f"{paired.index.min().date()}..{paired.index.max().date()}"
    print(f"[D] n={len(paired)} NSE={m['nse']:.3f} r={m['r']:.3f} KGE={m['kge']:.3f} "
          f"PBIAS={m['pbias']:+.1f}%", flush=True)

    result["metrics"].update({
        "nse": m["nse"], "kge": m["kge"], "pbias": m["pbias"], "r": m["r"],
        "period": period, "rmse": m["rmse"], "n_paired": len(paired),
        "obs_mean_m3s": float(paired["obs"].mean()),
        "sim_mean_m3s": float(paired["sim"].mean()),
        "nse_cal": cal["NSE"], "kge_cal": cal["KGE"], "pbias_cal": cal["PBIAS"], "r_cal": cal["r"],
        "nse_val": val["NSE"], "kge_val": val["KGE"], "pbias_val": val["PBIAS"], "r_val": val["r"],
    })
    result["routing"] = {
        "velocity_m_s": v_use, "diffusivity_m2_s": DIFF,
        "uh_lag_days_at_default_1.5": lag_ref,
        "uh_lag_days_in_use": uh_lag(v_use),
        "uh_lag_ceiling_days_at_v_min": lag_ceiling,
        "observed_signed_lag_days_cal": sl["best_lag_days"],
        "r_at_zero_lag_cal": sl["r_at_zero_lag"],
        "nse_ceiling_at_zero_lag_cal": sl["nse_ceiling_at_zero_lag"],
        "ki_observed_lag_days_nonneg_scan": ki_lag["best_lag_days"],
        "note": vel_note,
    }
    result["tools_used"] += ["ki_tools_common.metrics.all_metrics",
                             "validators.standard_calval.compute_calval_metrics"]

    # ---------------- water balance -----------------------------------------
    print("[D] water balance ...", flush=True)
    P, ET, RO, dS = [], [], [], []
    for fn in sorted(glob.glob(f"{VIC_RESULT}/bengbu_fluxes_*")):
        df = pd.read_csv(fn, sep=r"\s+", skiprows=2)
        df.columns = [c.lstrip("#") for c in df.columns]
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
    nyr = ndays / 365.25
    result["water_balance"] = {
        "status": wb["status"],
        "residual_pct": float(wb["residual_pct"]) if wb.get("residual_pct") is not None else None,
        "basin_mean_P_mm_yr": float(np.mean(P)) / nyr,
        "basin_mean_ET_mm_yr": float(np.mean(ET)) / nyr,
        "basin_mean_Q_mm_yr": float(np.mean(RO)) / nyr,
        "basin_mean_dS_mm": float(np.mean(dS)),
        "n_cells": len(P),
    }
    result["tools_used"].append("ki_tools_common.validation.validate_water_balance")
    result["basin"] = {"delineated_area_km2": delin["area"],
                       "published_area_km2": PUB_AREA_KM2,
                       "area_err_pct": area_err}

    result["status"] = "completed"
    result["notes"] = (
        f"VERIFIER at Bengbu (Huai River gauge 51080, published {PUB_AREA_KM2:.0f} km2 lowland, "
        f"heavily regulated outlet) -- a different climate/regime than the cold snowmelt-driven "
        f"Harbin real-case. Full KI chain with the REAL binaries: delineate_basin -> "
        f"build_routing_param.py -> vic_classic.exe ({NCELL} cells @0.25deg, CMFD 3-hourly, "
        f"1980-1990, 1980=spinup) -> Lohmann route_1.0/rout. Delineated {delin['area']:.0f} km2 "
        f"({area_err:.1f}% off published). UNCALIBRATED (binfilt=0.30 Ds=0.02 Dsmax=10 Ws=0.70, "
        f"VIC defaults verbatim) -- deliberately the SAME protocol as the uncalibrated Harbin "
        f"real-case. Routing velocity: {vel_note}. Scored {len(paired)} paired days ({period}): "
        f"NSE={m['nse']:.3f} r={m['r']:.3f} KGE={m['kge']:.3f} PBIAS={m['pbias']:+.1f}% "
        f"(obs_mean={paired['obs'].mean():.0f}, sim_mean={paired['sim'].mean():.0f} m3/s); "
        f"cal 1981-85 NSE={cal['NSE']:.3f}/PBIAS={cal['PBIAS']:+.1f}%, "
        f"val 1986-90 NSE={val['NSE']:.3f}/PBIAS={val['PBIAS']:+.1f}%. "
        f"Zero-lag r={sl['r_at_zero_lag']:.3f} on the cal window caps NSE at "
        f"{sl['nse_ceiling_at_zero_lag']:.3f} (NSE <= r^2). Water balance {wb['status']} "
        f"(residual {wb['residual_pct']:.2f}%); basin-mean P={np.mean(P)/nyr:.0f}, "
        f"ET={np.mean(ET)/nyr:.0f}, Q={np.mean(RO)/nyr:.0f} mm/yr. Lohmann routing renormalises "
        f"UH_S, so velocity moves timing and essentially never PBIAS: the volume bias reported "
        f"here is the honest uncalibrated forcing/soil bias, not a routing artefact. "
        f"obs_shape=point_time_series -> NSE/KGE/r/PBIAS all dag-valid; determining_metric=nse."
    )
    write_result()
    print("[DONE]", flush=True)
    print(json.dumps(result["metrics"], indent=2, default=float), flush=True)

except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    result["tools_failed"].append("runner exception")
    result["notes"] = "Runner crashed: " + traceback.format_exc()[-900:]
    write_result()
    sys.exit(1)
