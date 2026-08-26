#!/usr/bin/env python3
"""
VERIFY_2 run_and_score for BIOME-BGC at RISMA ON2 (Real-time In-situ Soil
Monitoring for Agriculture, South Nation watershed, Eastern Ontario, ~45.3N).

Cross-variable / cross-domain verifier: the Real-case (FI-Hyy) and verify_1
(US-MMS) validated daily GPP at flux towers. RISMA is a soil-moisture network
(no flux tower), so here we validate the OTHER declared BIOME-BGC observable:
single-bucket soil water (dag var 'soilw', validation_rank 10, point_time_series,
determining_metric NSE). The dag caveats that the single-bucket Clapp-Hornberger
column magnitude is NOT directly comparable to a multi-layer column storage, so we
compare VOLUMETRIC water content (model soilw / rooting-depth) against RISMA's
profile-mean VWC -- same unit, magnitude+dynamics comparable.

BIOME-BGC cannot run cropland (dt_021); RISMA ON2 is agricultural, so the
natural-vegetation analog C3GRASS PFT is used for the soil-water balance.

Pipeline (KI tools end-to-end):
  weather_complete.csv -> FLUXNET-format adapter -> convert_forcing_to_bgc
  -> select_ecophysiology (C3GRASS) -> generate_site_ini (spinup) -> run_bgc_spinup
  -> generate_site_ini (normal) -> run_bgc -> parse soilw (col 0).

RESUMABLE: skips spinup/normal whose output files already exist.
"""
import os, sys, json, subprocess, calendar, csv, math
from datetime import date

KI = "KISSPATH_KI_ROOT/BIOME_BGC/knowledge_infrastructure"
BGC = "KISSPATH_BINARIES/biome-bgc/bgc-src/bgc"
TOOLS = os.path.join(KI, "tools")
OBSDIR = "KISSPATH_OBS/risma_on2"
WX = os.path.join(OBSDIR, "weather_complete.csv")
OBS_VWC = os.path.join(OBSDIR, "obs_vwc_by_depth.csv")
OBS_SM = os.path.join(OBSDIR, "obs_soil_moisture.csv")
OUT = "KISSPATH_KI_ROOT/BIOME_BGC/detached/verify_2"
RESULT = os.path.join(OUT, "result.json")

# --- Site: RISMA ON2, South Nation watershed, Eastern Ontario clay plain ---
SITE = "rismaon2"
LAT, LON, ELEV = 45.27, -75.03, 78.0
PFT = "C3GRASS"          # natural-veg analog (BIOME-BGC cannot run cropland, dt_021)
START, END = 2015, 2019
NYEARS = END - START + 1
CO2_PPM = 405.0          # ~2015-2019 mean
SOIL_DEPTH_M = 1.0       # rooting-zone bucket depth
CAL_END = 2017           # cal 2015-2017, val 2018-2019

sys.path.insert(0, KI)
sys.path.insert(0, os.path.join(KI, "lib"))
from ki_tools_common.metrics import all_metrics
from ki_tools_common.soil_utils import lookup_hwsd


def run(cmd):
    print(">>", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout); print(p.stderr)
        raise RuntimeError(f"FAILED ({p.returncode}): {' '.join(cmd)}")
    return p.stdout


def esat_hpa(t):
    """Saturation vapor pressure (hPa) from temperature (deg C)."""
    return 6.108 * math.exp(17.27 * t / (t + 237.3))


def build_fluxnet_csv(path):
    """Adapt RISMA weather_complete.csv -> FLUXNET FULLSET_DD-style columns so
    the validated --source fluxnet path can be reused.
      TA_F_MDS_DAY = tmax, TA_F_MDS_NIGHT = tmin, P_F = precip_mm,
      SW_IN_F = srad (24h-mean W/m2, FLUXNET convention) = MJ/m2/d * 1e6/86400,
      VPD_F (hPa) = es(Tday) - RH/100*es(Tmean), daytime VPD.
    """
    avail = {}
    with open(WX) as f:
        for r in csv.DictReader(f):
            tmax = float(r["tmax_C"]); tmin = float(r["tmin_C"])
            tmean = 0.5 * (tmax + tmin)
            tday = tmin + 0.45 * (tmax - tmin)
            rh = float(r["rh_pct"])
            ea = (rh / 100.0) * esat_hpa(tmean)
            vpd_hpa = max(0.0, esat_hpa(tday) - ea)
            sw = float(r["srad_MJ_m2"]) * 1e6 / 86400.0
            y, m, d = (int(x) for x in r["date"].split("-"))
            avail[date(y, m, d)] = (tmax, tmin, float(r["precip_mm"]), vpd_hpa, sw)

    # Build a gap-free daily calendar START..END; fill missing days by ffill/bfill
    full = []
    d = date(START, 1, 1)
    last = None
    while d.year <= END:
        full.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    # forward pass
    rec = {}
    for dt in full:
        if dt in avail:
            last = avail[dt]
        if last is not None:
            rec[dt] = last
    # back pass for any leading gap
    last = None
    for dt in reversed(full):
        if dt in avail:
            last = avail[dt]
        elif dt not in rec and last is not None:
            rec[dt] = last
    n_filled = sum(1 for dt in full if dt not in avail)
    print(f"weather: {len(avail)} obs days, {n_filled} gap-filled to {len(full)} total", flush=True)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["TIMESTAMP", "TA_F_MDS_DAY", "TA_F_MDS_NIGHT",
                    "P_F", "VPD_F", "SW_IN_F"])
        for dt in full:
            tmax, tmin, p, vpd, sw = rec[dt]
            # gap-filled days: zero precip (no event evidence) to avoid spurious wetting
            if dt not in avail:
                p = 0.0
            w.writerow([dt.strftime("%Y%m%d"), f"{tmax:.2f}", f"{tmin:.2f}",
                        f"{p:.2f}", f"{vpd:.2f}", f"{sw:.2f}"])


def load_obs_vwc():
    """RISMA profile-mean volumetric water content (mean of 0-5/5/20/50 cm,
    dropping 0.0 missing-data sentinels)."""
    obs = {}
    with open(OBS_VWC) as f:
        for r in csv.DictReader(f):
            y, m, d = (int(x) for x in r["date"].split("-"))
            vals = []
            for k in ("vwc_0_5cm", "vwc_5cm", "vwc_20cm", "vwc_50cm"):
                v = float(r[k])
                if v > 0.01:          # 0.0 == missing
                    vals.append(v)
            if vals:
                obs[date(y, m, d)] = sum(vals) / len(vals)
    return obs


def load_obs_smcm():
    obs = {}
    with open(OBS_SM) as f:
        for r in csv.DictReader(f):
            y, m, d = (int(x) for x in r["date"].split("-"))
            obs[date(y, m, d)] = float(r["sm_cm"])
    return obs


def main():
    os.makedirs(OUT, exist_ok=True)
    for sub in ("metdata", "epc", "outputs", "restart"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)

    soil = lookup_hwsd(LAT, LON)
    sand, silt, clay = soil["sand"], soil["silt"], soil["clay"]
    tot = sand + silt + clay
    sand, silt, clay = [round(x * 100.0 / tot, 1) for x in (sand, silt, clay)]
    # fix rounding so they sum to exactly 100 (segfault guard dt_003)
    drift = round(100.0 - (sand + silt + clay), 1)
    silt = round(silt + drift, 1)
    print(f"Soil HWSD: sand={sand} silt={silt} clay={clay} ({soil['texture']})", flush=True)

    fx = os.path.join(OUT, "metdata", "risma_fluxnet.csv")
    epc = os.path.join(OUT, "epc", f"{SITE}.epc")
    met = os.path.join(OUT, "metdata", f"{SITE}.mtc43")
    spin_ini = os.path.join(OUT, "spinup.ini")
    norm_ini = os.path.join(OUT, "normal.ini")
    spin_prefix = os.path.join(OUT, "outputs", "spinup")
    norm_prefix = os.path.join(OUT, "outputs", "normal")
    restart = os.path.join(OUT, "restart", f"{SITE}.endpoint")
    dayout = norm_prefix + ".dayout.ascii"

    build_fluxnet_csv(fx)

    # S2 ecophysiology (grassland)
    run([sys.executable, os.path.join(TOOLS, "select_ecophysiology.py"),
         "--pft", PFT, "--output", epc])

    # S3 forcing via validated fluxnet path, then drop leap Feb-29 (365/yr)
    run([sys.executable, os.path.join(TOOLS, "convert_forcing_to_bgc.py"),
         "--forcing_file", fx, "--source", "fluxnet",
         "--lat", str(LAT), "--start_year", str(START), "--end_year", str(END),
         "--output", met])
    with open(met) as f:
        lines = f.readlines()
    header, body = lines[:4], lines[4:]
    kept = []
    for ln in body:
        parts = ln.split()
        if not parts:
            continue
        yr, yday = int(parts[0]), int(parts[1])
        if calendar.isleap(yr) and yday == 60:
            continue
        kept.append(ln)
    with open(met, "w") as f:
        f.writelines(header + kept)
    per = {}
    for ln in kept:
        per[int(ln.split()[0])] = per.get(int(ln.split()[0]), 0) + 1
    assert all(v == 365 for v in per.values()), per
    print(f"met file: {len(kept)} lines = {len(per)} yrs x 365", flush=True)

    common = ["--met_file", met, "--epc_file", epc, "--lat", str(LAT),
              "--elevation", str(ELEV), "--soil_depth", str(SOIL_DEPTH_M),
              "--sand", str(sand), "--silt", str(silt), "--clay", str(clay),
              "--start_year", str(START), "--n_met_years", str(NYEARS),
              "--co2_ppm", str(CO2_PPM)]

    # S5 spinup (grassland: ~1000-1500 yr)
    if not os.path.exists(restart):
        run([sys.executable, os.path.join(TOOLS, "generate_site_ini.py"),
             *common, "--output_prefix", spin_prefix, "--mode", "spinup",
             "--max_spinup_years", "4000", "--restart_file", restart,
             "--write_restart", "--output", spin_ini])
        run([sys.executable, os.path.join(TOOLS, "run_bgc_spinup.py"),
             "--bgc_binary", BGC, "--ini_file", spin_ini, "--timeout", "1800"])
    else:
        print("spinup restart exists, skipping", flush=True)

    # S6 normal
    if not os.path.exists(dayout):
        run([sys.executable, os.path.join(TOOLS, "generate_site_ini.py"),
             *common, "--output_prefix", norm_prefix, "--mode", "normal",
             "--restart_file", restart, "--read_restart", "--output", norm_ini])
        run([sys.executable, os.path.join(TOOLS, "run_bgc.py"),
             "--bgc_binary", BGC, "--ini_file", norm_ini, "--ascii",
             "--timeout", "600"])
    else:
        print("dayout exists, skipping normal run", flush=True)

    # --- Parse sim soilw (col 0, kgH2O/m2 == mm) -> VWC (/ depth) ---
    SOILW_COL = 0
    sim_soilw_mm = []
    with open(dayout) as f:
        for ln in f:
            p = ln.split()
            if len(p) >= 23:
                sim_soilw_mm.append(float(p[SOILW_COL]))
    sim_dates = []
    for yr in range(START, END + 1):
        d = date(yr, 1, 1)
        while d.year == yr:
            if not (calendar.isleap(yr) and d.month == 2 and d.day == 29):
                sim_dates.append(d)
            d = date.fromordinal(d.toordinal() + 1)
    assert len(sim_dates) == len(sim_soilw_mm), (len(sim_dates), len(sim_soilw_mm))
    depth_mm = SOIL_DEPTH_M * 1000.0
    sim_vwc = {dt: v / depth_mm for dt, v in zip(sim_dates, sim_soilw_mm)}
    sim_smcm = {dt: v / 10.0 for dt, v in zip(sim_dates, sim_soilw_mm)}  # bucket cm

    obs_vwc = load_obs_vwc()
    obs_smcm = load_obs_smcm()

    def metrics_for(sim, obs, d0, d1):
        o, s = [], []
        for dt in sorted(set(sim) & set(obs)):
            if d0 <= dt.year <= d1:
                o.append(obs[dt]); s.append(sim[dt])
        if len(o) < 10:
            return None, len(o)
        return all_metrics(o, s), len(o)

    m_all, n_all = metrics_for(sim_vwc, obs_vwc, START, END)
    m_cal, n_cal = metrics_for(sim_vwc, obs_vwc, START, CAL_END)
    m_val, n_val = metrics_for(sim_vwc, obs_vwc, CAL_END + 1, END)
    # secondary cross-check vs column sm_cm (magnitude not comparable per dag)
    m_sm, n_sm = metrics_for(sim_smcm, obs_smcm, START, END)

    mean_sim = sum(sim_vwc[d] for d in sim_vwc if START <= d.year <= END) / len(sim_vwc)
    ov = [obs_vwc[d] for d in obs_vwc if START <= d.year <= END]
    mean_obs = sum(ov) / len(ov)

    val_nse_str = f"{m_val['NSE']:.3f}" if m_val else "NA"
    wb = {"status": "N/A", "residual_pct": None,
          "note": "soil-water diagnostic; BIOME-BGC enforces internal water mass balance daily (check_balance)"}

    out = {
        "model_id": "BIOME_BGC",
        "this_location": "RISMA - Real-time In-situ Soil Monitoring for Agriculture (~36 stations, 2011-present)",
        "obs_source": "RISMA",
        "status": "completed",
        "tools_used": ["select_ecophysiology.py", "convert_forcing_to_bgc.py",
                       "generate_site_ini.py", "run_bgc_spinup.py", "run_bgc.py",
                       "ki_tools_common.soil_utils.lookup_hwsd",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": round(m_all["NSE"], 4), "kge": round(m_all["KGE"], 4),
            "pbias": round(m_all["PBIAS"], 3), "r": round(m_all["r"], 4),
            "rmse": round(m_all["RMSE"], 5),
            "nse_cal": round(m_cal["NSE"], 4) if m_cal else None,
            "kge_cal": round(m_cal["KGE"], 4) if m_cal else None,
            "nse_val": round(m_val["NSE"], 4) if m_val else None,
            "kge_val": round(m_val["KGE"], 4) if m_val else None,
            "pbias_val": round(m_val["PBIAS"], 3) if m_val else None,
            "n_days": n_all, "n_cal": n_cal, "n_val": n_val,
            "mean_sim_vwc": round(mean_sim, 4),
            "mean_obs_vwc": round(mean_obs, 4),
            "smcm_crosscheck": ({"nse": round(m_sm["NSE"], 4), "r": round(m_sm["r"], 4),
                                 "pbias": round(m_sm["PBIAS"], 2), "n": n_sm}
                                if m_sm else None),
            "variable": "soilw->VWC (volumetric, single-bucket)",
            "period": f"{START}-{END}",
            "period_calibration": f"{START}-{CAL_END}",
            "period_validation": f"{CAL_END+1}-{END}",
        },
        "water_balance": wb,
        "location": "RISMA ON2, South Nation watershed, Eastern Ontario (~45.3N, agricultural)",
        "notes": (
            f"BIOME-BGC 4.2 C3GRASS (natural-veg analog; cropland barred by dt_021) at RISMA ON2. "
            f"Single-bucket soil water 'soilw' (dag rank-10 observable) -> VWC vs RISMA profile-mean "
            f"VWC {START}-{END}: NSE {m_all['NSE']:.3f}/KGE {m_all['KGE']:.3f}/r {m_all['r']:.3f}/"
            f"PBIAS {m_all['PBIAS']:.1f}% (n={n_all}, val NSE {val_nse_str}). "
            f"Mean VWC sim {mean_sim:.3f} vs obs {mean_obs:.3f}. "
            f"Per dag caveat the single-bucket cm magnitude is not directly comparable to RISMA's deep "
            f"column sm_cm; comparison done in volumetric units. HWSD {soil['texture']}. Same KI tools as "
            f"Real-case FI-Hyy / verify_1 US-MMS but the OTHER declared observable (soil water, not GPP, "
            f"since RISMA has no flux tower). Spinup grassland; Feb-29 dropped (365/yr)."
        ),
    }
    with open(RESULT, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
